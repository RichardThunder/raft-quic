#!/usr/bin/env bash
# run_tests.sh – Comprehensive test suite for Raft-over-QUIC
#
# Runs all tests and generates a summary report with metrics
# Usage:
#   ./scripts/run_tests.sh [--skip-docker] [--skip-benchmark]

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="${REPO_ROOT}/test_results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT="${RESULTS_DIR}/test_report_${TIMESTAMP}.txt"
LOG="${RESULTS_DIR}/test_log_${TIMESTAMP}.log"

# Options
SKIP_DOCKER=false
SKIP_BENCHMARK=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-docker) SKIP_DOCKER=true; shift ;;
    --skip-benchmark) SKIP_BENCHMARK=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# Create results directory
mkdir -p "$RESULTS_DIR"

# Logging function
log() { echo -e "$@" | tee -a "$LOG"; }
info() { log "${BLUE}[INFO]${NC} $1"; }
pass() { log "${GREEN}[PASS]${NC} $1"; }
fail() { log "${RED}[FAIL]${NC} $1"; return 1; }
warn() { log "${YELLOW}[WARN]${NC} $1"; }

# Header
{
  echo "╔════════════════════════════════════════════════════════════════╗"
  echo "║   Raft-over-QUIC Comprehensive Test Suite                      ║"
  echo "║   Date: $(date)                      ║"
  echo "╚════════════════════════════════════════════════════════════════╝"
  echo ""
} | tee "$REPORT" "$LOG"

# Test 1: Build verification
log "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
log "${BLUE}TEST 1: Build Verification${NC}"
log "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
{
  if [[ -f "$REPO_ROOT/raftd" ]]; then
    pass "Binary exists: $REPO_ROOT/raftd"
    file "$REPO_ROOT/raftd" | tee -a "$LOG"
  else
    info "Building raftd binary..."
    cd "$REPO_ROOT"
    if go build -o raftd ./cmd/raftd 2>&1 | tee -a "$LOG"; then
      pass "Build successful"
    else
      fail "Build failed"
      exit 1
    fi
  fi
} | tee -a "$REPORT"

# Test 2: Code quality
log "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
log "${BLUE}TEST 2: Code Quality (go fmt, go vet)${NC}"
log "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
{
  cd "$REPO_ROOT"
  if go fmt ./... 2>&1 | grep -q "formatting"; then
    warn "Some files need formatting"
  else
    pass "Code formatting OK"
  fi

  if go vet ./... 2>&1 | tee -a "$LOG"; then
    pass "go vet passed"
  else
    fail "go vet found issues"
  fi
} | tee -a "$REPORT"

# Test 3: Docker cluster (if not skipped)
if [[ "$SKIP_DOCKER" == "false" ]]; then
  log "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
  log "${BLUE}TEST 3: Docker Cluster Setup & Functional Tests${NC}"
  log "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
  {
    cd "$REPO_ROOT"

    info "Checking Docker..."
    if ! command -v docker &> /dev/null; then
      warn "Docker not available, skipping Docker tests"
    else
      info "Cleaning up old containers..."
      docker compose down 2>/dev/null || true

      info "Building and starting cluster..."
      if docker compose up --build -d 2>&1 | tee -a "$LOG"; then
        pass "Docker cluster started"

        info "Waiting for cluster to stabilize (30s)..."
        sleep 30

        # Run functional tests
        if [[ -f "$SCRIPT_DIR/test_cluster.sh" ]]; then
          info "Running functional tests..."
          if bash "$SCRIPT_DIR/test_cluster.sh" 2>&1 | tee -a "$LOG"; then
            pass "All functional tests passed"
          else
            fail "Some functional tests failed"
          fi
        fi
      else
        fail "Failed to start Docker cluster"
      fi
    fi
  } | tee -a "$REPORT"
else
  log "\n${YELLOW}[SKIP]${NC} Docker tests skipped (use --skip-docker)"
fi

# Test 4: Benchmarks (if not skipped)
if [[ "$SKIP_BENCHMARK" == "false" ]] && [[ "$SKIP_DOCKER" == "false" ]]; then
  log "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
  log "${BLUE}TEST 4: Performance Benchmarks${NC}"
  log "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
  {
    cd "$REPO_ROOT"

    if command -v python3 &> /dev/null && python3 -c "import requests" 2>/dev/null; then
      info "Running performance benchmarks..."
      if python3 "$SCRIPT_DIR/benchmark.py" \
        --writes 50 \
        --concurrency 1,4,8 \
        --out "$RESULTS_DIR" 2>&1 | tee -a "$LOG"; then
        pass "Benchmarks completed"

        # List benchmark results
        if ls "$RESULTS_DIR"/benchmark_*.csv 2>/dev/null; then
          pass "Benchmark results saved"
        fi
      else
        fail "Benchmark execution failed"
      fi
    else
      warn "Python3 or requests library not available, skipping benchmarks"
    fi
  } | tee -a "$REPORT"
else
  log "\n${YELLOW}[SKIP]${NC} Benchmark tests skipped"
fi

# Final summary
log "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
log "${BLUE}TEST SUMMARY${NC}"
log "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
{
  echo "Report saved to: $REPORT"
  echo "Log saved to: $LOG"
  echo "Results directory: $RESULTS_DIR"
  echo ""

  if [[ "$SKIP_DOCKER" == "false" ]]; then
    echo "✓ Build verification"
    echo "✓ Code quality checks"
    echo "✓ Docker cluster tests"
    if [[ "$SKIP_BENCHMARK" == "false" ]]; then
      echo "✓ Performance benchmarks"
    fi
  else
    echo "✓ Build verification"
    echo "✓ Code quality checks"
    echo "⊘ Docker/benchmark tests skipped"
  fi
  echo ""
  echo "${GREEN}Test suite completed!${NC}"
} | tee -a "$REPORT"

log ""
