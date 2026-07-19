"""
section_parser.py — Document Structure Splitter (Phase 1.7.7-A)

纯规则：将通知/消息切分为结构化 Section 列表。
不涉及 AI，不涉及语义理解。只做切块。

规则:
  - 【xxx】  → 独立 section title
  - 一、/ 一） / （一） → section title
  - 空行 → section 边界
  - 不拆：首先/其次/此外/另外/同时/然后/最后/接着
  - 无标题段落 → 归入最近的 section 或 header(S0)
  - 连续两个 title 行且第一节无内容 → 第二个当 content 而非替换
"""

import re

TITLE_MARKER = re.compile(
    r"^(?:"
    r"【[^】]+】"                                    # 【通知】
    r"|"
    r"[（(][一二三四五六七八九十]+[）)]"               # （一）
    r"|"
    r"[一二三四五六七八九十]{1,3}\s*[、.，。．)）]"     # 一、 二） 十．
    r")"
)

NON_SPLIT = {"首先", "其次", "此外", "另外", "同时", "然后", "最后", "接着"}


def _is_title(line):
    stripped = line.strip().lstrip("\u3000 ")
    if not stripped:
        return False
    for w in NON_SPLIT:
        if stripped.startswith(w):
            return False
    if TITLE_MARKER.match(stripped):
        return True
    return False


def parse_sections(text, parent_event="", target_role=""):
    if not text or not text.strip():
        return [_make_section(0, "header", "", parent_event, target_role)]

    lines = text.split("\n")
    sections = []
    current_title = None
    current_lines = []

    def flush():
        nonlocal current_title, current_lines
        if current_title is not None:
            title = current_title
            level = 0 if title == "header" else 1
            sections.append(_make_section(
                len(sections), title,
                "\n".join(current_lines).strip(),
                parent_event, target_role, level,
            ))
            current_title = None
            current_lines = []

    header_buf = []

    for line in lines:
        stripped = line.strip().replace("\u3000", " ").replace("\u00a0", " ")

        if not stripped:
            current_title = current_title or "header"
            if current_lines:
                current_lines.append("")
            continue

        if _is_title(stripped):
            flush()
            current_title = stripped
            current_lines = []
        else:
            if current_title is None:
                header_buf.append(stripped)
            else:
                current_lines.append(stripped)

    flush()

    # Prepend header
    if header_buf:
        sections.insert(0, _make_section(
            0, "header",
            "\n".join(header_buf).strip(),
            parent_event, target_role, 0,
        ))
        for i, s in enumerate(sections):
            s["section_id"] = f"S{i}"

    if not sections:
        sections.append(_make_section(
            0, "header", text.strip(),
            parent_event, target_role, 0,
        ))

    return sections


def _make_section(idx, title, content, parent_event, target_role, level=1):
    return {
        "section_id": f"S{idx}",
        "section_title": title,
        "content": content,
        "level": level,
        "parent_event": parent_event,
        "target_role": target_role,
    }


def parse(text, parent_event="", target_role=""):
    return {"sections": parse_sections(text, parent_event, target_role)}
