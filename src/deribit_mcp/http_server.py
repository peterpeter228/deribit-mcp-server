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
        await asyncio.sleep(20.0)
        
        while not session._closed:
            if session._closed or session.is_timed_out():
                break
            
            try:
                # Send heartbeat as MCP notification
                heartbeat_message = {
                    "jsonrpc": "2.0",
                    "method": "ping",
                    "params": {
                        "timestamp": asyncio.get_event_loop().time(),
                        "session_id": session.session_id
                    },
                }
                await session.send("notification", heartbeat_message)
                logger.debug(f"Heartbeat sent for session {session.session_id}")
            except Exception as e:
                logger.debug(f"Error sending heartbeat for {session.session_id}: {e}")
                break
            
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
    """Health check endpoint."""
    settings = get_settings()
    client = get_client()

    # Quick status check
    try:
        status = await deribit_status(client=client)
        api_ok = status.get("api_ok", False)
    except Exception:
        api_ok = False

    return JSONResponse(
        {
            "status": "healthy" if api_ok else "degraded",
            "env": settings.env.value,
            "api_ok": api_ok,
            "private_enabled": settings.enable_private,
        }
    )


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
            # Send session initialization message immediately
            # MCP format: event: message, data: JSON-RPC message
            init_message = {
                "jsonrpc": "2.0",
                "method": "session/init",
                "params": {
                    "session_id": session_id,
                    "protocol": "mcp",
                    "version": "1.0",
                },
            }
            yield {
                "event": "message",
                "data": _compact_json(init_message),
            }
            
            logger.debug(f"SSE session {session_id} initialization sent to {client_ip}")

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

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering for nginx/proxy
            "X-Session-Id": session_id,
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )


async def mcp_message_endpoint(request: Request) -> JSONResponse:
    """
    Handle MCP messages via HTTP POST.

    Expects JSON body with:
    - session_id: SSE session ID
    - method: MCP method name
    - params: Method parameters
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": True, "code": 400, "message": "Invalid JSON"},
            status_code=400,
        )

    session_id = body.get("session_id")
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id", 1)

    if not session_id or session_id not in _sessions:
        return JSONResponse(
            {"error": True, "code": 400, "message": "Invalid or missing session_id"},
            status_code=400,
        )

    session = _sessions[session_id]
    
    # Mark activity to prevent timeout
    session.mark_activity()
    
    # Check if session is closed or timed out
    if session._closed or session.is_timed_out():
        return JSONResponse(
            {"error": True, "code": 400, "message": "Session expired or closed"},
            status_code=400,
        )

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
        # Handle MCP initialization
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "deribit-mcp-server",
                    "version": "1.0.0",
                },
            },
        }
        await session.send("response", response)
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
