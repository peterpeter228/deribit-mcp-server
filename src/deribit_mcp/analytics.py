"""
Analytics module for volatility and expected move calculations.

Contains formulas for:
- IV to expected move conversion
- Risk reversal and butterfly calculations
- Volatility surface interpolation
"""

import math
from dataclasses import dataclass
from typing import Literal

# Constants
MINUTES_PER_YEAR = 525600  # 365.25 * 24 * 60
DAYS_PER_YEAR = 365.25
HOURS_PER_YEAR = 8766  # 365.25 * 24


@dataclass
class ExpectedMoveResult:
    """Result of expected move calculation."""

    spot: float
    iv_used: float  # Annualized IV (0-1 scale, e.g., 0.80 = 80%)
    iv_source: str
    horizon_minutes: int
    move_points: float  # 1σ move in price points
    move_bps: float  # 1σ move in basis points
    up_1sigma: float  # Spot + 1σ
    down_1sigma: float  # Spot - 1σ
    confidence: float  # 0-1


def iv_annualized_to_horizon(
    iv_annualized: float,
    horizon_minutes: int,
) -> float:
    """
    Convert annualized IV to IV for a specific time horizon.

    Formula: IV_horizon = IV_annual * sqrt(T_years)
    where T_years = horizon_minutes / MINUTES_PER_YEAR

    Args:
        iv_annualized: Annualized IV (e.g., 0.80 for 80%)
        horizon_minutes: Time horizon in minutes

    Returns:
        IV scaled to the horizon (same units as input)
    """
    if horizon_minutes <= 0:
        return 0.0

    t_years = horizon_minutes / MINUTES_PER_YEAR
    return iv_annualized * math.sqrt(t_years)


def calculate_expected_move(
    spot: float,
    iv_annualized: float,
    horizon_minutes: int,
    iv_source: str = "unknown",
    confidence: float = 1.0,
) -> ExpectedMoveResult:
    """
    Calculate expected move (1σ) based on IV and time horizon.

    The expected move represents the 1 standard deviation range,
    meaning ~68.3% of price moves should fall within this range
    (assuming log-normal distribution).

    Formula:
        expected_move = spot * IV_annual * sqrt(T_years)

    Where:
        - IV_annual is annualized implied volatility (decimal form)
        - T_years = horizon_minutes / 525600

    Args:
        spot: Current spot/index price
        iv_annualized: Annualized IV (e.g., 0.80 for 80%)
        horizon_minutes: Time horizon in minutes
        iv_source: Source of IV data ('dvol', 'atm_iv', etc.)
        confidence: Confidence in the calculation (0-1)

    Returns:
        ExpectedMoveResult with all computed values
    """
    if spot <= 0 or iv_annualized <= 0 or horizon_minutes <= 0:
        return ExpectedMoveResult(
            spot=spot,
            iv_used=iv_annualized,
            iv_source=iv_source,
            horizon_minutes=horizon_minutes,
            move_points=0.0,
            move_bps=0.0,
            up_1sigma=spot,
            down_1sigma=spot,
            confidence=0.0,
        )

    # Calculate time in years
    t_years = horizon_minutes / MINUTES_PER_YEAR

    # Expected move (1σ)
    move_points = spot * iv_annualized * math.sqrt(t_years)
    move_bps = (move_points / spot) * 10000

    return ExpectedMoveResult(
        spot=spot,
        iv_used=iv_annualized,
        iv_source=iv_source,
        horizon_minutes=horizon_minutes,
        move_points=round(move_points, 2),
        move_bps=round(move_bps, 2),
        up_1sigma=round(spot + move_points, 2),
        down_1sigma=round(spot - move_points, 2),
        confidence=confidence,
    )


def days_to_expiry_from_ts(expiration_ts_ms: int, current_ts_ms: int) -> float:
    """Calculate days to expiry from timestamps (milliseconds)."""
    diff_ms = expiration_ts_ms - current_ts_ms
    if diff_ms <= 0:
        return 0.0
    return diff_ms / (1000 * 60 * 60 * 24)


def find_nearest_tenor_instruments(
    instruments: list[dict],
    target_tenor_days: int,
    current_ts_ms: int,
    tolerance_days: float = 5.0,
) -> list[dict]:
    """
    Find instruments closest to the target tenor.

    Args:
        instruments: List of instrument dicts with 'expiration_timestamp'
        target_tenor_days: Target days to expiration
        current_ts_ms: Current timestamp in ms
        tolerance_days: Maximum deviation from target tenor

    Returns:
        List of instruments within tolerance, sorted by distance to target
    """
    result = []
    for inst in instruments:
        exp_ts = inst.get("expiration_timestamp", 0)
        if exp_ts <= current_ts_ms:
            continue

        days = days_to_expiry_from_ts(exp_ts, current_ts_ms)
        distance = abs(days - target_tenor_days)

        if distance <= tolerance_days:
            result.append({**inst, "_days_to_expiry": days, "_distance": distance})

    result.sort(key=lambda x: x["_distance"])
    return result


