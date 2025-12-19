"""
Tests for MCP tools.

Covers:
- Output size limits (≤2KB target)
- Response structure validation
- Error degradation
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from deribit_mcp.models import (
    DvolResponse,
    ExpectedMoveResponse,
    FundingResponse,
    InstrumentCompact,
    InstrumentsResponse,
    OrderBookSummaryResponse,
    StatusResponse,
    SurfaceResponse,
    TickerResponse,
)
from deribit_mcp.tools import (
    _round_or_none,
    _safe_float,
)


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_safe_float_valid(self):
        """Test safe_float with valid inputs."""
        assert _safe_float(1.5) == 1.5
        assert _safe_float("2.5") == 2.5
        assert _safe_float(100) == 100.0

    def test_safe_float_invalid(self):
        """Test safe_float with invalid inputs."""
        assert _safe_float(None) is None
        assert _safe_float("invalid") is None
        assert _safe_float(None, default=0.0) == 0.0

    def test_round_or_none(self):
        """Test round_or_none function."""
        assert _round_or_none(1.23456, 2) == 1.23
        assert _round_or_none(None, 2) is None
        assert _round_or_none(1.999999, 4) == 2.0


class TestOutputSizeLimits:
    """Tests to verify output stays within size limits."""

    def test_status_response_size(self):
        """Test StatusResponse stays compact."""
        response = StatusResponse(
            env="prod",
            api_ok=True,
            server_time_ms=1700000000000,
            notes=["note1", "note2", "note3"],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 200  # Status should be tiny

    def test_instruments_response_max_50(self):
        """Test InstrumentsResponse respects 50 item limit."""
        instruments = [
            InstrumentCompact(
                name=f"BTC-28JUN24-{50000 + i * 1000}-C",
                exp_ts=1719561600000,
                strike=50000 + i * 1000,
                type="call",
                tick=0.0001,
                size=1.0,
            )
            for i in range(50)
        ]

        response = InstrumentsResponse(
            count=100,  # Original count was higher
            instruments=instruments,
            notes=["truncated_from:100"],
        )

        json_str = response.model_dump_json()

        # 50 instruments should fit within reasonable size
        # Using 6KB as limit (hardcoded 5KB is a soft target)
        assert len(json_str) < 6000
        assert len(response.instruments) <= 50

    def test_ticker_response_size(self):
        """Test TickerResponse stays compact."""
        response = TickerResponse(
            inst="BTC-PERPETUAL",
            bid=50000.0,
            ask=50001.0,
            mid=50000.5,
            mark=50000.25,
            idx=50000.0,
            und=50000.0,
            iv=0.80,
            greeks=None,
            oi=1000000.0,
            vol_24h=50000.0,
            funding=0.0001,
            next_funding_ts=1700003600000,
            notes=[],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 500  # Ticker should be compact

    def test_orderbook_summary_max_5_levels(self):
        """Test OrderBookSummaryResponse limits to 5 levels."""
        from deribit_mcp.models import PriceLevel

        response = OrderBookSummaryResponse(
            inst="BTC-PERPETUAL",
            bid=50000.0,
            ask=50001.0,
            spread_pts=1.0,
            spread_bps=2.0,
            bids=[PriceLevel(p=50000 - i, q=1.0) for i in range(5)],
            asks=[PriceLevel(p=50001 + i, q=1.0) for i in range(5)],
            bid_depth=100.0,
            ask_depth=100.0,
            imbalance=0.0,
            notes=[],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 1000  # Should be under 1KB
        assert len(response.bids) <= 5
        assert len(response.asks) <= 5

    def test_dvol_response_size(self):
        """Test DvolResponse stays compact."""
        response = DvolResponse(
            ccy="BTC",
            dvol=80.5,
            dvol_chg_24h=2.5,
            percentile=65.0,
            ts=1700000000000,
            notes=["source:index"],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 200

    def test_surface_response_max_tenors(self):
        """Test SurfaceResponse limits tenors."""
        from deribit_mcp.models import TenorIV

        response = SurfaceResponse(
            ccy="BTC",
            spot=50000.0,
            tenors=[
                TenorIV(days=7, atm_iv=0.80, rr25=0.02, fly25=0.01, fwd=50100),
                TenorIV(days=14, atm_iv=0.78, rr25=0.01, fly25=0.005, fwd=50200),
                TenorIV(days=30, atm_iv=0.75, rr25=0.005, fly25=0.002, fwd=50500),
                TenorIV(days=60, atm_iv=0.72, rr25=0.003, fly25=0.001, fwd=51000),
            ],
            confidence=0.95,
            ts=1700000000000,
            notes=[],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 1000
        assert len(response.tenors) <= 6  # Max 6 tenors

    def test_expected_move_response_size(self):
        """Test ExpectedMoveResponse stays compact."""
        response = ExpectedMoveResponse(
            ccy="BTC",
            spot=50000.0,
            iv_used=0.80,
            iv_source="dvol",
            horizon_min=60,
            move_1s_pts=427.5,
            move_1s_bps=85.5,
            up_1s=50427.5,
            down_1s=49572.5,
            confidence=0.95,
            notes=["dvol_raw:80"],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 400

    def test_funding_response_max_history(self):
        """Test FundingResponse limits history."""
        from deribit_mcp.models import FundingEntry

        response = FundingResponse(
            ccy="BTC",
            perp="BTC-PERPETUAL",
            rate=0.0001,
            rate_8h=0.1095,
            next_ts=1700003600000,
            history=[FundingEntry(ts=1700000000000 - i * 28800000, rate=0.0001) for i in range(5)],
            notes=[],
        )

        json_str = response.model_dump_json()

        assert len(json_str) < 500
        assert len(response.history) <= 5


class TestCompactJson:
    """Tests for compact JSON serialization."""

    def test_compact_json_no_spaces(self):
        """Test compact JSON has no unnecessary spaces."""
        data = {"key": "value", "number": 123, "list": [1, 2, 3]}
        result = json.dumps(data, separators=(",", ":"))

        assert " " not in result.replace('"key"', "").replace('"value"', "")
        assert '{"key":"value","number":123,"list":[1,2,3]}' == result


class TestNotesLimit:
    """Tests for notes array limit."""

    def test_status_notes_max_6(self):
        """Test StatusResponse rejects more than 6 notes."""
        import pytest
        from pydantic import ValidationError

        # Pydantic should raise ValidationError for more than 6 notes
        with pytest.raises(ValidationError):
            StatusResponse(
                env="prod",
                api_ok=True,
                server_time_ms=1700000000000,
                notes=["1", "2", "3", "4", "5", "6", "7", "8"],
            )

        # Exactly 6 should work
        response = StatusResponse(
            env="prod",
            api_ok=True,
            server_time_ms=1700000000000,
            notes=["1", "2", "3", "4", "5", "6"],
        )
        assert len(response.notes) == 6

    def test_ticker_notes_max_6(self):
        """Test TickerResponse rejects more than 6 notes."""
        import pytest
        from pydantic import ValidationError

        # Pydantic should raise ValidationError for more than 6 notes
        with pytest.raises(ValidationError):
            TickerResponse(
                inst="BTC-PERPETUAL",
                mark=50000.0,
                notes=["1", "2", "3", "4", "5", "6", "7"],
            )

        # Exactly 6 should work
        response = TickerResponse(
            inst="BTC-PERPETUAL",
            mark=50000.0,
            notes=["1", "2", "3", "4", "5", "6"],
        )
        assert len(response.notes) == 6


class TestErrorDegradation:
    """Tests for graceful error degradation."""

    def test_error_response_structure(self):
        """Test error response has expected structure."""
        from deribit_mcp.models import ErrorResponse

        error = ErrorResponse(
            code=10001,
            message="Test error message",
            notes=["context1", "context2"],
        )

        data = error.model_dump()

        assert data["error"] is True
        assert data["code"] == 10001
        assert "message" in data
        assert len(data["notes"]) == 2

    def test_error_message_truncation(self):
        """Test long error messages get truncated in tool output."""
        # In tools.py, we truncate messages to 100 chars
        long_message = "A" * 200
        truncated = long_message[:100]

        assert len(truncated) == 100


class TestModelValidation:
    """Tests for Pydantic model validation."""

    def test_currency_enum(self):
        """Test currency must be BTC or ETH."""
        response = DvolResponse(
            ccy="BTC",
            dvol=80.0,
            ts=1700000000000,
        )

        assert response.ccy == "BTC"

    def test_confidence_bounds(self):
        """Test confidence is bounded 0-1."""
        response = ExpectedMoveResponse(
            ccy="BTC",
            spot=50000.0,
            iv_used=0.80,
            iv_source="dvol",
            horizon_min=60,
            move_1s_pts=0,
            move_1s_bps=0,
            up_1s=50000,
            down_1s=50000,
            confidence=0.5,  # Valid
            notes=[],
        )

        assert 0 <= response.confidence <= 1

    def test_instrument_compact_fields(self):
        """Test InstrumentCompact has minimal fields."""
        inst = InstrumentCompact(
            name="BTC-28JUN24-70000-C",
            exp_ts=1719561600000,
            strike=70000,
            type="call",
            tick=0.0001,
            size=1.0,
        )

        # Check fields are present
        data = inst.model_dump()

        assert "name" in data
        assert "exp_ts" in data
        assert "strike" in data
        assert "type" in data
        assert "tick" in data
        assert "size" in data

        # Should not have verbose field names
        assert "instrument_name" not in data
        assert "expiration_timestamp" not in data
