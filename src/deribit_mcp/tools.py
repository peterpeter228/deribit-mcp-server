"""
MCP Tools implementation for Deribit API.

All tools return compact JSON (≤2KB target).
Each tool handles errors gracefully with degraded responses.
"""

import logging
import time
from typing import Any, Literal

from .analytics import (
    calculate_butterfly,
    calculate_expected_move,
    calculate_imbalance,
    calculate_risk_reversal,
    days_to_expiry_from_ts,
    dvol_to_decimal,
    spread_in_bps,
)
from .client import DeribitError, DeribitJsonRpcClient, get_client
from .config import Currency, InstrumentKind, get_settings
from .models import (
    AccountSummaryResponse,
    DvolResponse,
    ErrorResponse,
    ExpectedMoveResponse,
    FundingEntry,
    FundingResponse,
    GreeksCompact,
    InstrumentCompact,
    InstrumentsResponse,
    OpenOrdersResponse,
    OrderBookSummaryResponse,
    OrderCompact,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PositionCompact,
    PositionsResponse,
    PriceLevel,
    StatusResponse,
    SurfaceResponse,
    TenorIV,
    TickerResponse,
)

logger = logging.getLogger(__name__)


def _current_ts_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Safely convert value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_or_none(value: float | None, decimals: int = 6) -> float | None:
    """Round value if not None."""
    if value is None:
        return None
    return round(value, decimals)


# =============================================================================
# Tool 1: deribit_status
# =============================================================================


async def deribit_status(
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Check Deribit API connectivity and status.

    Returns:
        StatusResponse with environment, connectivity status, and server time.
    """
    client = client or get_client()
    settings = get_settings()
    notes: list[str] = []
    api_ok = False
    server_time_ms = 0

    try:
        # Get server time (validates connectivity)
        time_result = await client.call_public("public/get_time")
        server_time_ms = time_result
        api_ok = True

        # Try to get status info
        try:
            status_result = await client.call_public("public/status")
            if status_result.get("locked"):
                notes.append("platform_locked")
        except DeribitError:
            # Status endpoint might not be available, that's ok
            pass

        # Check cache stats
        cache_stats = client.get_cache_stats()
        if cache_stats["total_entries"] > 0:
            notes.append(f"cache_entries:{cache_stats['total_entries']}")

    except DeribitError as e:
        notes.append(f"error:{e.code}")
        notes.append(e.message[:50])
    except Exception as e:
        notes.append(f"connection_error:{type(e).__name__}")

    return StatusResponse(
        env=settings.env.value,
        api_ok=api_ok,
        server_time_ms=server_time_ms,
        notes=notes[:6],
    ).model_dump()


# =============================================================================
# Tool 2: deribit_instruments
# =============================================================================


async def deribit_instruments(
    currency: Currency,
    kind: InstrumentKind = "option",
    expired: bool = False,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get available instruments for a currency.

    Returns compact instrument list (max 50 items), prioritizing
    nearest expirations for options.

    Args:
        currency: BTC or ETH
        kind: option or future
        expired: Include expired instruments

    Returns:
        InstrumentsResponse with trimmed instrument list.
    """
    client = client or get_client()
    notes: list[str] = []

    try:
        result = await client.call_public(
            "public/get_instruments",
            {
                "currency": currency,
                "kind": kind,
                "expired": expired,
            },
        )

        instruments_raw = result if isinstance(result, list) else []
        total_count = len(instruments_raw)

        if total_count > 50:
            notes.append(f"truncated_from:{total_count}")

            # For options, prioritize nearest expirations
            if kind == "option":
                current_ts = _current_ts_ms()
                # Group by expiration
                by_expiry: dict[int, list] = {}
                for inst in instruments_raw:
                    exp = inst.get("expiration_timestamp", 0)
                    if exp not in by_expiry:
                        by_expiry[exp] = []
                    by_expiry[exp].append(inst)

                # Sort expirations and take nearest 3
                sorted_expiries = sorted([e for e in by_expiry if e > current_ts])[:3]

                # Collect instruments from these expirations
                filtered = []
                for exp in sorted_expiries:
                    filtered.extend(by_expiry[exp])

                instruments_raw = filtered[:50]
                notes.append(f"nearest_{len(sorted_expiries)}_expiries")
            else:
                instruments_raw = instruments_raw[:50]

        # Convert to compact format
        instruments = []
        for inst in instruments_raw:
            instruments.append(
                InstrumentCompact(
                    name=inst.get("instrument_name", ""),
                    exp_ts=inst.get("expiration_timestamp", 0),
                    strike=_safe_float(inst.get("strike")),
                    type=inst.get("option_type"),
                    tick=inst.get("tick_size", 0),
                    size=inst.get("contract_size", 0),
                )
            )

        return InstrumentsResponse(
            count=total_count,
            instruments=instruments,
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"currency:{currency}", f"kind:{kind}"],
        ).model_dump()


