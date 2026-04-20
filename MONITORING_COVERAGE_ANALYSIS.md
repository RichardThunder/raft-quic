# 监控覆盖分析报告

## 📊 现有代码的监控覆盖情况

### ✅ 已实现的指标

#### 1. 基准测试指标 (完整覆盖)
```
✓ write_throughput         (ops/s)
✓ write_p50_ms             (ms)
✓ write_p95_ms             (ms)
✓ write_p99_ms             (ms)
✓ read_throughput          (ops/s)
```
**位置**: `distributed_benchmark.py` - `DistributedBenchmark.run_benchmark()`  
**收集方式**: 直接基准测试测量

#### 2. Raft协议指标 (部分覆盖)
```
✓ is_leader                (boolean)
✓ current_term             (integer)
✓ committed_index          (integer)
✓ last_applied             (integer)
✓ last_log_index           (integer)
✓ replication_lag          (committed - last_log_index)
✓ peers                    (count)
```
**位置**: `collect_metrics.py` - `MetricsCollector.collect_raft_metrics()`  
**收集方式**: HTTP `/status` API

#### 3. 系统资源指标 (较完整)
```
✓ cpu_usage_percent        (%)
✓ memory_usage_percent     (%)
✓ memory_used_gb           (GB)
✓ network_rx_bytes         (bytes)
✓ network_tx_bytes         (bytes)
✓ disk_read_kb_s           (KB/s)
✓ disk_write_kb_s          (KB/s)
✓ load_average_1m          (1-minute average)
✓ load_average_5m          (5-minute average)
✓ load_average_15m         (15-minute average)
✓ raftd_cpu_percent        (% of raftd process)
✓ raftd_rss_mb             (MB resident memory)
```
**位置**: `collect_metrics.py` - `MetricsCollector.collect_system_metrics()`  
**收集方式**: SSH执行系统命令 (top, free, iostat, ps等)

#### 4. 网络指标 (有限)
```
✓ established_connections  (count)
✓ operation_latency_ms     (ms, 单个操作)
```
**位置**: `collect_metrics.py` - `MetricsCollector.collect_network_metrics()`

---

### ❌ 缺失的关键指标

#### 第一优先级 - 必需指标

**选举相关** (影响分析节点数量影响):
```
✗ election_time_ms         (选举耗时)
✗ election_count           (选举总次数)
✗ last_election_time       (上次选举时间)
✗ election_duration_stats  (选举时间的p50/p95/p99)
```
**为什么重要**: 直接反映节点数增加对Raft稳定性的影响

**心跳/选举超时** (影响跨区域稳定性):
```
✗ heartbeat_timeout_count  (心跳超时次数)
✗ heartbeat_timeout_events (超时事件时间戳)
```
**为什么重要**: 跨区域测试中关键诊断指标，心跳超时会触发选举

**Leader稳定性**:
```
✗ leader_changes           (Leader变更次数)
✗ leader_change_history    (变更时间和原因)
```
**为什么重要**: 频繁变更表示集群不稳定

**日志复制效率**:
```
✗ entries_replicated_per_sec  (每秒复制的日志条数)
✗ replication_efficiency      (复制效率百分比)
✗ follower_next_index         (每个follower的进度)
✗ max_replication_lag         (最大复制延迟)
```
**为什么重要**: 反映集群整体吞吐能力

---

#### 第二优先级 - 网络质量指标

**网络延迟** (跨区域分析必需):
```
✗ node_to_node_rtt_ms      (节点间往返时间)
✗ jitter_ms                (延迟抖动/标准差)
✗ rtt_min/max/avg          (RTT统计)
```
**当前问题**: `latency_to_leader_ms` 是ping到自己，无用

**包丢失** (网络质量指标):
```
✗ packet_loss_rate         (%)
✗ tcp_retransmit_rate      (TCP协议级)
✗ quic_packet_loss_rate    (QUIC协议级)
```
**为什么缺失**: 没有网络分析工具集成 (mtr, tcpdump等)

**TCP特定指标**:
```
✗ tcp_window_size          (接收窗口)
✗ tcp_connection_count     (TCP连接数)
✗ tcp_established_count    (已建立的TCP连接)
```
**为什么缺失**: 仅有general连接数，没有TCP特定分析

**QUIC特定指标**:
```
✗ quic_stream_count        (活跃流数)
✗ quic_connection_count    (连接数)
✗ quic_initial_rtt         (初始RTT)
```
**为什么缺失**: 没有quic-go库集成

---

#### 第三优先级 - 高级诊断指标

**GC和垃圾回收**:
```
✗ gc_frequency             (GC次数/秒)
✗ gc_pause_max_ms          (最大暂停)
✗ gc_pause_p95_ms          (p95暂停)
✗ gc_pause_total_ms        (总暂停时间)
✗ heap_objects             (堆对象数)
✗ heap_allocated_mb        (已分配内存)
```
**为什么缺失**: 需要Go runtime集成

