import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OBS_DIR = ROOT / "data" / "memory" / "observations" / "people"


def handle(name: str, ctx=None) -> str:
    lines = []
    role = "未知"

    entity_name = name
    try:
        from skills.router.entity_resolver import resolve_entities
        resolved = resolve_entities(name)
        if resolved.get("entities"):
            info = resolved["entities"][0]
            entity_name = info.get("name", name)
            role = info.get("role", "未知")
            lines.append(f"{entity_name}: {role}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("profile_query resolve failed: %s", e, exc_info=True)

    if not lines:
        if ctx and ctx.user:
            user = ctx.user
            entity_name = user.get("name", name)
            role = user.get("role", "工班长")
            lines.append(f"{entity_name}：{role}")
        else:
            return f"[Cipher:profile]\n暂无 {name} 的相关记录。"

    recent = _recent_observations(entity_name)
    if recent:
        lines.append("")
        lines.append("近期动态：")
        lines.extend(recent)

    return "[Cipher:profile]\n" + "\n".join(lines)


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
