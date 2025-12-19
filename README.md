# Deribit MCP Server

🚀 **LLM-友好的 Deribit 衍生品数据 MCP Server**

专为交易系统设计，提供高质量、低 token 消耗的期权/波动率/资金费率/市场快照数据。

## ✨ 特性

- **极简输出**：每个 tool 返回 ≤2KB 紧凑 JSON（硬目标 5KB）
- **智能缓存**：双层 TTL 缓存（快速 1s / 慢速 30s）
- **限速保护**：Token Bucket 限速器，避免触发 API 限制
- **错误降级**：优雅处理超时/错误，返回可用的部分数据
- **安全优先**：密钥环境变量读取，自动日志脱敏
- **双模式部署**：支持 stdio（本地）和 HTTP/SSE（远程）

## 📦 安装

### 使用 uv（推荐）

```bash
# 克隆项目
git clone https://github.com/your-repo/deribit-mcp-server.git
cd deribit-mcp-server

# 安装依赖
uv sync

# 或者安装开发依赖
uv sync --dev
```

### 使用 pip

```bash
# 安装
pip install -e .

# 或者安装开发依赖
pip install -e ".[dev]"
```

## ⚙️ 配置

### 环境变量

创建 `.env` 文件或设置环境变量：

```bash
# 环境选择（prod/test），默认 prod
DERIBIT_ENV=prod

# Private API 开关，默认 false（只读模式）
DERIBIT_ENABLE_PRIVATE=false

# API 凭证（仅 Private API 需要）
DERIBIT_CLIENT_ID=YOUR_CLIENT_ID
DERIBIT_CLIENT_SECRET=YOUR_CLIENT_SECRET

# 网络设置
DERIBIT_TIMEOUT_S=10
DERIBIT_MAX_RPS=8

# 缓存 TTL（秒）
DERIBIT_CACHE_TTL_FAST=1.0   # ticker/orderbook
DERIBIT_CACHE_TTL_SLOW=30.0  # instruments/expirations

# 交易安全（默认 true = 只模拟不执行）
DERIBIT_DRY_RUN=true

# HTTP 服务器设置
DERIBIT_HOST=0.0.0.0
DERIBIT_PORT=8000
```

### 🔐 安全要求

⚠️ **重要安全提示**：

1. **永远不要** 将真实 API 密钥提交到代码仓库
2. 使用 `.env` 文件存储密钥，并将其添加到 `.gitignore`
3. 定期轮换 API 密钥
4. 生产环境使用环境变量而非文件

```bash
# 示例 .env 文件（使用占位符）
DERIBIT_CLIENT_ID=YOUR_CLIENT_ID
DERIBIT_CLIENT_SECRET=YOUR_CLIENT_SECRET
```

## 🚀 启动服务器

### 方式 1: stdio 模式（本地 MCP 客户端）

```bash
# 使用 uv
uv run deribit-mcp

# 或直接运行
python -m deribit_mcp.server
```

### 方式 2: HTTP/SSE 模式（远程部署）

```bash
# 使用 uv
uv run deribit-mcp-http

# 或直接运行
python -m deribit_mcp.http_server

# 自定义端口
DERIBIT_PORT=9000 python -m deribit_mcp.http_server
```

HTTP 服务器端点：
- `GET /health` - 健康检查
- `GET /tools` - 列出所有工具
- `POST /tools/call` - 调用工具
- `GET /sse` - SSE 连接（MCP 协议）
- `POST /mcp/message` - MCP 消息

## 🔧 MCP 客户端配置

### CherryStudio / Cursor 配置

```json
{
  "mcpServers": {
    "deribit": {
      "command": "uv",
      "args": ["run", "deribit-mcp"],
      "cwd": "/path/to/deribit-mcp-server",
      "env": {
        "DERIBIT_ENV": "prod",
        "DERIBIT_ENABLE_PRIVATE": "false",
        "DERIBIT_CLIENT_ID": "YOUR_CLIENT_ID",
        "DERIBIT_CLIENT_SECRET": "YOUR_CLIENT_SECRET"
      }
    }
  }
}
```

