"""
entity_resolver.py — 实体-路由信号桥接层
解析用户输入中的人名，返回路由信号。

数据源: worldview entities/*.md
  模块加载时一次性读入内存，不每次请求读盘。

返回结构:
  {
    "routes": ["G", ...],       # 命中的路由信号 (去重)
    "entities": [               # 命中的实体详情 (按 name 匹配)
      {"name": "王超", "weight": 1.0, "route_hint": ["G"], ...}
    ]
  }
"""

import json
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITIES_DIR = ROOT / "data" / "state" / "worldview" / "entities"
_WORLDVIEW_INDEX = ROOT / "data" / "state" / "worldview" / "index.json"

_CONFIG_PATH = Path(__file__).parent / "route_config.json"
_WV_TYPE_ROUTE = json.loads(_CONFIG_PATH.read_text(encoding="utf-8")).get("_WV_TYPE_ROUTE", {})

_ALL: Optional[list] = None

_RE_WEIGHT = re.compile(r"-\s+\*\*权重\*\*:\s*(\d+(?:\.\d+)?)")
_RE_ROUTE_HINT = re.compile(r"-\s+\*\*路由提示\*\*:\s*(.*)")
_RE_ALIAS = re.compile(r"-\s+\*\*别名\*\*:\s*(.*)")


def _load():
    global _ALL
    if _ALL is not None:
        return
    if not ENTITIES_DIR.exists():
        _ALL = []
        return
    items = []
    for f in sorted(ENTITIES_DIR.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        name = f.stem
        weight = 1.0
        route_hint = []
        aliases = []
        for line in content.splitlines():
            m = _RE_WEIGHT.match(line)
            if m:
                weight = float(m.group(1))
            m = _RE_ROUTE_HINT.match(line)
            if m:
                try:
                    route_hint = json.loads(m.group(1))
                except (json.JSONDecodeError, TypeError):
                    route_hint = []
            m = _RE_ALIAS.match(line)
            if m:
                raw = m.group(1).strip()
                aliases = [a.strip() for a in raw.split("、") if a.strip()]
        items.append({
            "name": name,
            "weight": weight,
            "route_hint": route_hint,
            "aliases": aliases,
        })
    _ALL = sorted(items, key=lambda e: len(e.get("name", "")), reverse=True)


def resolve_entities(text: str) -> dict:
    return _resolve(text, min_weight=0.7)


def resolve_entities_detailed(text: str) -> dict:
    confirmed   = _resolve(text, min_weight=0.7)
    pending_all = _resolve(text, min_weight=0.0)

    pending_routes = [r for r in pending_all["routes"] if r not in set(confirmed["routes"])]
    pending_entities = [
        e for e in pending_all["entities"]
        if 0.5 <= e.get("weight", 0.5) < 0.7
    ]

    return {
        "routes": confirmed["routes"],
        "entities": confirmed["entities"],
        "pending_routes": pending_routes,
        "pending_entities": pending_entities,
    }


def _resolve(text: str, min_weight: float) -> dict:
    _load()
    routes = []
    matched = []

    for item in _ALL:
        w = item.get("weight", 1.0)
        if w < min_weight:
            continue
        names = [item["name"]] + item.get("aliases", [])
        for name in names:
            if not name:
                continue
            idx = text.find(name)
            if idx == -1:
                continue
            if len(name) == 1:
                prev_char = text[idx - 1] if idx > 0 else ""
                next_char = text[idx + 1] if idx + 1 < len(text) else ""
                if prev_char and "\u4e00" <= prev_char <= "\u9fff":
                    continue
                if next_char and "\u4e00" <= next_char <= "\u9fff":
                    continue
            routes.extend(item.get("route_hint", []))
            matched.append({
                "name": item["name"],
                "weight": w,
                "route_hint": item.get("route_hint", []),
                "role": item.get("role", ""),
                "source": item.get("source", ""),
                "confidence": item.get("confidence"),
            })
            break

    # 子串匹配为空时，用 worldview 语义搜索兜底
    if not matched:
        try:
            from skills.memory.worldview import search as wv_search
            hits = wv_search(text, top_k=1)
            if hits and hits[0].get("score", 0) >= 0.6:
                h = hits[0]
                etype = h.get("type", "")
                matched.append({
                    "name": h["entity_id"],
                    "weight": 0.5,
                    "route_hint": [_WV_TYPE_ROUTE.get(etype, "knowledge_retrieve")] if etype else [],
                    "role": "",
                    "source": "worldview_semantic",
                    "confidence": h["score"],
                })
                if etype:
                    routes.append(_WV_TYPE_ROUTE.get(etype, "knowledge_retrieve"))
        except Exception:
            pass

    return {
        "routes": list(dict.fromkeys(routes)),
        "entities": matched,
    }
