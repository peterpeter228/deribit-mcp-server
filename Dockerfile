# Deribit MCP Server Docker Image
# Multi-stage build for smaller final image

# =============================================================================
# Build Stage
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv sync --no-dev

# =============================================================================
# Runtime Stage
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Copy from builder
COPY --from=builder /app /app
COPY --from=builder /root/.local /root/.local

# Install uv in runtime (needed to run commands)
RUN pip install --no-cache-dir uv

# Copy source code
COPY src/ src/
COPY pyproject.toml .

# Install package
RUN uv sync --no-dev

# Set ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Default environment variables
ENV DERIBIT_ENV=prod
ENV DERIBIT_ENABLE_PRIVATE=false
ENV DERIBIT_HOST=0.0.0.0
ENV DERIBIT_PORT=8000
ENV DERIBIT_TIMEOUT_S=10
ENV DERIBIT_MAX_RPS=8
ENV DERIBIT_CACHE_TTL_FAST=1.0
ENV DERIBIT_CACHE_TTL_SLOW=30.0
ENV DERIBIT_DRY_RUN=true

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Default command: HTTP server
# Override with CMD ["uv", "run", "deribit-mcp"] for stdio mode
CMD ["uv", "run", "deribit-mcp-http"]
