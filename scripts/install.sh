#!/bin/bash
# =============================================================================
# Deribit MCP Server - Ubuntu 安装脚本
# =============================================================================
# 用法: sudo bash install.sh
#
# 支持的系统:
# - Ubuntu 20.04, 22.04, 24.04
# - Debian 11, 12
#
# 功能:
# - 自动安装 Python 3.10+ 和依赖
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
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
APP_NAME="deribit-mcp"
APP_USER="deribit"
APP_GROUP="deribit"
INSTALL_DIR="/opt/deribit-mcp"
CONFIG_DIR="/etc/deribit-mcp"
LOG_DIR="/var/log/deribit-mcp"
VENV_DIR="${INSTALL_DIR}/venv"

# Python 版本要求
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# 检测到的 Python
PYTHON_CMD=""

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

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 检查是否以 root 运行
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "此脚本需要 root 权限运行"
        print_info "请使用: sudo bash install.sh"
        exit 1
    fi
}

# 检查 Python 版本是否满足要求
check_python_version() {
    local python_cmd=$1
    if command -v "$python_cmd" &> /dev/null; then
        local version=$("$python_cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        local major=$(echo "$version" | cut -d. -f1)
        local minor=$(echo "$version" | cut -d. -f2)
        
        if [[ "$major" -ge "$MIN_PYTHON_MAJOR" ]] && [[ "$minor" -ge "$MIN_PYTHON_MINOR" ]]; then
            echo "$version"
            return 0
        fi
    fi
    return 1
}

# 查找可用的 Python
find_python() {
    print_info "检查 Python 版本..."
    
    # 按优先级检查不同的 Python 命令
    local python_commands=("python3.12" "python3.11" "python3.10" "python3")
    
    for cmd in "${python_commands[@]}"; do
        local version=$(check_python_version "$cmd")
        if [[ -n "$version" ]]; then
            PYTHON_CMD="$cmd"
            print_info "找到 Python: $cmd (版本 $version)"
            return 0
        fi
    done
    
    return 1
}

# 获取系统信息
get_os_info() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS_ID="$ID"
        OS_VERSION="$VERSION_ID"
        OS_CODENAME="$VERSION_CODENAME"
    else
        OS_ID="unknown"
        OS_VERSION="unknown"
        OS_CODENAME="unknown"
    fi
}

# 安装系统依赖
install_system_deps() {
    print_step "安装系统依赖..."
    
    get_os_info
    print_info "检测到系统: $OS_ID $OS_VERSION ($OS_CODENAME)"
    
    # 更新包列表
    print_info "更新系统包列表..."
    apt-get update -qq
    
    # 安装基础依赖
    print_info "安装基础工具..."
    apt-get install -y -qq \
        curl \
        wget \
        git \
        build-essential \
        libffi-dev \
        libssl-dev \
        ca-certificates \
        gnupg \
        2>/dev/null || true
    
    # 检查是否已有合适的 Python
    if find_python; then
        print_info "系统已有满足要求的 Python: $PYTHON_CMD"
    else
        print_warn "系统 Python 版本不满足要求 (需要 >= 3.10)"
        print_info "尝试安装 Python..."
        install_python
    fi
    
    # 安装 Python venv 和 pip
    install_python_packages
    
    print_info "系统依赖安装完成"
}

# 安装 Python
install_python() {
    get_os_info
    
    case "$OS_ID" in
        ubuntu)
            install_python_ubuntu
            ;;
        debian)
            install_python_debian
            ;;
        *)
            print_error "不支持的操作系统: $OS_ID"
            print_error "请手动安装 Python 3.10+"
            exit 1
            ;;
    esac
}

# Ubuntu 安装 Python
install_python_ubuntu() {
    print_info "添加 deadsnakes PPA..."
    
    # 安装 software-properties-common
    apt-get install -y -qq software-properties-common 2>/dev/null || true
    
    # 添加 deadsnakes PPA
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || {
        print_warn "无法添加 PPA，尝试直接安装..."
    }
    
    apt-get update -qq
    
    # 尝试安装 Python 3.11 或 3.10
    for version in "3.11" "3.10"; do
        print_info "尝试安装 Python $version..."
        if apt-get install -y -qq "python${version}" "python${version}-venv" "python${version}-dev" 2>/dev/null; then
            PYTHON_CMD="python${version}"
            print_info "Python $version 安装成功"
            return 0
        fi
    done
    
    print_error "无法安装 Python 3.10+"
    exit 1
}

# Debian 安装 Python
install_python_debian() {
    print_info "Debian 系统安装 Python..."
    
    # Debian 12 自带 Python 3.11
    # Debian 11 需要从 backports 安装
    
    case "$OS_VERSION" in
        11*)
            print_info "Debian 11: 添加 backports 源..."
            echo "deb http://deb.debian.org/debian bullseye-backports main" > /etc/apt/sources.list.d/backports.list
            apt-get update -qq
            apt-get install -y -qq -t bullseye-backports python3.10 python3.10-venv python3.10-dev 2>/dev/null || {
                # 如果 backports 失败，尝试编译安装
                print_warn "backports 安装失败，使用系统 Python..."
            }
            ;;
        12*)
            print_info "Debian 12: 安装默认 Python 3.11..."
            apt-get install -y -qq python3 python3-venv python3-dev 2>/dev/null || true
            ;;
    esac
    
    # 重新检查 Python
    if ! find_python; then
        print_error "无法安装满足要求的 Python"
        exit 1
    fi
}

