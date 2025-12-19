# Deribit MCP Server Docker Image
# =============================================================================
# 支持 amd64 和 arm64 架构
# 
# 构建: docker build -t deribit-mcp .
# 运行: docker run -p 8000:8000 deribit-mcp
# =============================================================================

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash appuser

# 复制项目文件
COPY pyproject.toml .
COPY src/ src/

# 安装 Python 依赖
RUN pip install --upgrade pip && \
    pip install -e .

# 设置文件权限
RUN chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 默认环境变量
ENV DERIBIT_ENV=prod \
    DERIBIT_ENABLE_PRIVATE=false \
    DERIBIT_HOST=0.0.0.0 \
    DERIBIT_PORT=8000 \
    DERIBIT_TIMEOUT_S=10 \
    DERIBIT_MAX_RPS=8 \
    DERIBIT_CACHE_TTL_FAST=1.0 \
    DERIBIT_CACHE_TTL_SLOW=30.0 \
    DERIBIT_DRY_RUN=true

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python", "-m", "deribit_mcp.http_server"]
