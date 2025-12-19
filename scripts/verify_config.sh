#!/bin/bash
# Quick script to verify Deribit MCP Server configuration

echo "=== Deribit MCP Server Configuration Verification ==="
echo ""

# Check if .env file exists
if [ -f ".env" ]; then
    echo "✓ .env file found"
else
    echo "✗ .env file not found"
    exit 1
fi

# Check required variables
echo ""
echo "Checking required environment variables:"

check_var() {
    if grep -q "^$1=" .env 2>/dev/null; then
        value=$(grep "^$1=" .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
        if [ -n "$value" ]; then
            echo "  ✓ $1 is set"
            return 0
        else
            echo "  ✗ $1 is empty"
            return 1
        fi
    else
        echo "  ✗ $1 is missing"
        return 1
    fi
}

check_var "DERIBIT_ENV"
check_var "DERIBIT_ENABLE_PRIVATE"
check_var "DERIBIT_CLIENT_ID"
check_var "DERIBIT_CLIENT_SECRET"
check_var "DERIBIT_PORT"

echo ""
echo "=== Configuration Summary ==="
echo ""
echo "Environment: $(grep '^DERIBIT_ENV=' .env | cut -d'=' -f2)"
echo "Private API: $(grep '^DERIBIT_ENABLE_PRIVATE=' .env | cut -d'=' -f2)"
echo "Port: $(grep '^DERIBIT_PORT=' .env | cut -d'=' -f2)"
echo "Client ID: $(grep '^DERIBIT_CLIENT_ID=' .env | cut -d'=' -f2 | cut -c1-4)****"
echo ""
echo "=== Next Steps ==="
echo "1. Build and start: docker compose up -d --build"
echo "2. Check logs: docker compose logs -f"
echo "3. Test health: curl http://localhost:$(grep '^DERIBIT_PORT=' .env | cut -d'=' -f2)/health"
echo ""
