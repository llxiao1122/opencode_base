from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
KNOWLEDGE_DIR = ROOT_DIR / "Knowledge"


def _search_worldview(query: str, top_k: int = 3) -> str:
    """优先走世界观 FAISS 语义检索（process + topic 实体档案），命中高分即用。"""
    try:
        from skills.memory.worldview import search as wv_search
        hits = wv_search(query, top_k=top_k)
        hits = [h for h in hits if h.get("type") != "person" and h.get("score", 0) >= 0.6]
        if not hits:
            return ""
        blocks = []
        for h in hits:
            snippet = (h.get("content") or "")[:600].strip()
            if snippet:
                blocks.append(f"【{h['entity_id']}】（世界观档案）\n{snippet}")
        return "\n\n".join(blocks[:top_k])
    except Exception:
        return ""


def _search_knowledge(query: str, top_k: int = 3) -> str:
    if not KNOWLEDGE_DIR.exists():
        return ""
    results = []
    for md_path in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        rel = md_path.relative_to(KNOWLEDGE_DIR)
        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        hits = []
        for i, line in enumerate(lines):
            if query.lower() in line.lower():
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                ctx = "\n".join(lines[start:end])
                hits.append(f"行{i+1}:\n{ctx}")
        if hits:
            results.append(f"【{rel}】\n" + "\n...\n".join(hits[:3]))
    if not results:
        return ""
    return "\n\n".join(results[:top_k])


def handle(user_input, ctx):
    user_name = (ctx.user or {}).get("name", "未知")

    knowledge_text = _search_worldview(user_input, top_k=3)
    if not knowledge_text:
        knowledge_text = _search_knowledge(user_input, top_k=3)
    if not knowledge_text:
        origin = getattr(ctx, "original_route", "") or ""
        orig_conf = getattr(ctx, "original_confidence", 0.0) or 0.0
        if origin in ("event", "unknown") and orig_conf < 0.5:
            return "[Cipher] 已记录。"
        return "[Cipher] 制度库中暂无匹配条目。"

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于提供的制度文档，回答合规性问题。引用具体条目。"
    )
    prompt = (
        f"当前用户 {user_name} 提问: {user_input}\n"
        f"\n相关制度内容:\n{knowledge_text}\n"
        f"\n请根据制度内容回答。如果制度未覆盖，如实说明。"
    )
    from skills.shared.llm_cache import call as _cached_llm
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=60, max_tokens=400, temperature=0.2)
    if not answer:
        answer = "未能检索到匹配的制度内容。"
    return f"[Cipher:knowledge]\n{answer}"
