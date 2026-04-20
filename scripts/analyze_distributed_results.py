#!/usr/bin/env python3
"""
分布式性能测试结果分析工具

功能:
  • 解析所有采集的性能指标
  • 生成对比分析报告
  • 创建可视化对比图表
  • 输出性能趋势分析

Usage:
    python3 scripts/analyze_distributed_results.py \\
      --results results/distributed_test_* \\
      --out analysis_report.html
"""

import argparse
import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


class DistributedTestAnalyzer:
    """分析分布式测试结果"""

    def __init__(self, results_dir: str):
        self.results_dir = results_dir
        self.benchmark_data = []
        self.metrics_data = defaultdict(list)
        self.load_data()

    def load_data(self):
        """加载所有结果数据"""
        # 加载基准测试数据
        for csv_file in Path(self.results_dir).glob("**/distributed_benchmark_*.csv"):
            with open(csv_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.benchmark_data.append(row)

        # 加载监控指标
        for csv_file in Path(self.results_dir).glob("**/metrics_*.csv"):
            metric_type = csv_file.stem
            with open(csv_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.metrics_data[metric_type].append(row)

    def analyze_benchmark_performance(self) -> Dict:
        """分析基准测试性能"""
        analysis = {
            "by_protocol": {},
            "by_scenario": {},
            "by_cluster_size": {},
            "quic_vs_tcp": {},
        }

        # 按协议分析
        for protocol in ["quic", "tcp"]:
            protocol_data = [d for d in self.benchmark_data if d.get("protocol") == protocol]
            if protocol_data:
                analysis["by_protocol"][protocol] = self._calculate_stats(protocol_data)

        # 按场景分析
        for scenario in set(d.get("scenario") for d in self.benchmark_data if d.get("scenario")):
            scenario_data = [d for d in self.benchmark_data if d.get("scenario") == scenario]
            analysis["by_scenario"][scenario] = self._calculate_stats(scenario_data)

        # 按集群规模分析
        for cluster_size in sorted(
            set(int(d.get("cluster_size", 0)) for d in self.benchmark_data if d.get("cluster_size"))
        ):
            size_data = [
                d for d in self.benchmark_data if int(d.get("cluster_size", 0)) == cluster_size
            ]
            analysis["by_cluster_size"][cluster_size] = self._calculate_stats(size_data)

        # QUIC vs TCP 对比
        analysis["quic_vs_tcp"] = self._analyze_quic_vs_tcp()

        return analysis

    def analyze_system_metrics(self) -> Dict:
        """分析系统指标"""
        analysis = {
            "cpu": {},
            "memory": {},
            "network": {},
            "disk_io": {},
        }

        # 分析系统指标
        if "metrics_*_system" in str(self.metrics_data):
            system_data = []
            for key, data in self.metrics_data.items():
                if "_system" in key:
                    system_data.extend(data)

            if system_data:
                # CPU分析
                cpu_values = [
                    float(d.get("cpu_usage_percent", 0))
                    for d in system_data
                    if d.get("cpu_usage_percent")
                ]
                if cpu_values:
                    analysis["cpu"] = {
                        "min": min(cpu_values),
                        "max": max(cpu_values),
                        "avg": statistics.mean(cpu_values),
                        "stdev": (
                            statistics.stdev(cpu_values)
                            if len(cpu_values) > 1
                            else 0
                        ),
                    }

                # 内存分析
                mem_values = [
                    float(d.get("memory_usage_percent", 0))
                    for d in system_data
                    if d.get("memory_usage_percent")
                ]
                if mem_values:
                    analysis["memory"] = {
                        "min": min(mem_values),
                        "max": max(mem_values),
                        "avg": statistics.mean(mem_values),
                        "stdev": (
                            statistics.stdev(mem_values)
                            if len(mem_values) > 1
                            else 0
                        ),
                    }

                # 网络分析
                tx_values = [
                    float(d.get("network_tx_bytes", 0))
                    for d in system_data
                    if d.get("network_tx_bytes")
                ]
                if tx_values:
                    analysis["network"] = {
                        "total_tx_bytes": sum(tx_values),
                        "avg_tx_rate": statistics.mean(tx_values) if tx_values else 0,
                    }

                # 磁盘I/O分析
                io_values = [
                    float(d.get("disk_write_kb_s", 0))
                    for d in system_data
                    if d.get("disk_write_kb_s")
                ]
                if io_values:
                    analysis["disk_io"] = {
                        "avg_write_kb_s": statistics.mean(io_values),
                        "max_write_kb_s": max(io_values),
                    }

        return analysis

    def _calculate_stats(self, data: List[Dict]) -> Dict:
        """计算统计量"""
        stats = {}

        # 吞吐量分析
        throughputs = [
            float(d.get("write_throughput", 0))
            for d in data
            if d.get("write_throughput")
        ]
        if throughputs:
            stats["write_throughput"] = {
                "min": min(throughputs),
                "max": max(throughputs),
                "avg": statistics.mean(throughputs),
                "stdev": statistics.stdev(throughputs) if len(throughputs) > 1 else 0,
            }

        # 延迟分析 (p99)
        p99_values = [
            float(d.get("write_p99_ms", 0))
            for d in data
            if d.get("write_p99_ms")
        ]
        if p99_values:
            stats["write_p99_ms"] = {
                "min": min(p99_values),
                "max": max(p99_values),
                "avg": statistics.mean(p99_values),
                "stdev": statistics.stdev(p99_values) if len(p99_values) > 1 else 0,
            }

        # 读吞吐量
        read_throughputs = [
            float(d.get("read_throughput", 0))
            for d in data
            if d.get("read_throughput")
        ]
        if read_throughputs:
            stats["read_throughput"] = {
                "min": min(read_throughputs),
                "max": max(read_throughputs),
                "avg": statistics.mean(read_throughputs),
                "stdev": statistics.stdev(read_throughputs) if len(read_throughputs) > 1 else 0,
            }

        return stats

    def _analyze_quic_vs_tcp(self) -> Dict:
        """对比QUIC和TCP性能"""
        comparison = {}

        # 按场景分组对比
        for scenario in set(d.get("scenario") for d in self.benchmark_data if d.get("scenario")):
            quic_data = [
                d for d in self.benchmark_data
                if d.get("scenario") == scenario and d.get("protocol") == "quic"
            ]
            tcp_data = [
                d for d in self.benchmark_data
                if d.get("scenario") == scenario and d.get("protocol") == "tcp"
            ]

            if quic_data and tcp_data:
                quic_tput = statistics.mean(
                    float(d.get("write_throughput", 0)) for d in quic_data
                )
                tcp_tput = statistics.mean(
                    float(d.get("write_throughput", 0)) for d in tcp_data
                )

                quic_lat = statistics.mean(
                    float(d.get("write_p99_ms", 0)) for d in quic_data
                )
                tcp_lat = statistics.mean(
                    float(d.get("write_p99_ms", 0)) for d in tcp_data
                )

                comparison[scenario] = {
                    "quic_throughput": quic_tput,
                    "tcp_throughput": tcp_tput,
                    "throughput_ratio": quic_tput / tcp_tput if tcp_tput > 0 else 0,
                    "quic_p99_ms": quic_lat,
                    "tcp_p99_ms": tcp_lat,
                    "latency_ratio": quic_lat / tcp_lat if tcp_lat > 0 else 1,
                }

        return comparison

    def analyze_cluster_scaling(self) -> Dict:
        """分析集群规模扩展性"""
        scaling = {}

        for scenario in set(d.get("scenario") for d in self.benchmark_data if d.get("scenario")):
            scenario_data = [
                d for d in self.benchmark_data if d.get("scenario") == scenario
            ]

            # 按集群规模排序
            by_size = defaultdict(list)
            for d in scenario_data:
                size = int(d.get("cluster_size", 0))
                by_size[size].append(d)

            scaling[scenario] = {}
            sizes = sorted(by_size.keys())

            for i, size in enumerate(sizes):
                data = by_size[size]
                tput = statistics.mean(
                    float(d.get("write_throughput", 0)) for d in data
                )

                scaling[scenario][size] = {
                    "throughput": tput,
                    "scaling_factor": tput / statistics.mean(
                        float(d.get("write_throughput", 0))
                        for d in by_size[sizes[0]]
                    ) if i > 0 else 1.0,
                }

        return scaling

    def generate_html_report(self, output_path: str):
        """生成HTML报告"""
        benchmark_analysis = self.analyze_benchmark_performance()
        system_analysis = self.analyze_system_metrics()
        scaling_analysis = self.analyze_cluster_scaling()

        html = self._generate_html(benchmark_analysis, system_analysis, scaling_analysis)

        with open(output_path, "w") as f:
            f.write(html)

        print(f"[+] HTML报告已生成: {output_path}")

    def _generate_html(self, bench: Dict, system: Dict, scaling: Dict) -> str:
        """生成HTML内容"""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>分布式性能测试分析报告</title>
    <style>
        * {{ margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; border-radius: 8px; margin-bottom: 40px; }}
        h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        h2 {{ font-size: 1.8em; color: #667eea; border-bottom: 3px solid #667eea; padding-bottom: 10px; margin: 30px 0 20px 0; }}
        h3 {{ font-size: 1.3em; color: #764ba2; margin: 20px 0 10px 0; }}
        .section {{ background: white; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ background: #f5f5f5; padding: 12px; text-align: left; border-bottom: 2px solid #667eea; font-weight: 600; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f9f9f9; }}
        .metric {{ display: inline-block; background: #f9f9f9; padding: 15px 20px; margin: 10px 10px 10px 0; border-radius: 8px; border-left: 4px solid #667eea; }}
        .metric-label {{ font-size: 0.9em; color: #666; }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; color: #667eea; }}
        .positive {{ color: #27ae60; }}
        .negative {{ color: #e74c3c; }}
        .neutral {{ color: #f39c12; }}
        .footer {{ text-align: center; color: #999; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 分布式性能测试分析报告</h1>
            <p>生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </header>

        <div class="section">
            <h2>📈 基准测试性能总结</h2>
            {self._html_benchmark_summary(bench)}
        </div>

        <div class="section">
            <h2>🔄 TCP vs QUIC 对比</h2>
            {self._html_quic_vs_tcp(bench['quic_vs_tcp'])}
        </div>

        <div class="section">
            <h2>📊 集群规模扩展性</h2>
            {self._html_scaling_analysis(scaling)}
        </div>

        <div class="section">
            <h2>💻 系统资源使用</h2>
            {self._html_system_metrics(system)}
        </div>

        <div class="section">
            <h2>📋 详细数据</h2>
            {self._html_detailed_data(bench)}
        </div>

        <div class="footer">
            <p>本报告由分布式性能分析工具自动生成</p>
        </div>
    </div>
</body>
</html>
        """

    def _html_benchmark_summary(self, bench: Dict) -> str:
        """生成基准测试摘要HTML"""
        html = "<h3>按协议分析</h3>\n<table>\n<tr><th>协议</th><th>平均吞吐(ops/s)</th><th>p99延迟(ms)</th><th>读吞吐(ops/s)</th></tr>\n"

        for protocol in sorted(bench["by_protocol"].keys()):
            stats = bench["by_protocol"][protocol]
            write_tput = stats.get("write_throughput", {}).get("avg", 0)
            p99 = stats.get("write_p99_ms", {}).get("avg", 0)
            read_tput = stats.get("read_throughput", {}).get("avg", 0)

            html += f"<tr><td><strong>{protocol.upper()}</strong></td><td>{write_tput:.1f}</td><td>{p99:.2f}</td><td>{read_tput:.1f}</td></tr>\n"

        html += "</table>\n"

        # 按场景分析
        html += "<h3>按场景分析</h3>\n<table>\n<tr><th>场景</th><th>平均吞吐(ops/s)</th><th>p99延迟(ms)</th></tr>\n"

        for scenario in sorted(bench["by_scenario"].keys()):
            stats = bench["by_scenario"][scenario]
            write_tput = stats.get("write_throughput", {}).get("avg", 0)
            p99 = stats.get("write_p99_ms", {}).get("avg", 0)

            html += f"<tr><td><strong>{scenario}</strong></td><td>{write_tput:.1f}</td><td>{p99:.2f}</td></tr>\n"

        html += "</table>"

        return html

    def _html_quic_vs_tcp(self, comparison: Dict) -> str:
        """生成QUIC vs TCP对比HTML"""
        if not comparison:
            return "<p>无对比数据</p>"

        html = "<table>\n<tr><th>场景</th><th>QUIC吞吐</th><th>TCP吞吐</th><th>吞吐比</th><th>QUIC p99</th><th>TCP p99</th><th>延迟比</th></tr>\n"

        for scenario, data in sorted(comparison.items()):
            ratio = data["throughput_ratio"]
            ratio_class = "positive" if ratio > 1 else "negative" if ratio < 1 else "neutral"
            lat_ratio = data["latency_ratio"]
            lat_class = "positive" if lat_ratio < 1 else "negative" if lat_ratio > 1 else "neutral"

            html += f"""<tr>
                <td><strong>{scenario}</strong></td>
                <td>{data['quic_throughput']:.1f}</td>
                <td>{data['tcp_throughput']:.1f}</td>
                <td class="{ratio_class}">{ratio:.2f}x</td>
                <td>{data['quic_p99_ms']:.2f}</td>
                <td>{data['tcp_p99_ms']:.2f}</td>
                <td class="{lat_class}">{lat_ratio:.2f}x</td>
            </tr>\n"""

        html += "</table>"
        return html

    def _html_scaling_analysis(self, scaling: Dict) -> str:
        """生成扩展性分析HTML"""
        html = ""

        for scenario, data in sorted(scaling.items()):
            html += f"<h3>{scenario}</h3>\n"
            html += "<table>\n<tr><th>集群规模</th><th>吞吐(ops/s)</th><th>相对于3节点</th></tr>\n"

            for size in sorted(data.keys()):
                metrics = data[size]
                factor = metrics["scaling_factor"]
                factor_class = "positive" if factor > 0.8 else "negative" if factor < 0.5 else "neutral"

                html += f"<tr><td>{size}节点</td><td>{metrics['throughput']:.1f}</td><td class=\"{factor_class}\">{factor:.2f}x</td></tr>\n"

            html += "</table>\n"

        return html

    def _html_system_metrics(self, system: Dict) -> str:
        """生成系统指标HTML"""
        html = ""

        if system.get("cpu"):
            cpu = system["cpu"]
            html += f"""
            <div class="metric">
                <div class="metric-label">平均 CPU 使用率</div>
                <div class="metric-value">{cpu.get('avg', 0):.1f}%</div>
            </div>
            """

        if system.get("memory"):
            mem = system["memory"]
            html += f"""
            <div class="metric">
                <div class="metric-label">平均内存使用率</div>
                <div class="metric-value">{mem.get('avg', 0):.1f}%</div>
            </div>
            """

        if system.get("disk_io"):
            io = system["disk_io"]
            html += f"""
            <div class="metric">
                <div class="metric-label">平均磁盘写入</div>
                <div class="metric-value">{io.get('avg_write_kb_s', 0):.1f} KB/s</div>
            </div>
            """

        return html if html else "<p>无系统指标数据</p>"

    def _html_detailed_data(self, bench: Dict) -> str:
        """生成详细数据HTML"""
        html = "<h3>按集群规模详细数据</h3>\n"
        html += "<table>\n<tr><th>集群规模</th><th>吞吐(ops/s)</th><th>p99(ms)</th><th>p95(ms)</th><th>p50(ms)</th></tr>\n"

        for size in sorted(bench["by_cluster_size"].keys()):
            stats = bench["by_cluster_size"][size]
            tput = stats.get("write_throughput", {}).get("avg", 0)
            p99 = stats.get("write_p99_ms", {}).get("avg", 0)

            html += f"<tr><td>{size}节点</td><td>{tput:.1f}</td><td>{p99:.2f}</td><td>-</td><td>-</td></tr>\n"

        html += "</table>"
        return html


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("--results", required=True,
                       help="results directory path")
    parser.add_argument("--out", default="distributed_analysis_report.html",
                       help="output report file path")

    args = parser.parse_args()

    print("=" * 70)
    print("分布式性能测试结果分析")
    print("=" * 70)

    analyzer = DistributedTestAnalyzer(args.results)

    if not analyzer.benchmark_data:
        print("[!] 未找到基准测试数据")
        return

    print(f"[+] 已加载 {len(analyzer.benchmark_data)} 条基准测试数据")
    print(f"[+] 已加载 {len(analyzer.metrics_data)} 类监控指标")

    # 执行分析
    print("\n[*] 分析基准测试性能...")
    bench_analysis = analyzer.analyze_benchmark_performance()

    print("[*] 分析系统资源使用...")
    system_analysis = analyzer.analyze_system_metrics()

    print("[*] 分析集群扩展性...")
    scaling_analysis = analyzer.analyze_cluster_scaling()

    # 输出摘要
    print("\n" + "=" * 70)
    print("分析摘要")
    print("=" * 70)

    if bench_analysis["quic_vs_tcp"]:
        print("\nQUIC vs TCP 对比:")
        for scenario, data in bench_analysis["quic_vs_tcp"].items():
            print(f"\n  {scenario}:")
            print(f"    QUIC 吞吐: {data['quic_throughput']:.1f} ops/s")
            print(f"    TCP 吞吐: {data['tcp_throughput']:.1f} ops/s")
            print(f"    吞吐比: {data['throughput_ratio']:.2f}x")
            print(f"    QUIC p99: {data['quic_p99_ms']:.2f} ms")
            print(f"    TCP p99: {data['tcp_p99_ms']:.2f} ms")
            print(f"    延迟比: {data['latency_ratio']:.2f}x")

    # 生成HTML报告
    print(f"\n[*] 生成HTML报告...")
    analyzer.generate_html_report(args.out)

    print(f"[+] 分析完成!")


if __name__ == "__main__":
    main()
