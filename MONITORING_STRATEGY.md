# 分布式Raft系统监控策略

分析不同节点数量和跨区域部署对Raft和TCP的影响，需要从多个维度监控关键指标。

---

## 📊 分类监控指标体系

### 🎯 第一层：应用性能指标 (必须)

这些指标直接反映系统的功能性能，是最重要的观察指标。

#### 吞吐量指标

| 指标 | 含义 | 监控方法 | 预期变化趋势 |
|------|------|---------|------------|
| **write_throughput** | 写操作吞吐量 (ops/s) | 基准测试直接测量 | 节点↑吞吐↓; 延迟↑吞吐↓ |
| **read_throughput** | 读操作吞吐量 (ops/s) | 基准测试直接测量 | 相对稳定，受延迟影响小 |
| **committed_per_sec** | 每秒提交的日志条数 | Raft状态采样 | 节点↑下降; 延迟↑下降 |

**为什么重要**：
- 吞吐量直接受节点数量影响 (需要更多往返复制)
- 跨区域延迟大幅降低吞吐量
- 两个协议对吞吐的影响不同

**解读方式**:
```
吞吐量下降的原因分析:
- 如果只有3→5节点下降10%: 正常 (Raft复制链变长)
- 如果同区域3→5下降30%: 异常 (可能有网络问题)
- 如果跨区域比同区域下降80%: 正常 (RTT延迟)
```

#### 延迟指标 (关键)

| 指标 | 含义 | 监控方法 | 预期值范围 |
|------|------|---------|-----------|
| **latency_p50** | 50%请求延迟 | 基准测试采样 | 同区: <5ms; 跨区: 150-250ms |
| **latency_p95** | 95%请求延迟 | 基准测试采样 | 同区: <15ms; 跨区: 300-500ms |
| **latency_p99** | 99%请求延迟 | 基准测试采样 | 同区: <30ms; 跨区: 500-1000ms |
| **latency_max** | 最大延迟 | 基准测试采样 | 检查异常值 |

**为什么重要**：
- p50反映基线性能，p99反映最坏情况
- 跨区域时延迟是主要的性能杀手
- 延迟分布形状表示系统稳定性

**解读方式**:
```
延迟分析:
┌─────────────────────────────────────┐
│ 同区域 (正常分布，低方差)           │
│   p50: 5ms                          │
│   p99: 20ms  (p99/p50 = 4x)        │
│   应为钟形分布                      │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ 跨区域 (左偏分布，高方差)           │
│   p50: 180ms                        │
│   p99: 800ms  (p99/p50 = 4.4x)     │
│   会有长尾                          │
└─────────────────────────────────────┘

警告信号:
- p99/p50 > 10: 表示不稳定
- 延迟在30秒内突增: 检查日志同步
```

---

### 🔄 第二层：Raft协议指标 (关键)

这些指标反映Raft共识机制的行为。节点数量和延迟会显著影响这些指标。

#### Leader选举指标

| 指标 | 含义 | 监控方法 | 预期变化 |
|------|------|---------|---------|
| **election_time_ms** | 选举耗时 | Raft日志/HTTP API | 节点↑增加; 延迟↑增加10倍 |
| **election_count** | 选举总次数 | Raft计数器 | 不应该频繁(>1次/分钟异常) |
| **term_changes** | 任期变化次数 | Raft状态 | term应该单调递增 |

**为什么重要**：
- 节点数增加 → 选举所需往返次数↑
- 跨区域延迟大 → 选举超时设置必须更大
- 频繁选举表示集群不稳定

**预期数据**:
```
同区域3节点:      选举时间 < 500ms   (心跳超时150ms, 选举超时300ms)
同区域5节点:      选举时间 < 800ms   (需要更多投票往返)
同区域7节点:      选举时间 < 1000ms  (更多投票轮数)

跨区域3节点:      选举时间 2-5s      (RTT 150-300ms)
跨区域5节点:      选举时间 3-8s      (更多投票轮数)
跨区域7节点:      选举时间 5-12s     (显著增加)

关键: 跨区域时需要调整Raft超时参数!
     HeartbeatTimeout = 1s
     ElectionTimeout = 2-3s
```

