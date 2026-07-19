"""
event_detector.py — Event Candidate Extractor

业务事件采集，不推理。从文本中提取"可能值得记录的业务事件候选"。

检测策略 (L1: 4信号任意2触发):
  ① 动作词 + 时间词
  ② 动作词 + 实体
  ③ 编号结构 + 动作词
  ④ 通知类标题 + 时间词

置信度阈值:
  >= 0.80 → active/      高置信度
  0.70~0.79 → active/   普通候选
  < 0.70  → ignored/    保留用作规则分析

 生命周期: detected → active → completed / cancelled → archived; expired 由 maintenance 自动标记

实体识别统一通过 entity_resolver，不自建人名检测。
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_FILE = ROOT / "memory" / "events" / "index.json"
EVENTS_DIR = ROOT / "memory" / "events"

ACTION_VERBS = [
    "安排", "通知", "协调", "交接", "报备", "确认", "回收", "处置",
    "开展", "催促", "对接", "检查", "整改", "办理", "上报", "审批",
    "验收", "移交", "排查", "登记", "发放", "领取", "关闭", "启动",
    "暂停", "恢复", "调整", "分配", "部署", "汇总", "跟踪",
    "组织", "拍摄", "建立", "发送", "参加", "请假", "值班", "巡检",
    "发布", "执行", "回复",
]

TIME_PATTERNS = [
    (r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", "iso_date"),
    (r"(\d{1,2}月\d{1,2}日)", "cn_date"),
    (r"(\d{1,2}月)", "cn_month"),
    (r"明[日天]起?(至|到)?(下?\w{1,3})?", "relative"),
    (r"(今日|今天)(起|开始)?", "today"),
    (r"(下?周[一二三四五六日])", "weekday"),
    (r"(\d+)日内", "within_days"),
    (r"即日起", "effective"),
    (r"截止日?期?", "deadline_marker"),
    (r"(\d+)月前", "before_month"),
]

ANNOUNCE_PATTERNS = [
    r"通知", r"知悉", r"请各", r"各工班",
    r"根据.*指示", r"按照.*要求", r"根据.*安排",
    r"经.*研究", r"经.*决定",
    r"预警(信号)?", r"应急(预案|响应)?", r"演练",
]

NUMBERED_PATTERN = re.compile(r"(?:^|\n)\s*\d+[.、)]\s*", re.MULTILINE)


def _load_index():
    if not INDEX_FILE.exists():
        return {"events": []}
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(data):
    tmp = Path(str(INDEX_FILE) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(INDEX_FILE)


def _next_id():
    index = _load_index()
    existing = {e["id"] for e in index.get("events", [])}
    today = datetime.now().strftime("%Y%m%d")
    for i in range(1, 1000):
        cid = f"evt_{today}_{i:03d}"
        if cid not in existing:
            return cid
    return f"evt_{today}_{int(datetime.now().timestamp()) % 100000:05d}"


def _persist(event):
    status = event.get("status", "active")
    dir_map = {
        "active": EVENTS_DIR / "active",
        "detected": EVENTS_DIR / "detected",
        "completed": EVENTS_DIR / "completed",
        "archived": EVENTS_DIR / "archived",
        "cancelled": EVENTS_DIR / "cancelled",
        "expired": EVENTS_DIR / "expired",
        "ignored": EVENTS_DIR / "ignored",
    }
    target_dir = dir_map.get(status, EVENTS_DIR / "active")
    target_dir.mkdir(parents=True, exist_ok=True)

    filepath = target_dir / f"{event['id']}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False, indent=2)

    index = _load_index()
    meta = {
        "id": event["id"],
        "title": event.get("title", ""),
        "status": status,
        "owners": [e["name"] for e in event.get("entities", [])],
        "deadline": event.get("time", {}).get("deadline", ""),
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }
    existing = [e for e in index["events"] if e["id"] != event["id"]]
    existing.append(meta)
    index["events"] = existing
    _save_index(index)


def _signal_count(text, entities_found):
    signals = 0

    # ① 动作词 + 时间词
    has_action = any(v in text for v in ACTION_VERBS)
    has_time = False
    for pat, _ in TIME_PATTERNS:
        if re.search(pat, text):
            has_time = True
            break
    if has_action and has_time:
        signals += 1

    # ② 动作词 + 实体
    if has_action and entities_found:
        signals += 1

    # ③ 编号结构 + 动作词
    if NUMBERED_PATTERN.search(text) and has_action:
        signals += 1

    # ④ 通知类标题 + (时间词 或 动作词)
    has_announce = any(re.search(p, text) for p in ANNOUNCE_PATTERNS)
    if has_announce and (has_time or has_action):
        signals += 1

    # ⑤ 角色/团队词 + 动作词（覆盖无时间无实体的任务分配）
    ROLE_WORDS = ["各工班长", "各工班", "各库区", "全体人员", "所有工班"]
    if has_action and any(r in text for r in ROLE_WORDS):
        signals += 1

    return signals


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
                day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
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
                day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
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
            # bare "周日" without 下 prefix (e.g. "最晚周日")
            for wd in re.finditer(r"(?<!下)周([一二三四五六日])", text):
                day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
                target = day_map.get(wd.group(1), 0)
                days_ahead = (target - now.weekday()) % 7
                if days_ahead != 0:
                    pass
                dt = now + timedelta(days=days_ahead)
                result["deadline"] = dt.strftime("%Y-%m-%d")
        elif label == "within_days":
            n = int(m.group(1))
            result["deadline"] = (now + timedelta(days=n)).strftime("%Y-%m-%d")

    return result


def _extract_entities(text):
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from routing.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        result = []
        for e in resolved["entities"]:
            result.append({"name": e["name"], "role": e.get("role", ""), "source": e.get("source", "")})
        return result
    except Exception:
        return []


def _extract_actions(text):
    return [v for v in ACTION_VERBS if v in text]


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
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
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


_TEAM_MAP = {
    "李林骁": "铁炉西工班",
    "陈红洁": "铁炉西工班",
    "杨梦卓": "铁炉西工班",
    "谭继衡": "铁炉西工班",
    "苗笑天": "铁炉西工班",
    "张志斌": "铁炉西工班",
}

_TEAM_LEADER_MAP = {
    "铁炉西工班": "李林骁",
}

_HAZWASTE_CONSTRAINTS = [
    "须佩戴执法记录仪全程录像",
    "须确认车辆信息与联单派遣信息一致",
    "须签署《外来人员安全告知书》并登记",
    "须2名工班人员用校准过的称重工具共同核对重量",
    "双方须在i物资上签字确认后才可装车",
    "须拍摄装车前、装车后带水印照片（各≥2张）发钉钉群",
    "处置完成后须在OA流程上及时办理",
    "须2个工作日内完成台账更新",
]

_HAZWASTE_TASKS = [
    "确认处置单据对应的OA单号",
    "确认处置车辆进段场前信息一致性（车牌号与联单）",
    "对处置单位人员进行安全交底，签署《外来人员安全告知书》",
    "2名工班人员用校准过的称重工具与处置单位共同核对重量",
    "双方在i物资上签字确认",
    "全程佩戴执法记录仪，网盘留存录像",
    "拍摄装车前、装车后带水印照片各≥2张，发钉钉工作群",
    "处置完成后在OA流程上及时办理",
    "2个工作日内完成台账更新",
    "每月30日前将处置单据移交模块责任人",
]


def _extract_related_teams(entities):
    teams = set()
    for e in entities:
        name = e.get("name", "") if isinstance(e, dict) else str(e)
        if name in _TEAM_MAP:
            teams.add(_TEAM_MAP[name])
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
        else:
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

def _resolve_executor(participants):
    for p in participants:
        if p in _TEAM_LEADER_MAP:
            return _TEAM_LEADER_MAP[p]
    for p in participants:
        if "工班长" in p:
            try:
                up = ROOT / "state" / "user_profile.md"
                for line in up.read_text(encoding="utf-8").split("\n"):
                    if line.strip().startswith("name:"):
                        return line.split(":", 1)[1].strip()
            except Exception:
                pass
    team_words = ["各工班", "各工班长", "铁炉西工班", "各库区", "全体人员"]
    if any(w in participants for w in team_words):
        try:
            up = ROOT / "state" / "user_profile.md"
            for line in up.read_text(encoding="utf-8").split("\n"):
                if line.strip().startswith("name:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return None

def _resolve_affected(participants):
    for p in participants:
        if p in _TEAM_LEADER_MAP:
            return p
    if participants:
        return participants[0]
    return None

def _enrich_hazwaste(event, text):
    if not any(kw in text for kw in ["危废", "危险废物"]):
        return event
    existing_actions = event.get("required_actions", [])
    for t in _HAZWASTE_TASKS:
        if t not in existing_actions:
            existing_actions.append(t)
    existing_constraints = event.get("constraints", [])
    for c in _HAZWASTE_CONSTRAINTS:
        if c not in existing_constraints:
            existing_constraints.append(c)
    event["required_actions"] = existing_actions
    event["constraints"] = existing_constraints
    return event


def _extract_title(text):
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return "未命名事件"

    first = lines[0]

    for marker in ["安排工作计划如下", "通知如下", "如下：", "如下:", "通知：", "通知:"]:
        if marker in first:
            candidate = first[first.index(marker) + len(marker):].strip("：: 　")
            if candidate and len(candidate) >= 2:
                return candidate[:30]
            prefix = first[:first.index(marker)].strip("：: 　")
            for sep in ["：", "，", ":", "。", "、"]:
                if sep in prefix:
                    parts = prefix.rsplit(sep, 1)
                    if parts[-1].strip("：: 　"):
                        return parts[-1].strip("：: 　，, ")[:30]
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


def _compute_confidence(signals, entities_found, items_found, time_found):
    conf = 0.5
    conf += signals * 0.10
    if entities_found:
        conf += 0.08
    if items_found:
        conf += 0.12
    if time_found:
        conf += 0.10
    return round(min(0.95, conf), 2)


def detect(text: str) -> list[dict]:
    if not text.strip():
        return []

    entities = _extract_entities(text)
    participants = _extract_participants(text)

    signals = _signal_count(text, entities)
    # 短消息（≤15字）+ 实体 + 动作词：接受单信号
    min_signals = 1 if (len(text) <= 15 and entities and any(v in text for v in ACTION_VERBS)) else 2
    if signals < min_signals:
        return []

    time_info = _extract_time(text)
    if not time_info.get("start") and not time_info.get("deadline"):
        time_info["start"] = datetime.now().strftime("%Y-%m-%d")
    actions = _extract_actions(text)
    items = _extract_items(text)
    title = _extract_title(text)

    confidence = _compute_confidence(
        signals=signals,
        entities_found=bool(entities),
        items_found=bool(items),
        time_found=bool(time_info.get("deadline") or time_info.get("start")),
    )

    publisher = _extract_sender(text, entities)
    executor = _resolve_executor(participants)
    affected = _resolve_affected(participants)

    event = {
        "id": _next_id(),
        "type": "work_event",
        "title": title,
        "publisher": publisher,
        "executor": executor,
        "affected": affected,
        "entities": entities,
        "actions": actions,
        "required_actions": [],
        "time": time_info,
        "items": [],
        "priority": _guess_priority(text),
        "confidence": confidence,
        "constraints": [],
        "evidence": [],
        "report_to": _extract_report_to(text),
        "participants": participants,
        "related_teams": _extract_related_teams(entities),
        "source": {
            "type": "text",
            "raw": text[:1000],
        },
        "detected_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if confidence >= 0.85:
        event["status"] = "active"
    elif confidence >= 0.60:
        event["status"] = "detected"
    else:
        return []

    _persist(event)
    return [event]


def _guess_priority(text):
    if any(kw in text for kw in ["紧急", "立即", "马上", "立刻", "尽快"]):
        return "high"
    if any(kw in text for kw in ["注意", "重要", "严格"]):
        return "normal"
    return "normal"


def list_events(status=None):
    index = _load_index()
    events = index.get("events", [])
    if status:
        events = [e for e in events if e.get("status") == status]
    return sorted(events, key=lambda e: e.get("updated", ""), reverse=True)


def _change_status(event_id, new_status):
    index = _load_index()
    target = None
    for e in index.get("events", []):
        if e["id"] == event_id:
            target = e
            break
    if not target:
        return False

    old_status = target["status"]
    if old_status == new_status:
        return False

    old_dir = EVENTS_DIR / old_status / f"{event_id}.json"
    new_dir = EVENTS_DIR / new_status
    new_dir.mkdir(parents=True, exist_ok=True)
    new_path = new_dir / f"{event_id}.json"

    if old_dir.exists():
        with open(old_dir, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["status"] = new_status
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        old_dir.unlink()
    elif new_dir != old_dir:
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump({"id": event_id, "status": new_status}, f, ensure_ascii=False)

    target["status"] = new_status
    target["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_index(index)
    return True


def complete(event_id):
    return _change_status(event_id, "completed")


def archive(event_id):
    return _change_status(event_id, "archived")


def ignore(event_id):
    return _change_status(event_id, "ignored")


change_status = _change_status
load_index = _load_index
save_index = _save_index


def main():
    if len(sys.argv) < 2:
        print("用法: event_detector.py detect <text> | list [active|completed|ignored] | complete <id> | archive <id>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "detect":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not text.strip():
            print("错误: 请提供要分析的文本")
            sys.exit(1)
        results = detect(text)
        if results:
            for r in results:
                print(f"id={r['id']} title={r['title']} conf={r['confidence']} status={r['status']}")
        else:
            print("未检测到事件 (信号数 < 2)")

    elif cmd == "list":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        events = list_events(status)
        if not events:
            print("暂无事件。")
            return
        for e in events:
            print(f"{e['id']} [{e['status']}] {e['title']}  "
                  f"owners={e.get('owners',[])} deadline={e.get('deadline','')}")

    elif cmd == "complete" and len(sys.argv) > 2:
        if complete(sys.argv[2]):
            print(f"已标记完成: {sys.argv[2]}")
        else:
            print(f"未找到事件: {sys.argv[2]}")

    elif cmd == "archive" and len(sys.argv) > 2:
        if archive(sys.argv[2]):
            print(f"已归档: {sys.argv[2]}")
        else:
            print(f"未找到事件: {sys.argv[2]}")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