### 使用 Python 直接运行

```json
{
  "mcpServers": {
    "deribit": {
      "command": "python",
      "args": ["-m", "deribit_mcp.server"],
      "cwd": "/path/to/deribit-mcp-server",
      "env": {
        "DERIBIT_ENV": "prod"
      }
    }
  }
}
```

### HTTP/SSE 远程连接

```json
{
  "mcpServers": {
    "deribit": {
      "transport": "sse",
      "url": "http://your-server:8000/sse"
    }
  }
}
```

## 🛠️ 可用工具

### Public Tools（默认启用）

#### 1. `deribit_status`
检查 API 连通性和状态。

```json
// 调用
{}

// 返回（~100 bytes）
{"env":"prod","api_ok":true,"server_time_ms":1700000000000,"notes":[]}
```

#### 2. `deribit_instruments`
获取可用合约列表（最多 50 个，优先最近到期）。

```json
// 调用
{"currency": "BTC", "kind": "option"}

// 返回（~2KB）
{
  "count": 500,
  "instruments": [
    {"name":"BTC-28JUN24-70000-C","exp_ts":1719561600000,"strike":70000,"type":"call","tick":0.0001,"size":1}
  ],
  "notes": ["truncated_from:500", "nearest_3_expiries"]
}
```

#### 3. `deribit_ticker`
获取紧凑的市场快照。

```json
// 调用
{"instrument_name": "BTC-PERPETUAL"}

// 返回（~400 bytes）
{
  "inst": "BTC-PERPETUAL",
  "bid": 50000.0,
  "ask": 50001.0,
  "mid": 50000.5,
  "mark": 50000.25,
  "idx": 50000.0,
  "funding": 0.0001,
  "oi": 1000000,
  "vol_24h": 50000,
  "notes": []
}
```

#### 4. `deribit_orderbook_summary`
获取订单簿摘要（仅 top 5 档）。

```json
// 调用
{"instrument_name": "BTC-PERPETUAL", "depth": 20}

// 返回（~800 bytes）
{
  "inst": "BTC-PERPETUAL",
  "bid": 50000.0,
  "ask": 50001.0,
  "spread_pts": 1.0,
  "spread_bps": 2.0,
  "bids": [{"p":50000,"q":1.5}],
  "asks": [{"p":50001,"q":2.0}],
  "bid_depth": 100.5,
  "ask_depth": 95.3,
  "imbalance": 0.027,
  "notes": []
}
```

#### 5. `dvol_snapshot`
获取 DVOL（Deribit 波动率指数）快照。

```json
// 调用
{"currency": "BTC"}

// 返回（~150 bytes）
{
  "ccy": "BTC",
  "dvol": 80.5,
  "dvol_chg_24h": 2.5,
  "percentile": null,
  "ts": 1700000000000,
  "notes": []
}
```

#### 6. `options_surface_snapshot`
获取波动率曲面快照（ATM IV、Risk Reversal、Butterfly）。

```json
// 调用
{"currency": "BTC", "tenor_days": [7, 14, 30, 60]}

// 返回（~800 bytes）
{
  "ccy": "BTC",
  "spot": 50000.0,
  "tenors": [
    {"days":7,"atm_iv":0.82,"rr25":0.02,"fly25":0.01,"fwd":50100},
    {"days":14,"atm_iv":0.80,"rr25":0.015,"fly25":0.008,"fwd":50200}
  ],
  "confidence": 0.85,
  "ts": 1700000000000,
  "notes": []
}
```

#### 7. `expected_move_iv`
基于 IV 计算预期波动（1σ）。

```json
// 调用
{"currency": "BTC", "horizon_minutes": 60, "method": "dvol"}

// 返回（~350 bytes）
{
  "ccy": "BTC",
  "spot": 50000.0,
  "iv_used": 0.80,
  "iv_source": "dvol",
  "horizon_min": 60,
  "move_1s_pts": 427.5,
  "move_1s_bps": 85.5,
  "up_1s": 50427.5,
  "down_1s": 49572.5,
  "confidence": 0.95,
  "notes": ["dvol_raw:80"]
}
```

