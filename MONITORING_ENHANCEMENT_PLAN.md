# 监控增强计划

## 🎯 优先级方案

### 方案1: 快速修复 (3-4小时) - 推荐

添加以下**6个关键指标**，立即支撑你的分析需求:

#### 1. Raft事件计数器 (修改raftd)
```go
// 在 cmd/raftd/main.go 中的 FSM 或 Node 结构体中添加

type RaftMetrics struct {
    LeaderChanges       int64              // Leader变更次数
    ElectionTriggers    int64              // 选举触发次数  
    LastElectionMs      int64              // 上次选举耗时
    HeartbeatTimeouts   int64              // 心跳超时次数
    EntriesReplicatedps float64            // 每秒复制条数
}

// 在 HTTP handler 中返回这些指标
func (n *Node) GetMetrics() RaftMetrics {
    return RaftMetrics{
        LeaderChanges:     atomic.LoadInt64(&n.metricsLeaderChanges),
        ElectionTriggers:  atomic.LoadInt64(&n.metricsElections),
        LastElectionMs:    n.lastElectionDuration,
        HeartbeatTimeouts: atomic.LoadInt64(&n.metricsHeartbeatTimeouts),
        EntriesReplicatedps: n.calculateEntriesPerSecond(),
    }
}
```

**修改位置**: `cmd/raftd/main.go` - 约30-50行新代码

---

#### 2. 修复网络延迟测量 (改进监控脚本)
```python
# 在 scripts/collect_metrics.py 中修改 collect_network_metrics()

def collect_network_metrics(self, node_id: str, ip: str) -> Dict:
    """收集网络性能指标"""
    metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

    # ❌ 旧方式: ping到自己，无用
    # cmd = f"ping -c 1 {ip}"
    
    # ✓ 新方式: ping到其他节点（leader）
    if node_id != 'leader':
        try:
            # 假设leader_ip已知或通过状态获取
            cmd = f"ping -c 3 {leader_ip} | grep 'rtt min/avg/max/stddev' | awk -F'/' '{{print $4, $5}}'"
            result = subprocess.run(
                f"ssh -i {self.ssh_key} ec2-user@{ip} '{cmd}'",
                shell=True, capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0 and result.stdout:
                avg, stddev = result.stdout.strip().split()
                metrics["latency_to_leader_ms"] = float(avg)
                metrics["jitter_ms"] = float(stddev)
        except:
            pass

    # 添加: 包丢失率
    try:
        loss_cmd = f"ping -c 100 {leader_ip} | grep 'loss' | awk '{{print $6}}' | tr -d '%'"
        result = subprocess.run(
            f"ssh -i {self.ssh_key} ec2-user@{ip} '{loss_cmd}'",
            shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout:
            metrics["packet_loss_percent"] = float(result.stdout.strip())
    except:
        metrics["packet_loss_percent"] = 0

    return metrics
```

**修改位置**: `scripts/collect_metrics.py` - 约30行改进

---

#### 3. 添加TCP重传率监控 (TCP only)
```python
# 在 scripts/collect_metrics.py 中添加新函数

def collect_tcp_metrics(self, node_id: str, ip: str) -> Dict:
    """收集TCP特定指标"""
    metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

    try:
        # TCP重传统计
        tcp_stats_cmd = "cat /proc/net/snmp | grep Tcp | awk 'NR==2 {print $13}'"
        result = subprocess.run(
            f"ssh -i {self.ssh_key} ec2-user@{ip} '{tcp_stats_cmd}'",
            shell=True, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            metrics["tcp_retransmits_total"] = int(result.stdout.strip())
    except:
        metrics["tcp_retransmits_total"] = 0

    try:
        # 监听端口的连接数 (8001 for QUIC)
        conn_cmd = "netstat -tn | grep ':8001' | grep ESTABLISHED | wc -l"
        result = subprocess.run(
            f"ssh -i {self.ssh_key} ec2-user@{ip} '{conn_cmd}'",
            shell=True, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            metrics["tcp_connections_8001"] = int(result.stdout.strip())
    except:
        metrics["tcp_connections_8001"] = 0

    return metrics

# 在 start_monitoring() 的 monitor_loop 中调用
# self.metrics_history[f"{node_id}_tcp"].append(
#     self.collect_tcp_metrics(node_id, ip)
# )
```

**修改位置**: `scripts/collect_metrics.py` - 约40行新代码

---

#### 4. 改进结果分析 (数据处理)
```python
# 在 scripts/analyze_distributed_results.py 中添加新的分析函数

def analyze_raft_stability(self) -> Dict:
    """分析Raft集群稳定性"""
    analysis = {
        "leader_stability": {},
        "election_events": {},
        "replication_efficiency": {},
    }

    # 分析Leader稳定性
    for metric_type, data in self.metrics_data.items():
        if "_raft" in metric_type:
            leader_changes = [
                d for d in data 
                if "leader_change_count" in d
            ]
            if leader_changes:
                total_changes = max(
                    [int(d.get("leader_change_count", 0)) for d in leader_changes]
                )
                analysis["leader_stability"] = {
                    "total_changes": total_changes,
                    "is_stable": total_changes <= 1,  # 应该=1 (初始选举)
                }

    # 分析选举事件
    for metric_type, data in self.metrics_data.items():
        if "_raft" in metric_type and data:
            election_times = [
                float(d.get("election_duration_ms", 0)) 
                for d in data 
                if d.get("election_duration_ms")
            ]
            if election_times:
                analysis["election_events"] = {
                    "avg_duration_ms": statistics.mean(election_times),
                    "max_duration_ms": max(election_times),
                }

    return analysis

# 在 generate_html_report() 中使用这个新分析
```

