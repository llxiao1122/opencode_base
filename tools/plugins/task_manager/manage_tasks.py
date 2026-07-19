#!/usr/bin/env python3
"""
task_manager - 工作安排单文件管理
支持：按日期记录、按日期查询、标记完成、清理已完结
"""
import sys
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

TASK_FILE = Path("/home/admin/opencode/memory/tasks.md")

# ============================================================
# 1. 文件读写
# ============================================================

def ensure_task_file():
    """确保文件存在，新建则创建模板"""
    if not TASK_FILE.exists():
        TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TASK_FILE, "w", encoding="utf-8") as f:
            f.write("""# 当前工作安排

> 格式：`- [ ] YYYY-MM-DD: 任务描述`
> 说"完成了 XXX"来删除该任务

## 待办

## 进行中
""")
        return True
    return False

def read_file():
    """读取完整内容"""
    ensure_task_file()
    with open(TASK_FILE, "r", encoding="utf-8") as f:
        return f.read()

def write_file(content):
    """覆写文件"""
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        f.write(content)

# ============================================================
# 2. 任务解析
# ============================================================

def parse_task_line(line):
    """
    解析任务行，返回 (状态, 日期, 描述)
    格式：`- [ ] 2026-07-13: 任务描述`
    """
    line = line.strip()
    if not line.startswith("- ["):
        return None

    status_match = re.match(r"- \[([ xX])\]\s*(.*)", line)
    if not status_match:
        return None

    is_done = status_match.group(1).lower() == "x"
    rest = status_match.group(2).strip()

    # 提取日期（YYYY-MM-DD）
    date_match = re.match(r"(\d{4}-\d{2}-\d{2})\s*[:：]\s*(.*)", rest)
    if date_match:
        date_str = date_match.group(1)
        desc = date_match.group(2).strip()
    else:
        # 兼容旧格式：没有日期 → 默认今天
        date_str = datetime.now().date().isoformat()
        desc = rest

    return {
        "status": "done" if is_done else "pending",
        "date": date_str,
        "desc": desc,
        "raw": line
    }

def parse_section(content, section_name):
    """解析某一章节（待办/进行中/已完成）的所有任务"""
    # 找章节标题
    pattern = rf"##\s*{section_name}\s*\n(.*?)(?=\n##|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return [], content

    section_body = match.group(1)
    lines = section_body.strip().split("\n") if section_body.strip() else []

    tasks = []
    other_lines = []
    for line in lines:
        parsed = parse_task_line(line)
        if parsed:
            tasks.append(parsed)
        else:
            other_lines.append(line)

    return tasks, other_lines

# ============================================================
# 3. 操作函数
# ============================================================

def add_task(date_str, desc, section="待办"):
    """添加任务到指定章节"""
    content = read_file()

    # 找章节位置
    pattern = rf"(##\s*{section}\s*\n)"
    match = re.search(pattern, content)
    if not match:
        return {"status": "error", "message": f"未找到章节: {section}"}

    pos = match.end()
    new_line = f"- [ ] {date_str}: {desc}\n"

    # 在章节后面插入（保持缩进）
    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"##\s*{section}", line):
            insert_idx = i + 1
            break

    if insert_idx is None:
        return {"status": "error", "message": f"未找到章节位置: {section}"}

    lines.insert(insert_idx, new_line)
    new_content = "\n".join(lines)
    write_file(new_content)

    return {"status": "ok", "action": "added", "section": section, "task": f"{date_str}: {desc}"}

def complete_task(desc_keyword):
    """根据关键词删除已完成的任务（彻底抹除）"""
    content = read_file()

    desc_keyword = desc_keyword.strip()
    found = False
    new_lines = []
    removed_task = None

    for line in content.split("\n"):
        parsed = parse_task_line(line)
        if parsed and parsed["status"] == "pending" and desc_keyword and desc_keyword in parsed["desc"]:
            found = True
            removed_task = parsed["desc"]
            continue  # 跳过该行 = 删除
        new_lines.append(line)

    if not found:
        return {"status": "error", "message": f"未找到包含 '{desc_keyword}' 的未完成任务"}

    write_file("\n".join(new_lines))
    return {"status": "ok", "action": "completed", "task": removed_task}

def clean_done():
    """清空已完成区（无已完成区时返回空消息）"""
    content = read_file()
    if "已完成" not in content:
        return {"status": "ok", "action": "cleaned", "message": "无已完成任务"}
    lines = content.split("\n")
    new_lines = []
    in_done_section = False
    for line in lines:
        if re.match(r"##\s*已完成", line):
            in_done_section = True
            continue
        if in_done_section:
            if re.match(r"##\s*", line):
                in_done_section = False
                new_lines.append(line)
            continue
        new_lines.append(line)
    write_file("\n".join(new_lines))
    return {"status": "ok", "action": "cleaned", "message": "已完成任务已清空"}