**公式说明**：
```
expected_move = spot × IV_annual × √(T_years)
where T_years = horizon_minutes / 525600

示例：
spot = 50000, IV = 80%, horizon = 60 min
move = 50000 × 0.80 × √(60/525600) ≈ 427.5 点
```

#### 8. `funding_snapshot`
获取永续合约资金费率快照。

```json
// 调用
{"currency": "BTC"}

// 返回（~400 bytes）
{
  "ccy": "BTC",
  "perp": "BTC-PERPETUAL",
  "rate": 0.0001,
  "rate_8h": 0.1095,
  "next_ts": 1700003600000,
  "history": [
    {"ts":1700000000000,"rate":0.0001}
  ],
  "notes": []
}
```

### Private Tools（需要 DERIBIT_ENABLE_PRIVATE=true）

#### P1. `account_summary`
获取账户摘要。

```json
{"currency": "BTC"}
```

#### P2. `positions`
获取持仓列表（最多 20 个）。

```json
{"currency": "BTC", "kind": "future"}
```

#### P3. `open_orders`
获取挂单列表（最多 20 个）。

```json
{"currency": "BTC"}
```

#### P4. `place_order`
下单（默认 DRY_RUN 模式）。

```json
{
  "instrument": "BTC-PERPETUAL",
  "side": "buy",
  "type": "limit",
  "amount": 0.1,
  "price": 50000
}
```

#### P5. `cancel_order`
取消订单。

```json
{"order_id": "12345"}
```

## 🧪 测试

```bash
# 运行所有测试
uv run pytest

# 运行测试并显示覆盖率
uv run pytest --cov=deribit_mcp --cov-report=term-missing

# 运行特定测试
uv run pytest tests/test_analytics.py -v
```

## 📁 项目结构

```
deribit-mcp-server/
├── pyproject.toml          # 项目配置
├── README.md               # 文档
├── .env.example            # 环境变量示例
├── src/
│   └── deribit_mcp/
│       ├── __init__.py     # 包初始化
│       ├── config.py       # 配置管理（pydantic-settings）
│       ├── client.py       # JSON-RPC 客户端（缓存/限速/重试）
│       ├── models.py       # Pydantic 数据模型
│       ├── analytics.py    # 分析计算（IV/expected move）
│       ├── tools.py        # MCP Tools 实现
│       ├── server.py       # stdio MCP 服务器
│       └── http_server.py  # HTTP/SSE 服务器
└── tests/
    ├── conftest.py         # 测试配置
    ├── test_analytics.py   # 分析模块测试
    ├── test_client.py      # 客户端测试
    └── test_tools.py       # Tools 测试
```

## 🔄 部署

### Ubuntu 服务器部署（推荐，带自动重启）

提供完整的安装脚本，支持 systemd 服务管理、自动重启和日志轮转。

#### 一键安装

```bash
# 克隆项目
git clone https://github.com/your-repo/deribit-mcp-server.git
cd deribit-mcp-server

# 运行安装脚本（需要 sudo）
sudo bash scripts/install.sh
```

#### 安装脚本功能

- ✅ 自动安装 Python 3.11+ 和依赖
- ✅ 创建专用系统用户（安全隔离）
- ✅ 配置 systemd 服务（后台运行）
- ✅ 自动重启（崩溃后 5 秒内重启）
- ✅ 日志轮转（保留 14 天）
- ✅ 资源限制（内存 512MB）

#### 安装后的目录结构

```
/opt/deribit-mcp/          # 应用目录
├── src/                   # 源代码
├── venv/                  # Python 虚拟环境
└── pyproject.toml

/etc/deribit-mcp/          # 配置目录
└── config.env             # 配置文件（编辑此文件）

/var/log/deribit-mcp/      # 日志目录
```

#### 服务管理命令

