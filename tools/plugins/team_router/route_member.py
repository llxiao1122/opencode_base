#!/usr/bin/env python3
"""
team_router - 成员画像查询
流程: state/_index.md查映射 → 读成员文件 → 自动查观察记录
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import date

STATE_DIR = Path("/home/admin/opencode/state")
OBS_DIR = Path("/home/admin/opencode/memory/observations")
INDEX_FILE = STATE_DIR / "_index.md"


def resolve_member_file(member_name):
    """从 _index.md 查成员→文件映射"""
    r = subprocess.run(
        ["grep", f"^{member_name} ", str(INDEX_FILE)],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            if "→" in line:
                fname = line.split("→")[-1].strip()
                member_file = STATE_DIR / fname
                if member_file.exists():
                    return member_file
    return None


def read_member_profile(member_file):
    with open(member_file, "r", encoding="utf-8") as f:
        return f.read().strip()


def grep_observations(member_name, limit=5):
    if not OBS_DIR.exists():
        return []

    r = subprocess.run(
        ["grep", "-r", "-l", member_name, str(OBS_DIR)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return []

    files = []
    for f in r.stdout.strip().split("\n"):
        f = f.strip()
        if f and not f.endswith("/_index.md") and f.endswith(".md"):
            files.append(f)

    results = []
    for fpath in sorted(files, reverse=True)[:limit]:
        with open(fpath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        relevant = []
        for line in lines:
            if member_name in line and line.strip().startswith("-"):
                relevant.append(line.strip())
        if relevant:
            results.append({"file": fpath, "entries": relevant})

    return results


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    member_name = " ".join(args) if args else ""

    if not member_name and not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
            if data:
                parsed = json.loads(data)
                member_name = parsed.get("query", "")
        except:
            pass

    if not member_name:
        print(json.dumps({"status": "error", "message": "请提供成员姓名"}, ensure_ascii=False))
        sys.exit(1)

    member_file = resolve_member_file(member_name)

    if not member_file:
        print(json.dumps({"status": "not_found", "member": member_name,
                          "message": f"未在 state/_index.md 中找到 {member_name}"}, ensure_ascii=False))
        return

    profile = read_member_profile(member_file)
    observations = grep_observations(member_name)

    result = {
        "status": "success",
        "member": member_name,
        "profile": profile,
        "observations": observations,
        "obs_count": len(observations)
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
