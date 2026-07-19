"""
routing/query_router.py — Query type classifier (Phase 12.1).

Rule-based, no LLM. Priority: profile > task > knowledge > event.
"""

PROFILE_WORDS = [
    "什么样", "怎么样", "评价", "能力", "表现",
    "情况", "画像", "是谁", "性格", "优缺点",
    "做事", "为人", "如何",
]

TASK_WORDS = [
    "今天", "明天", "本周", "待办", "任务", "安排", "工作",
    "做了什么", "有什么活", "近期", "还有什么", "这周",
]

KNOWLEDGE_WORDS = [
    "制度", "规定", "流程", "标准", "规范", "条例",
    "要求", "禁止", "不得", "应做", "怎么办",
]


def classify(user_input: str) -> str:
    """Return: profile | task | knowledge | event"""
    text = user_input.strip()

    # profile has highest priority — "张志斌工作怎么样" → profile, not task
    if any(w in text for w in PROFILE_WORDS):
        return "profile"

    if any(w in text for w in TASK_WORDS):
        return "task"

    if any(w in text for w in KNOWLEDGE_WORDS):
        return "knowledge"

    return "event"
