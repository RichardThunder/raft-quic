#!/usr/bin/env python3
"""
Visualize full-benchmark test results — one PNG per chart.

Usage:
    python3 scripts/visualize_benchmark.py \
        --results-dir results/full-benchmark-20260420_132814 \
        --out-dir results/full-benchmark-20260420_132814/charts
"""

import argparse
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Font: prefer a font that ships with macOS / Linux
# ---------------------------------------------------------------------------
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["font.size"] = 9

PROTOCOL_COLORS = {"quic": "#2196F3", "tcp": "#FF9800"}
SCENARIO_LABELS = {"same-region": "Same-Region", "cross-region": "Cross-Region"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_csv(results_dir: str) -> pd.DataFrame:
    pattern = os.path.join(results_dir, "**", "distributed_benchmark_*.csv")
    files = glob.glob(pattern, recursive=True)
    if not files:
        raise FileNotFoundError(f"No distributed_benchmark_*.csv found under {results_dir}")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df = df.drop_duplicates(subset=["protocol", "cluster_size", "scenario"])
    df["cluster_size"] = df["cluster_size"].astype(int)
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(fig, out_dir: str, name: str):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"[+] {path}")
    plt.close(fig)


def _node_labels(cluster_sizes):
    return [f"{s} nodes" for s in cluster_sizes]


def _legend_outside(ax, fontsize=8, ncol=1):
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
        fontsize=fontsize,
        ncol=ncol,
    )


def _grouped_bars(ax, df_sub, metric, protocols, cluster_sizes, ylabel, title, fmt="{:.2f}", show_legend=True):
    x = np.arange(len(cluster_sizes))
    w = 0.35
    for i, proto in enumerate(protocols):
        sub = df_sub[df_sub["protocol"] == proto].set_index("cluster_size")
        vals = [sub.loc[s, metric] if s in sub.index else 0 for s in cluster_sizes]
        bars = ax.bar(x + (i - 0.5) * w, vals, w,
                      label=proto.upper(), color=PROTOCOL_COLORS[proto], alpha=0.85, zorder=3)
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.02,
                        fmt.format(v), ha="center", va="bottom", fontsize=7.5, color="#333")
    ax.set_title(title, fontweight="bold", pad=6)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(_node_labels(cluster_sizes))
    if show_legend:
        _legend_outside(ax)
    ax.yaxis.set_minor_locator(mticker.AutoMinorLocator())
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------------------
# Chart 1: Write Throughput (ops/s) — same-region vs cross-region side by side
# ---------------------------------------------------------------------------