**解读方式**:
```
分析选举时间增长:
- 同区域 3→5→7: 线性增长 → 正常
- 跨区域 3→5→7: 指数增长 → 需要优化超时参数
- 选举时间突增到10秒: 检查网络分区或GC暂停
```

#### 日志复制指标 (核心)

| 指标 | 含义 | 监控方法 | 关键观察 |
|------|------|---------|---------|
| **committed_index** | 已提交的日志索引 | Raft状态 | 应该单调递增 |
| **last_applied** | 应用到FSM的日志索引 | Raft状态 | 应该≤ committed_index |
| **replication_lag** | committed - leader的日志长度 | 计算得出 | 反映复制速度 |
| **entries_replicated_per_sec** | 每秒复制的日志条数 | Raft统计 | 受节点数和延迟影响 |
| **follower_next_index** | 每个follower的下一个日志位置 | Raft内部 | 用于检测慢节点 |

**为什么重要**：
- committed_index反映集群能达成共识的速度
- replication_lag大 → 某些节点落后
- entries_replicated_per_sec是有效吞吐量的直接反映

**预期数据**:
```
同区域3节点:
  entries_replicated_per_sec ≈ write_throughput (接近100%)
  replication_lag < 10           (复制及时)
  
同区域5节点:
  entries_replicated_per_sec ≈ write_throughput * 0.85-0.90
  replication_lag < 20           (需要更多轮次)
  
跨区域3节点:
  entries_replicated_per_sec ≈ write_throughput * 0.70-0.80
  replication_lag 50-100         (RTT累积)
```

**关键指标关系**:
```
有效吞吐量 = entries_replicated_per_sec = write_throughput * replication_efficiency

replication_efficiency 分析:
- 同区域3节点: ~95% (几乎无损)
- 同区域5节点: ~85% (每多一个节点损失5%)
- 同区域7节点: ~75% (链变长)

跨区域3节点: ~75% (RTT重复)
跨区域5节点: ~60% (RTT + 节点数双重影响)
```

#### Leader稳定性指标

| 指标 | 含义 | 监控方法 | 异常阈值 |
|------|------|---------|---------|
| **leader_changes** | Leader变更次数 | 检测leader_id变化 | >1次/小时 → 异常 |
| **heartbeat_timeout_count** | 心跳超时次数 | 日志统计 | > 0 → 需要调查 |
| **requests_rejected** | 被拒绝的请求 | 应用层计数 | > 1% → 检查leader |

**预期行为**:
```
正常情况:
- leader_changes = 0 (整个测试期间只有一个leader)
- heartbeat_timeout_count = 0 (心跳不应超时)
- requests_rejected < 0.1% (偶发)

异常情况:
- leader_changes > 3: 检查网络分区或GC暂停
- heartbeat_timeout频繁: HeartbeatTimeout设置太小
- requests_rejected > 5%: leader可能过载
```

---

### 🌐 第三层：网络传输指标 (重要)

区分TCP和QUIC的性能差异，以及跨区域网络的影响。

#### TCP特定指标

| 指标 | 含义 | 监控方法 | 跨区域影响 |
|------|------|---------|----------|
| **tcp_connections_established** | 已建立连接数 | netstat/ss | 应该=节点对数 |
| **tcp_retransmit_rate** | TCP重传率 | /proc/net/tcp | >1% → 网络问题 |
| **tcp_window_size** | TCP接收窗口大小 | TCP流监控 | 跨区域需要更大 |
| **round_trip_time** | RTT延迟 | ping/tcpdump | 关键指标 |

**为什么重要**：
- TCP单连接 → 受RTT影响严重
- 跨区域RTT可能导致重传
- 窗口大小限制吞吐量: 带宽延迟积(BDP)

