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

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_FILE = ROOT / "state" / "entity_index.json"

with open(INDEX_FILE, "r", encoding="utf-8") as f:
    _DATA = json.load(f)

CONFIRMED = _DATA.get("confirmed_entities", [])
PENDING   = _DATA.get("pending_entities", [])
ALL_ENTITIES = CONFIRMED + PENDING


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
    routes = []
    matched = []

    for item in ALL_ENTITIES:
        w = item.get("weight", 1.0)
        if w < min_weight:
            continue
        names = [item["name"]] + item.get("aliases", [])
        for name in names:
            if name in text:
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
