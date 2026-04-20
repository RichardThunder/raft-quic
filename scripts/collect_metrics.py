#!/usr/bin/env python3
"""
监控指标收集工具 - 实时采集系统和应用性能数据

支持:
  • 系统指标: CPU, 内存, 网络, 磁盘 I/O
  • 应用指标: Raft term, leader, committed index
  • 网络指标: 延迟, 丢包, 吞吐量
  • 周期采集和实时监控

Usage:
    python3 scripts/collect_metrics.py \\
      --nodes node1=10.0.0.1,node2=10.0.0.2,node3=10.0.0.3 \\
      --interval 5 \\
      --duration 300 \\
      --ssh-key /path/to/key.pem \\
      --out metrics
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class MetricsCollector:
    """实时收集各种性能指标"""

    def __init__(self, nodes: Dict[str, str], ssh_key: str):
        self.nodes = nodes
        self.ssh_key = ssh_key
        self.metrics_history = defaultdict(list)
        self.running = False

    def collect_system_metrics(self, node_id: str, ip: str) -> Dict:
        """收集系统级指标"""
        metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

        # CPU使用率
        try:
            cpu = self._ssh_exec(ip, "top -bn1 | grep Cpu | awk '{print $2}' | cut -d'%' -f1")
            metrics["cpu_usage_percent"] = float(cpu) if cpu else 0
        except:
            metrics["cpu_usage_percent"] = 0

        # 内存使用率
        try:
            mem_cmd = "free | grep Mem | awk '{printf \"%.1f\", ($3/$2)*100}'"
            mem = self._ssh_exec(ip, mem_cmd)
            metrics["memory_usage_percent"] = float(mem) if mem else 0
        except:
            metrics["memory_usage_percent"] = 0

        # 网络接口统计 (eth0)
        try:
            net_cmd = "cat /proc/net/dev | grep eth0 | awk '{print $2, $10}'"
            net = self._ssh_exec(ip, net_cmd)
            if net:
                rx, tx = net.split()
                metrics["network_rx_bytes"] = int(rx)
                metrics["network_tx_bytes"] = int(tx)
        except:
            metrics["network_rx_bytes"] = 0
            metrics["network_tx_bytes"] = 0

        # 进程统计 (raftd)
        try:
            ps_cmd = "ps aux | grep raftd | grep -v grep | awk '{print $3, $6}'"
            ps = self._ssh_exec(ip, ps_cmd)
            if ps:
                cpu, rss = ps.split()
                metrics["raftd_cpu_percent"] = float(cpu)
                metrics["raftd_rss_mb"] = float(rss) / 1024
        except:
            metrics["raftd_cpu_percent"] = 0
            metrics["raftd_rss_mb"] = 0

        # 磁盘I/O (iostat)
        try:
            io_cmd = "iostat -dx 1 2 | tail -1 | awk '{print $4, $5}' | head -1"
            io = self._ssh_exec(ip, io_cmd)
            if io:
                parts = io.split()
                if len(parts) >= 2:
                    metrics["disk_read_kb_s"] = float(parts[0])
                    metrics["disk_write_kb_s"] = float(parts[1])
        except:
            metrics["disk_read_kb_s"] = 0
            metrics["disk_write_kb_s"] = 0

        # 系统负载
        try:
            load_cmd = "cat /proc/loadavg | awk '{print $1, $2, $3}'"
            load = self._ssh_exec(ip, load_cmd)
            if load:
                l1, l5, l15 = load.split()
                metrics["load_average_1m"] = float(l1)
                metrics["load_average_5m"] = float(l5)
                metrics["load_average_15m"] = float(l15)
        except:
            metrics["load_average_1m"] = 0
            metrics["load_average_5m"] = 0
            metrics["load_average_15m"] = 0

        return metrics

    def collect_raft_metrics(self, node_id: str, ip: str, port: int = 8001) -> Dict:
        """收集Raft协议级指标"""
        metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

        try:
            cmd = f"curl -s http://{ip}:{port}/status"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                status = json.loads(result.stdout)
                metrics["is_leader"] = status.get("is_leader", False)
                metrics["current_term"] = status.get("term", 0)
                metrics["committed_index"] = status.get("committed_index", 0)
                metrics["last_applied"] = status.get("last_applied", 0)
                metrics["last_log_index"] = status.get("last_log_index", 0)
                metrics["peers_count"] = status.get("peers_count", 0)
                metrics["replication_lag"] = status.get("replication_lag", 0)

                # 新增优先级1指标
                metrics["leader_changes"] = status.get("leader_changes", 0)
                metrics["election_triggered"] = status.get("election_triggered", 0)
                metrics["last_election_duration_ms"] = status.get("last_election_duration_ms", 0)
                metrics["heartbeat_timeouts"] = status.get("heartbeat_timeouts", 0)

                # 优先级2指标
                metrics["entries_per_second"] = status.get("entries_per_second", 0)
        except:
            pass

        return metrics

    def collect_network_metrics(self, node_id: str, ip: str) -> Dict:
        """收集网络性能指标"""
        metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

        # 优先级2: 修复RTT测量 - 测量到其他节点的延迟（而不是ping自己）
        # 这里假设我们已经有leader_ip，实际使用中可以从discovery获取
        if len(self.nodes) > 1:
            # 选择第一个非自己的节点作为目标
            target_ip = None
            for nid, nip in self.nodes.items():
                if nid != node_id:
                    target_ip = nip
                    break

            if target_ip:
                try:
                    # 测量到其他节点的平均RTT和抖动
                    cmd = f"ping -c 5 -q {target_ip} | grep 'rtt min/avg/max/stddev' | awk -F'/' '{{print $4, $5}}'"
                    result = subprocess.run(
                        f"ssh -i {self.ssh_key} -o ConnectTimeout=3 ec2-user@{ip} '{cmd}'",
                        shell=True, capture_output=True, text=True, timeout=15
                    )

                    if result.returncode == 0 and result.stdout:
                        parts = result.stdout.strip().split()
                        if len(parts) >= 2:
                            metrics["rtt_avg_ms"] = float(parts[0])
                            metrics["rtt_stddev_ms"] = float(parts[1])
                except:
                    pass

                # 包丢失率 (ping 100次)
                try:
                    loss_cmd = f"ping -c 100 -q {target_ip} | grep 'loss' | awk '{{print $6}}' | tr -d '%'"
                    result = subprocess.run(
                        f"ssh -i {self.ssh_key} -o ConnectTimeout=3 ec2-user@{ip} '{loss_cmd}'",
                        shell=True, capture_output=True, text=True, timeout=120
                    )

                    if result.returncode == 0 and result.stdout:
                        metrics["packet_loss_percent"] = float(result.stdout.strip())
                except:
                    metrics["packet_loss_percent"] = 0

        # 网络连接数
        try:
            netstat_cmd = "ss -tn state established | wc -l"
            result = subprocess.run(
                f"ssh -i {self.ssh_key} -o ConnectTimeout=3 ec2-user@{ip} '{netstat_cmd}'",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                metrics["established_connections"] = int(result.stdout.strip())
        except:
            metrics["established_connections"] = 0

        # 优先级2: TCP重传率
        try:
            # 获取TCP重传总数
            tcp_stats_cmd = "cat /proc/net/snmp 2>/dev/null | grep Tcp | tail -1 | awk '{print $13}'"
            result = subprocess.run(
                f"ssh -i {self.ssh_key} -o ConnectTimeout=3 ec2-user@{ip} '{tcp_stats_cmd}'",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                metrics["tcp_retransmits_total"] = int(result.stdout.strip())
        except:
            metrics["tcp_retransmits_total"] = 0

        return metrics

    def collect_benchmark_metrics(self, node_id: str, ip: str, protocol: str = "quic") -> Dict:
        """收集基准测试期间的应用指标"""
        metrics = {"timestamp": datetime.now().isoformat(), "node": node_id, "protocol": protocol}

        port = 8001 if protocol == "quic" else 9001

        try:
            # 测试单次操作延迟
            cmd = f"curl -s -X POST 'http://{ip}:{port}/set?key=test&value=test' -w '%{{time_total}}' -o /dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                metrics["operation_latency_ms"] = float(result.stdout) * 1000
        except:
            metrics["operation_latency_ms"] = 0

        return metrics

    def _ssh_exec(self, ip: str, cmd: str, timeout: int = 5) -> str:
        """执行SSH命令"""
        full_cmd = f"ssh -i {self.ssh_key} -o ConnectTimeout=3 ec2-user@{ip} '{cmd}'"
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else ""

    def start_monitoring(self, interval: int, duration: int, protocols: List[str] = None):
        """开始监控线程"""
        if protocols is None:
            protocols = ["quic"]

        def monitor_loop():
            end_time = time.time() + duration

            while time.time() < end_time and self.running:
                for node_id, ip in self.nodes.items():
                    # 系统指标
                    sys_metrics = self.collect_system_metrics(node_id, ip)
                    self.metrics_history[f"{node_id}_system"].append(sys_metrics)

                    # Raft指标
                    raft_metrics = self.collect_raft_metrics(node_id, ip)
                    self.metrics_history[f"{node_id}_raft"].append(raft_metrics)

                    # 网络指标
                    net_metrics = self.collect_network_metrics(node_id, ip)
                    self.metrics_history[f"{node_id}_network"].append(net_metrics)

                    # 基准测试指标
                    for protocol in protocols:
                        bench_metrics = self.collect_benchmark_metrics(node_id, ip, protocol)
                        self.metrics_history[f"{node_id}_{protocol}_bench"].append(bench_metrics)

                time.sleep(interval)

        self.running = True
        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()
        return thread

    def stop_monitoring(self):
        """停止监控"""
        self.running = False

    def save_metrics(self, output_dir: str):
        """保存所有采集的指标到CSV文件"""
        os.makedirs(output_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        for metric_type, data in self.metrics_history.items():
            if not data:
                continue

            # 确定CSV列
            fieldnames = set()
            for row in data:
                fieldnames.update(row.keys())
            fieldnames = sorted(list(fieldnames))

            # 写入CSV
            csv_path = os.path.join(output_dir, f"metrics_{metric_type}_{ts}.csv")
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row in data:
                    writer.writerow(row)

            print(f"[+] 指标已保存: {csv_path}")

    def get_summary(self) -> Dict:
        """生成指标摘要统计"""
        summary = {}

        for metric_type, data in self.metrics_history.items():
            if not data:
                continue

            # 提取数值字段
            numeric_fields = defaultdict(list)
            for row in data:
                for key, value in row.items():
                    if isinstance(value, (int, float)):
                        numeric_fields[key].append(value)

            # 计算统计量
            for key, values in numeric_fields.items():
                if values:
                    summary[f"{metric_type}_{key}"] = {
                        "min": min(values),
                        "max": max(values),
                        "avg": sum(values) / len(values),
                        "count": len(values),
                    }

        return summary


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("--nodes", required=True,
                       help="comma-separated node list (node1=ip1,node2=ip2,...)")
    parser.add_argument("--interval", type=int, default=5,
                       help="collection interval in seconds")
    parser.add_argument("--duration", type=int, default=300,
                       help="total monitoring duration in seconds")
    parser.add_argument("--ssh-key", default="deploy/terraform/same-region/raft-key.pem",
                       help="SSH key path for remote execution")
    parser.add_argument("--protocols", default="quic",
                       help="comma-separated protocols to monitor (quic,tcp)")
    parser.add_argument("--out", default="metrics",
                       help="output directory for metrics")

    args = parser.parse_args()

    # 解析节点列表
    nodes = {}
    for node_spec in args.nodes.split(","):
        node_id, ip = node_spec.split("=")
        nodes[node_id] = ip

    protocols = args.protocols.split(",")

    print("=" * 70)
    print("监控指标收集工具")
    print("=" * 70)
    print(f"节点: {list(nodes.keys())}")
    print(f"采集间隔: {args.interval}s")
    print(f"监控时长: {args.duration}s")
    print(f"协议: {protocols}")
    print("=" * 70)

    collector = MetricsCollector(nodes, args.ssh_key)

    # 启动监控
    print(f"\n[*] 启动监控线程...")
    monitor_thread = collector.start_monitoring(args.interval, args.duration, protocols)

    print(f"[+] 监控运行中... (Ctrl+C 中止)")

    try:
        monitor_thread.join()
    except KeyboardInterrupt:
        print("\n[*] 收到中止信号，停止监控...")
        collector.stop_monitoring()
        monitor_thread.join()

    # 保存结果
    print(f"\n[*] 保存采集数据...")
    collector.save_metrics(args.out)

    # 生成摘要
    summary = collector.get_summary()

    # 打印摘要报告
    print(f"\n{'='*70}")
    print("监控摘要统计")
    print(f"{'='*70}")

    for key, stats in sorted(summary.items()):
        print(f"{key}:")
        print(f"  最小值: {stats['min']:.2f}")
        print(f"  最大值: {stats['max']:.2f}")
        print(f"  平均值: {stats['avg']:.2f}")
        print(f"  样本数: {stats['count']}")

    print(f"\n[+] 监控完成，数据保存到 {args.out}")


if __name__ == "__main__":
    main()
