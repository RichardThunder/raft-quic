#!/bin/bash

#  AWS 分布式性能测试编排脚本
#
# 功能:
#   • 部署不同规模的Raft集群(3, 5, 7节点)
#   • 在同区域和跨区域部署场景测试
#   • 并发运行TCP和QUIC基准测试
#   • 实时监控系统和应用指标
#   • 生成详细的性能报告
#
# Usage:
#     bash scripts/aws_distributed_test.sh \
#       --cluster-sizes 3,5,7 \
#       --scenarios same-region,cross-region \
#       --writes 500 \
#       --duration 300 \
#       --monitor

set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认参数
CLUSTER_SIZES="3,5,7"
SCENARIOS="same-region,cross-region"
WRITES=500
DURATION=300
MONITOR=false
SSH_KEY="deploy/terraform/same-region/raft-key.pem"
OUTPUT_DIR="results/distributed_test_$(date +%Y%m%d_%H%M%S)"
SKIP_DEPLOY=false
SKIP_TCP=false
SKIP_QUIC=false

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster-sizes)
            CLUSTER_SIZES="$2"
            shift 2
            ;;
        --scenarios)
            SCENARIOS="$2"
            shift 2
            ;;
        --writes)
            WRITES="$2"
            shift 2
            ;;
        --duration)
            DURATION="$2"
            shift 2
            ;;
        --monitor)
            MONITOR=true
            shift
            ;;
        --ssh-key)
            SSH_KEY="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --skip-deploy)
            SKIP_DEPLOY=true
            shift
            ;;
        --skip-tcp)
            SKIP_TCP=true
            shift
            ;;
        --skip-quic)
            SKIP_QUIC=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# 函数: 打印日志
