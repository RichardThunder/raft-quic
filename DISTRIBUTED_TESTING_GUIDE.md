# 分布式性能测试完整指南

本指南说明如何在AWS上运行Raft-over-QUIC的分布式性能测试，对比TCP和QUIC在不同集群规模和部署场景下的性能表现。

---

## 📋 测试框架概述

### 核心组件

1. **distributed_benchmark.py** - 主基准测试执行器
   - 支持多种集群规模 (3, 5, 7 节点)
   - 支持不同部署场景 (同区域、跨区域)
   - 测试TCP和QUIC协议
   - 收集吞吐量、延迟、读性能等指标

2. **collect_metrics.py** - 监控指标收集工具
   - 实时采集系统指标 (CPU, 内存, 网络, 磁盘)
   - 收集Raft协议级指标 (term, leader, committed_index)
   - 收集网络性能指标 (延迟, 连接数)
   - 背景监控线程运行

3. **aws_distributed_test.sh** - 主测试编排脚本
   - 协调所有测试组件的执行
   - 管理集群的部署和清理
   - 并发运行基准测试和监控
   - 生成汇总报告

4. **analyze_distributed_results.py** - 结果分析工具
   - 解析所有采集的性能指标
   - 生成对比分析报告
   - 创建HTML可视化报告
   - 输出性能趋势分析

---

## 🚀 快速开始

### 前置条件

```bash
# 1. 安装依赖
brew install terraform aws-cli go python3

# 2. 配置AWS凭据
aws configure

# 3. 验证配置
aws sts get-caller-identity
```

### 最简单的测试 (5分钟)

```bash
# 运行单个3节点同区域集群测试
python3 scripts/distributed_benchmark.py \
  --cluster-sizes 3 \
  --scenarios same-region \
  --writes 100 \
  --duration 60 \
  --out results/quick_test

# 分析结果
python3 scripts/analyze_distributed_results.py \
  --results results/quick_test \
  --out results/quick_test_report.html
```

---

## 📊 完整测试流程

### 1. 单组件测试 - 仅基准测试

```bash
# 测试3、5、7节点集群
python3 scripts/distributed_benchmark.py \
  --cluster-sizes 3,5,7 \
  --scenarios same-region \
  --writes 500 \
  --duration 300 \
  --out results/baseline_test

# 预期时间: ~45分钟
# 预期成本: ~$3-5 (取决于EC2启动时间)
```

### 2. 带监控的完整测试

```bash
# 启用详细的系统监控
python3 scripts/distributed_benchmark.py \
  --cluster-sizes 3,5,7 \
  --scenarios same-region,cross-region \
  --writes 500 \
  --duration 300 \
  --monitor \
  --ssh-key deploy/terraform/same-region/raft-key.pem \
  --out results/full_test

# 预期时间: ~2小时
# 预期成本: ~$10-15
```

### 3. 使用编排脚本运行完整套件

```bash
# 最完整的自动化测试
bash scripts/aws_distributed_test.sh \
  --cluster-sizes 3,5,7 \
  --scenarios same-region,cross-region \
  --writes 500 \
  --duration 300 \
  --monitor \
  --ssh-key deploy/terraform/same-region/raft-key.pem \
  --output results/complete_test_$(date +%Y%m%d_%H%M%S)

# 预期时间: ~2-3小时
# 预期成本: ~$15-25
```

---

## 📈 监控指标说明

### 基准测试指标

| 指标 | 含义 | 正常范围 |
|------|------|---------|
| write_throughput | 写入吞吐量 (ops/s) | 300-1000 |
| write_p50_ms | 50%延迟 (ms) | <5 |
| write_p95_ms | 95%延迟 (ms) | <15 |
| write_p99_ms | 99%延迟 (ms) | <30 |
| read_throughput | 读取吞吐量 (ops/s) | 1000-3000 |

### 系统指标

| 指标 | 含义 | 正常范围 |
|------|------|---------|
| cpu_usage_percent | CPU使用率 | 20-80% |
| memory_usage_percent | 内存使用率 | 30-70% |
| network_tx_bytes | 网络发送字节 | - |
| disk_write_kb_s | 磁盘写入速率 | <1000 KB/s |

### Raft指标

| 指标 | 含义 | 正常范围 |
|------|------|---------|
| is_leader | 是否为Leader | 每个集群1个true |
| current_term | 当前任期 | ≥1 |
| committed_index | 已提交索引 | 递增 |
| replication_lag | 复制延迟 | 0-100 |

