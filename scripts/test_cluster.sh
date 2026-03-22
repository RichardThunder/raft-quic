#!/usr/bin/env bash
# test_cluster.sh – Automated functional tests for the Raft-over-QUIC cluster.
#
# Prerequisites:
#   docker compose up --build -d   (from the repo root)
#
# Usage:
#   ./scripts/test_cluster.sh [--host HOST] [--ports 8001,8002,8003]
#
# Exit code: 0 = all tests passed, non-zero = at least one test failed.

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
HOST="localhost"
PORTS=(8001 8002 8003)
WAIT_TIMEOUT=60   # seconds to wait for cluster to become ready
PASS=0
FAIL=0

# Parse optional arguments.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --ports) IFS=',' read -r -a PORTS <<< "$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

URLS=()
for p in "${PORTS[@]}"; do
  URLS+=("http://${HOST}:${p}")
done

# ── Helpers ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

# Returns the raft state ("Leader", "Follower", "Candidate") for a node URL.
get_state() {
  curl -sf "$1/status" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state','unknown'))" \
    2>/dev/null || echo "unreachable"
}

# Returns true if the URL is reachable.
is_alive() { curl -sf "$1/status" > /dev/null 2>&1; }

# Find the URL of the current leader.
find_leader_url() {
  for url in "${URLS[@]}"; do
    if [[ "$(get_state "$url")" == "Leader" ]]; then
      echo "$url"; return 0
    fi
  done
  echo ""; return 1
}

# Wait until at least one node reports it is the Leader.
wait_for_leader() {
  local deadline=$((SECONDS + WAIT_TIMEOUT))
  while [[ $SECONDS -lt $deadline ]]; do
    leader=$(find_leader_url)
    if [[ -n "$leader" ]]; then
      echo "$leader"; return 0
    fi
    sleep 1
  done
  return 1
}

section() { echo; echo "══════════════════════════════════════════"; echo "  $1"; echo "══════════════════════════════════════════"; }

# ── Tests ──────────────────────────────────────────────────────────────────────

section "Test 1: Cluster Readiness"
info "Waiting up to ${WAIT_TIMEOUT}s for a leader to be elected…"
LEADER_URL=$(wait_for_leader) || { fail "No leader elected within ${WAIT_TIMEOUT}s"; exit 1; }
pass "Leader elected: ${LEADER_URL}"

for url in "${URLS[@]}"; do
  state=$(get_state "$url")
  if [[ "$state" == "Leader" || "$state" == "Follower" ]]; then
    pass "Node ${url} is in state: ${state}"
  else
    fail "Node ${url} is in unexpected state: ${state}"
  fi
done

section "Test 2: Write to Leader"
curl -sf -X POST "${LEADER_URL}/set?key=hello&value=world" > /dev/null \
  && pass "SET hello=world on leader (${LEADER_URL})" \
  || fail "SET hello=world failed"

curl -sf -X POST "${LEADER_URL}/set?key=foo&value=bar" > /dev/null \
  && pass "SET foo=bar on leader" \
  || fail "SET foo=bar failed"

section "Test 3: Reject Write on Follower"
for url in "${URLS[@]}"; do
  if [[ "$url" != "$LEADER_URL" ]]; then
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${url}/set?key=x&value=y")
    if [[ "$http_code" == "503" ]]; then
      pass "Follower ${url} correctly rejected write with 503"
    else
      fail "Follower ${url} returned ${http_code} (expected 503)"
    fi
    break
  fi
done

section "Test 4: Read Consistency Across All Nodes"
sleep 1  # allow replication to propagate
for url in "${URLS[@]}"; do
  val=$(curl -sf "${url}/get?key=hello" 2>/dev/null || echo "ERROR")
  if [[ "$val" == "world" ]]; then
    pass "Read hello=world from ${url}"
  else
    fail "Read hello from ${url}: got '${val}' (expected 'world')"
  fi
done

section "Test 5: Multiple Keys"
for i in $(seq 1 5); do
  curl -sf -X POST "${LEADER_URL}/set?key=key${i}&value=val${i}" > /dev/null \
    || fail "SET key${i} failed"
