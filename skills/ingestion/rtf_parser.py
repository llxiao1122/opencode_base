"""
ingestion/rtf_parser.py — RTF → plain text converter for DingTalk exports.

Handles Cocoa RTF exports (macOS DingTalk) with \\uNNNNN Unicode escapes.
Output: plain text suitable for message_parser.parse().
"""

import re
from pathlib import Path


def rtf_to_text(rtf_content: str) -> str:
    """Convert RTF with Unicode escapes to plain text.

    Args:
        rtf_content: raw RTF string from .rtf file

    Returns:
        plain text with Chinese characters restored, ready for message_parser
    """
    # Strip RTF header (everything up to the first \\uc0 content line)
    # The header ends roughly at the first \\f0\\fs24 line
    lines = rtf_content.splitlines()

    content_lines = []
    in_content = False

    # Skip RTF preamble lines
    header_seps = {"\\f0\\fs24", "\\f0\\fs26", "\\f0\\fs28", "\\pard"}

    for line in lines:
        stripped = line.strip()
        if not in_content:
            if any(stripped.startswith(s) for s in header_seps) or stripped.endswith("\\cf0"):
                in_content = True
                # Extract content from this line (after the prefix)
                for s in header_seps:
                    if stripped.startswith(s):
                        stripped = stripped[len(s):].lstrip()
                        break
                if stripped:
                    content_lines.append(stripped)
                continue
            # Also check if line starts with data directly
            if stripped.startswith("\\uc0"):
                in_content = True

        if in_content:
            content_lines.append(stripped)

    text = "\n".join(content_lines)

    # Convert \\uNNNNN Unicode escapes to characters
    def _unicode_replace(match):
        codepoint = int(match.group(1))
        return chr(codepoint)

    text = re.sub(r"\\u(\d{3,6})\s?", _unicode_replace, text)

    # Remove remaining RTF control sequences
    text = re.sub(r"\\uc\d+", "", text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)  # hex escapes
    text = re.sub(r"\\[a-z]+\d*\s?", " ", text)      # other RTF commands
    text = re.sub(r"\\\s*$", "", text, flags=re.MULTILINE)  # trailing backslash
    text = re.sub(r"\s*\\cf\d+\s*", " ", text)
    text = re.sub(r"\s*\\pard[a-z]*\s*", "\n", text)

    # Normalize: multiple spaces → one, blank lines → one
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^\s+", "", text, flags=re.MULTILINE)

    return text.strip()


def parse_rtf(filepath: str) -> list:
    """Parse RTF file into Message dicts (same format as message_parser.parse).

    Args:
        filepath: path to .rtf file

    Returns:
        list of Message dicts: [{id, timestamp, sender, content, source}]
    """
    from ingestion.message_parser import parse

    raw = Path(filepath).read_text(encoding="utf-8")
    plain = rtf_to_text(raw)
    return parse(plain)
