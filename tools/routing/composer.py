"""
composer.py — 能力编排层 — DEPRECATED: 入口不调用，无管线集成
职责: 路由向量 → 能力计划 → 串行执行 → 结果合成
不直接导入 wrapper.py, handler 字典由调用方注入。
"""

from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(TOOLS_DIR))

from routing.protocol import CapabilityResult, error_result

SERIOUS_KEYWORDS = ["事故", "火灾", "伤亡", "处罚", "考核", "转正", "人事"]

PERSONALITY_PATH = Path(__file__).resolve().parent.parent.parent / "state" / "personality.md"


def _load_personality() -> str:
    """Load Fairy personality config if file exists."""
    if PERSONALITY_PATH.exists():
        return PERSONALITY_PATH.read_text(encoding="utf-8")
    return ""


def _select_mode(user_input: str) -> str:
    """Select response mode from user input.
    Deadpan (Fairy) is the default. Only safety/HR keywords lock to professional.
    """
    if any(k in user_input for k in SERIOUS_KEYWORDS):
        return "professional"
    return "deadpan"


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
        mode = _select_mode(user_input)
        base_prompt = (
            "你是 Cipher，工班AI助手。自称'Cipher'（第三人称），不说'我'。"
            "优先使用指令关系理解消息：issuer是任务来源不是对话对象。"
            "回复当前用户为你的对话对象。口语化中文。"
        )
        if mode == "deadpan":
            personality = _load_personality()
            if personality:
                sys_prompt = f"{base_prompt}\n\n{personality}\n\n当前模式: Cipher。保持事实准确，语气平静。"
            else:
                sys_prompt = base_prompt
        else:
            sys_prompt = base_prompt

        # Inject personal context (preferences + recent thoughts)
        try:
            from personal.retriever import format_personal_context, has_personal_relevance, format_thought_context
            personal = format_personal_context()
            if personal:
                sys_prompt = f"{sys_prompt}\n\n{personal}"
            # Topic-specific thought search
            if has_personal_relevance(user_input):
                thoughts = format_thought_context(user_input)
                if thoughts:
                    sys_prompt = f"{sys_prompt}\n{thoughts}"
        except Exception:
            pass
        full_prompt = (
            f"{user_prompt}\n\n"
            f"用户问: {user_input}\n\n"
            f"多能力执行结果:\n{joined[:3000]}\n\n"
            "请整合为一段连贯的口语化回复。保留所有关键信息点。"
        )
        raw = _llm(full_prompt, system_prompt=sys_prompt, max_tokens=600, temperature=0.3)
        
        # Auto-update preferences after each reply
        try:
            from personal.retriever import maybe_update_preferences
            if raw and isinstance(raw, str):
                maybe_update_preferences(user_input, str(raw))
        except Exception:
            pass
        
        if raw and not (isinstance(raw, dict) and "error" in raw):
            return str(raw).strip()
    except Exception:
        pass
    return "\n\n".join(str(s.result) for s in visible)
