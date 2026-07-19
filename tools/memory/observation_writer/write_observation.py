#!/usr/bin/env python3
"""
observation_writer - 写入观察记录
写: memory/observations/{日期}.md (追加)
自动刷新 observations/_index.md
"""
import sys
import json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OBS_DIR = ROOT / "memory" / "observations"
INDEX_FILE = OBS_DIR / "_index.md"


def write_observation(topic, content):
    topic = topic.replace("/", "_").replace("..", "_")
    OBS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    fpath = OBS_DIR / f"{today}.md"
    entry = f"- {topic}: {content}\n"

    with open(fpath, "a", encoding="utf-8") as f:
        f.write(entry)

    refresh_index()

    return str(fpath)


def refresh_index():
    if not OBS_DIR.exists():
        return

    members = set()
    index_entries = []

    for fpath in sorted(OBS_DIR.glob("*.md"), reverse=True):
        if fpath.name.startswith("_"):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("- ") and ":" in line:
                    name = line[2:].split(":")[0].strip()
                    if name and name not in members:
                        members.add(name)
                        index_entries.append(f"{name} → {fpath.name}")
                        if len(index_entries) >= 20:
                            break

    content = "# 观察记录索引\n" + "\n".join(index_entries) + "\n"

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args and not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read())
            args = [data.get("topic", ""), data.get("content", "")]
        except:
            pass
    if len(args) < 2:
        print(json.dumps({"status": "error", "message": "用法: write_observation.py <主题> <内容>"}, ensure_ascii=False))
        sys.exit(1)
    fpath = write_observation(args[0], args[1])
    print(json.dumps({"status": "ok", "file": fpath}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
