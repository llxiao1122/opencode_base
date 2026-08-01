import re
from datetime import datetime
from pathlib import Path

from skills.shared.path import root as _root
ROOT = _root()
OBS_DIR = ROOT / "data" / "memory" / "observations" / "people"
WORLDVIEW_DIR = ROOT / "data" / "state" / "worldview" / "entities"


def handle(text: str, ctx=None) -> str:
    # 解析输入中提到的实体名
    entity_name = text
    try:
        from skills.router.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        if resolved.get("entities"):
            entity_name = resolved["entities"][0].get("name", text)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("profile_query resolve failed: %s", e)

    # 先尝试从世界观档案读
    worldview_path = WORLDVIEW_DIR / f"{entity_name}.md"
    if worldview_path.exists():
        content = worldview_path.read_text(encoding="utf-8")
        sections = _extract_sections(content, ["基本信息", "行为模式", "近期事件"])
        lines = [f"📋 {entity_name} 档案"]
        for sec in sections:
            lines.append("")
            lines.extend(sec)
        # 世界观档案"近期事件"为空占位时，补观测库动态
        event_sections = _extract_sections(content, ["近期事件"])
        is_placeholder = any(
            l.strip() in ("（待 bootstrap 更新）", "") for sec in event_sections for l in sec
        ) if event_sections else True
        recent = _recent_observations(entity_name)
        if is_placeholder and recent:
            lines.append("")
            lines.append("近期动态：")
            lines.extend(recent)
        return "[Cipher:profile]\n" + "\n".join(lines)

    # 无世界观档案，fallback 到 observations
    lines = []
    role = "未知"
    try:
        resolved = resolve_entities(text)
        if resolved.get("entities"):
            info = resolved["entities"][0]
            entity_name = info.get("name", text)
            role = info.get("role", "未知")
            lines.append(f"{entity_name}: {role}")
    except Exception as e:
        logging.getLogger(__name__).warning("profile_query resolve failed: %s", e)

    if not lines:
        if ctx and ctx.user:
            user = ctx.user
            entity_name = user.get("name", text)
            role = user.get("role", "工班长")
            lines.append(f"{entity_name}：{role}")
        else:
            return f"[Cipher:profile]\n暂无 {text} 的相关记录。"

    recent = _recent_observations(entity_name)
    if recent:
        lines.append("")
        lines.append("近期动态：")
        lines.extend(recent)

    return "[Cipher:profile]\n" + "\n".join(lines)


def _extract_sections(content: str, wanted: list[str]) -> list[list[str]]:
    result = []
    current_section = ""
    current_lines = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_section in wanted:
                result.append(current_lines)
            current_section = line.strip("## #").strip()
            current_lines = [line]
        elif current_section in wanted:
            current_lines.append(line)
    if current_section in wanted:
        result.append(current_lines)
    return result


def _recent_obs_files(name: str) -> list[dict]:
    fp = OBS_DIR / f"{name}.md"
    if not fp.exists():
        return []
    content = fp.read_text(encoding="utf-8")
    sections = re.split(r"\n---\n", content)
    entries = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        date_m = re.search(r"## (\d{4}-\d{2}-\d{2})", sec)
        source_m = re.search(r"source:\s*(\S+)", sec)
        summary_m = re.search(r"### Summary\s*\n(.+)", sec)
        if date_m and summary_m:
            summary = summary_m.group(1).strip()
            source = source_m.group(1) if source_m else ""
            if source == "pattern_miner":
                continue
            entries.append({
                "date": date_m.group(1),
                "source": source,
                "summary": summary,
            })
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:5]


def _recent_observations(name: str) -> list[str]:
    entries = _recent_obs_files(name)
    if not entries:
        return []
    out = []
    for e in entries:
        out.append(f"  [{e['date']}] {e['summary']}")
    return out
