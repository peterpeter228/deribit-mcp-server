#!/usr/bin/env python3
"""
Test MCP client to diagnose SSE connection issues.
This simulates a real MCP client's behavior.
"""

import asyncio
import json
import sys
from typing import Optional

import httpx


async def test_sse_connection(base_url: str = "http://localhost:8005"):
    """Test SSE connection and MCP protocol."""
    print("=" * 60)
    print("MCP Client Test")
    print("=" * 60)
    print(f"Connecting to: {base_url}")
    print()
    
    session_id: Optional[str] = None
    messages_received = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Connect to SSE endpoint
        print("Step 1: Connecting to SSE endpoint...")
        try:
            async with client.stream("GET", f"{base_url}/sse") as response:
                print(f"  Status: {response.status_code}")
                print(f"  Headers: {dict(response.headers)}")
                
                if response.status_code != 200:
                    print(f"  ERROR: Expected 200, got {response.status_code}")
                    text = await response.aread()
                    print(f"  Response: {text.decode()[:200]}")
                    return False
                
                # Extract session_id from headers
                session_id = response.headers.get("X-Session-Id")
                print(f"  Session ID: {session_id}")
                print()
                
                # Step 2: Read initial messages from SSE
                print("Step 2: Reading SSE messages...")
                message_count = 0
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    
                    message_count += 1
                    print(f"  Message #{message_count}: {line[:200]}")
                    messages_received.append(line)
                    
                    # Parse SSE format: event: message\ndata: {...}
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        print(f"    Event type: {event_type}")
                    elif line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        try:
                            data = json.loads(data_str)
                            print(f"    Data: {json.dumps(data, indent=2)[:300]}")
                            
                            # Check if this is the initialization message
                            if isinstance(data, dict) and "method" in data:
                                if data.get("method") == "notifications/initialized":
                                    print("    ✓ Received initialization notification")
                                    if "session_id" in data.get("params", {}):
                                        received_session_id = data["params"]["session_id"]
                                        if received_session_id == session_id:
                                            print("    ✓ Session ID matches")
                        except json.JSONDecodeError:
                            print(f"    Data (raw): {data_str[:100]}")
                    
                    # Stop after receiving a few messages
                    if message_count >= 5:
                        print("  (Stopping after 5 messages)")
                        break
                
                print()
                
                # Step 3: Send initialize request
                if session_id:
                    print(f"Step 3: Sending initialize request for session {session_id}...")
                    initialize_request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "test-client",
                                "version": "1.0.0",
                            },
                        },
                    }
                    
                    try:
                        init_response = await client.post(
                            f"{base_url}/mcp/message",
                            json={
                                "session_id": session_id,
                                **initialize_request,
                            },
                            headers={"X-Session-Id": session_id},
                        )
                        print(f"  Status: {init_response.status_code}")
                        init_data = init_response.json()
                        print(f"  Response: {json.dumps(init_data, indent=2)[:500]}")
                        print()
                        
                        # Step 4: Wait for SSE response
                        print("Step 4: Waiting for initialize response via SSE...")
                        await asyncio.sleep(2)
                        
                        # Continue reading SSE for response
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            if line.startswith("data:"):
                                data_str = line.split(":", 1)[1].strip()
                                try:
                                    data = json.loads(data_str)
                                    if isinstance(data, dict) and "id" in data and data.get("id") == 1:
                                        print(f"  ✓ Received initialize response: {json.dumps(data, indent=2)[:500]}")
                                        return True
                                except json.JSONDecodeError:
                                    pass
                            
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        import traceback
                        traceback.print_exc()
                        return False
                else:
                    print("  ERROR: No session_id received")
                    return False
                    
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return False


async def main():
    """Main test function."""
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8005"
    
    success = await test_sse_connection(base_url)
    
    print()
    print("=" * 60)
    if success:
        print("✓ Test PASSED - MCP connection working correctly")
        sys.exit(0)
    else:
        print("✗ Test FAILED - MCP connection has issues")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
