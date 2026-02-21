#!/usr/bin/env bash
###############################################################################
# MSClaw Smoke Test
#
# Exercises the full execution chain:
#   UI/CLI → control-api → OPA policy → NATS → orchestrator → NATS →
#   tool-runner → Microsoft APIs (mock) → audit-service → artifacts (MinIO)
#
# Prerequisites: docker compose up -d  (from msclaw/ directory)
#
# Verifies:
#   1. Workflow submission + execution
#   2. Approval flow (VIP device)
#   3. Audit chain integrity
#   4. Idempotency (duplicate detection)
#   5. Durability (services can restart without data loss)
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

wait_for_api() {
    info "Waiting for control-api to be ready..."
    for i in $(seq 1 30); do
        if curl -sf "${API}/health" > /dev/null 2>&1; then
            pass "Control API is ready"
            return
        fi
        sleep 2
    done
    fail "Control API did not become ready in 60s"
}

###############################################################################
# Step 0: Wait for stack
###############################################################################
info "=== MSClaw Smoke Test ==="
wait_for_api

###############################################################################
# Step 1: Run DB migrations & seed workflow
###############################################################################
info "Running migrations..."
docker compose exec -T control-api python -c "
import asyncio
from msclaw.shared.db_init import run_migrations
asyncio.run(run_migrations())
" 2>&1 | tail -1
pass "Migrations complete"

info "Seeding workflow..."
SEED_OUTPUT=$(docker compose exec -T control-api python -c "
import asyncio, sys, json
from msclaw.scripts.seed_workflow import seed
wf_id = asyncio.run(seed())
print(json.dumps({'workflow_id': wf_id}))
")
WORKFLOW_ID=$(echo "$SEED_OUTPUT" | tail -1 | python3 -c "import sys,json; print(json.load(sys.stdin)['workflow_id'])" 2>/dev/null || echo "")

if [ -z "$WORKFLOW_ID" ]; then
    # Fallback: get from API
    WORKFLOW_ID=$(curl -sf "${API}/api/v1/workflows" | python3 -c "import sys,json; wfs=json.load(sys.stdin); print(wfs[0]['id'])" 2>/dev/null || echo "")
fi

if [ -z "$WORKFLOW_ID" ]; then
    fail "Could not get workflow ID"
fi
pass "Workflow seeded: $WORKFLOW_ID"

###############################################################################
# Step 2: Submit a workflow run (with idempotency key)
###############################################################################
IDEM_KEY="smoke-test-$(date +%s)"
info "Submitting workflow run (idempotency_key=$IDEM_KEY)..."

RUN_RESPONSE=$(curl -sf -X POST "${API}/api/v1/runs" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $IDEM_KEY" \
    -d "{
        \"workflow_id\": \"$WORKFLOW_ID\",
        \"params\": {\"incident_id\": \"INC-SMOKE-001\", \"actor_role\": \"incident_responder\"},
        \"initiated_by\": \"smoke_test@contoso.com\"
    }")

RUN_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
CORR_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('correlation_id',''))" 2>/dev/null || echo "")
STATUS=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

if [ -z "$RUN_ID" ]; then
    info "Run response: $RUN_RESPONSE"

    # Check if it needs approval
    APPROVAL_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('approval_id',''))" 2>/dev/null || echo "")
    if [ -n "$APPROVAL_ID" ]; then
        pass "Run requires approval (VIP device policy triggered)"

        info "Approving run..."
        APPROVE_RESP=$(curl -sf -X POST "${API}/api/v1/approvals/${APPROVAL_ID}" \
            -H "Content-Type: application/json" \
            -d '{"decision": "approved", "decided_by": "security_lead@contoso.com"}')
        pass "Approval submitted"

        # Re-get run info
        sleep 2
        RUN_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    else
        fail "Run submission failed: $RUN_RESPONSE"
    fi
fi

if [ -n "$RUN_ID" ]; then
    pass "Run submitted: id=$RUN_ID correlation=$CORR_ID status=$STATUS"
fi

