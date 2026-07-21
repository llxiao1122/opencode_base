#!/usr/bin/env python3
"""
state_analyzer — DEPRECATED: 无调用方 - 管理分析 + 报告生成
流程: state/_index.md关键词→文件映射 → 只读命中文件 → 回退全读
"""
import sys
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = ROOT / "state"
MEMORY_DIR = ROOT / "memory"
INDEX_FILE = STATE_DIR / "_index.md"

KEYWORD_FILE_MAP = {
    "台账": ["org.md"],
    "安全": ["org.md"],
    "消防": ["org.md"],
    "领导": ["leaders.md"],
    "上级": ["leaders.md"],
    "汇报": ["leaders.md"],
    "分工": ["org.md"],
    "审批": ["org.md"],
    "排班": ["org.md"],
    "准则": ["rules.md"],
    "判断": ["rules.md"],
    "压力": ["rules.md"],
    "底线": ["rules.md"],
    "认知": ["cognition.md"],
    "思维": ["cognition.md"],
    "情绪": ["cognition.md"],
    "会议": ["leaders.md"],
    "纪要": ["leaders.md"],
}

ALL_STATE_FILES = ["cognition.md", "leaders.md", "org.md", "rules.md"]


def read_file_safe(fpath, max_len=3000):
    if not fpath.exists():
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError) as e:
        return f"⚠️ 文件读取失败: {type(e).__name__}: {e}"
    if len(content) > max_len:
        return content[:max_len] + "\n... (已截断)"
    return content


def resolve_files(user_input):
    """根据用户输入匹配要读的state文件"""
    matched = set()
    for keyword, files in KEYWORD_FILE_MAP.items():
        if keyword in user_input:
            matched.update(files)
    if matched:
        return sorted(matched)
    return ALL_STATE_FILES


def read_state_files(user_input):
    files = resolve_files(user_input)
    result = {}
    for fname in files:
        fpath = STATE_DIR / fname
        content = read_file_safe(fpath)
        if content:
            result[fname] = content
        else:
            result[fname] = f"⚠️ 文件不存在: {fname}"
    return result, files


def read_meeting_notes():
    fpath = MEMORY_DIR / "meeting-notes.md"
    if fpath.exists():
        return read_file_safe(fpath, max_len=2000)
    return None


def is_report_mode(user_input):
    keywords = ["写", "生成", "整理", "汇报", "会议纪要", "讲话稿", "总结", "简报", "报告"]
    return any(kw in user_input for kw in keywords)


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    user_input = " ".join(args) if args else ""

    if not user_input and not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
            if data:
                parsed = json.loads(data)
                user_input = parsed.get("query", "")
        except:
            pass

    if not user_input:
        print(json.dumps({"status": "error", "message": "请提供分析或报告需求"}, ensure_ascii=False))
        sys.exit(1)

    state_data, loaded_files = read_state_files(user_input)
    meeting_notes = read_meeting_notes()

    mode = "report" if is_report_mode(user_input) else "analysis"

    result = {
        "status": "success",
        "mode": mode,
        "user_query": user_input,
        "loaded_files": loaded_files,
        "data": state_data,
        "meeting_notes": meeting_notes,
    }

    if mode == "report":
        result["generated_at"] = datetime.now().isoformat()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
