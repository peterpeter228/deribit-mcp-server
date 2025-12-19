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


async def test_sse_connection(base_url: str = None):
    """Test SSE connection and MCP protocol."""
    # Auto-detect URL based on environment
    if base_url is None:
        import os
        if os.path.exists("/.dockerenv"):
            # Running inside Docker container
            base_url = "http://localhost:8000"  # Container internal port
        else:
            base_url = "http://localhost:8005"  # Host port
    
    print("=" * 60)
    print("MCP Client Test")
    print("=" * 60)
    print(f"Connecting to: {base_url}")
    print()
    
    session_id: Optional[str] = None
    messages_received = []
    initialize_response_received = False
    
    # Use separate clients: one for SSE (long-lived), one for POST requests
    async with httpx.AsyncClient(timeout=30.0) as sse_client, httpx.AsyncClient(timeout=10.0) as post_client:
        # Step 1: Connect to SSE endpoint
        print("Step 1: Connecting to SSE endpoint...")
        try:
            async with sse_client.stream("GET", f"{base_url}/sse") as sse_response:
                print(f"  Status: {sse_response.status_code}")
                
                if sse_response.status_code != 200:
                    print(f"  ERROR: Expected 200, got {sse_response.status_code}")
                    text = await sse_response.aread()
                    print(f"  Response: {text.decode()[:200]}")
                    return False
                
                # Extract session_id from headers
                session_id = sse_response.headers.get("X-Session-Id")
                if not session_id:
                    print("  ERROR: No X-Session-Id header received")
                    return False
                    
                print(f"  Session ID: {session_id}")
                print()
                
                # Step 2: Start reading SSE messages in background
                print("Step 2: Starting SSE message reader...")
                
                async def read_sse_messages():
                    """Read messages from SSE stream."""
                    nonlocal initialize_response_received
                    message_count = 0
                    try:
                        async for line in sse_response.aiter_lines():
                            if not line.strip():
                                continue
                            
                            message_count += 1
                            messages_received.append(line)
                            
                            # Parse SSE format
                            if line.startswith("data:"):
                                data_str = line.split(":", 1)[1].strip()
                                try:
                                    data = json.loads(data_str)
                                    
                                    # Check for initialize response
                                    if isinstance(data, dict) and "id" in data:
                                        if data.get("id") == 1 and "result" in data:
                                            print(f"  ✓ Received initialize response via SSE")
                                            print(f"    Response: {json.dumps(data, indent=2)[:500]}")
                                            initialize_response_received = True
                                            return
                                    
                                    # Log other messages
                                    if message_count <= 3:
                                        print(f"  SSE Message #{message_count}: {json.dumps(data, indent=2)[:200]}")
                                except json.JSONDecodeError:
                                    if message_count <= 3:
                                        print(f"  SSE Message #{message_count} (raw): {data_str[:100]}")
                    except Exception as e:
                        print(f"  SSE reader error: {e}")
                
                # Start reading SSE messages
                sse_task = asyncio.create_task(read_sse_messages())
                
                # Wait a moment for initial connection message
                await asyncio.sleep(0.5)
                
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
                        # Send POST request with session_id in header
                        init_response = await post_client.post(
                            f"{base_url}/mcp/message",
                            json=initialize_request,  # Don't include session_id in body, use header only
                            headers={
                                "Content-Type": "application/json",
                                "X-Session-Id": session_id,
                            },
                        )
                        print(f"  HTTP Status: {init_response.status_code}")
                        
                        if init_response.status_code == 200:
                            try:
                                init_data = init_response.json()
                                print(f"  HTTP Response: {json.dumps(init_data, indent=2)[:500]}")
                                
                                # Check if response indicates success
                                if "result" in init_data:
                                    print("  ✓ Initialize successful (HTTP response)")
                                    initialize_response_received = True
                            except json.JSONDecodeError:
                                print(f"  HTTP Response (raw): {init_response.text[:200]}")
                        else:
                            print(f"  ERROR: HTTP {init_response.status_code}")
                            print(f"  Response: {init_response.text[:200]}")
                            
                    except Exception as e:
                        print(f"  ERROR sending initialize request: {e}")
                        import traceback
                        traceback.print_exc()
                        return False
                    
                    # Step 4: Wait for SSE response (if not already received)
                    if not initialize_response_received:
                        print()
                        print("Step 4: Waiting for initialize response via SSE...")
                        try:
                            await asyncio.wait_for(asyncio.shield(sse_task), timeout=5.0)
                        except asyncio.TimeoutError:
                            print("  Timeout waiting for SSE response")
                        except Exception as e:
                            print(f"  Error waiting for SSE: {e}")
                    
                    # Cancel SSE reader task
                    if not sse_task.done():
                        sse_task.cancel()
                        try:
                            await sse_task
                        except asyncio.CancelledError:
                            pass
                    
                    return initialize_response_received
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
