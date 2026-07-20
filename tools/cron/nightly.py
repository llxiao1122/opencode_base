"""
cron/nightly.py — Nightly maintenance + analysis.

Run via cron: 0 2 * * * cd /project && python3 -c "from cron.nightly import run; run()"

Steps:
  1. event_maintenance — mark past-deadline events as expired
  2. memory_analyzer — discover behavioral/role patterns → Observation
  3. memory_core.reflect() — LLM experience refinement → Observation
  4. DingTalk push — if new insights found
"""

import sys, json
from pathlib import Path
from datetime import datetime

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))


def run():
    print(f"[nightly] {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    insights = []

    # 1. Event maintenance
    try:
        from memory.event_maintenance import run_maintenance
        expired = run_maintenance()
        if expired:
            insights.append(f"过期事件: {len(expired)}")
            print(f"  maintenance: {len(expired)} expired")
    except Exception as e:
        print(f"  maintenance: FAILED ({e})")

    # 2. Memory analyzer → Observation
    try:
        from memory.memory_analyzer import run as analyzer_run
        candidates = analyzer_run()
        if candidates:
            insights.append(f"行为模式: {len(candidates)} 条")
            print(f"  analyzer: {len(candidates)} observations")
    except Exception as e:
        print(f"  analyzer: FAILED ({e})")

    # 3. Reflect (LLM experience refinement)
    try:
        from memory.memory_core import MemoryCore
        core = MemoryCore(root_path=str(Path(__file__).resolve().parent.parent.parent))
        reflection = core.reflect(since_days=7)
        compressed = reflection.get("compressed", 0)
        if compressed:
            insights.append(f"经验提炼: {compressed} 条")
            print(f"  reflect: {compressed} compressed")
    except Exception as e:
        print(f"  reflect: FAILED ({e})")

    # 4. DingTalk push
    if insights:
        try:
            from plugins.dingbot.send_msg import send_markdown
            msg = "## Cipher 每日洞察\n\n" + "\n".join(f"- {i}" for i in insights)
            result = send_markdown("Cipher 每日洞察", msg)
            print(f"  dingbot: {result}")
        except Exception as e:
            print(f"  dingbot: FAILED ({e})")
    else:
        print("  no new insights")

    print(f"[nightly] done")


if __name__ == "__main__":
    run()
