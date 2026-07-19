"""
routing/entry.py — Cipher main entry (Phase 13).

Route dispatch only. Handlers live in routing/{profile,task,knowledge}_handler.py.
"""

import sys, hashlib, time as _time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(TOOLS_DIR))

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

    if route == "profile":
        from routing.profile_handler import handle as _h
        return _h(user_input, ctx)
    if route == "task":
        from routing.task_handler import handle as _h
        return _h(user_input, ctx)
    if route == "knowledge":
        from routing.knowledge_handler import handle as _h
        return _h(user_input, ctx)

    return _handle_event(user_input, user, user_name, user_role, user_team)


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
