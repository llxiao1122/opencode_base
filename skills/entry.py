"""
skills/entry.py — Cipher main entry.

Usage:
  python3 -m skills.entry '<消息>'
  python3 -m skills.entry --core '<消息>'
"""

import logging, os, sys, threading, typing
from pathlib import Path

from skills.shared.path import ensure_paths, root as _root

ensure_paths()

logger = logging.getLogger(__name__)

ROOT_DIR = _root()

_VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python3"
if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
    os.execve(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv, os.environ)

_index_built = False
_daemon_started = False

_CHANGE_KW = ["负责", "接手", "调整", "转交", "改管", "分管", "接管",
              "离职", "休假", "调走", "借调", "辞职", "退休"]
_CORRECTION_KW = ["不对", "不是", "错了", "纠错", "应该", "改成",
                  "不应该是", "你说错了", "你搞错了"]


def _build_index_once():
    global _index_built
    if _index_built:
        return
    try:
        from skills.router.builder import build
        build()
    except Exception as e:
        logger.warning("entity index build() failed: %s", e, exc_info=True)
    try:
        from skills.router.faiss_router import _get_index
        _get_index()
    except Exception as e:
        logger.warning("FAISS index _get_index() failed: %s", e, exc_info=True)
    _index_built = True


def _detect_entity_changes(user_input):
    if not any(kw in user_input for kw in _CHANGE_KW):
        return
    try:
        from memory.change_detector import detect as cd_detect
        changes = cd_detect(user_input)
        if not changes:
            return
        _apply_changes_direct(changes)
    except Exception as e:
        logger.warning("entity change detection failed: %s", e, exc_info=True)


def _apply_changes_direct(changes):
    import json
    path = ROOT_DIR / "data" / "state" / "entity_index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entities = data.get("confirmed_entities", [])
    for c in changes:
        if c.get("confidence", 0) < 0.80:
            continue
        name = c["entity"]
        new_role = c["new_value"]
        found = False
        for e in entities:
            if e["name"] == name:
                e["role"] = new_role
                found = True
                break
        if not found:
            entities.append({
                "name": name,
                "aliases": [],
                "route_hint": ["G"],
                "weight": 1.0,
                "role": new_role,
                "source": "change_detector",
            })
    data["_meta"]["updated"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _update_event_lifecycle(user_input):
    try:
        from memory.event_lifecycle import update_from_message
        update_from_message(user_input)
    except Exception as e:
        logger.warning("event lifecycle update failed: %s", e, exc_info=True)


def _auto_handle_corrections(user_input: str) -> typing.Optional[str]:
    if not any(kw in user_input for kw in _CORRECTION_KW):
        return None
    return "correction_detected"


def _should_route_to_workflow(user_input: str) -> typing.Optional[str]:
    from skills.workflow.definitions import list_triggers
    triggers = list_triggers()
    tag = _auto_handle_corrections(user_input)
    if tag:
        wf_id = triggers.get(tag)
        if wf_id:
            return wf_id
    return None


def _profile_handle(text, ctx):
    from skills.router.entity_resolver import resolve_entities
    resolved = resolve_entities(text)
    entities = resolved.get("entities", [])
    if not entities:
        return "[Cipher:profile]\n暂无记录。"
    e = entities[0]
    return f"[Cipher:profile]\n{e.get('name', '?')}: {e.get('role', '未知')}（{e.get('team', '')}）"

_FAST_HANDLERS = {
    "task_query":         ("skills.agent.handlers.task_query", "handle"),
    "knowledge_retrieve": ("skills.agent.handlers.knowledge_retrieve", "handle"),
    "profile_query":      _profile_handle,
}


def _fast_dispatch(route, user_input, ctx):
    hit = _FAST_HANDLERS.get(route)
    if not hit:
        return None
    if callable(hit):
        return hit(user_input, ctx)
    import importlib
    mod_path, func_name = hit
    mod = importlib.import_module(mod_path)
    handler = getattr(mod, func_name)
    return handler(user_input, ctx)


def handle_core(user_input):
    _build_index_once()
    _update_event_lifecycle(user_input)

    from skills.shared.schema import RequestContext, CT
    from skills.router.faiss_router import classify

    rctx = RequestContext(message=user_input)

    workflow_id = _should_route_to_workflow(user_input)
    if workflow_id:
        from skills.workflow.engine import WorkflowEngine
        wf_result = WorkflowEngine().run(workflow_id, user_input, rctx)
        result = wf_result.text
        tool_id = workflow_id
        rctx.route = workflow_id
        rctx.confidence = 0.9
    else:
        route, confidence = classify(user_input)

        if confidence >= CT.HIGH and route != "event":
            result = _fast_dispatch(route, user_input, rctx)
            tool_id = route
            rctx.route = route
            rctx.confidence = confidence
        else:
            from agent.engine import run as agent_run
            result = agent_run(user_input, rctx)
            tool_id = rctx.route if rctx.route else route

    _detect_entity_changes(user_input)

    try:
        from correction.logger import append
        append(rctx, result, tool_id=tool_id or "")
    except Exception as e:
        logger.warning("decision log append failed: %s", e, exc_info=True)

    try:
        from agent.reflector import reflect
        t = threading.Thread(
            target=reflect,
            args=(tool_id or "", {}, str(result or ""), user_input),
            daemon=True,
        )
        t.start()
    except Exception as e:
        logger.debug("reflect async start failed: %s", e)

    global _daemon_started
    if not _daemon_started:
        _daemon_started = True
        try:
            from skills.trigger.daemon import ProactiveDaemon
            t = threading.Thread(
                target=ProactiveDaemon(check_interval_sec=300).start_loop,
                daemon=True,
            )
            t.start()
            logger.info("ProactiveDaemon thread started")
        except Exception as e:
            logger.warning("daemon start failed: %s", e)

    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--core":
        os.environ["CORE_MODE"] = "1"
        args.pop(0)

    user_input = " ".join(args) if args else ""
    if not user_input and not sys.stdin.isatty():
        user_input = sys.stdin.read().strip()

    if user_input:
        print(handle_core(user_input))
    else:
        print("用法: python3 -m skills.entry '<消息>'")
