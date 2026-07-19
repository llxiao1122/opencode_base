"""
composer.py — 能力编排层
职责: 路由向量 → 能力计划 → 串行执行 → 结果合成
不直接导入 wrapper.py, handler 字典由调用方注入。
"""

from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(TOOLS_DIR))

from routing.protocol import CapabilityResult, error_result


ROUTE_TO_CAPABILITY = {
    "A": "casual_chat",       "B": "generate_summary",
    "C": "fault_analysis",    "D": "compliance_lookup",
    "E": "query_records",     "F": "safety_check",
    "G": "schedule_check",    "H": "task_assign",
    "I": "knowledge_retrieve",
}


def execute_plan(routes, user_input, handlers, ctx=None):
    """
    routes: ['H','G','C'] → 串行执行 → compose → 回复
    handlers: {capability_name: handler_function}
    ctx: RequestContext dict (user/event/org)
    """
    plan = _routes_to_plan(routes)
    steps = _execute_plan(plan, user_input, handlers, ctx=ctx)
    return _compose(steps, user_input, ctx=ctx)


def _routes_to_plan(routes):
    return [ROUTE_TO_CAPABILITY[r] for r in routes
            if r in ROUTE_TO_CAPABILITY]


def _run_step(capability, user_input, prev_results, handlers, ctx=None):
    handler = handlers.get(capability)
    if not handler:
        return error_result(capability, f"未注册能力: {capability}")
    try:
        result = handler(user_input, ctx=ctx)
        extracted = _extract_context(result)
        return CapabilityResult(capability=capability, result=result,
                                context=extracted)
    except Exception as e:
        return error_result(capability, f"{type(e).__name__}: {e}")


def _execute_plan(plan, user_input, handlers, ctx=None):
    prev_results = []
    steps = []
    for cap in plan:
        step = _run_step(cap, user_input, prev_results, handlers, ctx=ctx)
        steps.append(step)
        if not step.continue_exec:
            break
        if step.context:
            prev_results.append(step.context)
    return steps


def _extract_context(result):
    text = str(result) if result else ""
    if len(text) <= 500:
        return text
    half = 250
    return text[:half] + "\n...[截断]...\n" + text[-half:]


def _compose(steps, user_input, ctx=None):
    visible = [s for s in steps if s.status == "success" and s.user_visible]
    if not visible:
        err = next((s for s in steps if s.status == "error"), None)
        return f"执行异常: {err.error if err else '未知错误'}"

    if len(visible) == 1:
        return str(visible[0].result)

    joined = "\n---\n".join(
        f"[{s.capability}] {str(s.result)[:600]}" for s in visible
    )
    try:
        from reasoning.llm_client import call as _llm
        from context.request_context import inject_user_prompt
        user_prompt = inject_user_prompt(ctx) if ctx else ""
        sys_prompt = (
            "你是工班AI助手。优先使用指令关系理解消息：issuer是任务来源不是对话对象。"
            "回复当前用户为你的对话对象。口语化中文。"
        )
        full_prompt = (
            f"{user_prompt}\n\n"
            f"用户问: {user_input}\n\n"
            f"多能力执行结果:\n{joined[:3000]}\n\n"
            "请整合为一段连贯的口语化回复。保留所有关键信息点。"
        )
        raw = _llm(full_prompt, system_prompt=sys_prompt, max_tokens=600, temperature=0.3)
        if raw and not (isinstance(raw, dict) and "error" in raw):
            return str(raw).strip()
    except Exception:
        pass
    return "\n\n".join(str(s.result) for s in visible)
