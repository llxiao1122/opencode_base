"""
routing/entry.py — Cipher main entry (Phase 13).

Route dispatch only. Handlers live in routing/{profile,task,knowledge}_handler.py.

Usage:
  python3 skills/routing/entry.py '<消息>'
  python3 skills/routing/entry.py --core '<消息>'
"""

import sys, os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(TOOLS_DIR))

_VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python3"
if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
    os.execve(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv, os.environ)

_index_built = False

_CHANGE_KW = ["负责", "接手", "调整", "转交", "改管", "分管", "接管",
              "离职", "休假", "调走", "借调", "辞职", "退休"]


def _build_index_once():
    global _index_built
    if _index_built:
        return
    try:
        from routing.builder import build
        build()
    except Exception:
        pass
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
    except Exception:
        pass


def _apply_changes_direct(changes):
    import json
    path = ROOT_DIR / "state" / "entity_index.json"
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
    except Exception:
        pass


def handle_core(user_input):
    _build_index_once()
    _update_event_lifecycle(user_input)

    from core.pipeline import Pipeline
    from shared.schema import RequestContext

    pipe = Pipeline.build_default()
    rctx = RequestContext(message=user_input)
    result = pipe.run(rctx)

    _detect_entity_changes(user_input)
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
        print("用法: python3 skills/routing/entry.py '<消息>'")
