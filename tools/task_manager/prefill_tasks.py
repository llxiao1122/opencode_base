#!/usr/bin/env python3
"""
prefill_tasks.py - 按月预填固定工作到 tasks.md

读取工班日常固定工作.md 中的周期性规则(每周五/每月固定日/每季末),
计算指定月份的所有固定工作日期(遇周末向前调整),
与 tasks.md 已有【固定】条目比对, 缺失则追加。

用法:
  python3 tools/task_manager/prefill_tasks.py            # 当前月
  python3 tools/task_manager/prefill_tasks.py --month 2026-07  # 指定月
"""
import sys
import json
import re
import calendar
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path("/home/admin/opencode")
TASK_FILE = PROJECT_ROOT / "memory" / "tasks.md"

# 规则定义(与 Knowledge/00-日常工作指引/工班日常固定工作.md 同步)
# (类型, 参数, 工作项)
# 类型: weekly_friday / monthly_date / quarterly_end
RULES = [
    ("weekly_friday", None, "安全自查记录"),
    ("weekly_friday", None, "隐患排查清单"),
    ("weekly_friday", None, "CIMS系统内故障提报记录 核查处置进度"),
    ("weekly_friday", None, "防汛防寒物资(汛期/防寒期)"),
    ("weekly_friday", None, "日常班组业务检查清单"),
    ("monthly_date", 15, "防火检查记录表"),
    ("monthly_date", 18, "灭火器情况统计表"),
    ("monthly_date", 18, "杂品库应急物资"),
    ("monthly_date", 18, "防寒防汛物资(非汛期)"),
    ("monthly_date", 20, "应急演练台账(上传系统)"),
    ("monthly_date", 25, "安全培训(含消防)"),
    ("monthly_date", 25, "叉车充电记录表、电量检查记录表"),
    ("monthly_date", 30, "防火检查记录表"),
    ("quarterly_end", None, "防爆手电筒充电记录"),
]


def adjust_forward(d):
    """遇周末/非工作日 → 向前调到最近工作日"""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def calc_month_dates(year, month):
    """计算指定月份所有固定工作的 (日期, 工作项) 列表"""
    results = []
    cal = calendar.monthcalendar(year, month)

    for rule_type, param, task in RULES:
        if rule_type == "weekly_friday":
            # 当月所有周五, 逐个处理
            for week in cal:
                friday = week[4]  # 周五 = index 4
                if friday == 0:
                    continue
                d = date(year, month, friday)
                d = adjust_forward(d)
                results.append((d, task))

        elif rule_type == "monthly_date":
            try:
                d = date(year, month, param)
            except ValueError:
                continue
            d = adjust_forward(d)
            results.append((d, task))

        elif rule_type == "quarterly_end":
            if month not in (3, 6, 9, 12):
                continue
            last_day = calendar.monthrange(year, month)[1]
            d = date(year, month, last_day)
            d = adjust_forward(d)
            results.append((d, task))

    return results


PREFILL_MARKER_PREFIX = "> 上月预填: "


def read_marker(content):
    """检查 tasks.md 头部的预填标记行"""
    for line in content.split("\n"):
        if line.startswith(PREFILL_MARKER_PREFIX):
            return line[len(PREFILL_MARKER_PREFIX):].strip()
    return None


def write_marker(year, month):
    """写入/更新 tasks.md 预填标记"""
    path = TASK_FILE
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    marker = f"{PREFILL_MARKER_PREFIX}{year}-{month:02d}"

    for i, line in enumerate(lines):
        if line.startswith(PREFILL_MARKER_PREFIX):
            lines[i] = marker + "\n"
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return

    # 没有现有标记 → 加在第一行注释区
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith("##"):
            insert_idx = i
            break

    if insert_idx is None:
        insert_idx = 1

    lines.insert(insert_idx, marker + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def read_tasks():
    path = TASK_FILE
    if not path.exists():
        return [], None
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    marker = read_marker(content)

    entries = []
    for line in content.split("\n"):
        line = line.strip()
        m = re.match(r"-\s*\[\s*[ xX]?\s*\]\s*(\d{4}-\d{2}-\d{2})\s*:\s*(.+)", line)
        if m:
            entries.append({"date": m.group(1), "desc": m.group(2).strip(), "raw": line})

    return entries, marker


def is_prefilled_for_month(year, month, marker):
    """检查本月是否已预填: 看标记文件"""
    expected = f"{year}-{month:02d}"
    return marker == expected


def add_task_line(date_str, desc):
    """向 tasks.md 的 待办 节追加一条任务"""
    path = TASK_FILE
    if not path.exists():
        return {"status": "error", "message": f"tasks.md 不存在: {path}"}

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 找 待办 节
    sec_match = re.search(r"(##\s*待办\s*\n)", content)
    if not sec_match:
        return {"status": "error", "message": "tasks.md 中未找到 ## 待办 章节"}

    new_line = f"- [ ] {date_str}: {desc}\n"
    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if re.match(r"##\s*待办", line):
            insert_idx = i + 1
            break

    if insert_idx is None:
        return {"status": "error", "message": "无法定位待办章节插入位置"}

    lines.insert(insert_idx, new_line)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {"status": "ok", "task": f"{date_str}: {desc}"}


def main():
    # 解析参数
    target_month = None
    if "--month" in sys.argv:
        idx = sys.argv.index("--month")
        if idx + 1 < len(sys.argv):
            target_month = sys.argv[idx + 1]

    if target_month:
        match = re.match(r"(\d{4})-(\d{1,2})", target_month)
        if not match:
            print(json.dumps({"status": "error", "message": f"月份格式错误: {target_month}, 示例: 2026-07"}, ensure_ascii=False))
            sys.exit(1)
        year, month = int(match.group(1)), int(match.group(2))
    else:
        today = date.today()
        year, month = today.year, today.month

    # 计算当月应生成的固定工作
    new_entries = calc_month_dates(year, month)
    if not new_entries:
        print(json.dumps({"status": "ok", "month": f"{year}-{month:02d}", "action": "no_rules", "message": "本月无固定工作规则"}, ensure_ascii=False))
        return

    # 读已有 tasks + 预填标记
    existing, marker = read_tasks()

    if is_prefilled_for_month(year, month, marker):
        print(json.dumps({"status": "ok", "month": f"{year}-{month:02d}", "action": "skipped", "message": f"本月已有预填标记, 无需预填", "total": len(new_entries)}, ensure_ascii=False))
        return

    # 追加缺失条目
    added = 0
    skipped = 0
    for d, task in new_entries:
        date_str = d.isoformat()
        desc = f"【固定】{task}"
        found = False
        for e in existing:
            if e["date"] == date_str and desc in e["desc"]:
                found = True
                break
        if found:
            skipped += 1
        else:
            result = add_task_line(date_str, desc)
            if result["status"] == "ok":
                added += 1
            else:
                print(json.dumps({"status": "error", "task": desc, "message": result["message"]}, ensure_ascii=False))

    # 写入预填标记(无论有没有新增, 第一次跑就算已预填)
    write_marker(year, month)

    # 输出结果
    result_text = f"月 {year}-{month:02d}: 新增{added}条" + (f", 已存在{skipped}条" if skipped else "")
    print(json.dumps({
        "status": "ok",
        "month": f"{year}-{month:02d}",
        "action": "prefilled" if added > 0 else "up_to_date",
        "message": result_text,
        "added": added,
        "skipped": skipped,
        "total_rules": len(new_entries)
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
