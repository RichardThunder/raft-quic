# Demo Guide — Raft-over-QUIC

This guide walks you through every experiment you can run against the 3-node local cluster, explains what you should observe at each step, and explains _why_ you see it in terms of the Raft protocol.

---

## Prerequisites

```bash
go version        # need 1.23+
cd raft-quic
go build -o raftd ./cmd/raftd
```

You will need **four terminal windows**: one per node plus one for curl commands.

---

## Port Map

| Node   | QUIC (Raft RPC) | HTTP (API) |
|--------|-----------------|------------|
| node1  | 127.0.0.1:7001  | 127.0.0.1:8001 |
| node2  | 127.0.0.1:7002  | 127.0.0.1:8002 |
| node3  | 127.0.0.1:7003  | 127.0.0.1:8003 |

The `-bind` address is the QUIC transport address; peers dial each other here. The `-http` address is only for your curl commands.

---

## Experiment 1 — Cluster Formation & Leader Election

### What to do

**Terminal 1** — start the bootstrap node:
```bash
./raftd -id node1 -bind 127.0.0.1:7001 -http 127.0.0.1:8001
```

Wait for the line:
```
[INFO]  node1: cluster bootstrapped
```

**Terminal 2** — join node2:
```bash
./raftd -id node2 -bind 127.0.0.1:7002 -http 127.0.0.1:8002 -join 127.0.0.1:8001
```

**Terminal 3** — join node3:
```bash
./raftd -id node3 -bind 127.0.0.1:7003 -http 127.0.0.1:8003 -join 127.0.0.1:8001
```

**Terminal 4** — query who the leader is from all three nodes:
```bash
curl -s http://127.0.0.1:8001/leader
curl -s http://127.0.0.1:8002/leader
curl -s http://127.0.0.1:8003/leader
```

### What you should see

All three commands return the same QUIC address, e.g.:
```
127.0.0.1:7001
127.0.0.1:7001
127.0.0.1:7001
```

### Why

When node1 bootstraps alone it immediately holds an election and votes for itself. After node2 and node3 join (via `AddVoter` on the leader), they receive a snapshot of the cluster configuration and start exchanging heartbeats with the leader. The cluster has a stable leader within ~500 ms of all three nodes being up.

---

## Experiment 2 — Writing and Reading Data

### What to do

```bash
# Write a key (must go to the leader)
curl -s -X POST "http://127.0.0.1:8001/set?key=hello&value=world"

# Read from the leader
curl -s "http://127.0.0.1:8001/get?key=hello"

# Read from follower node2 (stale read)
curl -s "http://127.0.0.1:8002/get?key=hello"

# Read from follower node3 (stale read)
curl -s "http://127.0.0.1:8003/get?key=hello"
```

### What you should see

```
ok
world
world
world
```

### Why

`POST /set` calls `raft.Apply()` on the leader. The leader appends the command to its log, replicates it to a majority (2 of 3 nodes) via AppendEntries RPCs over QUIC streams, then commits and applies it to its local FSM. The followers apply the command to their own FSMs as they receive the commit. Because all reads go to the local FSM (`Get()` is not a linearizable read), there is a brief window after the write where a follower may not have the entry yet — but within a heartbeat period (100 ms) all nodes converge.

---

## Experiment 3 — Write Rejected on a Follower

### What to do

First confirm node1 is still the leader:
```bash
curl -s http://127.0.0.1:8001/leader
```

Then try to write directly to a follower:
```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST "http://127.0.0.1:8002/set?key=test&value=direct"
```

### What you should see

```
not leader; leader is 127.0.0.1:7001
HTTP 503
```

### Why

Only the Raft leader is allowed to append to the log. Followers reject writes with `503 Service Unavailable` and tell you the current leader's QUIC address. In production you would proxy or redirect the client — in this PoC you forward the request manually.

---

## Experiment 4 — Multiple Writes, Verify Consistency

### What to do

```bash
# Write several keys in sequence
for i in 1 2 3 4 5; do
  curl -s -X POST "http://127.0.0.1:8001/set?key=k${i}&value=v${i}"
done

# Read all keys from each node
for node in 8001 8002 8003; do
  echo "=== node on port $node ==="
  for i in 1 2 3 4 5; do
    echo -n "k${i}="; curl -s "http://127.0.0.1:${node}/get?key=k${i}"
  done
done
```

### What you should see

