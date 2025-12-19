#!/bin/bash
# =============================================================================
# Deribit MCP Server - Ubuntu 安装脚本
# =============================================================================
# 用法: sudo bash install.sh
# 
# 功能:
# - 安装 Python 3.11+ 和依赖
# - 创建专用用户和目录
# - 安装项目
# - 配置 systemd 服务（自动重启）
# - 配置日志轮转
# =============================================================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置变量
APP_NAME="deribit-mcp"
APP_USER="deribit"
APP_GROUP="deribit"
INSTALL_DIR="/opt/deribit-mcp"
CONFIG_DIR="/etc/deribit-mcp"
LOG_DIR="/var/log/deribit-mcp"
VENV_DIR="${INSTALL_DIR}/venv"

# 打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否以 root 运行
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "此脚本需要 root 权限运行"
        print_info "请使用: sudo bash install.sh"
        exit 1
    fi
}

# 检查系统要求
check_requirements() {
    print_info "检查系统要求..."
    
    # 检查是否是 Ubuntu/Debian
    if ! command -v apt-get &> /dev/null; then
        print_error "此脚本仅支持 Ubuntu/Debian 系统"
        exit 1
    fi
    
    print_info "系统检查通过"
}

# 安装系统依赖
install_system_deps() {
    print_info "更新系统包..."
    apt-get update -qq
    
    print_info "安装系统依赖..."
    apt-get install -y -qq \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        git \
        curl \
        build-essential \
        libffi-dev \
        libssl-dev
    
    # 如果 python3.11 不可用，尝试安装
    if ! command -v python3.11 &> /dev/null; then
        print_warn "Python 3.11 不可用，尝试从 deadsnakes PPA 安装..."
        apt-get install -y -qq software-properties-common
        add-apt-repository -y ppa:deadsnakes/ppa
        apt-get update -qq
        apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
    fi
    
    print_info "系统依赖安装完成"
}

# 创建用户和目录
create_user_and_dirs() {
    print_info "创建应用用户和目录..."
    
    # 创建用户（如果不存在）
    if ! id "$APP_USER" &>/dev/null; then
        useradd --system --shell /bin/false --home-dir "$INSTALL_DIR" "$APP_USER"
        print_info "创建用户: $APP_USER"
    else
        print_warn "用户 $APP_USER 已存在"
    fi
    
    # 创建目录
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$LOG_DIR"
    
    print_info "目录创建完成"
}

# 安装应用
install_app() {
    print_info "安装应用..."
    
    # 获取脚本所在目录（项目根目录）
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    
    # 复制项目文件
    print_info "复制项目文件到 $INSTALL_DIR..."
    cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
    
    # 创建虚拟环境
    print_info "创建 Python 虚拟环境..."
    python3.11 -m venv "$VENV_DIR"
    
    # 安装依赖
    print_info "安装 Python 依赖..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"
    
    print_info "应用安装完成"
}

# 创建配置文件
create_config() {
    print_info "创建配置文件..."
    
    CONFIG_FILE="$CONFIG_DIR/config.env"
    
    if [[ -f "$CONFIG_FILE" ]]; then
        print_warn "配置文件已存在，跳过创建"
        print_warn "如需重新配置，请编辑: $CONFIG_FILE"
    else
        cat > "$CONFIG_FILE" << 'EOF'
# =============================================================================
# Deribit MCP Server 配置
# =============================================================================
# 编辑此文件后运行: sudo systemctl restart deribit-mcp

# 环境选择: prod 或 test
DERIBIT_ENV=prod

# Private API 开关 (true/false)
DERIBIT_ENABLE_PRIVATE=false

# API 凭证 (仅 Private API 需要)
# ⚠️ 请替换为真实凭证
DERIBIT_CLIENT_ID=YOUR_CLIENT_ID
DERIBIT_CLIENT_SECRET=YOUR_CLIENT_SECRET

# 网络设置
DERIBIT_TIMEOUT_S=10
DERIBIT_MAX_RPS=8

# 缓存设置
DERIBIT_CACHE_TTL_FAST=1.0
DERIBIT_CACHE_TTL_SLOW=30.0

# 交易安全 (true = 只模拟，不执行)
DERIBIT_DRY_RUN=true

# HTTP 服务器设置
DERIBIT_HOST=0.0.0.0
DERIBIT_PORT=8000
EOF
        chmod 600 "$CONFIG_FILE"
        print_info "配置文件创建完成: $CONFIG_FILE"
    fi
}

