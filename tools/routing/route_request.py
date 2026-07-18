#!/usr/bin/env python3
"""
route_request.py — 多路由语义向量（稳定版）

设计原则: 框架是逻辑, 不是数据. 关键词和标签集定义后基本不动.

Layer 1: HARD_KEYWORDS → 覆盖最明确、零歧义的表达 (0ms)
Layer 2: LLM 语义标签 → 标签集固定, 利用 LLM 自身语义理解 (~0.7s 首次, 缓存后 0ms)
Layer 3: 兜底 A → 记日志, 不自动挖掘

输出: list[str], 多路由向量. routes[0] 为核心意图(primary), 其余为语义信号.
  例: "安排陈红洁排查故障" → ["H", "G", "C"]
      H = 任务分配 (primary), G = 涉及排班 (signal), C = 需要排查分析 (signal)

路由标签 (与 AGENTS.md / wrapper.py 对齐):
  A = 闲聊/兜底   B = 总结汇报   C = 分析排查
  D = 制度规范    E = 台账报表   F = 防汛安全
  G = 排班考勤    H = 任务分配   I = 知识学习
"""

from datetime import datetime
from pathlib import Path
from routing.llm_tags import extract_tags
from routing.entity_resolver import resolve_entities, resolve_entities_detailed

# ═══════════════ Layer 1: 初始关键词 ═══════════════
# 仅覆盖最明确、无歧义的表达。模糊或交叉表达交给 Layer 2。

HARD_KEYWORDS = {
    "G": ["请假",    "排班",    "考勤",    "值班",    "调休",    "加班"],
    "F": ["暴雨",    "台风",    "防汛",    "积水",    "排水",    "塌方",    "渗漏",    "边坡"],
    "E": ["台账",    "报表",    "归档",    "日志"],
    "D": ["制度",    "规范",    "操作规程", "灭火器",  "应急预案", "标准"],
    "C": ["根因",    "诊断",    "分析原因"],
    "B": ["总结",    "周报",    "日报",    "月报",    "复盘"],
    "H": ["安排",    "分配",    "派谁去",  "安排谁",  "让谁负责"],
    "I": ["学习",    "培训",    "资料",    "什么是",  "定义"],
}

# ═══════════════ Layer 2: 语义标签集 ═══════════════
# 每个路由对应的核心语义域。定义后不主动扩充。

ROUTE_TAGS = {
    "G": {"排班",    "考勤",    "请假",    "值班",    "出勤"},
    "F": {"防汛",    "排水",    "暴雨",    "台风",    "渗漏",    "积水",    "边坡",    "应急"},
    "E": {"台账",    "报表",    "归档",    "日志",    "统计"},
    "D": {"制度",    "规范",    "标准",    "流程",    "消防",    "合规"},
    "C": {"故障",    "排查",    "诊断",    "分析",    "根因",    "方案",    "修复",    "检查",    "安全"},
    "B": {"总结",    "汇报",    "回顾",    "周报",    "复盘",    "报告"},
    "H": {"任务",    "安排",    "分配",    "调度",    "分工"},
    "I": {"学习",    "培训",    "知识",    "资料",    "术语"},
}

ROUTE_PRIORITY = ["E", "G", "I", "F", "D", "C", "B", "H"]
FALLBACK_ROUTE = "A"

# 未知日志 (仅记录, 不自动挖掘)
UNKNOWNS_LOG = Path(__file__).resolve().parent.parent / "logs" / "unknowns.log"


def _route_single(text: str) -> str:
    for route in ROUTE_PRIORITY:
        for kw in HARD_KEYWORDS.get(route, []):
            if kw in text:
                return route
    tags = extract_tags(text)
    if tags:
        for route in ROUTE_PRIORITY:
            tag_set = ROUTE_TAGS.get(route, set())
            if any(tag in tag_set for tag in tags):
                return route
    return FALLBACK_ROUTE


def _collect_layer1(text: str) -> list[str]:
    matches = []
    for route in ROUTE_PRIORITY:
        for kw in HARD_KEYWORDS.get(route, []):
            if kw in text:
                matches.append(route)
                break
    return matches


def _collect_layer2(tags: list[str], exclude: set[str]) -> list[str]:
    if not tags:
        return []
    matches = []
    for route in ROUTE_PRIORITY:
        if route in exclude:
            continue
        tag_set = ROUTE_TAGS.get(route, set())
        if any(tag in tag_set for tag in tags):
            matches.append(route)
    return matches


def route_request(text: str) -> list[str]:
    text = text.strip()
    primary = _route_single(text)

    l1 = _collect_layer1(text)

    seen = {primary}
    result = [primary]

    for route in l1:
        if route not in seen:
            result.append(route)
            seen.add(route)

    l1_signal_count = sum(1 for r in result if r != primary)
    if l1_signal_count == 0 and primary != FALLBACK_ROUTE:
        tags = extract_tags(text)
        if tags:
            for route in ROUTE_PRIORITY:
                if route in seen:
                    continue
                tag_set = ROUTE_TAGS.get(route, set())
                if any(tag in tag_set for tag in tags):
                    result.append(route)
                    seen.add(route)

    if primary != FALLBACK_ROUTE:
        entity = resolve_entities(text)
        for route in entity["routes"]:
            if route not in seen:
                result.append(route)
                seen.add(route)

    if primary == FALLBACK_ROUTE:
        _log_unknown(text)

    return result


def route_request_detailed(text: str) -> dict:
    routes = route_request(text)
    entity = resolve_entities_detailed(text)

    pending_hints = []
    for e in entity["pending_entities"]:
        suggestion = e.get("role", "")
        if suggestion and suggestion != "未知":
            hint = f"{e['name']}可能{suggestion}"
        else:
            hint = f"{e['name']}可能有变化"
        pending_hints.append({
            "entity": e["name"],
            "route_hint": e.get("route_hint", []),
            "confidence": e.get("confidence", 0.5),
            "suggestion": hint,
        })

    return {
        "routes": routes,
        "pending_hints": pending_hints,
    }


def _log_unknown(text: str):
    if not text:
        return
    try:
        UNKNOWNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(UNKNOWNS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {text}\n")
    except Exception:
        pass
