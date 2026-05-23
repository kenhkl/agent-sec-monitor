#!/bin/bash
# deploy.sh — AI Agent 安全监控每日部署脚本
# 用法: ./deploy.sh
# 配合 cron 使用:
#   0 5 * * * cd /home/hkl/github/agent-sec-monitor && bash deploy.sh >> logs/deploy.log 2>&1
#   0 12 * * * cd /home/hkl/github/agent-sec-monitor && bash deploy.sh >> logs/deploy.log 2>&1
#   0 22 * * * cd /home/hkl/github/agent-sec-monitor && bash deploy.sh >> logs/deploy.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 配置（可在 config.ini 的 [Deploy] 段中覆盖） ──
MAX_PIPELINE_RETRIES=3        # 整个 pipeline 最大重试次数
LLM_ANALYSIS_MIN_RATIO=0.8     # LLM 分析覆盖率最低阈值（低于此值视为分析失败）
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"   # 告警 Webhook URL（企业微信/钉钉/飞书）
COS_BUCKET="${COS_BUCKET:-}"                 # COS 存储桶名
COS_REGION="${COS_REGION:-ap-shanghai}"      # COS 区域

# 尝试从 config.ini 读取配置（如有）
CONFIG_FILE="$SCRIPT_DIR/config.ini"
if [ -f "$CONFIG_FILE" ]; then
    # 简易 INI 解析
    parse_ini_val() {
        local section="$1" key="$2"
        awk -F '=' -v sec="[$section]" -v k="$key" '
            $0 ~ /^\[/ { in_sec=($0 == sec) }
            in_sec && $1 ~ /^[[:space:]]*'"$key"'[[:space:]]*$/ {
                val=$2; sub(/^[[:space:]]+/, "", val); sub(/[[:space:]]+$/, "", val); print val
            }
        ' "$CONFIG_FILE"
    }
    PIPELINE_RETRIES_CFG=$(parse_ini_val "Deploy" "max_pipeline_retries" || echo "")
    [ -n "$PIPELINE_RETRIES_CFG" ] && MAX_PIPELINE_RETRIES="$PIPELINE_RETRIES_CFG"
    MIN_RATIO_CFG=$(parse_ini_val "Deploy" "llm_analysis_min_ratio" || echo "")
    [ -n "$MIN_RATIO_CFG" ] && LLM_ANALYSIS_MIN_RATIO="$MIN_RATIO_CFG"
    WEBHOOK_CFG=$(parse_ini_val "Deploy" "alert_webhook_url" || echo "")
    [ -n "$WEBHOOK_CFG" ] && ALERT_WEBHOOK_URL="$WEBHOOK_CFG"
    BUCKET_CFG=$(parse_ini_val "COS" "bucket" || echo "")
    [ -n "$BUCKET_CFG" ] && COS_BUCKET="$BUCKET_CFG"
    REGION_CFG=$(parse_ini_val "COS" "region" || echo "")
    [ -n "$REGION_CFG" ] && COS_REGION="$REGION_CFG"
fi

# ── 日志 ──
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/deploy.log"
ALERT_LOG="$LOG_DIR/alert.log"

log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $*" | tee -a "$LOG_FILE"
}

# ── 告警 ──
# 发送 Webhook 通知（支持企业微信机器人 / 钉钉机器人 / 飞书机器人）
send_alert() {
    local title="$1" content="$2"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')

    echo "[$ts] 🔔 ALERT: $title — $content" >> "$ALERT_LOG"

    if [ -z "$ALERT_WEBHOOK_URL" ]; then
        log "⚠️  未配置 ALERT_WEBHOOK_URL，跳过告警推送。"
        log "   请在 config.ini [Deploy] 段中设置 alert_webhook_url"
        log "   企业微信机器人示例: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
        log "   钉钉机器人示例:   https://oapi.dingtalk.com/robot/send?access_token=xxx"
        return
    fi

    local msg
    msg=$(cat <<EOF
{
    "msgtype": "text",
    "text": {
        "content": "【Agent 安全监控】${title}\n时间: ${ts}\n${content}"
    }
}
EOF
)
    curl -s -X POST "$ALERT_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "$msg" > /dev/null 2>&1 || true
}

