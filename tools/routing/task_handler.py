"""
routing/task_handler.py — Task query handler (Phase 13.1).

Queries: today, tomorrow, this week.
Data source: data/tasks.json (dynamic tasks only).
"""

import json
from datetime import datetime, timedelta, date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TASKS_PATH = ROOT_DIR / "data" / "tasks.json"

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def handle(user_input, ctx):
    user_name = ctx.get("user", {}).get("name", "未知")
    today = datetime.now().date()

    scope = _detect_scope(user_input)
    if scope == "today":
        target_date = today
        date_range = (target_date, target_date)
        label = "今天"
    elif scope == "tomorrow":
        target_date = today + timedelta(days=1)
        date_range = (target_date, target_date)
        label = "明天"
    elif scope == "week":
        target_date = today
        days_ahead = 7 - today.weekday()
        week_end = today + timedelta(days=days_ahead - 1)
        date_range = (today, week_end)
        label = "本周"
    else:
        target_date = today
        date_range = (target_date, target_date)
        label = "今天"

    tasks = _load_tasks()
    matched = _filter_tasks(tasks, date_range)
    daily_work = _get_daily_work(user_input, target_date)

    if not daily_work and not matched:
        week_day = WEEKDAY_ZH[target_date.weekday()]
        return f"[Cipher:task]\n{label} {target_date.strftime('%Y-%m-%d')} {week_day} 暂未找到进行中的任务。"

    # Build output directly — no LLM for formatting
    lines = []
    week_day = WEEKDAY_ZH[target_date.weekday()]
    lines.append(f"{user_name}，{target_date.strftime('%Y-%m-%d')} {week_day} {label}待办：")

    if daily_work:
        # Clean table markdown, bold syntax, empty sections
        raw = daily_work.replace("**", "").replace("（无）", "").replace("(无)", "")
        cleaned = []
        for line in raw.split("\n"):
            l = line.strip()
            if not l: continue
            if l.startswith(":") and all(c in ":-. —｜| " for c in l): continue
            if l.startswith("｜") and all(c in ":-. —｜| " for c in l): continue
            cleaned.append(l)
        # Filter empty section headers  
        filtered = []
        for i, l in enumerate(cleaned):
            if l.startswith("【") and l.endswith("】"):
                next_is_header = (i + 1 < len(cleaned) and cleaned[i+1].startswith("【"))
                if next_is_header or i + 1 >= len(cleaned):
                    continue
            filtered.append(l)
        lines.append("\n" + "\n".join(filtered))

    if matched:
        lines.append(f"\n📋 {label}任务 {len(matched)} 项：")
        for t in matched:
            deadline = t.get("deadline", "")
            dl_tag = f" ⏰{deadline}" if deadline else ""
            # Strip boilerplate prefix
            action = t['action']
            action = action.replace("督促铁炉西工班员工", "").strip()
            if not action:
                action = "相关任务"
            lines.append(f"\n  {action}{dl_tag}")
            for st in t.get("subtasks", []):
                mark = "✓" if st.get("done") else "○"
                name = st.get("assignee", "")
                sub_action = st['action']
                sub_action = sub_action.replace(f"通知{name}", "").replace("完成", "").strip()
                lines.append(f"    {mark} {name}{'　' if not sub_action else '：'+sub_action}")
        
        contacts = _extract_contacts(matched, daily_work)
        if contacts:
            lines.append(f"\n📞 {contacts.strip()}")

    return f"[Cipher:task]\n" + "\n".join(lines)


def _detect_scope(text):
    if "本周" in text or "这周" in text or "这星期" in text:
        return "week"
    if "明天" in text or "明日" in text:
        return "tomorrow"
    return "today"


def _load_tasks():
    if not TASKS_PATH.exists():
        return []
    try:
        return json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _filter_tasks(tasks, date_range):
    start, end = date_range
    active = []
    for t in tasks:
        if t.get("status") == "completed":
            continue
        active.append(t)
    return active


