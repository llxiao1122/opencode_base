#!/bin/bash
# 杀掉多余 opencode 进程（保留 serve），只保留最新的一个
pids=$(pgrep -x opencode | sort -n | head -n -1)
for pid in $pids; do
    # 跳过 serve 进程
    if ps -p "$pid" -o args= 2>/dev/null | grep -q "opencode serve"; then
        continue
    fi
    kill "$pid" 2>/dev/null
    echo "[opencode-guard] 杀掉旧进程 PID=$pid"
done
