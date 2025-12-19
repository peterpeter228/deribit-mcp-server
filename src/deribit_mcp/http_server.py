"""
HTTP/SSE Server implementation for Deribit MCP.

This module provides HTTP-based transport for the MCP server,
enabling integration with web clients and remote deployments.

Supports:
- SSE (Server-Sent Events) for streaming responses
- Standard HTTP endpoints for tool invocation
- Health check endpoint

Usage:
    # Start HTTP server
    python -m deribit_mcp.http_server

    # Or use the entry point
    deribit-mcp-http

    # With custom host/port via env vars
    DERIBIT_HOST=0.0.0.0 DERIBIT_PORT=8080 deribit-mcp-http
"""

import asyncio
import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .client import get_client, shutdown_client
from .config import get_settings, sanitize_log_message
from .diagnostics import run_full_diagnostics, test_authentication, test_private_api, test_public_api
from .server import _dispatch_tool, get_private_tools, get_public_tools
from .tools import deribit_status

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("deribit_mcp.http")


def _compact_json(data: dict) -> str:
    """Convert dict to compact JSON string."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


# =============================================================================
# SSE Session Management
# =============================================================================


class SSESession:
    """Manages an SSE session with message queue."""

    # Heartbeat interval (seconds)
    HEARTBEAT_INTERVAL = 30.0
    # Connection timeout (seconds) - close if no activity
    CONNECTION_TIMEOUT = 300.0  # 5 minutes

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.created_at = asyncio.get_event_loop().time()
        self.last_activity = asyncio.get_event_loop().time()
        self._closed = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def send(self, event: str, data: dict):
        """
        Send an event to the client.
        
        Args:
            event: Event type (ignored, always uses "message" for MCP)
            data: JSON-RPC 2.0 formatted message dict
        """
        if self._closed:
            return
        self.last_activity = asyncio.get_event_loop().time()
        # Format as MCP message - all messages use "message" event type
        # Data should already be JSON-RPC 2.0 formatted
        await self.queue.put(
            {
                "event": "message",  # MCP standard event type
                "data": _compact_json(data),
            }
        )

    async def close(self):
        """Close the session."""
        if self._closed:
            return
        self._closed = True
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self.queue.put(None)

    def mark_activity(self):
        """Mark that there was activity on this session."""
        self.last_activity = asyncio.get_event_loop().time()

    def is_timed_out(self) -> bool:
        """Check if session has timed out."""
        if self._closed:
            return True
        elapsed = asyncio.get_event_loop().time() - self.last_activity
        return elapsed > self.CONNECTION_TIMEOUT


# Global session storage
_sessions: dict[str, SSESession] = {}
_shutdown_event: Optional[asyncio.Event] = None


async def _cleanup_stale_sessions():
    """Periodically clean up stale/timed out sessions."""
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            if _shutdown_event and _shutdown_event.is_set():
                break

            now = asyncio.get_event_loop().time()
            timed_out_sessions = [
                session_id
                for session_id, session in list(_sessions.items())
                if session.is_timed_out()
            ]

            for session_id in timed_out_sessions:
                logger.info(f"Cleaning up timed out SSE session: {session_id}")
                session = _sessions.get(session_id)
                if session:
                    await session.close()
                if session_id in _sessions:
                    del _sessions[session_id]

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")


async def _send_heartbeat(session: SSESession):
    """Send periodic heartbeat to keep connection alive."""
    try:
        # Wait longer before starting heartbeat to let connection fully establish
        # MCP clients may need time to process initialization
        await asyncio.sleep(30.0)
        
        heartbeat_count = 0
        while not session._closed:
            if session._closed or session.is_timed_out():
                break
            
            try:
                # Send heartbeat as MCP notification (optional, some clients don't need it)
                # Only send if session is still active
                if not session._closed:
                    heartbeat_message = {
                        "jsonrpc": "2.0",
                        "method": "ping",
                        "params": {
                            "timestamp": asyncio.get_event_loop().time(),
                            "session_id": session.session_id,
                            "count": heartbeat_count,
                        },
                    }
                    await session.send("notification", heartbeat_message)
                    heartbeat_count += 1
                    logger.debug(f"Heartbeat #{heartbeat_count} sent for session {session.session_id}")
            except Exception as e:
                logger.debug(f"Error sending heartbeat for {session.session_id}: {e}")
                # Don't break on heartbeat errors, just log and continue
                pass
            
            # Wait for next heartbeat interval
            await asyncio.sleep(session.HEARTBEAT_INTERVAL)
            
    except asyncio.CancelledError:
        logger.debug(f"Heartbeat task cancelled for session {session.session_id}")
    except Exception as e:
        logger.debug(f"Heartbeat error for session {session.session_id}: {e}")


# =============================================================================
# HTTP Endpoints
# =============================================================================


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint with detailed diagnostics."""
    settings = get_settings()
    client = get_client()
    
    diagnostics = {
        "status": "healthy",
        "env": settings.env.value,
        "api_ok": False,
        "private_enabled": settings.enable_private,
        "has_credentials": settings.has_credentials,
        "errors": [],
    }

    # Test public API
    try:
        status = await deribit_status(client=client)
        diagnostics["api_ok"] = status.get("api_ok", False)
        diagnostics["server_time_ms"] = status.get("server_time_ms")
    except Exception as e:
        diagnostics["api_ok"] = False
        diagnostics["errors"].append(f"Public API error: {str(e)[:100]}")
        logger.error(f"Health check failed: {e}", exc_info=True)

    # Test authentication if private API is enabled
    if settings.enable_private:
        try:
            if not settings.has_credentials:
                diagnostics["errors"].append("Private API enabled but no credentials configured")
                diagnostics["status"] = "degraded"
            else:
                # Try to get access token
                try:
                    token = await client._get_access_token()
                    if token:
                        diagnostics["auth_ok"] = True
                    else:
                        diagnostics["auth_ok"] = False
                        diagnostics["errors"].append("Authentication returned empty token")
                        diagnostics["status"] = "degraded"
                except Exception as auth_error:
                    diagnostics["auth_ok"] = False
                    diagnostics["errors"].append(f"Authentication failed: {str(auth_error)[:100]}")
                    diagnostics["status"] = "degraded"
        except Exception as e:
            diagnostics["auth_ok"] = False
            diagnostics["errors"].append(f"Auth check error: {str(e)[:100]}")
            diagnostics["status"] = "degraded"

    # Determine overall status
    if not diagnostics["api_ok"]:
        diagnostics["status"] = "unhealthy"
    elif diagnostics.get("errors"):
        diagnostics["status"] = "degraded"

    return JSONResponse(diagnostics)


