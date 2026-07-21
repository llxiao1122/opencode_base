#!/usr/bin/env python3
"""
value_arbiter.py - 价值对齐仲裁器 — DEPRECATED: 仅 slow_think 引用（slow_think 也已废弃）
基于 memory/values_profile.json 对多个方案进行加权评判，无 LLM 依赖。
"""

import json
from pathlib import Path


class ValueArbiter:
    def __init__(self, profile_path=None):
        if profile_path is None:
            profile_path = Path(__file__).parent.parent.parent / "memory" / "values_profile.json"
        with open(profile_path, "r", encoding="utf-8") as f:
            self.profile = json.load(f)
        self.values = self.profile["core_values"]

    def evaluate(self, options):
        """对 slow_think 输出的方案列表进行仲裁。

        options = [
            {
                "hypothesis": "...",
                "impacts": {
                    "human_safety": "safe",          # 硬约束: "safe" | "violated"
                    "structural_safety": 0.8,        # 数值: 0.0-1.0
                    ...
                }
            }
        ]
        """
        scored = []
        for opt in options:
            impacts = opt.get("impacts", {})
            total = 0.0
            breakdown = {}
            vetoed = False
            veto_reason = ""

            for dim, cfg in self.values.items():
                if cfg.get("is_hard_constraint"):
                    violation = impacts.get(dim, "safe")
                    if violation == "violated":
                        vetoed = True
                        veto_reason = cfg["hard_constraint_rule"]
                        breakdown[dim] = {"raw": 0, "weighted": 0, "weight": cfg["weight"], "vetoed": True}
                        continue
                    breakdown[dim] = {"raw": "safe", "weighted": cfg["weight"], "weight": cfg["weight"], "vetoed": False}
                    total += cfg["weight"]
                    continue

                raw = impacts.get(dim, 0.5)
                raw = max(0.0, min(1.0, float(raw)))
                weighted = cfg["weight"] * raw
                total += weighted
                breakdown[dim] = {"raw": raw, "weighted": weighted, "weight": cfg["weight"]}

            label = opt.get("hypothesis", str(opt))
            if isinstance(opt, dict) and "risk" in opt:
                label = opt.get("hypothesis", "")

            scored.append({
                "option": label,
                "total_score": round(total, 3),
                "breakdown": breakdown,
                "vetoed": vetoed,
                "veto_reason": veto_reason,
            })

        scored.sort(key=lambda x: (x["vetoed"], -x["total_score"]))

        best = scored[0] if scored else None

        return {
            "ranked": scored,
            "best": best,
            "rationale": self._explain(scored) if best else "无有效方案。",
        }

    def _explain(self, scored):
        lines = []
        for i, s in enumerate(scored[:3]):
            label = s["option"]
            if len(label) > 50:
                label = label[:47] + "..."
            if s["vetoed"]:
                lines.append(f"方案{i+1}被一票否决：{s['veto_reason']}")
            else:
                lines.append(f"方案{i+1}（{label}）：综合得分 {s['total_score']:.2f}")
        return "；".join(lines)


# ══════════════════════════════════════════════════════════════
# CLI test
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    arbiter = ValueArbiter()

    tests = [
        {
            "hypothesis": "方案A：暴雨继续施工，加派人工抽水",
            "impacts": {"human_safety": "violated", "structural_safety": 0.6, "schedule_progress": 0.9},
        },
        {
            "hypothesis": "方案B：停工加固，启用备用水泵",
            "impacts": {"human_safety": "safe", "structural_safety": 0.9, "schedule_progress": 0.4},
        },
        {
            "hypothesis": "方案C：减员施工，核心岗位上岗",
            "impacts": {"human_safety": "safe", "structural_safety": 0.7, "cost_efficiency": 0.8},
        },
    ]

    result = arbiter.evaluate(tests)
    print(json.dumps(result, ensure_ascii=False, indent=2))
