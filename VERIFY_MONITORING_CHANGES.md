# 监控增强验证指南

## 🔍 快速验证清单

### 1️⃣ 代码修改验证

**检查node.go是否正确修改**:
```bash
grep -n "leaderChanges\|monitorMetrics\|GetMetrics\|type Metrics" node/node.go
```

**预期看到**:
```
45: type Node struct {
51:     leaderChanges           int64
...
160: func (n *Node) monitorMetrics() {
200: func (n *Node) GetMetrics() Metrics {
220: type Metrics struct {
```

**检查main.go是否修改**:
```bash
grep -n "GetMetrics\|handleStatus" cmd/raftd/main.go
```

**预期看到**:
```
214: func (s *server) handleStatus(w http.ResponseWriter, r *http.Request) {
215:     metrics := s.node.GetMetrics()
```

**检查collect_metrics.py是否修改**:
```bash
grep -n "leader_changes\|election_triggered\|rtt_avg_ms\|tcp_retransmits" scripts/collect_metrics.py
```

**预期看到**:
```
125: metrics["leader_changes"] = status.get("leader_changes", 0)
126: metrics["election_triggered"] = status.get("election_triggered", 0)
127: metrics["last_election_duration_ms"] = status.get("last_election_duration_ms", 0)
128: metrics["heartbeat_timeouts"] = status.get("heartbeat_timeouts", 0)
...
180: metrics["rtt_avg_ms"] = float(parts[0])
181: metrics["rtt_stddev_ms"] = float(parts[1])
...
200: metrics["tcp_retransmits_total"] = int(result.stdout.strip())
```

---

### 2️⃣ 编译验证

**验证语法**:
```bash
go vet ./node
go vet ./cmd/raftd
```

**预期**: 无错误

**尝试编译** (可能因沙箱限制失败，但不影响功能):
```bash
go build -o /tmp/raftd-test ./cmd/raftd 2>&1
```

---

### 3️⃣ 指标采集验证

**确保node.go有这个方法** (FSM.LastApplied):
```bash
grep -n "LastApplied" fsm/fsm.go
```

**预期**: 找到该方法

如果没有，需要在fsm/fsm.go的KVStateMachine结构体中添加:
```go
func (kv *KVStateMachine) LastApplied() uint64 {
    kv.mu.RLock()
    defer kv.mu.RUnlock()
    return kv.lastApplied
}
```

---

### 4️⃣ 指标字段验证

**检查所有必要的指标字段都在Metrics结构体中**:
```bash
grep -A 20 "type Metrics struct" node/node.go
```

**应该包含这些字段**:
```
IsLeader               bool
LeaderID               string
Term                   uint64
CommittedIndex         uint64
LastApplied            uint64
LastLogIndex           uint64
ReplicationLag         int64
PeersCount             int
LeaderChanges          int64          ✓ 优先级1
ElectionTriggered      int64          ✓ 优先级1
LastElectionDurationMs int64          ✓ 优先级1
HeartbeatTimeouts      int64          ✓ 优先级1
EntriesPerSecond       float64        ✓ 优先级2
```

---

## 📊 本地测试验证

### 第一步: 启动测试集群

```bash
# 打开3个终端窗口，分别运行:

# 终端1
./raftd -id node1 -bind 127.0.0.1:7001 -http 127.0.0.1:8001

# 终端2
./raftd -id node2 -bind 127.0.0.1:7002 -http 127.0.0.1:8002 -join 127.0.0.1:8001

# 终端3
./raftd -id node3 -bind 127.0.0.1:7003 -http 127.0.0.1:8003 -join 127.0.0.1:8001

# 等待30秒让集群稳定
sleep 30
```

### 第二步: 验证新指标

**查看leader节点状态**:
```bash
curl -s http://localhost:8001/status | jq '.'
```

**预期输出** (初始化后):
```json
{
  "is_leader": true,
  "leader_id": "node1",
  "term": 1,
  "committed_index": 0,
  "last_applied": 0,
  "last_log_index": 0,
  "replication_lag": 0,
  "peers_count": 3,
  "leader_changes": 0,
  "election_triggered": 1,
  "last_election_duration_ms": 250,
  "heartbeat_timeouts": 0,
  "entries_per_second": 0.0
}
```

**关键验证点**:
- ✓ `election_triggered` 应该 = 1 (初始选举)
- ✓ `heartbeat_timeouts` 应该 = 0 (无超时)
- ✓ `leader_changes` 应该 = 0 (无变更)
- ✓ `last_election_duration_ms` 应该 > 0 (有选举时间)

### 第三步: 执行写入并观察

**执行几个写入操作**:
```bash
curl -X POST 'http://localhost:8001/set?key=test1&value=value1'
curl -X POST 'http://localhost:8001/set?key=test2&value=value2'
curl -X POST 'http://localhost:8001/set?key=test3&value=value3'

sleep 2

# 再查看状态
curl -s http://localhost:8001/status | jq '.entries_per_second'
```

**预期**:
- `entries_per_second` 应该 > 0 (有日志复制)

### 第四步: 验证监控脚本