**CPU和并发**:
```
✗ context_switch_rate      (上下文切换/秒)
✗ cpu_system_percent       (系统态CPU)
✗ cpu_iowait_percent       (I/O等待)
✗ goroutine_count          (goroutine数量)
```
**为什么缺失**: 需要更深入的系统工具

**应用层请求统计**:
```
✗ requests_total           (总请求数)
✗ requests_success_rate    (成功率)
✗ requests_error_rate      (错误率)
✗ requests_rejected        (被拒绝的请求)
```
**为什么缺失**: 需要应用层埋点

**延迟分布详情**:
```
✗ latency_min_ms
✗ latency_max_ms
✗ latency_mean_ms
✗ latency_stdev_ms
✗ latency_histogram        (分布直方图)
```
**当前状态**: 只有p50/p95/p99三个百分位

---

## 📈 按分析维度的覆盖率

### 分析维度1: "节点数量影响" (3→5→7)

**现有覆盖**:
```
✓ write_throughput         ✓ ✓ ✓ (可用)
✓ latency_p99             ✓ ✓ ✓ (可用)
✓ cpu_usage_percent       ✓ ✓ ✓ (可用)
✓ replication_lag         ✓ ✓ ✓ (可用)

✗ election_time           ✗ ✗ ✗ (关键缺失!)
✗ entries_replicated      ✗ ✗ ✗ (关键缺失!)
✗ context_switch_rate     ✗ ✗ ✗ (诊断缺失)
```

**覆盖率**: ~60% (基本指标有, 诊断指标缺失)

**无法回答的问题**:
- "为什么5节点选举变慢?" → 无法直接观察选举时间
- "日志复制速度如何变化?" → 无法观察entries_replicated_per_sec
- "锁竞争是否增加?" → 无法观察context_switch_rate

---

### 分析维度2: "跨区域影响" (同区域 vs 跨区域)

**现有覆盖**:
```
✓ write_throughput        ✓ ✓ (可用)
✓ latency_p99            ✓ ✓ (可用)
✓ replication_lag        ✓ ✓ (可用)

✗ node_to_node_rtt       ✗ ✗ (缺失, 现有ping数据无用)
✗ jitter                 ✗ ✗ (关键缺失!)
✗ packet_loss_rate       ✗ ✗ (关键缺失!)
✗ heartbeat_timeout      ✗ ✗ (关键缺失!)
✗ leader_changes         ✗ ✗ (关键缺失!)
✗ election_time          ✗ ✗ (关键缺失!)
```

**覆盖率**: ~40% (应用层有数据, 网络层严重缺失)

**无法回答的问题**:
- "节点间真实RTT是多少?" → latency_to_leader_ms只是ping自己
- "网络延迟抖动有多大?" → 完全缺失jitter数据
- "跨区域时为什么频繁选举?" → 无heartbeat_timeout_count
- "心跳是否超时?" → 无超时计数

---

### 分析维度3: "TCP vs QUIC对比"

**现有覆盖**:
```
✓ write_throughput        ✓ ✓ (可用)
✓ latency_p99            ✓ ✓ (可用)
✓ cpu_usage_percent      ✓ ✓ (可用)
✓ established_connections ✓ ✓ (有但不区分协议)

✗ tcp_retransmit_rate    ✗ ✗ (关键缺失!)
✗ quic_packet_loss_rate  ✗ ✗ (关键缺失!)
✗ tcp_window_size        ✗ ✗ (关键缺失!)
✗ quic_stream_count      ✗ ✗ (关键缺失!)
✗ connection_reuse       ✗ ✗ (缺失)
✗ gc_pause_impact        ✗ ✗ (缺失)
```

**覆盖率**: ~50% (高层指标有, 协议层缺失)

**无法回答的问题**:
- "TCP重传率是多少?" → 无TCP层观察
- "QUIC包丢失如何?" → 无QUIC层观察
- "TCP窗口大小是否足够?" → 完全缺失
- "QUIC多流是否被利用?" → 无stream_count

---

## 🔧 快速修复方案

### 优先级1: 补充Raft事件监控 (1-2天)

**添加这些指标** (需要修改Raft节点的HTTP API):

```python
# 在 /status endpoint 返回
{
    "is_leader": bool,
    "term": int,
    "last_leader_change": timestamp,
    "leader_change_count": int,           # 新增
    "election_trigger_count": int,        # 新增
    "election_last_duration_ms": int,     # 新增
    "last_heartbeat_timeout": timestamp,  # 新增
    "heartbeat_timeout_count": int,       # 新增
    "committed_index": int,
    "last_applied": int,
    "last_log_index": int,
    "log_replication_rate": float,        # 新增 (entries/sec)
}
```

**实现位置**: `cmd/raftd/main.go` 的HTTP /status handler

---

### 优先级2: 补充网络诊断 (2-3天)

