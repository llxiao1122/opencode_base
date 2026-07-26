"""
memory/pattern_miner.py — 从 event_recorder + tasks.json 提取模式并写入 observation_store.

纯统计，无 LLM。输出为自然语言观察，自动路由到对应人员文件。
每次运行覆盖更新，不追加。

用法:
   python3 -m skills.memory.pattern_miner
"""

import sys, json
from pathlib import Path
from collections import Counter
from datetime import datetime

from skills.shared.path import ensure_paths
ensure_paths()

from memory.event_recorder import list_events
from memory.observation_store import write as obs_write


def mine():
    events = list_events(limit=1000)

    person_total = Counter()
    person_as_executor = Counter()
    person_as_requester = Counter()
    requester_event_type = Counter()
    requester_event_type_with_dl = Counter()

    for e in events:
        actors = e.get("actors", [])
        if not actors:
            continue
        etype = e.get("event_type", "unknown")
        dl = e.get("deadline", "")
        for a in actors:
            if not isinstance(a, dict):
                continue
            name = a.get("name", "")
            pos = a.get("position", "")
            if not name:
                continue
            person_total[name] += 1
            if pos == "executor":
                person_as_executor[name] += 1
            elif pos == "requester":
                person_as_requester[name] += 1
                requester_event_type[(name, etype)] += 1
                if dl:
                    requester_event_type_with_dl[(name, etype)] += 1

    patterns = []

    for name, total in person_total.most_common(20):
        req = person_as_requester.get(name, 0)
        exe = person_as_executor.get(name, 0)
        parts = []
        if req:
            parts.append(f"发起{req}次")
        if exe:
            parts.append(f"被指派执行{exe}次")
        summary = f"{name} 参与 {total} 条事件" + ("，" + "、".join(parts) if parts else "")
        patterns.append(summary)

    for (name, etype), count in requester_event_type.most_common(10):
        dl_count = requester_event_type_with_dl.get((name, etype), 0)
        dl_note = f"（其中 {dl_count} 次带截止时间）" if dl_count else ""
        patterns.append(f"{name} 常发起 {etype} 类型{dl_note}，累计 {count} 次")

    etype_dist = Counter(e.get("event_type", "unknown") for e in events)
    total = sum(etype_dist.values())
    for etype, count in etype_dist.most_common():
        pct = count * 100 // total
        patterns.append(f"事件类型分布: {etype} {count} 次（{pct}%）")

    for pattern in patterns:
        obs_write(
            pattern,
            source="pattern_miner",
            obs_type="pattern",
            layer="pattern",
            confidence=0.8,
        )

    print(f"✅ 已写入 {len(patterns)} 条模式")
    return patterns


if __name__ == "__main__":
    patterns = mine()
    for p in patterns:
        print(f"  {p}")
