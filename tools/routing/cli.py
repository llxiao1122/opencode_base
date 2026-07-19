#!/usr/bin/env python3
"""
routing/cli.py — CLI entry point (extracted from wrapper.py Phase 9).
"""

import sys, os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

_VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python3"
if _VENV_PYTHON.exists() and sys.executable != str(_VENV_PYTHON):
    os.execve(str(_VENV_PYTHON), [str(_VENV_PYTHON)] + sys.argv, os.environ)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--core":
        os.environ["CORE_MODE"] = "1"
        sys.argv.pop(1)

    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        from routing.legacy_pipeline import handle
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

    from routing.legacy_pipeline import handle
    user_input = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not user_input and not sys.stdin.isatty():
        user_input = sys.stdin.read().strip()

    if user_input:
        print(handle(user_input))
    else:
        print("用法: python3 tools/routing/cli.py '<问题>'\n"
              "  或: python3 tools/routing/cli.py --interactive\n"
              "  或: python3 tools/routing/cli.py --core '<问题>'")


if __name__ == "__main__":
    main()
