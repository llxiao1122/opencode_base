"""
routing/record_manager.py — 工作记录管理（从 entry.py 提取）

职责：
  1. 检测记录意图
  2. 创建/合并任务
  3. 检测缺失信息
  4. 合并相似任务
"""

import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def record(text: str, user: dict) -> str:
    """Detect work recording intent for unknown events, create tasks.

    Returns response string or None if not a record intent.
    """
    markers = ["记录", "录入", "记一下", "备忘", "记：", "记录：", "录入："]
    ltext = text.lstrip()
    is_explicit = any(ltext.startswith(m) for m in markers)

    from shared import has_known_entity, find_entities_in_text
    has_entity = has_known_entity(text) or bool(find_entities_in_text(text))
    has_date = any(kw in text for kw in ["明天", "今天", "下周", "周", "日", "月", "号",
                                            "早上", "下午", "晚上", "下班前", "尽快"])

    if not is_explicit and not (has_entity or has_date):
        if len(text) >= 6:
            try:
                from shared.semantic import score as sem_score
                record_score = sem_score(text, [
                    "明天要做的事情", "今天的工作记录", "要处理的事",
                    "接下来要干什么", "发生了什么事", "办完了什么",
                ])
                chat_score = sem_score(text, [
                    "你好", "再见", "谢谢", "天气不错", "吃了吗",
                    "在吗", "怎么样", "行不行",
                ])
                if record_score < 0.52 or chat_score > record_score:
                    return None
            except Exception:
                return None
        else:
            return None

    from organization.model import OrganizationModel
    from task.manager import TaskManager
    org = OrganizationModel()
    tm = TaskManager(org)

    action = text
    if is_explicit:
        for m in markers:
            if ltext.startswith(m):
                action = ltext[len(m):].lstrip("：: ").strip()
                break

    task_event = {
        "id": "",
        "event_type": "note",
        "time": _extract_deadline_from_text(text),
        "source": "手动记录",
        "actors": [],
        "action": {"type": "note", "summary": action},
        "target": "",
        "confidence": 0.7,
        "raw": text,
    }

    context = {
        "my_position": {"type": "observer", "owner": user.get("name", "")},
        "required_action": {"verb": "", "scope": ""},
        "reason": "手动记录",
    }

    task = tm.create(task_event, context, user)
    task["action"] = action
    from task.store import save

    merged = merge_similar(task, delete_new=True)
    if merged:
        msg = f"✅ 已合并到已有任务：{merged[:80]}..."
        return f"[Cipher:task]\n{msg}"

    if is_explicit:
        return f"[Cipher:task]\n✅ 已记录：{action[:100]}"

    missing = detect_missing(action)
    msg = f"✅ 已记录：{action[:100]}"
    if missing:
        msg += f"\n📝 需要补充：{missing}"
    return f"[Cipher:task]\n{msg}"


def merge_similar(new_task: dict, delete_new: bool = False) -> str:
    """Check if new_task is similar to any existing active task. If so, merge and return merged action."""
    path = ROOT_DIR / "data" / "tasks.json"
    if not path.exists():
        return ""
    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    new_action = new_task.get("action", "")
    if not new_action or len(new_action) < 4:
        return ""

    for t in tasks:
        if t["id"] == new_task.get("id"):
            continue
        existing = t.get("action", "")
        if not existing or len(existing) < 4:
            continue

        from shared import find_entities_in_text
        new_ents = {e["name"] for e in find_entities_in_text(new_action)}
        old_ents = {e["name"] for e in find_entities_in_text(existing)}
        shared = new_ents & old_ents
        if not shared:
            continue

        sim = 0.0
        threshold = 0.68
        try:
            from shared.semantic import score as sem_score
            sim = sem_score(new_action, [existing])
        except Exception:
            def _bigrams(t):
                clean = re.sub(r"[，。、；：！？（）()/\d\s]", "", t)
                return {clean[i:i+2] for i in range(len(clean)-1)}
            bg_new = _bigrams(new_action)
            bg_old = _bigrams(existing)
            bg_common = bg_new & bg_old
            if bg_new and bg_old:
                sim = len(bg_common) / min(len(bg_new), len(bg_old))
            threshold = 0.28

        if sim > threshold and shared:
            merged = _select_better_info(existing, new_action)
            t["action"] = merged
            from task.store import save
            save(t)
            if delete_new:
                tasks = [x for x in tasks if x["id"] != new_task.get("id")]
                import json as _j
                tmp = Path(str(path) + ".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    _j.dump(tasks, f, ensure_ascii=False, indent=2)
                tmp.replace(path)
            return merged
    return ""


def _select_better_info(old: str, new: str) -> str:
    """Merge: keep old as base, add new info that old is missing."""
    result = old
    time_pattern = r"(上午|下午|中午|晚上|早上)([零一二三四五六七八九十0-9]{1,2})?(点|时|点钟)"
    has_time_old = re.search(time_pattern, old)
    has_time_new = re.search(time_pattern, new)
    if not has_time_old and has_time_new:
        result = result.rstrip("。；，. ") + "，" + has_time_new.group(0)

    # Find substantive phrases in new that are absent in old
    import difflib
    matcher = difflib.SequenceMatcher(None, old, new)
    extra_parts = []
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag == 'insert':
            part = new[j1:j2].strip("，。、；：！？（）()")
            if len(part) >= 3:
                extra_parts.append(part)
    if extra_parts:
        sep = "，" if not result.endswith("，") else ""
        result += sep + "".join(extra_parts)
    return result


def detect_missing(text: str) -> str:
    """Detect missing info in a work record text."""
    missing = []
    has_time = any(kw in text for kw in ["几点", "上午", "下午", "早上", "晚上",
                                            "点", "时", "分"])
    if not re.search(r"(上午|下午|中午|晚上|早上)([零一二三四五六七八九十0-9]{1,2})?(点|时|点钟)", text) and not has_time:
        missing.append("具体时间")
    from shared import has_known_entity
    if not has_known_entity(text):
        missing.append("相关人员")
    has_location = any(kw in text for kw in ["站", "库", "室", "楼", "区", "路", "街",
                                                "园", "厂", "段", "线"])
    if not has_location:
        missing.append("地点")
    if not missing:
        return ""
    return "、".join(missing)


def _extract_deadline_from_text(text: str) -> dict:
    patterns = [
        (r"(\d{4}-\d{2}-\d{2})", "date"),
        (r"(\d{1,2}月\d{1,2}日)", "cn"),
        (r"明天", "tomorrow"),
        (r"今天", "today"),
        (r"周[一二三四五六日]", "weekday"),
    ]
    for pat, _ in patterns:
        if re.search(pat, text):
            return {"deadline": re.search(pat, text).group(0), "start": ""}
    return {"deadline": "", "start": ""}