**修改位置**: `scripts/analyze_distributed_results.py` - 约50行新代码

---

### 修复步骤总结

| 步骤 | 文件 | 代码量 | 时间 |
|------|------|--------|------|
| 1. 添加Raft计数器 | cmd/raftd/main.go | 50行 | 1h |
| 2. 修复网络测量 | collect_metrics.py | 30行 | 30min |
| 3. 添加TCP指标 | collect_metrics.py | 40行 | 30min |
| 4. 改进分析 | analyze_distributed_results.py | 50行 | 1h |
| 5. 测试验证 | 全部 | - | 30min |
| **总计** | | ~170行 | **3.5h** |

---

## 方案2: 完整增强 (1周)

在方案1的基础上，再添加:

### 5. GC暂停监控
```go
// cmd/raftd/main.go 中的metrics端点
import "runtime"

type GCMetrics struct {
    GCPauseMax      uint64
    GCPauseP95      uint64
    GCFrequency     float64
    HeapObjects     uint64
    GoRoutineCount  int
}

func getGCMetrics() GCMetrics {
    var m runtime.MemStats
    runtime.ReadMemStats(&m)
    return GCMetrics{
        GCPauseMax:     m.PauseNs[(m.NumGC+255)%256],
        GCFrequency:    float64(m.NumGC) / elapsedSeconds,
        HeapObjects:    m.HeapObjects,
        GoRoutineCount: runtime.NumGoroutine(),
    }
}
```

### 6. 上下文切换率
```python
# collect_metrics.py
def collect_scheduling_metrics(self, node_id: str, ip: str) -> Dict:
    """收集调度相关指标"""
    metrics = {}
    
    try:
        # 上下文切换频率
        ctx_switch_cmd = "cat /proc/stat | grep ctxt | awk '{print $2}'"
        # 采样前后的差异 / 时间差
        # 需要实现两次采样的逻辑
    except:
        pass
    
    return metrics
```

### 7. QUIC特定指标
```python
# 需要在Raft节点中集成quic-go的metrics导出
# 或在代理层添加观察

def collect_quic_metrics(self, node_id: str, ip: str) -> Dict:
    """收集QUIC特定指标"""
    # 需要Raft节点支持quic metrics导出
    # 或通过代理监控
    pass
```

---

## 🛠️ 逐步实现指南

### 步骤1: 修改Raft节点的状态接口

**文件**: `cmd/raftd/main.go`

```go
// 在 handleStatus() 函数中修改返回的状态结构

type RaftStatus struct {
    // 现有字段
    IsLeader      bool   `json:"is_leader"`
    Term          uint64 `json:"term"`
    CommittedIdx  uint64 `json:"committed_index"`
    LastApplied   uint64 `json:"last_applied"`
    LastLogIdx    uint64 `json:"last_log_index"`
    Peers         []string `json:"peers"`
    
    // 新增字段
    LeaderChanges      int64   `json:"leader_changes"`
    ElectionTriggers   int64   `json:"election_triggers"`
    LastElectionMs     int64   `json:"last_election_ms"`
    HeartbeatTimeouts  int64   `json:"heartbeat_timeouts"`
    EntriesPerSecond   float64 `json:"entries_per_second"`
    ReplicationLag     int64   `json:"replication_lag"`
}

// 在HTTP handler中:
func handleStatus(w http.ResponseWriter, r *http.Request) {
    status := RaftStatus{
        // 填充现有字段
        IsLeader:   raftNode.IsLeader(),
        Term:       raftNode.CurrentTerm(),
        
        // 添加新计数器 (使用atomic来记录)
        LeaderChanges:      atomic.LoadInt64(&raftNode.statsLeaderChanges),
        ElectionTriggers:   atomic.LoadInt64(&raftNode.statsElections),
        LastElectionMs:     raftNode.getLastElectionDuration(),
        HeartbeatTimeouts:  atomic.LoadInt64(&raftNode.statsHeartbeatTimeouts),
        EntriesPerSecond:   raftNode.calculateReplicationRate(),
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(status)
}
```

### 步骤2: 修改监控脚本获取新指标

**文件**: `scripts/collect_metrics.py`

