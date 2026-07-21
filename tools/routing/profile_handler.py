"""
routing/profile_handler.py — Profile query handler (Phase 13).

Handles profile queries: loads person profile + memory, generates summary.
"""

import json, sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent


def handle(user_input, ctx):
    user_name = ctx.get("user", {}).get("name", "未知")

    target_name = _extract_person_name(user_input, ctx=ctx)
    if not target_name:
        return "[Cipher] 请问你想了解谁的情况？"

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。自称'Cipher'（第三人称），不说'我'。"
        "你的职责：理解工作上下文，辅助任务管理，积累组织经验。"
        "基于提供的数据，客观陈述事实。不评价、不猜测、不做人格判断。"
    )
    from pathlib import Path as _P
    persona_path = _P(__file__).resolve().parent.parent.parent / "state" / "personality.md"
    if persona_path.exists():
        persona = persona_path.read_text(encoding="utf-8")[:600]
        sys_prompt = f"{sys_prompt}\n\n{persona}"

    profile_text = ""
    memory_text = ""
    observation_text = ""
    event_text = ""
    try:
        from user_profile.retriever import get_person_context
        profile = get_person_context(target_name)
        if profile and "error" not in profile:
            profile_text = f"\n人员画像:\n{json.dumps(profile, ensure_ascii=False, indent=2)[:3000]}"
    except Exception:
        pass
    try:
        from memory.retriever import search_person
        memories = search_person(target_name)
        if memories:
            memory_text = f"\n近期动态:\n{json.dumps(memories, ensure_ascii=False, indent=2)[:2000]}"
    except Exception:
        pass
    try:
        from memory.observation_store import read as obs_read
        obs = obs_read("people", target_name)
        if obs:
            observation_text = f"\n观察记录:\n{obs[-2000:]}"
    except Exception:
        pass
    try:
        from memory.event_search import search_events, build_event_context
        evts = search_events(target_name, limit=5)
        if evts:
            ctx_list = []
            for e in evts[:3]:
                ec = build_event_context(e.get("id", ""))
                if ec:
                    ctx_list.append(str(ec)[:300])
            if ctx_list:
                event_text = "\n事件上下文:\n" + "\n---\n".join(ctx_list)
    except Exception:
        pass

    if not profile_text and not memory_text and not observation_text:
        return f"[Cipher] 暂无 {target_name} 的相关记录。"

    org_context = ""
    if target_name == user_name:
        try:
            leaders_path = Path(__file__).resolve().parent.parent.parent / "state" / "leaders.md"
            if leaders_path.exists():
                org_context = f"\n组织上下文（指令来自多级领导，任务数据仅为部分采样）:\n{leaders_path.read_text(encoding='utf-8')[:800]}"
        except Exception:
            pass

    prompt = (
        f"用户 {user_name} 查询了 {target_name} 的情况。\n"
        f"原始问题: {user_input}\n"
        f"{org_context}"
        f"{profile_text}"
        f"{memory_text}"
        f"{observation_text}"
        f"{event_text}"
        f"\n请简要总结 {target_name} 的工作情况。只基于以上数据，不编造。"
        f"\n注意：不要从单一任务数据推断'主要指令来源'，指令来自多级领导。"
    )

    from shared.llm_cache import call as _cached_llm
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=300, max_tokens=300, temperature=0.3)
    if not answer:
        answer = f"根据现有数据，{target_name} 暂无足够信息形成画像。"
    return f"[Cipher:profile]\n{answer}"


def _extract_person_name(text: str, ctx=None) -> str:
    self_ref = {"我", "自己", "本人", "我的", "自个"}
    if any(w in text for w in self_ref):
        if ctx and ctx.get("user", {}).get("name"):
            return ctx["user"]["name"]
    try:
        sys.path.insert(0, str(TOOLS_DIR))
        from routing.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        entities = resolved.get("entities", [])
        if entities:
            return entities[0]["name"]
    except Exception:
        pass
    return ""
