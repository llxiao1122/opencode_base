"""
core/cognitive_loop.py — 2-step 认知反馈环.

Step 1: Probe — LLM 单次调用 (分析+假设+评分+标签)
Step 2: Simulate — 对最优假设做因果推演
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext

_SIM_TRIGGERS = ["如果", "假如", "假设", "会怎样", "万一", "不干预", "为什么"]


class CognitiveLoop:
    def __init__(self, llm, simulator, store):
        self._llm = llm
        self._simulator = simulator
        self._store = store

    @classmethod
    def build_default(cls):
        from skills.core.llm_client import call as _llm
        from skills.reasoning.simulator import CausalSimulator
        from skills.memory.observation_store import write

        return cls(
            llm=_llm,
            simulator=CausalSimulator(llm=_llm),
            store=write,
        )

    def run(self, ctx: RequestContext) -> None:
        if not self._should_trigger(ctx):
            return

        # Step 1: Probe — LLM 单次调用
        probe_result = self._probe(ctx.message)
        if not probe_result:
            return

        self._store(
            f"分析: {probe_result['analysis'][:200]}",
            source="cognitive", obs_type="probe",
            layer="pattern", confidence=0.7,
        )
        for h in probe_result.get("hypotheses", []):
            self._store(
                f"假设 {h['id']}: {h['statement'][:120]} | 安全={h['scores'].get('safety','?')} 效率={h['scores'].get('efficiency','?')}",
                source="cognitive", obs_type="hypothesis",
                layer="pattern", confidence=0.6,
            )
        if probe_result.get("tags"):
            self._store(
                f"标签: {', '.join(probe_result['tags'])}",
                source="cognitive", obs_type="cognitive_tags",
                layer="conclusion", confidence=0.5,
            )

        # Step 2: Simulate — 对最高分假设做因果推演
        best = probe_result["hypotheses"][0]
        try:
            sim = self._simulator.run(best["statement"], time_horizon_hours=12)
            if isinstance(sim, dict) and sim.get("scenario"):
                summary = sim.get("scenario", "")[:120]
                worst = sim.get("worst_case", "")[:120]
                self._store(
                    f"推演[{best['id']}]: {summary} | 最坏情况: {worst}",
                    source="cognitive", obs_type="simulation",
                    layer="conclusion", confidence=0.7,
                )
        except Exception:
            pass

    def _probe(self, message: str) -> dict:
        prompt = (
            f"分析以下问题，输出 JSON 格式：\n\n{message}\n\n"
            "输出格式：\n"
            "{\n"
            '  "analysis": "问题本质一句话分析",\n'
            '  "hypotheses": [\n'
            "    {\n"
            '      "id": "h1",\n'
            '      "statement": "假设内容",\n'
            '      "scores": {"safety": 0-1, "efficiency": 0-1, "compliance": 0-1, "collaboration": 0-1, "growth": 0-1},\n'
            '      "alignment": "该假设的出发点说明"\n'
            "    }\n"
            "  ],\n"
            '  "tags": ["标签1", "标签2"]\n'
            "}\n"
            "只输出 JSON，不要额外文字。"
        )
        try:
            raw = self._llm(prompt, system_prompt="你是安全分析专家，输出严格 JSON。",
                            max_tokens=1000, temperature=0.3)
            raw = str(raw).strip() if raw else ""
            import json
            data = json.loads(raw)
            if not data.get("hypotheses"):
                return None
            return data
        except json.JSONDecodeError:
            return None
        except Exception:
            return None

    def _should_trigger(self, ctx: RequestContext) -> bool:
        if any(kw in ctx.message for kw in _SIM_TRIGGERS):
            return True
        return False
