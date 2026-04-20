#!/usr/bin/env python3
"""
generate_sample_results.py – Create sample benchmark results for visualization

Generates synthetic benchmark data that represents typical Raft-over-QUIC
performance characteristics for visualization and testing.

Usage:
    python3 scripts/generate_sample_results.py [--output DIR]
"""

import argparse
import csv
import os
import random
import sys
from datetime import datetime
from pathlib import Path


def generate_sample_benchmarks(output_dir):
    """Generate sample benchmark CSV with realistic data."""

    # Realistic benchmark results
    benchmarks = [
        # Sequential writes
        {
            'benchmark': 'write_sequential',
            'concurrency': 1,
            'n': 50,
            'throughput_ops_s': 320.5,
            'p50_ms': 2.8,
            'p95_ms': 4.2,
            'p99_ms': 5.8,
            'mean_ms': 3.1,
            'min_ms': 2.1,
            'max_ms': 8.5,
            'errors': 0,
        },
        # Concurrent writes - C=4
        {
            'benchmark': 'write_concurrent',
            'concurrency': 4,
            'n': 50,
            'throughput_ops_s': 650.2,
            'p50_ms': 5.5,
            'p95_ms': 8.3,
            'p99_ms': 12.4,
            'mean_ms': 6.2,
            'min_ms': 4.2,
            'max_ms': 18.7,
            'errors': 0,
        },
        # Concurrent writes - C=8
        {
            'benchmark': 'write_concurrent',
            'concurrency': 8,
            'n': 50,
            'throughput_ops_s': 845.6,
            'p50_ms': 8.2,
            'p95_ms': 12.5,
            'p99_ms': 18.3,
            'mean_ms': 9.5,
            'min_ms': 6.5,
            'max_ms': 28.4,
            'errors': 0,
        },
        # Sequential reads
        {
            'benchmark': 'read_sequential',
            'concurrency': 1,
            'n': 100,
            'throughput_ops_s': 1520.8,
            'p50_ms': 0.58,
            'p95_ms': 0.92,
            'p99_ms': 1.24,
            'mean_ms': 0.66,
            'min_ms': 0.42,
            'max_ms': 2.15,
            'errors': 0,
        },
        # Leader election timing
        {
            'benchmark': 'leader_election',
            'concurrency': 1,
            'n': 1,
            'throughput_ops_s': '',
            'p50_ms': '',
            'p95_ms': '',
            'p99_ms': '',
            'mean_ms': '',
            'min_ms': '',
            'max_ms': '',
            'election_time_s': 0.387,
            'errors': 0,
        },
    ]

    # Write CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_file = os.path.join(output_dir, f'benchmark_{timestamp}.csv')

    fieldnames = [
        'benchmark', 'concurrency', 'n', 'throughput_ops_s',
        'p50_ms', 'p95_ms', 'p99_ms', 'mean_ms', 'min_ms', 'max_ms', 'errors'
    ]

    os.makedirs(output_dir, exist_ok=True)

    with open(csv_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for bench in benchmarks:
            row = {field: bench.get(field, '') for field in fieldnames}
            if bench['benchmark'] == 'leader_election':
                row['mean_ms'] = bench['election_time_s']
            writer.writerow(row)

    print(f"✓ Sample benchmark data generated: {csv_file}")
    return csv_file


def generate_sample_test_log(output_dir):
    """Generate a sample test execution log."""

    log_content = """╔════════════════════════════════════════════════════════════════╗
║   Raft-over-QUIC Comprehensive Test Suite                      ║
║   Date: 2026-04-19 16:30:45                                    ║
╚════════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════
TEST 1: Build Verification
═══════════════════════════════════════════════════════════════

[INFO] Building raftd binary...
[PASS] Build successful
raftd: Mach-O 64-bit executable arm64

═══════════════════════════════════════════════════════════════
TEST 2: Code Quality (go fmt, go vet)
═══════════════════════════════════════════════════════════════

[PASS] Code formatting OK
[PASS] go vet passed

═══════════════════════════════════════════════════════════════
TEST 3: Docker Cluster Setup & Functional Tests
═══════════════════════════════════════════════════════════════

[INFO] Cleaning up old containers...
[INFO] Building and starting cluster...
[PASS] Docker cluster started
[INFO] Waiting for cluster to stabilize (30s)...

[INFO] Running functional tests...
[PASS] All functional tests passed

═══════════════════════════════════════════════════════════════
TEST 4: Performance Benchmarks
═══════════════════════════════════════════════════════════════

[INFO] Running performance benchmarks...
  Sequential writes: n=50 …
  Concurrent writes: n=50, concurrency=4 …
  Concurrent writes: n=50, concurrency=8 …
  Sequential reads: n=100 …
  Leader election timing …
[PASS] Benchmarks completed
[PASS] Benchmark results saved

═══════════════════════════════════════════════════════════════
TEST SUMMARY
═══════════════════════════════════════════════════════════════

✓ Build verification
✓ Code quality checks
✓ Docker cluster tests
✓ Performance benchmarks

Test suite completed successfully!
"""

    log_file = os.path.join(output_dir, 'sample_test_log.txt')
    os.makedirs(output_dir, exist_ok=True)

    with open(log_file, 'w') as f:
        f.write(log_content)

    print(f"✓ Sample test log generated: {log_file}")
    return log_file


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', '-o', default='./test_results',
                       help='Output directory for sample data')

    args = parser.parse_args()

    csv_file = generate_sample_benchmarks(args.output)
    log_file = generate_sample_test_log(args.output)

    print(f"\n✓ Sample data generated successfully!")
    print(f"  Output directory: {args.output}")
    print(f"\nNext steps:")
    print(f"  1. Generate visualizations:")
    print(f"     python3 scripts/visualize.py --input {csv_file} --output {args.output}")
    print(f"  2. Generate HTML report:")
    print(f"     python3 scripts/generate_report.py --benchmark {csv_file} --output {args.output}/report.html")


if __name__ == '__main__':
    main()
