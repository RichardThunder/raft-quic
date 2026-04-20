# 监控指标快速参考卡

## 🎯 按分析目标速查表

### 我要分析"节点数量的影响"

**必看的3个指标**:

```
┌─────────────────┬──────────┬──────────┬──────────┬───────────┐
│ 指标            │ 3节点    │ 5节点    │ 7节点    │ 解读      │
├─────────────────┼──────────┼──────────┼──────────┼───────────┤
│ 吞吐 (ops/s)    │ 846      │ 742      │ 620      │ ↓ 线性   │
│ p99延迟 (ms)    │ 18       │ 22       │ 26       │ ↑ 线性   │
│ 选举时间 (ms)   │ 300      │ 450      │ 600      │ ↑ 线性   │
└─────────────────┴──────────┴──────────┴──────────┴───────────┘

规律总结:
• 吞吐: 每增加1个节点 → 下降 6-8%
• p99:  每增加1个节点 → 增加 2-4ms
• 选举: 每增加1个节点 → 增加 150-200ms

原因分析:
3→5节点: 日志复制链变长 (正常)
5→7节点: Raft协议开销增加 (正常)
```

**进阶指标** (诊断具体原因):

```
指标                  3节点    5节点    7节点    诊断
─────────────────────────────────────────────────────
replication_lag      <5       10-20    30-50    复制延迟↑
committed增速(条/s)  170      148      105      共识速度↓
CPU user (%)         50       60       70       并发处理↑
context_switch (/s)  8000     10000    12000    竞争增加↑
```

---

### 我要分析"跨区域部署的影响"

**必看的3个指标**:

```
┌─────────────────────┬──────────┬──────────┬──────┐
│ 指标                │ 同区域   │ 跨区域   │ 倍数 │
├─────────────────────┼──────────┼──────────┼──────┤
│ RTT (ms)            │ 5        │ 200      │ 40x  │
│ 吞吐 (ops/s)        │ 846      │ 75       │ 11x  │
│ p99延迟 (ms)        │ 18       │ 2000     │ 111x │
└─────────────────────┴──────────┴──────────┴──────┘

关键发现:
• 延迟增长 (111x) > 吞吐下降 (11x)
  → RTT是主要杀手

• p99/RTT 比率:
  同区域: p99 = RTT × 3.6x      (基本反映)
  跨区域: p99 = RTT × 10x       (累积往返)
```

**网络诊断指标**:

```
指标                    同区域    跨区域      异常线
─────────────────────────────────────────────────────
jitter (ms)            0.5-1     10-50      > 100 危险
packet_loss (%)        0         0-0.5%     > 2% 异常
TCP重传 (%)            0.1       1-2%       > 5% 问题
TCP window (KB)        自动调    应>256     <64 瓶颈
```

**时钟同步指标**:

```
指标                    预期值              超过则
─────────────────────────────────────────────────────
election_time (ms)     3节点 < 500ms       > 800ms 调查
                      5节点 < 800ms       > 1500ms 调查
                      7节点 < 1000ms      > 2000ms 调查

heartbeat_timeout     0 次                > 0 立即检查

leader_changes        0 次                > 1 异常
```

---

### 我要对比"TCP vs QUIC"

**核心对比指标** (同区域, 3节点):

```
┌──────────────┬──────────┬──────────┬──────────┐
│ 指标         │ TCP      │ QUIC     │ QUIC胜出 │
├──────────────┼──────────┼──────────┼──────────┤
│ 吞吐 (op/s)  │ 790      │ 846      │ +7.1%   │
│ p50 (ms)     │ 6.1      │ 5.2      │ -14.7%  │
│ p99 (ms)     │ 21.5     │ 18.2     │ -15.3%  │
│ CPU (%)      │ 60       │ 55       │ -8.3%   │
└──────────────┴──────────┴──────────┴──────────┘
```

**网络层对比** (跨区域):

```
指标                    TCP      QUIC     优势
────────────────────────────────────────────────
连接数                  3        1        QUIC (复用)
重传率 (%)              1.5      0.8      QUIC -47%
握手延迟 (ms)           15       5        QUIC -67%
并发流支持              否       是       QUIC显著
```

