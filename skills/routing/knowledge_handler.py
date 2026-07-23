"""
routing/knowledge_handler.py — Knowledge query handler (Phase 13).

Handles compliance/institutional queries via FAISS search + LLM synthesis.
"""

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def handle(user_input, ctx):
    user_name = (ctx.user or {}).get("name", "未知")

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于提供的制度文档，回答合规性问题。引用具体条目。"
    )

    from memory.memory_core import MemoryCore
    mc = MemoryCore()
    result = mc.retrieve(user_input, max_chars=2000)
    knowledge_text = result.get("result", "")

    if not knowledge_text or knowledge_text == "未找到相关内容":
        return "[Cipher] 制度库中暂无匹配条目。"

    prompt = (
        f"当前用户 {user_name} 提问: {user_input}\n"
        f"\n相关制度内容:\n{knowledge_text}\n"
        f"\n请根据制度内容回答。如果制度未覆盖，如实说明。"
    )

    from shared.llm_cache import call as _cached_llm
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=60, max_tokens=400, temperature=0.2)
    if not answer:
        answer = "未能检索到匹配的制度内容。"
    return f"[Cipher:knowledge]\n{answer}"
