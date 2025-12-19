"""
Diagnostic tools for testing Deribit API connectivity and credentials.
"""

import asyncio
import logging
import sys
from typing import Any

from .client import DeribitAuthError, DeribitError, get_client
from .config import get_settings

logger = logging.getLogger(__name__)


async def test_public_api() -> dict[str, Any]:
    """Test public API connectivity."""
    result = {
        "success": False,
        "error": None,
        "server_time": None,
        "status": None,
    }
    
    try:
        client = get_client()
        
        # Test 1: Get server time
        logger.info("Testing public API: get_time...")
        server_time = await client.call_public("public/get_time")
        result["server_time"] = server_time
        logger.info(f"✓ Server time: {server_time}")
        
        # Test 2: Get status
        try:
            logger.info("Testing public API: status...")
            status = await client.call_public("public/status")
            result["status"] = status
            logger.info(f"✓ Status: {status}")
        except Exception as e:
            logger.warning(f"Status check failed: {e}")
        
        result["success"] = True
        return result
        
    except DeribitError as e:
        result["error"] = f"Deribit API error: {e.code} - {e.message}"
        logger.error(result["error"])
        return result
    except Exception as e:
        result["error"] = f"Unexpected error: {type(e).__name__}: {str(e)}"
        logger.error(result["error"], exc_info=True)
        return result


async def test_authentication() -> dict[str, Any]:
    """Test authentication with provided credentials."""
    result = {
        "success": False,
        "error": None,
        "token": None,
        "expires_in": None,
    }
    
    settings = get_settings()
    
    # Check if credentials are configured
    if not settings.has_credentials:
        result["error"] = "No credentials configured (DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET)"
        logger.error(result["error"])
        return result
    
    logger.info(f"Testing authentication with client_id: {settings.client_id[:4]}****")
    
    try:
        client = get_client()
        
        # Try to authenticate
        logger.info("Attempting authentication...")
        token = await client._get_access_token()
        
        if token:
            result["success"] = True
            result["token"] = f"{token[:20]}..." if len(token) > 20 else token
            if client._auth_token:
                result["expires_in"] = int(client._auth_token.expires_at - __import__("time").time())
            logger.info("✓ Authentication successful")
        else:
            result["error"] = "Authentication returned empty token"
            logger.error(result["error"])
            
    except DeribitAuthError as e:
        result["error"] = f"Authentication failed: {e.code} - {e.message}"
        logger.error(result["error"])
        if e.code == 13009:
            result["error"] += " (Invalid credentials - check CLIENT_ID and CLIENT_SECRET)"
        elif e.code == 13004:
            result["error"] += " (Invalid grant type or credentials)"
    except Exception as e:
        result["error"] = f"Unexpected error during authentication: {type(e).__name__}: {str(e)}"
        logger.error(result["error"], exc_info=True)
    
    return result


async def test_private_api() -> dict[str, Any]:
    """Test private API access."""
    result = {
        "success": False,
        "error": None,
        "account_summary": None,
    }
    
    settings = get_settings()
    
    if not settings.enable_private:
        result["error"] = "Private API is disabled (DERIBIT_ENABLE_PRIVATE=false)"
        logger.warning(result["error"])
        return result
    
    try:
        client = get_client()
        
        # Test private API call
        logger.info("Testing private API: get_account_summary...")
        account = await client.call_private("private/get_account_summary", {"currency": "BTC"})
        result["account_summary"] = {
            "currency": account.get("currency"),
            "equity": account.get("equity"),
            "available_funds": account.get("available_funds"),
        }
        result["success"] = True
        logger.info("✓ Private API access successful")
        
    except DeribitAuthError as e:
        result["error"] = f"Private API authentication error: {e.code} - {e.message}"
        logger.error(result["error"])
    except DeribitError as e:
        result["error"] = f"Private API error: {e.code} - {e.message}"
        logger.error(result["error"])
    except Exception as e:
        result["error"] = f"Unexpected error: {type(e).__name__}: {str(e)}"
        logger.error(result["error"], exc_info=True)
    
    return result


async def run_full_diagnostics() -> dict[str, Any]:
    """Run all diagnostic tests."""
    settings = get_settings()
    
    logger.info("=" * 60)
    logger.info("Deribit MCP Server Diagnostics")
    logger.info("=" * 60)
    logger.info(f"Environment: {settings.env.value}")
    logger.info(f"Base URL: {settings.base_url}")
    logger.info(f"Private API enabled: {settings.enable_private}")
    logger.info(f"Client ID: {settings.client_id[:4]}****" if settings.client_id else "Not set")
    logger.info(f"Has credentials: {settings.has_credentials}")
    logger.info("=" * 60)
    
    results = {
        "config": {
            "env": settings.env.value,
            "base_url": settings.base_url,
            "enable_private": settings.enable_private,
            "has_credentials": settings.has_credentials,
            "client_id_set": bool(settings.client_id),
        },
        "public_api": await test_public_api(),
        "authentication": await test_authentication(),
        "private_api": await test_private_api(),
    }
    
    logger.info("=" * 60)
    logger.info("Diagnostic Summary:")
    logger.info(f"  Public API: {'✓' if results['public_api']['success'] else '✗'}")
    logger.info(f"  Authentication: {'✓' if results['authentication']['success'] else '✗'}")
    logger.info(f"  Private API: {'✓' if results['private_api']['success'] else '✗'}")
    logger.info("=" * 60)
    
    return results


async def main():
    """Main entry point for diagnostics."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    results = await run_full_diagnostics()
    
    # Exit with error code if any critical test failed
    if not results["public_api"]["success"]:
        sys.exit(1)
    if results["config"]["enable_private"] and not results["authentication"]["success"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
