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

    knowledge_text = ""
    try:
        from knowledge.retriever import search as _k_search
        hits = _k_search(user_input, top_k=3)
        if hits:
            store_path = ROOT_DIR / "state" / "knowledge" / "knowledge_index.json"
            if store_path.exists():
                chunks = json.loads(store_path.read_text(encoding="utf-8"))
                parts = []
                for score, idx in hits:
                    if 0 <= idx < len(chunks):
                        c = chunks[idx]
                        text = c.get("text", c.get("content", str(c)))[:800]
                        source = c.get("source_file", c.get("title", ""))
                        parts.append(f"[{source}] {text}")
                knowledge_text = "\n---\n".join(parts) if parts else ""
    except Exception:
        pass

    if not knowledge_text:
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
