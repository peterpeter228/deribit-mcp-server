#!/bin/bash
# =============================================================================
# Deribit MCP Server - 更新脚本
# =============================================================================
# 用法: sudo bash update.sh
# =============================================================================

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 配置变量
INSTALL_DIR="/opt/deribit-mcp"
VENV_DIR="${INSTALL_DIR}/venv"

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 root 权限
if [[ $EUID -ne 0 ]]; then
    print_error "此脚本需要 root 权限运行"
    exit 1
fi

echo "=============================================="
echo "Deribit MCP Server - 更新脚本"
echo "=============================================="
echo ""

# 检查安装目录
if [[ ! -d "$INSTALL_DIR" ]]; then
    print_error "未找到安装目录: $INSTALL_DIR"
    print_error "请先运行 install.sh 安装"
    exit 1
fi

# 获取脚本所在目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 停止服务
print_info "停止服务..."
systemctl stop deribit-mcp 2>/dev/null || true

# 备份当前版本
BACKUP_DIR="/tmp/deribit-mcp-backup-$(date +%Y%m%d%H%M%S)"
print_info "备份当前版本到: $BACKUP_DIR"
cp -r "$INSTALL_DIR/src" "$BACKUP_DIR" 2>/dev/null || true

# 更新代码
print_info "更新代码..."
rm -rf "$INSTALL_DIR/src"
cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"

# 更新依赖
print_info "更新 Python 依赖..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

# 修复权限
print_info "修复文件权限..."
chown -R deribit:deribit "$INSTALL_DIR"

# 重新加载 systemd
systemctl daemon-reload

# 启动服务
print_info "启动服务..."
systemctl start deribit-mcp

# 检查服务状态
sleep 2
if systemctl is-active --quiet deribit-mcp; then
    print_info "服务启动成功!"
else
    print_error "服务启动失败!"
    print_warn "尝试恢复备份..."
    rm -rf "$INSTALL_DIR/src"
    cp -r "$BACKUP_DIR" "$INSTALL_DIR/src"
    systemctl start deribit-mcp
    exit 1
fi

echo ""
echo -e "${GREEN}更新完成!${NC}"
echo ""
echo "查看服务状态: sudo systemctl status deribit-mcp"
echo "查看日志: sudo journalctl -u deribit-mcp -f"