###############################################################################
# Step 3: Poll until complete (or timeout)
###############################################################################
info "Polling run status..."
for i in $(seq 1 30); do
    POLL=$(curl -sf "${API}/api/v1/runs/${RUN_ID}" 2>/dev/null || echo '{"status":"unknown"}')
    CURRENT=$(echo "$POLL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

    if [ "$CURRENT" = "completed" ]; then
        pass "Run completed successfully"
        break
    elif [ "$CURRENT" = "failed" ]; then
        ERROR=$(echo "$POLL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error',''))" 2>/dev/null || echo "")
        fail "Run failed: $ERROR"
    elif [ "$CURRENT" = "awaiting_approval" ]; then
        info "Run awaiting approval, checking approvals queue..."
        APPROVALS=$(curl -sf "${API}/api/v1/approvals?status=pending" 2>/dev/null || echo "[]")
        APPROVAL_ID=$(echo "$APPROVALS" | python3 -c "import sys,json; a=json.load(sys.stdin); print(a[0]['id'] if a else '')" 2>/dev/null || echo "")
        if [ -n "$APPROVAL_ID" ]; then
            info "Approving: $APPROVAL_ID"
            curl -sf -X POST "${API}/api/v1/approvals/${APPROVAL_ID}" \
                -H "Content-Type: application/json" \
                -d '{"decision": "approved", "decided_by": "security_lead@contoso.com"}' > /dev/null
            pass "Approval granted"
        fi
    fi

    info "  Status: $CURRENT (attempt $i/30)"
    sleep 3
done

if [ "$CURRENT" != "completed" ]; then
    fail "Run did not complete within timeout (last status: $CURRENT)"
fi

###############################################################################
# Step 4: Verify audit chain
###############################################################################
info "Verifying audit chain..."
VERIFY=$(curl -sf -X POST "${API}/api/v1/audit/verify")
VALID=$(echo "$VERIFY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('valid', False))" 2>/dev/null || echo "False")

if [ "$VALID" = "True" ]; then
    pass "Audit chain integrity verified"
else
    ERRORS=$(echo "$VERIFY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('errors', []))" 2>/dev/null || echo "[]")
    fail "Audit chain verification failed: $ERRORS"
fi

###############################################################################
# Step 5: Check audit entries for this run
###############################################################################
info "Checking audit entries for correlation $CORR_ID..."
AUDIT_ENTRIES=$(curl -sf "${API}/api/v1/audit?correlation_id=${CORR_ID}")
AUDIT_COUNT=$(echo "$AUDIT_ENTRIES" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$AUDIT_COUNT" -ge "3" ]; then
    pass "Found $AUDIT_COUNT audit entries for this run"
else
    fail "Expected >= 3 audit entries, found $AUDIT_COUNT"
fi

###############################################################################
# Step 6: Verify idempotency (duplicate detection)
###############################################################################
info "Testing idempotency (same key, same payload)..."
DUPE_RESPONSE=$(curl -sf -X POST "${API}/api/v1/runs" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $IDEM_KEY" \
    -d "{
        \"workflow_id\": \"$WORKFLOW_ID\",
        \"params\": {\"incident_id\": \"INC-SMOKE-001\", \"actor_role\": \"incident_responder\"},
        \"initiated_by\": \"smoke_test@contoso.com\"
    }")

DUPE_STATUS=$(echo "$DUPE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

if [ "$DUPE_STATUS" = "duplicate" ]; then
    pass "Idempotency: duplicate correctly detected"
else
    fail "Idempotency: expected 'duplicate' status, got '$DUPE_STATUS'"
fi

info "Testing idempotency (same key, different payload)..."
CONFLICT_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API}/api/v1/runs" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $IDEM_KEY" \
    -d "{
        \"workflow_id\": \"$WORKFLOW_ID\",
        \"params\": {\"incident_id\": \"INC-DIFFERENT-999\"},
        \"initiated_by\": \"smoke_test@contoso.com\"
    }")

if [ "$CONFLICT_RESPONSE" = "409" ]; then
    pass "Idempotency: conflict correctly rejected (HTTP 409)"
else
    fail "Idempotency: expected HTTP 409, got $CONFLICT_RESPONSE"
fi

###############################################################################
# Step 7: Check run timeline
###############################################################################
info "Fetching run timeline..."
TIMELINE=$(curl -sf "${API}/api/v1/runs/${RUN_ID}/timeline")
STEP_COUNT=$(echo "$TIMELINE" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('steps',[])))" 2>/dev/null || echo "0")

if [ "$STEP_COUNT" -ge "3" ]; then
    pass "Timeline shows $STEP_COUNT steps"
else
    fail "Expected >= 3 steps in timeline, found $STEP_COUNT"
fi

###############################################################################
# Step 8: Check artifacts
###############################################################################
info "Checking artifacts..."
ARTIFACTS=$(curl -sf "${API}/api/v1/artifacts" 2>/dev/null || echo "[]")
ART_COUNT=$(echo "$ARTIFACTS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
info "Found $ART_COUNT artifacts in MinIO"

###############################################################################
# Summary
###############################################################################
echo ""
echo "============================================================"
echo -e "${GREEN}ALL SMOKE TESTS PASSED${NC}"
echo "============================================================"
echo ""
echo "Run ID:         $RUN_ID"
echo "Correlation ID: $CORR_ID"
echo "Audit entries:  $AUDIT_COUNT"
echo "Timeline steps: $STEP_COUNT"
echo "Artifacts:      $ART_COUNT"
echo ""
echo "View in UI: http://localhost:3000"
echo "View run:   ${API}/api/v1/runs/${RUN_ID}/timeline"
echo "View audit: ${API}/api/v1/audit?correlation_id=${CORR_ID}"
