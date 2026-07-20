"""
ingestion/flomo_parser.py — Flomo HTML export → thoughts.jsonl converter.

Extracts full text from flomo memos. No truncation. Fixes tag extraction.
"""

import re, json
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

# CSS color codes mistakenly captured as tags
_COLOR_FILTER = {"9d9d9d", "efefef", "fff", "7d7d7d", "dddddd", "fafafa",
                  "454545", "bababa", "4f4f4f", "3d3d3d"}


def parse(html_path: str) -> list:
    html = Path(html_path).read_text(encoding="utf-8")
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    dates = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", html)
    blocks = re.split(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", html)

    entries = []
    for i, block in enumerate(blocks[1:]):
        if i >= len(dates):
            break
        ts = dates[i]

        # Extract full text content (no truncation)
        content = re.sub(r"<[^>]+>", " ", block).strip()
        content = re.sub(r"\s+", " ", content)

        # Extract and clean tags
        tag_matches = re.findall(r"#([\u4e00-\u9fff\w/]+)", content)
        clean_tags = [t for t in tag_matches if t not in _COLOR_FILTER]

        # Map to type
        thought_type = "observation"
        for tag, ttype in TAG_MAP.items():
            if tag in clean_tags:
                thought_type = ttype
                break

        # Clean content (remove tags from displayed text)
        clean_content = content
        for tag_name in clean_tags:
            clean_content = clean_content.replace(f"#{tag_name}", "").strip()
        clean_content = re.sub(r"\s+", " ", clean_content)

        if not clean_content or len(clean_content) < 3:
            continue

        entries.append({
            "time": ts,
            "type": thought_type,
            "content": clean_content,  # Full text, no truncation
            "tags": clean_tags,
            "source": "flomo_import",
            "confidence": 0.9,
        })

    return entries


def import_flomo(html_path: str = None):
    if html_path is None:
        html_path = str(ROOT / "data" / "flomo_export.html")

    entries = parse(html_path)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"Imported {len(entries)} thoughts → {OUTPUT_PATH}")
    return entries