---

## 🔍 测试场景详解

### 同区域测试 (same-region)

**部署方式**: 所有3个节点部署在同一AWS区域 (ap-east-1 香港)

**特点**:
- 低网络延迟 (<5ms)
- 高可用性
- 代表局域网场景

**预期性能**:
```
集群规模    写吞吐(ops/s)    p99延迟(ms)
3节点      800-900         15-20
5节点      700-800         18-25
7节点      600-700         20-30
```

### 跨区域测试 (cross-region)

**部署方式**: 3个节点分别部署在3个不同AWS区域:
- node1: ap-east-1 (香港)
- node2: us-east-1 (美国东)
- node3: eu-west-1 (欧洲西)

**特点**:
- 高网络延迟 (150-300ms)
- 跨域部署
- 代表地理分布式场景

**预期性能**:
```
集群规模    写吞吐(ops/s)    p99延迟(ms)
3节点      50-100          1500-2500
5节点      30-50           2000-3000
7节点      20-40           2500-4000
```

---

## 🔄 TCP vs QUIC 对比

### 测试方式

两个协议使用相同的应用逻辑:
- QUIC: 使用quic-go库，多流设计
- TCP: 标准HTTP，单连接

### 预期差异

**同区域场景**:
```
指标            QUIC        TCP        对比
吞吐量         800 ops/s   750 ops/s   QUIC略优 (1.07x)
p99延迟        18 ms       20 ms       QUIC略优
网络开销       低          低          相当
```

**跨区域场景**:
```
指标            QUIC        TCP        对比
吞吐量         75 ops/s    70 ops/s    QUIC略优 (1.07x)
p99延迟        2000 ms     2100 ms     QUIC略优
网络开销       低          低          相当
```

### 性能差异原因

1. **多流设计**: QUIC支持多个并发流，在高并发下有优势
2. **连接建立**: QUIC握手较快 (1-RTT vs 3-way TCP)
3. **拥塞控制**: QUIC使用更现代的拥塞控制算法
4. **Raft开销**: Raft的影响主要来自日志复制，协议层面差异有限

---

## 📊 结果解读

### 性能指标对标

| 系统 | 写吞吐 | 读吞吐 | p99延迟 | 说明 |
|------|--------|--------|---------|------|
| 本项目 (3节点) | 800 ops/s | 1500 ops/s | 18ms | QUIC，同区域 |
| etcd (3节点) | 1000-2000 | 10000 | <50ms | 一般负载 |
| Consul (3节点) | 500-1000 | 5000 | <100ms | 一般负载 |

### 集群规模影响

```
吞吐量 (ops/s)
900 │     ●
    │    ╱ ╲
800 │   ╱   ╲
    │  ╱     ●
700 │ ╱
    │●
600 └─────────────
    3   5   7  节点数

关键观察:
- 3→5节点: 吞吐下降12% (Raft开销增加)
- 5→7节点: 吞吐下降15% (选举时间增加)
```

### 同区域 vs 跨区域

```
p99延迟 (ms)
3000 │
     │           ╱● (跨区域7节点)
2500 │         ╱
     │       ●
2000 │     ╱
     │   ●
1500 │ ╱
     │
1000 │
     │
500  │   ●
     │ ╱   ╲
100  │●      ● (同区域)
     └───────────────
     3   5   7  节点数
```

---

## 💾 数据存储和分析

### 输出目录结构

```
results/
├── complete_test_YYYYMMDD_HHMMSS/
│   ├── logs/                          # 详细日志
│   │   ├── benchmark.log
│   │   └── monitor.log
│   ├── results/                       # CSV结果文件
│   │   ├── distributed_benchmark_*.csv
│   │   └── ...
│   ├── metrics/                       # 监控指标数据
│   │   ├── metrics_*_system_*.csv
│   │   ├── metrics_*_raft_*.csv
│   │   └── metrics_*_network_*.csv
│   ├── SUMMARY_REPORT.md              # 文本摘要
│   └── analysis_report.html           # 详细HTML报告
```

### 数据格式

**基准测试CSV** (`distributed_benchmark_*.csv`):
```csv
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,timestamp
quic,3,same-region,846.5,5.2,12.3,18.4,1520.0,2026-04-20T10:00:00
tcp,3,same-region,790.2,6.1,14.2,21.3,1450.0,2026-04-20T10:05:00
...
```

