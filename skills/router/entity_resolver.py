"""
entity_resolver.py — 实体-路由信号桥接层
解析用户输入中的人名，返回路由信号。

数据源: state/entity_index.json
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
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_FILE = ROOT / "data" / "state" / "entity_index.json"

_CONFIRMED: Optional[list] = None
_PENDING: Optional[list] = None
_ALL: Optional[list] = None


def _load():
    global _CONFIRMED, _PENDING, _ALL
    if _ALL is not None:
        return
    if not INDEX_FILE.exists():
        _CONFIRMED, _PENDING, _ALL = [], [], []
        return
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    _CONFIRMED = data.get("confirmed_entities", [])
    _PENDING = data.get("pending_entities", [])
    _ALL = sorted(_CONFIRMED + _PENDING, key=lambda e: len(e.get("name", "")), reverse=True)


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

    return {
        "routes": list(dict.fromkeys(routes)),
        "entities": matched,
    }
