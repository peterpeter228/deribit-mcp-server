"""
Deribit JSON-RPC Client with caching, rate limiting, and retry logic.

Features:
- Token bucket rate limiting
- TTL-based caching (fast/slow tiers)
- Exponential backoff with jitter
- Unified error handling
- Automatic authentication management
"""

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings, get_settings, sanitize_log_message

logger = logging.getLogger(__name__)


class DeribitError(Exception):
    """Base exception for Deribit API errors."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"Deribit error {code}: {message}")


class DeribitRateLimitError(DeribitError):
    """Rate limit exceeded."""

    pass


class DeribitAuthError(DeribitError):
    """Authentication error."""

    pass


class DeribitTimeoutError(DeribitError):
    """Request timeout."""

    pass


@dataclass
class CacheEntry:
    """Cache entry with TTL tracking."""

    value: Any
    expires_at: float
    cache_tier: str  # 'fast' or 'slow'


@dataclass
class TokenBucket:
    """Simple token bucket for rate limiting."""

    rate: float  # tokens per second
    capacity: float  # max tokens
    tokens: float = field(default=0.0)
    last_update: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.tokens = self.capacity

    async def acquire(self, tokens: float = 1.0) -> float:
        """
        Acquire tokens, waiting if necessary.

        Returns the wait time in seconds.
        """
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return 0.0

        # Calculate wait time
        deficit = tokens - self.tokens
        wait_time = deficit / self.rate
        await asyncio.sleep(wait_time)

        self.tokens = 0
        self.last_update = time.monotonic()
        return wait_time


@dataclass
class AuthToken:
    """Cached authentication token."""

    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 30s buffer)."""
        return time.time() > (self.expires_at - 30)


