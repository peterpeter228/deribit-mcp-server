#!/bin/bash
# =============================================================================
# Deribit MCP Server - 一键安装脚本 (从 GitHub)
# =============================================================================
# 用法: 
#   curl -sSL https://raw.githubusercontent.com/your-repo/deribit-mcp-server/main/scripts/quick-install.sh | sudo bash
#
# 或者:
#   wget -qO- https://raw.githubusercontent.com/your-repo/deribit-mcp-server/main/scripts/quick-install.sh | sudo bash
# =============================================================================

set -e

# 配置
REPO_URL="https://github.com/your-repo/deribit-mcp-server.git"
INSTALL_DIR="/opt/deribit-mcp"
TMP_DIR="/tmp/deribit-mcp-install"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查 root
if [[ $EUID -ne 0 ]]; then
    print_error "请使用 sudo 运行此脚本"
    exit 1
fi

echo "=============================================="
echo "Deribit MCP Server - 一键安装"
echo "=============================================="
echo ""

# 安装 git
print_info "安装依赖..."
apt-get update -qq
apt-get install -y -qq git curl

# 克隆仓库
print_info "下载代码..."
rm -rf "$TMP_DIR"
git clone --depth 1 "$REPO_URL" "$TMP_DIR"

# 运行安装脚本
print_info "运行安装脚本..."
cd "$TMP_DIR"
chmod +x scripts/install.sh
bash scripts/install.sh

# 清理
rm -rf "$TMP_DIR"

print_info "安装完成!"
