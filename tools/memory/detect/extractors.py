"""
memory/detect/extractors.py — Event field extraction from text.

All functions are module-internal (prefixed with _).
Performs: time, entities, actions, constraints, evidence,
report_to, participants, related_teams, executor analysis,
sender, executor, target, title, items extraction.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path as _PathInternal

_root = _PathInternal(__file__).resolve().parent.parent.parent.parent

from .signals import ACTION_VERBS, TIME_PATTERNS, NUMBERED_PATTERN

TEAM_MAP = {}
TEAM_LEADER_MAP = {}

def _init_team_maps():
    global TEAM_MAP, TEAM_LEADER_MAP
    if TEAM_MAP:
        return
    import sys as _sys
    _sys.path.insert(0, str(_root))
    from tools.shared.entity import TEAM_MAP as _tm, TEAM_LEADER_MAP as _tlm
    TEAM_MAP = _tm
    TEAM_LEADER_MAP = _tlm


def _extract_time(text):
    result = {"start": "", "deadline": ""}
    now = datetime.now()

    for pat, label in TIME_PATTERNS:
        m = re.search(pat, text)
        if not m:
            continue

        if label == "iso_date":
            raw = m.group(1).replace("/", "-").replace(".", "-")
            result["deadline"] = raw[:10]
        elif label == "cn_date":
            m2 = re.search(r"(\d{1,2})月(\d{1,2})日", m.group(1))
            if m2:
                month, day = int(m2.group(1)), int(m2.group(2))
                y = now.year
                result["deadline"] = f"{y}-{month:02d}-{day:02d}"
        elif label == "relative":
            found_xiayao = False
            for wd in re.finditer(r"下周([一二三四五六日])", text):
                day_map = {"\u4e00": 0, "\u4e8c": 1, "\u4e09": 2, "\u56db": 3, "\u4e94": 4, "\u516d": 5, "\u65e5": 6}
                target_wd = day_map.get(wd.group(1), 0)
                days_ahead = (7 + target_wd - now.weekday()) % 7 + 7
                dt = now + timedelta(days=days_ahead)
                result["deadline"] = dt.strftime("%Y-%m-%d")
                found_xiayao = True
                break
            if not found_xiayao:
                result["deadline"] = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                result["start"] = result["deadline"]
        elif label == "today":
            result["start"] = now.strftime("%Y-%m-%d")
        elif label == "weekday":
            for wd in re.finditer(r"(下?周)([一二三四五六日])", text):
                day_map = {"\u4e00": 0, "\u4e8c": 1, "\u4e09": 2, "\u56db": 3, "\u4e94": 4, "\u516d": 5, "\u65e5": 6}
                target = day_map.get(wd.group(2), 0)
                days_ahead = (target - now.weekday()) % 7
                has_xia = "下周" in wd.group(1)
                if not has_xia and days_ahead == 0:
                    days_ahead = 0
                elif days_ahead == 0:
                    days_ahead = 7
                if has_xia:
                    days_ahead += 7
                dt = now + timedelta(days=days_ahead)
                result["deadline"] = dt.strftime("%Y-%m-%d")
            for wd in re.finditer(r"(?<!下)周([一二三四五六日])", text):
                day_map = {"\u4e00": 0, "\u4e8c": 1, "\u4e09": 2, "\u56db": 3, "\u4e94": 4, "\u516d": 5, "\u65e5": 6}
                target = day_map.get(wd.group(1), 0)
                days_ahead = (target - now.weekday()) % 7
                if days_ahead == 0:
                    continue
                dt = now + timedelta(days=days_ahead)
                result["deadline"] = dt.strftime("%Y-%m-%d")
        elif label == "within_days":
            n = int(m.group(1))
            result["deadline"] = (now + timedelta(days=n)).strftime("%Y-%m-%d")
        elif label == "minutes_ago":
            pass
        elif label == "day_only":
            day_match = re.search(r"(\d{1,2})日", m.group(0))
            if day_match:
                day = int(day_match.group(1))
                y, month = now.year, now.month
                try:
                    deadline = datetime(y, month, day)
                except ValueError:
                    deadline = now + timedelta(days=1)
                if deadline < now:
                    if month == 12:
                        deadline = datetime(y + 1, 1, day)
                    else:
                        try:
                            deadline = datetime(y, month + 1, day)
                        except ValueError:
                            deadline = now + timedelta(days=1)
                result["deadline"] = deadline.strftime("%Y-%m-%d")
        elif label == "end_of_work":
            if not result["deadline"]:
                result["deadline"] = now.strftime("%Y-%m-%d")
            result["time_note"] = "下班前"
        elif label == "immediate":
            if not result["deadline"]:
                result["deadline"] = now.strftime("%Y-%m-%d")
        elif label == "date_range_end":
            m2 = re.search(r"(\d{1,2})月(\d{1,2})日", m.group(1))
            if m2:
                month, day = int(m2.group(1)), int(m2.group(2))
                y = now.year
                result["deadline"] = f"{y}-{month:02d}-{day:02d}"

    return result


def _extract_entities(text):
    try:
        sys.path.insert(0, str(_root / "tools"))
        from routing.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        result = []
        for e in resolved["entities"]:
            result.append({"name": e["name"], "role": e.get("role", ""), "source": e.get("source", "")})
        return result
    except Exception:
        return []


def _extract_required_actions(text):
    results = []
    noise = ["时间", "商", "之前", "之后", "计划如下", "如下：", "如下:", "距", "距离"]
    distance_chars = "距离防以免被可已正用"
    compound_suffix = "组员部处室院局队站所科委办"
    for clause in re.split(r"[，。；；\n]", text):
        clause = clause.strip()
        if len(clause) < 5:
            continue
        for v in sorted(ACTION_VERBS, key=len, reverse=True):
            idx = clause.find(v)
            if idx < 0:
                continue
            if idx > 0 and clause[idx - 1] in distance_chars:
                break
            after = clause[idx + len(v):idx + len(v) + 1] if idx + len(v) < len(clause) else ""
            if after in compound_suffix:
                break
            action = clause[idx:].strip("，。；、").rstrip("）)】□■▲★●◎◆→←")
            if 5 <= len(action) <= 40 and not any(n in action[:6] for n in noise):
                if action.startswith(v):
                    if not action.startswith("通知："):
                        results.append(action)
            break
    return results


def _extract_constraints(text):
    patterns = [
        r"(使用[^，。；\n]{3,60})",
        r"((?<!所)需[^，。；\n]{1,60})",
        r"(须[^，。；\n]{2,60})",
        r"(禁止[^，。；\n]{2,60})",
        r"(不得[^，。；\n]{2,60})",
        r"(注意[^，。；\n]{2,60})",
        r"(确保[^，。；\n]{2,60})",
        r"(应[^，。；\n]{2,60})",
        r"(全程[^，。；\n]{2,60})",
    ]
    seen = set()
    results = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            clause = m.group(1).strip()
            if len(clause) >= 4 and clause not in seen:
                results.append(clause)
                seen.add(clause)
    return results


def _extract_evidence(text):
    keywords = ["照片", "影像", "视频", "截图", "记录仪", "签字", "打卡", "图片"]
    results = []
    for clause in re.split(r"[，。；\n]", text):
        clause = clause.strip().strip("，。；、")
        for kw in keywords:
            if kw in clause:
                if 2 <= len(clause) <= 80 and clause not in results:
                    results.append(clause)
                break
    return results


def _extract_report_to(text):
    patterns = [
        r"发送[^，。；]{0,20}[到至给]([^，。；]{2,15})",
        r"反馈[^，。；]{0,20}[到至给]([^，。；]{2,15})",
        r"上报[^，。；]{0,20}[到至给]([^，。；]{2,15})",
        r"交[^，。；]{0,20}[到至给]([^，。；]{2,15})",
        r"发[给到]([^，。；]{2,15})",
        r"与([^，。；]{2,8})联系报备",
        r"与([^，。；]{2,8})联系",
        r"和([^，。；]{2,8})确认",
        r"与([^，。；]{2,8})对接确认",
        r"找([^，。；]{2,8})报备",
    ]
    candidates = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            candidate = m.group(1).strip().rstrip("。，；、钉钉")
            if candidate and len(candidate) <= 12:
                candidates.append(candidate)

    results = []
    try:
        import sys as _sys
        _sys.path.insert(0, str(_root / "tools"))
        from routing.entity_resolver import resolve_entities
        for candidate in candidates:
            if candidate in ("我", "本人", "自己", "我们", "俺"):
                continue
            resolved = resolve_entities(candidate)
            if resolved.get("entities"):
                results.append(resolved["entities"][0]["name"])
            else:
                results.append(candidate)
    except Exception:
        results = candidates

    if not results and any(pat in text for pat in [
        "与我联系", "和我确认", "与我对接", "找我报备", "向我反馈"
    ]):
        try:
            entities_found = _extract_entities(text)
            if entities_found:
                results.append(entities_found[0]["name"])
        except Exception:
            pass

    return list(set(results))


def _extract_participants(text):
    patterns = [
        r"(各工班长)",
        r"(各工班)",
        r"(各班组)",
        r"(铁炉西工班)",
        r"(产废中心)",
        r"(生产中心)",
        r"(全体人员)",
        r"(全员)",
    ]
    role_fragments = [
        (r"工班长", "工班长"),
        (r"科室副主任", "科室副主任"),
        (r"线路包保管理岗", "线路包保管理岗"),
    ]
    results = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            p = m.group(1).strip()
            if p and p not in results and len(p) <= 20:
                results.append(p)
    for pat, label in role_fragments:
        if pat in text and label not in results:
            results.append(label)
    return results


def _extract_related_teams(entities):
    _init_team_maps()
    teams = set()
    for e in entities:
        name = e.get("name", "") if isinstance(e, dict) else str(e)
        if name in TEAM_MAP:
            teams.add(TEAM_MAP[name])
    return list(teams)


def _build_executor_analysis(participants):
    if not participants:
        return {"source": "participants", "scope": "unknown", "type": "unknown",
                "confidence": 0.0, "evidence": []}
    scope = "all_teams" if "各库区" in participants else "team"
    etype = "role" if any("工班长" in p for p in participants) else "team"
    conf = 0.82 if "工班长" in "".join(participants) else 0.70
    return {
        "source": "participants",
        "scope": scope,
        "type": etype,
        "confidence": conf,
        "evidence": list(participants),
    }


_NOTICE_WORDS = {"迎检", "紧急", "重要", "工作", "会议", "安全", "临时", "最新", "消防", "防汛"}


def _extract_sender(text, entities):
    m = re.match(r"(\S+)通知", text)
    if m:
        sender_name = m.group(1)
        if sender_name in _NOTICE_WORDS:
            pass
        elif len(sender_name) > 10:
            pass
        elif any(kw in sender_name for kw in ["关于", "开展", "专题", "培训", "会议", "工作", "组织"]):
            pass
        else:
            if "要求" in sender_name:
                parts = sender_name.split("要求")
                if len(parts) >= 2 and len(parts[-1]) <= 6:
                    sender_name = parts[-1]
            for e in entities:
                if e["name"] == sender_name:
                    return e["name"]
            return sender_name
    m2 = re.search(r"(\S{2,4})\d{1,2}[日晚]通知", text)
    if m2:
        sender_name = m2.group(1)
        for e in entities:
            if e["name"] == sender_name:
                return e["name"]
        if sender_name not in _NOTICE_WORDS:
            return sender_name
    m3 = re.search(r"([\u4e00-\u9fff]{2,4}发?布?通知)", text)
    if m3:
        sender_name = m3.group(1).rstrip("发布通知通知")
        for e in entities:
            if e["name"] == sender_name:
                return e["name"]
    if entities:
        last_entity = entities[-1]["name"]
        tail = text[-200:]
        if last_entity in tail[-80:]:
            return last_entity
    return None


def _resolve_executor(participants, current_user=None):
    _init_team_maps()
    for p in participants:
        if p in TEAM_LEADER_MAP:
            return TEAM_LEADER_MAP[p]
    for p in participants:
        if "工班长" in p:
            try:
                up = _root / "state" / "user_profile.md"
                for line in up.read_text(encoding="utf-8").split("\n"):
                    if line.strip().startswith("name:"):
                        return line.split(":", 1)[1].strip()
            except Exception:
                pass
    team_words = ["各工班", "各工班长", "铁炉西工班", "各库区", "全体人员"]
    if any(w in participants for w in team_words):
        try:
            up = _root / "state" / "user_profile.md"
            for line in up.read_text(encoding="utf-8").split("\n"):
                if line.strip().startswith("name:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    if current_user and isinstance(current_user, dict):
        return current_user.get("name")
    return None


def _resolve_target(participants):
    _init_team_maps()
    for p in participants:
        if p in TEAM_LEADER_MAP:
            return p
    if participants:
        return participants[0]
    return None


def _extract_title(text):
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return "未命名事件"

    first = lines[0]

    for marker in ["安排工作计划如下", "通知如下", "如下：", "如下:", "通知：", "通知:"]:
        if marker in first:
            candidate = first[first.index(marker) + len(marker):].strip("：: \u3000")
            if candidate and len(candidate) >= 2:
                return candidate[:30]
            prefix = first[:first.index(marker)].strip("：: \u3000")
            for sep in ["：", "，", ":", "。", "、"]:
                if sep in prefix:
                    parts = prefix.rsplit(sep, 1)
                    if parts[-1].strip("：: \u3000"):
                        return parts[-1].strip("：: \u3000，, ")[:30]
            return prefix[-30:] if len(prefix) > 2 else "紧急通知"

    if len(first) <= 30:
        return first
    for sep in ["，", "。", "；", ": ", "：", "、"]:
        if sep in first:
            return first[:first.index(sep)]
    return first[:30]


def _extract_items(text):
    items = []
    for m in NUMBERED_PATTERN.finditer(text):
        start = m.end()
        next_m = NUMBERED_PATTERN.search(text, start)
        end = next_m.start() if next_m else len(text)
        content = text[start:end].strip()[:200]
        if content:
            sub_actions = [v for v in ACTION_VERBS if v in content]
            items.append({
                "seq": len(items) + 1,
                "text": content,
                "actions": sub_actions,
                "required_actions": _extract_required_actions(content),
            })
    return items
