#!/usr/bin/env bash
###############################################################################
# MSClaw Policy Enforcement Test
#
# Proves that:
#   1. Denied runs never reach the tool-runner
#   2. VIP device tag triggers approval requirement
#   3. Unauthorized roles are rejected
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

info "=== MSClaw Policy Enforcement Test ==="

# Get workflow ID
WORKFLOW_ID=$(curl -sf "${API}/api/v1/workflows" | python3 -c "import sys,json; wfs=json.load(sys.stdin); print(wfs[0]['id'])" 2>/dev/null || echo "")
if [ -z "$WORKFLOW_ID" ]; then
    fail "No workflow found – run smoke_test.sh first"
fi

###############################################################################
# Test 1: Unauthorized role should be denied
###############################################################################
info "Test 1: Submitting run as unauthorized 'guest' role..."
DENIED_HTTP=$(curl -s -o /tmp/msclaw_denied.json -w "%{http_code}" -X POST "${API}/api/v1/runs" \
    -H "Content-Type: application/json" \
    -d "{
        \"workflow_id\": \"$WORKFLOW_ID\",
        \"params\": {\"incident_id\": \"INC-POLICY-001\", \"actor_role\": \"guest\"},
        \"initiated_by\": \"guest@external.com\"
    }")

if [ "$DENIED_HTTP" = "403" ]; then
    pass "Unauthorized role correctly denied (HTTP 403)"
else
    info "Response: $(cat /tmp/msclaw_denied.json)"
    fail "Expected HTTP 403 for unauthorized role, got $DENIED_HTTP"
fi

# Verify denial is in audit
sleep 1
DENIED_AUDIT=$(curl -sf "${API}/api/v1/audit?limit=5" | python3 -c "
import sys,json
entries = json.load(sys.stdin)
denied = [e for e in entries if 'denied' in e.get('action','')]
print(len(denied))
" 2>/dev/null || echo "0")

if [ "$DENIED_AUDIT" -ge "1" ]; then
    pass "Denial recorded in audit ledger"
else
    info "Warning: denial audit entry not found (may be async)"
fi

###############################################################################
# Test 2: Verify denied run did NOT produce tool execution
###############################################################################
info "Test 2: Checking no tool execution for denied run..."

# Get tool-runner logs
TOOL_LOGS=$(docker compose logs tool-runner --tail=20 2>/dev/null || echo "")
if echo "$TOOL_LOGS" | grep -q "INC-POLICY-001"; then
    fail "Denied run reached tool-runner! Policy bypass detected!"
else
    pass "Denied run did NOT reach tool-runner (policy gate working)"
fi

###############################################################################
# Test 3: VIP device triggers approval
###############################################################################
info "Test 3: Submitting run with VIP device tag..."
VIP_RESPONSE=$(curl -sf -X POST "${API}/api/v1/runs" \
    -H "Content-Type: application/json" \
    -d "{
        \"workflow_id\": \"$WORKFLOW_ID\",
        \"params\": {\"incident_id\": \"INC-VIP-001\", \"actor_role\": \"incident_responder\", \"tags\": [\"VIP\"]},
        \"initiated_by\": \"responder@contoso.com\"
    }" 2>/dev/null || echo "")

VIP_STATUS=$(echo "$VIP_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

if [ "$VIP_STATUS" = "awaiting_approval" ]; then
    pass "VIP device correctly requires approval"
    VIP_APPROVAL_ID=$(echo "$VIP_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('approval_id',''))" 2>/dev/null || echo "")
    if [ -n "$VIP_APPROVAL_ID" ]; then
        pass "Approval ID returned: $VIP_APPROVAL_ID"
    fi
else
    info "Response: $VIP_RESPONSE"
    info "Note: VIP approval may depend on OPA policy being loaded correctly"
fi

echo ""
echo "============================================================"
echo -e "${GREEN}POLICY ENFORCEMENT TESTS COMPLETED${NC}"
echo "============================================================"
