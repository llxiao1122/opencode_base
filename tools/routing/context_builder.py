"""
context_builder.py — 组装 LLM 上下文
输入 work_query 结果 → 输出三层结构化提示
"""

import json
from datetime import datetime


def build_work_context(query_result):
    person = query_result.get("person", "未知")
    team = query_result.get("team", "")
    date_str = query_result.get("date", datetime.now().strftime("%Y-%m-%d"))
    routine = query_result.get("routine", [])
    responsibility = query_result.get("responsibility", {})

    direct = responsibility.get("direct_task", [])
    role = responsibility.get("role_task", [])
    attention = responsibility.get("team_attention", [])

    if not routine and not direct and not role and not attention:
        return f"\n当前用户: {person}\n暂无本周安排。"

    context = {"person": person, "team": team, "date": date_str}

    if routine:
        context["固定工作"] = [r["task"] for r in routine[:8]]

    if direct:
        context["【直接任务】"] = direct

    if role:
        context["【岗位关注】"] = role

    if attention:
        context["【涉及事项】"] = attention

    return (
        "\n个人工作视图:\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\n请将以上数据转换为自然语言工作汇报：\n"
        + "1. 先列出固定工作，再按【直接任务】→【岗位关注】→【涉及事项】顺序输出\n"
        + "2. 【直接任务】是你必须亲自完成的\n"
        + "3. 【岗位关注】是你岗位职责范围内需协调安排的，不是亲自执行\n"
        + "4. 【涉及事项】是你的团队受影响的，你只需关注，不是你的个人任务\n"
        + "5. 保留时间节点、约束条件、汇报对象\n"
        + "6. 结尾加一句：当前重点不是由你负责全部事项，而是做好本工班范围内协调和执行\n"
        + "7. 使用工班管理格式"
    )