**系统监控CSV** (`metrics_*_system_*.csv`):
```csv
timestamp,node,cpu_usage_percent,memory_usage_percent,network_rx_bytes,network_tx_bytes,disk_write_kb_s
2026-04-20T10:00:00,node1,45.2,52.3,1024000,2048000,100.5
...
```

---

## 🛠️ 高级用法

### 跳过部署，仅运行基准测试

如果集群已存在，可以跳过部署阶段:

```bash
python3 scripts/distributed_benchmark.py \
  --cluster-sizes 3 \
  --scenarios same-region \
  --skip-deploy \
  --out results/quick_bench
```

### 仅测试某个协议

```bash
# 只测试QUIC
python3 scripts/distributed_benchmark.py \
  --skip-tcp \
  --out results/quic_only

# 只测试TCP
python3 scripts/distributed_benchmark.py \
  --skip-quic \
  --out results/tcp_only
```

### 自定义集群规模

```bash
# 测试2、4、6节点
python3 scripts/distributed_benchmark.py \
  --cluster-sizes 2,4,6 \
  --out results/custom_sizes
```

### 后处理已有数据

```bash
# 不需要重新测试，直接分析已有结果
python3 scripts/analyze_distributed_results.py \
  --results results/complete_test_20260420_100000 \
  --out results/analysis_report.html
```

---

## 💰 成本预估

### 按测试类型

| 测试类型 | 集群规模 | 时长 | 预计成本 |
|----------|---------|------|---------|
| 快速测试 | 3节点 | 10分钟 | $0.01 |
| 基本测试 | 3×3节点 | 1小时 | $0.10 |
| 完整测试 | 3×2×3节点 | 2小时 | $0.25 |
| 全面测试 | 3×2×2×3节点 | 4小时 | $0.50 |

### 成本优化

```bash
# 1. 使用Free Tier (首12个月免费)
# 2. 快速测试后立即销毁资源
./deploy/teardown.sh same-region
./deploy/teardown.sh cross-region

# 3. 跳过监控以减少运行时间
# (移除 --monitor 参数)

# 4. 减少写操作次数
--writes 100  # 而不是 500

# 5. 缩短监控时长
--duration 60  # 而不是 300
```

---

## 🔍 故障排除

### 问题1: "No credentials found"

```bash
# 重新配置AWS凭据
aws configure

# 或使用环境变量
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```

### 问题2: Terraform 初始化失败

```bash
# 清理缓存
rm -rf deploy/terraform/*/.terraform*

# 重试
python3 scripts/distributed_benchmark.py ...
```

### 问题3: SSH 连接超时

```bash
# 检查安全组规则
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=raft-quic-*"

# 检查节点IP
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=raft-quic" \
  --query 'Reservations[].Instances[].[PublicIpAddress,State.Name]'
```

### 问题4: 基准测试失败

```bash
# 检查节点是否已启动
curl http://<node-ip>:8001/status

# 查看日志
tail -f results/*/logs/*benchmark.log
```

### 问题5: 监控数据为空

```bash
# 检查SSH密钥权限
chmod 600 deploy/terraform/*/raft-key.pem

# 手动测试SSH连接
ssh -i deploy/terraform/same-region/raft-key.pem \
    ec2-user@<node-ip> \
    'top -bn1 | head -1'
```

---

## 📚 参考资源

### 文档
- [AWS_DEPLOYMENT_GUIDE.md](AWS_DEPLOYMENT_GUIDE.md) - AWS部署详细指南
- [AWS_GET_CREDENTIALS.md](AWS_GET_CREDENTIALS.md) - AWS凭据获取指南
- [TESTING.md](TESTING.md) - 本地测试方法

### 项目
- [Raft协议](https://raft.github.io/)
- [QUIC规范](https://quicwg.org/)
- [quic-go库](https://github.com/quic-go/quic-go)

---

## ✅ 检查清单

部署前确认:
- [ ] AWS凭据已配置
- [ ] 有足够的AWS配额 (≥3个t3.micro)
- [ ] Terraform已安装 (≥1.5)
- [ ] Go已安装 (≥1.23)
- [ ] Python3已安装 (≥3.7)
- [ ] SSH密钥文件权限正确 (chmod 600)

测试期间:
- [ ] 检查AWS成本告警
- [ ] 监控日志输出
- [ ] 定期检查实例运行状态

测试后:
- [ ] 所有资源已清理
- [ ] 数据已备份
- [ ] 报告已生成

---

**版本**: 1.0  
**最后更新**: 2026-04-20  
**维护者**: Richard