**BDP计算**:
```
带宽延迟积 = 网络速度 × RTT

同区域:
  BDP = 1Gbps × 5ms = 625 KB    (小)
  
跨区域:
  BDP = 1Gbps × 200ms = 25 MB   (大)
  
如果TCP窗口 < BDP → 吞吐量受限

示例:
  跨区域RTT=200ms, TCP窗口=64KB
  最大吞吐 ≈ 64KB / 200ms = 320 KB/s ≈ 2.5 Mbps
  (远低于实际网络带宽)
```

**TCP问题诊断**:
```
观察项目:
1. tcp_retransmit_rate
   - 同区域 > 0.1%: 异常
   - 跨区域 < 2%: 正常
   
2. tcp_window_size
   - 跨区域应该 > 1 MB (自动调整)
   - 手工限制 < 256 KB: 性能杀手
   
3. 连接创建速率
   - 如果频繁重建: 检查close_wait状态
```

#### QUIC特定指标

| 指标 | 含义 | 监控方法 | 多流优势 |
|------|------|---------|---------|
| **quic_connection_count** | QUIC连接数 | quic-go库计数 | 应该<节点对数 |
| **quic_stream_count** | 活跃流数 | quic-go库统计 | 多流并发 |
| **quic_packet_loss_rate** | QUIC包丢失率 | 协议统计 | 丢包重传快 |
| **quic_flow_control** | 流控事件 | 库事件计数 | 应该很少 |

**为什么重要**：
- QUIC多流 → 不同流相互独立，不阻塞
- QUIC 0-RTT → 握手快
- 包丢失恢复更快

**预期行为**:
```
QUIC连接利用率:
- 同区域: 1个连接 × N个并发流 (高效)
- 跨区域: 1个连接 × N个并发流 (仍然高效)

TCP连接利用率:
- 同区域: N个连接 (串行处理)
- 跨区域: 更多连接 (应对延迟)
```

#### 网络质量指标 (跨区域关键)

| 指标 | 含义 | 监控方法 | 测量频率 |
|------|------|---------|---------|
| **latency_node_to_node** | 节点间RTT | ping/icmp | 每10秒 |
| **jitter** | 延迟抖动 | RTT标准差 | 连续采样 |
| **packet_loss_rate** | 丢包率 | mtr/loss统计 | 长期平均 |
| **bandwidth_utilization** | 带宽利用率 | 网络流量 / 链路容量 | 连续采样 |

**跨区域预期值**:
```
同区域 (ap-east-1):
  RTT: 2-5 ms
  Jitter: 0.5-1 ms
  Loss: 0%
  Utilization: <5%

跨区域 (ap-east-1 ↔ us-east-1):
  RTT: 150-200 ms
  Jitter: 10-50 ms
  Loss: 0-0.5%
  Utilization: 10-30%

跨区域 (ap-east-1 ↔ eu-west-1):
  RTT: 200-250 ms
  Jitter: 20-100 ms
  Loss: 0-1%
  Utilization: 15-40%
```

**网络问题诊断**:
```
延迟突增 (同区域5ms→50ms):
  → 检查GC暂停、网络拥塞
  
丢包率上升 (0% → 5%+):
  → 链路问题、接收端缓冲满
  
Jitter增加 (1ms → 50ms):
  → 转发延迟增加、设备过载
```

---

### 💻 第四层：系统资源指标 (必要)

监控CPU、内存、磁盘等，用于诊断性能瓶颈。

#### CPU指标

| 指标 | 含义 | 监控方法 | 预期值 |
|------|------|---------|--------|
| **cpu_user_percent** | 用户态CPU使用 | /proc/stat | 30-60% |
| **cpu_system_percent** | 系统态CPU使用 | /proc/stat | 10-20% |
| **cpu_iowait_percent** | I/O等待 | /proc/stat | <5% |
| **context_switch_rate** | 上下文切换频率 | /proc/stat | <10000/s |

**关键观察**:
```
同区域3节点:
  cpu_user: 40-50%     (处理请求)
  cpu_system: 10-15%   (系统调用)
  iowait: <2%          (很少IO阻塞)

同区域5/7节点:
  cpu_user: 50-70%     (更多Raft处理)
  cpu_system: 15-25%   (更多锁竞争)
  iowait: <2%          (日志是内存操作)

跨区域:
  cpu_user: 20-40%     (等待网络)
  iowait: <1%          (不是IO问题)
```

