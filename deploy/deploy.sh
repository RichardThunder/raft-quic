#!/usr/bin/env bash
# deploy.sh – Build the raftd binary, provision EC2 instances with Terraform,
# upload the binary, and start the Raft-over-QUIC cluster.
#
# Usage:
#   ./deploy/deploy.sh [same-region|cross-region]
#
# Prerequisites:
#   • AWS credentials configured (aws configure  OR  env vars AWS_ACCESS_KEY_ID …)
#   • terraform  ≥ 1.5    (brew install terraform)
#   • go         ≥ 1.23
#   • ssh / scp  (macOS built-in)
#   • python3           (macOS built-in)
#   • curl
#
# The script writes deploy/cluster.env with node IPs and SSH key path so that
# benchmark scripts can source it without re-running Terraform.

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
SCENARIO="${1:-same-region}"   # same-region | cross-region
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$SCRIPT_DIR/terraform/$SCENARIO"
BINARY="$SCRIPT_DIR/raftd-linux-amd64"
ENV_FILE="$SCRIPT_DIR/cluster.env"

# Raft timeouts — cross-region needs much larger values due to RTT 150-300 ms.
if [[ "$SCENARIO" == "cross-region" ]]; then
  HB_TIMEOUT="1s"
  EL_TIMEOUT="2s"
else
  HB_TIMEOUT="150ms"
  EL_TIMEOUT="300ms"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Prerequisite checks ────────────────────────────────────────────────────────
check_cmd() { command -v "$1" &>/dev/null || die "'$1' not found. Install it first."; }
check_cmd terraform
check_cmd go
check_cmd ssh
check_cmd scp
check_cmd python3
check_cmd curl
check_cmd aws

info "Scenario : $SCENARIO"
info "HB timeout: $HB_TIMEOUT  |  Election timeout: $EL_TIMEOUT"
echo

# ── Step 1: Build Linux/amd64 binary ──────────────────────────────────────────
info "Building raftd for linux/amd64 …"
cd "$REPO_ROOT"
GOOS=linux GOARCH=amd64 go build -trimpath -o "$BINARY" ./cmd/raftd
success "Binary: $BINARY  ($(du -sh "$BINARY" | cut -f1))"

# ── Step 2: Terraform ─────────────────────────────────────────────────────────
info "Initialising Terraform in $TF_DIR …"
cd "$TF_DIR"
terraform init -upgrade -input=false > /dev/null

info "Planning …"
terraform plan -input=false -compact-warnings

info "Applying (this takes ~60 s for EC2 to boot) …"
terraform apply -input=false -auto-approve -compact-warnings
echo

# ── Step 3: Extract outputs ───────────────────────────────────────────────────
info "Reading Terraform outputs …"
TF_JSON=$(terraform output -json)

parse() {
  # parse <key> [index]
  local key="$1" idx="${2:-}"
  if [[ -n "$idx" ]]; then
    echo "$TF_JSON" | python3 -c \
      "import json,sys; d=json.load(sys.stdin); print(d['$key']['value'][$idx])"
  else
    echo "$TF_JSON" | python3 -c \
      "import json,sys; d=json.load(sys.stdin); print(d['$key']['value'])"
  fi
}

NODE1_IP=$(parse node_ips 0)
NODE2_IP=$(parse node_ips 1)
NODE3_IP=$(parse node_ips 2)
KEY_FILE=$(parse ssh_key_file)
SSH_USER=$(parse ssh_user)
# KEY_FILE from Terraform is an absolute path; normalise for macOS.
[[ -f "$KEY_FILE" ]] || KEY_FILE="$TF_DIR/raft-key.pem"
chmod 600 "$KEY_FILE"

