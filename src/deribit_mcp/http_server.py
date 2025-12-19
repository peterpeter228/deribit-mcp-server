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

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.created_at = asyncio.get_event_loop().time()

    async def send(self, event: str, data: dict):
        """Send an event to the client."""
        await self.queue.put(
            {
                "event": event,
                "data": _compact_json(data),
            }
        )

    async def close(self):
        """Close the session."""
        await self.queue.put(None)


# Global session storage
_sessions: dict[str, SSESession] = {}


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
    """
    session_id = str(uuid.uuid4())
    session = SSESession(session_id)
    _sessions[session_id] = session

    logger.info(f"SSE session created: {session_id}")

    async def event_generator():
        # Send session initialization
        yield {
            "event": "session",
            "data": _compact_json(
                {
                    "session_id": session_id,
                    "protocol": "mcp",
                    "version": "1.0",
                }
            ),
        }

        try:
            while True:
                message = await session.queue.get()
                if message is None:
                    break
                yield message
        finally:
            # Cleanup session
            if session_id in _sessions:
                del _sessions[session_id]
            logger.info(f"SSE session closed: {session_id}")

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Session-Id": session_id,
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
    settings = get_settings()
    logger.info("Starting Deribit MCP HTTP Server")
    logger.info(f"Configuration: {settings.get_safe_config_summary()}")

    yield

    # Cleanup
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
