"""
knowledge/processor.py — Markdown structure parser + chunker.

Preserves section hierarchy: # → ## → ### → text.
Splits at header boundaries, max 500 chars per chunk.
Does not break list items mid-section.
"""

import re
from pathlib import Path

HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s|^\s*\d+[.、]\s")
MAX_CHUNK = 500


def process(filepath: str) -> list:
    """Parse and chunk a markdown file into knowledge blocks.

    Args:
        filepath: path to .md file

    Returns:
        [{section_path: [str, ...], text: str, type: str}, ...]
    """
    try:
        text = open(filepath, "r", encoding="utf-8").read()[:100000]
    except Exception:
        return []

    if not text.strip():
        return []

    sections = _split_by_headers(text)
    chunks = []
    section_path = []
    meta = _extract_metadata(filepath)
    file_title = meta["title"]

    for header, body in sections:
        level, title = header
        section_path = section_path[:level - 1]
        section_path.append(title)

        body_paras = _split_paragraphs(body)
        current = ""
        for para in body_paras:
            combined = (current + "\n" + para).strip() if current else para
            if len(combined) <= MAX_CHUNK:
                current = combined
            else:
                if current:
                    chunks.append(_make_chunk(section_path, current, file_title, meta))
                current = para
        if current:
            chunks.append(_make_chunk(section_path, current, file_title, meta))

    if not chunks and text.strip():
        chunks.append(_make_chunk([file_title], text.strip()[:MAX_CHUNK], file_title, meta))

    return chunks


def _split_by_headers(text: str) -> list:
    """Split markdown text into (header, body) pairs by H1-H6."""
    lines = text.split("\n")
    sections = []
    current_header = (1, "")
    current_body = []

    for line in lines:
        m = HEADER_RE.match(line)
        if m:
            if current_body:
                body_text = "\n".join(current_body).strip()
                sections.append((current_header, body_text))
            level = len(m.group(1))
            current_header = (level, m.group(2).strip())
            current_body = []
        else:
            current_body.append(line)

    if current_body or current_header[1]:
        sections.append((current_header, "\n".join(current_body).strip()))

    return sections


def _split_paragraphs(body: str) -> list:
    """Split body text into paragraphs, keeping list items grouped."""
    raw = body.strip()
    if not raw:
        return []

    parts = re.split(r"\n\n+", raw)
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > MAX_CHUNK:
            sub = re.split(r"\n(?=[^\s])", p)
            for s in sub:
                s = s.strip()
                if s:
                    result.append(s)
        else:
            result.append(p)
    return result


def _make_chunk(section_path: list, text: str, file_title: str, meta: dict) -> dict:
    return {
        "section_path": list(section_path),
        "text": text,
        "type": _infer_type(section_path, file_title),
        "version": meta["version"],
        "base_name": meta["base_name"],
        "status": meta["status"],
    }


def _extract_metadata(filepath: str) -> dict:
    """Extract version, base_name, and lifecycle status from filename.

    Patterns:
        "05-安全管理.md"          → base_name="安全管理", version="v1", active
        "05-安全管理_v2.md"       → base_name="安全管理", version="v2", active
        "消防管理办法(2026版).md"  → base_name="消防管理办法", version="2026", active
        "旧制度_废止.md"          → base_name="旧制度", version="v1", deprecated
    """
    name = Path(filepath).stem

    deprecated = False
    version = "v1"

    for kw in ["废止", "作废", "废弃", "过期"]:
        if kw in name:
            deprecated = True
            name = name.replace(f"_{kw}", "").replace(f"({kw})", "").replace(f"（{kw}）", "").replace(kw, "")
            break

    v_match = re.search(r"[_\(（][vV](\d+)[_\)）]?", name)
    if v_match:
        version = f"v{v_match.group(1)}"
        name = name[:v_match.start()] + name[v_match.end():]

    yr_match = re.search(r"[\(（](\d{4})版[\)）]", name)
    if yr_match:
        version = yr_match.group(1)
        name = name[:yr_match.start()] + name[yr_match.end():]
    if not v_match:
        yr_match2 = re.search(r"_(\d{4})版", name)
        if yr_match2:
            version = yr_match2.group(1)
            name = name[:yr_match2.start()] + name[yr_match2.end():]

    base_name = re.sub(r"^\d{1,2}[-_]", "", name).strip("-_")
    base_name = re.sub(r"_{2,}", "_", base_name)

    return {
        "title": base_name,
        "base_name": base_name,
        "version": version,
        "deprecated": deprecated,
        "status": "deprecated" if deprecated else "active",
    }


# Removed _extract_title — replaced by _extract_metadata above.


def _infer_type(section_path: list, file_title: str) -> str:
    """Infer knowledge type from section path and content hints."""
    combined = " ".join(section_path).lower() + " " + file_title.lower()
    if any(w in combined for w in ["制度", "规定", "办法", "管理", "规程"]):
        return "rule"
    if any(w in combined for w in ["流程", "步骤", "操作", "指南"]):
        return "procedure"
    if any(w in combined for w in ["模板", "表格", "格式", "范文"]):
        return "template"
    if any(w in combined for w in ["预案", "应急"]):
        return "procedure"
    return "reference"
