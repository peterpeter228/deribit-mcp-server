"""
Tests for Deribit JSON-RPC client.

Covers:
- Cache hit/miss behavior
- Rate limiting
- Error handling and degradation
- Authentication flow
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deribit_mcp.client import (
    CacheEntry,
    DeribitError,
    DeribitJsonRpcClient,
    DeribitRateLimitError,
    DeribitTimeoutError,
    TokenBucket,
)
from deribit_mcp.config import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    return Settings(
        env="test",
        enable_private=False,
        client_id="",
        client_secret="",
        timeout_s=5.0,
        max_rps=10.0,
        cache_ttl_fast=1.0,
        cache_ttl_slow=30.0,
    )


@pytest.fixture
def client(mock_settings):
    """Create a client with mock settings."""
    return DeribitJsonRpcClient(settings=mock_settings)


class TestTokenBucket:
    """Tests for token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_available(self):
        """Test acquiring tokens when available."""
        bucket = TokenBucket(rate=10.0, capacity=10.0)

        wait_time = await bucket.acquire(1.0)

        assert wait_time == 0.0
        assert bucket.tokens == 9.0

    @pytest.mark.asyncio
    async def test_acquire_wait(self):
        """Test waiting when tokens not available."""
        bucket = TokenBucket(rate=10.0, capacity=1.0)
        bucket.tokens = 0.0

        start = time.monotonic()
        wait_time = await bucket.acquire(1.0)
        elapsed = time.monotonic() - start

        # Should have waited ~0.1s (1 token at 10/s rate)
        assert wait_time > 0
        assert elapsed >= 0.09  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_token_refill(self):
        """Test token refill over time."""
        bucket = TokenBucket(rate=10.0, capacity=10.0)
        bucket.tokens = 5.0

        # Wait a bit for tokens to refill
        await asyncio.sleep(0.2)

        # Acquire should trigger refill calculation
        await bucket.acquire(1.0)

        # Should have refilled ~2 tokens in 0.2s at 10/s
        assert bucket.tokens >= 5.5  # At least some refill


class TestCache:
    """Tests for client caching behavior."""

    def test_cache_key_generation(self, client):
        """Test cache key is deterministic."""
        key1 = client._get_cache_key("public/ticker", {"instrument_name": "BTC-PERPETUAL"})
        key2 = client._get_cache_key("public/ticker", {"instrument_name": "BTC-PERPETUAL"})
        key3 = client._get_cache_key("public/ticker", {"instrument_name": "ETH-PERPETUAL"})

        assert key1 == key2  # Same params = same key
        assert key1 != key3  # Different params = different key

    def test_cache_ttl_selection(self, client):
        """Test correct TTL selection for different methods."""
        fast_ttl = client._get_cache_ttl("public/ticker")
        slow_ttl = client._get_cache_ttl("public/get_instruments")

        assert fast_ttl == client.settings.cache_ttl_fast
        assert slow_ttl == client.settings.cache_ttl_slow

    def test_cache_hit(self, client):
        """Test cache hit returns cached value."""
        method = "public/ticker"
        params = {"instrument_name": "BTC-PERPETUAL"}
        cached_value = {"mark_price": 50000}

        # Set cache
        client._set_cache(method, params, cached_value)

        # Get should return cached value
        result = client._get_from_cache(method, params)

        assert result == cached_value

    def test_cache_miss_expired(self, client):
        """Test cache miss when entry expired."""
        method = "public/ticker"
        params = {"instrument_name": "BTC-PERPETUAL"}

        # Set cache with past expiration
        key = client._get_cache_key(method, params)
        client._cache[key] = CacheEntry(
            value={"old": "data"},
            expires_at=time.time() - 10,  # Expired
            cache_tier="fast",
        )

        # Get should return None (expired)
        result = client._get_from_cache(method, params)

        assert result is None

    def test_no_cache_methods(self, client):
        """Test that certain methods are never cached."""
        method = "public/auth"
        params = {"grant_type": "client_credentials"}

        # Try to set cache
        client._set_cache(method, params, {"access_token": "secret"})

        # Should not be cached
        result = client._get_from_cache(method, params)

        assert result is None

    def test_cache_clear(self, client):
        """Test cache clearing."""
        # Add some entries
        client._set_cache("public/ticker", {"a": 1}, {"data": "a"})
        client._set_cache("public/ticker", {"b": 2}, {"data": "b"})

        assert len(client._cache) == 2

        # Clear
        client.clear_cache()

        assert len(client._cache) == 0

    def test_cache_stats(self, client):
        """Test cache statistics."""
        # Add fast and slow cache entries
        client._set_cache("public/ticker", {"a": 1}, {"data": "fast"})
        client._set_cache("public/get_instruments", {"b": 2}, {"data": "slow"})

        stats = client.get_cache_stats()

        assert stats["total_entries"] == 2
        assert stats["fast_tier_entries"] == 1
        assert stats["slow_tier_entries"] == 1