**CPU瓶颈诊断**:
```
观察1: cpu_user持续90%+ → CPU饱和
  - 原因: 串行化处理、锁竞争
  - 解决: 增加并发或优化算法

观察2: context_switch_rate > 20000/s → 切换过频
  - 原因: 过多goroutine竞争
  - 解决: 调整worker数量

观察3: iowait > 5% → 磁盘IO问题
  - 原因: 日志写入瓶颈
  - 解决: 使用更快的存储或异步写入
```

#### 内存指标

| 指标 | 含义 | 监控方法 | 正常范围 |
|------|------|---------|---------|
| **resident_memory_mb** | 常驻内存 | /proc/[pid]/status | 100-500 MB |
| **heap_objects** | 堆对象数 | Go runtime | 取决于负载 |
| **gc_frequency** | GC频率 | Go runtime | 1-10次/秒 |
| **gc_pause_ms** | GC暂停时间 | Go runtime | <100ms |

**节点数影响**:
```
内存使用与日志大小:
  write_count × entry_size + 索引结构

3节点, 500写操作:
  ~50 MB (日志 + 索引 + 缓冲)

5节点, 500写操作:
  ~60 MB (多一些元数据)

7节点, 500写操作:
  ~80 MB (更多元数据)

跨区域影响: +10-20% (缓冲更多未提交数据)
```

**GC暂停风险**:
```
同区域: GC暂停 < 100ms → 通常可接受
跨区域: GC暂停 > 200ms → 可能导致心跳超时
        
如果RTT=200ms, HeartbeatTimeout=1s, GC暂停=500ms
→ GC会导致5个心跳周期无响应 → 可能触发选举
```

#### 磁盘指标

| 指标 | 含义 | 监控方法 | 关键观察 |
|------|------|---------|---------|
| **disk_write_kb_s** | 磁盘写入速率 | iostat | 反映日志写入 |
| **disk_read_kb_s** | 磁盘读取速率 | iostat | 反映快照恢复 |
| **fsync_latency_ms** | fsync延迟 | 应用日志 | 影响提交延迟 |

**预期行为**:
```
同区域:
  write_rate: 1-10 MB/s (日志写入)
  read_rate: 0-5 MB/s   (快照恢复)
  fsync延迟: <10ms      (本地磁盘)

跨区域:
  write_rate: 1-10 MB/s (相同)
  read_rate: 0-5 MB/s   (相同)
  fsync延迟: <10ms      (不受网络影响)
```

---

## 🔍 指标分析矩阵

### 按"节点数量"维度的指标变化

```
指标                    3节点    5节点    7节点    预期趋势
─────────────────────────────────────────────────────
吞吐量 (ops/s)         846      742      620      ↓ 线性/指数递减
p99延迟 (ms)           18       22       26       ↑ 线性递增
选举时间 (ms)          300      450      600      ↑ 线性递增
committed_index增速    高       中       低       ↓ 递减
replication_lag        低       中       高       ↑ 递增
日志复制时间           5ms      8ms      12ms     ↑ 递增
心跳超时事件           0        0        0        保持0
leader变更             0        0        0        保持0
CPU使用率              50%      60%      70%      ↑ 轻微递增
上下文切换             8000/s   10000/s  12000/s  ↑ 递增
```

### 按"跨区域"维度的指标变化

```
指标                    同区域   跨区域   倍数关系
─────────────────────────────────────────────────────
吞吐量 (ops/s)         846      75       ~ 1/11x
p99延迟 (ms)           18       2000     ~ 111x
选举时间 (ms)          300      2500     ~ 8x
网络RTT (ms)           5        200      ~ 40x
packet_loss_rate       0%       0.2%     显著增加
TCP重传率              0.1%     1-2%     显著增加
连接建立时间           <5ms     150-300ms 30-60x
TCP窗口调整           快速      缓慢      受延迟制约
```