def _format_fallback(label, target_date, week_day="", tasks=None):
    lines = []
    if week_day:
        lines.append(week_day)
    if tasks:
        lines.append(f"\n{label} 进行中的任务 ({len(tasks)} 项)")
    return "\n".join(lines) if lines else f"{label} {target_date} 暂未找到进行中的任务。"


def _extract_contacts(matched_tasks, daily_work_text):
    from tools.shared.entity import load_entities
    entities = load_entities()
    name_role = {e["name"]: e.get("role", "") for e in entities}

    seen = set()
    lines = []

    for t in matched_tasks:
        action = t.get("action", "")
        action_tail = action[-10:] if len(action) > 10 else action
        for name, role in name_role.items():
            if name in seen:
                continue
            matched = False
            if name in action:
                matched = True
            elif len(name) >= 3 and name[:2] in action_tail:
                matched = True
            if matched:
                from organization.model import OrganizationModel
                org = OrganizationModel()
                team = set(org.get_members("李林骁"))
                team.add("李林骁")
                if name not in team:
                    lines.append(f"  {name}（{role}）— {_contact_context(name, action)}")
                    seen.add(name)

    if "危废" in daily_work_text or any("危废" in t.get("action", "") for t in matched_tasks):
        for name, role in name_role.items():
            if "危废" in role and name not in seen:
                lines.append(f"  {name}（{role}）— 危废处置协调")
                seen.add(name)

    return "\n".join(lines) if lines else ""


def _name_matches(full_name, text):
    if full_name in text:
        return True
    if len(full_name) >= 3 and full_name[:2] in text:
        return True
    return False


def _contact_context(name, action_text):
    if "危废" in action_text:
        return "危废处置协调"
    if any(kw in action_text for kw in ["补单", "送站", "查收", "办理"]):
        return "任务发起方"
    if "安全" in action_text:
        return "安全事项"
    if "消防" in action_text:
        return "消防安全"
    return "相关事项"


def _parse_duty_cycle(md: str):
    """Parse duty rotation from Knowledge markdown: sequence line + anchor table."""
    import re
    cycle = []
    anchor_date = None
    anchor_idx = -1

    for line in md.split("\n"):
        if "→" in line and not line.strip().startswith("|"):
            cycle = [n.strip() for n in line.strip().split("→")]
            break

    anchor_section = md.find("已知排班参照点")
    if anchor_section < 0 or not cycle:
        return cycle, None, -1

    table = []
    for line in md[anchor_section:].split("\n")[:15]:
        line = line.strip()
        if not line.startswith("|") or not line[1:].strip():
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}", cells[0][:10]):
            dt_str = cells[0][:10]
            name = cells[1].strip()
            try:
                d = datetime.strptime(dt_str, "%Y-%m-%d").date()
                if name in cycle:
                    anchor_date = d
                    anchor_idx = cycle.index(name)
                    break
            except ValueError:
                continue

    return cycle, anchor_date, anchor_idx


def _get_duty_person(target: date, md=None) -> str:
    """Calculate duty person from Knowledge markdown duty rotation rules."""
    if md is None:
        md_path = ROOT_DIR / "Knowledge" / "00-日常工作指引.md"
        if not md_path.exists():
            return "未知"
        md = md_path.read_text(encoding="utf-8")

    cycle, anchor_date, anchor_idx = _parse_duty_cycle(md)

    if not cycle or anchor_date is None or anchor_idx < 0:
        return "未知"

    delta = (target - anchor_date).days
    idx = (anchor_idx + delta) % len(cycle)
    return cycle[idx]


def _get_zone_chiefs(md: str) -> list[dict]:
    return _parse_table_section(md, "## 库区负责人")


def _get_material_shed(md: str, target: date) -> str:
    shed = _parse_table_section(md, "## 材料棚（轮值说明）")
    for row in shed:
        if not row.get("轮值期"):
            continue
        if "当前" in row.get("状态", ""):
            return f"材料棚轮换: {row.get('负责人', '')}（{row['轮值期']}）"
    return ""