async def list_tools_endpoint(request: Request) -> JSONResponse:
    """List all available tools."""
    settings = get_settings()
    tools = get_public_tools()

    if settings.enable_private:
        tools.extend(get_private_tools())

    # Convert tools to serializable format
    tools_list = []
    for tool in tools:
        tools_list.append(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
        )

    return JSONResponse({"tools": tools_list})


async def call_tool_endpoint(request: Request) -> JSONResponse:
    """Call a specific tool via HTTP POST."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": True, "code": 400, "message": "Invalid JSON"},
            status_code=400,
        )

    tool_name = body.get("name")
    arguments = body.get("arguments", {})

    if not tool_name:
        return JSONResponse(
            {"error": True, "code": 400, "message": "Missing tool name"},
            status_code=400,
        )

    logger.info(f"HTTP tool call: {tool_name}")
    logger.debug(f"Arguments: {sanitize_log_message(str(arguments))}")

    try:
        result = await _dispatch_tool(tool_name, arguments)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Tool {tool_name} error: {e}")
        return JSONResponse(
            {"error": True, "code": 500, "message": str(e)[:200]},
            status_code=500,
        )


async def sse_endpoint(request: Request) -> EventSourceResponse:
    """
    SSE endpoint for MCP protocol.

    Creates a new session and returns an SSE stream.
    Clients should POST to /mcp/message with the session_id to send messages.
    
    MCP SSE Format:
    - Event type: "message" (standard MCP format)
    - Data: JSON-RPC 2.0 formatted string
    """
    session_id = str(uuid.uuid4())
    session = SSESession(session_id)
    _sessions[session_id] = session

    client_ip = request.client.host if request.client else 'unknown'
    logger.info(f"SSE session created: {session_id} (client: {client_ip})")

    # Start heartbeat task (delayed to let connection stabilize)
    session._heartbeat_task = asyncio.create_task(_send_heartbeat(session))

    async def event_generator():
        connection_alive = True
        try:
            # MCP SSE protocol: 
            # 1. Server opens SSE stream
            # 2. Client sends initialize request via POST to /mcp/message
            # 3. Server responds via SSE stream with initialize response
            # 
            # For compatibility, we send an immediate connection notification
            # This helps clients detect the connection is ready and know the session_id
            
            # MCP SSE Protocol:
            # 1. Client connects to SSE endpoint
            # 2. Server sends session_id in header (X-Session-Id) - already done
            # 3. Optionally send a connection notification so client knows connection is ready
            # 4. Client sends initialize request via POST to /mcp/message
            # 5. Server responds via SSE stream
            
            # Send a simple connection notification with session_id
            # This helps clients that need to know the session_id before sending requests
            # Format: SSE comment (doesn't interfere with MCP protocol)
            try:
                # Send session_id as comment so client can extract it if needed
                # This is non-blocking and doesn't interfere with MCP protocol
                yield {
                    "event": "comment",
                    "data": f"session_id:{session_id}",
                }
                logger.info(f"SSE session {session_id} ready (client: {client_ip})")
            except Exception as e:
                logger.warning(f"Error sending session comment: {e}")
                # Continue anyway - session_id is in header
            
            # Now wait for client to send initialize request
            logger.debug(f"Waiting for initialize request for session {session_id}")

            # Main message loop - keep connection alive
            while connection_alive and not session._closed:
                try:
                    # Wait for message with reasonable timeout
                    # Longer timeout reduces CPU usage while still checking connection
                    try:
                        message = await asyncio.wait_for(
                            session.queue.get(), timeout=15.0
                        )
                    except asyncio.TimeoutError:
                        # Timeout occurred - check if we should continue
                        # Don't check disconnect status too frequently to avoid overhead
                        if session.is_timed_out():
                            logger.info(f"SSE session {session_id} timed out after {session.CONNECTION_TIMEOUT}s")
                            connection_alive = False
                            break
                        # Continue waiting - heartbeat will keep connection alive
                        continue
                    
                    if message is None:
                        # Close signal received
                        logger.debug(f"SSE session {session_id} received close signal")
                        connection_alive = False
                        break
                    
                    # Yield the message to client
                    # Message should already be in correct format: {"event": "message", "data": "..."}
                    if isinstance(message, dict) and "event" in message and "data" in message:
                        yield message
                    else:
                        # Fallback: wrap in MCP format
                        logger.warning(f"Unexpected message format for session {session_id}: {type(message)}")
                        mcp_message = {
                            "jsonrpc": "2.0",
                            "method": "notification",
                            "params": message if isinstance(message, dict) else {"data": str(message)},
                        }
                        yield {
                            "event": "message",
                            "data": _compact_json(mcp_message),
                        }
                    
                except GeneratorExit:
                    # Client closed the connection gracefully
                    logger.info(f"SSE connection closed by client {client_ip} for session {session_id}")
                    connection_alive = False
                    break
                    
                except asyncio.CancelledError:
                    # Task was cancelled
                    logger.debug(f"SSE session {session_id} generator cancelled")
                    connection_alive = False
                    break
                    
                except Exception as e:
                    logger.error(f"Error in event generator for {session_id}: {e}", exc_info=True)
                    connection_alive = False
                    break
                    
        except Exception as e:
            logger.error(f"Fatal error in event generator for {session_id}: {e}", exc_info=True)
        finally:
            # Cleanup session
            connection_alive = False
            try:
                await session.close()
            except Exception as e:
                logger.debug(f"Error closing session {session_id}: {e}")
            
            if session_id in _sessions:
                del _sessions[session_id]
            
            logger.info(f"SSE session closed: {session_id} (client: {client_ip})")

    # Create SSE response with proper headers
    response = EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering for nginx/proxy
            "X-Session-Id": session_id,  # Critical: client needs this to send messages
            "Content-Type": "text/event-stream; charset=utf-8",
            "Access-Control-Allow-Origin": "*",  # CORS for web clients
            "Access-Control-Allow-Headers": "Cache-Control, X-Session-Id",
            "Access-Control-Expose-Headers": "X-Session-Id",  # Allow client to read session_id
        },
    )
    
    logger.debug(f"SSE response created for session {session_id} with headers")
    return response


async def mcp_message_endpoint(request: Request) -> JSONResponse:
    """
    Handle MCP messages via HTTP POST.

    Expects JSON body with:
    - session_id: SSE session ID (from X-Session-Id header or body)
    - method: MCP method name
    - params: Method parameters
    - id: Request ID (optional, defaults to 1)
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": True, "code": 400, "message": "Invalid JSON"},
            status_code=400,
        )

    # Try to get session_id from header first, then body
    session_id = request.headers.get("X-Session-Id") or body.get("session_id")
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")
    
    # Generate request_id if not provided
    if request_id is None:
        request_id = 1

    if not session_id:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "Missing session_id"},
            },
            status_code=400,
        )
    
    if session_id not in _sessions:
        logger.warning(f"Invalid session_id: {session_id} (available sessions: {list(_sessions.keys())[:3]})")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"Invalid or expired session_id: {session_id}"},
            },
            status_code=400,
        )

    session = _sessions[session_id]
    
    # Mark activity to prevent timeout
    session.mark_activity()
    
    # Check if session is closed or timed out
    if session._closed or session.is_timed_out():
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": "Session expired or closed"},
            },
            status_code=400,
        )
    
    logger.info(f"MCP message received: {method} (id={request_id}) for session {session_id[:8]}...")

    # Handle MCP methods
    if method == "tools/list":
        settings = get_settings()
        tools = get_public_tools()
        if settings.enable_private:
            tools.extend(get_private_tools())

        tools_list = []
        for tool in tools:
            tools_list.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
            )

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools_list},
        }

        # Send via SSE
        await session.send("response", response)
        return JSONResponse(response)

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            error_response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "Missing tool name"},
            }
            await session.send("response", error_response)
            return JSONResponse(error_response)

        try:
            result = await _dispatch_tool(tool_name, arguments)
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": _compact_json(result)}],
                },
            }
            await session.send("response", response)
            return JSONResponse(response)
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(e)[:200]},
            }
            await session.send("response", error_response)
            return JSONResponse(error_response)

    elif method == "initialize":
        # Handle MCP initialization - this is critical for client connection
        logger.info(f"MCP initialize request for session {session_id} (request_id: {request_id})")
        
        # Get capabilities based on configuration
        settings = get_settings()
        capabilities = {
            "tools": {
                "listChanged": False,  # We don't support dynamic tool changes
            },
        }
        
        # Build initialize response according to MCP spec
        response = {
            "jsonrpc": "2.0",
            "id": request_id,  # Must match client's request ID
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": capabilities,
                "serverInfo": {
                    "name": "deribit-mcp-server",
                    "version": "1.0.0",
                },
            },
        }
        
        # Send response via SSE FIRST (this is what the client is waiting for)
        # The client is likely blocking on this response
        await session.send("response", response)
        logger.info(f"MCP initialize response sent via SSE for session {session_id}")
        
        # Small delay to ensure SSE message is sent before HTTP response
        await asyncio.sleep(0.05)
        
        # Also return HTTP response for compatibility
        return JSONResponse(response)

    else:
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }
        await session.send("response", error_response)
        return JSONResponse(error_response)


