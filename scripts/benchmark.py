#!/usr/bin/env python3
"""
benchmark.py – Performance benchmark for the Raft-over-QUIC cluster.

Measures:
  • Write throughput (ops/s) at various concurrency levels
  • Read  throughput (ops/s)
  • Write latency distribution: p50 / p95 / p99

Outputs a CSV file (results/benchmark_<timestamp>.csv) and a summary table
suitable for inclusion in the CS5296 final report.

Prerequisites:
    pip install requests
    docker compose up --build -d   # cluster must be running

Usage:
    python3 scripts/benchmark.py [--host HOST] [--ports 8001,8002,8003]
                                 [--writes N] [--concurrency C[,C...]]
                                 [--out DIR]
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

# ── Helpers ────────────────────────────────────────────────────────────────────

def find_leader(urls: list[str]) -> str | None:
    """Return the URL of the current Raft leader, or None."""
    for url in urls:
        try:
            r = requests.get(f"{url}/status", timeout=3)
            if r.ok and r.json().get("state") == "Leader":
                return url
        except Exception:
            pass
    return None


def wait_for_leader(urls: list[str], timeout: int = 60) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        leader = find_leader(urls)
        if leader:
            return leader
        time.sleep(1)
    raise RuntimeError(f"No leader found after {timeout}s")


def rand_key(n: int = 8) -> str:
    return "bench_" + "".join(random.choices(string.ascii_lowercase, k=n))


def rand_val(n: int = 32) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


# ── Single-operation timing ────────────────────────────────────────────────────

def timed_write(leader_url: str, key: str, value: str) -> float:
    """Returns latency in milliseconds, or raises on error."""
    t0 = time.perf_counter()
    r = requests.post(f"{leader_url}/set?key={key}&value={value}", timeout=10)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        raise RuntimeError(f"write failed: {r.status_code} {r.text.strip()}")
    return elapsed_ms


def timed_read(url: str, key: str) -> float:
    t0 = time.perf_counter()
    r = requests.get(f"{url}/get?key={key}", timeout=10)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if r.status_code not in (200, 404):
        raise RuntimeError(f"read failed: {r.status_code}")
    return elapsed_ms


# ── Benchmark routines ─────────────────────────────────────────────────────────

def benchmark_write_sequential(leader_url: str, n: int) -> dict:
    """Sequential writes – measures raw single-threaded throughput."""
    print(f"  Sequential writes: n={n} …", flush=True)
    latencies = []
    errors = 0
    t_start = time.monotonic()
    for i in range(n):
        key = f"seq_{i}"
        try:
            lat = timed_write(leader_url, key, rand_val())
            latencies.append(lat)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    error: {e}")
    elapsed = time.monotonic() - t_start
    return _stats("write_sequential", 1, n, elapsed, latencies, errors)


def benchmark_write_concurrent(leader_url: str, n: int, concurrency: int) -> dict:
    """Concurrent writes with a fixed thread pool."""
    print(f"  Concurrent writes: n={n}, concurrency={concurrency} …", flush=True)
    latencies = []
    errors = 0

    def _worker(i):
        return timed_write(leader_url, f"conc_{concurrency}_{i}", rand_val())

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
    return _stats("write_concurrent", concurrency, n, elapsed, latencies, errors)


def benchmark_read(urls: list[str], known_key: str, n: int) -> dict:
    """Sequential reads (local, stale reads) from a random node."""
    print(f"  Sequential reads: n={n} …", flush=True)
    latencies = []
    errors = 0
    t_start = time.monotonic()
    for _ in range(n):
        url = random.choice(urls)
        try:
            latencies.append(timed_read(url, known_key))
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    error: {e}")
    elapsed = time.monotonic() - t_start
    return _stats("read_sequential", 1, n, elapsed, latencies, errors)


def _stats(bench: str, concurrency: int, n: int, elapsed: float,
           latencies: list[float], errors: int) -> dict:
    if not latencies:
        return {"benchmark": bench, "concurrency": concurrency, "n": n,
                "throughput_ops_s": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
                "mean_ms": 0, "min_ms": 0, "max_ms": 0, "errors": errors}
    s = sorted(latencies)
    pct = lambda p: s[int(len(s) * p / 100)]
    return {
        "benchmark":        bench,
        "concurrency":      concurrency,
        "n":                n,
        "throughput_ops_s": round(len(latencies) / elapsed, 2),
        "p50_ms":           round(pct(50), 2),
        "p95_ms":           round(pct(95), 2),
        "p99_ms":           round(pct(99), 2),
        "mean_ms":          round(statistics.mean(latencies), 2),
        "min_ms":           round(min(latencies), 2),
        "max_ms":           round(max(latencies), 2),
        "errors":           errors,
    }


# ── Leader-election timing ─────────────────────────────────────────────────────

def benchmark_leader_election(urls: list[str], container_map: dict) -> dict:
    """
    Stop the current leader, measure how long until a new leader is elected.
    Restarts the container afterward.
    """
    import subprocess

    leader_url = find_leader(urls)
    if not leader_url:
        return {"benchmark": "leader_election", "election_time_s": -1,
                "notes": "no leader found"}

    container = container_map.get(leader_url)
    if not container:
        return {"benchmark": "leader_election", "election_time_s": -1,
                "notes": f"unknown container for {leader_url}"}

    remaining = [u for u in urls if u != leader_url]
    print(f"  Stopping {container} (leader: {leader_url}) …", flush=True)

    subprocess.run(["docker", "stop", container], check=True,
                   capture_output=True)
    t_stop = time.monotonic()

    new_leader = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        new_leader = find_leader(remaining)
        if new_leader:
            break
        time.sleep(0.1)

    election_time = time.monotonic() - t_stop

    print(f"  Restarting {container} …", flush=True)
    subprocess.run(["docker", "start", container], check=True,
                   capture_output=True)

    return {
        "benchmark":        "leader_election",
        "concurrency":      1,
        "n":                1,
        "throughput_ops_s": "",
        "p50_ms":           "",
        "p95_ms":           "",
        "p99_ms":           "",
        "mean_ms":          "",
        "min_ms":           "",
        "max_ms":           "",
        "election_time_s":  round(election_time, 3),
        "errors":           0 if new_leader else 1,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--ports", default="8001,8002,8003",
                        help="comma-separated HTTP ports")
    parser.add_argument("--writes", type=int, default=200,
                        help="number of write operations per scenario")
    parser.add_argument("--reads", type=int, default=500,
                        help="number of read operations")
    parser.add_argument("--concurrency", default="1,2,4,8",
                        help="comma-separated concurrency levels for writes")
    parser.add_argument("--out", default="results",
                        help="output directory for CSV results")
    parser.add_argument("--skip-election", action="store_true",
                        help="skip the leader-election benchmark (requires docker CLI)")
    args = parser.parse_args()

    ports = [int(p) for p in args.ports.split(",")]
    urls  = [f"http://{args.host}:{p}" for p in ports]
    concurrencies = [int(c) for c in args.concurrency.split(",")]

    container_map = {
        f"http://{args.host}:{ports[0]}": "raft-node1",
        f"http://{args.host}:{ports[1]}": "raft-node2",
        f"http://{args.host}:{ports[2]}": "raft-node3",
    }

    print("=" * 60)
    print("Raft-over-QUIC Cluster Benchmark")
    print(f"  Nodes : {urls}")
    print(f"  Writes: {args.writes} per scenario")
    print(f"  Conc  : {concurrencies}")
    print("=" * 60)

    print("\n[+] Waiting for cluster leader …")
    leader_url = wait_for_leader(urls)
    print(f"    Leader: {leader_url}")

    results = []

    # ── Write benchmarks ───────────────────────────────────────────────────
    print("\n[+] Write benchmarks")
    for c in concurrencies:
        if c == 1:
            results.append(benchmark_write_sequential(leader_url, args.writes))
        else:
            results.append(benchmark_write_concurrent(leader_url, args.writes, c))

    # ── Seed a key for reads ───────────────────────────────────────────────
    seed_key = "bench_read_seed"
    try:
        requests.post(f"{leader_url}/set?key={seed_key}&value=readtest", timeout=5)
        time.sleep(0.5)  # let replication propagate
    except Exception:
        pass

    # ── Read benchmark ─────────────────────────────────────────────────────
    print("\n[+] Read benchmark")
    results.append(benchmark_read(urls, seed_key, args.reads))

    # ── Leader-election benchmark ──────────────────────────────────────────
    if not args.skip_election:
        print("\n[+] Leader-election benchmark")
        results.append(benchmark_leader_election(urls, container_map))

    # ── Output ─────────────────────────────────────────────────────────────
    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.out, f"benchmark_{ts}.csv")

    fieldnames = ["benchmark", "concurrency", "n", "throughput_ops_s",
                  "p50_ms", "p95_ms", "p99_ms", "mean_ms", "min_ms", "max_ms",
                  "election_time_s", "errors"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    # ── Summary table ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'Benchmark':<25} {'Conc':>5} {'Tput(ops/s)':>12} {'p50(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9}")
    print("-" * 70)
    for r in results:
        bench = r.get("benchmark", "")
        if bench == "leader_election":
            print(f"{'leader_election':<25} {'1':>5} {'—':>12} {'—':>9} {'—':>9} {'—':>9}  election={r.get('election_time_s','')}s")
        else:
            print(f"{bench:<25} {r.get('concurrency',''):>5} {r.get('throughput_ops_s',''):>12} "
                  f"{r.get('p50_ms',''):>9} {r.get('p95_ms',''):>9} {r.get('p99_ms',''):>9}")
    print("=" * 70)
    print(f"\nResults saved to: {csv_path}")


if __name__ == "__main__":
    main()
