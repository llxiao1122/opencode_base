#!/bin/bash
# Telegram Opencode Bridge 启动脚本
# 自动检测脚本所在目录，避免硬编码路径

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/bot.pid"

# ── 前置检查：防止重复启动 ──
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "❌ Telegram Bridge 已在运行中 (PID $OLD_PID)。如需重启请先停止旧实例。"
        exit 1
    fi
    # PID 文件存在但进程已死 → 清理
    rm -f "$PID_FILE"
fi

# ── 检测 python3 ──
PYTHON=""
for cmd in python3 /usr/bin/python3 /Library/Developer/CommandLineTools/usr/bin/python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ 找不到 python3，请确认已安装 Python 3。"
    exit 1
fi

cd "$SCRIPT_DIR" || exit 1
nohup "$PYTHON" bot.py >> bot.log 2>&1 &
echo "✅ Telegram Bridge 已启动 (PID $!, python=$PYTHON, log=bot.log)"
