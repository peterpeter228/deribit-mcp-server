"""
Tests for analytics module.

Covers:
- IV conversion
- Expected move calculation
- Risk reversal/butterfly
- Spread calculations
"""

import math
import pytest

from deribit_mcp.analytics import (
    calculate_butterfly,
    calculate_expected_move,
    calculate_imbalance,
    calculate_risk_reversal,
    days_to_expiry_from_ts,
    dvol_to_decimal,
    iv_annualized_to_horizon,
    spread_in_bps,
    MINUTES_PER_YEAR,
)


class TestIVConversion:
    """Tests for IV conversion functions."""

    def test_iv_annualized_to_horizon_1hour(self):
        """Test IV conversion for 1 hour horizon."""
        iv_annual = 0.80  # 80% annual IV
        horizon_minutes = 60  # 1 hour

        result = iv_annualized_to_horizon(iv_annual, horizon_minutes)

        # Expected: 0.80 * sqrt(60 / 525600) ≈ 0.00855
        expected = 0.80 * math.sqrt(60 / MINUTES_PER_YEAR)
        assert abs(result - expected) < 1e-10

    def test_iv_annualized_to_horizon_1day(self):
        """Test IV conversion for 1 day horizon."""
        iv_annual = 0.80
        horizon_minutes = 1440  # 24 hours

        result = iv_annualized_to_horizon(iv_annual, horizon_minutes)

        expected = 0.80 * math.sqrt(1440 / MINUTES_PER_YEAR)
        assert abs(result - expected) < 1e-10

    def test_iv_annualized_zero_horizon(self):
        """Test IV conversion with zero horizon returns 0."""
        result = iv_annualized_to_horizon(0.80, 0)
        assert result == 0.0

    def test_dvol_to_decimal(self):
        """Test DVOL percentage to decimal conversion."""
        assert dvol_to_decimal(80) == 0.80
        assert dvol_to_decimal(100) == 1.0
        assert dvol_to_decimal(50.5) == 0.505


class TestExpectedMove:
    """Tests for expected move calculation."""

    def test_expected_move_basic(self):
        """Test basic expected move calculation."""
        spot = 100000  # $100,000 BTC
        iv_annual = 0.80  # 80% IV
        horizon_minutes = 60  # 1 hour

        result = calculate_expected_move(spot, iv_annual, horizon_minutes)

        # Expected 1σ move ≈ $854.60
        assert result.spot == spot
        assert result.iv_used == iv_annual
        assert result.horizon_minutes == horizon_minutes
        assert result.confidence == 1.0

        # Verify math: 100000 * 0.80 * sqrt(60/525600) ≈ 854.6
        expected_move = spot * iv_annual * math.sqrt(horizon_minutes / MINUTES_PER_YEAR)
        assert abs(result.move_points - expected_move) < 0.1

    def test_expected_move_bps(self):
        """Test expected move in basis points."""
        spot = 100000
        iv_annual = 0.80
        horizon_minutes = 60

        result = calculate_expected_move(spot, iv_annual, horizon_minutes)

        # BPS = (move_points / spot) * 10000
        expected_bps = (result.move_points / spot) * 10000
        assert abs(result.move_bps - expected_bps) < 0.01

    def test_expected_move_bands(self):
        """Test expected move bands (up/down 1σ)."""
        spot = 100000
        iv_annual = 0.80
        horizon_minutes = 60

        result = calculate_expected_move(spot, iv_annual, horizon_minutes)

        assert result.up_1sigma == round(spot + result.move_points, 2)
        assert result.down_1sigma == round(spot - result.move_points, 2)

    def test_expected_move_zero_iv(self):
        """Test expected move with zero IV returns zero move."""
        result = calculate_expected_move(100000, 0, 60)

        assert result.move_points == 0.0
        assert result.confidence == 0.0

    def test_expected_move_zero_spot(self):
        """Test expected move with zero spot returns zero move."""
        result = calculate_expected_move(0, 0.80, 60)

        assert result.move_points == 0.0
        assert result.confidence == 0.0

    def test_expected_move_different_horizons(self):
        """Test expected move scales with sqrt(time)."""
        spot = 100000
        iv_annual = 0.80

        result_1h = calculate_expected_move(spot, iv_annual, 60)
        result_4h = calculate_expected_move(spot, iv_annual, 240)

        # 4h move should be ~2x the 1h move (sqrt(4) = 2)
        ratio = result_4h.move_points / result_1h.move_points
        assert abs(ratio - 2.0) < 0.01


