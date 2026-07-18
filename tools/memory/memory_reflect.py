#!/usr/bin/env python3
"""
memory_reflect.py — 反思回路 CLI 入口
供 cron / 手动调用:  python3 tools/memory/memory_reflect.py --since 7
"""

import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory.memory_core import MemoryCore

import argparse

parser = argparse.ArgumentParser(description="工班 AI 反思回路")
parser.add_argument("--since", type=int, default=7, help="扫描最近 N 天的记录")
args = parser.parse_args()

core = MemoryCore(root_path="/home/admin/opencode")
result = core.reflect(since_days=args.since)
print(json.dumps(result, ensure_ascii=False, indent=2))