def calculate_risk_reversal(
    call_iv: float | None,
    put_iv: float | None,
) -> float | None:
    """
    Calculate 25-delta risk reversal.

    Risk Reversal = Call_IV(25d) - Put_IV(25d)

    Positive RR = calls more expensive (bullish skew)
    Negative RR = puts more expensive (bearish skew)
    """
    if call_iv is None or put_iv is None:
        return None
    return call_iv - put_iv


def calculate_butterfly(
    call_iv: float | None,
    put_iv: float | None,
    atm_iv: float | None,
) -> float | None:
    """
    Calculate 25-delta butterfly.

    Butterfly = (Call_IV(25d) + Put_IV(25d)) / 2 - ATM_IV

    Positive butterfly = wings more expensive (fat tails pricing)
    """
    if call_iv is None or put_iv is None or atm_iv is None:
        return None
    wing_avg = (call_iv + put_iv) / 2
    return wing_avg - atm_iv


@dataclass
class OptionChainAnalysis:
    """Analysis of an option chain for a single expiry."""

    expiry_ts: int
    days_to_expiry: float
    atm_strike: float | None
    atm_iv: float | None
    call_25d_strike: float | None
    call_25d_iv: float | None
    put_25d_strike: float | None
    put_25d_iv: float | None
    risk_reversal: float | None
    butterfly: float | None
    forward_price: float | None
    num_options: int


def find_atm_option(
    options: list[dict],
    underlying_price: float,
    option_type: Literal["call", "put"] = "call",
) -> dict | None:
    """
    Find the ATM option closest to underlying price.

    Args:
        options: List of option instruments with 'strike' and ticker data
        underlying_price: Current underlying/index price
        option_type: 'call' or 'put'

    Returns:
        The option dict closest to ATM, or None
    """
    filtered = [o for o in options if o.get("option_type") == option_type and o.get("strike")]

    if not filtered:
        return None

    return min(filtered, key=lambda x: abs(x.get("strike", 0) - underlying_price))


def find_delta_option(
    options: list[dict],
    target_delta: float,
    option_type: Literal["call", "put"],
) -> dict | None:
    """
    Find option closest to target delta.

    Args:
        options: List of options with 'greeks' containing 'delta'
        target_delta: Target absolute delta (e.g., 0.25)
        option_type: 'call' or 'put'

    Returns:
        The option closest to target delta, or None
    """
    filtered = [
        o
        for o in options
        if o.get("option_type") == option_type
        and o.get("greeks")
        and o["greeks"].get("delta") is not None
    ]

    if not filtered:
        return None

    # For puts, delta is negative, so we compare absolute values
    return min(filtered, key=lambda x: abs(abs(x["greeks"]["delta"]) - target_delta))


def interpolate_iv_to_tenor(
    iv_points: list[tuple[float, float]],  # (days, iv)
    target_days: float,
) -> float | None:
    """
    Linearly interpolate IV to target tenor.

    Args:
        iv_points: List of (days_to_expiry, iv) tuples, sorted by days
        target_days: Target days for interpolation

    Returns:
        Interpolated IV or None if not possible
    """
    if not iv_points:
        return None

    if len(iv_points) == 1:
        return iv_points[0][1]

    # Sort by days
    sorted_points = sorted(iv_points, key=lambda x: x[0])

    # Find bracketing points
    for i in range(len(sorted_points) - 1):
        d1, iv1 = sorted_points[i]
        d2, iv2 = sorted_points[i + 1]

        if d1 <= target_days <= d2:
            # Linear interpolation
            weight = (target_days - d1) / (d2 - d1) if d2 != d1 else 0.5
            return iv1 + weight * (iv2 - iv1)

    # Extrapolate if target is outside range
    if target_days < sorted_points[0][0]:
        return sorted_points[0][1]  # Use nearest
    if target_days > sorted_points[-1][0]:
        return sorted_points[-1][1]  # Use nearest

    return None


def dvol_to_decimal(dvol_value: float) -> float:
    """
    Convert DVOL index value to decimal form.

    DVOL is typically expressed as a percentage (e.g., 80 for 80% IV).
    This converts to decimal form (0.80) for calculations.
    """
    # DVOL is already in percentage form (e.g., 80.5)
    return dvol_value / 100.0


def calculate_forward_price(
    spot: float,
    rate: float,
    time_years: float,
) -> float:
    """
    Calculate forward price.

    F = S * e^(r*t)

    For crypto, rate is often approximated from futures basis or set to 0.
    """
    return spot * math.exp(rate * time_years)


def estimate_forward_from_futures(
    spot: float,
    futures_price: float,
    time_years: float,
) -> float | None:
    """
    Estimate implied risk-free rate from futures price.

    r = ln(F/S) / t
    """
    if spot <= 0 or futures_price <= 0 or time_years <= 0:
        return None
    return math.log(futures_price / spot) / time_years


def calculate_imbalance(bid_depth: float, ask_depth: float) -> float | None:
    """
    Calculate order book imbalance.

    Imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)

    Returns value between -1 (all asks) and 1 (all bids).
    """
    total = bid_depth + ask_depth
    if total == 0:
        return None
    return (bid_depth - ask_depth) / total


def spread_in_bps(bid: float, ask: float) -> float | None:
    """Calculate spread in basis points relative to mid price."""
    if bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    if mid == 0:
        return None
    spread = ask - bid
    return (spread / mid) * 10000
