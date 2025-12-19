#!/bin/bash
# Manual SSE connection test script

echo "Testing SSE connection manually..."
echo ""

# Test 1: Connect to SSE and see what we get
echo "1. Connecting to SSE endpoint..."
curl -N -H "Accept: text/event-stream" http://localhost:8005/sse &
SSE_PID=$!

sleep 2

# Test 2: Get session ID from a new connection
echo ""
echo "2. Getting session ID..."
SESSION_RESPONSE=$(curl -s -N -H "Accept: text/event-stream" http://localhost:8005/sse 2>&1 | head -5)
echo "$SESSION_RESPONSE"

# Extract session ID if possible
SESSION_ID=$(echo "$SESSION_RESPONSE" | grep -i "session" | head -1 | sed 's/.*session[:_-]\([a-f0-9-]*\).*/\1/i' | head -1)

if [ -z "$SESSION_ID" ]; then
    # Try to get from headers
    SESSION_ID=$(curl -s -I http://localhost:8005/sse | grep -i "X-Session-Id" | cut -d' ' -f2 | tr -d '\r\n')
fi

if [ -n "$SESSION_ID" ]; then
    echo "Found session ID: $SESSION_ID"
    echo ""
    echo "3. Sending initialize request..."
    
    INIT_RESPONSE=$(curl -s -X POST http://localhost:8005/mcp/message \
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
    
    echo "Initialize response:"
    echo "$INIT_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$INIT_RESPONSE"
else
    echo "Could not extract session ID"
fi

# Cleanup
kill $SSE_PID 2>/dev/null

echo ""
echo "Test complete"