# ── 依赖检查 ──
if ! command -v python3 &>/dev/null; then
    log "❌ python3 未找到，退出"
    send_alert "部署失败" "python3 未安装或不在 PATH 中"
    exit 1
fi

if ! command -v coscmd &>/dev/null; then
    log "⚠️  coscmd 未安装，将跳过 COS 上传"
    COSCMD_MISSING=true
else
    COSCMD_MISSING=false
fi

# ── 激活 Conda 环境 ──
if [ -n "${CONDA_PREFIX:-}" ]; then
    conda_base="$(conda info --base 2>/dev/null || echo '')"
    if [ -n "$conda_base" ] && [ -f "$conda_base/etc/profile.d/conda.sh" ]; then
        source "$conda_base/etc/profile.d/conda.sh"
        conda activate "$(basename "$CONDA_PREFIX")" 2>/dev/null || true
    fi
fi

# ── 检查 LLM 分析质量 ──
# 返回值: echo 输出分析覆盖率（0-1 之间的小数），失败则输出 "parse_error"
check_llm_quality() {
    local json_file="$1"
    if [ ! -f "$json_file" ]; then
        echo "no_file"
        return
    fi

    python3 -c "
import json, sys
try:
    with open('$json_file', 'r', encoding='utf-8') as f:
        data = json.load(f)
    items = data.get('items', [])
    total = len(items)
    if total == 0:
        print('no_items')
        sys.exit(0)
    analyzed = sum(1 for item in items if item.get('llm_summary') and item['llm_summary'] != '[noise]')
    ratio = analyzed / total if total > 0 else 0
    print(f'{ratio:.4f}')
except Exception as e:
    print('parse_error', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || echo "parse_error"
}

# ── 检查是否有 LLM API Key ──
has_llm_key() {
    python3 -c "
import configparser, os
cfg = configparser.ConfigParser()
cfg.read('$CONFIG_FILE')
key = cfg.get('LLM', 'api_key', fallback='') or os.environ.get('LLM_API_KEY', '')
print('yes' if key.strip() else 'no')
"
}

# ── 主流程 ──
TODAY=$(date '+%Y-%m-%d')
JSON_FILE="data/${TODAY}.json"
JS_FILE="data/${TODAY}.js"

log "=============================================="
log "开始执行每日扫描部署"
log "日期: $TODAY"
log "Pipeline 最大重试次数: $MAX_PIPELINE_RETRIES"
log "LLM 分析最低覆盖率: $LLM_ANALYSIS_MIN_RATIO"
log "COS 存储桶: ${COS_BUCKET:-未配置}"
log "告警 Webhook: ${ALERT_WEBHOOK_URL:+已配置}${ALERT_WEBHOOK_URL:-未配置}"

LLM_KEY_STATUS=$(has_llm_key || echo "no")
if [ "$LLM_KEY_STATUS" = "no" ]; then
    log "⚠️  LLM API Key 未配置，跳过分析质量检查，直接采集后上传"
fi

# ── 阶段一：爬取 + 分析（带重试） ──
CRAWL_SUCCESS=false
CRAWL_ATTEMPT=1
LAST_ERROR=""

while [ "$CRAWL_ATTEMPT" -le "$MAX_PIPELINE_RETRIES" ]; do
    log ""
    log "── 第 $CRAWL_ATTEMPT/$MAX_PIPELINE_RETRIES 次尝试 ──"

    # 执行 crawl
    log ">>> 运行 crawl.py (attempt $CRAWL_ATTEMPT)"
    CRAWL_LOG=$(mktemp /tmp/crawl_XXXXXX.log)
    if python3 crawl.py > "$CRAWL_LOG" 2>&1; then
        cat "$CRAWL_LOG" | tee -a "$LOG_FILE"
        log "✅ crawl.py 执行成功"
    else
        cat "$CRAWL_LOG" | tee -a "$LOG_FILE"
        log "❌ crawl.py 执行失败"
        LAST_ERROR="crawl.py 非零退出"
        rm -f "$CRAWL_LOG"
        CRAWL_ATTEMPT=$((CRAWL_ATTEMPT + 1))
        if [ "$CRAWL_ATTEMPT" -le "$MAX_PIPELINE_RETRIES" ]; then
            WAIT=$((30 * CRAWL_ATTEMPT))
            log "⏳ 等待 ${WAIT}s 后重试..."
            sleep "$WAIT"
        fi
        continue
    fi
    rm -f "$CRAWL_LOG"

    # 检查数据文件是否生成
    if [ ! -f "$JSON_FILE" ]; then
        log "❌ 数据文件未生成: $JSON_FILE"
        LAST_ERROR="数据文件未生成"
        CRAWL_ATTEMPT=$((CRAWL_ATTEMPT + 1))
        if [ "$CRAWL_ATTEMPT" -le "$MAX_PIPELINE_RETRIES" ]; then
            WAIT=$((30 * CRAWL_ATTEMPT))
            log "⏳ 等待 ${WAIT}s 后重试..."
            sleep "$WAIT"
        fi
        continue
    fi

    FILE_SIZE=$(wc -c < "$JSON_FILE" | tr -d ' ')
    ITEM_COUNT=$(python3 -c "import json; d=json.load(open('$JSON_FILE')); print(len(d.get('items',[])))" 2>/dev/null || echo "0")
    log "📄 数据文件已生成: $JSON_FILE (${FILE_SIZE} bytes, ${ITEM_COUNT} 条)"

    # 没有 LLM Key，说明不需要分析，直接成功
    if [ "$LLM_KEY_STATUS" = "no" ]; then
        log "ℹ️  无需 LLM 分析，采集成功"
        CRAWL_SUCCESS=true
        break
    fi

    # 检查 LLM 分析质量
    QUALITY=$(check_llm_quality "$JSON_FILE")
    log "📊 LLM 分析覆盖率: $QUALITY"

    if [ "$QUALITY" = "parse_error" ] || [ "$QUALITY" = "no_file" ]; then
        log "❌ 无法解析数据文件质量"
        LAST_ERROR="数据文件解析失败"
    elif [ "$QUALITY" = "no_items" ]; then
        log "ℹ️  当日无数据条目，视为成功"
        CRAWL_SUCCESS=true
        break
    else
        # quality 是一个 0-1 的小数
        if awk "BEGIN {exit !($QUALITY < $LLM_ANALYSIS_MIN_RATIO)}"; then
            log "⚠️  分析覆盖率 $QUALITY 低于阈值 $LLM_ANALYSIS_MIN_RATIO"
            LAST_ERROR="LLM 分析覆盖率不足: $QUALITY < $LLM_ANALYSIS_MIN_RATIO"

            # 全量重试: 使用 --force 重新分析
            if [ "$CRAWL_ATTEMPT" -lt "$MAX_PIPELINE_RETRIES" ]; then
                CRAWL_ATTEMPT=$((CRAWL_ATTEMPT + 1))
                WAIT=$((60 * CRAWL_ATTEMPT))
                log "⏳ 将在下次尝试中使用 --force 重新全量分析，等待 ${WAIT}s..."
                sleep "$WAIT"
                continue
            fi
        else
            log "✅ 分析质量达标（$QUALITY >= $LLM_ANALYSIS_MIN_RATIO）"
            CRAWL_SUCCESS=true
            break
        fi
    fi

    CRAWL_ATTEMPT=$((CRAWL_ATTEMPT + 1))
    if [ "$CRAWL_ATTEMPT" -le "$MAX_PIPELINE_RETRIES" ]; then
        WAIT=$((60 * CRAWL_ATTEMPT))
        log "⏳ 等待 ${WAIT}s 后重试..."
        sleep "$WAIT"
    fi
done

# ── 重试耗尽，告警 ──
if [ "$CRAWL_SUCCESS" != true ]; then
    log "❌ 已重试 $MAX_PIPELINE_RETRIES 次，仍未成功。"
    log "   最后错误: $LAST_ERROR"

    send_alert "采集/分析失败（已重试${MAX_PIPELINE_RETRIES}次）" \
        "日期: $TODAY\n最后错误: $LAST_ERROR\n请检查 LLM API 配置、网络连接或查看日志: $LOG_FILE"

    # 如果数据文件存在且分析质量勉强可用，仍然上传（降级服务）
    if [ -f "$JSON_FILE" ]; then
        QUALITY_FALLBACK=$(check_llm_quality "$JSON_FILE" || echo "0")
        if [ "$QUALITY_FALLBACK" != "parse_error" ] && [ "$QUALITY_FALLBACK" != "no_file" ] && [ "$QUALITY_FALLBACK" != "no_items" ]; then
            if awk "BEGIN {exit !($QUALITY_FALLBACK >= 0.3)}"; then
                log "⚠️  降级: 分析质量仅 $QUALITY_FALLBACK，但仍上传已有数据"
                CRAWL_SUCCESS="degraded"
            fi
        fi
    fi

    if [ "$CRAWL_SUCCESS" != "degraded" ]; then
        exit 1
    fi
fi

log ""

# ── 阶段二：COS 上传 ──
if [ "$COSCMD_MISSING" = true ]; then
    log "⚠️  跳过 COS 上传（coscmd 未安装）"
    log "    安装方法: pip install coscmd"
    log "    配置方法: coscmd config -a <SecretId> -s <SecretKey> -b <BucketName> -r <Region>"
else
    COS_UPLOAD_OK=true

    log ">>> 上传 data/ 目录到 COS"
    if coscmd upload -r data/ data/ 2>&1 | tee -a "$LOG_FILE"; then
        log "✅ data/ 上传成功"
    else
        log "⚠️  data/ 上传失败，重试一次..."
        sleep 10
        if coscmd upload -r data/ data/ 2>&1 | tee -a "$LOG_FILE"; then
            log "✅ data/ 上传成功（重试后）"
        else
            log "❌ data/ 上传失败"
            COS_UPLOAD_OK=false
        fi
    fi

    log ">>> 上传 index.html 到 COS"
    if coscmd upload index.html index.html 2>&1 | tee -a "$LOG_FILE"; then
        log "✅ index.html 上传成功"
    else
        log "⚠️  index.html 上传失败，重试一次..."
        sleep 10
        if coscmd upload index.html index.html 2>&1 | tee -a "$LOG_FILE"; then
            log "✅ index.html 上传成功（重试后）"
        else
            log "❌ index.html 上传失败"
            COS_UPLOAD_OK=false
        fi
    fi

    if [ "$COS_UPLOAD_OK" = false ]; then
        send_alert "COS 上传失败" \
            "日期: $TODAY\n请检查 coscmd 配置和网络连接"
    fi
fi

# ── 完成 ──
if [ "$CRAWL_SUCCESS" = "degraded" ]; then
    log "=============================================="
    log "部署完成（降级模式: 分析质量未达标但已上传可用数据）"
elif [ "$CRAWL_SUCCESS" = true ]; then
    log "=============================================="
    log "部署完成 ✅"
fi

# ── 清理旧文件（保留最近 30 天） ──
log ">>> 清理 30 天前的数据文件..."
find "$SCRIPT_DIR/data" -name "*.json" -mtime +30 -delete 2>/dev/null || true
find "$SCRIPT_DIR/data" -name "*.js" -mtime +30 -delete 2>/dev/null || true
log "清理完成"
