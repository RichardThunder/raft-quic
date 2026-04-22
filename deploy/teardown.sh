#!/usr/bin/env bash
# teardown.sh – Stop raftd on all nodes and destroy AWS infrastructure.
#
# Usage:
#   ./deploy/teardown.sh [same-region|cross-region]

set -euo pipefail

SCENARIO="${1:-same-region}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TF_DIR="$SCRIPT_DIR/terraform/$SCENARIO"
ENV_FILE="$SCRIPT_DIR/cluster.env"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
die()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
check_cmd() { command -v "$1" &>/dev/null || die "'$1' not found. Install it first."; }
check_aws_auth() {
  info "Validating AWS credentials with STS …"
  if ! aws sts get-caller-identity >/dev/null 2>&1; then
    die "AWS credentials are invalid or expired. Fix ~/.aws/credentials or your active profile, then retry. Useful checks: 'aws configure list', 'aws sts get-caller-identity', or 'aws sso login'."
  fi
  success "AWS credentials are valid"
}

check_cmd terraform
check_cmd aws
check_aws_auth

# Try to stop raftd gracefully before destroying instances.
if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
  SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes"
  for ip in $NODE1_IP $NODE2_IP $NODE3_IP; do
    info "Stopping raftd on $ip …"
    ssh $SSH_OPTS "$SSH_USER@$ip" "pkill -f raftd 2>/dev/null; true" 2>/dev/null || true
  done
  success "raftd processes stopped"
fi

info "Running terraform destroy for $SCENARIO …"
cd "$TF_DIR"
terraform destroy -input=false -auto-approve -compact-warnings

# Clean up local files.
rm -f "$TF_DIR/raft-key.pem" "$ENV_FILE"
success "Infrastructure destroyed and local keys removed"
