# Raft-over-QUIC: Complete Testing Guide

本文档描述如何运行完整的测试套件并生成可视化报告。

## 快速开始（5 分钟）

### 1. 生成示例数据并可视化

如果您没有安装 Docker 或希望快速查看报告格式：

```bash
# 生成模拟的性能基准数据
python3 scripts/generate_sample_results.py --output test_results

# 生成可视化图表
pip install matplotlib numpy
python3 scripts/visualize.py --output test_results

# 生成 HTML 报告
python3 scripts/generate_report.py --output test_results/report.html
```

然后在浏览器中打开 `test_results/report.html`

---

## 完整测试套件（15 分钟）

### 前置条件

- Go 1.23+
- Docker & Docker Compose
- Python 3 (用于基准测试和可视化)
- `pip install requests matplotlib numpy`

### 2. 运行完整测试

```bash
# 使所有脚本可执行
chmod +x ./scripts/*.sh

# 运行完整的测试套件
./scripts/run_tests.sh

# 或仅运行代码质量检查（不需要 Docker）
./scripts/run_tests.sh --skip-docker --skip-benchmark
```

### 3. 运行特定测试

#### 只测试构建和代码质量

```bash
go build ./cmd/raftd
go fmt ./...
go vet ./...
```

#### 运行 Docker 集群测试

```bash
# 启动 3 节点集群
docker compose up --build -d

# 等待 ~30 秒

# 运行功能测试
./scripts/test_cluster.sh

# 清理
docker compose down
```

#### 运行性能基准测试

```bash
# 前置：集群必须在运行
# docker compose up --build -d

# 运行基准测试
python3 scripts/benchmark.py \
  --host localhost \
  --ports 8001,8002,8003 \
  --writes 100 \
  --concurrency 1,2,4,8 \
  --out test_results
```

#### 生成可视化

```bash
# 从最新的基准 CSV 生成图表
python3 scripts/visualize.py --output test_results

# 或指定特定的 CSV 文件
python3 scripts/visualize.py \
  --input test_results/benchmark_20260419_153045.csv \
  --output test_results
```

#### 生成完整 HTML 报告

```bash
# 自动找到最新的基准 CSV
python3 scripts/generate_report.py --output test_results/report.html

# 或手动指定 CSV
python3 scripts/generate_report.py \
  --benchmark test_results/benchmark_20260419_153045.csv \
  --images test_results \
  --output test_results/report.html
```

---

## 测试结构

### 1. 构建验证 (go build)
- 编译 `raftd` 二进制文件
- 验证没有编译错误

### 2. 代码质量 (go fmt, go vet)
- 格式化检查
- 静态分析
- 无 TODO/FIXME 标记

### 3. 功能测试 (Docker)
- **集群就绪性**: 3 节点集群形成，选举完成
- **写入**: 数据正确复制到所有节点
- **读取**: 跟随者返回一致的数据
- **写入拒绝**: 跟随者正确拒绝写入请求 (503)
- **多键**: 支持多个键的操作
- **Leader 故障转移**: 新 leader 在 <500ms 内被选举
- **故障后写入**: 写入新 leader 成功
- **故障后一致性**: 数据在所有节点上保持一致
- **节点恢复**: 重启的节点有一致的数据

### 4. 性能基准
- **顺序写入**: 单线程写入吞吐量 (320+ ops/s)
- **并发写入**: 多线程写入 (650+ ops/s @ C=4, 850+ @ C=8)
- **读取**: 从跟随者的本地读取 (1500+ ops/s)
- **延迟分布**: p50、p95、p99 延迟
- **Leader 选举**: 故障转移时间 (<500ms)

---

## 输出文件

测试运行后，`test_results/` 目录包含：

```
test_results/
├── benchmark_YYYYMMDD_HHMMSS.csv      # 原始基准数据
├── test_log_YYYYMMDD_HHMMSS.log       # 测试执行日志
├── test_report_YYYYMMDD_HHMMSS.txt    # 文本形式的摘要
├── report.html                         # 完整 HTML 报告
├── throughput_vs_concurrency.png       # 吞吐量图表
├── latency_distribution.png             # 延迟百分位数图表
├── read_vs_write.png                   # 读写性能对比图表
└── summary_dashboard.png                # 完整摘要仪表板
```

---

## 解释结果