```python
def collect_raft_metrics(self, node_id: str, ip: str, port: int = 8001) -> Dict:
    """收集Raft协议级指标"""
    metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

    try:
        cmd = f"curl -s http://{ip}:{port}/status"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            status = json.loads(result.stdout)
            
            # 现有指标
            metrics["is_leader"] = status.get("is_leader", False)
            metrics["current_term"] = status.get("term", 0)
            metrics["committed_index"] = status.get("committed_index", 0)
            metrics["last_applied"] = status.get("last_applied", 0)
            metrics["last_log_index"] = status.get("last_log_index", 0)
            metrics["peers"] = len(status.get("peers", []))
            metrics["replication_lag"] = (
                status.get("last_log_index", 0) - status.get("committed_index", 0)
            )
            
            # 新增指标 ✓
            metrics["leader_changes"] = status.get("leader_changes", 0)
            metrics["election_triggers"] = status.get("election_triggers", 0)
            metrics["last_election_ms"] = status.get("last_election_ms", 0)
            metrics["heartbeat_timeouts"] = status.get("heartbeat_timeouts", 0)
            metrics["entries_per_second"] = status.get("entries_per_second", 0)
    except:
        pass

    return metrics
```

### 步骤3: 改进网络诊断

**文件**: `scripts/collect_metrics.py`

```python
def collect_network_metrics(self, node_id: str, ip: str) -> Dict:
    """收集网络性能指标"""
    metrics = {"timestamp": datetime.now().isoformat(), "node": node_id}

    # 获取集群中其他节点的IP用于测量
    other_nodes = {k: v for k, v in self.nodes.items() if k != node_id}
    if other_nodes:
        leader_ip = list(other_nodes.values())[0]  # 选第一个作为目标
        
        try:
            # RTT测量 (ping 5次获得平均值)
            cmd = f"ping -c 5 {leader_ip} | tail -1 | awk -F'/' '{{print $4, $5}}'"
            result = subprocess.run(
                f"ssh -i {self.ssh_key} ec2-user@{ip} '{cmd}'",
                shell=True, capture_output=True, text=True, timeout=15
            )
            
            if result.returncode == 0 and result.stdout:
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    metrics["rtt_avg_ms"] = float(parts[0])
                    metrics["rtt_stddev_ms"] = float(parts[1])
        except:
            pass

        try:
            # 包丢失率 (ping 100次)
            cmd = f"ping -c 100 -q {leader_ip} | grep 'loss' | awk '{{print $6}}' | tr -d '%'"
            result = subprocess.run(
                f"ssh -i {self.ssh_key} ec2-user@{ip} '{cmd}'",
                shell=True, capture_output=True, text=True, timeout=120
            )
            
            if result.returncode == 0 and result.stdout:
                metrics["packet_loss_percent"] = float(result.stdout.strip())
        except:
            metrics["packet_loss_percent"] = 0

    return metrics
```

### 步骤4: 更新报告生成

**文件**: `scripts/analyze_distributed_results.py`

```python
def _html_benchmark_summary(self, bench: Dict) -> str:
    """生成基准测试摘要HTML"""
    html = "<h3>Raft稳定性指标</h3>\n<table>\n"
    html += "<tr><th>指标</th><th>值</th><th>评价</th></tr>\n"
    
    # 从监控数据中提取Raft指标
    for metric_type, data in self.metrics_data.items():
        if "_raft" in metric_type and data:
            latest = data[-1]  # 最后一条记录
            
            leader_changes = latest.get("leader_changes", 0)
            election_triggers = latest.get("election_triggers", 0)
            heartbeat_timeouts = latest.get("heartbeat_timeouts", 0)
            
            html += f"<tr><td>Leader变更</td><td>{leader_changes}</td>"
            html += f"<td>{'✓ 稳定' if leader_changes <= 1 else '⚠ 异常'}</td></tr>\n"
            
            html += f"<tr><td>选举次数</td><td>{election_triggers}</td>"
            html += f"<td>{'✓ 正常' if election_triggers <= 1 else '⚠ 频繁'}</td></tr>\n"
            
            html += f"<tr><td>心跳超时</td><td>{heartbeat_timeouts}</td>"
            html += f"<td>{'✓ 无' if heartbeat_timeouts == 0 else '🚨 有问题'}</td></tr>\n"
    
    html += "</table>"
    return html
```

---

## ✅ 完成检查清单

实现完成后验证:

- [ ] Raft节点的/status返回新字段
- [ ] `curl http://localhost:8001/status | jq` 能看到新字段
- [ ] 监控脚本能成功采集新指标
- [ ] 新指标出现在CSV输出中
- [ ] 分析脚本能正确处理新指标
- [ ] HTML报告展示了新的Raft稳定性部分
- [ ] 基准测试运行无错误

---

## 🎯 预期效果

实施后，你将能够:

✓ 分析"为什么5节点吞吐下降" → 看election_time和heartbeat_timeouts  
✓ 分析"跨区域为什么慢" → 看rtt_avg_ms和packet_loss_percent  
✓ 对比"TCP vs QUIC" → 看tcp_retransmits和entries_per_second  

**总共添加这些关键指标**:
- election_duration_ms
- leader_changes
- heartbeat_timeouts
- entries_per_second
- rtt_avg_ms + rtt_stddev_ms
- packet_loss_percent
- tcp_retransmits_total

---

**下一步**: 选择方案1或方案2，开始实施修改！