def _get_flood_season(md: str, target: date) -> str:
    rows = _parse_table_section(md, "## 汛期附加")
    if not rows:
        return ""
    lines = ["【汛期附加工作】"]
    for row in rows:
        note = f" — {row.get('备注', '')}" if row.get('备注') else ""
        lines.append(f"  {row.get('#', '')}. {row.get('工作项', '')}{note}")
    return "\n".join(lines)


def _get_daily_work(user_input, target_date):
    """Parse Knowledge/00-日常工作指引.md for today/tomorrow/week routines."""
    md_path = ROOT_DIR / "Knowledge" / "00-日常工作指引.md"
    if not md_path.exists():
        return ""
    md = md_path.read_text(encoding="utf-8")

    target = target_date
    weekday_zh = ["周一","周二","周三","周四","周五","周六","周日"][target.weekday()]

    lines_out = []

    # 值班
    duty_person = _get_duty_person(target, md=md)
    lines_out.append("【值班】")
    lines_out.append(f"  当日值班人员: {duty_person}（参照'今日我值班工作提示卡'）")

    # 库区负责人
    lines_out.append("")
    lines_out.append("【库区负责人】")
    zones = _get_zone_chiefs(md)
    for row in zones:
        lines_out.append(f"  {row.get('库区', '')} — {row.get('负责人', '')}")

    # 材料棚轮换
    shed = _get_material_shed(md, target)
    if shed:
        lines_out.append("")
        lines_out.append(f"【材料棚轮换】")
        lines_out.append(f"  {shed}")

    # 汛期附加
    flood = _get_flood_season(md, target)
    if flood:
        lines_out.append("")
        lines_out.append(flood)

    # 每日
    lines_out.append("")
    lines_out.append("【每日固定工作】")
    daily = _parse_table_section(md, "## 每日")
    for row in daily:
        lines_out.append(f"  {row.get('#', '')}. {row.get('工作项', '')} — {row.get('负责人', '')}")

    # 每周五
    if target.weekday() == 4:
        lines_out.append("")
        lines_out.append("【每周五固定工作】")
        weekly = _parse_table_section(md, "## 每周五")
        for row in weekly:
            lines_out.append(f"  {row.get('#', '')}. {row.get('工作项', '')} — {row.get('负责人', '')}")

    # 每月固定日期
    day = target.day
    lines_out.append("")
    lines_out.append(f"【本月{day}日固定工作】")
    monthly = _parse_monthly_table(md, "## 每月固定日期")
    matched = [r for r in monthly if r.get("日期") == f"{day}日"]
    if matched:
        for row in matched:
            lines_out.append(f"  {row.get('#', '')}. {row.get('工作项', '')} — {row.get('负责人', '')}")
    else:
        lines_out.append("  （无）")

    # 本月演练
    mon = target.month
    for line in md.split("\n"):
        if "应急演练" in line and "月份" in line:
            continue
        if f"{mon}月" in line and "应急演练" in line:
            exercise = line.strip().lstrip("|").split("|")
            if len(exercise) >= 3:
                lines_out.append("")
                lines_out.append(f"【本月演练】{exercise[1].strip()} — {exercise[2].strip()}")

    return "\n".join(lines_out)


def _parse_table_section(md, section_header):
    """Parse a markdown table section into list of dicts."""
    import re as _re
    pos = md.find(section_header)
    if pos < 0:
        return []
    section = md[pos:].split("\n## ")[0]
    lines = section.split("\n")
    headers = None
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if headers is None:
            headers = cells
        else:
            if len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
    return rows


def _parse_monthly_table(md, section_header):
    """Parse monthly table (day-based) into list of dicts."""
    import re as _re
    pos = md.find(section_header)
    if pos < 0:
        return []
    section = md[pos:].split("\n## ")[0]
    lines = section.split("\n")
    headers = None
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if headers is None:
            headers = cells
        else:
            if len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
    return rows