**测试collect_metrics.py能否采集新指标**:
```bash
# 手动运行一次采集
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from collect_metrics import MetricsCollector

nodes = {'node1': '127.0.0.1', 'node2': '127.0.0.1', 'node3': '127.0.0.1'}
collector = MetricsCollector(nodes, '')

# 测试Raft指标采集
metrics = collector.collect_raft_metrics('node1', '127.0.0.1:8001')
print('Raft metrics:', metrics)
"
```

**或更简单地用curl**:
```bash
# 直接查看API返回的JSON
curl -s http://localhost:8001/status | python3 -m json.tool
```

---

## 🎯 分布式测试验证

### 快速测试脚本

```bash
#!/bin/bash

echo "=== 监控增强验证 ==="
echo ""

echo "1. 检查代码修改"
echo "✓ node.go 新增指标"
grep -c "leaderChanges" node/node.go && echo "  Found leaderChanges field"

echo "✓ main.go 修改handleStatus"
grep -c "GetMetrics" cmd/raftd/main.go && echo "  Found GetMetrics call"

echo "✓ collect_metrics.py 采集新指标"
grep -c "leader_changes" scripts/collect_metrics.py && echo "  Found leader_changes metric"

echo ""
echo "2. 编译验证"
go vet ./node && echo "✓ node package syntax OK"
go vet ./cmd/raftd && echo "✓ raftd package syntax OK"

echo ""
echo "3. API验证"
echo "✓ Checking /status endpoint..."
curl -s http://localhost:8001/status | grep -q "election_triggered" && echo "  Contains election_triggered"
curl -s http://localhost:8001/status | grep -q "leader_changes" && echo "  Contains leader_changes"

echo ""
echo "=== 验证完成 ==="
```

**保存为verify.sh并运行**:
```bash
chmod +x verify.sh
./verify.sh
```

---

## 📋 预期的CSV输出

运行监控后，CSV应该包含这些新列:

```csv
timestamp,node,leader_changes,election_triggered,last_election_duration_ms,heartbeat_timeouts,entries_per_second,rtt_avg_ms,rtt_stddev_ms,packet_loss_percent,tcp_retransmits_total
2026-04-20T10:00:00,node1,0,1,250,0,170.5,5.2,0.8,0.0,125
2026-04-20T10:00:05,node1,0,1,250,0,168.3,5.1,0.7,0.0,125
```

**关键列**:
- ✓ `leader_changes`: 应该稳定在0
- ✓ `election_triggered`: 应该=1 (初始选举)
- ✓ `last_election_duration_ms`: 应该>0
- ✓ `heartbeat_timeouts`: 应该=0
- ✓ `entries_per_second`: 应该>0 (有写入)
- ✓ `rtt_avg_ms`: 同区域应该<10ms
- ✓ `packet_loss_percent`: 应该=0
- ✓ `tcp_retransmits_total`: 应该很低

---

## 🚨 常见问题排查

### 问题1: /status返回旧格式

**症状**: 返回的是map[string]string，而不是Metrics JSON

**原因**: handleStatus未正确更新或代码未重新编译

**解决**: 
```bash
# 检查main.go第215行是否是GetMetrics()
grep -n "GetMetrics" cmd/raftd/main.go

# 重新编译
GOOS=linux GOARCH=amd64 go build -o raftd-linux-amd64 ./cmd/raftd
```

### 问题2: election_triggered为0

**症状**: election_triggered一直是0

**原因**: monitorMetrics()没有正确检测选举

**解决**:
```bash
# 检查node.go中monitorMetrics是否在New()中启动
grep -n "go node.monitorMetrics" node/node.go

# 检查是否有错误日志
# 在日志中应该看到 "election detected"
```

### 问题3: entries_per_second为0

**症状**: entries_per_second持续为0

**原因**: 可能没有写入或FSM.LastApplied()不存在

**解决**:
```bash
# 执行写入操作
curl -X POST 'http://localhost:8001/set?key=test&value=test'

# 检查FSM.LastApplied()方法
grep -n "LastApplied" fsm/fsm.go

# 如果不存在，添加到KVStateMachine
```

### 问题4: rtt_avg_ms为空

**症状**: 监控脚本中rtt_avg_ms为0或缺失

**原因**: SSH ping命令失败或网络连接问题

**解决**:
```bash
# 检查SSH密钥权限
ls -la deploy/terraform/*/raft-key.pem

# 手动测试SSH
ssh -i deploy/terraform/same-region/raft-key.pem ec2-user@<node-ip> "ping -c 5 <target-ip>"

# 检查collect_metrics.py中的SSH命令
grep -A 10 "ping -c 5" scripts/collect_metrics.py
```

---

## ✅ 完整验证清单

- [ ] 代码修改检查 (grep验证)
- [ ] 编译验证 (go vet)
- [ ] 本地集群启动
- [ ] /status端点返回新字段
- [ ] 新指标值合理（非0, 非负数）
- [ ] CSV包含新列
- [ ] 监控脚本无错误运行
- [ ] AWS分布式测试成功

---

**文档版本**: 1.0  
**最后更新**: 2026-04-20  
**状态**: 验证指南完成

