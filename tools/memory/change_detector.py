"""
change_detector.py — 变化检测引擎

从用户输入中发现"可能发生的事实变化"，不直接修改 state。

检测类型 (Phase 1.2):
  1. 人员职责变化: 负责/接手/调整/转交/改管/分管/接管
  2. 人员状态变化: 离职/休假/调走/借调/辞职/退休

工作模式:
  CLI  detect  → 分析文本并追加 pending
  CLI  review  → 列出 pending，支持逐条确认/拒绝

置信度: 0.5~1.0 (base 0.5 + entity_in_index 0.2 + conflicts 0.15 + extra_keywords)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX = ROOT / "state" / "entity_index.json"
PENDING_FILE = ROOT / "state" / "_changes" / "pending.md"
CONFIRMED_FILE = ROOT / "state" / "_changes" / "confirmed.md"
REJECTED_FILE = ROOT / "state" / "_changes" / "rejected.md"

RESPONSIBILITY_KEYWORDS = ["负责", "接手", "调整", "转交", "改管", "分管", "接管"]
STATUS_KEYWORDS = ["离职", "休假", "调走", "借调", "辞职", "退休"]


def _load_entities():
    with open(ENTITY_INDEX, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("confirmed_entities", []) + data.get("pending_entities", [])


def _find_entities(text, entities):
    matched = []
    seen = set()
    sorted_entities = sorted(entities, key=lambda e: e.get("weight", 1.0), reverse=True)
    for item in sorted_entities:
        if item["name"] in seen:
            continue
        names = [item["name"]] + item.get("aliases", [])
        for name in names:
            if name in text:
                matched.append(item)
                seen.add(item["name"])
                break
    return matched


def _compute_confidence(entity_in_index, keyword_count, has_conflict):
    confidence = 0.5
    if entity_in_index:
        confidence += 0.2
    if has_conflict:
        confidence += 0.15
    if keyword_count > 1:
        confidence += min(0.3, (keyword_count - 1) * 0.1)
    return round(min(1.0, confidence), 2)


def _read_pending_ids():
    if not PENDING_FILE.exists():
        return set()
    content = PENDING_FILE.read_text(encoding="utf-8")
    return set(m.group(1) for m in re.finditer(r"^## (chg-\d+)", content, re.MULTILINE))


def _next_id(existing_ids):
    for i in range(1, 1000):
        cid = f"chg-{i:03d}"
        if cid not in existing_ids:
            return cid
    return f"chg-{int(datetime.now().timestamp()):06d}"


def _append_pending(change):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = f"""
## {change['id']}
- timestamp: {change['timestamp']}
- type: {change['type']}
- entity: {change['entity']}
- field: {change['field']}
- old_value: {change['old_value']}
- new_value: {change['new_value']}
- confidence: {change['confidence']}
- source: "{change['source_text']}"
- status: pending
"""
    with open(PENDING_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def _extract_context(text, entity_name, keyword):
    pattern = re.escape(entity_name) + r"[\s\S]*?" + re.escape(keyword)
    m = re.search(pattern, text)
    if m:
        start = max(0, m.start() - 10)
        end = min(len(text), m.end() + 20)
        return text[start:end]
    rev_pattern = re.escape(keyword) + r"[\s\S]*?" + re.escape(entity_name)
    m = re.search(rev_pattern, text)
    if m:
        start = max(0, m.start() - 10)
        end = min(len(text), m.end() + 20)
        return text[start:end]
    return text


def detect(user_input: str) -> list[dict]:
    entities = _load_entities()
    matched_entities = _find_entities(user_input, entities)
    if not matched_entities:
        return []

    existing_ids = _read_pending_ids()
    results = []

    for group in [
        (RESPONSIBILITY_KEYWORDS, "responsibility", "role"),
        (STATUS_KEYWORDS, "status", "status"),
    ]:
        keywords, ctype, field = group
        found_kws = [kw for kw in keywords if kw in user_input]
        if not found_kws:
            continue

        for entity in matched_entities:
            old_value = entity.get("role", "未知")
            ctx = _extract_context(user_input, entity["name"], found_kws[0])

            new_value = _guess_new_value(user_input, entity["name"], found_kws, ctype)
            has_conflict = (old_value != "未知" and new_value != old_value)

            confidence = _compute_confidence(
                entity_in_index=True,
                keyword_count=len(found_kws),
                has_conflict=has_conflict,
            )

            if confidence < 0.5:
                continue

            change_id = _next_id(existing_ids)
            existing_ids.add(change_id)

            change = {
                "id": change_id,
                "type": ctype,
                "entity": entity["name"],
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "confidence": confidence,
                "source_text": ctx,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            _append_pending(change)
            results.append(change)

    return results


def _guess_new_value(text, entity_name, keywords, ctype):
    if ctype == "responsibility":
        for kw in keywords:
            idx = text.find(kw)
            if idx < 0:
                continue
            after = text[idx + len(kw):].strip()
            if after:
                snippet = re.sub(r"[，。！？；、,\s]", "", after[:20])
                if snippet:
                    return f"{kw}{snippet}"
        return f"{kw}相关业务" if keywords else "职责调整"
    elif ctype == "status":
        for kw in keywords:
            if kw in text:
                return kw
        return "状态变更"
    return "未知"


def review():
    if not PENDING_FILE.exists():
        return []

    content = PENDING_FILE.read_text(encoding="utf-8")
    entries = list(re.finditer(
        r"^## (chg-\d+)\n"
        r"^- timestamp:\s*(.+)\n"
        r"^- type:\s*(.+)\n"
        r"^- entity:\s*(.+)\n"
        r"^- field:\s*(.+)\n"
        r"^- old_value:\s*(.+)\n"
        r"^- new_value:\s*(.+)\n"
        r"^- confidence:\s*(.+)\n"
        r"^- source:\s*\"(.+)\"\n"
        r"^- status:\s*(.+)",
        content, re.MULTILINE
    ))

    changes = []
    for m in entries:
        changes.append({
            "id": m.group(1),
            "timestamp": m.group(2),
            "type": m.group(3),
            "entity": m.group(4),
            "field": m.group(5),
            "old_value": m.group(6),
            "new_value": m.group(7),
            "confidence": float(m.group(8)),
            "source_text": m.group(9),
            "status": m.group(10),
        })

    return [c for c in changes if c["status"] == "pending"]


def confirm(change_id):
    _move_change(change_id, "confirmed", CONFIRMED_FILE)


def reject(change_id):
    _move_change(change_id, "rejected", REJECTED_FILE)


def _move_change(change_id, new_status, target_file):
    if not PENDING_FILE.exists():
        return False

    content = PENDING_FILE.read_text(encoding="utf-8")
    pattern = rf"(^## {re.escape(change_id)}\n.*?)(?=^##|\Z)"

    def _replacer(m):
        block = m.group(0)
        if new_status in ("confirmed", "rejected"):
            block = re.sub(r"status:\s*pending", f"status: {new_status}", block)
        if target_file:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(f"\n{block.strip()}\n")
        return ""

    new_content = re.sub(pattern, _replacer, content, flags=re.MULTILINE | re.DOTALL)
    PENDING_FILE.write_text(new_content, encoding="utf-8")
    return True


def sync_entity_index():
    entities = _load_entities()
    pending = review()

    activity_map = {}
    for c in pending:
        name = c["entity"]
        if name not in activity_map:
            activity_map[name] = []
        activity_map[name].append(c)

    seen = set()
    pending_list = []
    for item in entities:
        name = item["name"]
        if name in seen:
            continue
        seen.add(name)
        if name in activity_map:
            latest = activity_map[name][-1]
            pending_list.append({
                "name": name,
                "aliases": item.get("aliases", []),
                "route_hint": item.get("route_hint", ["G"]),
                "weight": 0.5,
                "role": latest["new_value"],
                "source": "pending",
                "confidence": latest["confidence"],
            })

    with open(ENTITY_INDEX, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["pending_entities"] = pending_list
    data["_meta"]["updated"] = datetime.now().strftime("%Y-%m-%d")

    tmp = Path(str(ENTITY_INDEX) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(ENTITY_INDEX)

    return pending_list


def main():
    if len(sys.argv) < 2:
        print("用法: change_detector.py detect <text> | review | confirm <id> | reject <id> | sync")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "detect":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not text.strip():
            print("错误: 请提供要分析的文本")
            sys.exit(1)
        results = detect(text)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "review":
        changes = review()
        if not changes:
            print("没有待确认的变化。")
            return
        for i, c in enumerate(changes, 1):
            types_cn = {"responsibility": "职责变化", "status": "状态变化"}
            print(f"[{i}] {c['entity']}: {c['old_value']} → {c['new_value']} "
                  f"({types_cn.get(c['type'], c['type'])} 置信度 {c['confidence']})")
            print(f"    来源: {c['source_text']}")
            print()

        print("操作: y <编号> 确认 | n <编号> 拒绝 | q 退出")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line or line == "q":
                break
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            action, num = parts[0], parts[1]
            try:
                idx = int(num) - 1
            except ValueError:
                continue
            if idx < 0 or idx >= len(changes):
                print("无效编号")
                continue
            c = changes[idx]
            if action == "y":
                confirm(c["id"])
                print(f"已确认: {c['entity']}")
            elif action == "n":
                reject(c["id"])
                print(f"已拒绝: {c['entity']}")

    elif cmd == "confirm":
        if len(sys.argv) < 3:
            print("错误: 需要提供 change_id")
            sys.exit(1)
        confirm(sys.argv[2])
        print(f"已确认: {sys.argv[2]}")

    elif cmd == "reject":
        if len(sys.argv) < 3:
            print("错误: 需要提供 change_id")
            sys.exit(1)
        reject(sys.argv[2])
        print(f"已拒绝: {sys.argv[2]}")

    elif cmd == "sync":
        result = sync_entity_index()
        print(f"已同步 {len(result)} 条 pending entity 到 entity_index.json")

    else:
        print(f"未知命令: {cmd}")
        print("用法: change_detector.py detect <text> | review | confirm <id> | reject <id> | sync")


if __name__ == "__main__":
    main()
