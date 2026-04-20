#!/usr/bin/env bash

set -euo pipefail

# 串行执行全量分布式测试（固定并行度=1）
#
# 可通过环境变量覆盖默认值：
#   CLUSTER_SIZES, SCENARIOS, WRITES, DURATION, MONITOR, OUTPUT_DIR
#
# 示例：
#   bash scripts/run_serial_test.sh
#   WRITES=200 DURATION=120 bash scripts/run_serial_test.sh

CLUSTER_SIZES="${CLUSTER_SIZES:-3,5,7}"
SCENARIOS="${SCENARIOS:-same-region,cross-region}"
WRITES="${WRITES:-500}"
DURATION="${DURATION:-300}"
MONITOR="${MONITOR:-true}"
OUTPUT_DIR="${OUTPUT_DIR:-results/full-benchmark-serial-$(date +%Y%m%d_%H%M%S)}"

cmd=(
  bash scripts/aws_distributed_test.sh
  --cluster-sizes "$CLUSTER_SIZES"
  --scenarios "$SCENARIOS"
  --writes "$WRITES"
  --duration "$DURATION"
  --parallel-cases 1
  --output "$OUTPUT_DIR"
)

if [ "$MONITOR" = "true" ]; then
  cmd+=(--monitor)
fi

echo "[*] 串行测试开始"
echo "[*] 输出目录: $OUTPUT_DIR"
echo "[*] 参数: cluster_sizes=$CLUSTER_SIZES scenarios=$SCENARIOS writes=$WRITES duration=$DURATION monitor=$MONITOR"

"${cmd[@]}"