def chart_write_throughput(df, protocols, cluster_sizes, scenarios, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    fig.suptitle("Write Throughput: QUIC vs TCP", fontsize=11, fontweight="bold")
    for ax, scenario in zip(axes, scenarios):
        _grouped_bars(ax, df[df["scenario"] == scenario],
                      "write_throughput", protocols, cluster_sizes,
                      "Write Throughput (ops/s)",
                      SCENARIO_LABELS[scenario], show_legend=False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
    fig.tight_layout(rect=(0, 0, 0.86, 1))
    _save(fig, out_dir, "01_write_throughput.png")


# ---------------------------------------------------------------------------
# Chart 2: Write Latency Percentiles (P50 / P95 / P99) — line chart per scenario
# ---------------------------------------------------------------------------

def chart_write_latency(df, protocols, cluster_sizes, scenarios, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=False)
    fig.suptitle("Write Latency Percentiles (P50 / P95 / P99)", fontsize=11, fontweight="bold")
    linestyles = {"write_p50_ms": "-", "write_p95_ms": "--", "write_p99_ms": ":"}
    markers = {"quic": "o", "tcp": "s"}
    x = np.arange(len(cluster_sizes))

    for ax, scenario in zip(axes, scenarios):
        for proto in protocols:
            sub = df[(df["scenario"] == scenario) & (df["protocol"] == proto)].set_index("cluster_size")
            for col, ls in linestyles.items():
                pct = col.split("_")[1].upper()
                vals = [sub.loc[s, col] if s in sub.index else np.nan for s in cluster_sizes]
                ax.plot(x, vals, linestyle=ls, marker=markers[proto],
                        color=PROTOCOL_COLORS[proto], linewidth=1.6, markersize=5,
                        label=f"{proto.upper()} {pct}")
        ax.set_title(SCENARIO_LABELS[scenario], fontweight="bold", pad=6)
        ax.set_ylabel("Latency (ms)")
        ax.set_xlabel("Cluster Size")
        ax.set_xticks(x)
        ax.set_xticklabels(_node_labels(cluster_sizes))
        ax.grid(linestyle="--", alpha=0.5)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=7, ncol=1)
    fig.tight_layout(rect=(0, 0, 0.84, 1))
    _save(fig, out_dir, "02_write_latency_percentiles.png")


# ---------------------------------------------------------------------------
# Chart 3: Read Throughput (ops/s)
# ---------------------------------------------------------------------------

def chart_read_throughput(df, protocols, cluster_sizes, scenarios, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    fig.suptitle("Read Throughput: QUIC vs TCP", fontsize=11, fontweight="bold")
    for ax, scenario in zip(axes, scenarios):
        _grouped_bars(ax, df[df["scenario"] == scenario],
                      "read_throughput", protocols, cluster_sizes,
                      "Read Throughput (ops/s)",
                      SCENARIO_LABELS[scenario], show_legend=False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
    fig.tight_layout(rect=(0, 0, 0.86, 1))
    _save(fig, out_dir, "03_read_throughput.png")


# ---------------------------------------------------------------------------
# Chart 4: TCP / QUIC Write Throughput Ratio
# ---------------------------------------------------------------------------

def chart_throughput_ratio(df, protocols, cluster_sizes, scenarios, out_dir):
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.suptitle("TCP / QUIC Write Throughput Ratio", fontsize=11, fontweight="bold")
    scene_colors = {"same-region": "#4CAF50", "cross-region": "#E91E63"}
    x = np.arange(len(cluster_sizes))
    w = 0.35
    for i, scenario in enumerate(scenarios):
        quic = df[(df["scenario"] == scenario) & (df["protocol"] == "quic")].set_index("cluster_size")
        tcp  = df[(df["scenario"] == scenario) & (df["protocol"] == "tcp")].set_index("cluster_size")
        ratios = [tcp.loc[s, "write_throughput"] / quic.loc[s, "write_throughput"]
                  if s in quic.index and quic.loc[s, "write_throughput"] > 0 else np.nan
                  for s in cluster_sizes]
        bars = ax.bar(x + (i - 0.5) * w, ratios, w,
                      label=SCENARIO_LABELS[scenario],
                      color=scene_colors[scenario], alpha=0.85, zorder=3)
        for bar, v in zip(bars, ratios):
            if not np.isnan(v):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                        f"{v:.1f}x", ha="center", va="bottom", fontsize=8)
    ax.axhline(1.0, color="gray", linestyle="--", linewidth=1, label="QUIC = TCP (1x)")
    ax.set_ylabel("Ratio (TCP / QUIC)")
    ax.set_xlabel("Cluster Size")
    ax.set_xticks(x)
    ax.set_xticklabels(_node_labels(cluster_sizes))
    _legend_outside(ax)
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 0.84, 1))
    _save(fig, out_dir, "04_throughput_ratio.png")


# ---------------------------------------------------------------------------
# Chart 5: Write Error Heatmap
# ---------------------------------------------------------------------------

def chart_error_heatmap(df, protocols, cluster_sizes, scenarios, out_dir):
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.suptitle("Write Error Count Heatmap", fontsize=11, fontweight="bold")
    rows = [f"{p.upper()} / {SCENARIO_LABELS[s]}" for p in protocols for s in scenarios]
    data = np.zeros((len(rows), len(cluster_sizes)))
    for ri, (proto, scenario) in enumerate((p, s) for p in protocols for s in scenarios):
        sub = df[(df["protocol"] == proto) & (df["scenario"] == scenario)].set_index("cluster_size")
        for ci, s in enumerate(cluster_sizes):
            data[ri, ci] = sub.loc[s, "write_errors"] if s in sub.index else 0
    im = ax.imshow(data, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(cluster_sizes)))
    ax.set_xticklabels(_node_labels(cluster_sizes))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.set_xlabel("Cluster Size")
    plt.colorbar(im, ax=ax, label="Write Errors")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, str(int(data[i, j])), ha="center", va="center", fontsize=9,
                    color="white" if data[i, j] > data.max() * 0.6 else "black")
    fig.tight_layout()
    _save(fig, out_dir, "05_write_error_heatmap.png")


