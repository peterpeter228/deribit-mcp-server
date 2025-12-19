#!/usr/bin/env python3
"""
Quick test script to verify Deribit API connection and credentials.
Run this inside the Docker container or locally.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from deribit_mcp.diagnostics import run_full_diagnostics


async def main():
    """Run diagnostics."""
    print("Testing Deribit API Connection...")
    print("=" * 60)
    
    try:
        results = await run_full_diagnostics()
        
        # Print summary
        print("\n" + "=" * 60)
        print("SUMMARY:")
        print("=" * 60)
        print(f"Public API:     {'✓ PASS' if results['public_api']['success'] else '✗ FAIL'}")
        if results['public_api']['error']:
            print(f"  Error: {results['public_api']['error']}")
        
        print(f"Authentication: {'✓ PASS' if results['authentication']['success'] else '✗ FAIL'}")
        if results['authentication']['error']:
            print(f"  Error: {results['authentication']['error']}")
        
        if results['config']['enable_private']:
            print(f"Private API:    {'✓ PASS' if results['private_api']['success'] else '✗ FAIL'}")
            if results['private_api'].get('error'):
                print(f"  Error: {results['private_api']['error']}")
        
        print("=" * 60)
        
        # Exit with error code if critical tests failed
        if not results['public_api']['success']:
            print("\n❌ Public API test failed - check network connectivity")
            sys.exit(1)
        
        if results['config']['enable_private'] and not results['authentication']['success']:
            print("\n❌ Authentication failed - check DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET")
            sys.exit(1)
        
        print("\n✓ All tests passed!")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
