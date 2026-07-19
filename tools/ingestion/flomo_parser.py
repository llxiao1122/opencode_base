"""
ingestion/flomo_parser.py — Flomo HTML export → thoughts.jsonl converter.

One-time use. Extracts 72 memos from flomo HTML export,
maps tags to thought types, writes data/personal/thoughts.jsonl.
"""

import re
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = ROOT / "data" / "personal" / "thoughts.jsonl"

TAG_MAP = {
    "思维/实现自我": "belief",
    "思维/工作": "strategy",
    "日记": "observation",
    "读书/天幕红尘": "note",
    "读书": "note",
    "疑惑": "concern",
    "素材": "reference",
    "影视/摄影": "reference",
    "影视/剪辑": "reference",
    "影视/待看": "reference",
    "影视/指南": "reference",
    "学习/经济学": "reference",
    "娱乐": "reference",
}


def parse(html_path: str) -> list:
    """Parse flomo HTML export into thought entries."""
    html = Path(html_path).read_text(encoding="utf-8")

    # Remove CSS/style blocks
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # Extract timestamps
    dates = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", html)

    # Split by date markers
    blocks = re.split(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", html)
    # blocks[0] is header, each subsequent block is memo content

    entries = []
    for i, block in enumerate(blocks[1:]):
        if i >= len(dates):
            break
        ts = dates[i]
        content = re.sub(r"<[^>]+>", " ", block).strip()
        content = re.sub(r"\s+", " ", content)

        # Extract tags
        tags = re.findall(r"#([\u4e00-\u9fff\w/]+)", content)
        clean_tags = [t for t in tags if t not in ("9d9d9d", "efefef", "fff", "7d7d7d", "dddddd", "fafafa", "454545", "bababa", "4f4f4f", "3d3d3d")]

        # Find thought type
        thought_type = "observation"
        for tag, ttype in TAG_MAP.items():
            if tag in clean_tags:
                thought_type = ttype
                break

        # Clean content (remove tags from text)
        clean_content = content
        for tag_name in clean_tags:
            clean_content = clean_content.replace(f"#{tag_name}", "").strip()
        clean_content = re.sub(r"\s+", " ", clean_content)

        if not clean_content or len(clean_content) < 3:
            continue

        entries.append({
            "time": ts,
            "type": thought_type,
            "content": clean_content[:500],
            "tags": clean_tags,
            "source": "flomo_import",
            "confidence": 0.9,
        })

    return entries


def import_flomo(html_path: str = None):
    """Import flomo HTML and write thoughts.jsonl."""
    if html_path is None:
        html_path = str(ROOT / "data" / "flomo_export.html")

    entries = parse(html_path)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"Imported {len(entries)} thoughts → {OUTPUT_PATH}")
    return entries
