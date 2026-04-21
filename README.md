# Raft-over-QUIC

A proof-of-concept implementation of the [Raft consensus algorithm](https://raft.github.io/) running over [QUIC](https://quicwg.org/) as the transport layer, written in Go.

## Why QUIC?

| Feature | TCP | QUIC |
|---------|-----|------|
| Multiplexing | No (head-of-line blocking) | Yes (independent streams) |
| TLS | External | Built-in (TLS 1.3) |
| Connection setup | 1+ RTT + TLS | 0-RTT / 1-RTT |
| Stream isolation | N/A | Each RPC on its own stream |

## Prerequisites

- Go 1.23 or later (`go version`)
- git

## Quick Start

```bash
git clone <repo>
cd raft-quic
go mod download
go build ./cmd/raftd
```

## Running a 3-Node Local Cluster

Open three terminal windows and run:

```bash
# Terminal 1 — bootstrap node
./raftd -id node1 -bind 127.0.0.1:7001 -http 127.0.0.1:8001

# Terminal 2 — join node1
./raftd -id node2 -bind 127.0.0.1:7002 -http 127.0.0.1:8002 -join 127.0.0.1:8001

# Terminal 3 — join node1
./raftd -id node3 -bind 127.0.0.1:7003 -http 127.0.0.1:8003 -join 127.0.0.1:8001
```

`-join` points to the **HTTP** address of any existing cluster member (not the QUIC address).

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/set?key=K&value=V` | Write a key/value (leader only) |
| `GET`  | `/get?key=K` | Read a key (any node, stale read) |
| `GET`  | `/leader` | Current leader QUIC address |
| `POST` | `/join?id=ID&addr=ADDR` | Add a node to the cluster (leader only) |
| `GET`  | `/status` | Raft stats as JSON |

## Verifying the Cluster

```bash
# Wait ~500 ms for leader election, then write
curl -X POST "http://127.0.0.1:8001/set?key=hello&value=world"

# Read from follower (stale read)
curl "http://127.0.0.1:8002/get?key=hello"

# Check who the leader is
curl "http://127.0.0.1:8002/leader"

# Kill node1 (Ctrl-C in terminal 1), then after ~400 ms:
curl "http://127.0.0.1:8002/leader"          # new leader

curl -X POST "http://127.0.0.1:8002/set?key=after&value=failover"
curl "http://127.0.0.1:8003/get?key=after"
```

## Architecture

```
cmd/raftd/main.go          HTTP API + CLI flags
node/node.go               Assembles all components
fsm/fsm.go                 In-memory KV state machine
transport/
  tls.go                   Self-signed TLS cert (ALPN "raft-quic/1")
  stream.go                Wire frame: [1B type][4B len][body]
  conn.go                  Per-peer persistent QUIC connection pool
  pipeline.go              AppendEntriesPipeline implementation
  transport.go             QuicTransport — implements raft.Transport
```

### Wire Protocol

```
+----------+---------+--------------------+
| 1 byte   | 4 bytes | N bytes            |
| RPC Type | Length  | JSON-encoded body  |
+----------+---------+--------------------+
```

RPC types: `0x01` AppendEntries, `0x02` RequestVote, `0x03` InstallSnapshot, `0x04` TimeoutNow.

Each Raft RPC uses one QUIC bidirectional stream: request frame then response frame.

## AWS Cluster (Same-region & Cross-region)

### Prerequisites

```bash
# Tools: terraform >= 1.5, aws configure, go >= 1.23, python3
aws configure          # set Access Key, Secret, default region
terraform -version
go version
```

### Deploy

```bash
# Same-region (3 nodes, us-east-1 by default)
./deploy/deploy.sh same-region

# Cross-region (us-east-1 + us-west-2 + eu-west-1) — uses extended Raft timeouts
./deploy/deploy.sh cross-region
```

Both scripts write a `deploy/cluster-<scenario>.env` file with node IPs and instance IDs, consumed by the benchmark scripts.

### Run Benchmarks

```bash
# Full benchmark matrix: 3/5/7 nodes × same-region/cross-region × QUIC/TCP
bash scripts/aws_distributed_test.sh \
  --cluster-sizes 3,5,7 \
  --scenarios same-region,cross-region \
  --writes 500 \
  --duration 300 \
  --monitor

# Lightweight smoke test (3 nodes, same-region only, 5 writes)
bash scripts/aws_distributed_test.sh \
  --cluster-sizes 3 \
  --scenarios same-region \
  --writes 5 \
  --duration 5 \
  --monitor

# Parallel execution (run 2 test cases simultaneously — check EC2 vCPU quota first)
bash scripts/aws_distributed_test.sh \
  --cluster-sizes 3,5,7 \
  --scenarios same-region,cross-region \
  --writes 500 \
  --parallel-cases 2

# Skip Terraform deploy (reuse existing cluster from deploy/cluster-*.env)
bash scripts/aws_distributed_test.sh \
  --cluster-sizes 3 \
  --scenarios same-region \
  --writes 500 \
  --skip-deploy
```

Results are saved under `results/distributed_test_<timestamp>/`.

### Visualize Results

```bash
# Generate 7 individual charts from a benchmark result directory
conda run -n base python3 scripts/visualize_benchmark.py \
  --results-dir results/full-benchmark-20260421_034557 \
  --out-dir results/full-benchmark-20260421_034557/charts
```

Charts are saved as numbered PNGs:

| File | Content |
|------|---------|
| `01_write_throughput.png` | Write throughput bar chart (same-region vs cross-region) |
| `02_write_latency_percentiles.png` | P50/P95/P99 latency line chart per scenario |
| `03_read_throughput.png` | Read throughput bar chart |
| `04_throughput_ratio.png` | TCP / QUIC throughput multiplier |
| `05_write_error_heatmap.png` | Write error count heatmap |
| `06_write_throughput_scalability.png` | Throughput vs cluster size |
| `07_cross_region_p99_delta.png` | P99 latency delta: cross-region minus same-region |

### Collect Live Metrics (optional)

```bash
# Monitor nodes during a benchmark run (requires cluster-*.env to exist)
python3 scripts/collect_metrics.py \
  --nodes node1=<IP1>,node2=<IP2>,node3=<IP3> \
  --instances node1=<i-xxx>,node2=<i-yyy>,node3=<i-zzz> \
  --regions node1=us-east-1,node2=us-east-1,node3=us-east-1 \
  --interval 5 \
  --duration 300 \
  --protocols quic,tcp \
  --out metrics/
```

### Destroy Infrastructure

```bash
./deploy/teardown.sh same-region
./deploy/teardown.sh cross-region
```

> **Cost note**: t3.micro × 3 costs ~$0.04/hour in ap-east-1. Always run `teardown.sh` when done.

## Docker Cluster

```bash
# Build images and start a 3-node cluster
docker compose up --build -d

# Check status
docker compose ps

# Functional tests (requires curl, python3, docker CLI)
./scripts/test_cluster.sh

# Performance benchmark
pip install requests
python3 scripts/benchmark.py

# Tear down
docker compose down
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-id` | (required) | Node ID |
| `-bind` | `127.0.0.1:7001` | QUIC listen address |
| `-advertise` | (= bind) | QUIC address advertised to peers (set this in Docker) |
| `-http` | `127.0.0.1:8001` | HTTP API address |
| `-data` | (empty) | Snapshot directory; empty = in-memory |
| `-join` | (empty) | HTTP address of cluster member to join |
| `-join-retries` | `10` | Retry attempts when joining fails |

## Benchmark Results (AWS, 2026-04-21)

Source: `results/full-benchmark-20260421_034557/`  
Matrix: **3 / 5 / 7 nodes × same-region / cross-region × QUIC / TCP**  
Workload: **500 writes**, duration **300s**, monitor enabled  
Infrastructure: `t3.micro`; same-region = `us-east-1`; cross-region = `us-east-1` + `us-west-2` + `eu-west-1`

### Write Throughput (ops/s)

| Nodes | QUIC same-region | TCP same-region | QUIC cross-region | TCP cross-region |
|-------|-----------------|-----------------|-------------------|-----------------|
| 3     | 1.60            | **1.77**        | 1.48              | **1.55**        |
| 5     | 1.55            | **1.78**        | 1.45              | **1.59**        |
| 7     | 1.46            | **1.77**        | 1.44              | **1.59**        |

### Write Latency P99 (ms)

| Nodes | QUIC same-region | TCP same-region | QUIC cross-region | TCP cross-region |
|-------|-----------------|-----------------|-------------------|-----------------|
| 3     | 636             | **599**         | 919               | **693**         |
| 5     | 637             | **600**         | 817               | **661**         |
| 7     | 635             | **602**         | 663               | **658**         |

### Read Throughput (ops/s)

| Nodes | QUIC same-region | TCP same-region | QUIC cross-region | TCP cross-region |
|-------|-----------------|-----------------|-------------------|-----------------|
| 3     | 1.78            | 1.78            | 1.36              | 1.77            |
| 5     | 1.78            | 1.77            | 1.37              | 1.77            |
| 7     | 1.78            | 1.77            | 1.78              | 1.78            |

### Write Errors / Retries

- Write errors: **0/6000** (all 12 runs, both protocols)
- QUIC retries: **64**, all recovered (**64/64**)
- TCP retries: **1**, recovered (**1/1**)

## Key Findings

1. **QUIC and TCP are now both stable in write path.**  
   The previous large-scale QUIC write failure no longer appears in this full matrix: all runs completed with zero write errors.

2. **TCP still leads write throughput, but the gap is moderate.**  
   Case-by-case TCP/QUIC write-throughput ratio is **1.05–1.21** (average **1.12**), i.e. TCP is typically about 5–21% faster.

3. **P99 write latency is generally lower on TCP in this run.**  
   TCP has lower P99 in 5/6 scenario-size combinations; largest gap is cross-region 3-node (**919 ms vs 693 ms**).

4. **Read throughput is close in same-region, mixed in cross-region.**  
   Same-region reads are nearly identical (~1.77–1.78 ops/s). In cross-region, QUIC is lower at 3/5 nodes (~1.36–1.37 ops/s), but converges at 7 nodes.

5. **Scale impact is visible for QUIC in same-region writes.**  
   QUIC same-region write throughput drops from **1.60 → 1.46 ops/s** when scaling 3 → 7 nodes, while TCP remains around **1.77–1.78 ops/s**.

## Troubleshooting

**`connection refused` on join**: The bootstrap node needs a moment to elect itself leader (~200 ms). The joining node waits 500 ms automatically, but if the bootstrap node is slow, retry.

**`not leader`**: Writes must go to the leader. Use `GET /leader` to find the current leader's QUIC address, then map it to the corresponding HTTP port.

**QUIC idle timeout**: The QUIC config sets `MaxIdleTimeout=30s` and `KeepAlivePeriod=10s` to prevent connections from dropping during election pauses.

**`operation not permitted` on macOS**: QUIC uses UDP. macOS firewalls/VPNs occasionally block loopback UDP — disable or add an exception.

**EC2 vCPU quota for parallel benchmarks**: The default on-demand standard instance quota is 16 vCPU. Running all 6 test cases in parallel requires up to 30 instances simultaneously. Use `--parallel-cases 2` to stay within the default quota, or request a quota increase via:
```bash
aws service-quotas request-service-quota-increase \
  --service-code ec2 --quota-code L-1216C47A --desired-value 64
```