# =============================================================================
# Tool 3: deribit_ticker
# =============================================================================


async def deribit_ticker(
    instrument_name: str,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get compact ticker snapshot for an instrument.

    Args:
        instrument_name: Full instrument name (e.g., BTC-PERPETUAL, BTC-28JUN24-70000-C)

    Returns:
        TickerResponse with essential market data.
    """
    client = client or get_client()
    notes: list[str] = []

    try:
        result = await client.call_public("public/ticker", {"instrument_name": instrument_name})

        # Extract greeks if available
        greeks = None
        greeks_data = result.get("greeks")
        if greeks_data:
            greeks = GreeksCompact(
                delta=_round_or_none(_safe_float(greeks_data.get("delta")), 4),
                gamma=_round_or_none(_safe_float(greeks_data.get("gamma")), 6),
                vega=_round_or_none(_safe_float(greeks_data.get("vega")), 4),
                theta=_round_or_none(_safe_float(greeks_data.get("theta")), 4),
            )

        # Calculate mid price
        bid = _safe_float(result.get("best_bid_price"))
        ask = _safe_float(result.get("best_ask_price"))
        mid = None
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            mid = (bid + ask) / 2

        # Get IV (convert from percentage to decimal if needed)
        iv = _safe_float(result.get("mark_iv"))
        if iv is not None and iv > 1:
            iv = iv / 100  # Convert from percentage
            notes.append("iv_pct_converted")

        # Get funding rate for perpetuals
        funding = None
        next_funding_ts = None
        if "PERPETUAL" in instrument_name.upper():
            funding = _safe_float(result.get("current_funding"))
            next_funding_ts = result.get("funding_8h")

        return TickerResponse(
            inst=instrument_name,
            bid=_round_or_none(bid, 2),
            ask=_round_or_none(ask, 2),
            mid=_round_or_none(mid, 2),
            mark=_round_or_none(_safe_float(result.get("mark_price")), 4),
            idx=_round_or_none(_safe_float(result.get("index_price")), 2),
            und=_round_or_none(_safe_float(result.get("underlying_price")), 2),
            iv=_round_or_none(iv, 4),
            greeks=greeks,
            oi=_round_or_none(_safe_float(result.get("open_interest")), 2),
            vol_24h=_round_or_none(_safe_float(result.get("stats", {}).get("volume")), 2),
            funding=_round_or_none(funding, 8),
            next_funding_ts=next_funding_ts,
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"instrument:{instrument_name}"],
        ).model_dump()


# =============================================================================
# Tool 4: deribit_orderbook_summary
# =============================================================================


async def deribit_orderbook_summary(
    instrument_name: str,
    depth: int = 20,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get order book summary with top levels and depth metrics.

    Does NOT return full orderbook - only key metrics for LLM consumption.

    Args:
        instrument_name: Full instrument name
        depth: Depth to fetch (max 20, we return max 5 levels)

    Returns:
        OrderBookSummaryResponse with top levels and imbalance metrics.
    """
    client = client or get_client()
    notes: list[str] = []
    depth = min(depth, 20)  # Cap at 20

    try:
        result = await client.call_public(
            "public/get_order_book",
            {
                "instrument_name": instrument_name,
                "depth": depth,
            },
        )

        # Extract bids/asks
        raw_bids = result.get("bids", [])
        raw_asks = result.get("asks", [])

        # Top 5 levels only
        bids = [PriceLevel(p=round(b[0], 4), q=round(b[1], 4)) for b in raw_bids[:5]]
        asks = [PriceLevel(p=round(a[0], 4), q=round(a[1], 4)) for a in raw_asks[:5]]

        # Calculate depth sums
        bid_depth = sum(b[1] for b in raw_bids[:depth])
        ask_depth = sum(a[1] for a in raw_asks[:depth])

        # Best bid/ask
        best_bid = _safe_float(result.get("best_bid_price"))
        best_ask = _safe_float(result.get("best_ask_price"))

        # Spread calculations
        spread_pts = None
        spread_bps_val = None
        if best_bid and best_ask and best_bid > 0:
            spread_pts = best_ask - best_bid
            spread_bps_val = spread_in_bps(best_bid, best_ask)

        # Imbalance
        imbalance = calculate_imbalance(bid_depth, ask_depth)

        if len(raw_bids) > 5 or len(raw_asks) > 5:
            notes.append(f"levels_truncated_from:{max(len(raw_bids), len(raw_asks))}")

        return OrderBookSummaryResponse(
            inst=instrument_name,
            bid=_round_or_none(best_bid, 4),
            ask=_round_or_none(best_ask, 4),
            spread_pts=_round_or_none(spread_pts, 4),
            spread_bps=_round_or_none(spread_bps_val, 2),
            bids=bids,
            asks=asks,
            bid_depth=round(bid_depth, 4),
            ask_depth=round(ask_depth, 4),
            imbalance=_round_or_none(imbalance, 4),
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"instrument:{instrument_name}"],
        ).model_dump()


