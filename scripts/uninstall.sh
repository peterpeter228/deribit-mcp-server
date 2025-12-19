#!/bin/bash
# =============================================================================
# Deribit MCP Server - Ubuntu 卸载脚本
# =============================================================================
# 用法: sudo bash uninstall.sh
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 配置变量
APP_NAME="deribit-mcp"
APP_USER="deribit"
INSTALL_DIR="/opt/deribit-mcp"
CONFIG_DIR="/etc/deribit-mcp"
LOG_DIR="/var/log/deribit-mcp"

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# 检查 root 权限
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR]${NC} 此脚本需要 root 权限运行"
    exit 1
fi

echo "=============================================="
echo "Deribit MCP Server - 卸载脚本"
echo "=============================================="
echo ""

read -p "确定要卸载 Deribit MCP Server? (y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "取消卸载"
    exit 0
fi

# 停止并禁用服务
print_info "停止服务..."
systemctl stop deribit-mcp 2>/dev/null || true
systemctl disable deribit-mcp 2>/dev/null || true

# 删除 systemd 服务文件
print_info "删除 systemd 服务..."
rm -f /etc/systemd/system/deribit-mcp.service
rm -f /etc/systemd/system/deribit-mcp-stdio@.service
systemctl daemon-reload

# 询问是否保留配置
read -p "是否保留配置文件? (Y/n): " keep_config
if [[ "$keep_config" == "n" || "$keep_config" == "N" ]]; then
    print_info "删除配置目录..."
    rm -rf "$CONFIG_DIR"
else
    print_warn "配置文件保留在: $CONFIG_DIR"
fi

# 询问是否保留日志
read -p "是否保留日志文件? (Y/n): " keep_logs
if [[ "$keep_logs" == "n" || "$keep_logs" == "N" ]]; then
    print_info "删除日志目录..."
    rm -rf "$LOG_DIR"
else
    print_warn "日志文件保留在: $LOG_DIR"
fi

# 删除应用目录
print_info "删除应用目录..."
rm -rf "$INSTALL_DIR"

# 删除 logrotate 配置
rm -f /etc/logrotate.d/deribit-mcp

# 询问是否删除用户
read -p "是否删除系统用户 '$APP_USER'? (y/N): " delete_user
if [[ "$delete_user" == "y" || "$delete_user" == "Y" ]]; then
    print_info "删除用户..."
    userdel "$APP_USER" 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}卸载完成!${NC}"
