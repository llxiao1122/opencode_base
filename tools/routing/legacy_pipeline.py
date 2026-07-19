"""
routing/legacy_pipeline.py — Old A-I route pipeline (extracted from wrapper.py Phase 9).

DEPRECATED: kept for backward compatibility with --interactive mode.
New pipeline: use routing/entry.py (handle_core) with CORE_MODE=1.
"""

import sys, subprocess, os, json
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = TOOLS_DIR.parent

_VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python3"

from routing.llm_helpers import _llm, _add_history, _truncate
from routing.route_request import route_request
from routing.composer import execute_plan
from context.request_context import build_request_context, inject_user_prompt


# ══════════════════════════════════════════════════════════════
# A-G-I handlers
# ══════════════════════════════════════════════════════════════

def handle_A(user_input, ctx=None):
    return _llm(user_input,
                system_prompt="你是工班AI助手，回答简洁直接，用口语化中文。",
                use_history=True)


def handle_B(user_input, ctx=None):
    from pipeline.instruction_resolver import resolve_instruction
    inst = ctx.get("instruction") if ctx else None
    prompt = user_input
    if not inst:
        from core.event import extract
        from core.context import resolve as ctx_resolve
        evt = extract(user_input, current_user=ctx.get("user") if ctx else None)
        subject = ctx_resolve(evt, ctx.get("user") if ctx else {})
        reason = subject.get("reason", "")
        pos_info = f"责任判定: {reason}\n" if reason else ""
        prompt = (
            f"{pos_info}" + f"事件: {evt.get('raw', user_input)[:200]}\n"
        )
    prompt += "\n请生成工班工作总结汇报，按时间/事项/状态/问题四部分，简洁口语化。"
    return _llm(prompt, system_prompt="你是诚实的工班助理，如实呈现工作情况。", use_history=True)


def handle_C(user_input, ctx=None):
    try:
        from memory.retriever import search_person
        person_data = search_person(ctx.get("user", {}).get("name", "")) if ctx else {}
        prompt = f"{user_input}\n\n相关记忆:\n{person_data or '暂无'}"
    except Exception:
        prompt = user_input
    return _llm(f"分析以下情况:\n{prompt}",
               system_prompt="你是工班排障分析助手，按现象/根因/建议/预防四步输出。",
               use_history=True)


def handle_D(user_input, ctx=None):
    from context.hierarchy_resolver import inject_org_context as _org_ctx
    prompt = user_input
    org = _org_ctx(ctx.get("event") if ctx else None, ctx.get("user") if ctx else {})
    event_ctx_text = ""
    if ctx and ctx.get("event"):
        from memory.event_context import build_event_context as _bec
        try:
            evt_id = ctx["event"].get("id", "")
            if evt_id:
                event_ctx = _bec(evt_id)
                if event_ctx:
                    event_ctx_text = f"\n事件上下文:\n{json.dumps(event_ctx, ensure_ascii=False, indent=2)[:2000]}"
        except Exception:
            pass
    if org:
        prompt = f"{prompt}\n\n{org}{event_ctx_text}"
    base = _llm(prompt,
                system_prompt="你是工班制度助理，回答须基于实际规章，引用具体条目。",
                use_history=True)
    enriched = inject_user_prompt(ctx, base) if ctx else base
    return enriched


def handle_E(user_input, ctx=None):
    try:
        user = ctx.get("user", {}) if ctx else {}
        from work.work_query import get_my_tasks
        from work.work_view import format_tasks_for_agent
        event_ctx = ctx.get("event") if ctx else None
        tasks = get_my_tasks(user.get("name", ""), event_context=event_ctx)
        formatted = format_tasks_for_agent(tasks, user.get("name", ""), user_input)
        work_context_info = f"\n工作视图:\n{formatted}"
    except Exception:
        work_context_info = ""
    return _llm(f"{user_input}{work_context_info}",
                system_prompt="你是工班台账助理，基于实际台账数据回答。", use_history=True)


def handle_G(user_input, ctx=None):
    try:
        from memory.memory_core import MemoryCore
        mc = MemoryCore(root_path=str(ROOT_DIR))
        mc.save("reflect", user_input, priority="normal")
        summary = mc.reflect(user_input, max_response_len=300)
        if summary and not summary.startswith("["):
            return summary
    except Exception:
        pass
    return _llm(user_input, system_prompt="你是工班反思助理，提取关键事实和待办。", use_history=True)


def handle_I(user_input, ctx=None):
    prompt = f"请逐步分析:\n问题: {user_input}\n步骤:\n1) 收集事实\n2) 列出可能原因\n3) 排除\n4) 确定原因\n5) 建议方案\n6) 验证"
    return _llm(prompt,
                system_prompt="你是工班系统分析助理，按步骤逐步输出，不猜测不跳步。",
                max_tokens=2048, temperature=0.1, use_history=True)