```bash
# 查看服务状态
sudo systemctl status deribit-mcp

# 查看实时日志
sudo journalctl -u deribit-mcp -f

# 重启服务
sudo systemctl restart deribit-mcp

# 停止服务
sudo systemctl stop deribit-mcp

# 启动服务
sudo systemctl start deribit-mcp

# 禁用开机自启
sudo systemctl disable deribit-mcp
```

#### 配置文件编辑

```bash
# 编辑配置
sudo nano /etc/deribit-mcp/config.env

# 修改后重启服务
sudo systemctl restart deribit-mcp
```

配置文件内容：

```bash
# 环境选择: prod 或 test
DERIBIT_ENV=prod

# Private API 开关
DERIBIT_ENABLE_PRIVATE=false

# API 凭证（替换为真实值）
DERIBIT_CLIENT_ID=YOUR_CLIENT_ID
DERIBIT_CLIENT_SECRET=YOUR_CLIENT_SECRET

# HTTP 服务器
DERIBIT_HOST=0.0.0.0
DERIBIT_PORT=8000
```

#### 健康检查与自动恢复

设置定时健康检查（可选）：

```bash
# 编辑 crontab
sudo crontab -e

# 添加以下行（每 5 分钟检查一次）
*/5 * * * * /opt/deribit-mcp/scripts/healthcheck.sh >> /var/log/deribit-mcp/healthcheck.log 2>&1
```

#### 更新应用

```bash
# 进入项目目录
cd /path/to/deribit-mcp-server
git pull

# 运行更新脚本
sudo bash scripts/update.sh
```

#### 卸载

```bash
sudo bash scripts/uninstall.sh
```

#### systemd 服务配置详解

服务文件位于 `/etc/systemd/system/deribit-mcp.service`：

```ini
[Unit]
Description=Deribit MCP Server (HTTP/SSE)
After=network-online.target

[Service]
Type=simple
User=deribit
Group=deribit

# 环境配置文件
EnvironmentFile=/etc/deribit-mcp/config.env

# 启动命令
ExecStart=/opt/deribit-mcp/venv/bin/python -m deribit_mcp.http_server

# 自动重启配置
Restart=always           # 总是重启
RestartSec=5            # 重启间隔 5 秒
StartLimitIntervalSec=60 # 60 秒内
StartLimitBurst=3        # 最多重启 3 次

# 资源限制
MemoryMax=512M
CPUQuota=100%

# 安全加固
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes

[Install]
WantedBy=multi-user.target
```

### Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install uv && uv sync

ENV DERIBIT_ENV=prod
ENV DERIBIT_HOST=0.0.0.0
ENV DERIBIT_PORT=8000

EXPOSE 8000

CMD ["uv", "run", "deribit-mcp-http"]
```

```bash
docker build -t deribit-mcp .
docker run -p 8000:8000 \
  -e DERIBIT_CLIENT_ID=YOUR_CLIENT_ID \
  -e DERIBIT_CLIENT_SECRET=YOUR_CLIENT_SECRET \
  deribit-mcp
```

### Render.com 部署

使用项目中的 `render.yaml`：

```yaml
services:
  - type: web
    name: deribit-mcp
    runtime: python
    buildCommand: pip install uv && uv sync
    startCommand: uv run deribit-mcp-http
    envVars:
      - key: DERIBIT_ENV
        value: prod
      - key: DERIBIT_CLIENT_ID
        sync: false
      - key: DERIBIT_CLIENT_SECRET
        sync: false
```

## 📊 性能目标

| 指标 | 目标值 |
|------|--------|
| 单个 Tool 输出大小 | ≤2KB（软目标），≤5KB（硬限制） |
| ticker 响应时间 | <200ms（含缓存） |
| 缓存命中率 | >80%（正常使用） |
| API 请求限速 | 8 RPS（可配置） |

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 许可证

MIT License

## ⚠️ 免责声明

本项目仅供学习和研究目的。使用本软件进行交易的风险由用户自行承担。请确保了解并遵守 Deribit 的服务条款和相关法规。