class TestErrorHandling:
    """Tests for error handling and degradation."""

    def test_deribit_error_creation(self):
        """Test DeribitError creation."""
        error = DeribitError(code=10001, message="Test error", data={"detail": "info"})

        assert error.code == 10001
        assert error.message == "Test error"
        assert error.data == {"detail": "info"}
        assert "10001" in str(error)

    def test_rate_limit_error(self):
        """Test rate limit error is subclass."""
        error = DeribitRateLimitError(code=10028, message="Too many requests")

        assert isinstance(error, DeribitError)
        assert error.code == 10028

    def test_timeout_error(self):
        """Test timeout error is subclass."""
        error = DeribitTimeoutError(code=-1, message="Request timeout")

        assert isinstance(error, DeribitError)

    @pytest.mark.asyncio
    async def test_call_with_cache_hit_skips_request(self, client):
        """Test that cache hit skips actual request."""
        method = "public/ticker"
        params = {"instrument_name": "BTC-PERPETUAL"}
        cached_value = {"mark_price": 50000}

        # Set cache
        client._set_cache(method, params, cached_value)

        # Mock the request method to track calls
        client._do_request = AsyncMock()

        # Call should use cache
        result = await client.call(method, params)

        assert result == cached_value
        client._do_request.assert_not_called()


class TestClientIntegration:
    """Integration-style tests for client behavior."""

    @pytest.mark.asyncio
    async def test_client_close(self, client):
        """Test client can be closed."""
        # Create HTTP client
        _ = client.http_client
        assert client._http_client is not None

        # Close
        await client.close()

        assert client._http_client is None

    def test_request_id_increments(self, client):
        """Test request ID increments correctly."""
        id1 = client._next_request_id()
        id2 = client._next_request_id()
        id3 = client._next_request_id()

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3


class TestConfigSecurity:
    """Tests for configuration security."""

    def test_secret_not_in_summary(self):
        """Test that secrets are masked in config summary."""
        settings = Settings(
            env="prod",
            client_id="test_client_123",
            client_secret="super_secret_key_abc",
        )

        summary = settings.get_safe_config_summary()

        assert "super_secret_key_abc" not in str(summary)
        assert "REDACTED" in summary["client_secret"]
        assert "test" in summary["client_id"]  # First 4 chars
        assert "****" in summary["client_id"]  # Masked

    def test_has_credentials_check(self):
        """Test credentials check."""
        no_creds = Settings(client_id="", client_secret="")
        has_creds = Settings(client_id="id", client_secret="secret")

        assert not no_creds.has_credentials
        assert has_creds.has_credentials

    def test_base_url_selection(self):
        """Test correct base URL for environment."""
        prod = Settings(env="prod")
        test = Settings(env="test")

        assert "www.deribit.com" in prod.base_url
        assert "test.deribit.com" in test.base_url
