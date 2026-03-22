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

```bash
# Prerequisites: terraform ≥ 1.5, aws configure, go ≥ 1.23
cd raft-quic

# Same region (3 nodes in ap-east-1 Hong Kong)
./deploy/deploy.sh same-region

# Cross region (HK + US-East + EU-West) — uses extended Raft timeouts
./deploy/deploy.sh cross-region

# Benchmark a single running cluster (reads deploy/cluster.env)
python3 scripts/benchmark_aws.py

# Compare same-region vs cross-region side by side
python3 scripts/benchmark_aws.py --compare \
  --same-env deploy/cluster-same.env \
  --cross-env deploy/cluster-cross.env

# Destroy infrastructure
./deploy/teardown.sh same-region
./deploy/teardown.sh cross-region
```

> **Cost note**: t3.micro × 3 costs ~$0.04/hour in ap-east-1. Always `teardown.sh` when done.

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

## Troubleshooting

**`connection refused` on join**: The bootstrap node needs a moment to elect itself leader (~200 ms). The joining node waits 500 ms automatically, but if the bootstrap node is slow, retry.

**`not leader`**: Writes must go to the leader. Use `GET /leader` to find the current leader's QUIC address, then map it to the corresponding HTTP port.

**QUIC idle timeout**: The QUIC config sets `MaxIdleTimeout=30s` and `KeepAlivePeriod=10s` to prevent connections from dropping during election pauses.

**`operation not permitted` on macOS**: QUIC uses UDP. macOS firewalls/VPNs occasionally block loopback UDP — disable or add an exception.
