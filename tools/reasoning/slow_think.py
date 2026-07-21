#!/usr/bin/env python3
"""
slow_think.py — System 2 慢思考引擎 — DEPRECATED: 废弃，无管线集成
在复杂任务时展开思维树,每条假设实时检索记忆校验,检测矛盾并输出最佳路径。
"""

import sys, json, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory.memory_core import MemoryCore
from memory.user_model import UserContextTracer
from reasoning.value_arbiter import ValueArbiter
from reasoning.simulator import CausalSimulator

ROOT = Path(__file__).resolve().parent.parent.parent
core = MemoryCore(root_path=str(ROOT))
user_tracer = UserContextTracer(core)
arbiter = ValueArbiter()
simulator = CausalSimulator(core)

SIM_TRIGGERS = ["如果", "假如", "假设", "不停工会怎样", "会怎样", "万一", "不干预"]

def _is_counterfactual(problem):
    return any(kw in problem for kw in SIM_TRIGGERS)


def _tree_to_arbiter_options(tree):
    """将 slow_think 的假设树转换为仲裁器可用的选项格式。
    risk 映射为 safety 维度影响（高风险=低安全分），其余维度默认 0.5。
    """
    options = []
    for t in tree:
        risk = t.get("risk", 0.5)
        safety_score = round(max(0.0, 1.0 - risk), 2)
        # 模拟分支自带高风险（worst_case scenario）
        if t.get("source") == "causal_simulation" and t.get("simulation"):
            raw = t["simulation"]
            safety_score = 0.2  # 最坏情况=低安全
        options.append({
            "hypothesis": t["hypothesis"],
            "impacts": {
                "human_safety": "safe",
                "structural_safety": safety_score,
            },
        })
    return options


def think(problem, top_k=5):
    """展开思维树 + 记忆关联 + 冲突检测 + 价值仲裁"""

    # User context: classify domain + load relevant history
    user_ctx = user_tracer.get_context(problem)

    # Generate hypotheses (simplified: delegate to LLM caller)
    hypotheses = _generate_hypotheses(problem)

    tree = []
    past_ids = set()

    # If counterfactual, run simulation first
    if _is_counterfactual(problem):
        try:
            sim_result = simulator.run(problem, time_horizon_hours=12, lightweight=True)
            tree.append({
                "hypothesis": f"【模拟推演】{sim_result.get('worst_case', sim_result.get('scenario', problem))[:80]}",
                "risk": 0.9,
                "source": "causal_simulation",
                "simulation": sim_result,
                "past_case": None,
                "past_eids": [],
            })
        except Exception:
            pass

    for h in hypotheses:
        results = core.search(h, types=["episodic"], top_k=2)
        past_case = None
        past_eids = []
        risk = 0.3  # baseline

        for hit in results.get("hits", []):
            past_ids.add(hit.get("c", "")[:60])
            if hit.get("id"):
                past_eids.append(hit["id"])
            if hit["r"] > 0.7:
                risk += 0.2
                past_case = hit["c"]

        tree.append({
            "hypothesis": h,
            "risk": min(round(risk, 2), 1.0),
            "past_case": past_case,
            "past_eids": past_eids,
        })

    # Conflict detection
    conflicts = _detect_conflicts(tree)

    # Persist conflicts for curiosity engine
    for conflict in conflicts:
        core.register_conflict(conflict)

    # Value arbitration: replace simple risk sort
    arbiter_options = _tree_to_arbiter_options(tree)
    arbitration = arbiter.evaluate(arbiter_options)
    best = arbitration["best"]

    return {
        "tree": tree,
        "conflicts": conflicts,
        "arbitration": arbitration,
        "best_path": best["option"] if best else None,
        "user_context": {
            "domain": user_ctx["active_domain"],
            "history": user_ctx["relevant_history"],
        },
    }


def _generate_hypotheses(problem):
    """Generate 3-5 hypotheses from problem statement.
    Can be extended to call LLM; currently uses heuristic splitting."""
    perspectives = [
        f"假设1：{problem}是设备故障导致",
        f"假设2：{problem}是操作失误导致",
        f"假设3：{problem}是环境因素导致",
        f"假设4：{problem}是制度漏洞导致",
        f"假设5：{problem}是人员安排问题",
    ]
    return perspectives[:min(5, max(3, len(problem) // 10 + 1))]


def _detect_conflicts(tree):
    """Detect contradictory past cases across hypotheses"""
    conflicts = []
    cases = [(t["hypothesis"], t.get("past_case"), t.get("past_eids", []))
             for t in tree if t.get("past_case")]
    for i, (ha, ca, eids_a) in enumerate(cases):
        for j, (hb, cb, eids_b) in enumerate(cases):
            if i >= j:
                continue
            if ca and cb and abs(len(ca) - len(cb)) > 30:
                items = list(set(eids_a + eids_b))
                conflicts.append({
                    "items": items,
                    "nature": "contradicts",
                    "detail": f"{ha[:30]} vs {hb[:30]}",
                })
    return conflicts


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "用法: slow_think.py '<问题>'"}))
        sys.exit(1)

    problem = " ".join(sys.argv[1:])
    result = think(problem)
    print(json.dumps(result, ensure_ascii=False, indent=2))
