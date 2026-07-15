#!/bin/bash
# 杀掉多余 opencode 进程，只保留最新的一个
pids=$(pgrep -x opencode | sort -n | head -n -1)
for pid in $pids; do
    kill "$pid" 2>/dev/null
    echo "[opencode-guard] 杀掉旧进程 PID=$pid"
done
