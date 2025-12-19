#!/bin/bash
# =============================================================================
# Deribit MCP Server - 健康检查脚本
# =============================================================================
# 可配合 cron 使用，实现定期检查和自动恢复
# 
# 添加到 cron:
#   sudo crontab -e
#   */5 * * * * /opt/deribit-mcp/scripts/healthcheck.sh >> /var/log/deribit-mcp/healthcheck.log 2>&1
# =============================================================================

set -e

# 配置
HEALTH_URL="http://localhost:8000/health"
SERVICE_NAME="deribit-mcp"
MAX_RETRIES=3
RETRY_DELAY=5
LOG_DATE=$(date '+%Y-%m-%d %H:%M:%S')

log_info() {
    echo "[$LOG_DATE] [INFO] $1"
}

log_error() {
    echo "[$LOG_DATE] [ERROR] $1"
}

log_warn() {
    echo "[$LOG_DATE] [WARN] $1"
}

# 检查服务是否运行
check_service() {
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        return 0
    else
        return 1
    fi
}

# 检查 HTTP 健康端点
check_http_health() {
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$HEALTH_URL" 2>/dev/null || echo "000")
    
    if [[ "$response" == "200" ]]; then
        return 0
    else
        return 1
    fi
}

# 重启服务
restart_service() {
    log_warn "尝试重启服务..."
    systemctl restart "$SERVICE_NAME"
    sleep 5
    
    if check_service && check_http_health; then
        log_info "服务重启成功"
        return 0
    else
        log_error "服务重启后仍不健康"
        return 1
    fi
}

# 主检查逻辑
main() {
    # 检查服务状态
    if ! check_service; then
        log_error "服务未运行"
        restart_service
        exit $?
    fi
    
    # 检查 HTTP 健康
    local retry=0
    while [[ $retry -lt $MAX_RETRIES ]]; do
        if check_http_health; then
            if [[ $retry -eq 0 ]]; then
                log_info "健康检查通过"
            else
                log_info "健康检查通过 (重试 $retry 次后)"
            fi
            exit 0
        fi
        
        retry=$((retry + 1))
        if [[ $retry -lt $MAX_RETRIES ]]; then
            log_warn "健康检查失败，等待 ${RETRY_DELAY}s 后重试 ($retry/$MAX_RETRIES)"
            sleep $RETRY_DELAY
        fi
    done
    
    # 所有重试都失败
    log_error "健康检查失败，尝试重启服务"
    restart_service
}

main "$@"
