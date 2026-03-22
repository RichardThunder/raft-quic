#!/usr/bin/env python3
"""
benchmark_aws.py – Performance benchmark for Raft-over-QUIC on AWS.

Runs the same workload against both a same-region cluster and a cross-region
cluster, then produces a side-by-side comparison CSV and summary table for the
CS5296 final report.

Features over benchmark.py:
  • Sources cluster state from deploy/cluster.env (written by deploy.sh)
  • SSH-based leader failover (no docker dependency)
  • Automatic same-region vs cross-region comparison mode
  • Latency CDF data for plotting

Prerequisites:
    pip install requests
    # cluster must be running (./deploy/deploy.sh same-region)

Usage:
    # Single scenario (reads deploy/cluster.env):
    python3 scripts/benchmark_aws.py

    # Explicit IPs:
    python3 scripts/benchmark_aws.py \\
        --ips 54.1.2.3,54.4.5.6,54.7.8.9 \\
        --ssh-key deploy/terraform/same-region/raft-key.pem \\
        --label same-region

    # Compare same-region vs cross-region (runs both sequentially):
    python3 scripts/benchmark_aws.py --compare \\
        --same-env  deploy/cluster-same.env \\
        --cross-env deploy/cluster-cross.env
"""

import argparse
import csv
import os
import random
import statistics
import string
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.exit("requests library required: pip install requests")


# ── HTTP session with retries ──────────────────────────────────────────────────

def make_session(retries: int = 3) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=retries, backoff_factor=0.3,
                  status_forcelist=[500, 502, 503, 504])
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


SESSION = make_session()


# ── Cluster helpers ────────────────────────────────────────────────────────────

def node_urls(ips: list[str], port: int = 8001) -> list[str]:
    return [f"http://{ip}:{port}" for ip in ips]


def get_state(url: str) -> str:
    try:
        r = SESSION.get(f"{url}/status", timeout=5)
        return r.json().get("state", "unknown")
    except Exception:
        return "unreachable"


def find_leader(urls: list[str]) -> str | None:
    for url in urls:
        if get_state(url) == "Leader":
            return url
    return None


def wait_for_leader(urls: list[str], timeout: int = 90) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        leader = find_leader(urls)
        if leader:
            return leader
        time.sleep(1)
    raise RuntimeError(f"No leader found after {timeout}s")


# ── Timed operations ───────────────────────────────────────────────────────────

def rand_val(n: int = 32) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def timed_write(leader_url: str, key: str, value: str,
                timeout: float = 15.0) -> float:
    t0 = time.perf_counter()
    r = SESSION.post(f"{leader_url}/set?key={key}&value={value}",
                     timeout=timeout)
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        raise RuntimeError(f"write failed: {r.status_code}")
    return ms


def timed_read(url: str, key: str, timeout: float = 10.0) -> float:
    t0 = time.perf_counter()
    r = SESSION.get(f"{url}/get?key={key}", timeout=timeout)
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code not in (200, 404):
        raise RuntimeError(f"read failed: {r.status_code}")
    return ms


# ── Benchmark routines ─────────────────────────────────────────────────────────

def _stats(bench: str, concurrency: int, n: int, elapsed: float,
           latencies: list[float], errors: int,
           extra: dict | None = None) -> dict:
    if not latencies:
        row = {"benchmark": bench, "concurrency": concurrency, "n": n,
               "throughput_ops_s": 0, "mean_ms": 0, "p50_ms": 0,
               "p95_ms": 0, "p99_ms": 0, "min_ms": 0, "max_ms": 0,
               "errors": errors}
    else:
        s = sorted(latencies)
        pct = lambda p: s[min(int(len(s) * p / 100), len(s) - 1)]
        row = {
            "benchmark":        bench,
            "concurrency":      concurrency,
            "n":                n,
            "throughput_ops_s": round(len(latencies) / elapsed, 2),
            "mean_ms":          round(statistics.mean(latencies), 2),
            "p50_ms":           round(pct(50), 2),
            "p95_ms":           round(pct(95), 2),
            "p99_ms":           round(pct(99), 2),
            "min_ms":           round(min(latencies), 2),
            "max_ms":           round(max(latencies), 2),
            "errors":           errors,
        }
    if extra:
        row.update(extra)
    return row


def bench_write_seq(leader_url: str, n: int, label: str = "") -> dict:
    print(f"  [{label}] Sequential writes n={n} …", flush=True)
    latencies, errors = [], 0
    t0 = time.monotonic()
    for i in range(n):
        try:
            latencies.append(timed_write(leader_url, f"aws_seq_{i}", rand_val()))
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    error: {e}")
    elapsed = time.monotonic() - t0
    return _stats("write_sequential", 1, n, elapsed, latencies, errors)


def bench_write_concurrent(leader_url: str, n: int,
                            concurrency: int, label: str = "") -> dict:
    print(f"  [{label}] Concurrent writes n={n} c={concurrency} …", flush=True)
    latencies, errors = [], 0

    def _w(i):
        return timed_write(leader_url, f"aws_c{concurrency}_{i}", rand_val())

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for fut in as_completed([pool.submit(_w, i) for i in range(n)]):
            try:
                latencies.append(fut.result())
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"    error: {e}")
    elapsed = time.monotonic() - t0
    return _stats("write_concurrent", concurrency, n, elapsed, latencies, errors)


