#!/bin/bash
# Simple SSE connection test - properly maintains SSE connection

BASE_URL="${1:-http://localhost:8005}"

echo "Testing SSE connection..."
echo ""

# Create temp files
SESSION_ID_FILE="/tmp/sse_test_$$.session"
SSE_OUTPUT_FILE="/tmp/sse_test_$$.output"

# Cleanup function
cleanup() {
    rm -f "$SESSION_ID_FILE" "$SSE_OUTPUT_FILE"
}
trap cleanup EXIT

# Step 1: Connect to SSE and extract session_id
echo "1. Connecting to SSE and extracting session_id..."

# Start SSE connection in background - keep it alive
# Use a simple approach: start curl, extract session_id from logs, keep curl running
curl -s -N -H "Accept: text/event-stream" "$BASE_URL/sse" > "$SSE_OUTPUT_FILE" 2>&1 &
CURL_PID=$!
SSE_BG_PID=$CURL_PID

# Wait a moment for connection to establish and server to log
sleep 1.2

# Extract session_id from logs (most reliable method for Docker)
SESSION_ID=$(docker compose logs --tail 30 2>/dev/null | grep "SSE session created" | tail -1 | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | tail -1)

if [ -n "$SESSION_ID" ]; then
    echo "$SESSION_ID" > "$SESSION_ID_FILE"
fi

# Wait for session_id to be extracted
sleep 1.5

# Read session_id
if [ -f "$SESSION_ID_FILE" ]; then
    SESSION_ID=$(cat "$SESSION_ID_FILE")
else
    # Fallback: try one more time from logs
    sleep 0.5
    SESSION_ID=$(docker compose logs --tail 10 2>/dev/null | grep "SSE session created" | tail -1 | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | tail -1)
fi

if [ -z "$SESSION_ID" ]; then
    echo "ERROR: Could not extract session_id"
    echo "Recent logs:"
    docker compose logs --tail 20 2>/dev/null | grep -E "SSE session" || true
    kill $SSE_BG_PID 2>/dev/null || true
    exit 1
fi

echo "Found session_id: $SESSION_ID"
echo ""

# Verify session exists
SESSION_COUNT=$(docker compose logs --tail 100 2>/dev/null | grep -c "$SESSION_ID" || echo "0")
if [ "$SESSION_COUNT" -gt 0 ]; then
    echo "✓ Session found in logs"
else
    echo "⚠ WARNING: Session not found in recent logs"
fi

# Small delay to ensure session is fully registered
sleep 0.3

echo ""

# Step 2: Send initialize request (SSE connection still alive in background)
echo "2. Sending initialize request..."

# Send POST request with session_id in header
INIT_RESPONSE=$(curl -s -X POST "$BASE_URL/mcp/message" \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: $SESSION_ID" \
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
    }" 2>&1)

echo "Response:"
echo "$INIT_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$INIT_RESPONSE"

# Check if it succeeded
if echo "$INIT_RESPONSE" | grep -q '"error"'; then
    echo ""
    echo "ERROR: Initialize failed"
    echo ""
    echo "Debugging info:"
    echo "  Session ID used: $SESSION_ID"
    echo "  Active sessions in logs:"
    docker compose logs --tail 30 2>/dev/null | grep -E "SSE session created|MCP message|session_id" | tail -10 || true
    kill $SSE_BG_PID 2>/dev/null || true
    exit 1
else
    echo ""
    echo "✓ Initialize successful!"
fi

# Cleanup background process
kill $SSE_BG_PID 2>/dev/null || true
wait $SSE_BG_PID 2>/dev/null || true

echo ""
echo "Test completed successfully!"