async def close_session_endpoint(request: Request) -> JSONResponse:
    """Close an SSE session."""
    try:
        body = await request.json()
        session_id = body.get("session_id")
    except json.JSONDecodeError:
        session_id = request.query_params.get("session_id")

    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        await session.close()
        return JSONResponse({"status": "closed", "session_id": session_id})

    return JSONResponse(
        {"error": True, "message": "Session not found"},
        status_code=404,
    )


async def diagnostics_endpoint(request: Request) -> JSONResponse:
    """Run full diagnostic tests."""
    try:
        results = await run_full_diagnostics()
        return JSONResponse(results)
    except Exception as e:
        logger.error(f"Diagnostics error: {e}", exc_info=True)
        return JSONResponse(
            {"error": True, "message": str(e)[:200]},
            status_code=500,
        )


async def test_connection_endpoint(request: Request) -> JSONResponse:
    """Quick connection test endpoint."""
    results = {
        "public_api": await test_public_api(),
        "authentication": await test_authentication(),
    }
    
    if results["authentication"]["success"]:
        results["private_api"] = await test_private_api()
    
    return JSONResponse(results)


# =============================================================================
# Application Setup
# =============================================================================


@asynccontextmanager
async def lifespan(app: Starlette):
    """Application lifespan handler."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    settings = get_settings()
    logger.info("Starting Deribit MCP HTTP Server")
    logger.info(f"Configuration: {settings.get_safe_config_summary()}")

    # Start cleanup task
    cleanup_task = asyncio.create_task(_cleanup_stale_sessions())

    try:
        yield
    finally:
        # Signal shutdown
        _shutdown_event.set()
        
        # Cancel cleanup task
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        # Close all active SSE sessions
        logger.info(f"Closing {len(_sessions)} active SSE sessions...")
        close_tasks = [session.close() for session in _sessions.values()]
        if close_tasks:
            try:
                # Wait up to 5 seconds for sessions to close gracefully
                await asyncio.wait_for(
                    asyncio.gather(*close_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("Some SSE sessions did not close within timeout")
        _sessions.clear()

        # Cleanup client
        await shutdown_client()
        logger.info("Server shutdown complete")


# Define routes
routes = [
    Route("/health", health_check, methods=["GET"]),
    Route("/diagnostics", diagnostics_endpoint, methods=["GET"]),
    Route("/test", test_connection_endpoint, methods=["GET"]),
    Route("/tools", list_tools_endpoint, methods=["GET"]),
    Route("/tools/call", call_tool_endpoint, methods=["POST"]),
    Route("/sse", sse_endpoint, methods=["GET"]),
    Route("/mcp/message", mcp_message_endpoint, methods=["POST"]),
    Route("/mcp/session/close", close_session_endpoint, methods=["POST"]),
]

# CORS middleware for web clients
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    ),
]

# Create Starlette application
app = Starlette(
    debug=False,
    routes=routes,
    middleware=middleware,
    lifespan=lifespan,
)


def main():
    """Main entry point for HTTP server."""
    settings = get_settings()

    logger.info(f"Starting HTTP server on {settings.host}:{settings.port}")

    uvicorn.run(
        "deribit_mcp.http_server:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