def bench_read(urls: list[str], key: str, n: int, label: str = "") -> dict:
    print(f"  [{label}] Sequential reads n={n} …", flush=True)
    latencies, errors = [], 0
    t0 = time.monotonic()
    for _ in range(n):
        try:
            latencies.append(timed_read(random.choice(urls), key))
        except Exception as e:
            errors += 1
    elapsed = time.monotonic() - t0
    return _stats("read_sequential", 1, n, elapsed, latencies, errors)


def bench_leader_election(ips: list[str], ssh_key: str,
                           ssh_user: str = "ec2-user",
                           label: str = "") -> dict:
    """
    Stop the current leader via SSH, measure how long until a new leader
    emerges, then restart the stopped node.
    """
    urls = node_urls(ips)
    leader_url = find_leader(urls)
    if not leader_url:
        return {"benchmark": "leader_election", "election_time_s": -1,
                "errors": 1, "notes": "no leader"}

    leader_ip = leader_url.split("//")[1].split(":")[0]
    remaining_urls = [u for u in urls if u != leader_url]

    print(f"  [{label}] Leader election: stopping {leader_ip} …", flush=True)
    ssh = ["ssh", "-i", ssh_key, "-o", "StrictHostKeyChecking=no",
           "-o", "ConnectTimeout=8", f"{ssh_user}@{leader_ip}"]
    subprocess.run(ssh + ["pkill -f raftd; true"],
                   capture_output=True, timeout=15)

    t_stop = time.monotonic()
    new_leader = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        new_leader = find_leader(remaining_urls)
        if new_leader:
            break
        time.sleep(0.2)

    election_time = time.monotonic() - t_stop

    # Restart the stopped node.
    print(f"  [{label}] Restarting {leader_ip} …", flush=True)
    subprocess.run(ssh + [
        "nohup ~/raftd "
        "-id node1 "
        f"-bind 0.0.0.0:7001 "
        f"-advertise {leader_ip}:7001 "
        "-http 0.0.0.0:8001 "
        "-join " + (remaining_urls[0].split("//")[1].split(":")[0]) + ":8001 "
        "-join-retries 15 "
        "> ~/raftd.log 2>&1 &"
    ], capture_output=True, timeout=15)

    return {
        "benchmark":        "leader_election",
        "concurrency":      "",
        "n":                "",
        "throughput_ops_s": "",
        "mean_ms":          "",
        "p50_ms":           "",
        "p95_ms":           "",
        "p99_ms":           "",
        "min_ms":           "",
        "max_ms":           "",
        "election_time_s":  round(election_time, 3),
        "errors":           0 if new_leader else 1,
    }


# ── CSV / CDF output ───────────────────────────────────────────────────────────

FIELDS = ["scenario", "benchmark", "concurrency", "n", "throughput_ops_s",
          "mean_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms",
          "election_time_s", "errors"]


def save_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})
    print(f"Results saved → {path}")


def print_table(rows: list[dict], scenario: str) -> None:
    print(f"\n{'─'*75}")
    print(f"  Scenario: {scenario}")
    print(f"{'─'*75}")
    print(f"{'Benchmark':<22} {'Conc':>5} {'Tput(ops/s)':>12} "
          f"{'p50(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9}")
    print(f"{'─'*75}")
    for r in rows:
        bench = r.get("benchmark", "")
        if bench == "leader_election":
            print(f"{'leader_election':<22} {'—':>5} {'—':>12} {'—':>9} {'—':>9} {'—':>9}"
                  f"   election={r.get('election_time_s','')}s")
        else:
            print(f"{bench:<22} {str(r.get('concurrency','')):>5} "
                  f"{str(r.get('throughput_ops_s','')):>12} "
                  f"{str(r.get('p50_ms','')):>9} "
                  f"{str(r.get('p95_ms','')):>9} "
                  f"{str(r.get('p99_ms','')):>9}")
    print(f"{'─'*75}")


# ── Single-scenario runner ─────────────────────────────────────────────────────

def run_scenario(ips: list[str], ssh_key: str, ssh_user: str,
                 scenario: str, writes: int, reads: int,
                 concurrencies: list[int]) -> list[dict]:
    urls = node_urls(ips)
    print(f"\n{'═'*60}")
    print(f"  Benchmarking: {scenario}")
    print(f"  Nodes: {ips}")
    print(f"{'═'*60}")

    leader_url = wait_for_leader(urls)
    print(f"  Leader: {leader_url}")

    results = []

    # Write benchmarks at each concurrency level.
    for c in concurrencies:
        if c == 1:
            r = bench_write_seq(leader_url, writes, label=scenario)
        else:
            r = bench_write_concurrent(leader_url, writes, c, label=scenario)
        r["scenario"] = scenario
        results.append(r)

    # Seed a key for read benchmark.
    try:
        SESSION.post(f"{leader_url}/set?key=read_seed&value=bench",
                     timeout=10)
        time.sleep(1)
    except Exception:
        pass

    r = bench_read(urls, "read_seed", reads, label=scenario)
    r["scenario"] = scenario
    results.append(r)

    # Leader-election benchmark (requires SSH).
    if ssh_key and os.path.exists(ssh_key):
        r = bench_leader_election(ips, ssh_key, ssh_user, label=scenario)
        r["scenario"] = scenario
        results.append(r)
    else:
        print(f"  Skipping leader-election benchmark (no SSH key provided)")

    return results


