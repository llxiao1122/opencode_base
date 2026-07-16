#!/usr/bin/env python3
"""
event_recorder - 统一录制入口
所有状态变更事件都必须经过此模块，保证 log / member / observation 不遗漏。
"""
import sys, os, json, subprocess
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = "/home/admin/opencode"
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
OBS_DIR = os.path.join(PROJECT_ROOT, "memory/observations")
STATE_DIR = os.path.join(PROJECT_ROOT, "state")


def _read_file(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _append_file(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run_tool(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=PROJECT_ROOT, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""


def append_log(text):
    os.makedirs(LOGS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M")
    _append_file(os.path.join(LOGS_DIR, f"{today}.log"), f"{today} {ts} {text}")


def _update_member_portrait(name, content_tag):
    index_path = os.path.join(STATE_DIR, "_index.md")
    content = _read_file(index_path)
    filepath = None
    for line in content.split("\n"):
        if "→" not in line or line.strip().startswith("#"):
            continue
        parts = line.split("→")
        if len(parts) == 2 and parts[0].strip() == name:
            fpath = parts[1].strip()
            if fpath.startswith("members/"):
                filepath = os.path.join(STATE_DIR, fpath)
            break
    if not filepath:
        return
    current = _read_file(filepath)
    if not current:
        return
    base = content_tag
    tag = ""
    if "(" in base and base.endswith(")"):
        idx = base.rindex("(")
        tag = f" {base[idx+1:-1]}"
        base = base[:idx].strip()
    month_cn = datetime.now().strftime("%m月")
    entry = f"- {base}({tag.strip()} {month_cn})" if tag else f"- {base}({month_cn})"
    if entry in current:
        return
    eval_marker = "## 评价"
    eval_idx = current.find(eval_marker)
    if eval_idx >= 0:
        after = current[eval_idx + len(eval_marker):]
        next_sec = after.find("\n## ")
        if next_sec >= 0:
            ipos = eval_idx + len(eval_marker) + next_sec
            current = current[:ipos] + f"\n{entry}" + current[ipos:]
        else:
            current = current.rstrip() + f"\n{entry}\n"
    else:
        current = current.rstrip() + f"\n\n{eval_marker}\n{entry}\n"
    _write_file(filepath, current)


def _write_observation(topic, content):
    os.makedirs(OBS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    fpath = os.path.join(OBS_DIR, f"{today}.md")
    _append_file(fpath, f"- {topic}: {content}\n")


def record(category, desc, members=None, write_obs=False):
    """
    统一录制入口

    category: [分配][人员][任务][风险][汇报][外部][系统]
    desc: 事件描述
    members: ["陈红洁"] 或 None — 触发 member portrait 更新
    write_obs: 是否写入 observation
    """
    append_log(f"{category} {desc}")
    if members:
        for m in members:
            _update_member_portrait(m, desc[:80])
    if write_obs:
        _write_observation(desc[:20], desc[:200])


def main():
    """CLI 调用: record.py <category> <desc> [--members 张三,李四] [--obs]"""
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args:
        print('用法: record.py <分类> <描述> [--members 张三,李四] [--obs]')
        sys.exit(1)

    category = args[0]
    desc_parts = []
    members = None
    write_obs = False
    i = 1
    while i < len(args):
        if args[i] == "--members":
            i += 1
            if i < len(args):
                members = [m.strip() for m in args[i].split(",")]
        elif args[i] == "--obs":
            write_obs = True
        else:
            desc_parts.append(args[i])
        i += 1

    desc = " ".join(desc_parts) if desc_parts else ""
    if not desc:
        print("错误: 请提供描述")
        sys.exit(1)

    record(category, desc, members=members, write_obs=write_obs)
    print(json.dumps({"status": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