**集成mtr和tcpdump**:

```bash
# 在collect_metrics.py中添加
def collect_network_quality():
    # 1. 真实RTT采样 (不是ping自己)
    mtr -c 5 <node-ip> --report
    
    # 2. 丢包率统计
    ping -c 100 <node-ip> 
    
    # 3. TCP重传 (使用ss而不是netstat)
    ss -s | grep retrans
    
    # 4. 网络延迟直方图
    tcpdump -i eth0 -n 'host <node-ip>' | analyze_latency
```

---

### 优先级3: 补充协议层观察 (1周)

**TCP特定**:
```bash
# TCP窗口大小
ss -o state established '( dport = :8001 or dport = :9001 )' | grep -o 'wscale:[0-9]*'

# TCP连接统计
netstat -tn | grep -E ':(8001|9001)' | wc -l
```

**QUIC特定** (需要quic-go库支持):
```go
// 在 quic-go 中添加指标导出
conn.ReceivedStreamCount()
conn.OpenStreamCount()
conn.ConnectionState().PacketLoss
```

---

### 优先级4: 补充GC和并发指标 (2-3天)

```go
// 在 cmd/raftd/main.go 添加runtime指标
var m runtime.MemStats
runtime.ReadMemStats(&m)

metrics := {
    "gc_pause_max": m.PauseNs[(m.NumGC+255)%256],
    "gc_frequency": m.NumGC / elapsed_seconds,
    "goroutine_count": runtime.NumGoroutine(),
}

// 在/status中返回
// 或创建新的/metrics endpoint
```

---

## 📋 修复优先级建议

### 如果只有3天:
```
优先修复:
1. ✓ 添加election_time和leader_changes (必需诊断节点数影响)
2. ✓ 修复node_to_node_rtt测量 (必需诊断跨区域影响)
3. ✓ 添加heartbeat_timeout_count (必需诊断跨区域稳定性)
```

### 如果有1周:
```
上面3项 + 
4. ✓ 添加TCP重传率观察
5. ✓ 补充网络质量指标 (jitter, packet_loss)
6. ✓ 添加entries_replicated_per_sec
```

### 如果有2周:
```
上面所有 +
7. ✓ 集成GC暂停监控
8. ✓ 添加上下文切换率
9. ✓ QUIC特定指标
10. ✓ 延迟直方图
```

---

## 🔄 现有代码可快速利用的地方

**已有的基础结构，可以快速扩展**:

### 1. HTTP /status API 已就位
```python
# 在 collect_metrics.py 中已可访问
curl -s http://{ip}:8001/status | jq
```
**快速修复**: 在Raft节点中添加更多计数器即可

### 2. SSH执行框架已有
```python
# _ssh_exec() 方法已实现，可以直接运行命令
def _ssh_exec(self, ip, cmd, timeout=5)
```
**快速修复**: 添加新的命令调用即可

### 3. 监控线程已就位
```python
# start_monitoring() 已实现后台采集
# 可以直接添加新的采集函数
```
**快速修复**: 在monitor_loop中添加新的collect函数调用

### 4. CSV输出已实现
```python
# save_metrics() 已完整实现CSV写入
# 新指标会自动保存
```
**快速修复**: 只需添加指标，不需改格式

---

## ✅ 现有代码质量评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 基准测试覆盖 | 9/10 | 吞吐和延迟百分位都有 |
| Raft协议覆盖 | 6/10 | 基本状态有，事件缺失 |
| 系统资源覆盖 | 8/10 | CPU内存磁盘都有，GC缺失 |
| 网络诊断覆盖 | 3/10 | 缺少质量监测，ping数据无用 |
| 协议对标覆盖 | 4/10 | 无TCP/QUIC分化指标 |
| **总体覆盖** | **6/10** | 基础完整，诊断深度不足 |

---

## 📊 建议立即添加的指标 (最小化工作量)

**这4个指标需要修改Raft节点，可在1-2小时内完成**:

```python
# 在 raftd/main.go 的 /status endpoint 中添加

"election_duration_ms": 500,              # 上次选举耗时
"leader_change_count": 0,                  # 变更总次数  
"heartbeat_timeout_count": 0,              # 超时总次数
"log_entries_per_second": 170.5,           # 复制速度
```

**这2个指标可以通过改进现有监控脚本完成**:

```bash
# 修改collect_metrics.py中的collect_network_metrics()

# 正确测量节点间RTT (而不是ping自己)
for other_node in nodes:
    if other_node != current_node:
        rtt = ping(other_node)  # 测量到其他节点

# 添加包丢失统计
ping -c 100 <node-ip> | grep "loss" | awk '{print $6}'
```

**成本**: ~100行代码, 3-4小时工作量, 立即可用

---

**总结**: 现有框架已经不错，但关键诊断指标缺失。建议优先添加Raft事件计数器和真实网络质量指标。