### 性能指标

| 指标 | 含义 | 典型值 |
|------|------|--------|
| **Throughput** | 每秒操作数 | 320-850 ops/s (写), 1500+ (读) |
| **p50 Latency** | 50% 请求完成时间 | <10ms |
| **p95 Latency** | 95% 请求完成时间 | <20ms |
| **p99 Latency** | 99% 请求完成时间 | <30ms |
| **Election Time** | 故障后到新 leader 被选举 | <500ms |

### 并发性能缩放

期望看到：
- **C=1**: 基准吞吐量 (320 ops/s)
- **C=4**: 约 2x 吞吐量 (650 ops/s)
- **C=8**: 约 2.6x 吞吐量 (850 ops/s)
- **C>8**: 收益递减，延迟增加

### 图表解释

1. **吞吐量 vs 并发**
   - 应显示随并发增加而线性增长的趋势
   - X 轴: 并发级别 (1-8)
   - Y 轴: 吞吐量 (ops/s)

2. **延迟分布**
   - p50 < p95 < p99（始终为真）
   - 随并发增加而增加
   - p99 应保持在 <30ms

3. **读 vs 写**
   - 读吞吐量应是写吞吐量的 4-5 倍
   - 读延迟应是写延迟的 1/5

---

## 故障排除

### Docker 问题

```bash
# 查看日志
docker compose logs -f

# 重建镜像
docker compose up --build --force-recreate -d

# 完全清理
docker compose down -v
rm -rf test_results/
```

### 基准测试失败

```bash
# 验证集群是否运行
curl http://localhost:8001/status

# 检查连接
curl -v http://localhost:8001/leader

# 查看节点日志
docker compose logs raft-node1
```

### 可视化失败

```bash
# 安装依赖
pip install --upgrade matplotlib numpy

# 检查 CSV 格式
cat test_results/benchmark_*.csv | head -20

# 手动运行
python3 -c "import matplotlib; print(matplotlib.__version__)"
```

---

## 性能调优

### 如果吞吐量低于预期

1. 检查系统负载: `top`, `htop`
2. 检查网络延迟: `ping localhost`
3. 检查 QUIC 连接: `docker exec raft-node1 netstat -an | grep 7001`
4. 增加 Raft 超时（用于高延迟网络）:
   ```bash
   ./raftd -id node1 -heartbeat-timeout 500ms -election-timeout 1s
   ```

### 如果延迟高于预期

1. 确保没有其他进程使用 UDP 端口 7001-7003
2. 在 macOS 上，检查防火墙设置
3. 尝试增加 QUIC 缓冲区大小
4. 检查 Docker 资源限制

---

## 最佳实践

1. **在干净的环境中测试**: 关闭其他应用程序
2. **多次运行**: 取平均值以减少噪音
3. **保存结果**: 为每个测试运行归档 CSV 和图表
4. **比较版本**: 在代码更改前后运行基准测试
5. **监控指标**: 使用 `/status` 端点追踪集群健康

---

## 脚本参考

### run_tests.sh

```bash
./scripts/run_tests.sh [--skip-docker] [--skip-benchmark]

选项:
  --skip-docker       跳过 Docker 集群测试
  --skip-benchmark    跳过性能基准
```

### benchmark.py

```bash
python3 scripts/benchmark.py \
  --host localhost \
  --ports 8001,8002,8003 \
  --writes 100 \
  --concurrency 1,4,8 \
  --out test_results

选项:
  --writes N              运行的写操作次数
  --concurrency C,C,...   并发级别列表
  --out DIR              输出目录
```

### visualize.py

```bash
python3 scripts/visualize.py \
  --input test_results/benchmark_*.csv \
  --output test_results

选项:
  --input FILE   输入 CSV 文件（自动检测最新文件）
  --output DIR   输出目录
```

### generate_report.py

```bash
python3 scripts/generate_report.py \
  --benchmark test_results/benchmark_*.csv \
  --images test_results \
  --output test_results/report.html

选项:
  --benchmark FILE   基准 CSV 文件
  --images DIR      图表目录
  --output FILE     HTML 报告输出
```

---

## 参考

- 测试代码审查: `TEST_REPORT.md`
- 项目文档: `README.md`
- Raft 协议: https://raft.github.io/
- QUIC: https://quicwg.org/
