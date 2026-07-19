"""
ingestion/message_classifier.py — Classify message type by structure, not content.

Only judges message nature: instruction, feedback, announcement, discussion, question, irrelevant.
Does NOT judge: who is responsible, what task to do, or generate profiles.

Pure rule-based, no LLM.
"""

INSTRUCTION_WORDS = ["请", "安排", "通知", "督促", "要求", "执行", "落实", "必须", "严禁"]
FEEDBACK_WORDS = ["收到", "已完成", "完成", "做完了", "搞定", "好了", "OK"]
FEEDBACK_HIGH = ["已完成", "已处理", "已整改", "已提交", "已上传", "已更换", "完成情况"]
ANNOUNCE_WORDS = ["通知：", "公告", "关于", "各班组注意", "各位注意"]
QUESTION_WORDS = ["？", "吗", "呢", "请问", "怎么", "如何"]


def classify(msg: dict) -> str:
    """Classify a Message dict into one of six types.

    Args:
        msg: dict from message_parser.parse() with {sender, content, ...}

    Returns:
        str: instruction | feedback | announcement | discussion | question | irrelevant
    """
    content = msg.get("content", "").strip()
    if not content:
        return "irrelevant"

    # ① High-confidence feedback (any length) — check before instruction
    if any(kw in content for kw in FEEDBACK_HIGH):
        return "feedback"

    # ② Very short ack → feedback candidate
    if len(content) <= 4 and any(kw in content for kw in FEEDBACK_WORDS):
        return "feedback"

    # ③ Starts with announcement keyword
    if any(content.startswith(kw) for kw in ANNOUNCE_WORDS):
        return "announcement"

    # ④ Contains question marks → question
    if any(kw in content for kw in QUESTION_WORDS):
        return "question"

    # ⑤ Contains instruction keywords → instruction
    if any(kw in content for kw in INSTRUCTION_WORDS):
        return "instruction"

    # ⑥ Very long message without sender context → announcement
    if len(content) > 100:
        return "announcement"

    # ⑦ Short ack / emoji / noise
    if len(content) <= 3:
        return "irrelevant"

    # ⑧ Default: discussion (multi-person chat)
    return "discussion"