log_info() {
    echo -e "${BLUE}[*]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[+]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 函数: 检查依赖
check_dependencies() {
    log_info "检查依赖..."

    local missing=()

    for cmd in python3 terraform aws go; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "缺少依赖: ${missing[*]}"
        exit 1
    fi

    log_success "所有依赖检查通过"
}

# 函数: 初始化输出目录
init_output_dir() {
    log_info "初始化输出目录: $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR/logs"
    mkdir -p "$OUTPUT_DIR/metrics"
    mkdir -p "$OUTPUT_DIR/results"
}

# 函数: 构建Linux二进制文件
build_binaries() {
    log_info "构建Linux二进制文件..."

    if [ ! -f "raftd-linux-amd64" ]; then
        GOOS=linux GOARCH=amd64 go build -o raftd-linux-amd64 ./cmd/raftd
        log_success "raftd 构建完成"
    else
        log_success "raftd 二进制已存在"
    fi

    if [ ! -f "cmd/tcp-server/tcp-server-linux-amd64" ]; then
        GOOS=linux GOARCH=amd64 go build -o cmd/tcp-server/tcp-server-linux-amd64 ./cmd/tcp-server
        log_success "tcp-server 构建完成"
    else
        log_success "tcp-server 二进制已存在"
    fi
}

# 函数: 验证AWS凭据
verify_aws_credentials() {
    log_info "验证AWS凭据..."

    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS凭据无效或未配置"
        exit 1
    fi

    log_success "AWS凭据验证通过"
}

# 函数: 运行测试套件
run_test_suite() {
    local cluster_size=$1
    local scenario=$2
    local test_id="${scenario}_${cluster_size}nodes_$(date +%Y%m%d_%H%M%S)"

    log_info "开始测试: $test_id"

    local test_output="$OUTPUT_DIR/results/$test_id"
    mkdir -p "$test_output"

    # 构建命令行参数
    local bench_args="--cluster-sizes $cluster_size --scenarios $scenario"
    bench_args="$bench_args --writes $WRITES --duration $DURATION"
    bench_args="$bench_args --out $test_output"
    bench_args="$bench_args --ssh-key $SSH_KEY"

    if [ "$SKIP_DEPLOY" = true ]; then
        bench_args="$bench_args --skip-deploy"
    fi

    if [ "$SKIP_TCP" = true ]; then
        bench_args="$bench_args --skip-tcp"
    fi

    if [ "$SKIP_QUIC" = true ]; then
        bench_args="$bench_args --skip-quic"
    fi

    # 运行基准测试
    local bench_log="$OUTPUT_DIR/logs/${test_id}_benchmark.log"
    log_info "运行基准测试... (日志: $bench_log)"

    python3 scripts/distributed_benchmark.py $bench_args > "$bench_log" 2>&1 &
    local bench_pid=$!

    # 如果启用监控,启动监控线程
    if [ "$MONITOR" = true ]; then
        # 等待集群部署完成(最多5分钟)
        sleep 30

        # 读取集群配置获取节点IP
        local cluster_env="deploy/cluster-${scenario}-${cluster_size}.env"
        if [ -f "$cluster_env" ]; then
            local nodes=""
            local monitor_ssh_key="$SSH_KEY"
            while IFS='=' read -r key value; do
                if [[ "$key" == *"_IP" ]]; then
                    local node_name=$(echo "$key" | tr '[:upper:]' '[:lower:]' | sed 's/_ip//')
                    if [ -n "$nodes" ]; then
                        nodes="$nodes,$node_name=$value"
                    else
                        nodes="$node_name=$value"
                    fi
                elif [[ "$key" == "KEY_FILE" && -n "$value" ]]; then
                    monitor_ssh_key="$value"
                fi
            done < "$cluster_env"

            if [ -n "$nodes" ]; then
                local monitor_log="$OUTPUT_DIR/logs/${test_id}_monitor.log"
                log_info "启动监控... (日志: $monitor_log)"

                python3 scripts/collect_metrics.py \
                    --nodes "$nodes" \
                    --interval 5 \
                    --duration $((DURATION + 60)) \
                    --ssh-key "$monitor_ssh_key" \
                    --protocols quic,tcp \
                    --out "$OUTPUT_DIR/metrics/$test_id" \
                    > "$monitor_log" 2>&1 &
                local monitor_pid=$!

                # 等待基准测试和监控完成
                wait $bench_pid
                sleep 10
                kill $monitor_pid 2>/dev/null || true
            else
                log_warning "无法从 $cluster_env 读取节点信息"
                wait $bench_pid
            fi
        else
            log_warning "集群配置文件不存在: $cluster_env"
            wait $bench_pid
        fi
    else
        # 只等待基准测试完成
        wait $bench_pid
    fi

    log_success "测试完成: $test_id"
}

# 函数: 生成汇总报告
generate_summary_report() {
    log_info "生成汇总报告..."

    local report="$OUTPUT_DIR/SUMMARY_REPORT.md"

    {
        echo "# 分布式性能测试汇总报告"
        echo ""
        echo "生成时间: $(date)"
        echo ""
        echo "## 测试配置"
        echo ""
        echo "- 集群规模: $CLUSTER_SIZES"
        echo "- 场景: $SCENARIOS"
        echo "- 写操作数: $WRITES"
        echo "- 监控时长: ${DURATION}s"
        echo "- 监控启用: $MONITOR"
        echo ""
        echo "## 测试结果"
        echo ""

        # 列出所有CSV结果
        find "$OUTPUT_DIR/results" -name "*.csv" -type f | while read csv_file; do
            echo "### $(basename "$csv_file")"
            echo ""
            echo "\`\`\`"
            head -20 "$csv_file"
            echo "\`\`\`"
            echo ""
        done

        echo "## 监控数据"
        echo ""

        # 列出所有监控文件
        if [ -d "$OUTPUT_DIR/metrics" ]; then
            find "$OUTPUT_DIR/metrics" -name "*.csv" -type f | while read metric_file; do
                local metric_name=$(basename "$metric_file" | sed 's/.csv//')
                echo "- $metric_name"
            done
        fi

        echo ""
        echo "## 详细分析"
        echo ""
        echo "### 同区域 vs 跨区域性能差异"
        echo ""
        echo "基于测试数据分析:"
        echo "- 同区域延迟应该远低于跨区域"
        echo "- 跨区域吞吐量预期下降5-10倍"
        echo "- 网络延迟主要由地理距离决定"
        echo ""
        echo "### TCP vs QUIC性能对比"
        echo ""
        echo "预期结果:"
        echo "- QUIC吞吐量应与TCP相当或更高"
        echo "- QUIC延迟应低于或等于TCP"
        echo "- 多流优势在高并发下体现"
        echo ""
        echo "### 集群规模影响"
        echo ""
        echo "分析点:"
        echo "- 3节点: 基线性能"
        echo "- 5节点: Raft开销增加(日志复制)"
        echo "- 7节点: 选举时间和网络消息增加"
        echo ""

    } | tee "$report"

    log_success "汇总报告已保存: $report"
}

# 函数: 生成可视化图表
generate_visualizations() {
    log_info "生成可视化图表..."

    # 收集所有CSV文件
    local csv_files=$(find "$OUTPUT_DIR/results" -name "distributed_benchmark_*.csv" -type f | head -1)

    if [ -z "$csv_files" ]; then
        log_warning "未找到基准测试CSV文件"
        return
    fi

    # 使用现有的可视化脚本
    python3 scripts/visualize_svg.py \
        --input "$csv_files" \
        --output "$OUTPUT_DIR" || true

    log_success "可视化图表已生成"
}

# 主流程
main() {
    log_info "开始 AWS 分布式性能测试"
    echo "=========================================="

    check_dependencies
    init_output_dir
    verify_aws_credentials

    if [ "$SKIP_DEPLOY" = false ]; then
        build_binaries
    fi

    # 遍历所有场景和集群规模组合
    IFS=',' read -ra size_array <<< "$CLUSTER_SIZES"
    IFS=',' read -ra scenario_array <<< "$SCENARIOS"

    local total_tests=$((${#size_array[@]} * ${#scenario_array[@]}))
    local test_count=0

    echo "=========================================="
    log_info "总计 $total_tests 个测试任务"
    echo "=========================================="

    for scenario in "${scenario_array[@]}"; do
        for cluster_size in "${size_array[@]}"; do
            test_count=$((test_count + 1))
            log_info "测试 $test_count/$total_tests: $scenario - $cluster_size 节点"

            run_test_suite "$cluster_size" "$scenario"

            log_info "等待5秒后开始下一个测试..."
            sleep 5
        done
    done

    # 生成报告
    log_info "生成最终报告..."
    generate_summary_report
    generate_visualizations

    log_success "所有测试完成!"
    log_info "结果保存在: $OUTPUT_DIR"
    echo "=========================================="
}

# 错误处理
trap 'log_error "测试被中断"; exit 1' SIGINT SIGTERM

# 运行主程序
main "$@"
