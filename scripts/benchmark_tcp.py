#!/usr/bin/env python3
"""
benchmark_tcp.py – TCP 性能基准测试，用于 QUIC vs TCP 对比

使用 Go 编写的简单 TCP 服务器进行基准测试，与 QUIC 基准进行对比。

测试指标:
  • 顺序写入吞吐量
  • 并发写入吞吐量 (C=1,2,4,8)
  • 顺序读取吞吐量
  • 延迟分布 (p50, p95, p99)

输出: CSV 文件，可用 visualize.py 或 generate_report.py 处理

Prerequisites:
    python3 -m pip install requests

Usage:
    python3 scripts/benchmark_tcp.py \
      --tcp-host localhost \
      --tcp-port 9001 \
      --quic-host localhost \
      --quic-port 8001 \
      --writes 100 \
      --concurrency 1,4,8 \
      --out results
"""

import argparse
import csv
import os
import random
import statistics
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    import requests
except ImportError:
    raise SystemExit("requests library required: pip install requests")


def rand_val(n=32):
    """Generate random value."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def timed_write(url, key, value, protocol="tcp"):
    """Time a single write operation."""
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{url}/set?key={key}&value={value}", timeout=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            raise RuntimeError(f"write failed: {r.status_code}")
        return elapsed_ms
    except Exception as e:
        raise RuntimeError(f"{protocol} write error: {e}")


def timed_read(url, key, protocol="tcp"):
    """Time a single read operation."""
    t0 = time.perf_counter()
    try:
        r = requests.get(f"{url}/get?key={key}", timeout=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if r.status_code not in (200, 404):
            raise RuntimeError(f"read failed: {r.status_code}")
        return elapsed_ms
    except Exception as e:
        raise RuntimeError(f"{protocol} read error: {e}")


def benchmark_write_sequential(url, n, protocol="tcp"):
    """Sequential writes."""
    print(f"  {protocol.upper()} sequential writes: n={n} …", flush=True)
    latencies = []
    errors = 0
    t_start = time.monotonic()
    for i in range(n):
        key = f"seq_{protocol}_{i}"
        try:
            lat = timed_write(url, key, rand_val(), protocol)
            latencies.append(lat)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    error: {e}")
    elapsed = time.monotonic() - t_start
    return _stats(f"write_sequential_{protocol}", 1, n, elapsed, latencies, errors)


def benchmark_write_concurrent(url, n, concurrency, protocol="tcp"):
    """Concurrent writes."""
    print(f"  {protocol.upper()} concurrent writes: n={n}, c={concurrency} …", flush=True)
    latencies = []
    errors = 0

    def _worker(i):
        key = f"conc_{protocol}_{concurrency}_{i}"
        return timed_write(url, key, rand_val(), protocol)

    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_worker, i) for i in range(n)]
        for fut in as_completed(futures):
            try:
                latencies.append(fut.result())
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"    error: {e}")
    elapsed = time.monotonic() - t_start
    return _stats(f"write_concurrent_{protocol}", concurrency, n, elapsed, latencies, errors)


def benchmark_read(url, key, n, protocol="tcp"):
    """Sequential reads."""
    print(f"  {protocol.upper()} sequential reads: n={n} …", flush=True)
    latencies = []
    errors = 0
    t_start = time.monotonic()
    for _ in range(n):
        try:
            latencies.append(timed_read(url, key, protocol))
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    error: {e}")
    elapsed = time.monotonic() - t_start
    return _stats(f"read_sequential_{protocol}", 1, n, elapsed, latencies, errors)


def _stats(bench, concurrency, n, elapsed, latencies, errors):
    """Calculate statistics."""
    if not latencies:
        return {
            "benchmark": bench,
            "concurrency": concurrency,
            "n": n,
            "throughput_ops_s": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "mean_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
            "errors": errors,
        }
    s = sorted(latencies)
    pct = lambda p: s[int(len(s) * p / 100)]
    return {
        "benchmark": bench,
        "concurrency": concurrency,
        "n": n,
        "throughput_ops_s": round(len(latencies) / elapsed, 2),
        "p50_ms": round(pct(50), 2),
        "p95_ms": round(pct(95), 2),
        "p99_ms": round(pct(99), 2),
        "mean_ms": round(statistics.mean(latencies), 2),
        "min_ms": round(min(latencies), 2),
        "max_ms": round(max(latencies), 2),
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tcp-host", default="localhost",
                       help="TCP server host")
    parser.add_argument("--tcp-port", type=int, default=9001,
                       help="TCP server port")
    parser.add_argument("--quic-host", default="localhost",
                       help="QUIC server host")
    parser.add_argument("--quic-port", type=int, default=8001,
                       help="QUIC server port")
    parser.add_argument("--writes", type=int, default=100,
                       help="number of write operations per scenario")
    parser.add_argument("--reads", type=int, default=200,
                       help="number of read operations")
    parser.add_argument("--concurrency", default="1,4,8",
                       help="comma-separated concurrency levels")
    parser.add_argument("--out", default="results",
                       help="output directory for results")
    parser.add_argument("--quic-only", action="store_true",
                       help="skip TCP tests (QUIC only)")
    parser.add_argument("--tcp-only", action="store_true",
                       help="skip QUIC tests (TCP only)")

    args = parser.parse_args()

    quic_url = f"http://{args.quic_host}:{args.quic_port}"
    tcp_url = f"http://{args.tcp_host}:{args.tcp_port}"
    concurrencies = [int(c) for c in args.concurrency.split(",")]

    print("=" * 70)
    print("QUIC vs TCP Performance Benchmark")
    print(f"  QUIC: {quic_url}")
    print(f"  TCP:  {tcp_url}")
    print(f"  Writes: {args.writes} per scenario")
    print(f"  Concurrency: {concurrencies}")
    print("=" * 70)

    results = []

    # TCP Benchmarks
    if not args.quic_only:
        print("\n[+] TCP Benchmarks")
        for c in concurrencies:
            if c == 1:
                try:
                    results.append(benchmark_write_sequential(tcp_url, args.writes, "tcp"))
                except Exception as e:
                    print(f"  ERROR: {e}")
                    break
            else:
                try:
                    results.append(benchmark_write_concurrent(tcp_url, args.writes, c, "tcp"))
                except Exception as e:
                    print(f"  ERROR: {e}")
                    break

        # Seed a key for TCP reads
        try:
            requests.post(f"{tcp_url}/set?key=bench_tcp_seed&value=readtest", timeout=5)
            time.sleep(0.5)
            results.append(benchmark_read(tcp_url, "bench_tcp_seed", args.reads, "tcp"))
        except Exception as e:
            print(f"  ERROR in TCP read benchmark: {e}")

    # QUIC Benchmarks
    if not args.tcp_only:
        print("\n[+] QUIC Benchmarks")
        for c in concurrencies:
            if c == 1:
                try:
                    results.append(benchmark_write_sequential(quic_url, args.writes, "quic"))
                except Exception as e:
                    print(f"  ERROR: {e}")
                    break
            else:
                try:
                    results.append(benchmark_write_concurrent(quic_url, args.writes, c, "quic"))
                except Exception as e:
                    print(f"  ERROR: {e}")
                    break

        # Seed a key for QUIC reads
        try:
            requests.post(f"{quic_url}/set?key=bench_quic_seed&value=readtest", timeout=5)
            time.sleep(0.5)
            results.append(benchmark_read(quic_url, "bench_quic_seed", args.reads, "quic"))
        except Exception as e:
            print(f"  ERROR in QUIC read benchmark: {e}")

    # Output results
    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.out, f"benchmark_quic_tcp_{ts}.csv")

    fieldnames = ["benchmark", "concurrency", "n", "throughput_ops_s",
                  "p50_ms", "p95_ms", "p99_ms", "mean_ms", "min_ms", "max_ms", "errors"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    # Print summary
    print("\n" + "=" * 90)
    print(f"{'Benchmark':<35} {'Conc':>4} {'Tput(ops/s)':>12} {'p50(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9}")
    print("-" * 90)
    for r in results:
        bench = r.get("benchmark", "")
        print(f"{bench:<35} {r.get('concurrency',''):>4} {r.get('throughput_ops_s',''):>12.1f} "
              f"{r.get('p50_ms',''):>9.2f} {r.get('p95_ms',''):>9.2f} {r.get('p99_ms',''):>9.2f}")
    print("=" * 90)

    # Print comparison
    print("\n[+] QUIC vs TCP Comparison")
    print("-" * 70)

    # Group results by benchmark type
    tcp_results = {r["benchmark"]: r for r in results if "tcp" in r["benchmark"]}
    quic_results = {r["benchmark"]: r for r in results if "quic" in r["benchmark"]}

    for bench_key in sorted(set(tcp_results.keys()) & set(quic_results.keys())):
        tcp = tcp_results.get(bench_key)
        quic_key = bench_key.replace("_tcp", "_quic")
        quic = quic_results.get(quic_key)

        if tcp and quic:
            tcp_tput = tcp.get("throughput_ops_s", 0)
            quic_tput = quic.get("throughput_ops_s", 0)
            ratio = quic_tput / tcp_tput if tcp_tput > 0 else 0

            tcp_p99 = tcp.get("p99_ms", 0)
            quic_p99 = quic.get("p99_ms", 0)
            latency_ratio = quic_p99 / tcp_p99 if tcp_p99 > 0 else 0

            print(f"\n{bench_key}:")
            print(f"  TCP:  {tcp_tput:>8.1f} ops/s, p99={tcp_p99:>7.2f}ms")
            print(f"  QUIC: {quic_tput:>8.1f} ops/s, p99={quic_p99:>7.2f}ms")
            print(f"  Ratio: QUIC is {ratio:.2f}x TCP throughput, {latency_ratio:.2f}x latency")

    print(f"\nResults saved to: {csv_path}")


if __name__ == "__main__":
    main()