# =============================================================================
# Tool 5: dvol_snapshot
# =============================================================================


async def dvol_snapshot(
    currency: Currency,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get DVOL (Deribit Volatility Index) snapshot.

    DVOL represents the 30-day implied volatility derived from
    Deribit's options market.

    Args:
        currency: BTC or ETH

    Returns:
        DvolResponse with current DVOL and metrics.
    """
    client = client or get_client()
    notes: list[str] = []

    # DVOL index names
    dvol_index = f"{currency}_DVOL" if currency == "BTC" else f"{currency}DVOL"
    dvol_index_alt = f"{currency}DVOL" if currency == "BTC" else f"{currency}_DVOL"

    try:
        # Try to get DVOL index data
        result = None
        try:
            result = await client.call_public(
                "public/get_volatility_index_data",
                {
                    "currency": currency,
                    "resolution": "1D",  # Daily resolution
                    "start_timestamp": _current_ts_ms() - 86400000,  # Last 24h
                    "end_timestamp": _current_ts_ms(),
                },
            )
        except DeribitError:
            # Fallback: try ticker for DVOL instrument
            try:
                ticker = await client.call_public(
                    "public/ticker", {"instrument_name": f"{currency}_DVOL"}
                )
                if ticker:
                    dvol_value = _safe_float(ticker.get("mark_price"))
                    if dvol_value:
                        return DvolResponse(
                            ccy=currency,
                            dvol=round(dvol_value, 2),
                            dvol_chg_24h=None,
                            percentile=None,
                            ts=_current_ts_ms(),
                            notes=["source:ticker_fallback"],
                        ).model_dump()
            except DeribitError:
                pass

        if result and result.get("data"):
            data = result["data"]
            # Data is array of [timestamp, open, high, low, close]
            if len(data) > 0:
                latest = data[-1]
                dvol_now = latest[4] if len(latest) > 4 else latest[-1]

                # Calculate 24h change if we have enough data
                dvol_chg = None
                if len(data) >= 2:
                    prev_close = data[0][4] if len(data[0]) > 4 else data[0][-1]
                    if prev_close and prev_close > 0:
                        dvol_chg = dvol_now - prev_close

                return DvolResponse(
                    ccy=currency,
                    dvol=round(dvol_now, 2),
                    dvol_chg_24h=_round_or_none(dvol_chg, 2),
                    percentile=None,  # Would need historical data
                    ts=_current_ts_ms(),
                    notes=notes[:6],
                ).model_dump()

        # If we get here, no DVOL data available
        notes.append("dvol_unavailable")
        notes.append("try_options_surface_for_iv")

        return DvolResponse(
            ccy=currency,
            dvol=0,
            dvol_chg_24h=None,
            percentile=None,
            ts=_current_ts_ms(),
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"currency:{currency}", "dvol_fetch_failed"],
        ).model_dump()


# =============================================================================
# Tool 6: options_surface_snapshot
# =============================================================================


async def options_surface_snapshot(
    currency: Currency,
    tenor_days: list[int] | None = None,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get volatility surface snapshot with ATM IV, risk reversal, and butterfly
    for key tenors.

    This is a derived metric that requires multiple API calls. Results are
    cached aggressively to minimize API load.

    Args:
        currency: BTC or ETH
        tenor_days: Target tenors in days (default: [7, 14, 30, 60])

    Returns:
        SurfaceResponse with IV by tenor and skew metrics.
    """
    client = client or get_client()
    notes: list[str] = []
    tenor_days = tenor_days or [7, 14, 30, 60]

    try:
        # Get index price first
        index_result = await client.call_public(
            "public/get_index_price", {"index_name": f"{currency.lower()}_usd"}
        )
        spot = _safe_float(index_result.get("index_price", 0))

        if not spot or spot <= 0:
            notes.append("spot_price_unavailable")
            return SurfaceResponse(
                ccy=currency,
                spot=0,
                tenors=[],
                confidence=0,
                ts=_current_ts_ms(),
                notes=notes[:6],
            ).model_dump()

        # Get options instruments
        instruments_result = await client.call_public(
            "public/get_instruments", {"currency": currency, "kind": "option", "expired": False}
        )

        all_options = instruments_result if isinstance(instruments_result, list) else []
        current_ts = _current_ts_ms()

        # Group by expiration
        by_expiry: dict[int, list] = {}
        for opt in all_options:
            exp = opt.get("expiration_timestamp", 0)
            if exp <= current_ts:
                continue
            if exp not in by_expiry:
                by_expiry[exp] = []
            by_expiry[exp].append(opt)

        # Find expirations closest to target tenors
        tenors_result: list[TenorIV] = []
        matched_expiries = 0

        for target_days in tenor_days[:4]:  # Max 4 tenors
            # Find closest expiration
            best_exp = None
            best_distance = float("inf")

            for exp_ts in by_expiry:
                days = days_to_expiry_from_ts(exp_ts, current_ts)
                distance = abs(days - target_days)
                if distance < best_distance and distance < target_days * 0.5:
                    best_distance = distance
                    best_exp = exp_ts

            if best_exp is None:
                tenors_result.append(
                    TenorIV(
                        days=target_days,
                        atm_iv=None,
                        rr25=None,
                        fly25=None,
                        fwd=None,
                    )
                )
                continue

            matched_expiries += 1
            actual_days = days_to_expiry_from_ts(best_exp, current_ts)
            expiry_options = by_expiry[best_exp]

            # Find ATM option (closest strike to spot)
            atm_strike = None
            atm_iv = None
            min_distance = float("inf")

            for opt in expiry_options:
                strike = _safe_float(opt.get("strike"))
                if strike is None:
                    continue
                distance = abs(strike - spot)
                if distance < min_distance:
                    min_distance = distance
                    atm_strike = strike

            # Get ATM IV from ticker
            if atm_strike:
                atm_call_name = f"{currency}-{_format_expiry(best_exp)}-{int(atm_strike)}-C"
                try:
                    atm_ticker = await client.call_public(
                        "public/ticker", {"instrument_name": atm_call_name}
                    )
                    iv = _safe_float(atm_ticker.get("mark_iv"))
                    if iv and iv > 1:
                        iv = iv / 100
                    atm_iv = iv
                except DeribitError:
                    notes.append(f"atm_ticker_failed:{target_days}d")

            # Estimate 25d options for RR/Fly (simplified)
            # In practice, would need to find actual 25d strikes
            rr25 = None
            fly25 = None

            # For simplicity, estimate 25d strikes as ATM ± 5-10%
            if atm_strike and atm_iv:
                call_25d_strike = int(atm_strike * 1.05)
                put_25d_strike = int(atm_strike * 0.95)

                try:
                    call_name = f"{currency}-{_format_expiry(best_exp)}-{call_25d_strike}-C"
                    put_name = f"{currency}-{_format_expiry(best_exp)}-{put_25d_strike}-P"

                    call_ticker = await client.call_public(
                        "public/ticker", {"instrument_name": call_name}
                    )
                    put_ticker = await client.call_public(
                        "public/ticker", {"instrument_name": put_name}
                    )

                    call_iv = _safe_float(call_ticker.get("mark_iv"))
                    put_iv = _safe_float(put_ticker.get("mark_iv"))

                    if call_iv and call_iv > 1:
                        call_iv = call_iv / 100
                    if put_iv and put_iv > 1:
                        put_iv = put_iv / 100

                    if call_iv and put_iv:
                        rr25 = calculate_risk_reversal(call_iv, put_iv)
                        fly25 = calculate_butterfly(call_iv, put_iv, atm_iv)
                except DeribitError:
                    pass

            tenors_result.append(
                TenorIV(
                    days=int(actual_days),
                    atm_iv=_round_or_none(atm_iv, 4),
                    rr25=_round_or_none(rr25, 4),
                    fly25=_round_or_none(fly25, 4),
                    fwd=_round_or_none(spot, 2),  # Simplified: use spot as forward
                )
            )

        # Calculate confidence based on data coverage
        confidence = matched_expiries / len(tenor_days) if tenor_days else 0
        if confidence < 0.5:
            notes.append("low_confidence_sparse_data")

        return SurfaceResponse(
            ccy=currency,
            spot=round(spot, 2),
            tenors=tenors_result,
            confidence=round(confidence, 2),
            ts=current_ts,
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"currency:{currency}", "surface_calc_failed"],
        ).model_dump()