# 安装 Python 包（venv, pip）
install_python_packages() {
    if [[ -z "$PYTHON_CMD" ]]; then
        if ! find_python; then
            print_error "找不到可用的 Python"
            exit 1
        fi
    fi
    
    print_info "安装 Python 虚拟环境支持..."
    
    # 获取 Python 版本号
    local py_version=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    
    # 尝试安装对应版本的 venv 和 dev 包
    apt-get install -y -qq \
        "python${py_version}-venv" \
        "python${py_version}-dev" \
        python3-pip \
        2>/dev/null || {
        # 如果特定版本包不存在，尝试通用包
        apt-get install -y -qq \
            python3-venv \
            python3-dev \
            python3-pip \
            2>/dev/null || true
    }
    
    # 验证 venv 可用
    if ! "$PYTHON_CMD" -m venv --help &>/dev/null; then
        print_error "Python venv 模块不可用"
        print_error "请手动安装: apt-get install python3-venv"
        exit 1
    fi
    
    print_info "Python 环境配置完成: $PYTHON_CMD"
}

# 创建用户和目录
create_user_and_dirs() {
    print_step "创建应用用户和目录..."
    
    # 创建用户（如果不存在）
    if ! id "$APP_USER" &>/dev/null; then
        useradd --system --shell /bin/false --home-dir "$INSTALL_DIR" --create-home "$APP_USER" || {
            # 如果 --create-home 失败，尝试不带该选项
            useradd --system --shell /bin/false --home-dir "$INSTALL_DIR" "$APP_USER" || true
        }
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
    print_step "安装应用..."
    
    # 获取脚本所在目录（项目根目录）
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    
    # 检查源文件是否存在
    if [[ ! -d "$SCRIPT_DIR/src" ]]; then
        print_error "找不到源代码目录: $SCRIPT_DIR/src"
        exit 1
    fi
    
    if [[ ! -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        print_error "找不到 pyproject.toml: $SCRIPT_DIR/pyproject.toml"
        exit 1
    fi
    
    # 复制项目文件
    print_info "复制项目文件到 $INSTALL_DIR..."
    cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
    
    # 复制脚本
    mkdir -p "$INSTALL_DIR/scripts"
    cp "$SCRIPT_DIR/scripts/"*.sh "$INSTALL_DIR/scripts/" 2>/dev/null || true
    chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true
    
    # 创建虚拟环境
    print_info "创建 Python 虚拟环境..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    
    # 升级 pip
    print_info "升级 pip..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip --quiet
    
    # 安装依赖
    print_info "安装 Python 依赖（这可能需要几分钟）..."
    "$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" --quiet || {
        print_warn "静默安装失败，显示详细输出..."
        "$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"
    }
    
    # 验证安装
    if "$VENV_DIR/bin/python" -c "import deribit_mcp" 2>/dev/null; then
        print_info "应用安装成功"
    else
        print_error "应用安装验证失败"
        exit 1
    fi
}

# 创建配置文件
create_config() {
    print_step "创建配置文件..."
    
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
    print_step "创建 systemd 服务..."
    
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
StartLimitBurst=5

# 超时设置
TimeoutStartSec=30
TimeoutStopSec=30

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

    print_info "systemd 服务创建完成"
}

# 创建日志轮转配置
create_logrotate() {
    print_step "配置日志轮转..."
    
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
    print_step "设置文件权限..."
    
    chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"
    chown -R "$APP_USER:$APP_GROUP" "$LOG_DIR"
    chown -R root:"$APP_GROUP" "$CONFIG_DIR"
    chmod 750 "$CONFIG_DIR"
    
    print_info "权限设置完成"
}

# 启动服务
start_service() {
    print_step "启动服务..."
    
    systemctl daemon-reload
    systemctl enable deribit-mcp
    systemctl start deribit-mcp
    
    # 等待服务启动
    print_info "等待服务启动..."
    sleep 3
    
    # 检查服务状态
    if systemctl is-active --quiet deribit-mcp; then
        print_info "服务启动成功!"
        
        # 尝试健康检查
        sleep 2
        if curl -s --connect-timeout 5 http://localhost:8000/health >/dev/null 2>&1; then
            print_info "健康检查通过!"
        else
            print_warn "健康检查未响应，服务可能仍在初始化..."
        fi
    else
        print_error "服务启动失败，请检查日志:"
        print_error "  journalctl -u deribit-mcp -n 50"
        systemctl status deribit-mcp --no-pager || true
        exit 1
    fi
}

# 打印安装完成信息
print_completion() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}✓ Deribit MCP Server 安装完成!${NC}"
    echo "=============================================="
    echo ""
    echo "安装信息:"
    echo "  Python:     $PYTHON_CMD"
    echo "  安装目录:   $INSTALL_DIR"
    echo "  配置文件:   $CONFIG_DIR/config.env"
    echo "  日志目录:   $LOG_DIR"
    echo ""
    echo "常用命令:"
    echo "  查看状态:   sudo systemctl status deribit-mcp"
    echo "  查看日志:   sudo journalctl -u deribit-mcp -f"
    echo "  重启服务:   sudo systemctl restart deribit-mcp"
    echo "  停止服务:   sudo systemctl stop deribit-mcp"
    echo "  编辑配置:   sudo nano $CONFIG_DIR/config.env"
    echo ""
    echo "API 端点:"
    echo "  健康检查:   http://localhost:8000/health"
    echo "  工具列表:   http://localhost:8000/tools"
    echo "  SSE 连接:   http://localhost:8000/sse"
    echo ""
    echo -e "${YELLOW}⚠ 重要: 请编辑配置文件设置 API 凭证${NC}"
    echo "  sudo nano $CONFIG_DIR/config.env"
    echo "  sudo systemctl restart deribit-mcp"
    echo ""
}

# 主函数
main() {
    echo "=============================================="
    echo "Deribit MCP Server - Ubuntu/Debian 安装脚本"
    echo "=============================================="
    echo ""
    
    check_root
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