# ══════════════════════════════════════════════════════════════
# Handler dispatch maps
# ══════════════════════════════════════════════════════════════

HANDLERS = {
    "A": handle_A, "B": handle_G, "C": handle_I,
    "D": handle_D, "E": handle_E, "F": handle_D,
    "G": handle_B, "H": handle_E, "I": handle_D,
}

CAPABILITY_HANDLERS = {
    "casual_chat":        handle_A,
    "generate_summary":   handle_G,
    "fault_analysis":     handle_I,
    "compliance_lookup":  handle_D,
    "query_records":      handle_E,
    "safety_check":       handle_D,
    "schedule_check":     handle_B,
    "task_assign":        handle_E,
    "knowledge_retrieve": handle_D,
}


def _subprocess_script(rel_path, *args, timeout=30):
    script = TOOLS_DIR / rel_path
    py = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
    cmd = [py, str(script)] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        return "命令执行超时"
    except Exception as e:
        return f"执行失败: {e}"


def _detect_and_enrich(tracer, user_input, ctx=None):
    if len(user_input) < 15:
        return []
    trigger_words = ["通知", "安排", "发布", "执行", "检查", "清理",
                     "严禁", "必须", "请各", "回复", "巡检", "演练",
                     "值班", "请假", "处置", "确认"]
    if not any(w in user_input for w in trigger_words):
        return []

    try:
        import json
        from memory.event_detector import detect as _detect_events
        current_user = ctx.get("user", {}) if ctx else {}
        events = _detect_events(user_input, current_user=current_user)
        if not events:
            return []

        from pipeline.event_enricher import enrich_event
        _EVENTS_DIR = ROOT_DIR / "memory" / "events"

        for evt in events:
            if evt.get("confidence", 0) < 0.70:
                continue
            target_status = evt.get("status", "detected")
            target = _EVENTS_DIR / target_status / f'{evt["id"]}.json'
            if not target.exists():
                continue
            detail = json.loads(target.read_text(encoding="utf-8"))
            if detail.get("ai_content_status"):
                continue
            enrich_event(detail, user_input, tracer=tracer)
            target.write_text(json.dumps(detail, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        return events
    except Exception:
        return []


def handle(user_input, mode=None):
    import os
    if os.environ.get("CORE_MODE") == "1":
        from routing.entry import handle_core
        return handle_core(user_input)

    if mode is None:
        mode = os.environ.get("COMPOSER_MODE", "composite")

    from guard.tracer import RequestTracer, log_error
    tracer = RequestTracer(user_input)

    ctx = build_request_context()

    try:
        from memory.event_lifecycle import update_from_message
        from memory.event_detector import load_index
        from guard.tracer import log_event_change
        affected = update_from_message(user_input)
        tracer.set_lifecycle(affected)
        if affected:
            idx = load_index()
            for action, eid in affected:
                if action in ("completed", "cancelled"):
                    meta = next((e for e in idx.get("events", []) if e["id"] == eid), None)
                    log_event_change(action, eid, meta.get("title", "") if meta else "")
                    if meta and meta.get("title"):
                        _subprocess_script(
                            "plugins/task_manager/manage_tasks.py",
                            f"完成了 {meta['title']}",
                            timeout=10)
    except Exception:
        pass

    detected = _detect_and_enrich(tracer, user_input, ctx=ctx)
    if detected:
        ctx["event"] = detected[0]
        from pipeline.instruction_resolver import resolve_instruction
        instruction = resolve_instruction(ctx["event"], ctx["user"])
        ctx["instruction"] = instruction
        ctx["event"]["instruction"] = instruction

    routes = route_request(user_input)
    primary = routes[0]

    try:
        from routing.entity_resolver import resolve_entities
        entities = resolve_entities(user_input)
        tracer.set_route(routes, entities)
    except Exception:
        tracer.set_route(routes)

    try:
        if mode == "single" or len(routes) == 1:
            handler = HANDLERS.get(primary)
            if not handler:
                answer = f"[Route {primary}] 未注册 handler"
            else:
                answer = handler(user_input, ctx=ctx)
        else:
            answer = execute_plan(routes, user_input, CAPABILITY_HANDLERS, ctx=ctx)
    except Exception as e:
        answer = f"[Route {primary} 异常] {type(e).__name__}: {e}"
        log_error(user_input, e)

    _add_history("user", user_input)
    _add_history("assistant", answer[:500])
    label = "/".join(routes)
    final = f"[Route {label}]\n{answer}"
    tracer.finish(final)
    return final