### 按"协议类型"维度的指标比较

```
指标                    TCP      QUIC     优势
─────────────────────────────────────────────────────
吞吐量                 790      846      QUIC +7%
p99延迟                21       18       QUIC -14%
连接建立延迟           10ms     2ms      QUIC显著优
多流支持               否       是       QUIC显著优
包丢失恢复             慢       快       QUIC显著优
同区域CPU使用         60%      55%      QUIC略优
跨区域CPU使用         40%      38%      QUIC略优
```

---

## 📈 关键监控场景和对应指标

### 场景1: 诊断"为什么5节点比3节点慢"

必须收集的指标:
1. **write_throughput** (应该↓12%)
2. **latency_p99** (应该↑20%)
3. **replication_lag** (应该↑150%)
4. **committed_index** (增速↓)
5. **cpu_user_percent** (应该↑10%)
6. **context_switch_rate** (应该↑)
7. **follower_next_index** (检查慢节点)

分析模板:
```
如果吞吐下降>20%:
  a) 检查replication_lag是否>30
     → Yes: 复制链变长 (正常)
     → No: 检查b)
  
  b) 检查CPU是否饱和 (>90%)
     → Yes: CPU瓶颈 (不正常，应该<70%)
     → No: 检查c)
  
  c) 检查某个follower的next_index远落后
     → Yes: 这个节点有问题 (网络/磁盘)
     → No: 系统设计限制
```

### 场景2: 诊断"跨区域为什么慢10倍"

必须收集的指标:
1. **latency_node_to_node** (RTT)
2. **latency_p99** (应该≈RTT × 某个倍数)
3. **committed_index** (增速大幅下降)
4. **tcp_window_size** (检查是否调整)
5. **tcp_retransmit_rate** (应该<2%)
6. **packet_loss_rate** (应该<1%)
7. **heartbeat_timeout_events** (应该=0)

分析模板:
```
跨区域性能分析:

RTT测量:
  同区域: 5ms → 期望p99 ≈ 5ms × 5 = 25ms
  跨区域: 200ms → 期望p99 ≈ 200ms × 10-20 = 2000-4000ms

如果实际p99 > 期望:
  a) 检查packet_loss_rate
     → > 2%: 链路质量问题
     
  b) 检查tcp_retransmit_rate
     → > 5%: TCP调整不足
     
  c) 检查heartbeat_timeout_events
     → > 0: HeartbeatTimeout设置太小
     
如果实际p99 < 期望:
  → 可能说明系统设计很高效 ✓
```

### 场景3: 诊断"TCP vs QUIC哪个更好"

必须收集的指标:
1. **write_throughput** (吞吐对比)
2. **latency_p50/p95/p99** (延迟对比)
3. **tcp_connections_established** vs **quic_stream_count**
4. **tcp_retransmit_rate** vs **quic_packet_loss_rate**
5. **cpu_user_percent** (资源效率)
6. **gc_pause_ms** (QUIC可能触发更多内存分配)

对比矩阵:
```
在同区域 (低延迟):
  ┌─────────────────┬──────────┬──────────┬─────────┐
  │ 指标            │ TCP      │ QUIC     │ 赢家    │
  ├─────────────────┼──────────┼──────────┼─────────┤
  │ 吞吐量 (ops/s)  │ 790      │ 846      │ QUIC ✓  │
  │ p99 (ms)        │ 21       │ 18       │ QUIC ✓  │
  │ CPU (%)         │ 60       │ 55       │ QUIC ✓  │
  │ 连接数          │ 多       │ 1        │ QUIC ✓  │
  │ GC暂停 (ms)     │ <10      │ 10-20    │ TCP ✓   │
  └─────────────────┴──────────┴──────────┴─────────┘

在跨区域 (高延迟):
  ┌─────────────────┬──────────┬──────────┬─────────┐
  │ 指标            │ TCP      │ QUIC     │ 赢家    │
  ├─────────────────┼──────────┼──────────┼─────────┤
  │ 吞吐量 (ops/s)  │ 70       │ 75       │ QUIC ✓  │
  │ p99 (ms)        │ 2100     │ 2000     │ QUIC ✓  │
  │ CPU (%)         │ 40       │ 38       │ QUIC ✓  │
  │ 重传率 (%)      │ 1.5      │ 0.8      │ QUIC ✓  │
  │ 连接重建        │ 频繁     │ 无       │ QUIC ✓  │
  └─────────────────┴──────────┴──────────┴─────────┘
```

