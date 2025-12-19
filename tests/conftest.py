"""
Pytest configuration and fixtures.
"""

import os
import pytest

# Set test environment variables before importing modules
os.environ.setdefault("DERIBIT_ENV", "test")
os.environ.setdefault("DERIBIT_ENABLE_PRIVATE", "false")
os.environ.setdefault("DERIBIT_CLIENT_ID", "")
os.environ.setdefault("DERIBIT_CLIENT_SECRET", "")
os.environ.setdefault("DERIBIT_TIMEOUT_S", "5")
os.environ.setdefault("DERIBIT_MAX_RPS", "10")
os.environ.setdefault("DERIBIT_CACHE_TTL_FAST", "1")
os.environ.setdefault("DERIBIT_CACHE_TTL_SLOW", "30")


@pytest.fixture(autouse=True)
def reset_settings():
    """Reset settings cache before each test."""
    from deribit_mcp.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_api_response():
    """Factory for creating mock API responses."""

    def _create_response(result=None, error=None):
        if error:
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "error": error,
            }
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": result,
        }

    return _create_response


@pytest.fixture
def sample_ticker_response():
    """Sample ticker response data."""
    return {
        "best_bid_price": 50000.0,
        "best_ask_price": 50001.0,
        "mark_price": 50000.5,
        "index_price": 50000.0,
        "underlying_price": 50000.0,
        "mark_iv": 80.0,  # Percentage form
        "open_interest": 1000000,
        "stats": {"volume": 50000},
        "current_funding": 0.0001,
        "greeks": {
            "delta": 0.5,
            "gamma": 0.0001,
            "vega": 100,
            "theta": -50,
        },
    }


@pytest.fixture
def sample_orderbook_response():
    """Sample orderbook response data."""
    return {
        "best_bid_price": 50000.0,
        "best_ask_price": 50001.0,
        "bids": [
            [50000.0, 1.0],
            [49999.0, 2.0],
            [49998.0, 3.0],
            [49997.0, 4.0],
            [49996.0, 5.0],
            [49995.0, 6.0],  # Will be truncated
        ],
        "asks": [
            [50001.0, 1.0],
            [50002.0, 2.0],
            [50003.0, 3.0],
            [50004.0, 4.0],
            [50005.0, 5.0],
            [50006.0, 6.0],  # Will be truncated
        ],
    }


@pytest.fixture
def sample_instruments_response():
    """Sample instruments response data."""
    return [
        {
            "instrument_name": f"BTC-28JUN24-{50000 + i * 1000}-C",
            "expiration_timestamp": 1719561600000,
            "strike": 50000 + i * 1000,
            "option_type": "call",
            "tick_size": 0.0001,
            "contract_size": 1.0,
        }
        for i in range(100)  # Generate 100 instruments
    ]
