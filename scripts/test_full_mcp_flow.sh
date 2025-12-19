#!/bin/bash
# Complete MCP flow test script

set -e

BASE_URL="${1:-http://localhost:8005}"
echo "Testing MCP flow at: $BASE_URL"
echo ""

# Step 1: Test health
echo "1. Testing health endpoint..."
HEALTH=$(curl -s "$BASE_URL/health")
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
echo ""

# Step 2: Connect to SSE and get session_id
echo "2. Connecting to SSE endpoint..."
SSE_OUTPUT=$(timeout 3 curl -s -N -H "Accept: text/event-stream" "$BASE_URL/sse" 2>&1 | head -10) || true

# Extract session_id from GET response headers.
# NOTE: Do NOT use HEAD /sse: it may not create/retain a valid session.
SESSION_ID=$(
  timeout 2 bash -c \
    "curl -s -D - -o /dev/null -H \"Accept: text/event-stream\" \"$BASE_URL/sse\" | grep -iE \"^(Mcp-Session-Id|X-Session-Id):\" | head -1 | sed -E 's/^[^:]+:[[:space:]]*([a-f0-9-]{36}).*/\\1/i'"
) || true

if [ -z "$SESSION_ID" ]; then
    echo "ERROR: Could not get session_id from headers"
    echo "SSE output: $SSE_OUTPUT"
    exit 1
fi

echo "Session ID: $SESSION_ID"
echo ""

# Step 3: Send initialize request
echo "3. Sending initialize request..."
INIT_RESPONSE=$(curl -s -X POST "$BASE_URL/mcp/message" \
    -H "Content-Type: application/json" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    -d "{
        \"jsonrpc\": \"2.0\",
        \"id\": 1,
        \"method\": \"initialize\",
        \"params\": {
            \"protocolVersion\": \"2024-11-05\",
            \"capabilities\": {},
            \"clientInfo\": {
                \"name\": \"test-client\",
                \"version\": \"1.0.0\"
            }
        }
    }")

echo "Initialize response:"
echo "$INIT_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$INIT_RESPONSE"
echo ""

# Step 4: Test tools/list
echo "4. Testing tools/list..."
TOOLS_RESPONSE=$(curl -s -X POST "$BASE_URL/mcp/message" \
    -H "Content-Type: application/json" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    -d "{
        \"jsonrpc\": \"2.0\",
        \"id\": 2,
        \"method\": \"tools/list\",
        \"params\": {}
    }")

echo "Tools list response:"
echo "$TOOLS_RESPONSE" | python3 -m json.tool 2>/dev/null | head -30 || echo "$TOOLS_RESPONSE" | head -30
echo ""

echo "✓ All tests completed"