class DeribitJsonRpcClient:
    """
    Async JSON-RPC client for Deribit API.

    Features:
    - Automatic rate limiting via token bucket
    - Two-tier caching (fast for market data, slow for metadata)
    - Exponential backoff retry with jitter
    - Automatic authentication management
    """

    # Methods that use slow cache (metadata)
    SLOW_CACHE_METHODS = {
        "public/get_instruments",
        "public/get_currencies",
        "public/get_index",
    }

    # Methods that should never be cached
    NO_CACHE_METHODS = {
        "public/auth",
        "private/buy",
        "private/sell",
        "private/cancel",
        "private/cancel_all",
    }

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._http_client: httpx.AsyncClient | None = None
        self._cache: dict[str, CacheEntry] = {}
        self._rate_limiter = TokenBucket(
            rate=self.settings.max_rps,
            capacity=self.settings.max_rps * 2,  # Allow burst
        )
        self._auth_token: AuthToken | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.settings.base_url,
                timeout=httpx.Timeout(self.settings.timeout_s),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "DeribitMCPServer/1.0",
                },
            )
        return self._http_client

    async def close(self):
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _get_cache_key(self, method: str, params: dict[str, Any] | None) -> str:
        """Generate a cache key from method and params."""
        param_str = json.dumps(params or {}, sort_keys=True)
        key_str = f"{method}:{param_str}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache_ttl(self, method: str) -> float:
        """Get appropriate TTL for a method."""
        if method in self.SLOW_CACHE_METHODS:
            return self.settings.cache_ttl_slow
        return self.settings.cache_ttl_fast

    def _get_from_cache(self, method: str, params: dict[str, Any] | None) -> Any | None:
        """Get value from cache if not expired."""
        if method in self.NO_CACHE_METHODS:
            return None

        key = self._get_cache_key(method, params)
        entry = self._cache.get(key)

        if entry is None:
            return None

        if time.time() > entry.expires_at:
            del self._cache[key]
            return None

        logger.debug(f"Cache hit for {method} (tier: {entry.cache_tier})")
        return entry.value

    def _set_cache(self, method: str, params: dict[str, Any] | None, value: Any):
        """Store value in cache."""
        if method in self.NO_CACHE_METHODS:
            return

        key = self._get_cache_key(method, params)
        ttl = self._get_cache_ttl(method)
        tier = "slow" if method in self.SLOW_CACHE_METHODS else "fast"

        self._cache[key] = CacheEntry(
            value=value,
            expires_at=time.time() + ttl,
            cache_tier=tier,
        )

    def _clean_expired_cache(self):
        """Remove expired cache entries."""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if now > v.expires_at]
        for key in expired_keys:
            del self._cache[key]

    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id

    async def _do_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
    ) -> Any:
        """
        Execute a single JSON-RPC request.

        Returns the 'result' field from the response.
        Raises DeribitError on API errors.
        """
        # Wait for rate limit
        wait_time = await self._rate_limiter.acquire()
        if wait_time > 0:
            logger.debug(f"Rate limited, waited {wait_time:.3f}s")

        # Build request
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params or {},
        }

        # Add auth if provided
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        try:
            # Deribit JSON-RPC: POST to base URL with method in body
            # Example: POST https://www.deribit.com/api/v2
            #          Body: {"jsonrpc":"2.0","id":1,"method":"public/get_time","params":{}}
            logger.debug(f"Making request: {method}")
            response = await self.http_client.post(
                "",  # Empty path = POST to base_url directly
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
                
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {method} after {self.settings.timeout_s}s")
            raise DeribitTimeoutError(
                code=-1,
                message=f"Request timeout after {self.settings.timeout_s}s",
                data=str(e),
            )
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:500]
            sanitized_error = sanitize_log_message(error_text)
            logger.error(f"HTTP error {e.response.status_code} for {method}: {sanitized_error}")
            raise DeribitError(
                code=e.response.status_code,
                message=f"HTTP error: {sanitized_error}",
            )
        except Exception as e:
            logger.error(f"Request failed for {method}: {type(e).__name__}: {e}")
            raise DeribitError(
                code=-1,
                message=f"Request failed: {type(e).__name__}",
                data=str(e),
            )

        # Handle JSON-RPC error
        if "error" in data:
            error = data["error"]
            code = error.get("code", -1)
            message = sanitize_log_message(error.get("message", "Unknown error"))
            error_data = error.get("data")

            # Classify error
            if code == 10028:  # Too many requests
                raise DeribitRateLimitError(code, message, error_data)
            elif code in (13004, 13009):  # Auth errors
                raise DeribitAuthError(code, message, error_data)
            else:
                raise DeribitError(code, message, error_data)

        return data.get("result")

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        use_auth: bool = False,
        max_retries: int = 2,
    ) -> Any:
        """
        Call a Deribit JSON-RPC method with caching, retry, and optional auth.

        Args:
            method: JSON-RPC method name (e.g., "public/ticker")
            params: Method parameters
            use_auth: Whether to use authentication
            max_retries: Maximum retry attempts (default: 2)

        Returns:
            The 'result' from the JSON-RPC response

        Raises:
            DeribitError: On API errors after all retries
        """
        # Check cache first
        cached = self._get_from_cache(method, params)
        if cached is not None:
            return cached

        # Get auth token if needed
        access_token = None
        if use_auth:
            access_token = await self._get_access_token()

        # Retry loop with exponential backoff
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                result = await self._do_request(method, params, access_token)

                # Cache successful result
                self._set_cache(method, params, result)

                return result

            except DeribitRateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    # Longer backoff for rate limits
                    delay = (2**attempt) + random.uniform(0.5, 1.5)
                    logger.warning(
                        f"Rate limited, retry {attempt + 1}/{max_retries} after {delay:.2f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

            except DeribitAuthError:
                # Clear cached token and retry once
                self._auth_token = None
                if attempt == 0 and use_auth:
                    logger.warning("Auth error, refreshing token and retrying")
                    access_token = await self._get_access_token()
                    continue
                raise

            except DeribitTimeoutError as e:
                last_error = e
                if attempt < max_retries:
                    delay = (1.5**attempt) + random.uniform(0.1, 0.5)
                    logger.warning(f"Timeout, retry {attempt + 1}/{max_retries} after {delay:.2f}s")
                    await asyncio.sleep(delay)
                    continue
                raise

            except DeribitError as e:
                last_error = e
                # Don't retry client errors (4xx equivalent)
                if e.code >= 10000 and e.code < 20000:
                    raise

                if attempt < max_retries:
                    delay = (1.5**attempt) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Error {e.code}, retry {attempt + 1}/{max_retries} after {delay:.2f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise DeribitError(-1, "Unknown error after retries")

    async def _get_access_token(self) -> str:
        """
        Get a valid access token, authenticating if necessary.

        Uses client_credentials grant type.
        """
        async with self._lock:
            # Check if we have a valid token
            if self._auth_token and not self._auth_token.is_expired:
                return self._auth_token.access_token

            # Check credentials
            if not self.settings.has_credentials:
                raise DeribitAuthError(
                    code=13009,
                    message="No credentials configured. Set DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET",
                )

            # Authenticate
            logger.info(f"Authenticating with Deribit (client_id: {self.settings.client_id[:4]}****)...")
            try:
                result = await self._do_request(
                    "public/auth",
                    {
                        "grant_type": "client_credentials",
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret.get_secret_value(),
                    },
                )
                
                if not result or "access_token" not in result:
                    raise DeribitAuthError(
                        code=13009,
                        message="Authentication response missing access_token",
                        data=result,
                    )

                # Store token
                self._auth_token = AuthToken(
                    access_token=result["access_token"],
                    refresh_token=result.get("refresh_token", ""),
                    expires_at=time.time() + result.get("expires_in", 900),
                )

                logger.info(f"Authentication successful (expires in {result.get('expires_in', 900)}s)")
                return self._auth_token.access_token
            except DeribitAuthError as e:
                logger.error(f"Authentication failed: {e.code} - {e.message}")
                if e.code == 13009:
                    logger.error("Invalid credentials - please check DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET")
                raise
            except Exception as e:
                logger.error(f"Unexpected authentication error: {type(e).__name__}: {e}", exc_info=True)
                raise DeribitAuthError(
                    code=13009,
                    message=f"Authentication error: {str(e)[:200]}",
                )

    async def call_public(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Convenience method for public API calls."""
        if not method.startswith("public/"):
            method = f"public/{method}"
        return await self.call(method, params, use_auth=False)

    async def call_private(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Convenience method for private API calls."""
        if not method.startswith("private/"):
            method = f"private/{method}"
        return await self.call(method, params, use_auth=True)

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        self._clean_expired_cache()

        fast_count = sum(1 for e in self._cache.values() if e.cache_tier == "fast")
        slow_count = sum(1 for e in self._cache.values() if e.cache_tier == "slow")

        return {
            "total_entries": len(self._cache),
            "fast_tier_entries": fast_count,
            "slow_tier_entries": slow_count,
        }


# Global client instance
_client: DeribitJsonRpcClient | None = None


def get_client(settings: Settings | None = None) -> DeribitJsonRpcClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = DeribitJsonRpcClient(settings)
    return _client


async def shutdown_client():
    """Shutdown the global client."""
    global _client
    if _client:
        await _client.close()
        _client = None