def _format_expiry(ts_ms: int) -> str:
    """Format expiration timestamp to Deribit format (e.g., 28JUN24)."""
    import datetime

    dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.UTC)
    return dt.strftime("%d%b%y").upper()


# =============================================================================
# Tool 7: expected_move_iv
# =============================================================================


async def expected_move_iv(
    currency: Currency,
    horizon_minutes: int = 60,
    method: Literal["dvol", "atm_iv"] = "dvol",
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Calculate expected price move based on implied volatility.

    Uses the formula: expected_move = spot × IV × √(T_years)
    where T_years = horizon_minutes / 525600

    This gives the 1σ (one standard deviation) expected move,
    meaning ~68.3% of moves should fall within this range.

    Args:
        currency: BTC or ETH
        horizon_minutes: Time horizon in minutes (default: 60)
        method: IV source - 'dvol' or 'atm_iv'

    Returns:
        ExpectedMoveResponse with calculated bands.
    """
    client = client or get_client()
    notes: list[str] = []

    try:
        # Get spot price
        index_result = await client.call_public(
            "public/get_index_price", {"index_name": f"{currency.lower()}_usd"}
        )
        spot = _safe_float(index_result.get("index_price", 0))

        if not spot or spot <= 0:
            notes.append("spot_unavailable")
            return ExpectedMoveResponse(
                ccy=currency,
                spot=0,
                iv_used=0,
                iv_source=method,
                horizon_min=horizon_minutes,
                move_1s_pts=0,
                move_1s_bps=0,
                up_1s=0,
                down_1s=0,
                confidence=0,
                notes=notes[:6],
            ).model_dump()

        # Get IV based on method
        iv_used = None
        iv_source = method
        confidence = 1.0

        if method == "dvol":
            # Try DVOL first
            dvol_result = await dvol_snapshot(currency, client)
            if not dvol_result.get("error") and dvol_result.get("dvol", 0) > 0:
                # DVOL is in percentage form (e.g., 80 = 80%)
                iv_used = dvol_to_decimal(dvol_result["dvol"])
                notes.append(f"dvol_raw:{dvol_result['dvol']}")
            else:
                notes.append("dvol_unavailable_fallback_atm")
                method = "atm_iv"
                confidence = 0.7

        if method == "atm_iv" or iv_used is None:
            # Get ATM IV from nearest expiry
            iv_source = "atm_iv"

            # Get options
            instruments = await client.call_public(
                "public/get_instruments", {"currency": currency, "kind": "option", "expired": False}
            )

            if instruments:
                current_ts = _current_ts_ms()

                # Find nearest expiry
                nearest_exp = None
                min_days = float("inf")
                for opt in instruments:
                    exp = opt.get("expiration_timestamp", 0)
                    if exp <= current_ts:
                        continue
                    days = days_to_expiry_from_ts(exp, current_ts)
                    if 1 < days < min_days:
                        min_days = days
                        nearest_exp = exp

                if nearest_exp:
                    # Find ATM strike
                    atm_strike = None
                    min_dist = float("inf")
                    for opt in instruments:
                        if opt.get("expiration_timestamp") != nearest_exp:
                            continue
                        strike = _safe_float(opt.get("strike"))
                        if strike:
                            dist = abs(strike - spot)
                            if dist < min_dist:
                                min_dist = dist
                                atm_strike = strike

                    if atm_strike:
                        atm_name = f"{currency}-{_format_expiry(nearest_exp)}-{int(atm_strike)}-C"
                        try:
                            ticker = await client.call_public(
                                "public/ticker", {"instrument_name": atm_name}
                            )
                            iv = _safe_float(ticker.get("mark_iv"))
                            if iv:
                                if iv > 1:
                                    iv = iv / 100
                                iv_used = iv
                                notes.append(f"atm_from:{atm_name}")
                        except DeribitError as e:
                            notes.append(f"atm_ticker_error:{e.code}")

        # Calculate expected move
        if iv_used is None or iv_used <= 0:
            notes.append("iv_unavailable_cannot_calculate")
            return ExpectedMoveResponse(
                ccy=currency,
                spot=round(spot, 2),
                iv_used=0,
                iv_source=iv_source,
                horizon_min=horizon_minutes,
                move_1s_pts=0,
                move_1s_bps=0,
                up_1s=spot,
                down_1s=spot,
                confidence=0,
                notes=notes[:6],
            ).model_dump()

        result = calculate_expected_move(
            spot=spot,
            iv_annualized=iv_used,
            horizon_minutes=horizon_minutes,
            iv_source=iv_source,
            confidence=confidence,
        )

        return ExpectedMoveResponse(
            ccy=currency,
            spot=round(result.spot, 2),
            iv_used=round(result.iv_used, 4),
            iv_source=result.iv_source,
            horizon_min=result.horizon_minutes,
            move_1s_pts=result.move_points,
            move_1s_bps=result.move_bps,
            up_1s=result.up_1sigma,
            down_1s=result.down_1sigma,
            confidence=round(result.confidence, 2),
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"currency:{currency}", "expected_move_failed"],
        ).model_dump()


# =============================================================================
# Tool 8: funding_snapshot
# =============================================================================


async def funding_snapshot(
    currency: Currency,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get perpetual funding rate snapshot.

    Args:
        currency: BTC or ETH

    Returns:
        FundingResponse with current rate and recent history.
    """
    client = client or get_client()
    notes: list[str] = []
    perp_name = f"{currency}-PERPETUAL"

    try:
        # Get current funding rate from ticker
        ticker = await client.call_public("public/ticker", {"instrument_name": perp_name})

        current_funding = _safe_float(ticker.get("current_funding"))

        # Get funding rate history (last 5 periods)
        history: list[FundingEntry] = []
        try:
            current_ts = _current_ts_ms()
            history_result = await client.call_public(
                "public/get_funding_rate_history",
                {
                    "instrument_name": perp_name,
                    "start_timestamp": current_ts - (8 * 3600 * 1000 * 5),  # ~5 periods
                    "end_timestamp": current_ts,
                },
            )

            if history_result:
                for entry in history_result[-5:]:  # Last 5 entries
                    history.append(
                        FundingEntry(
                            ts=entry.get("timestamp", 0),
                            rate=round(entry.get("interest_8h", 0), 8),
                        )
                    )
        except DeribitError:
            notes.append("history_unavailable")

        # Calculate 8h annualized rate
        rate_8h = None
        if current_funding is not None:
            # Funding is paid every 8 hours (3x per day)
            rate_8h = current_funding * 3 * 365  # Annualized

        # Next funding timestamp
        next_ts = ticker.get("funding_8h")

        return FundingResponse(
            ccy=currency,
            perp=perp_name,
            rate=round(current_funding or 0, 8),
            rate_8h=_round_or_none(rate_8h, 4),
            next_ts=next_ts,
            history=history,
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"perp:{perp_name}", "funding_fetch_failed"],
        ).model_dump()


