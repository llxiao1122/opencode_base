#!/usr/bin/env python3
"""
wrapper.py — 硬编码路由分发层
取代 opencode 的 LLM 自决路由。LLM 仅在合成自然回复时被调用。
所有用户输入先经 route_request.py 判定，再执行对应模块，LLM 不可绕过。

路由标签:
  A = 闲聊/兜底   B = 总结汇报   C = 分析排查
  D = 制度规范    E = 台账报表   F = 防汛安全
  G = 排班考勤    H = 任务分配   I = 知识学习

用法:
  python3 tools/routing/wrapper.py "你的问题"
  python3 tools/routing/wrapper.py --interactive
"""

import sys, json, subprocess, os, re
from pathlib import Path

# ── auto-detect venv ──
_VENV_PYTHON = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "python3"
if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
    os.execve(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv, os.environ)

TOOLS_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from reasoning.llm_client import call as _llm_call
from routing.route_request import route_request
from routing.composer import execute_plan
from context.request_context import build_request_context, inject_user_prompt

conversation_history = []  # [(role, content), ...]


# ══════════════════════════════════════════════════════════════
# LLM synthesis helper
# ══════════════════════════════════════════════════════════════

def _llm(prompt, system_prompt=None, max_tokens=1024, temperature=0.3, use_history=False):
    messages = _build_llm_messages(prompt, system_prompt, use_history)
    merged = "\n".join(f"[{m['role']}] {m['content'][:8000]}" for m in messages)
    result = _llm_call(merged, system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)
    if isinstance(result, dict) and "error" in result:
        return f"[LLM 错误] {result['error']}"
    return str(result) if result else ""


def _build_llm_messages(prompt, system_prompt, use_history):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if use_history:
        for role, content in conversation_history[-20:]:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": prompt})
    return messages


