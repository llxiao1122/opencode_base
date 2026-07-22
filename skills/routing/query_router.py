"""
routing/query_router.py — Query type classifier (Phase 12.1).

Keyword-first, semantic-fallback. No LLM.
Priority: profile > task > knowledge > event.
"""

PROFILE_WORDS = [
    "什么样", "怎么样", "评价", "能力", "表现",
    "画像", "是谁", "性格", "优缺点",
    "做事", "为人", "如何",
]

TASK_WORDS = [
    "今天", "明天", "本周", "待办", "任务",
    "做了什么", "有什么活", "近期", "还有什么", "这周",
]

KNOWLEDGE_WORDS = [
    "制度", "规定", "流程", "标准", "规范", "条例",
    "要求", "禁止", "不得", "应做", "怎么办",
]

SEMANTIC_ANCHORS = {
    "profile": [
        "这个人怎么样", "性格怎么样", "能力如何", "评价一下",
        "他的表现", "为人处世", "工作态度", "靠谱吗", "是什么样的人",
    ],
    "task": [
        "今天要做什么", "工作安排", "待办事项", "有什么任务",
        "最近的事情", "还有什么事", "忙不忙", "有啥活",
    ],
    "knowledge": [
        "制度规定是什么", "操作规程", "标准流程", "怎么处理",
        "有什么要求", "应急预案", "合规检查", "规章制度",
    ],
}


def classify(user_input: str) -> str:
    """Return: profile | task | knowledge | event"""
    text = user_input.strip()

    if any(w in text for w in PROFILE_WORDS):
        return "profile"

    if any(w in text for w in TASK_WORDS):
        return "task"

    if any(w in text for w in KNOWLEDGE_WORDS):
        return "knowledge"

    # No keyword hit — semantic fallback
    if len(text) >= 2:
        try:
            from shared.semantic import classify as sem_classify
            return sem_classify(text, SEMANTIC_ANCHORS, fallback="event", threshold=0.52)
        except Exception:
            pass

    return "event"