# =============================================================================
# Private Tools (only enabled when DERIBIT_ENABLE_PRIVATE=true)
# =============================================================================


async def account_summary(
    currency: Currency,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get account summary (requires authentication).

    Args:
        currency: BTC or ETH

    Returns:
        AccountSummaryResponse with equity and margin info.
    """
    settings = get_settings()
    if not settings.enable_private:
        return ErrorResponse(
            code=403,
            message="Private API disabled. Set DERIBIT_ENABLE_PRIVATE=true",
            notes=["private_api_disabled"],
        ).model_dump()

    client = client or get_client()

    try:
        result = await client.call_private(
            "private/get_account_summary", {"currency": currency, "extended": True}
        )

        return AccountSummaryResponse(
            ccy=currency,
            equity=round(_safe_float(result.get("equity"), 0), 8),
            avail=round(_safe_float(result.get("available_funds"), 0), 8),
            margin=round(_safe_float(result.get("margin_balance"), 0), 8),
            mm=_round_or_none(_safe_float(result.get("maintenance_margin")), 8),
            im=_round_or_none(_safe_float(result.get("initial_margin")), 8),
            delta_total=_round_or_none(_safe_float(result.get("delta_total")), 4),
            notes=[],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"currency:{currency}", "auth_required"],
        ).model_dump()


async def positions(
    currency: Currency,
    kind: InstrumentKind = "future",
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get open positions (requires authentication).

    Args:
        currency: BTC or ETH
        kind: future or option

    Returns:
        PositionsResponse with compact position list (max 20).
    """
    settings = get_settings()
    if not settings.enable_private:
        return ErrorResponse(
            code=403,
            message="Private API disabled. Set DERIBIT_ENABLE_PRIVATE=true",
            notes=["private_api_disabled"],
        ).model_dump()

    client = client or get_client()
    notes: list[str] = []

    try:
        result = await client.call_private(
            "private/get_positions", {"currency": currency, "kind": kind}
        )

        positions_list = result if isinstance(result, list) else []
        total = len(positions_list)

        if total > 20:
            notes.append(f"truncated_from:{total}")
            positions_list = positions_list[:20]

        compact_positions = []
        for pos in positions_list:
            size = _safe_float(pos.get("size"), 0)
            if size == 0:
                continue

            compact_positions.append(
                PositionCompact(
                    inst=pos.get("instrument_name", ""),
                    size=abs(size),
                    side="long" if size > 0 else "short",
                    entry=round(_safe_float(pos.get("average_price"), 0), 4),
                    mark=round(_safe_float(pos.get("mark_price"), 0), 4),
                    pnl=round(_safe_float(pos.get("floating_profit_loss"), 0), 4),
                    liq=_round_or_none(_safe_float(pos.get("estimated_liquidation_price")), 2),
                )
            )

        return PositionsResponse(
            ccy=currency,
            count=total,
            positions=compact_positions,
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"currency:{currency}", f"kind:{kind}"],
        ).model_dump()


