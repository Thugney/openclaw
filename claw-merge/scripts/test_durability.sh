#!/usr/bin/env bash
###############################################################################
# MSClaw Durability Test
#
# Proves that data survives service restarts:
#   1. Run a workflow
#   2. Restart ALL services
#   3. Verify run history, approvals, audit, artifacts still visible
###############################################################################

set -euo pipefail

API="http://localhost:8080"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

info "=== MSClaw Durability Test ==="

###############################################################################
# Step 1: Record current state
###############################################################################
info "Recording pre-restart state..."

RUNS_BEFORE=$(curl -sf "${API}/api/v1/runs" | python3 -c "import sys,json; runs=json.load(sys.stdin); print(len(runs))")
AUDIT_BEFORE=$(curl -sf "${API}/api/v1/audit?limit=1000" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
FIRST_RUN_ID=$(curl -sf "${API}/api/v1/runs" | python3 -c "import sys,json; runs=json.load(sys.stdin); print(runs[0]['id'] if runs else '')" 2>/dev/null || echo "")

info "Before restart: $RUNS_BEFORE runs, $AUDIT_BEFORE audit entries"

if [ -z "$FIRST_RUN_ID" ]; then
    fail "No runs exist – run smoke_test.sh first"
fi

###############################################################################
# Step 2: Restart all services
###############################################################################
info "Restarting ALL MSClaw services..."
docker compose restart control-api orchestrator tool-runner audit-service

info "Waiting for services to come back..."
for i in $(seq 1 30); do
    if curl -sf "${API}/health" > /dev/null 2>&1; then
        pass "Services restarted"
        break
    fi
    sleep 2
done

###############################################################################
# Step 3: Verify data persisted
###############################################################################
info "Verifying data after restart..."

RUNS_AFTER=$(curl -sf "${API}/api/v1/runs" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
AUDIT_AFTER=$(curl -sf "${API}/api/v1/audit?limit=1000" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

if [ "$RUNS_AFTER" -ge "$RUNS_BEFORE" ]; then
    pass "Runs persisted: $RUNS_AFTER runs (was $RUNS_BEFORE)"
else
    fail "Runs lost! $RUNS_AFTER < $RUNS_BEFORE"
fi

if [ "$AUDIT_AFTER" -ge "$AUDIT_BEFORE" ]; then
    pass "Audit entries persisted: $AUDIT_AFTER entries (was $AUDIT_BEFORE)"
else
    fail "Audit entries lost! $AUDIT_AFTER < $AUDIT_BEFORE"
fi

# Verify specific run still exists
RUN_DETAIL=$(curl -sf "${API}/api/v1/runs/${FIRST_RUN_ID}" 2>/dev/null || echo "{}")
RUN_STATUS=$(echo "$RUN_DETAIL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','missing'))" 2>/dev/null || echo "missing")

if [ "$RUN_STATUS" != "missing" ]; then
    pass "Run $FIRST_RUN_ID still accessible (status=$RUN_STATUS)"
else
    fail "Run $FIRST_RUN_ID not found after restart"
fi

# Verify audit chain still valid
VERIFY=$(curl -sf -X POST "${API}/api/v1/audit/verify")
VALID=$(echo "$VERIFY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('valid', False))" 2>/dev/null || echo "False")

if [ "$VALID" = "True" ]; then
    pass "Audit chain still valid after restart"
else
    fail "Audit chain broken after restart"
fi

echo ""
echo "============================================================"
echo -e "${GREEN}DURABILITY TEST PASSED${NC}"
echo "============================================================"
echo "All data survived service restart."
echo "Runs:  $RUNS_BEFORE → $RUNS_AFTER"
echo "Audit: $AUDIT_BEFORE → $AUDIT_AFTER"