done
sleep 1
for i in $(seq 1 5); do
  val=$(curl -sf "${LEADER_URL}/get?key=key${i}" 2>/dev/null)
  if [[ "$val" == "val${i}" ]]; then
    pass "key${i}=val${i} ✓"
  else
    fail "key${i}: expected val${i}, got '${val}'"
  fi
done

section "Test 6: Leader Failover"
info "Identifying leader container to stop…"

# Determine which container corresponds to the leader URL.
LEADER_PORT=$(echo "$LEADER_URL" | grep -oP ':\K\d+$')
LEADER_CONTAINER=""
case "$LEADER_PORT" in
  8001) LEADER_CONTAINER="raft-node1" ;;
  8002) LEADER_CONTAINER="raft-node2" ;;
  8003) LEADER_CONTAINER="raft-node3" ;;
esac

if [[ -z "$LEADER_CONTAINER" ]]; then
  fail "Could not identify leader container from port ${LEADER_PORT}"
else
  info "Stopping leader container: ${LEADER_CONTAINER}"
  docker stop "$LEADER_CONTAINER" > /dev/null 2>&1 || true

  info "Waiting for new leader to be elected among remaining nodes…"
  # Filter out the stopped node's URL.
  REMAINING_URLS=()
  for url in "${URLS[@]}"; do
    [[ "$url" != "$LEADER_URL" ]] && REMAINING_URLS+=("$url")
  done

  NEW_LEADER=""
  deadline=$((SECONDS + 30))
  while [[ $SECONDS -lt $deadline ]]; do
    for url in "${REMAINING_URLS[@]}"; do
      if is_alive "$url" && [[ "$(get_state "$url")" == "Leader" ]]; then
        NEW_LEADER="$url"; break 2
      fi
    done
    sleep 1
  done

  if [[ -n "$NEW_LEADER" ]]; then
    pass "New leader elected: ${NEW_LEADER} (failover in $((SECONDS - (deadline - 30)))s)"
  else
    fail "No new leader elected within 30s after stopping ${LEADER_CONTAINER}"
  fi

  section "Test 7: Write to New Leader After Failover"
  curl -sf -X POST "${NEW_LEADER}/set?key=after_failover&value=yes" > /dev/null \
    && pass "Write succeeded on new leader ${NEW_LEADER}" \
    || fail "Write failed on new leader"

  section "Test 8: Data Consistency After Failover"
  sleep 1
  for url in "${REMAINING_URLS[@]}"; do
    val=$(curl -sf "${url}/get?key=after_failover" 2>/dev/null || echo "ERROR")
    if [[ "$val" == "yes" ]]; then
      pass "after_failover=yes from ${url}"
    else
      fail "after_failover from ${url}: got '${val}'"
    fi
  done

  section "Test 9: Node Recovery"
  info "Restarting stopped container: ${LEADER_CONTAINER}"
  docker start "$LEADER_CONTAINER" > /dev/null 2>&1 || true
  sleep 5  # allow node to rejoin and catch up

  # Verify the restarted node serves consistent data.
  val=$(curl -sf "${LEADER_URL}/get?key=after_failover" 2>/dev/null || echo "ERROR")
  if [[ "$val" == "yes" ]]; then
    pass "Restarted node ${LEADER_CONTAINER} has consistent data after recovery"
  else
    fail "Restarted node ${LEADER_CONTAINER}: got '${val}' for after_failover (expected 'yes')"
  fi
fi

# ── Summary ────────────────────────────────────────────────────────────────────
section "Results"
TOTAL=$((PASS + FAIL))
echo -e "Tests run: ${TOTAL}   ${GREEN}Passed: ${PASS}${NC}   ${RED}Failed: ${FAIL}${NC}"
if [[ $FAIL -eq 0 ]]; then
  echo -e "${GREEN}All tests passed!${NC}"
  exit 0
else
  echo -e "${RED}${FAIL} test(s) failed.${NC}"
  exit 1
fi