async def open_orders(
    currency: Currency | None = None,
    instrument_name: str | None = None,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Get open orders (requires authentication).

    Args:
        currency: BTC or ETH (required if instrument_name not provided)
        instrument_name: Specific instrument (optional)

    Returns:
        OpenOrdersResponse with compact order list (max 20).
    """
    settings = get_settings()
    if not settings.enable_private:
        return ErrorResponse(
            code=403,
            message="Private API disabled. Set DERIBIT_ENABLE_PRIVATE=true",
            notes=["private_api_disabled"],
        ).model_dump()

    client = client or get_client()
    notes: list[str] = []

    try:
        if instrument_name:
            result = await client.call_private(
                "private/get_open_orders_by_instrument", {"instrument_name": instrument_name}
            )
        elif currency:
            result = await client.call_private(
                "private/get_open_orders_by_currency", {"currency": currency}
            )
        else:
            return ErrorResponse(
                code=400,
                message="Either currency or instrument_name required",
                notes=[],
            ).model_dump()

        orders_list = result if isinstance(result, list) else []
        total = len(orders_list)

        if total > 20:
            notes.append(f"truncated_from:{total}")
            orders_list = orders_list[:20]

        compact_orders = []
        for order in orders_list:
            compact_orders.append(
                OrderCompact(
                    id=order.get("order_id", ""),
                    inst=order.get("instrument_name", ""),
                    side=order.get("direction", "buy"),
                    type=order.get("order_type", "limit"),
                    price=_round_or_none(_safe_float(order.get("price")), 4),
                    amount=round(_safe_float(order.get("amount"), 0), 4),
                    filled=round(_safe_float(order.get("filled_amount"), 0), 4),
                    state=order.get("order_state", "unknown"),
                )
            )

        return OpenOrdersResponse(
            count=total,
            orders=compact_orders,
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=["auth_required"],
        ).model_dump()


async def place_order(
    request: PlaceOrderRequest,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Place an order (requires authentication).

    SAFETY: By default, this runs in DRY_RUN mode and only shows
    what would be sent. Set DERIBIT_DRY_RUN=false to enable live trading.

    Args:
        request: Order parameters

    Returns:
        PlaceOrderResponse with order ID or simulation result.
    """
    settings = get_settings()
    if not settings.enable_private:
        return ErrorResponse(
            code=403,
            message="Private API disabled. Set DERIBIT_ENABLE_PRIVATE=true",
            notes=["private_api_disabled"],
        ).model_dump()

    client = client or get_client()
    notes: list[str] = []

    # Build the request params
    params = {
        "instrument_name": request.instrument,
        "amount": request.amount,
        "type": request.type,
    }

    if request.type == "limit" and request.price:
        params["price"] = request.price

    if request.post_only:
        params["post_only"] = True

    if request.reduce_only:
        params["reduce_only"] = True

    # DRY RUN MODE
    if settings.dry_run:
        notes.append("DRY_RUN_MODE")
        notes.append("Set DERIBIT_DRY_RUN=false for live trading")

        return PlaceOrderResponse(
            dry_run=True,
            would_send={
                "method": f"private/{request.side}",
                "params": params,
            },
            order_id=None,
            status="simulated",
            notes=notes[:6],
        ).model_dump()

    # LIVE TRADING
    try:
        method = f"private/{request.side}"
        result = await client.call_private(method, params)

        order_data = result.get("order", {})

        return PlaceOrderResponse(
            dry_run=False,
            would_send=None,
            order_id=order_data.get("order_id"),
            status=order_data.get("order_state", "submitted"),
            notes=notes[:6],
        ).model_dump()

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"instrument:{request.instrument}", "order_failed"],
        ).model_dump()


async def cancel_order(
    order_id: str,
    client: DeribitJsonRpcClient | None = None,
) -> dict:
    """
    Cancel an order (requires authentication).

    SAFETY: Respects DRY_RUN mode.

    Args:
        order_id: Order ID to cancel

    Returns:
        Status of cancellation.
    """
    settings = get_settings()
    if not settings.enable_private:
        return ErrorResponse(
            code=403,
            message="Private API disabled. Set DERIBIT_ENABLE_PRIVATE=true",
            notes=["private_api_disabled"],
        ).model_dump()

    client = client or get_client()
    notes: list[str] = []

    if settings.dry_run:
        notes.append("DRY_RUN_MODE")
        return {
            "dry_run": True,
            "would_cancel": order_id,
            "status": "simulated",
            "notes": notes,
        }

    try:
        result = await client.call_private("private/cancel", {"order_id": order_id})

        return {
            "dry_run": False,
            "order_id": order_id,
            "status": result.get("order_state", "cancelled"),
            "notes": notes[:6],
        }

    except DeribitError as e:
        return ErrorResponse(
            code=e.code,
            message=e.message[:100],
            notes=[f"order_id:{order_id}", "cancel_failed"],
        ).model_dump()
