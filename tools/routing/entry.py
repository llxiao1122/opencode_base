"""
routing/entry.py — Main pipeline entry (extracted from wrapper.py Phase 9).

Core pipeline: Event → Context → Task → Reply.
Entry point: handle_core(message) -> result.

Phase 12: Query router (profile/task/knowledge/event) + Cipher identity.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import hashlib, time as _time
_llm_cache = {}


def _cached_llm(prompt, sys_prompt, user="", ttl=60, max_tokens=300, temperature=0.3):
    from reasoning.llm_client import call as _llm
    key = hashlib.sha256(
        f"{user}:{sys_prompt[:80]}:{prompt[:300]}".encode()
    ).hexdigest()
    entry = _llm_cache.get(key)
    if entry and _time.time() - entry[1] < entry[2]:
        return entry[0]
    raw = _llm(prompt, system_prompt=sys_prompt, max_tokens=max_tokens, temperature=temperature)
    answer = str(raw).strip() if raw and not (isinstance(raw, dict) and "error" in raw) else ""
    _llm_cache[key] = (answer, _time.time(), ttl)
    return answer


def handle_core(user_input):
    from context.request_context import build_request_context
    ctx = build_request_context()
    user = ctx["user"]
    user_name = user.get("name", "未知")
    user_role = user.get("role", "")
    user_team = user.get("team", "")

    from routing.query_router import classify
    route = classify(user_input)

    # ── Profile route ──
    if route == "profile":
        return _handle_profile(user_input, user_name)
    # ── Knowledge route ──
    elif route == "knowledge":
        return _handle_knowledge(user_input, user_name)
    # ── Task/Event route ──
    else:
        return _handle_event(user_input, user, user_name, user_role, user_team)


def _handle_profile(user_input, user_name):
    # Extract target person name from query
    target_name = _extract_person_name(user_input)
    if not target_name:
        return "[Cipher] 请问你想了解谁的情况？"

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "你的职责：理解工作上下文，辅助任务管理，积累组织经验。"
        "基于提供的数据，客观陈述事实。不评价、不猜测、不做人格判断。"
    )

    profile_text = ""
    memory_text = ""
    try:
        from profile.retriever import get_person_context
        import json
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

    if not profile_text and not memory_text:
        return f"[Cipher] 暂无 {target_name} 的相关记录。"

    prompt = (
        f"用户 {user_name} 查询了 {target_name} 的情况。\n"
        f"原始问题: {user_input}\n"
        f"{profile_text}"
        f"{memory_text}"
        f"\n请简要总结 {target_name} 的工作情况。只基于以上数据，不编造。"
    )
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=300, max_tokens=300, temperature=0.3)
    if not answer:
        answer = f"根据现有数据，{target_name} 暂无足够信息形成画像。"
    return f"[Cipher:profile]\n{answer}"


def _handle_knowledge(user_input, user_name):
    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于提供的制度文档，回答合规性问题。引用具体条目。"
    )

    knowledge_text = ""
    try:
        from knowledge.retriever import search as _k_search
        hits = _k_search(user_input, top_k=3)
        if hits:
            import json
            from pathlib import Path
            store_path = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge" / "knowledge_index.json"
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
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=60, max_tokens=400, temperature=0.2)
    if not answer:
        answer = "未能检索到匹配的制度内容。"
    return f"[Cipher:knowledge]\n{answer}"


def _handle_event(user_input, user, user_name, user_role, user_team):
    from core.event import extract
    from core.context import resolve as ctx_resolve
    from reasoning.llm_client import call as _llm

    event = extract(user_input, current_user=user)

    try:
        from memory.event_recorder import record
        record(event)
    except Exception:
        pass

    if event.get("event_type") == "feedback":
        from organization.model import OrganizationModel
        from task.manager import TaskManager
        fb_tm = TaskManager(OrganizationModel())
        result = fb_tm.update_from_event(event)
        if result.get("matched"):
            event["related_task"] = result.get("task_id", "")
            event["feedback_status"] = result.get("status", "")
            try:
                record(event)
            except Exception:
                pass
            try:
                from memory.observation_writer.write_observation import write_observation
                status_label = "全部完成" if result.get("all_done") else "部分完成"
                write_observation("任务完成",
                    f"{result['executor']}：{result.get('task_id', '')} {status_label}")
            except Exception:
                pass
            if result.get("all_done"):
                msg = f"✅ {result['executor']} 已完成。全员完成，任务 {result['task_id']} 已关闭。"
            else:
                msg = f"✅ 已记录：{result['executor']} 完成。"
        else:
            msg = result.get("reason", "未匹配到任务")
        return f"[Core:feedback]\n{msg}"

    subject_ctx = ctx_resolve(event, user)

    from organization.model import OrganizationModel
    from task.manager import TaskManager
    org = OrganizationModel()
    tm = TaskManager(org)
    managed_task = tm.create(event, subject_ctx, user)

    pos = subject_ctx.get("my_position", {})
    pos_type = pos.get("type", "observer")
    reason = subject_ctx.get("reason", "")

    dl_feasibility = subject_ctx.get("deadline_feasibility", {})
    dl_warning = ""
    if dl_feasibility.get("feasible") in (False, "tight"):
        dl_warning = f"\n⚠️ 截止可行性: {dl_feasibility.get('reason', '')}"

    act = managed_task.get("action", "")
    deadline = event.get("time", {}).get("deadline", "")
    actors = event.get("actors", [])
    requester = ""
    for a in actors:
        if a.get("position") == "requester":
            requester = a.get("name", "")

    event_title = event.get("raw", user_input)[:120]
    executors = [e["name"] for e in managed_task.get("executors", [])]
    subtasks_summary = "\n".join(
        f"  [{task.get('assignee','')}] {task.get('action','')}"
        for task in managed_task.get("subtasks", [])[:6]
    )

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于事件分析客观汇报理解，不替用户决策。"
        "禁止使用询问语气。"
        "直接陈述事实、位置、建议行动、截止时间。用动词开头。"
    )

    contact_info = ""
    if requester:
        role = ""
        for a in actors:
            if a["name"] == requester:
                role = a.get("role", "")
                break
        contact_info = f"发起人: {requester}" + (f"（{role}）" if role else "")

    full_prompt = (
        f"当前用户: {user_name}（{user_role}，{user_team}）\n"
        f"事件摘要: {event_title}\n"
        f"责任类型: {pos_type}（{reason}）\n"
        f"建议行动: {act}\n"
        + (f"截止时间: {deadline}\n" if deadline else "")
        + (f"{contact_info}\n" if contact_info else "")
        + (f"执行人员: {', '.join(executors)}\n" if executors else "")
        + (f"子任务:\n{subtasks_summary}\n" if subtasks_summary else "")
        + (dl_warning if dl_warning else "")
        + "\n请按以下格式输出（每项一行）：\n"
          f"【事件】<一句话概括>\n"
          f"【位置】{pos_type} — <含义>\n"
          f"【行动】<动词开头的待办>\n"
          + (f"【截止】{deadline}\n" if deadline else "")
          + (f"【发起】{requester}\n" if requester else "")
          + f"\n📋 任务已创建: {managed_task['id']} ({len(managed_task.get('subtasks',[]))} 子任务)"
    )

    try:
        raw = _llm(full_prompt, system_prompt=sys_prompt, max_tokens=400, temperature=0.3)
        answer = str(raw).strip() if raw and not (isinstance(raw, dict) and "error" in raw) else ""
    except Exception:
        answer = ""

    if not answer:
        answer = f"【事件】{event_title}\n【位置】{pos_type}\n【行动】{act}"

    return f"[Cipher:{pos_type}]\n{answer}"


def _extract_person_name(text: str) -> str:
    """Extract person name from query using entity_resolver."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(TOOLS_DIR))
        from routing.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        entities = resolved.get("entities", [])
        if entities:
            return entities[0]["name"]
    except Exception:
        pass
    return ""