# 创建 systemd 服务
create_systemd_service() {
    print_info "创建 systemd 服务..."
    
    # HTTP 服务
    cat > /etc/systemd/system/deribit-mcp.service << EOF
[Unit]
Description=Deribit MCP Server (HTTP/SSE)
Documentation=https://github.com/example/deribit-mcp-server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$INSTALL_DIR

# 环境配置
EnvironmentFile=$CONFIG_DIR/config.env

# 启动命令
ExecStart=$VENV_DIR/bin/python -m deribit_mcp.http_server

# 自动重启配置
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

# 资源限制
MemoryMax=512M
CPUQuota=100%

# 安全加固
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$LOG_DIR

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=deribit-mcp

[Install]
WantedBy=multi-user.target
EOF

    # stdio 服务（可选，用于本地 MCP 客户端）
    cat > /etc/systemd/system/deribit-mcp-stdio@.service << EOF
[Unit]
Description=Deribit MCP Server (stdio mode) - %i
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$INSTALL_DIR

EnvironmentFile=$CONFIG_DIR/config.env

ExecStart=$VENV_DIR/bin/python -m deribit_mcp.server

Restart=on-failure
RestartSec=5

StandardInput=socket
StandardOutput=socket
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    print_info "systemd 服务创建完成"
}

# 创建日志轮转配置
create_logrotate() {
    print_info "配置日志轮转..."
    
    cat > /etc/logrotate.d/deribit-mcp << EOF
$LOG_DIR/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 $APP_USER $APP_GROUP
    sharedscripts
    postrotate
        systemctl reload deribit-mcp > /dev/null 2>&1 || true
    endscript
}
EOF

    print_info "日志轮转配置完成"
}

# 设置权限
set_permissions() {
    print_info "设置文件权限..."
    
    chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"
    chown -R "$APP_USER:$APP_GROUP" "$LOG_DIR"
    chown -R root:$APP_GROUP "$CONFIG_DIR"
    chmod 750 "$CONFIG_DIR"
    
    print_info "权限设置完成"
}

# 启动服务
start_service() {
    print_info "启动服务..."
    
    systemctl daemon-reload
    systemctl enable deribit-mcp
    systemctl start deribit-mcp
    
    # 等待服务启动
    sleep 2
    
    if systemctl is-active --quiet deribit-mcp; then
        print_info "服务启动成功!"
    else
        print_error "服务启动失败，请检查日志:"
        print_error "  journalctl -u deribit-mcp -f"
        exit 1
    fi
}

# 打印安装完成信息
print_completion() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}Deribit MCP Server 安装完成!${NC}"
    echo "=============================================="
    echo ""
    echo "安装位置: $INSTALL_DIR"
    echo "配置文件: $CONFIG_DIR/config.env"
    echo "日志目录: $LOG_DIR"
    echo ""
    echo "常用命令:"
    echo "  查看状态:     sudo systemctl status deribit-mcp"
    echo "  查看日志:     sudo journalctl -u deribit-mcp -f"
    echo "  重启服务:     sudo systemctl restart deribit-mcp"
    echo "  停止服务:     sudo systemctl stop deribit-mcp"
    echo "  编辑配置:     sudo nano $CONFIG_DIR/config.env"
    echo ""
    echo "API 端点:"
    echo "  健康检查:     http://localhost:8000/health"
    echo "  工具列表:     http://localhost:8000/tools"
    echo "  SSE 连接:     http://localhost:8000/sse"
    echo ""
    echo -e "${YELLOW}重要: 请编辑配置文件设置 API 凭证${NC}"
    echo "  sudo nano $CONFIG_DIR/config.env"
    echo "  sudo systemctl restart deribit-mcp"
    echo ""
}

# 主函数
main() {
    echo "=============================================="
    echo "Deribit MCP Server - Ubuntu 安装脚本"
    echo "=============================================="
    echo ""
    
    check_root
    check_requirements
    install_system_deps
    create_user_and_dirs
    install_app
    create_config
    create_systemd_service
    create_logrotate
    set_permissions
    start_service
    print_completion
}

# 运行主函数
main "$@"