REGION_LABELS=$(echo "$TF_JSON" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(','.join(d['region_labels']['value']))")

info "Node IPs : $NODE1_IP  $NODE2_IP  $NODE3_IP"
info "SSH key  : $KEY_FILE"
info "Regions  : $REGION_LABELS"
echo

# Write env file for benchmark scripts.
cat > "$ENV_FILE" <<EOF
SCENARIO=$SCENARIO
NODE1_IP=$NODE1_IP
NODE2_IP=$NODE2_IP
NODE3_IP=$NODE3_IP
KEY_FILE=$KEY_FILE
SSH_USER=$SSH_USER
HB_TIMEOUT=$HB_TIMEOUT
EL_TIMEOUT=$EL_TIMEOUT
REGION_LABELS=$REGION_LABELS
EOF
success "Cluster env written to $ENV_FILE"

# ── Step 4: Wait for SSH ──────────────────────────────────────────────────────
SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o BatchMode=yes"

wait_ssh() {
  local ip="$1" name="$2"
  info "Waiting for SSH on $name ($ip) …"
  for i in $(seq 1 36); do
    if ssh $SSH_OPTS "$SSH_USER@$ip" "true" 2>/dev/null; then
      success "SSH ready: $name"
      return 0
    fi
    sleep 5
  done
  die "SSH timeout for $name ($ip) after 3 minutes"
}

wait_ssh "$NODE1_IP" "node1"
wait_ssh "$NODE2_IP" "node2"
wait_ssh "$NODE3_IP" "node3"
echo

# ── Step 5: Upload binary ─────────────────────────────────────────────────────
info "Uploading raftd binary to all nodes …"
SCP_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no"
for ip in $NODE1_IP $NODE2_IP $NODE3_IP; do
  scp $SCP_OPTS "$BINARY" "$SSH_USER@$ip:~/raftd" &
done
wait
success "Binary uploaded"

# ── Step 6: Start node1 (bootstrap leader) ────────────────────────────────────
info "Starting node1 (bootstrap) on $NODE1_IP …"
ssh $SSH_OPTS "$SSH_USER@$NODE1_IP" bash <<EOF
pkill -f raftd 2>/dev/null || true
sleep 1
chmod +x ~/raftd
nohup ~/raftd \
  -id node1 \
  -bind 0.0.0.0:7001 \
  -advertise ${NODE1_IP}:7001 \
  -http 0.0.0.0:8001 \
  -heartbeat-timeout ${HB_TIMEOUT} \
  -election-timeout ${EL_TIMEOUT} \
  > ~/raftd.log 2>&1 &
echo \$! > ~/raftd.pid
echo "node1 started (pid \$(cat ~/raftd.pid))"
EOF

# Give node1 time to elect itself as leader before others try to join.
info "Waiting 5 s for node1 to become leader …"
sleep 5

# ── Step 7: Start node2 and node3 (join node1) ────────────────────────────────
start_follower() {
  local id="$1" ip="$2"
  info "Starting ${id} on ${ip} …"
  ssh $SSH_OPTS "$SSH_USER@$ip" bash <<EOF
pkill -f raftd 2>/dev/null || true
sleep 1
chmod +x ~/raftd
nohup ~/raftd \
  -id ${id} \
  -bind 0.0.0.0:7001 \
  -advertise ${ip}:7001 \
  -http 0.0.0.0:8001 \
  -join ${NODE1_IP}:8001 \
  -join-retries 20 \
  -heartbeat-timeout ${HB_TIMEOUT} \
  -election-timeout ${EL_TIMEOUT} \
  > ~/raftd.log 2>&1 &
echo \$! > ~/raftd.pid
echo "${id} started (pid \$(cat ~/raftd.pid))"
EOF
}

start_follower "node2" "$NODE2_IP" &
start_follower "node3" "$NODE3_IP" &
wait
echo

# ── Step 8: Verify cluster health ─────────────────────────────────────────────
info "Waiting for leader election …"
LEADER=""
for i in $(seq 1 30); do
  for ip in $NODE1_IP $NODE2_IP $NODE3_IP; do
    state=$(curl -sf "http://$ip:8001/status" 2>/dev/null \
      | python3 -c "import json,sys; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || true)
    if [[ "$state" == "Leader" ]]; then
      LEADER="$ip"
      break 2
    fi
  done
  sleep 2
done

if [[ -z "$LEADER" ]]; then
  warn "No leader found yet — check logs: ssh $SSH_OPTS $SSH_USER@$NODE1_IP 'cat ~/raftd.log'"
else
  success "Leader: http://$LEADER:8001"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Raft-over-QUIC cluster is UP  ($SCENARIO)${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo
echo "  Node 1: http://$NODE1_IP:8001   (SSH: ssh $SSH_OPTS $SSH_USER@$NODE1_IP)"
echo "  Node 2: http://$NODE2_IP:8001"
echo "  Node 3: http://$NODE3_IP:8001"
echo
echo "Quick test:"
echo "  curl -X POST \"http://$NODE1_IP:8001/set?key=hello&value=world\""
echo "  curl \"http://$NODE2_IP:8001/get?key=hello\""
echo
echo "Functional tests:"
echo "  ./scripts/test_cluster.sh --host '' --ports ${NODE1_IP}:8001,${NODE2_IP}:8001,${NODE3_IP}:8001"
echo
echo "Benchmark:"
echo "  python3 scripts/benchmark_aws.py --env deploy/cluster.env"
echo
echo "Tear down:"
echo "  ./deploy/teardown.sh $SCENARIO"
