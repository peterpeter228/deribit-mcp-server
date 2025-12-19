"""
Configuration management with pydantic-settings.

All sensitive values are read from environment variables.
NEVER log or expose client_secret in plaintext.
"""

import re
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeribitEnv(str, Enum):
    """Deribit API environment."""

    PROD = "prod"
    TEST = "test"


class Settings(BaseSettings):
    """
    Deribit MCP Server configuration.

    All values read from environment variables with DERIBIT_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="DERIBIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment selection
    env: DeribitEnv = Field(default=DeribitEnv.PROD, description="API environment: prod or test")

    # Private API toggle (default: disabled for safety)
    enable_private: bool = Field(
        default=False, description="Enable private/authenticated API tools"
    )

    # Credentials (only used if enable_private=True)
    client_id: str = Field(default="", description="Deribit API client ID")
    client_secret: SecretStr = Field(
        default=SecretStr(""), description="Deribit API client secret (never logged)"
    )

    # Network settings
    timeout_s: float = Field(
        default=10.0, ge=1.0, le=60.0, description="HTTP request timeout in seconds"
    )
    max_rps: float = Field(
        default=8.0, ge=1.0, le=20.0, description="Maximum requests per second (token bucket rate)"
    )

    # Cache TTL settings
    cache_ttl_fast: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Fast cache TTL for ticker/orderbook (seconds)"
    )
    cache_ttl_slow: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description="Slow cache TTL for instruments/expirations (seconds)",
    )

    # Trading safety
    dry_run: bool = Field(
        default=True, description="If True, place_order only simulates, never executes"
    )

    # Server settings
    host: str = Field(default="0.0.0.0", description="HTTP server host")
    port: int = Field(default=8000, ge=1, le=65535, description="HTTP server port")

    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str | SecretStr) -> str | SecretStr:
        """Strip whitespace from credentials."""
        if isinstance(v, str):
            return v.strip()
        return v

    @property
    def base_url(self) -> str:
        """Get the Deribit API base URL for current environment."""
        if self.env == DeribitEnv.TEST:
            return "https://test.deribit.com/api/v2"
        return "https://www.deribit.com/api/v2"

    @property
    def ws_url(self) -> str:
        """Get the Deribit WebSocket URL for current environment."""
        if self.env == DeribitEnv.TEST:
            return "wss://test.deribit.com/ws/api/v2"
        return "wss://www.deribit.com/ws/api/v2"

    @property
    def has_credentials(self) -> bool:
        """Check if valid credentials are configured."""
        return bool(self.client_id and self.client_secret.get_secret_value())

    def get_safe_config_summary(self) -> dict:
        """
        Return a safe summary of configuration for logging.

        NEVER includes actual secrets - only masked values.
        """
        secret_val = self.client_secret.get_secret_value()
        masked_secret = "***REDACTED***" if secret_val else "(not set)"
        masked_id = self._mask_string(self.client_id) if self.client_id else "(not set)"

        return {
            "env": self.env.value,
            "base_url": self.base_url,
            "enable_private": self.enable_private,
            "client_id": masked_id,
            "client_secret": masked_secret,
            "timeout_s": self.timeout_s,
            "max_rps": self.max_rps,
            "cache_ttl_fast": self.cache_ttl_fast,
            "cache_ttl_slow": self.cache_ttl_slow,
            "dry_run": self.dry_run,
        }

    @staticmethod
    def _mask_string(s: str, show_chars: int = 4) -> str:
        """Mask a string, showing only first few characters."""
        if len(s) <= show_chars:
            return "****"
        return s[:show_chars] + "****"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure single instance across the application.
    """
    return Settings()


def sanitize_log_message(message: str, settings: Settings | None = None) -> str:
    """
    Sanitize a log message by removing any potential secrets.

    This is a safety net - secrets should never be in logs anyway,
    but this provides defense in depth.
    """
    if settings is None:
        settings = get_settings()

    sanitized = message

    # Mask client_secret if it appears
    secret = settings.client_secret.get_secret_value()
    if secret and secret in sanitized:
        sanitized = sanitized.replace(secret, "***REDACTED***")

    # Mask client_id if it appears (partial match)
    if settings.client_id and settings.client_id in sanitized:
        sanitized = sanitized.replace(settings.client_id, Settings._mask_string(settings.client_id))

    # Generic patterns for API keys/tokens
    sanitized = re.sub(
        r'(client_secret|api_key|secret|token|password)(["\s:=]+)[^\s,"}\]]+',
        r"\1\2***REDACTED***",
        sanitized,
        flags=re.IGNORECASE,
    )

    return sanitized


# Type alias for currency
Currency = Literal["BTC", "ETH"]
InstrumentKind = Literal["option", "future"]
