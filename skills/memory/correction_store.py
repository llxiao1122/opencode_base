"""
memory/correction_store.py — 系统自身成长纠错库。

纠错独立于人员/流程档案存储（data/state/worldview/纠错.md），
会话应答前由 engine.run() 全文加载，作为系统常驻记忆。

结构：
  # 纠错库
  ## YYYY-MM-DD
  - **纠错**：原文
  - **纠正**：原文
"""

import logging
import re
from pathlib import Path
from datetime import date

logger = logging.getLogger(__name__)

from skills.shared.path import root as _root
ROOT = _root()
CORRECTIONS_PATH = ROOT / "data" / "state" / "worldview" / "纠错.md"

_MAX_ENTRY_CHARS = 120
_MAX_ENTRIES = 200


def _load_lines() -> list[str]:
    if not CORRECTIONS_PATH.exists():
        return []
    try:
        return CORRECTIONS_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.debug("correction store read failed: %s", e)
        return []


def load_recent(limit: int = 20) -> list[dict]:
    """返回最近 N 条纠错：{date, text}。按文件倒序取最后 limit 条。"""
    lines = _load_lines()
    entries = []
    cur_date = ""
    for line in lines:
        line = line.rstrip()
        m = re.match(r"^## (\d{4}-\d{2}-\d{2})$", line.strip())
        if m:
            cur_date = m.group(1)
            continue
        m = re.match(r"^-\s+\*\*(纠错|纠正)\*\*[:：]\s*(.+)$", line.strip())
        if m:
            entries.append({"date": cur_date, "kind": m.group(1), "text": m.group(2).strip()})
    return entries[-limit:]


def append(text: str) -> bool:
    """追加一条纠错到当日分节，按内容去重，限长。返回是否新增。"""
    if not text or len(text.strip()) < 5:
        return False
    entry_text = text.strip().split("\n")[0][:_MAX_ENTRY_CHARS]
    key = entry_text[:40].split("（来源：")[0]

    existing = load_recent(limit=_MAX_ENTRIES)
    for e in existing:
        if e["text"][:40].split("（来源：")[0] == key:
            return False

    today = date.today().isoformat()
    lines = _load_lines()
    if not lines or not any(re.match(r"^## \d{4}-\d{2}-\d{2}$", l.strip()) for l in lines):
        if lines and lines[0].startswith("# "):
            base = lines[:1]
            body = lines[1:]
            new_block = [f"\n## {today}\n", f"- **纠错**：{entry_text}"]
            lines = base + new_block + body
        else:
            lines = [f"# 纠错库\n", f"\n## {today}\n", f"- **纠错**：{entry_text}"]
    else:
        insert_at = len(lines)
        for i, l in enumerate(lines):
            if re.match(rf"^## {re.escape(today)}$", l.strip()):
                insert_at = i + 1
                while insert_at < len(lines) and not re.match(
                        r"^## \d{4}-\d{2}-\d{2}$", lines[insert_at].strip()):
                    insert_at += 1
                break
        if not any(re.match(rf"^## {re.escape(today)}$", l.strip()) for l in lines):
            lines.append(f"\n## {today}\n")
            insert_at = len(lines)
        lines.insert(insert_at, f"- **纠错**：{entry_text}")

    try:
        CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CORRECTIONS_PATH.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("correction append failed: %s", e, exc_info=True)
        return False


def count() -> int:
    return len(load_recent(limit=_MAX_ENTRIES))