---

## 🎯 最少监控指标集合

如果只能监控少数指标，优先级顺序:

### 优先级 1 (必须) - 3个指标
```
1. write_throughput    → 核心性能指标
2. latency_p99         → 最坏情况反映
3. latency_node_to_node (RTT) → 环境基线
```

### 优先级 2 (强烈推荐) - 5个指标
```
4. election_time       → Raft稳定性
5. replication_lag     → 复制效率
6. cpu_user_percent    → 资源瓶颈
7. heartbeat_timeout_count → 时钟同步
8. packet_loss_rate    → 网络质量
```

### 优先级 3 (扩展) - 8个指标
```
9. latency_p50         → 基线性能
10. latency_p95        → 普遍性能
11. committed_index增速 → 整体吞吐
12. leader_changes     → 集群稳定性
13. tcp_retransmit_rate (TCP only) → 协议效率
14. quic_stream_count (QUIC only) → 多流使用
15. context_switch_rate → 并发度
16. gc_pause_ms        → 延迟稳定性
```

---

## 📊 监控数据收集方式

### 对于不同节点数量的对比

```bash
# 收集基准数据
for cluster_size in 3 5 7; do
    python3 scripts/distributed_benchmark.py \
      --cluster-sizes $cluster_size \
      --scenarios same-region \
      --monitor \
      --duration 300 \
      --out results/node_scaling_$cluster_size
done

# 指标提取
for size_dir in results/node_scaling_*; do
    python3 -c "
    import csv
    with open('$size_dir/distributed_benchmark_*.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            print(f\"Size: {row['cluster_size']}, \
                  Throughput: {row['write_throughput']}, \
                  P99: {row['write_p99_ms']}\")
    "
done
```

### 对于跨区域的对比

```bash
# 同区域数据
python3 scripts/distributed_benchmark.py \
  --scenarios same-region \
  --monitor \
  --out results/network_same

# 跨区域数据
python3 scripts/distributed_benchmark.py \
  --scenarios cross-region \
  --monitor \
  --out results/network_cross

# 网络延迟对比
bash -c "
  echo 'RTT Measurements:'
  echo 'Same Region:' && ping -c 5 <node-ip> | grep rtt
  echo 'Cross Region:' && ping -c 5 <cross-region-node-ip> | grep rtt
"
```

### 对于TCP vs QUIC的对比

```bash
# TCP基准
python3 scripts/distributed_benchmark.py \
  --skip-quic \
  --monitor \
  --out results/tcp_benchmark

# QUIC基准
python3 scripts/distributed_benchmark.py \
  --skip-tcp \
  --monitor \
  --out results/quic_benchmark

# 对标分析
python3 scripts/analyze_distributed_results.py \
  --results results \
  --out comparison_report.html
```

---

## ✅ 监控检查清单

部署前:
- [ ] 定义了清晰的性能目标
- [ ] 列出了需要监控的指标
- [ ] 准备了数据采集脚本
- [ ] 设置了告警阈值

测试运行中:
- [ ] 收集实时监控数据
- [ ] 检查异常值
- [ ] 记录任何事件 (GC, 网络变化等)
- [ ] 监控资源是否枯尽

测试完成后:
- [ ] 验证数据完整性
- [ ] 检查数据一致性
- [ ] 生成对比报告
- [ ] 归档原始数据

---

**关键记住**: 
- 不同节点数量 → 关注吞吐和复制延迟
- 跨区域部署 → 关注网络延迟和选举稳定性
- TCP vs QUIC → 关注连接效率和多流优势

每个维度的监控焦点不同，综合这些指标可以全面理解系统行为。
