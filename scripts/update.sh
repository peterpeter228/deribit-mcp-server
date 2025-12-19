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
    print_info "请使用: sudo bash update.sh"
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

# 检查虚拟环境
if [[ ! -f "$VENV_DIR/bin/python" ]]; then
    print_error "未找到 Python 虚拟环境: $VENV_DIR"
    exit 1
fi

# 获取脚本所在目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 检查源文件
if [[ ! -d "$SCRIPT_DIR/src" ]]; then
    print_error "找不到源代码目录: $SCRIPT_DIR/src"
    exit 1
fi

# 停止服务
print_info "停止服务..."
systemctl stop deribit-mcp 2>/dev/null || true

# 备份当前版本
BACKUP_DIR="/tmp/deribit-mcp-backup-$(date +%Y%m%d%H%M%S)"
print_info "备份当前版本到: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
cp -r "$INSTALL_DIR/src" "$BACKUP_DIR/" 2>/dev/null || true
cp "$INSTALL_DIR/pyproject.toml" "$BACKUP_DIR/" 2>/dev/null || true

# 更新代码
print_info "更新代码..."
rm -rf "$INSTALL_DIR/src"
cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"

# 更新脚本
print_info "更新脚本..."
mkdir -p "$INSTALL_DIR/scripts"
cp "$SCRIPT_DIR/scripts/"*.sh "$INSTALL_DIR/scripts/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true

# 更新依赖
print_info "更新 Python 依赖..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" --quiet || {
    print_warn "静默安装失败，显示详细输出..."
    "$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"
}

# 修复权限
print_info "修复文件权限..."
chown -R deribit:deribit "$INSTALL_DIR"

# 重新加载 systemd
systemctl daemon-reload

# 启动服务
print_info "启动服务..."
systemctl start deribit-mcp

# 检查服务状态
sleep 3
if systemctl is-active --quiet deribit-mcp; then
    print_info "服务启动成功!"
    
    # 健康检查
    sleep 2
    if curl -s --connect-timeout 5 http://localhost:8000/health >/dev/null 2>&1; then
        print_info "健康检查通过!"
    fi
else
    print_error "服务启动失败!"
    print_warn "尝试恢复备份..."
    rm -rf "$INSTALL_DIR/src"
    cp -r "$BACKUP_DIR/src" "$INSTALL_DIR/"
    cp "$BACKUP_DIR/pyproject.toml" "$INSTALL_DIR/"
    chown -R deribit:deribit "$INSTALL_DIR"
    systemctl start deribit-mcp
    
    if systemctl is-active --quiet deribit-mcp; then
        print_warn "已恢复到之前版本"
    else
        print_error "恢复失败，请手动检查"
    fi
    exit 1
fi

# 清理备份（可选保留）
# rm -rf "$BACKUP_DIR"

echo ""
echo -e "${GREEN}✓ 更新完成!${NC}"
echo ""
echo "查看服务状态: sudo systemctl status deribit-mcp"
echo "查看日志: sudo journalctl -u deribit-mcp -f"
echo "备份位置: $BACKUP_DIR"
