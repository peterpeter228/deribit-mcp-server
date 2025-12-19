#!/bin/bash
# Simple SSE connection test

BASE_URL="${1:-http://localhost:8005}"

echo "Testing SSE connection..."
echo ""

# Method 1: Get session_id from a real SSE connection
echo "1. Connecting to SSE and extracting session_id..."

# Start SSE connection in background and capture headers
SSE_PID=$(curl -s -N -H "Accept: text/event-stream" "$BASE_URL/sse" > /tmp/sse_output.txt 2>&1 & echo $!)
sleep 1

# Get session_id from the last created session (check logs)
SESSION_ID=$(docker compose logs --tail 5 2>/dev/null | grep "SSE session created" | tail -1 | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | tail -1)

if [ -z "$SESSION_ID" ]; then
    # Try alternative method: parse from curl headers
    SESSION_ID=$(curl -s -I "$BASE_URL/sse" 2>/dev/null | grep -i "x-session-id" | sed -E 's/.*[Xx]-[Ss]ession-[Ii][Dd][[:space:]]*:[[:space:]]*([a-f0-9-]{36}).*/\1/i')
fi

kill $SSE_PID 2>/dev/null

if [ -z "$SESSION_ID" ]; then
    echo "ERROR: Could not extract session_id"
    echo "SSE output (first 10 lines):"
    head -10 /tmp/sse_output.txt 2>/dev/null || echo "No output"
    exit 1
fi

echo "Found session_id: $SESSION_ID"
echo ""

# Step 2: Send initialize request
echo "2. Sending initialize request..."
INIT_RESPONSE=$(curl -s -X POST "$BASE_URL/mcp/message" \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: $SESSION_ID" \
    -d "{
        \"session_id\": \"$SESSION_ID\",
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

echo "Response:"
echo "$INIT_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$INIT_RESPONSE"

# Check if it succeeded
if echo "$INIT_RESPONSE" | grep -q '"error"'; then
    echo ""
    echo "ERROR: Initialize failed"
    exit 1
else
    echo ""
    echo "✓ Initialize successful!"
fi