All three nodes return identical values for every key:
```
=== node on port 8001 ===
k1=v1
k2=v2
...
=== node on port 8002 ===
k1=v1
k2=v2
...
```

### Why

Each `POST /set` is a separate Raft log entry. The leader assigns each a monotonically increasing log index, replicates all of them to a majority before acknowledging success, and the state machine applies them in log order. This guarantees that all nodes apply entries in the same sequence — the core Raft safety property.

---

## Experiment 5 — Leader Failover

This is the most dramatic experiment: kill the current leader and watch the cluster elect a new one.

### What to do

```bash
# Record a value that exists before the kill
curl -s -X POST "http://127.0.0.1:8001/set?key=pre&value=before-kill"

# Find the leader's HTTP port mapping
curl -s http://127.0.0.1:8001/leader   # e.g. 127.0.0.1:7001 → HTTP :8001
```

Now press **Ctrl-C** in the terminal running node1 (the leader).

```bash
# Wait ~400 ms, then check leader on the surviving nodes
sleep 1
curl -s http://127.0.0.1:8002/leader
curl -s http://127.0.0.1:8003/leader
```

Both should now report a new leader (either `127.0.0.1:7002` or `127.0.0.1:7003`).

```bash
# Write through the new leader (adjust port based on /leader output)
# If new leader is node2 (7002 → HTTP 8002):
curl -s -X POST "http://127.0.0.1:8002/set?key=post&value=after-failover"

# Read from the other surviving node to confirm replication
curl -s "http://127.0.0.1:8003/get?key=post"

# Confirm pre-kill data is still intact
curl -s "http://127.0.0.1:8002/get?key=pre"
curl -s "http://127.0.0.1:8003/get?key=pre"
```

### What you should see

```
127.0.0.1:7002          ← new leader
127.0.0.1:7002          ← both agree

after-failover          ← new write succeeded
before-kill             ← old data still present
before-kill
```

### Why

When node1 stops sending heartbeats, node2 and node3 both start an election timer. The first to time out (randomised between 200–400 ms by Raft) becomes a candidate, increments its term, and sends `RequestVote` RPCs over QUIC. Since at least one other node grants its vote, it wins and becomes the new leader. Pre-kill entries are already committed (the old leader confirmed majority replication before responding `ok` to your curl), so they are guaranteed to be in the new leader's log — Raft's Log Matching property ensures this.

---

## Experiment 6 — Status Inspection

### What to do

```bash
# Pretty-print the status of each node
for port in 8001 8002 8003; do
  echo "=== :$port ==="
  curl -s "http://127.0.0.1:${port}/status" | python3 -m json.tool 2>/dev/null \
    || curl -s "http://127.0.0.1:${port}/status"
  echo
done
```

### Key fields to watch

| Field | Meaning |
|-------|---------|
| `state` | `Leader`, `Follower`, or `Candidate` |
| `term` | Current Raft term number |
| `commit_index` | Highest log index known to be committed |
| `applied_index` | Highest log index applied to the FSM |
| `last_log_index` | Highest log index in this node's log |
| `num_peers` | Number of other nodes in the cluster |
| `last_contact` | Time since last heartbeat from leader (followers only) |

### Why

`term` advances by 1 each time a new election is triggered. After the leader failover in Experiment 5, you should see all surviving nodes reporting the same higher term. `commit_index` and `applied_index` should match on all nodes once replication catches up, confirming consistency.

---

## Experiment 7 — Minority Failure (Cluster Remains Available)

A 3-node Raft cluster tolerates 1 failure. Experiment 5 showed the leader failing. This experiment shows a **follower** failing — the cluster stays fully operational.

### What to do

Stop node3 (Ctrl-C in terminal 3) while node1 and node2 are still running.

```bash
# Cluster should still accept writes (majority = 2 of 3)
curl -s -X POST "http://127.0.0.1:8001/set?key=minority&value=still-works"
curl -s "http://127.0.0.1:8002/get?key=minority"
```

### What you should see

```
ok
still-works
```

### Why

The leader only needs acknowledgement from a **majority** (2 of 3 nodes). With node3 down, node1 and node2 form a quorum. Writes and reads continue uninterrupted. The `commit_index` on the two surviving nodes advances normally.

---

## Experiment 8 — Reading the Raft Log via Status

Run several writes, then compare `commit_index` across nodes to watch log advancement:

```bash
# Baseline
curl -s http://127.0.0.1:8001/status | python3 -c "import sys,json; d=json.load(sys.stdin); print('commit_index:', d['commit_index'])"

# Write 3 entries
for k in a b c; do
  curl -s -X POST "http://127.0.0.1:8001/set?key=$k&value=$k"
done

# Check commit_index again on all nodes
for port in 8001 8002 8003; do
  echo -n ":$port commit_index="
  curl -s "http://127.0.0.1:${port}/status" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('commit_index','?'))" 2>/dev/null
done
```

You should see `commit_index` advance by 3 on all live nodes.

---

## Experiment 9 — Rejoin a Restarted Node

After killing node3 in Experiment 7, restart it and watch it catch up.

```bash
# Restart node3 (same flags, no -join needed since cluster remembers it)
./raftd -id node3 -bind 127.0.0.1:7003 -http 127.0.0.1:8003 -join 127.0.0.1:8001
```

```bash
# Wait a moment, then verify it caught up
sleep 1
curl -s "http://127.0.0.1:8003/get?key=minority"   # written while node3 was down
curl -s http://127.0.0.1:8003/status | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('commit_index:', d['commit_index'])"
```

### What you should see

`minority` is readable on node3, and its `commit_index` matches the other two nodes.

### Why

When node3 reconnects and the leader discovers it is behind, it sends the missing log entries via `AppendEntries` (or an `InstallSnapshot` if the gap is large). The rejoined node applies them to its FSM, catching up to the current commit index.

---

## Quick Reference — All curl Commands

```bash
# Check leader
curl -s http://127.0.0.1:8001/leader

# Write (to whichever node is leader)
curl -s -X POST "http://127.0.0.1:8001/set?key=KEY&value=VALUE"

# Read (from any node)
curl -s "http://127.0.0.1:8002/get?key=KEY"

# Raft stats
curl -s http://127.0.0.1:8001/status

# Force-add a node (leader only, used internally by -join)
curl -s -X POST "http://127.0.0.1:8001/join?id=node4&addr=127.0.0.1:7004"
```

---

## What the Logs Tell You

Each node logs to stderr in this format:
```
2026-03-15T10:00:00.000Z [INFO]  node1.raft: entering follower state: ...
2026-03-15T10:00:00.200Z [INFO]  node1.raft: entering candidate state: term=1
2026-03-15T10:00:00.210Z [INFO]  node1.raft: election won: term=1 tally=1
2026-03-15T10:00:00.210Z [INFO]  node1.raft: entering leader state
```

Key log events to watch for:

| Log message | What it means |
|-------------|---------------|
| `entering candidate state` | This node's election timer fired — it started a vote |
| `election won` | Node received majority votes and became leader |
| `entering follower state` | Node stepped down (saw a higher term) |
| `appending to transaction log` | A new log entry is being written |
| `commit index updated` | A majority acknowledged the entry — it is now committed |
| `node joined` | A new peer was successfully added via AddVoter |

---

## Observed Timings (Expected)

| Event | Expected Duration |
|-------|------------------|
| Single-node bootstrap to leader | < 300 ms |
| Full 3-node cluster stabilises | < 1 s |
| Leader failover (kill & new election) | 200 – 500 ms |
| `POST /set` round-trip (healthy cluster) | < 20 ms |
| Follower catches up after rejoin | < 100 ms (small log) |

These are based on the configured timeouts: `HeartbeatTimeout=100ms`, `ElectionTimeout=200ms`.

---

## Troubleshooting

**`not leader; leader is ...` when posting to node1**
- node1 may not be the leader. Use `GET /leader` on any node to find the current leader's QUIC address and map it to the HTTP port via the table at the top of this guide.

**`connection refused` immediately after starting node2/node3**
- node1 is still electing itself. The joining node waits 500 ms automatically before calling `/join`. If the problem persists, wait 1 s and run the node again.

**`(no leader)` returned from `/leader`**
- Fewer than 2 nodes are running, or an election is in progress. Wait 500 ms.

**Reads return `not found` immediately after a write**
- The follower has not yet applied the entry. Wait one heartbeat period (100 ms) and retry.

**macOS: `bind: operation not permitted` or no UDP traffic**
- A VPN or firewall is blocking loopback UDP. Disconnect the VPN or add a rule to allow UDP on 127.0.0.1:7001–7003.