def _add_history(role, content):
    conversation_history.append((role, content[:500]))
    if len(conversation_history) > 40:
        conversation_history[:] = conversation_history[-40:]


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    # Keep beginning (most important) + ending context (deadlines/actions)
    head = text[:max_chars * 4 // 5]
    tail = text[-(max_chars // 5):]
    return head + "\n...[截断]...\n" + tail


# ══════════════════════════════════════════════════════════════
# lazy imports (avoid model loading on lightweight routes)
# ══════════════════════════════════════════════════════════════

def _load_core():
    from memory.memory_core import MemoryCore
    return MemoryCore(root_path=str(ROOT_DIR))


def _subprocess_script(rel_path, *args, timeout=30):
    """Run a tools/ subprocess script, return stdout text."""
    script = TOOLS_DIR / rel_path
    cmd = [str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable, str(script)] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        return "命令执行超时"
    except Exception as e:
        return f"执行失败: {e}"


def _detect_and_enrich(tracer, user_input, ctx=None):
    """Phase 1.7.7-C: detect events in user message, delegate AI enrichment
    to pipeline/event_enricher, persist enriched detail to file.
    Called from handle() after lifecycle update.
    Returns list of detected events."""
    if len(user_input) < 15:
        return []
    trigger_words = ["通知", "安排", "发布", "执行", "检查", "清理",
                     "严禁", "必须", "请各", "回复", "巡检", "演练",
                     "值班", "请假", "处置", "确认"]
    if not any(w in user_input for w in trigger_words):
        return []

    try:
        import sys as _sys
        _sys.path.insert(0, str(TOOLS_DIR))
        from memory.event_detector import detect as _detect_events
        current_user = ctx.get("user", {}) if ctx else {}
        events = _detect_events(user_input, current_user=current_user)
        if not events:
            return []

        from pipeline.event_enricher import enrich_event
        import json
        _EVENTS_DIR = TOOLS_DIR.parent / "memory" / "events"

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


# ══════════════════════════════════════════════════════════════
# A · 闲聊/兜底
# ══════════════════════════════════════════════════════════════

def handle_A(user_input, ctx=None):
    """A·闲聊/兜底：日常寒暄、情绪倾诉、无工班实质内容"""
    return _llm(user_input,
                system_prompt="你是工班AI助手，回答简洁直接，用口语化中文。",
                use_history=True)


# ══════════════════════════════════════════════════════════════
# G · 排班考勤：请假、排班、值班、调休
# ══════════════════════════════════════════════════════════════

def handle_B(user_input, ctx=None):
    """G·排班考勤：请假、排班、值班、调休"""
    raw = _subprocess_script("plugins/task_manager/manage_tasks.py", user_input)
    if not raw.strip():
        return "任务管理执行完成（无输出）"
    return _llm(f"格式化以下待办信息:\n{raw[:2000]}\n用户原话: {user_input}",
                system_prompt="将待办数据格式化为清晰的工作提醒。",
                max_tokens=800)


# ══════════════════════════════════════════════════════════════
# （已弃用于新路由，原 改/跑/编辑/部署）
# ══════════════════════════════════════════════════════════════

def handle_C(user_input, ctx=None):
    """（已弃用于新路由，原 改/跑/编辑/部署）"""
    import re as _re

    # "跑 X" / "执行 X" → subprocess
    m = _re.match(r"(?:跑|执行|运行|启动)\s+(.+)", user_input)
    if m:
        cmd = m.group(1)
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            out = (result.stdout or "") + (result.stderr or "")
            return out[:2000] or "命令执行完成"
        except subprocess.TimeoutExpired:
            return "命令执行超时（>60s）"
        except Exception as e:
            return f"执行失败: {e}"

    # "改 X Y" / "编辑 X Y" → file edit
    m = _re.match(r"(?:改|编辑|修改)\s+(\S+)\s+(.+)", user_input)
    if m:
        raw_path = m.group(1)
        fpath = Path(raw_path)
        if not fpath.is_absolute():
            fpath = ROOT_DIR / fpath
        if not fpath.exists():
            return f"文件不存在: {fpath}"
        old_content = fpath.read_text(encoding="utf-8")
        instruction = m.group(2)
        new_content = _llm(
            f"当前文件:\n```\n{old_content[:4000]}\n```\n\n用户要求: {instruction}\n\n输出修改后的完整文件内容。",
            system_prompt="你是文件编辑器。只输出修改后的完整文件内容，不含任何额外文字。",
            max_tokens=4000, temperature=0.2)
        if new_content and not new_content.startswith("[LLM 错误]"):
            fpath.write_text(new_content, encoding="utf-8")
            return f"文件已更新: {fpath}"
        return f"编辑失败: {new_content}"

    # fallback: ask LLM what to do
    return _llm(f"用户希望执行: {user_input}\n请输出建议的 shell 命令或操作步骤。",
                system_prompt="你是工班助手。输出具体的操作命令。",
                max_tokens=500)


# ══════════════════════════════════════════════════════════════
# D·制度规范 / F·防汛安全 / I·知识学习：知识库检索
# ══════════════════════════════════════════════════════════════

def handle_D(user_input, ctx=None):
    """D·制度规范 / F·防汛安全 / I·知识学习：知识库检索与规范查询"""
    core = _load_core()
    result = core.search(user_input, types=["semantic"], top_k=5)
    hits = result.get("hits", [])

    # 相似度阈值：all-MiniLM-L6-v2 对中文领域术语匹配度差，
    # 低于 0.55 视为误中，走关键词回退
    RELEVANCE_THRESHOLD = 0.60
    _vec_ok = bool(hits) and hits[0]["r"] >= 0.55
    if _vec_ok:
        _top = hits[0]
        _top_text = f'{_top.get("s","")} {_top.get("c","")}'
        _vec_ok = any(c in _top_text for c in user_input if len(c) > 1)

    if not _vec_ok:
        raw = _subprocess_script("plugins/knowledge_router/query_knowledge.py", user_input, timeout=15)
        try:
            kw_data = json.loads(raw)
            lines = []
            for fname, ctx_list in kw_data.get("content", {}).items():
                for ctx in ctx_list[:2]:
                    lines.append(f"【{fname}】\n{ctx[:600]}")
            base = "\n\n".join(lines[:4]) if lines else raw[:2000]
        except (json.JSONDecodeError, Exception):
            base = raw[:2000]
    else:
        from guard.sanitizer import sanitize_hits_as_text
        base = sanitize_hits_as_text(hits)

    event_context = ""
    try:
        sys.path.insert(0, str(TOOLS_DIR))
        from memory.event_context import get_related_event_context
        event_context = get_related_event_context(user_input)
    except Exception:
        pass

    entity_ctx = ""
    try:
        from routing.entity_resolver import resolve_entities
        resolved = resolve_entities(user_input)
        entities = resolved.get("entities", [])
        if entities:
            parts = []
            for e in entities[:3]:
                role = e.get("role", "")
                parts.append(f"{e['name']}" + (f"（{role}）" if role else ""))
            entity_ctx = f"\n已知实体: {'、'.join(parts)}\n"
    except Exception:
        pass

    user_prompt = inject_user_prompt(ctx) if ctx else ""
    return _llm(_truncate(f"{user_prompt}\n用户问: {user_input}\n\n检索结果:\n{base}{entity_ctx}{event_context}", 12000),
                system_prompt="你是工班AI助手。如果消息来自其他人，你是执行方，不要说'建议X做'或'让X做'，直接回答如何落实。口语化中文。",
                use_history=True)


# ══════════════════════════════════════════════════════════════
# E·台账报表 / H·任务分配：状态分析、团队分配
# ══════════════════════════════════════════════════════════════

def handle_E(user_input, ctx=None):
    """E·台账报表 / H·任务分配：状态分析、团队分配"""
    core = _load_core()

    # 1. 个人工作查询分支
    import re as _re_e
    _work_patterns = ["我.*工作", "有什么[待要]办", "我的任务", "今天做", "明天做", "周一做"]
    if any(_re_e.search(p, user_input) for p in _work_patterns):
        try:
            sys.path.insert(0, str(TOOLS_DIR))
            from work.work_query import get_my_tasks
            from work.work_view import build_work_view, render_work_view
            work_result = get_my_tasks(user_input)
            if work_result.get("person"):
                from guard.tracer import get_tracer
                t = get_tracer()
                if t:
                    t.set_pipeline(work_result)
                from guard.sanitizer import sanitize_context
                view_json = build_work_view(work_result)
                work_ctx = render_work_view(view_json)
                work_ctx = sanitize_context(work_ctx)
                answer = _llm(
                    _truncate(f"用户问: {user_input}\n\n请将以下工作报告转换为自然语言，不要修改事实、不要删除截止时间、不要改变责任表述：\n\n{work_ctx}", 10000),
                    system_prompt="你是工班管理助手。将报告转口语化中文。规则：①开头说'[名字]，[日期]（周一）工作安排' ②保持四栏结构，每栏换行 ③不改日期、人名、截止时间 ④绝不说'今天/明天/昨天'等相对词，只用绝对日期 ⑤不加原文没有的内容。",
                    use_history=True)
                return answer
        except Exception:
            pass

    # 2. episodic memory search
    hist = core.search(user_input, types=["episodic"], top_k=3)

    # 2. state analysis
    state_data = _subprocess_script("plugins/state_analyzer/analyze_state.py", user_input, timeout=15)

    # 3. event context
    event_context = ""
    try:
        sys.path.insert(0, str(TOOLS_DIR))
        from memory.event_context import get_related_event_context
        event_context = get_related_event_context(user_input)
    except Exception:
        pass

    # 4. LLM synthesis
    from guard.sanitizer import sanitize_context
    prompt_state = f"用户问: {user_input}\n\n历史经验:\n"
    prompt_state += json.dumps([h['c'][:300] for h in hist.get('hits', [])], ensure_ascii=False)
    prompt_state += f"\n\n当前状态:\n{sanitize_context(state_data[:2000])}{sanitize_context(event_context)}"
    answer = _llm(
        _truncate(prompt_state, 10000),
        system_prompt="你是工班管理助手。分析团队状态，给出建议。口语化中文。",
        use_history=True)

    # 5. save to memory
    core.save(situation=user_input, action="状态分析", outcome=answer[:200])

    # 6. reflect
    core.reflect(since_days=1)

    # 7. write observation
    _subprocess_script("memory/observation_writer/write_observation.py",
                       "团队状态", user_input[:80], timeout=10)

    return answer


# ══════════════════════════════════════════════════════════════
# （已合并到 handle_D）
# ══════════════════════════════════════════════════════════════

def handle_F(user_input, ctx=None):
    """（已合并到 handle_D：防汛安全 → 知识库检索）"""
    return handle_D(user_input, ctx=ctx)


# ══════════════════════════════════════════════════════════════
# B · 总结汇报：保存记忆 + 触发反思
# ══════════════════════════════════════════════════════════════

def handle_G(user_input, ctx=None):
    """B·总结汇报：保存记忆 + 触发反思"""
    core = _load_core()
    result = core.save(situation=user_input, action="经验总结",
                       outcome="用户主动总结", importance="medium")
    core.reflect(since_days=1)

    # trigger curiosity engine
    try:
        from memory.curiosity_engine import CuriosityEngine
        ce = CuriosityEngine(core)
        tasks = ce.scan_and_generate_tasks()
        task_list = "\n".join(f"  · {t['trigger'][:60]}" for t in tasks[:5])
        extra = f"\n好奇心扫描: {len(tasks)} 个待探索任务\n{task_list}" if tasks else ""
    except Exception:
        extra = ""

    return f"经验已保存 (id: {result['id']}, 重要性: {result['importance']}){extra}"


# ══════════════════════════════════════════════════════════════
# （已合并到 handle_E）
# ══════════════════════════════════════════════════════════════

def handle_H(user_input, ctx=None):
    """（已合并到 handle_E：任务分配 → 状态分析、团队分配）"""
    return handle_E(user_input, ctx=ctx)


# ══════════════════════════════════════════════════════════════
# C · 分析排查：慢思考引擎
# ══════════════════════════════════════════════════════════════

def handle_I(user_input, ctx=None):
    """C·分析排查：慢思考引擎"""
    from reasoning.slow_think import think
    result = think(user_input)

    lines = ["【思维树】"]
    for t in result.get("tree", []):
        label = t["hypothesis"][:60]
        risk = t.get("risk", "?")
        lines.append(f"  • {label}  (风险:{risk})")
        if t.get("past_case"):
            lines.append(f"    参考: {t['past_case'][:60]}")

    arb = result.get("arbitration", {})
    best = arb.get("best")
    if best:
        lines.append(f"\n【推荐】{best['option'][:80]}")
        lines.append(f"  得分: {best['total_score']} | veto: {best.get('vetoed', False)}")
    lines.append(f"\n{arb.get('rationale', '')}")

    conflicts = result.get("conflicts", [])
    if conflicts:
        lines.append(f"\n⚠️ 发现 {len(conflicts)} 条记忆矛盾:")
        for c in conflicts:
            lines.append(f"  · {c.get('detail', '')[:60]}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Dispatch
# ══════════════════════════════════════════════════════════════

HANDLERS = {
    # A（闲聊/兜底）—— 保持不变
    "A": handle_A,
    # B（总结汇报）—— 原 G，memory_save + reflect
    "B": handle_G,
    # C（分析排查）—— 原 I，slow_think
    "C": handle_I,
    # D（制度规范）—— 保持不变
    "D": handle_D,
    # E（台账报表）—— 保持不变
    "E": handle_E,
    # F（防汛安全）—— 同 D，知识库检索
    "F": handle_D,
    # G（排班考勤）—— 原 B，task_manager
    "G": handle_B,
    # H（任务分配）—— 同 E，团队分配
    "H": handle_E,
    # I（知识学习）—— 同 D，知识库检索
    "I": handle_D,
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


def handle(user_input, mode=None):
    import os
    if os.environ.get("CORE_MODE") == "1":
        return handle_core(user_input)

    if mode is None:
        mode = os.environ.get("COMPOSER_MODE", "composite")

    from guard.tracer import RequestTracer, log_error
    tracer = RequestTracer(user_input)

    ctx = build_request_context()

    # ── lifecycle: update event states from message ──
    try:
        sys.path.insert(0, str(TOOLS_DIR))
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

    # ── Phase 1.7.7: detect events and enrich with AI content extraction ──
    # Must run AFTER lifecycle to avoid new events being processed by
    # update_from_message (e.g. "周一完成" would complete the just-created event)
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


# ══════════════════════════════════════════════════════════════
# Core pipeline (Phase 1.8): Event → Context → Task → Reply
# ══════════════════════════════════════════════════════════════

def handle_core(user_input):
    """New pipeline: Event → Context → Task → Reply.
    Enabled via CORE_MODE=1 env var."""
    from core.event import extract
    from core.context import resolve as ctx_resolve
    from reasoning.llm_client import call as _llm

    from context.request_context import build_request_context
    ctx = build_request_context()
    user = ctx["user"]

    event = extract(user_input, current_user=user)

    # ── Event Recorder: persist every confirmed Event to memory/events/log.jsonl ──
    try:
        from memory.event_recorder import record
        record(event)
    except Exception:
        pass

    # ── Feedback branch: executor reports completion → update task status ──
    if event.get("event_type") == "feedback":
        from organization.model import OrganizationModel
        from task.manager import TaskManager
        fb_tm = TaskManager(OrganizationModel())
        result = fb_tm.update_from_event(event)
        if result.get("matched"):
            if result.get("all_done"):
                msg = f"✅ {result['executor']} 已完成。全员完成，任务 {result['task_id']} 已关闭。"
            else:
                msg = f"✅ 已记录：{result['executor']} 完成。"
        else:
            msg = result.get("reason", "未匹配到任务")
        return f"[Core:feedback]\n{msg}"

    subject_ctx = ctx_resolve(event, user)

    # ── Task Manager: create task from event + context ──
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
        "你是李林骁的认知系统。基于事件分析客观汇报理解，不替用户决策。"
        "禁止使用询问语气（\"您看要不要\"\"需要我帮您吗\"\"我来安排\"）。"
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
        f"当前用户: 李林骁（工班长，铁炉西工班）\n"
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

    return f"[Core:{pos_type}]\n{answer}"


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main():
    import os
    if len(sys.argv) > 1 and sys.argv[1] == "--core":
        os.environ["CORE_MODE"] = "1"
        sys.argv.pop(1)

    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        print("工班AI (wrapper 硬路由模式)。输入 exit 退出。")
        while True:
            try:
                user_input = input("\n> ").strip()
                if not user_input or user_input.lower() in ("exit", "quit"):
                    break
                print(handle(user_input))
            except (KeyboardInterrupt, EOFError):
                break
        return

    user_input = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not user_input and not sys.stdin.isatty():
        user_input = sys.stdin.read().strip()

    if user_input:
        print(handle(user_input))
    else:
        print("用法: python3 tools/routing/wrapper.py '<问题>'\n  或: python3 tools/routing/wrapper.py --interactive\n  或: python3 tools/routing/wrapper.py --core '<问题>'")


if __name__ == "__main__":
    main()