# ---------------------------------------------------------------------------
# Chart 6: Scalability — Write Throughput vs Cluster Size
# ---------------------------------------------------------------------------

def chart_scalability(df, protocols, cluster_sizes, scenarios, out_dir):
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.suptitle("Write Throughput Scalability vs Cluster Size", fontsize=11, fontweight="bold")
    markers = {"same-region": "o", "cross-region": "^"}
    for scenario in scenarios:
        for proto in protocols:
            sub = df[(df["scenario"] == scenario) & (df["protocol"] == proto)].sort_values("cluster_size")
            ax.plot(sub["cluster_size"], sub["write_throughput"],
                    marker=markers[scenario], color=PROTOCOL_COLORS[proto],
                    linestyle="-" if scenario == "same-region" else "--",
                    linewidth=1.8, markersize=6,
                    label=f"{proto.upper()} / {SCENARIO_LABELS[scenario]}")
    ax.set_xlabel("Cluster Size (nodes)")
    ax.set_ylabel("Write Throughput (ops/s)")
    ax.set_xticks(cluster_sizes)
    _legend_outside(ax, fontsize=7.5, ncol=1)
    ax.grid(linestyle="--", alpha=0.5)
    fig.tight_layout(rect=(0, 0, 0.84, 1))
    _save(fig, out_dir, "06_write_throughput_scalability.png")


# ---------------------------------------------------------------------------
# Chart 7: Cross-Region vs Same-Region P99 Latency Delta
# ---------------------------------------------------------------------------

def chart_cross_region_latency_delta(df, protocols, cluster_sizes, out_dir):
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.suptitle("Cross-Region vs Same-Region P99 Write Latency Delta",
                 fontsize=11, fontweight="bold")
    x = np.arange(len(cluster_sizes))
    w = 0.35
    for i, proto in enumerate(protocols):
        sr = df[(df["scenario"] == "same-region")  & (df["protocol"] == proto)].set_index("cluster_size")
        cr = df[(df["scenario"] == "cross-region") & (df["protocol"] == proto)].set_index("cluster_size")
        delta = [cr.loc[s, "write_p99_ms"] - sr.loc[s, "write_p99_ms"]
                 if s in sr.index and s in cr.index else np.nan
                 for s in cluster_sizes]
        ax.bar(x + (i - 0.5) * w, delta, w,
               label=proto.upper(), color=PROTOCOL_COLORS[proto], alpha=0.85, zorder=3)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_ylabel("P99 Latency Delta (ms)  [cross - same]")
    ax.set_xlabel("Cluster Size")
    ax.set_xticks(x)
    ax.set_xticklabels(_node_labels(cluster_sizes))
    _legend_outside(ax)
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    fig.tight_layout(rect=(0, 0, 0.84, 1))
    _save(fig, out_dir, "07_cross_region_p99_delta.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", default="results/full-benchmark-20260420_132814")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory for chart PNGs (default: <results-dir>/charts)")
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(args.results_dir, "charts")

    df = load_all_csv(args.results_dir)
    print(f"[+] Loaded {len(df)} rows | scenarios: {sorted(df['scenario'].unique())} | "
          f"sizes: {sorted(df['cluster_size'].unique())} | protocols: {sorted(df['protocol'].unique())}")

    protocols     = ["quic", "tcp"]
    cluster_sizes = sorted(df["cluster_size"].unique())
    scenarios     = ["same-region", "cross-region"]

    chart_write_throughput(df, protocols, cluster_sizes, scenarios, out_dir)
    chart_write_latency(df, protocols, cluster_sizes, scenarios, out_dir)
    chart_read_throughput(df, protocols, cluster_sizes, scenarios, out_dir)
    chart_throughput_ratio(df, protocols, cluster_sizes, scenarios, out_dir)
    chart_error_heatmap(df, protocols, cluster_sizes, scenarios, out_dir)
    chart_scalability(df, protocols, cluster_sizes, scenarios, out_dir)
    chart_cross_region_latency_delta(df, protocols, cluster_sizes, out_dir)

    print(f"\n[+] All charts saved to: {out_dir}")


if __name__ == "__main__":
    main()