def query_tasks(date_str, include_done=False):
    """查询指定日期的任务"""
    content = read_file()
    results = {"pending": [], "done": []}

    for line in content.split("\n"):
        parsed = parse_task_line(line)
        if parsed and parsed["date"] == date_str:
            if parsed["status"] == "pending":
                results["pending"].append(parsed["desc"])
            elif parsed["status"] == "done" and include_done:
                results["done"].append(parsed["desc"])

    return results

def get_today_str():
    return datetime.now().date().isoformat()

def get_tomorrow_str():
    return (datetime.now().date() + timedelta(days=1)).isoformat()

def query_done_tasks(days_back=7):
    """查询最近 days_back 天内所有已完成任务，按日期分组"""
    content = read_file()
    today = datetime.now().date()
    cutoff = today - timedelta(days=days_back)
    results = {}
    for line in content.split("\n"):
        parsed = parse_task_line(line)
        if parsed and parsed["status"] == "done":
            d = datetime.strptime(parsed["date"], "%Y-%m-%d").date()
            if cutoff <= d <= today:
                results.setdefault(parsed["date"], []).append(parsed["desc"])
    return dict(sorted(results.items()))

def parse_date_range(user_input):
    """从用户输入解析日期范围，返回 (days_back, label)"""
    today = datetime.now().date()
    if "今天" in user_input or "今日" in user_input:
        return 0, "今天"
    if "本周" in user_input or "这周" in user_input:
        return today.weekday(), "本周"
    if "上周" in user_input:
        return today.weekday() + 7, "上周"
    if "本月" in user_input or "这个月" in user_input:
        return today.day - 1, "本月"
    return 7, "近一周"

# ============================================================
# 4. 主入口
# ============================================================

def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    user_input = " ".join(args) if args else ""

    # 从stdin读取（兼容JSON调用）
    if not user_input and not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
            if data:
                parsed = json.loads(data)
                user_input = parsed.get("query", "")
        except:
            pass

    if not user_input:
        print(json.dumps({"status": "error", "message": "请提供查询或操作指令"}, ensure_ascii=False))
        sys.exit(1)

    # ========== 意图识别 ==========

    # 1. 完成/已完成
    if re.search(r"完成了|已完成|做完了", user_input):
        kw = re.sub(r"完成了|已完成|做完了", "", user_input).strip()
        if not kw:
            print(json.dumps({"status": "error", "message": "请指定要完成的任务（如：完成了防汛方案）"}, ensure_ascii=False))
            sys.exit(1)
        result = complete_task(kw)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 2. 清理已完成
    if re.search(r"清理|清空|移除.*完成", user_input):
        result = clean_done()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 3. 完成情况查询（已完成任务回顾）
    if re.search(r"完成情况|完成工作|完成了什么|完成进度|做了什么", user_input):
        days_back, label = parse_date_range(user_input)
        done = query_done_tasks(days_back)
        if not done:
            print(json.dumps({"status": "query_done", "range": label, "result": f"{label}无已完成任务", "tasks": {}}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"status": "query_done", "range": label, "result": f"{label}完成{sum(len(v) for v in done.values())}项", "tasks": done}, ensure_ascii=False, indent=2))
        return

    # 4. 待办查询（哪天的工作）
    if re.search(r"哪天|几号|什么安排|工作安排|任务", user_input):
        if "明天" in user_input:
            date_str = get_tomorrow_str()
        elif "后天" in user_input:
            date_str = (datetime.now().date() + timedelta(days=2)).isoformat()
        elif "今天" in user_input or "今日" in user_input:
            date_str = get_today_str()
        else:
            match = re.search(r"(\d{4}-\d{2}-\d{2})", user_input)
            if match:
                date_str = match.group(1)
            else:
                date_str = get_today_str()

        tasks = query_tasks(date_str)
        readable_date = f"{date_str[:4]}年{date_str[5:7]}月{date_str[8:10]}日"

        if not tasks["pending"] and not tasks["done"]:
            print(json.dumps({
                "status": "query",
                "date": date_str,
                "result": f"{readable_date}暂无安排",
                "pending": [],
                "done": []
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({
                "status": "query",
                "date": date_str,
                "pending": tasks["pending"],
                "done": tasks["done"],
                "result": f"{readable_date}：待办 {len(tasks['pending'])} 项，已完成 {len(tasks['done'])} 项"
            }, ensure_ascii=False, indent=2))
        return

    # 4. 记录（包含"安排"且不是查询）
    desc = re.sub(r"安排|记录|记下|帮我", "", user_input).strip()
    if not desc:
        print(json.dumps({"status": "error", "message": "请指定要记录的任务内容"}, ensure_ascii=False))
        sys.exit(1)

    if "明天" in user_input:
        date_str = get_tomorrow_str()
        desc = re.sub(r"明天", "", desc).strip()
    elif "后天" in user_input:
        date_str = (datetime.now().date() + timedelta(days=2)).isoformat()
        desc = re.sub(r"后天", "", desc).strip()
    else:
        date_str = get_today_str()
        desc = re.sub(r"今天", "", desc).strip()

    result = add_task(date_str, desc)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
