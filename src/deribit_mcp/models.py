"""
Pydantic models for Deribit MCP Server.

All output models are designed to be compact (≤2KB target).
Field names are kept short for token efficiency.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Type aliases
Currency = Literal["BTC", "ETH"]
InstrumentKind = Literal["option", "future"]
OptionType = Literal["call", "put"]


# =============================================================================
# Status Models
# =============================================================================


class StatusResponse(BaseModel):
    """Response from deribit_status tool."""

    env: str = Field(description="Environment: prod or test")
    api_ok: bool = Field(description="API connectivity status")
    server_time_ms: int = Field(description="Server timestamp in ms")
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Instrument Models
# =============================================================================


class InstrumentCompact(BaseModel):
    """Compact instrument representation (minimal fields)."""

    name: str = Field(description="Instrument name")
    exp_ts: int = Field(description="Expiration timestamp (ms)")
    strike: float | None = Field(default=None, description="Strike price (options)")
    type: OptionType | None = Field(default=None, description="Option type")
    tick: float = Field(description="Tick size")
    size: float = Field(description="Contract size")


class InstrumentsResponse(BaseModel):
    """Response from deribit_instruments tool."""

    count: int = Field(description="Total instruments matching")
    instruments: list[InstrumentCompact] = Field(max_length=50)
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Ticker Models
# =============================================================================


class GreeksCompact(BaseModel):
    """Compact greeks for options."""

    delta: float | None = None
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None


class TickerResponse(BaseModel):
    """Response from deribit_ticker tool - compact market snapshot."""

    inst: str = Field(description="Instrument name")
    bid: float | None = Field(default=None, description="Best bid")
    ask: float | None = Field(default=None, description="Best ask")
    mid: float | None = Field(default=None, description="Mid price")
    mark: float = Field(description="Mark price")
    idx: float | None = Field(default=None, description="Index price")
    und: float | None = Field(default=None, description="Underlying price")
    iv: float | None = Field(default=None, description="IV (annualized, 0-1)")
    greeks: GreeksCompact | None = Field(default=None, description="Option greeks")
    oi: float | None = Field(default=None, description="Open interest")
    vol_24h: float | None = Field(default=None, description="24h volume")
    funding: float | None = Field(default=None, description="Funding rate (perps)")
    next_funding_ts: int | None = Field(default=None, description="Next funding time")
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Order Book Models
# =============================================================================


class PriceLevel(BaseModel):
    """Single price level."""

    p: float = Field(description="Price")
    q: float = Field(description="Quantity")


class OrderBookSummaryResponse(BaseModel):
    """Response from deribit_orderbook_summary tool."""

    inst: str = Field(description="Instrument name")
    bid: float | None = Field(default=None, description="Best bid")
    ask: float | None = Field(default=None, description="Best ask")
    spread_pts: float | None = Field(default=None, description="Spread in points")
    spread_bps: float | None = Field(default=None, description="Spread in bps")
    bids: list[PriceLevel] = Field(default_factory=list, max_length=5)
    asks: list[PriceLevel] = Field(default_factory=list, max_length=5)
    bid_depth: float = Field(default=0, description="Sum of top N bid qty")
    ask_depth: float = Field(default=0, description="Sum of top N ask qty")
    imbalance: float | None = Field(default=None, description="Bid/ask imbalance -1 to 1")
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Volatility Models
# =============================================================================


class DvolResponse(BaseModel):
    """Response from dvol_snapshot tool."""

    ccy: Currency = Field(description="Currency")
    dvol: float = Field(description="Current DVOL value")
    dvol_chg_24h: float | None = Field(default=None, description="24h change")
    percentile: float | None = Field(default=None, description="Historical percentile 0-100")
    ts: int = Field(description="Timestamp ms")
    notes: list[str] = Field(default_factory=list, max_length=6)


class TenorIV(BaseModel):
    """IV data for a specific tenor."""

    days: int = Field(description="Days to expiration")
    atm_iv: float | None = Field(default=None, description="ATM IV")
    rr25: float | None = Field(default=None, description="25d risk reversal")
    fly25: float | None = Field(default=None, description="25d butterfly")
    fwd: float | None = Field(default=None, description="Forward price")


class SurfaceResponse(BaseModel):
    """Response from options_surface_snapshot tool."""

    ccy: Currency = Field(description="Currency")
    spot: float = Field(description="Current spot/index price")
    tenors: list[TenorIV] = Field(max_length=6, description="IV by tenor")
    confidence: float = Field(ge=0, le=1, description="Data quality 0-1")
    ts: int = Field(description="Timestamp ms")
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Expected Move Models
# =============================================================================


class ExpectedMoveResponse(BaseModel):
    """Response from expected_move_iv tool."""

    ccy: Currency = Field(description="Currency")
    spot: float = Field(description="Current spot price")
    iv_used: float = Field(description="IV used (annualized 0-1)")
    iv_source: str = Field(description="Source: dvol or atm_iv")
    horizon_min: int = Field(description="Horizon in minutes")
    move_1s_pts: float = Field(description="1σ expected move in points")
    move_1s_bps: float = Field(description="1σ expected move in bps")
    up_1s: float = Field(description="Upper 1σ band")
    down_1s: float = Field(description="Lower 1σ band")
    confidence: float = Field(ge=0, le=1, description="Data quality 0-1")
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Funding Models
# =============================================================================


class FundingEntry(BaseModel):
    """Single funding rate entry."""

    ts: int = Field(description="Timestamp ms")
    rate: float = Field(description="Funding rate")


class FundingResponse(BaseModel):
    """Response from funding_snapshot tool."""

    ccy: Currency = Field(description="Currency")
    perp: str = Field(description="Perpetual instrument name")
    rate: float = Field(description="Current funding rate")
    rate_8h: float | None = Field(default=None, description="8h annualized rate")
    next_ts: int | None = Field(default=None, description="Next funding timestamp")
    history: list[FundingEntry] = Field(default_factory=list, max_length=5)
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Private API Models
# =============================================================================


class AccountSummaryResponse(BaseModel):
    """Response from account_summary tool (private)."""

    ccy: Currency
    equity: float = Field(description="Total equity")
    avail: float = Field(description="Available funds")
    margin: float = Field(description="Margin balance")
    mm: float | None = Field(default=None, description="Maintenance margin")
    im: float | None = Field(default=None, description="Initial margin")
    delta_total: float | None = Field(default=None, description="Total delta")
    notes: list[str] = Field(default_factory=list, max_length=6)


class PositionCompact(BaseModel):
    """Compact position representation."""

    inst: str = Field(description="Instrument name")
    size: float = Field(description="Position size")
    side: Literal["long", "short"] = Field(description="Position side")
    entry: float = Field(description="Average entry price")
    mark: float = Field(description="Current mark price")
    pnl: float = Field(description="Unrealized PnL")
    liq: float | None = Field(default=None, description="Liquidation price")


class PositionsResponse(BaseModel):
    """Response from positions tool (private)."""

    ccy: Currency
    count: int = Field(description="Total positions")
    positions: list[PositionCompact] = Field(max_length=20)
    notes: list[str] = Field(default_factory=list, max_length=6)


class OrderCompact(BaseModel):
    """Compact order representation."""

    id: str = Field(description="Order ID")
    inst: str = Field(description="Instrument name")
    side: Literal["buy", "sell"]
    type: Literal["limit", "market", "stop_limit", "stop_market"]
    price: float | None = Field(default=None, description="Limit price")
    amount: float = Field(description="Order amount")
    filled: float = Field(default=0, description="Filled amount")
    state: str = Field(description="Order state")


class OpenOrdersResponse(BaseModel):
    """Response from open_orders tool (private)."""

    count: int = Field(description="Total open orders")
    orders: list[OrderCompact] = Field(max_length=20)
    notes: list[str] = Field(default_factory=list, max_length=6)


class PlaceOrderRequest(BaseModel):
    """Request for place_order tool (private)."""

    instrument: str = Field(description="Instrument name")
    side: Literal["buy", "sell"]
    type: Literal["limit", "market"] = Field(default="limit")
    amount: float = Field(gt=0, description="Order amount")
    price: float | None = Field(default=None, description="Limit price")
    post_only: bool = Field(default=False, description="Post-only flag")
    reduce_only: bool = Field(default=False, description="Reduce-only flag")


class PlaceOrderResponse(BaseModel):
    """Response from place_order tool (private)."""

    dry_run: bool = Field(description="Whether this was a dry run")
    would_send: dict | None = Field(default=None, description="Request that would be sent")
    order_id: str | None = Field(default=None, description="Created order ID")
    status: str = Field(description="Order status or simulation result")
    notes: list[str] = Field(default_factory=list, max_length=6)


# =============================================================================
# Error Models
# =============================================================================


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: bool = True
    code: int = Field(description="Error code")
    message: str = Field(description="Error message")
    notes: list[str] = Field(default_factory=list, max_length=6)
