#!/usr/bin/env python3
"""
llm_tags.py — 语义标签提取器
职责单一：给定文本，返回核心语义标签列表。与路由逻辑完全解耦。
首次调用可能调 LLM，后续命中内存缓存。
LLM 不可用时返回空列表，不抛异常。
"""

import json
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(TOOLS_DIR))

from reasoning.llm_client import call as _llm_call

# ── cache ──
CACHE_MAX = 500
_semantic_cache: dict[str, list[str]] = {}


def _cache_get(text: str) -> list[str] | None:
    return _semantic_cache.get(text)


def _cache_set(text: str, tags: list[str]):
    if len(_semantic_cache) >= CACHE_MAX:
        remove_count = CACHE_MAX // 2
        for key in list(_semantic_cache.keys())[:remove_count]:
            del _semantic_cache[key]
    _semantic_cache[text] = tags


# ── extract ──

def extract_tags(text: str) -> list[str]:
    """提取语义标签。首次调 LLM，后续命中缓存。"""
    cached = _cache_get(text)
    if cached is not None:
        return cached

    prompt = f"""提取以下工地管理输入的核心语义标签（2-4个词），只返回 JSON 字符串数组。只用下面列出的标签词。

输入：{text}

可用标签及适用场景:
- "排班" "考勤" → 请假、值班、排班、调休
- "防汛" "排水" "暴雨" "漏水" → 雨水、积水、防汛相关
- "台账" "归档" "报表" → 文档、记录、报表整理
- "制度" "规范" "消防" → 安全制度、操作规程、灭火器、标准查询
- "排查" "故障" "分析" "检查" "安全" → 故障排查、安全问题诊断、原因分析
- "总结" "汇报" "周报" → 工作总结、汇报、复盘
- "安排" "分配" → 明确指派某人做某事（含"安排""分配""让谁""派谁"等委派词）
- "学习" "培训" "知识" → 查询知识、学习资料、术语解释
- "情绪" → 心情、压力、疲劳、情绪倾诉

只返回 JSON 数组:"""

    try:
        raw = _llm_call(prompt, max_tokens=60, temperature=0.0, timeout=3.0)
    except Exception:
        _cache_set(text, [])
        return []

    if raw is None or (isinstance(raw, dict) and "error" in raw):
        _cache_set(text, [])
        return []

    raw_str = str(raw).strip()
    if not raw_str:
        _cache_set(text, [])
        return []

    try:
        start = raw_str.find("[")
        end = raw_str.rfind("]") + 1
        if start != -1 and end > start:
            tags = json.loads(raw_str[start:end])
            if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
                _cache_set(text, tags)
                return tags
    except json.JSONDecodeError:
        pass

    _cache_set(text, [])
    return []
