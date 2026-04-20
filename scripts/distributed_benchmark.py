#!/usr/bin/env python3
"""
分布式性能测试框架 - TCP vs QUIC 对比

支持:
  • 多种集群规模 (3, 5, 7 节点)
  • 同区域和跨区域部署
  • 系统指标与 Raft 指标采集
  • 详细的性能报告生成

Usage:
    python3 scripts/distributed_benchmark.py \
      --cluster-sizes 3,5,7 \
      --scenarios same-region,cross-region \
      --writes 500 \
      --duration 300 \
      --monitor \
      --out results
"""

import argparse
import csv
import json
import os
import random
import re
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def _node_sort_key(node_id: str) -> Tuple[int, str]:
    match = re.search(r"(\d+)$", node_id)
    if match:
        return (int(match.group(1)), node_id)
    return (sys.maxsize, node_id)


class AwsClusterManager:
    """管理 AWS 集群部署、服务启动和销毁。"""

    def __init__(self, cluster_size: int, scenario: str):
        self.cluster_size = cluster_size
        self.scenario = scenario
        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.deploy_dir = os.path.join(self.repo_root, "deploy", "terraform", scenario)
        self.cluster_env = os.path.join(
            self.repo_root, "deploy", f"cluster-{scenario}-{cluster_size}.env"
        )
        self.raft_binary = os.path.join(self.repo_root, "raftd-linux-amd64")
        self.tcp_binary = os.path.join(
            self.repo_root, "cmd", "tcp-server", "tcp-server-linux-amd64"
        )
        self.ssh_key_file = os.path.join(self.deploy_dir, "raft-key.pem")
        self.ssh_user = "ec2-user"
        self.nodes: Dict[str, str] = {}
        self.region_labels: List[str] = []

    def deploy(self) -> Dict[str, str]:
        """部署集群并启动 raftd + tcp-server。"""
        print(f"[*] 部署 {self.cluster_size} 节点 {self.scenario} 集群...", flush=True)

        self._ensure_linux_binaries()
        self._terraform_init()
        self._terraform_apply()
        self.nodes = self._parse_terraform_output()

        if not self.nodes:
            print("[!] Terraform 输出未包含节点信息")
            return {}

        if len(self.nodes) != self.cluster_size:
            print(
                f"[!] 节点数不匹配: 期望 {self.cluster_size}, 实际 {len(self.nodes)}",
                flush=True,
            )
            return {}

        self._save_cluster_config(self.nodes)
        self._wait_for_ssh_ready(self.nodes)
        self._upload_binaries(self.nodes)
        self._start_cluster_services(self.nodes)
        self._wait_for_cluster_ready(self.nodes)

        print(f"[+] 集群部署并启动完成: {list(self.nodes.keys())}", flush=True)
        return self.nodes

    def _ensure_linux_binaries(self):
        os.makedirs(os.path.dirname(self.tcp_binary), exist_ok=True)

        if not os.path.exists(self.raft_binary):
            print("[*] 构建 raftd Linux 二进制...", flush=True)
            self._run_cmd(
                ["go", "build", "-o", self.raft_binary, "./cmd/raftd"],
                cwd=self.repo_root,
                env=self._go_linux_env(),
            )

        if not os.path.exists(self.tcp_binary):
            print("[*] 构建 tcp-server Linux 二进制...", flush=True)
            self._run_cmd(
                ["go", "build", "-o", self.tcp_binary, "./cmd/tcp-server"],
                cwd=self.repo_root,
                env=self._go_linux_env(),
            )

    @staticmethod
    def _go_linux_env() -> Dict[str, str]:
        env = os.environ.copy()
        env["GOOS"] = "linux"
        env["GOARCH"] = "amd64"
        return env

    def _terraform_init(self):
        self._run_cmd(
            ["terraform", "init", "-input=false", "-upgrade"],
            cwd=self.deploy_dir,
        )

    def _terraform_apply(self):
        self._run_cmd(
            [
                "terraform",
                "apply",
                "-input=false",
                "-auto-approve",
                f"-var=cluster_size={self.cluster_size}",
            ],
            cwd=self.deploy_dir,
        )

    def _parse_terraform_output(self) -> Dict[str, str]:
        result = self._run_cmd(
            ["terraform", "output", "-json"],
            cwd=self.deploy_dir,
            capture_output=True,
        )
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"解析 terraform output 失败: {exc}") from exc

        node_ips = output.get("node_ips", {}).get("value", [])
        node_ids = output.get("node_ids", {}).get("value", [])
        if not node_ids:
            node_ids = [f"node{i}" for i in range(1, len(node_ips) + 1)]

        if len(node_ids) != len(node_ips):
            raise RuntimeError("Terraform 输出 node_ids 与 node_ips 数量不一致")

        key_file = output.get("ssh_key_file", {}).get("value")
        if key_file:
            self.ssh_key_file = key_file
        ssh_user = output.get("ssh_user", {}).get("value")
        if ssh_user:
            self.ssh_user = ssh_user

        self.region_labels = output.get("region_labels", {}).get("value", [])

        nodes = {}
        for node_id, ip in zip(node_ids, node_ips):
            nodes[node_id] = ip
        return dict(sorted(nodes.items(), key=lambda kv: _node_sort_key(kv[0])))

    def _save_cluster_config(self, nodes: Dict[str, str]):
        os.makedirs(os.path.dirname(self.cluster_env), exist_ok=True)
        with open(self.cluster_env, "w", encoding="utf-8") as f:
            f.write(f"SCENARIO={self.scenario}\n")
            f.write(f"CLUSTER_SIZE={self.cluster_size}\n")
            f.write(f"DEPLOYED_AT={datetime.now().isoformat()}\n")
            f.write(f"KEY_FILE={self.ssh_key_file}\n")
            f.write(f"SSH_USER={self.ssh_user}\n")
            if self.region_labels:
                f.write(f"REGION_LABELS={','.join(self.region_labels)}\n")
            for node_id, ip in nodes.items():
                f.write(f"{node_id.upper()}_IP={ip}\n")
        print(f"[+] 集群配置已保存: {self.cluster_env}", flush=True)

    def _wait_for_ssh_ready(self, nodes: Dict[str, str], retries: int = 36, wait_s: int = 5):
        for node_id, ip in nodes.items():
            print(f"[*] 等待 SSH 就绪: {node_id} ({ip})", flush=True)
            ready = False
            for _ in range(retries):
                result = self._ssh_cmd(ip, "true", check=False)
                if result.returncode == 0:
                    ready = True
                    break
                time.sleep(wait_s)
            if not ready:
                raise RuntimeError(f"SSH 超时: {node_id} ({ip})")
            print(f"[+] SSH 就绪: {node_id}", flush=True)

    def _upload_binaries(self, nodes: Dict[str, str]):
        print("[*] 上传二进制到所有节点...", flush=True)
        for node_id, ip in nodes.items():
            self._scp_cmd(self.raft_binary, ip, "~/raftd")
            self._scp_cmd(self.tcp_binary, ip, "~/tcp-server")
            print(f"[+] 上传完成: {node_id}", flush=True)

    def _start_cluster_services(self, nodes: Dict[str, str]):
        if not nodes:
            raise RuntimeError("空节点列表，无法启动服务")

        hb_timeout, el_timeout = self._raft_timeouts()
        ordered_nodes = list(nodes.items())
        bootstrap_id, bootstrap_ip = ordered_nodes[0]

        print(f"[*] 启动 bootstrap 节点: {bootstrap_id}", flush=True)
        self._start_node(
            node_id=bootstrap_id,
            ip=bootstrap_ip,
            join_addr=None,
            heartbeat_timeout=hb_timeout,
            election_timeout=el_timeout,
        )
        time.sleep(5)

        for node_id, ip in ordered_nodes[1:]:
            print(f"[*] 启动 follower 节点: {node_id}", flush=True)
            self._start_node(
                node_id=node_id,
                ip=ip,
                join_addr=f"{bootstrap_ip}:8001",
                heartbeat_timeout=hb_timeout,
                election_timeout=el_timeout,
            )

    def _wait_for_cluster_ready(self, nodes: Dict[str, str], timeout_s: int = 90):
        print("[*] 等待集群状态稳定...", flush=True)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            reachable = 0
            leaders = 0
            for ip in nodes.values():
                status = self._fetch_status(ip)
                if status is None:
                    continue
                reachable += 1
                if status.get("is_leader") or status.get("state") == "Leader":
                    leaders += 1
            if reachable == len(nodes) and leaders >= 1:
                print("[+] 集群状态已就绪", flush=True)
                return
            time.sleep(2)
        raise RuntimeError("集群未在超时内就绪")

    def _start_node(
        self,
        node_id: str,
        ip: str,
        join_addr: Optional[str],
        heartbeat_timeout: str,
        election_timeout: str,
    ):
        join_arg = ""
        if join_addr:
            join_arg = f" -join {join_addr} -join-retries 20"
        script = f"""set -e
pkill -f raftd >/dev/null 2>&1 || true
pkill -f tcp-server >/dev/null 2>&1 || true
sleep 1
chmod +x ~/raftd ~/tcp-server
nohup ~/tcp-server -bind 0.0.0.0:9001 > ~/tcp-server.log 2>&1 &
echo $! > ~/tcp-server.pid
nohup ~/raftd \\
  -id {node_id} \\
  -bind 0.0.0.0:7001 \\
  -advertise {ip}:7001 \\
  -http 0.0.0.0:8001 \\
  -heartbeat-timeout {heartbeat_timeout} \\
  -election-timeout {election_timeout}{join_arg} \\
  > ~/raftd.log 2>&1 &
echo $! > ~/raftd.pid
"""
        self._ssh_cmd(ip, "bash -s", stdin=script)

    def _raft_timeouts(self) -> Tuple[str, str]:
        if self.scenario == "cross-region":
            return ("1s", "2s")
        return ("150ms", "300ms")

    def _fetch_status(self, ip: str) -> Optional[Dict]:
        url = f"http://{ip}:8001/status"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def teardown(self):
        """销毁集群。"""
        print(f"[*] 销毁 {self.cluster_size} 节点 {self.scenario} 集群...", flush=True)
        self._run_cmd(
            [
                "terraform",
                "destroy",
                "-input=false",
                "-auto-approve",
                f"-var=cluster_size={self.cluster_size}",
            ],
            cwd=self.deploy_dir,
            check=False,
        )
        print("[+] 集群已销毁", flush=True)

    def _run_cmd(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            check=check,
            text=True,
            capture_output=capture_output,
        )

    def _ssh_cmd(
        self,
        ip: str,
        remote_cmd: str,
        stdin: Optional[str] = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = [
            "ssh",
            "-i",
            self.ssh_key_file,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            f"{self.ssh_user}@{ip}",
            remote_cmd,
        ]
        return subprocess.run(
            cmd,
            input=stdin,
            text=True,
            check=check,
            capture_output=True,
        )

    def _scp_cmd(self, local_file: str, ip: str, remote_file: str):
        cmd = [
            "scp",
            "-i",
            self.ssh_key_file,
            "-o",
            "StrictHostKeyChecking=no",
            local_file,
            f"{self.ssh_user}@{ip}:{remote_file}",
        ]
        subprocess.run(cmd, text=True, check=True, capture_output=True)


class MetricsCollector:
    """收集系统与 Raft 指标。"""

    def __init__(self, nodes: Dict[str, str], ssh_key: str, ssh_user: str = "ec2-user"):
        self.nodes = nodes
        self.ssh_key = ssh_key
        self.ssh_user = ssh_user

    def collect_baseline(self) -> Dict:
        baseline = {}
        for node_id, ip in self.nodes.items():
            baseline[node_id] = {
                "cpu": self._get_cpu(ip),
                "memory": self._get_memory(ip),
                "network": self._get_network(ip),
                "disk": self._get_disk(ip),
            }
        return baseline

    def collect_raft_metrics(self) -> Dict:
        raft_metrics = {}
        for node_id, ip in self.nodes.items():
            try:
                with urllib.request.urlopen(f"http://{ip}:8001/status", timeout=5) as resp:
                    if resp.status != 200:
                        continue
                    status = json.loads(resp.read().decode("utf-8"))
                    raft_metrics[node_id] = {
                        "is_leader": status.get("is_leader", False),
                        "term": status.get("term", 0),
                        "committed_index": status.get("committed_index", 0),
                        "last_applied": status.get("last_applied", 0),
                    }
            except Exception as exc:
                print(f"[!] 无法收集 {node_id} 的 Raft 指标: {exc}")
        return raft_metrics

    def _ssh_exec(self, ip: str, remote_cmd: str, timeout: int = 5) -> str:
        cmd = [
            "ssh",
            "-i",
            self.ssh_key,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=3",
            f"{self.ssh_user}@{ip}",
            remote_cmd,
        ]
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else ""

    def _get_cpu(self, ip: str) -> float:
        output = self._ssh_exec(ip, "top -bn1 | grep Cpu | awk '{print $2}'")
        try:
            return float(output.rstrip("%")) if output else 0.0
        except ValueError:
            return 0.0

    def _get_memory(self, ip: str) -> Dict[str, float]:
        output = self._ssh_exec(ip, "free -h | grep Mem | awk '{print $3, $2}'")
        try:
            used, total = output.split()
            return {
                "used_gb": float(used.rstrip("G")),
                "total_gb": float(total.rstrip("G")),
            }
        except Exception:
            return {"used_gb": 0.0, "total_gb": 0.0}

    def _get_network(self, ip: str) -> Dict[str, float]:
        output = self._ssh_exec(ip, "cat /proc/net/dev | grep eth0")
        try:
            parts = output.split()
            return {"rx_bytes": float(parts[1]), "tx_bytes": float(parts[9])}
        except Exception:
            return {"rx_bytes": 0.0, "tx_bytes": 0.0}

    def _get_disk(self, ip: str) -> Dict[str, float]:
        output = self._ssh_exec(ip, "df -h / | tail -1 | awk '{print $3, $2}'")
        try:
            used, total = output.split()
            return {
                "used_gb": float(used.rstrip("G")),
                "total_gb": float(total.rstrip("G")),
            }
        except Exception:
            return {"used_gb": 0.0, "total_gb": 0.0}


class DistributedBenchmark:
    """分布式基准测试执行器。"""

    def __init__(self, nodes: Dict[str, str], cluster_size: int, scenario: str):
        self.nodes = nodes
        self.cluster_size = cluster_size
        self.scenario = scenario
        self.leader_ip: Optional[str] = None

    def run_benchmark(self, writes: int, duration: int, protocol: str = "quic") -> Dict:
        print(
            f"\n[*] 运行 {protocol.upper()} 基准测试 ({self.cluster_size} 节点, {self.scenario})...",
            flush=True,
        )

        if not self._find_leader():
            print("[!] 无法找到 leader，跳过该轮", flush=True)
            return {}

        target_ip = self.leader_ip or next(iter(self.nodes.values()))
        benchmark_data = self._run_write_benchmark(writes, protocol, target_ip)
        latency_data = self._run_latency_benchmark(duration, protocol, target_ip)
        read_data = self._run_read_benchmark(max(writes // 2, 1), protocol, target_ip)

        return {
            "protocol": protocol,
            "cluster_size": self.cluster_size,
            "scenario": self.scenario,
            "write_throughput": benchmark_data.get("throughput", 0),
            "write_p50_ms": latency_data.get("p50", 0),
            "write_p95_ms": latency_data.get("p95", 0),
            "write_p99_ms": latency_data.get("p99", 0),
            "read_throughput": read_data.get("throughput", 0),
            "write_errors": benchmark_data.get("errors", 0),
            "read_errors": read_data.get("errors", 0),
            "timestamp": datetime.now().isoformat(),
        }

    def _find_leader(self, retries: int = 30, wait_s: float = 1.0) -> bool:
        for _ in range(retries):
            for node_id, ip in self.nodes.items():
                status, _, body = self._http_request("GET", ip, 8001, "/status", None, timeout=3)
                if status != 200 or not body:
                    continue
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if payload.get("is_leader") or payload.get("state") == "Leader":
                    self.leader_ip = ip
                    print(f"[+] 发现 leader: {node_id} ({ip})", flush=True)
                    return True
            time.sleep(wait_s)

        if self.nodes:
            self.leader_ip = next(iter(self.nodes.values()))
            print(f"[!] 未检测到 leader，回退到首节点: {self.leader_ip}", flush=True)
        return self.leader_ip is not None

    def _run_write_benchmark(self, writes: int, protocol: str, ip: str) -> Dict:
        port = 8001 if protocol == "quic" else 9001
        latencies: List[float] = []
        errors = 0
        start = time.monotonic()

        for i in range(writes):
            key = f"bench_{protocol}_{i}"
            value = "".join(random.choices(string.ascii_letters + string.digits, k=32))
            status, elapsed_ms, _ = self._http_request(
                "POST",
                ip,
                port,
                "/set",
                {"key": key, "value": value},
                timeout=10,
            )
            if status == 200:
                latencies.append(elapsed_ms)
            else:
                errors += 1

        elapsed = time.monotonic() - start
        return {
            "throughput": len(latencies) / elapsed if elapsed > 0 else 0,
            "latencies": latencies,
            "errors": errors,
        }

    def _run_latency_benchmark(self, duration: int, protocol: str, ip: str) -> Dict:
        port = 8001 if protocol == "quic" else 9001
        latencies: List[float] = []
        start = time.monotonic()

        while time.monotonic() - start < duration:
            key = f"latency_{protocol}_{int(time.time() * 1000)}"
            status, elapsed_ms, _ = self._http_request(
                "POST",
                ip,
                port,
                "/set",
                {"key": key, "value": "test_value"},
                timeout=10,
            )
            if status == 200:
                latencies.append(elapsed_ms)
            time.sleep(0.1)

        if not latencies:
            return {"p50": 0, "p95": 0, "p99": 0}

        latencies.sort()
        return {
            "p50": self._percentile(latencies, 0.50),
            "p95": self._percentile(latencies, 0.95),
            "p99": self._percentile(latencies, 0.99),
        }

    def _run_read_benchmark(self, reads: int, protocol: str, ip: str) -> Dict:
        port = 8001 if protocol == "quic" else 9001
        seed_keys = [f"read_key_{i}" for i in range(min(10, reads))]
        for key in seed_keys:
            self._http_request("POST", ip, port, "/set", {"key": key, "value": "seed_value"})

        latencies: List[float] = []
        errors = 0
        start = time.monotonic()

        if not seed_keys:
            seed_keys = ["read_key_0"]

        for i in range(reads):
            key = seed_keys[i % len(seed_keys)]
            status, elapsed_ms, _ = self._http_request(
                "GET",
                ip,
                port,
                "/get",
                {"key": key},
                timeout=10,
            )
            if status in (200, 404):
                latencies.append(elapsed_ms)
            else:
                errors += 1

        elapsed = time.monotonic() - start
        return {
            "throughput": len(latencies) / elapsed if elapsed > 0 else 0,
            "latencies": latencies,
            "errors": errors,
        }

    @staticmethod
    def _percentile(values: List[float], ratio: float) -> float:
        idx = min(int((len(values) - 1) * ratio), len(values) - 1)
        return values[idx]

    @staticmethod
    def _http_request(
        method: str,
        ip: str,
        port: int,
        path: str,
        params: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ) -> Tuple[Optional[int], float, str]:
        query = urllib.parse.urlencode(params or {})
        url = f"http://{ip}:{port}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url=url, method=method)

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                status = resp.getcode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            status = exc.code
        except Exception:
            return (None, 0.0, "")
        elapsed_ms = (time.perf_counter() - start) * 1000
        return (status, elapsed_ms, body)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--cluster-sizes",
        default="3,5,7",
        help="comma-separated cluster sizes to test",
    )
    parser.add_argument(
        "--scenarios",
        default="same-region,cross-region",
        help="comma-separated deployment scenarios",
    )
    parser.add_argument(
        "--writes",
        type=int,
        default=500,
        help="number of writes per benchmark",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="benchmark duration in seconds",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="collect detailed system metrics",
    )
    parser.add_argument(
        "--ssh-key",
        default="deploy/terraform/same-region/raft-key.pem",
        help="SSH key path for metric collection (used with --skip-deploy)",
    )
    parser.add_argument("--out", default="results", help="output directory")
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="skip cluster deployment (use existing)",
    )
    parser.add_argument("--skip-tcp", action="store_true", help="skip TCP benchmarks")
    parser.add_argument("--skip-quic", action="store_true", help="skip QUIC benchmarks")

    args = parser.parse_args()

    cluster_sizes = [int(c.strip()) for c in args.cluster_sizes.split(",") if c.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    if any(size < 3 for size in cluster_sizes):
        raise SystemExit("cluster size must be >= 3")
    if args.skip_tcp and args.skip_quic:
        raise SystemExit("cannot skip both tcp and quic benchmarks")

    os.makedirs(args.out, exist_ok=True)

    all_results: List[Dict] = []

    print("=" * 80)
    print("分布式性能测试框架 - TCP vs QUIC 对比")
    print("=" * 80)
    print(f"集群规模: {cluster_sizes}")
    print(f"场景: {scenarios}")
    print(f"写操作: {args.writes}")
    print(f"监控: {'启用' if args.monitor else '禁用'}")
    print("=" * 80)

    for scenario in scenarios:
        for cluster_size in cluster_sizes:
            manager = AwsClusterManager(cluster_size, scenario)
            collector = None
            try:
                if not args.skip_deploy:
                    nodes = manager.deploy()
                else:
                    env_kv = _load_env_file(manager.cluster_env)
                    nodes = _load_nodes_from_env(env_kv)
                    manager.ssh_key_file = env_kv.get("KEY_FILE", args.ssh_key)
                    manager.ssh_user = env_kv.get("SSH_USER", "ec2-user")

                if not nodes:
                    print(f"[!] 无法获取 {cluster_size} 节点 {scenario} 集群信息", flush=True)
                    continue

                if args.monitor:
                    collector = MetricsCollector(nodes, manager.ssh_key_file, manager.ssh_user)
                    collector.collect_baseline()
                    print("[+] 基线指标已收集", flush=True)

                benchmark = DistributedBenchmark(nodes, cluster_size, scenario)

                if not args.skip_quic:
                    quic_result = benchmark.run_benchmark(args.writes, args.duration, "quic")
                    if quic_result:
                        all_results.append(quic_result)

                if not args.skip_tcp:
                    tcp_result = benchmark.run_benchmark(args.writes, args.duration, "tcp")
                    if tcp_result:
                        all_results.append(tcp_result)

                if collector is not None:
                    collector.collect_raft_metrics()
                    print("[+] Raft 指标已收集", flush=True)

            except Exception as exc:
                print(f"[!] 测试失败: {exc}", flush=True)
            finally:
                if not args.skip_deploy:
                    manager.teardown()

    _save_results(all_results, args.out)
    _generate_report(all_results, args.out)

    print(f"\n[+] 所有测试完成，结果保存到 {args.out}", flush=True)


def _load_env_file(config_file: str) -> Dict[str, str]:
    env = {}
    if not os.path.exists(config_file):
        return env
    with open(config_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


def _load_nodes_from_env(env: Dict[str, str]) -> Dict[str, str]:
    nodes = {}
    for key, value in env.items():
        if key.endswith("_IP"):
            node_id = key[:-3].lower()
            nodes[node_id] = value
    return dict(sorted(nodes.items(), key=lambda kv: _node_sort_key(kv[0])))


def _save_results(results: List[Dict], output_dir: str):
    if not results:
        print("[!] 无可保存结果", flush=True)
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(output_dir, f"distributed_benchmark_{ts}.csv")

    fieldnames = [
        "protocol",
        "cluster_size",
        "scenario",
        "write_throughput",
        "write_p50_ms",
        "write_p95_ms",
        "write_p99_ms",
        "read_throughput",
        "write_errors",
        "read_errors",
        "timestamp",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"[+] 结果保存到 {csv_path}", flush=True)


def _generate_report(results: List[Dict], output_dir: str):
    if not results:
        print("[!] 无可生成报告的数据", flush=True)
        return

    grouped: Dict[Tuple[str, str], List[Dict]] = {}
    for row in results:
        key = (row["protocol"], row["scenario"])
        grouped.setdefault(key, []).append(row)

    summary: List[str] = []
    summary.append("# 分布式性能测试报告\n")
    summary.append(f"生成时间: {datetime.now().isoformat()}\n\n")

    for (protocol, scenario), rows in sorted(grouped.items()):
        summary.append(f"## {protocol.upper()} - {scenario}\n\n")
        summary.append("| 集群规模 | 写吞吐(ops/s) | 写p99(ms) | 读吞吐(ops/s) | 写错误 |\n")
        summary.append("|---------|-------------|---------|---------------|-------|\n")

        for row in sorted(rows, key=lambda x: x["cluster_size"]):
            summary.append(
                f"| {row['cluster_size']} | {row['write_throughput']:.1f} | "
                f"{row['write_p99_ms']:.2f} | {row['read_throughput']:.1f} | "
                f"{row.get('write_errors', 0)} |\n"
            )
        summary.append("\n")

    summary.append("## TCP vs QUIC 对比\n\n")
    same_region_quic = [
        r for r in results if r["protocol"] == "quic" and r["scenario"] == "same-region"
    ]
    same_region_tcp = [
        r for r in results if r["protocol"] == "tcp" and r["scenario"] == "same-region"
    ]

    if same_region_quic and same_region_tcp:
        for quic_row in same_region_quic:
            tcp_row = next(
                (t for t in same_region_tcp if t["cluster_size"] == quic_row["cluster_size"]),
                None,
            )
            if not tcp_row:
                continue
            tput_ratio = (
                quic_row["write_throughput"] / tcp_row["write_throughput"]
                if tcp_row["write_throughput"] > 0
                else 0
            )
            latency_ratio = (
                quic_row["write_p99_ms"] / tcp_row["write_p99_ms"]
                if tcp_row["write_p99_ms"] > 0
                else 0
            )

            summary.append(f"### {quic_row['cluster_size']} 节点\n")
            summary.append(f"- QUIC 吞吐: {quic_row['write_throughput']:.1f} ops/s\n")
            summary.append(f"- TCP 吞吐: {tcp_row['write_throughput']:.1f} ops/s\n")
            summary.append(f"- 吞吐比 (QUIC/TCP): {tput_ratio:.2f}x\n")
            summary.append(f"- QUIC p99: {quic_row['write_p99_ms']:.2f} ms\n")
            summary.append(f"- TCP p99: {tcp_row['write_p99_ms']:.2f} ms\n")
            summary.append(f"- 延迟比 (QUIC/TCP): {latency_ratio:.2f}x\n\n")

    report_path = os.path.join(output_dir, "distributed_benchmark_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(summary)
    print(f"[+] 报告保存到 {report_path}", flush=True)


if __name__ == "__main__":
    main()
