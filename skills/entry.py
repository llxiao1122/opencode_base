"""
skills/entry.py — Cipher 主入口。

用法：
  python3 -m skills.entry '<消息>'        # 单次处理
  python3 -m skills.entry --listen          # 持久服务模式（TCP 长驻）
  python3 -m skills.entry --warm            # 预加载索引后退出

流程：
  用户消息 → 分类 (FAISS / 关键词) → 高置信走 _fast_dispatch → 否则走 Agent
  后处理 → 实体变更检测 + 决策日志 + 异步反射 + 守护线程
"""

import logging, os, re, sys, threading
from pathlib import Path

# Ensure skills/ is importable before anything else
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _p in [str(_PROJECT_ROOT), str(_PROJECT_ROOT / "skills")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from skills.shared.path import ensure_paths, root as _root

ensure_paths()

logger = logging.getLogger(__name__)

ROOT_DIR = _root()

os.environ.setdefault("HF_HUB_OFFLINE", "1")

_index_built = False
_daemon_started = False

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






_FAST_HANDLERS = {
    "task_query":         ("skills.agent.handlers.task_query", "handle"),
    "knowledge_retrieve": ("skills.agent.handlers.knowledge_retrieve", "handle"),
    "profile_query":      ("skills.agent.handlers.profile_query", "handle"),
}


def _fast_dispatch(route: str, user_input: str, ctx) -> str:
    hit = _FAST_HANDLERS.get(route)
    if not hit:
        return "[Cipher:error]\n未知路由"
    if callable(hit):
        return hit(user_input, ctx)
    import importlib
    mod_path, func_name = hit
    mod = importlib.import_module(mod_path)
    handler = getattr(mod, func_name)
    return handler(user_input, ctx)


def _search_episodic(user_input: str) -> str:
    """搜索 worldview 档案，返回格式化情景记忆。仅 Agent 路径调用。"""
    try:
        from skills.memory.worldview import search as wv_search
        hits = wv_search(user_input, top_k=2)
        if not hits:
            return ""
        lines = ["[世界观档案]:"]
        for h in hits:
            snippet = h.get("content", "")[:300].replace("\n", " ").strip()
            lines.append(f"  • {h['entity_id']} ({h['type']}) {snippet}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("worldview search failed: %s", e)
        return ""


def handle_core(user_input: str) -> str:
    from skills.shared.tracer import Tracer
    tracer = Tracer()

    _build_index_once()

    from skills.shared.schema import RequestContext, CT
    from skills.router.faiss_router import classify

    rctx = RequestContext(message=user_input, trace_id=tracer.trace_id)
    rctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
    route = None
    confidence = 0.0

    with tracer.span("entry.route", input_len=len(user_input)):
        route, confidence = classify(user_input)

        if route == "correction" and confidence >= 0.5:
            with tracer.span("workflow.correction"):
                from skills.workflow.engine import WorkflowEngine
                wf_result = WorkflowEngine(tracer=tracer).run("correction", user_input, rctx)
                result = wf_result.text
                tool_id = "correction"
                rctx.route = "correction"
                rctx.confidence = confidence
        elif confidence >= CT.HIGH and route != "event":
            with tracer.span("fast_dispatch", route=route):
                result = _fast_dispatch(route, user_input, rctx)
                tool_id = route
                rctx.route = route
                rctx.confidence = confidence
        else:
            with tracer.span("agent.run"):
                rctx.memory_context = _search_episodic(user_input)
                from agent.engine import run as agent_run
                result = agent_run(user_input, rctx, tracer=tracer)
                tool_id = rctx.route if rctx.route else route

    with tracer.span("post_process"):
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

    tracer.dump()

    conf_label = rctx.confidence or confidence or 0.0
    result = re.sub(
        r'^\[Cipher:(\w+)\]',
        lambda m: f'[Cipher:{m.group(1)}@{conf_label:.2f}]',
        result
    )
    result = result.replace("李林骁", "主人")
    return result


def _serve(host: str = "127.0.0.1", port: int = 9099):
    import socketserver

    _build_index_once()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            raw = self.rfile.readline()
            if not raw:
                return
            msg = raw.decode("utf-8").strip()
            if msg:
                try:
                    result = handle_core(msg)
                except Exception as e:
                    logger.error("server handle failed: %s", e, exc_info=True)
                    result = f"[Cipher:error]\n处理失败: {e}"
                self.wfile.write((str(result or "") + "\n").encode("utf-8"))

    server = socketserver.ThreadingTCPServer((host, port), Handler)
    logger.info("Cipher server listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    _VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python3"
    if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
        env = os.environ.copy()
        expat_lib = "/opt/homebrew/opt/expat/lib"
        env["DYLD_LIBRARY_PATH"] = f"{expat_lib}:{env.get('DYLD_LIBRARY_PATH', '')}"
        os.execve(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv, env)

    args = sys.argv[1:]

    if args and args[0] == "--core":
        os.environ["CORE_MODE"] = "1"
        args.pop(0)

    if args and args[0] == "--listen":
        port = 9099
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                try:
                    port = int(args[idx + 1])
                except ValueError:
                    pass
        _serve(port=port)
        sys.exit(0)

    if args and args[0] == "--warm":
        _build_index_once()
        logger.info("Warm done — all indices loaded.")
        sys.exit(0)

    user_input = " ".join(args) if args else ""
    if not user_input and not sys.stdin.isatty():
        user_input = sys.stdin.read().strip()

    if user_input:
        print(handle_core(user_input))
    else:
        print("用法: python3 -m skills.entry '<消息>'")