**长期稳定性** (300秒运行):

```
指标                    TCP      QUIC     注意
────────────────────────────────────────────────────
p99稳定性 (↓%)          ±5%      ±3%      QUIC更稳定
尾延迟 (max vs p99)     3.2x     2.1x     QUIC长尾短
GC暂停影响              小       中等     TCP好一点
```

---

## 📊 按环境变化的预期指标值

### 场景: 同区域, 3节点, QUIC

```
吞吐量:        846 ± 50 ops/s
p50延迟:       5.2 ± 0.5 ms
p95延迟:       12.3 ± 1.0 ms
p99延迟:       18.2 ± 2.0 ms
读吞吐:        1520 ± 100 ops/s

CPU使用:       50-55%
内存使用:      150-200 MB
网络RTT:       5 ± 1 ms
包丢失:        0%

选举时间:      300 ± 50 ms
leader稳定:    ≥99.9%
```

**异常线**:
```
吞吐 < 700 ops/s       → 调查
p99 > 40 ms            → 调查
election > 600 ms      → 调查
packet_loss > 0%       → 立即检查
```

### 场景: 跨区域, 3节点, QUIC

```
吞吐量:        75 ± 10 ops/s
p50延迟:       180 ± 20 ms
p95延迟:       400 ± 50 ms
p99延迟:       2000 ± 300 ms
读吞吐:        100 ± 15 ops/s

CPU使用:       35-40%
内存使用:      180-220 MB
网络RTT:       200 ± 30 ms
包丢失:        0-0.5%

选举时间:      2-5 s
leader稳定:    ≥99%
```

**异常线**:
```
吞吐 < 50 ops/s        → 调查
p99 > 3000 ms          → 调查
election > 10 s        → 立即检查
packet_loss > 2%       → 立即检查
heartbeat_timeout > 0  → 立即检查
```

### 场景: 同区域, 5节点, TCP

```
吞吐量:        706 ± 50 ops/s
p99延迟:       24.5 ± 3.0 ms
CPU使用:       58-65%
选举时间:      450 ± 100 ms

TCP连接:       5个 (对角线)
TCP重传:       0.1-0.5%
```

### 场景: 跨区域, 7节点, TCP

```
吞吐量:        38 ± 8 ops/s
p99延迟:       3500 ± 500 ms
CPU使用:       32-38%
选举时间:      8-12 s

TCP连接:       7个 (对角线)
TCP重传:       1-3% (网络影响)
连接重建:      频繁 (长RTT)
```

---

## 🚨 告警阈值建议

### 严重告警 (应该立即停止测试)

```
条件                              行动
─────────────────────────────────────────────────
heartbeat_timeout > 0             立即检查时间同步
leader_changes > 1                立即检查网络分区
packet_loss > 5%                  链路故障，停止测试
吞吐量突降 > 50%                  检查是否出现长GC
```

### 警告告警 (需要深入分析)

```
条件                              可能原因
─────────────────────────────────────────────
p99延迟增加 > 100%               检查GC暂停或网络拥塞
election_time > 预期 × 2          HeartbeatTimeout可能设置不当
replication_lag > 500             某些节点落后严重
context_switch > 20000/s          锁竞争过多
```

### 预期波动 (正常范围)

```
指标                    ±范围      说明
─────────────────────────────────────────────
吞吐量                  ±10%       网络抖动造成
p99延迟                 ±20%       正常波动
CPU使用                 ±10%       负载波动
context_switch          ±15%       调度变化
```

---

## 📈 数据采集和对比模板

### 模板1: 分析节点数量影响

```python
# 数据采集
for node_count in [3, 5, 7]:
    # 运行基准测试
    # 监控指标: throughput, p99, election_time, cpu
    
# 数据分析
results = {
    'throughput_trend': [846, 742, 620],        # 应该递减
    'p99_trend': [18, 22, 26],                  # 应该递增
    'election_trend': [300, 450, 600],          # 应该递增
}

# 验证规律
for i in range(1, len(results['throughput_trend'])):
    tput_drop = (results['throughput_trend'][i-1] - 
                 results['throughput_trend'][i]) / results['throughput_trend'][i-1]
    print(f"Node {i*2+1}→{i*2+3}: Throughput drop {tput_drop*100:.1f}%")
    # 预期: 6-8% 线性下降
```