class TestRiskReversal:
    """Tests for risk reversal calculation."""

    def test_risk_reversal_bullish(self):
        """Test positive risk reversal (bullish skew)."""
        call_iv = 0.85
        put_iv = 0.80

        rr = calculate_risk_reversal(call_iv, put_iv)

        assert abs(rr - 0.05) < 1e-10  # Calls more expensive

    def test_risk_reversal_bearish(self):
        """Test negative risk reversal (bearish skew)."""
        call_iv = 0.75
        put_iv = 0.85

        rr = calculate_risk_reversal(call_iv, put_iv)

        assert abs(rr - (-0.10)) < 1e-10  # Puts more expensive

    def test_risk_reversal_none(self):
        """Test risk reversal with missing data."""
        assert calculate_risk_reversal(None, 0.80) is None
        assert calculate_risk_reversal(0.80, None) is None
        assert calculate_risk_reversal(None, None) is None


class TestButterfly:
    """Tests for butterfly calculation."""

    def test_butterfly_positive(self):
        """Test positive butterfly (fat tails)."""
        call_iv = 0.85
        put_iv = 0.85
        atm_iv = 0.80

        fly = calculate_butterfly(call_iv, put_iv, atm_iv)

        # (0.85 + 0.85) / 2 - 0.80 = 0.05
        assert abs(fly - 0.05) < 1e-10

    def test_butterfly_negative(self):
        """Test negative butterfly (thin tails)."""
        call_iv = 0.75
        put_iv = 0.75
        atm_iv = 0.80

        fly = calculate_butterfly(call_iv, put_iv, atm_iv)

        assert abs(fly - (-0.05)) < 1e-10

    def test_butterfly_none(self):
        """Test butterfly with missing data."""
        assert calculate_butterfly(None, 0.80, 0.80) is None
        assert calculate_butterfly(0.80, None, 0.80) is None
        assert calculate_butterfly(0.80, 0.80, None) is None


class TestSpreadCalculations:
    """Tests for spread calculations."""

    def test_spread_in_bps(self):
        """Test spread calculation in basis points."""
        bid = 99.0
        ask = 101.0

        result = spread_in_bps(bid, ask)

        # Spread = 2, mid = 100, bps = 2/100 * 10000 = 200
        assert abs(result - 200) < 0.01

    def test_spread_in_bps_tight(self):
        """Test tight spread calculation."""
        bid = 99.99
        ask = 100.01

        result = spread_in_bps(bid, ask)

        # Spread = 0.02, mid = 100, bps = 2
        assert abs(result - 2) < 0.01

    def test_spread_invalid(self):
        """Test spread with invalid inputs."""
        assert spread_in_bps(0, 100) is None
        assert spread_in_bps(100, 0) is None
        assert spread_in_bps(-1, 100) is None


class TestImbalance:
    """Tests for order book imbalance calculation."""

    def test_imbalance_balanced(self):
        """Test balanced book."""
        result = calculate_imbalance(100, 100)
        assert result == 0.0

    def test_imbalance_bid_heavy(self):
        """Test bid-heavy book."""
        result = calculate_imbalance(100, 0)
        assert result == 1.0

    def test_imbalance_ask_heavy(self):
        """Test ask-heavy book."""
        result = calculate_imbalance(0, 100)
        assert result == -1.0

    def test_imbalance_partial(self):
        """Test partial imbalance."""
        result = calculate_imbalance(75, 25)
        # (75 - 25) / 100 = 0.5
        assert result == 0.5

    def test_imbalance_zero(self):
        """Test zero depth."""
        result = calculate_imbalance(0, 0)
        assert result is None


class TestDaysToExpiry:
    """Tests for expiration timestamp conversion."""

    def test_days_to_expiry_basic(self):
        """Test basic days to expiry calculation."""
        current_ts_ms = 1700000000000  # Some timestamp
        expiry_ts_ms = current_ts_ms + (7 * 24 * 60 * 60 * 1000)  # 7 days later

        result = days_to_expiry_from_ts(expiry_ts_ms, current_ts_ms)

        assert abs(result - 7.0) < 0.001

    def test_days_to_expiry_expired(self):
        """Test expired option returns 0."""
        current_ts_ms = 1700000000000
        expiry_ts_ms = current_ts_ms - 1000  # Already expired

        result = days_to_expiry_from_ts(expiry_ts_ms, current_ts_ms)

        assert result == 0.0