# ── Env file loading ───────────────────────────────────────────────────────────

def load_env(path: str) -> dict:
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env",  default="deploy/cluster.env",
                        help="cluster.env file written by deploy.sh")
    parser.add_argument("--ips",  help="comma-separated node IPs (overrides --env)")
    parser.add_argument("--ssh-key",  help="SSH private key path (overrides --env)")
    parser.add_argument("--ssh-user", default="ec2-user")
    parser.add_argument("--label",    default="", help="Scenario label")
    parser.add_argument("--writes",   type=int, default=200)
    parser.add_argument("--reads",    type=int, default=500)
    parser.add_argument("--concurrency", default="1,2,4,8")
    parser.add_argument("--out", default="results", help="Output directory")

    # Compare mode: run same-region and cross-region and diff them.
    parser.add_argument("--compare", action="store_true",
                        help="Compare same-region vs cross-region")
    parser.add_argument("--same-env",  default="deploy/cluster-same.env")
    parser.add_argument("--cross-env", default="deploy/cluster-cross.env")

    args = parser.parse_args()
    concurrencies = [int(c) for c in args.concurrency.split(",")]
    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_rows: list[dict] = []

    if args.compare:
        # ── Compare mode ──────────────────────────────────────────────────────
        for env_path, label in [(args.same_env, "same-region"),
                                 (args.cross_env, "cross-region")]:
            if not os.path.exists(env_path):
                print(f"WARNING: {env_path} not found, skipping {label}")
                continue
            env = load_env(env_path)
            ips = [env["NODE1_IP"], env["NODE2_IP"], env["NODE3_IP"]]
            key = env.get("KEY_FILE", "")
            user = env.get("SSH_USER", "ec2-user")
            rows = run_scenario(ips, key, user, label,
                                args.writes, args.reads, concurrencies)
            all_rows.extend(rows)
            print_table(rows, label)

        # Side-by-side comparison for write_sequential.
        print(f"\n{'═'*75}")
        print("  Same-region vs Cross-region comparison (write_sequential, c=1)")
        print(f"{'═'*75}")
        print(f"{'Metric':<20} {'Same-region':>15} {'Cross-region':>15}  {'Ratio':>8}")
        print(f"{'─'*75}")
        same_rows  = {r["benchmark"]: r for r in all_rows
                      if r.get("scenario") == "same-region"}
        cross_rows = {r["benchmark"]: r for r in all_rows
                      if r.get("scenario") == "cross-region"}
        for metric in ["throughput_ops_s", "p50_ms", "p95_ms", "p99_ms"]:
            sv = same_rows.get("write_sequential", {}).get(metric, "—")
            cv = cross_rows.get("write_sequential", {}).get(metric, "—")
            try:
                ratio = f"{float(cv)/float(sv):.2f}×"
            except Exception:
                ratio = "—"
            print(f"{metric:<20} {str(sv):>15} {str(cv):>15}  {ratio:>8}")
        print(f"{'═'*75}")

        # Election time comparison.
        se = same_rows.get("leader_election", {}).get("election_time_s", "—")
        ce = cross_rows.get("leader_election", {}).get("election_time_s", "—")
        print(f"\n  Leader election time: same-region={se}s  cross-region={ce}s")

    else:
        # ── Single scenario mode ───────────────────────────────────────────────
        if args.ips:
            ips = args.ips.split(",")
            key  = args.ssh_key or ""
            user = args.ssh_user
            label = args.label or "custom"
        elif os.path.exists(args.env):
            env = load_env(args.env)
            ips  = [env["NODE1_IP"], env["NODE2_IP"], env["NODE3_IP"]]
            key  = env.get("KEY_FILE", "")
            user = env.get("SSH_USER", "ec2-user")
            label = env.get("SCENARIO", args.label or "aws")
        else:
            sys.exit(f"No --ips and no env file at {args.env}. "
                     f"Run ./deploy/deploy.sh first.")

        rows = run_scenario(ips, key, user, label,
                            args.writes, args.reads, concurrencies)
        all_rows.extend(rows)
        print_table(rows, label)

    # Save CSV.
    csv_path = os.path.join(args.out, f"benchmark_aws_{ts}.csv")
    save_csv(all_rows, csv_path)
    print(f"\nRaw results: {csv_path}")
    print("Tip: import the CSV into pandas/matplotlib or Excel for charts.")


if __name__ == "__main__":
    main()