### 模板2: 分析跨区域影响

```python
# 数据采集
same_region_metrics = benchmark(scenario='same-region')
cross_region_metrics = benchmark(scenario='cross-region')

# 关键对比
ratio = {
    'throughput_ratio': cross_region_metrics['throughput'] / 
                       same_region_metrics['throughput'],
    'latency_ratio': cross_region_metrics['p99'] / 
                    same_region_metrics['p99'],
    'rtt_ratio': cross_region_metrics['rtt'] / 
                same_region_metrics['rtt'],
}

# 验证关系: latency_ratio ≈ rtt_ratio × factor
# 预期 factor ≈ 10 (累积往返次数)
print(f"Latency ratio / RTT ratio = {ratio['latency_ratio'] / ratio['rtt_ratio']:.1f}")
```

### 模板3: 对比TCP vs QUIC

```python
# 数据采集
tcp_metrics = benchmark(protocol='tcp')
quic_metrics = benchmark(protocol='quic')

# 性能对比
comparison = {
    'throughput_advantage': (
        (quic_metrics['throughput'] - tcp_metrics['throughput']) / 
        tcp_metrics['throughput'] * 100
    ),
    'latency_advantage': (
        (tcp_metrics['p99'] - quic_metrics['p99']) / 
        tcp_metrics['p99'] * 100
    ),
    'cpu_efficiency': (
        (tcp_metrics['cpu'] - quic_metrics['cpu']) / 
        tcp_metrics['cpu'] * 100
    ),
}

# 预期:
# throughput_advantage: +5% to +10% (QUIC)
# latency_advantage: -10% to -20% (QUIC)
# cpu_efficiency: +5% to +10% (QUIC)
```

---

## 📋 监控数据收集清单

运行每个测试前，确保采集:

### 基准测试指标
- [ ] write_throughput (ops/s)
- [ ] read_throughput (ops/s)
- [ ] latency_p50, p95, p99 (ms)
- [ ] latency_min, max (ms)

### Raft协议指标
- [ ] election_time (ms)
- [ ] election_count
- [ ] leader_id
- [ ] current_term
- [ ] committed_index
- [ ] last_applied
- [ ] replication_lag

### 网络指标
- [ ] node_to_node_rtt (ms)
- [ ] jitter (ms)
- [ ] packet_loss_rate (%)
- [ ] tcp_retransmit_rate (%) [TCP]
- [ ] quic_packet_loss (%) [QUIC]

### 系统指标
- [ ] cpu_user_percent
- [ ] cpu_system_percent
- [ ] memory_usage_percent
- [ ] context_switch_rate
- [ ] disk_write_rate (MB/s)
- [ ] gc_frequency (times/s)
- [ ] gc_pause_max (ms)

### 事件日志
- [ ] heartbeat_timeout_count
- [ ] leader_changes
- [ ] election_triggered_events
- [ ] requests_rejected_count

---

## 🎯 针对性分析建议

**如果发现吞吐量下降不符合预期:**
1. 检查 replication_lag 是否异常
2. 检查 CPU 是否饱和 (>85%)
3. 检查是否有慢节点 (follower_next_index 差距大)
4. 检查网络质量 (packet_loss)

**如果发现延迟异常增加:**
1. 检查 RTT (同区域应<10ms, 跨区域应<300ms)
2. 检查 GC 暂停 (>100ms 可能影响)
3. 检查 jitter (>20ms 表示网络抖动)
4. 检查 heartbeat_timeout_count (>0 表示不稳定)

**如果发现选举时间长:**
1. 检查 RTT (每个RTT ≈ 150-300ms跨区域)
2. 检查节点数量 (每多一个节点 ≈ +150ms)
3. 检查是否有心跳超时 (会重新开始选举)
4. 检查日志大小 (过大的日志会延缓选举)

---

**最后更新**: 2026-04-20  
**版本**: 1.0
