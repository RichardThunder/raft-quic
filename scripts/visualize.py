#!/usr/bin/env python3
"""
visualize.py – Generate visualization charts from benchmark results

Reads CSV benchmark files and generates:
  • Throughput vs Concurrency plot
  • Latency distribution (p50, p95, p99)
  • Comparison charts for different test scenarios

Usage:
    python3 scripts/visualize.py [--input FILE] [--output DIR]
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.ticker import FuncFormatter
    import numpy as np
except ImportError:
    print("matplotlib required: pip install matplotlib numpy")
    sys.exit(1)


def read_benchmark_csv(filepath):
    """Read benchmark CSV and return parsed data."""
    data = {
        'sequential_writes': [],
        'concurrent_writes': [],
        'reads': [],
        'leader_election': None,
    }

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bench_name = row.get('benchmark', '').strip()

            if bench_name == 'write_sequential':
                data['sequential_writes'].append({
                    'concurrency': int(row.get('concurrency', 1)),
                    'throughput': float(row.get('throughput_ops_s', 0)),
                    'p50': float(row.get('p50_ms', 0)),
                    'p95': float(row.get('p95_ms', 0)),
                    'p99': float(row.get('p99_ms', 0)),
                    'mean': float(row.get('mean_ms', 0)),
                    'n': int(row.get('n', 0)),
                })
            elif bench_name == 'write_concurrent':
                data['concurrent_writes'].append({
                    'concurrency': int(row.get('concurrency', 1)),
                    'throughput': float(row.get('throughput_ops_s', 0)),
                    'p50': float(row.get('p50_ms', 0)),
                    'p95': float(row.get('p95_ms', 0)),
                    'p99': float(row.get('p99_ms', 0)),
                    'mean': float(row.get('mean_ms', 0)),
                    'n': int(row.get('n', 0)),
                })
            elif bench_name == 'read_sequential':
                data['reads'].append({
                    'throughput': float(row.get('throughput_ops_s', 0)),
                    'p50': float(row.get('p50_ms', 0)),
                    'p95': float(row.get('p95_ms', 0)),
                    'p99': float(row.get('p99_ms', 0)),
                    'mean': float(row.get('mean_ms', 0)),
                    'n': int(row.get('n', 0)),
                })
            elif bench_name == 'leader_election':
                data['leader_election'] = {
                    'election_time_s': float(row.get('election_time_s', 0)),
                }

    return data


def plot_throughput_vs_concurrency(data, output_dir):
    """Plot write throughput vs concurrency level."""
    fig, ax = plt.subplots(figsize=(10, 6))

    writes = data['concurrent_writes']
    if not writes:
        print("No concurrent write data available")
        return

    writes = sorted(writes, key=lambda x: x['concurrency'])
    concurrencies = [w['concurrency'] for w in writes]
    throughputs = [w['throughput'] for w in writes]

    # Plot
    ax.plot(concurrencies, throughputs, 'o-', linewidth=2, markersize=8,
            color='#2E86AB', markerfacecolor='#A23B72', markeredgewidth=2)
    ax.fill_between(concurrencies, throughputs, alpha=0.2, color='#2E86AB')

    ax.set_xlabel('Concurrency Level', fontsize=12, fontweight='bold')
    ax.set_ylabel('Throughput (ops/sec)', fontsize=12, fontweight='bold')
    ax.set_title('Write Throughput vs Concurrency\n(Raft-over-QUIC)',
                 fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.set_xticks(concurrencies)

    # Add value labels on points
    for x, y in zip(concurrencies, throughputs):
        ax.annotate(f'{y:.1f}', xy=(x, y), xytext=(0, 10),
                   textcoords='offset points', ha='center', fontsize=9)

    plt.tight_layout()
    output_path = os.path.join(output_dir, 'throughput_vs_concurrency.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    plt.close()


def plot_latency_distribution(data, output_dir):
    """Plot latency percentiles (p50, p95, p99)."""
    fig, ax = plt.subplots(figsize=(12, 6))

    writes = data['concurrent_writes']
    if not writes:
        print("No concurrent write data available")
        return

    writes = sorted(writes, key=lambda x: x['concurrency'])
    concurrencies = [str(w['concurrency']) for w in writes]

    p50s = [w['p50'] for w in writes]
    p95s = [w['p95'] for w in writes]
    p99s = [w['p99'] for w in writes]

    x = np.arange(len(concurrencies))
    width = 0.25

    bars1 = ax.bar(x - width, p50s, width, label='p50', color='#06A77D', alpha=0.8)
    bars2 = ax.bar(x, p95s, width, label='p95', color='#F77F00', alpha=0.8)
    bars3 = ax.bar(x + width, p99s, width, label='p99', color='#D62828', alpha=0.8)

    ax.set_xlabel('Concurrency Level', fontsize=12, fontweight='bold')
    ax.set_ylabel('Latency (milliseconds)', fontsize=12, fontweight='bold')
    ax.set_title('Write Latency Distribution\n(Raft-over-QUIC)',
                 fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(concurrencies)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis='y', linestyle='--')

    # Add value labels on bars
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.1f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    output_path = os.path.join(output_dir, 'latency_distribution.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    plt.close()


def plot_read_vs_write(data, output_dir):
    """Compare read and write performance."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Sequential write
    seq_writes = data['sequential_writes']
    if seq_writes:
        w = seq_writes[0]
        write_throughput = w['throughput']
        write_latency = w['mean']
    else:
        write_throughput = 0
        write_latency = 0

    # Read
    reads = data['reads']
    if reads:
        r = reads[0]
        read_throughput = r['throughput']
        read_latency = r['mean']
    else:
        read_throughput = 0
        read_latency = 0

    # Throughput comparison
    categories = ['Write', 'Read']
    throughputs = [write_throughput, read_throughput]
    colors = ['#2E86AB', '#A23B72']

    bars = ax1.bar(categories, throughputs, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax1.set_ylabel('Throughput (ops/sec)', fontsize=11, fontweight='bold')
    ax1.set_title('Read vs Write Throughput\n(Sequential)', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3, axis='y', linestyle='--')

    for bar, val in zip(bars, throughputs):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.1f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Latency comparison
    latencies = [write_latency, read_latency]
    bars = ax2.bar(categories, latencies, color=colors, alpha=0.7, edgecolor='black', linewidth=2)
    ax2.set_ylabel('Latency (milliseconds)', fontsize=11, fontweight='bold')
    ax2.set_title('Read vs Write Latency (Mean)\n(Sequential)', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y', linestyle='--')

    for bar, val in zip(bars, latencies):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.2f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

    plt.tight_layout()
    output_path = os.path.join(output_dir, 'read_vs_write.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    plt.close()


def plot_summary_dashboard(data, output_dir):
    """Create a comprehensive summary dashboard."""
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

    # Title
    fig.suptitle('Raft-over-QUIC: Comprehensive Benchmark Summary',
                fontsize=16, fontweight='bold', y=0.98)

    # 1. Throughput vs Concurrency
    ax1 = fig.add_subplot(gs[0, :])
    writes = sorted(data['concurrent_writes'], key=lambda x: x['concurrency'])
    if writes:
        conc = [w['concurrency'] for w in writes]
        tput = [w['throughput'] for w in writes]
        ax1.plot(conc, tput, 'o-', linewidth=2, markersize=8,
                color='#2E86AB', markerfacecolor='#A23B72', markeredgewidth=2)
        ax1.fill_between(conc, tput, alpha=0.15, color='#2E86AB')
        ax1.set_xlabel('Concurrency', fontsize=10)
        ax1.set_ylabel('Throughput (ops/s)', fontsize=10)
        ax1.set_title('Write Throughput vs Concurrency', fontsize=11, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.set_xticks(conc)

    # 2. Latency Percentiles
    ax2 = fig.add_subplot(gs[1, 0])
    if writes:
        conc_labels = [str(w['concurrency']) for w in writes]
        p50 = [w['p50'] for w in writes]
        p95 = [w['p95'] for w in writes]
        p99 = [w['p99'] for w in writes]
        x = np.arange(len(conc_labels))
        width = 0.25
        ax2.bar(x - width, p50, width, label='p50', color='#06A77D', alpha=0.8)
        ax2.bar(x, p95, width, label='p95', color='#F77F00', alpha=0.8)
        ax2.bar(x + width, p99, width, label='p99', color='#D62828', alpha=0.8)
        ax2.set_ylabel('Latency (ms)', fontsize=10)
        ax2.set_title('Latency Distribution', fontsize=11, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels(conc_labels)
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3, axis='y')

    # 3. Read vs Write
    ax3 = fig.add_subplot(gs[1, 1])
    seq_writes = data['sequential_writes']
    reads = data['reads']
    if seq_writes and reads:
        ops = ['Write\n(Sequential)', 'Read\n(Sequential)']
        tputs = [seq_writes[0]['throughput'], reads[0]['throughput']]
        colors_comp = ['#2E86AB', '#A23B72']
        bars = ax3.bar(ops, tputs, color=colors_comp, alpha=0.7, edgecolor='black', linewidth=1.5)
        ax3.set_ylabel('Throughput (ops/s)', fontsize=10)
        ax3.set_title('Read vs Write Performance', fontsize=11, fontweight='bold')
        ax3.grid(True, alpha=0.3, axis='y')
        for bar, val in zip(bars, tputs):
            ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{val:.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

    # 4. Statistics summary table
    ax4 = fig.add_subplot(gs[2, :])
    ax4.axis('tight')
    ax4.axis('off')

    table_data = []
    if writes:
        table_data.append(['Metric', 'Value', 'Unit'])
        table_data.append(['—————', '—————', '————'])
        w_max = max(writes, key=lambda x: x['throughput'])
        table_data.append([f'Peak Throughput (C={w_max["concurrency"]})',
                          f'{w_max["throughput"]:.2f}', 'ops/sec'])
        avg_p99 = np.mean([w['p99'] for w in writes])
        table_data.append(['Avg p99 Latency', f'{avg_p99:.2f}', 'ms'])
        if reads:
            table_data.append(['Read Throughput', f'{reads[0]["throughput"]:.2f}', 'ops/sec'])
        if data['leader_election']:
            le = data['leader_election']['election_time_s']
            table_data.append(['Leader Election Time', f'{le:.3f}', 'sec'])

    if table_data:
        table = ax4.table(cellText=table_data, cellLoc='center', loc='center',
                         colWidths=[0.4, 0.3, 0.2])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)

        # Style header row
        for i in range(3):
            table[(0, i)].set_facecolor('#2E86AB')
            table[(0, i)].set_text_props(weight='bold', color='white')

        # Alternate row colors
        for i in range(2, len(table_data)):
            for j in range(3):
                if i % 2 == 0:
                    table[(i, j)].set_facecolor('#F0F0F0')

    plt.tight_layout()
    output_path = os.path.join(output_dir, 'summary_dashboard.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', '-i',
                       help='Input CSV benchmark file')
    parser.add_argument('--output', '-o', default='./test_results',
                       help='Output directory for charts')

    args = parser.parse_args()

    # Find input file
    if args.input:
        input_file = args.input
    else:
        # Find latest benchmark CSV
        results_dir = Path(args.output)
        if not results_dir.exists():
            print(f"Results directory not found: {args.output}")
            print("Run benchmarks first: python3 scripts/benchmark.py")
            sys.exit(1)

        csv_files = list(results_dir.glob('benchmark_*.csv'))
        if not csv_files:
            print(f"No benchmark CSV files found in {args.output}")
            print("Run benchmarks first: python3 scripts/benchmark.py")
            sys.exit(1)

        input_file = str(max(csv_files, key=os.path.getctime))

    print(f"Reading: {input_file}")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Parse data
    try:
        data = read_benchmark_csv(input_file)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        sys.exit(1)

    print(f"Generating visualizations in {args.output}...")

    # Generate plots
    plot_throughput_vs_concurrency(data, args.output)
    plot_latency_distribution(data, args.output)
    plot_read_vs_write(data, args.output)
    plot_summary_dashboard(data, args.output)

    print(f"\n✓ All visualizations generated successfully!")
    print(f"  Output directory: {args.output}")


if __name__ == '__main__':
    main()
