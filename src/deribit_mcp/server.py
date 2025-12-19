"""
MCP Server implementation for Deribit API.

Supports:
- stdio transport (default, for local MCP clients)
- SSE transport (for web-based clients)

Usage:
    # stdio mode (default)
    python -m deribit_mcp.server

    # Or use the entry point
    deribit-mcp
"""

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

from .client import get_client, shutdown_client
from .config import get_settings, sanitize_log_message
from .models import PlaceOrderRequest
from .tools import (
    account_summary,
    cancel_order,
    deribit_instruments,
    deribit_orderbook_summary,
    deribit_status,
    deribit_ticker,
    dvol_snapshot,
    expected_move_iv,
    funding_snapshot,
    open_orders,
    options_surface_snapshot,
    place_order,
    positions,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("deribit_mcp")


# Create MCP server instance
server = Server("deribit-mcp-server")


def _compact_json(data: dict) -> str:
    """Convert dict to compact JSON string."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


# =============================================================================
# Tool Definitions
# =============================================================================


def get_public_tools() -> list[Tool]:
    """Get list of public (read-only) tools."""
    return [
        Tool(
            name="deribit_status",
            description="Check Deribit API connectivity and status. Returns environment, API status, and server time.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="deribit_instruments",
            description="Get available instruments for BTC/ETH. Returns compact list (max 50) with nearest expirations for options.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["option", "future"],
                        "default": "option",
                        "description": "Instrument kind",
                    },
                    "expired": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include expired instruments",
                    },
                },
                "required": ["currency"],
            },
        ),
        Tool(
            name="deribit_ticker",
            description="Get compact ticker snapshot for an instrument. Includes price, IV, greeks (for options), funding (for perps).",
            inputSchema={
                "type": "object",
                "properties": {
                    "instrument_name": {
                        "type": "string",
                        "description": "Full instrument name (e.g., BTC-PERPETUAL, BTC-28JUN24-70000-C)",
                    },
                },
                "required": ["instrument_name"],
            },
        ),
        Tool(
            name="deribit_orderbook_summary",
            description="Get order book summary with top 5 levels and depth metrics. Does NOT return full orderbook.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instrument_name": {
                        "type": "string",
                        "description": "Full instrument name",
                    },
                    "depth": {
                        "type": "integer",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 20,
                        "description": "Depth to fetch (max 20)",
                    },
                },
                "required": ["instrument_name"],
            },
        ),
        Tool(
            name="dvol_snapshot",
            description="Get DVOL (Deribit Volatility Index) snapshot. DVOL represents 30-day implied volatility.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                },
                "required": ["currency"],
            },
        ),
        Tool(
            name="options_surface_snapshot",
            description="Get volatility surface snapshot with ATM IV, risk reversal (25d), and butterfly (25d) for key tenors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                    "tenor_days": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "default": [7, 14, 30, 60],
                        "description": "Target tenors in days",
                    },
                },
                "required": ["currency"],
            },
        ),
        Tool(
            name="expected_move_iv",
            description="Calculate expected price move (1σ) based on IV. Formula: move = spot × IV × √(T_years). Returns bands and move in points/bps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                    "horizon_minutes": {
                        "type": "integer",
                        "default": 60,
                        "minimum": 1,
                        "maximum": 10080,
                        "description": "Time horizon in minutes (default: 60)",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["dvol", "atm_iv"],
                        "default": "dvol",
                        "description": "IV source: dvol or atm_iv",
                    },
                },
                "required": ["currency"],
            },
        ),
        Tool(
            name="funding_snapshot",
            description="Get perpetual funding rate snapshot with current rate and recent history (last 5 periods).",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                },
                "required": ["currency"],
            },
        ),
    ]


def get_private_tools() -> list[Tool]:
    """Get list of private (authenticated) tools."""
    return [
        Tool(
            name="account_summary",
            description="[PRIVATE] Get account summary with equity, margin, and delta. Requires DERIBIT_ENABLE_PRIVATE=true.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                },
                "required": ["currency"],
            },
        ),
        Tool(
            name="positions",
            description="[PRIVATE] Get open positions (max 20). Requires DERIBIT_ENABLE_PRIVATE=true.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["future", "option"],
                        "default": "future",
                        "description": "Instrument kind",
                    },
                },
                "required": ["currency"],
            },
        ),
        Tool(
            name="open_orders",
            description="[PRIVATE] Get open orders (max 20). Requires DERIBIT_ENABLE_PRIVATE=true.",
            inputSchema={
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["BTC", "ETH"],
                        "description": "Currency: BTC or ETH (optional if instrument_name provided)",
                    },
                    "instrument_name": {
                        "type": "string",
                        "description": "Specific instrument (optional)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="place_order",
            description="[PRIVATE] Place an order. SAFETY: Runs in DRY_RUN mode by default. Set DERIBIT_DRY_RUN=false for live trading.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instrument": {
                        "type": "string",
                        "description": "Instrument name",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["buy", "sell"],
                        "description": "Order side",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["limit", "market"],
                        "default": "limit",
                        "description": "Order type",
                    },
                    "amount": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Order amount",
                    },
                    "price": {
                        "type": "number",
                        "description": "Limit price (required for limit orders)",
                    },
                    "post_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Post-only flag",
                    },
                    "reduce_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Reduce-only flag",
                    },
                },
                "required": ["instrument", "side", "amount"],
            },
        ),
        Tool(
            name="cancel_order",
            description="[PRIVATE] Cancel an order. Respects DRY_RUN mode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order ID to cancel",
                    },
                },
                "required": ["order_id"],
            },
        ),
    ]


# =============================================================================
# MCP Handlers
# =============================================================================


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    settings = get_settings()
    tools = get_public_tools()

    if settings.enable_private:
        tools.extend(get_private_tools())
        logger.info("Private tools enabled")

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a tool and return results."""
    logger.info(f"Tool called: {name}")
    logger.debug(f"Arguments: {sanitize_log_message(str(arguments))}")

    try:
        result = await _dispatch_tool(name, arguments)
        json_result = _compact_json(result)

        # Log result size for monitoring
        result_size = len(json_result)
        if result_size > 5000:
            logger.warning(f"Tool {name} returned {result_size} bytes (exceeds 5KB target)")
        elif result_size > 2000:
            logger.info(f"Tool {name} returned {result_size} bytes (exceeds 2KB soft target)")

        return [TextContent(type="text", text=json_result)]

    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        error_result = {
            "error": True,
            "code": -1,
            "message": str(e)[:200],
            "notes": ["internal_error"],
        }
        return [TextContent(type="text", text=_compact_json(error_result))]


async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch tool call to appropriate handler."""
    client = get_client()

    # Public tools
    if name == "deribit_status":
        return await deribit_status(client=client)

    elif name == "deribit_instruments":
        return await deribit_instruments(
            currency=arguments["currency"],
            kind=arguments.get("kind", "option"),
            expired=arguments.get("expired", False),
            client=client,
        )

    elif name == "deribit_ticker":
        return await deribit_ticker(
            instrument_name=arguments["instrument_name"],
            client=client,
        )

    elif name == "deribit_orderbook_summary":
        return await deribit_orderbook_summary(
            instrument_name=arguments["instrument_name"],
            depth=arguments.get("depth", 20),
            client=client,
        )

    elif name == "dvol_snapshot":
        return await dvol_snapshot(
            currency=arguments["currency"],
            client=client,
        )

    elif name == "options_surface_snapshot":
        return await options_surface_snapshot(
            currency=arguments["currency"],
            tenor_days=arguments.get("tenor_days"),
            client=client,
        )

    elif name == "expected_move_iv":
        return await expected_move_iv(
            currency=arguments["currency"],
            horizon_minutes=arguments.get("horizon_minutes", 60),
            method=arguments.get("method", "dvol"),
            client=client,
        )

    elif name == "funding_snapshot":
        return await funding_snapshot(
            currency=arguments["currency"],
            client=client,
        )

    # Private tools
    elif name == "account_summary":
        return await account_summary(
            currency=arguments["currency"],
            client=client,
        )

    elif name == "positions":
        return await positions(
            currency=arguments["currency"],
            kind=arguments.get("kind", "future"),
            client=client,
        )

    elif name == "open_orders":
        return await open_orders(
            currency=arguments.get("currency"),
            instrument_name=arguments.get("instrument_name"),
            client=client,
        )

    elif name == "place_order":
        request = PlaceOrderRequest(
            instrument=arguments["instrument"],
            side=arguments["side"],
            type=arguments.get("type", "limit"),
            amount=arguments["amount"],
            price=arguments.get("price"),
            post_only=arguments.get("post_only", False),
            reduce_only=arguments.get("reduce_only", False),
        )
        return await place_order(request=request, client=client)

    elif name == "cancel_order":
        return await cancel_order(
            order_id=arguments["order_id"],
            client=client,
        )

    else:
        return {
            "error": True,
            "code": 404,
            "message": f"Unknown tool: {name}",
            "notes": [],
        }


# =============================================================================
# Server Entry Point
# =============================================================================


async def run_stdio():
    """Run the MCP server using stdio transport."""
    settings = get_settings()
    logger.info("Starting Deribit MCP Server (stdio mode)")
    logger.info(f"Configuration: {settings.get_safe_config_summary()}")

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await shutdown_client()
        logger.info("Server shutdown complete")


def main():
    """Main entry point for stdio mode."""
    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
