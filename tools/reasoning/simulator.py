#!/usr/bin/env python3
"""
simulator.py - 轻量级因果模拟引擎
基于当前状态与假设条件，利用 LLM 推理能力进行结构化推演。
只做被动推理（用户提问触发），不做主动扫描。
"""

import sys, json, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory.memory_core import MemoryCore
from reasoning.llm_client import call as call_llm


class CausalSimulator:
    def __init__(self, core: MemoryCore):
        self.core = core

    def run(self, scenario, time_horizon_hours=24, lightweight=True):
        raw = self._simulate(scenario, time_horizon_hours, lightweight)
        return self._parse_with_retry(raw, scenario, time_horizon_hours)

    def _simulate(self, scenario, time_horizon_hours, lightweight):
        hist_top_k = 3 if lightweight else 5
        hist_max_chars = 150 if lightweight else None
        know_top_k = 1 if lightweight else None
        know_max_chars = 500 if lightweight else 2000

        history = self.core.search(query=scenario, types=["episodic"], top_k=hist_top_k)
        if lightweight and hist_max_chars:
            for h in history.get("hits", []):
                h["c"] = h.get("c", "")[:hist_max_chars]

        if lightweight:
            raw_know = self.core.search(query=scenario, types=["semantic"], top_k=know_top_k)
            knowledge = {"result": "".join(h["c"][:know_max_chars] for h in raw_know.get("hits", []))}
        else:
            knowledge = self.core.retrieve(topic=scenario, max_chars=know_max_chars)

        prompt = self._build_prompt(scenario, history, knowledge, time_horizon_hours, lightweight)
        max_tokens = 800 if lightweight else 2000
        return call_llm(prompt, temperature=0.3, max_tokens=max_tokens)

    def _build_prompt(self, scenario, history, knowledge, horizon, lightweight):
        if lightweight:
            return f"""你是工地安全模拟引擎。只输出最关键的干预建议，返回 JSON，不要额外文字。

【场景】{scenario}
【时间范围】未来 {horizon} 小时

【参考历史经验】
{json.dumps(history.get("hits", []), ensure_ascii=False, indent=2)}

【参考规范】
{knowledge.get("result", "")}

【输出 JSON 格式】
{{
  "scenario": "...",
  "critical_windows": [
    {{
      "deadline": "2h",
      "domain": "flood",
      "action": "启动备用水泵，清理排水沟",
      "avoided_risk": "积水超警戒线进入库房"
    }}
  ],
  "worst_case": "若不干预，{horizon}小时后..."
}}"""

        return f"""你是工地安全模拟引擎。严格按以下框架推演，只返回 JSON，不要额外文字。

【场景】{scenario}
【时间范围】未来 {horizon} 小时

【参考历史经验】
{json.dumps(history.get("hits", []), ensure_ascii=False, indent=2)}

【参考规范】
{knowledge.get("result", "")}

【推演规则】
- 每个事件必须标注上游原因（cause_chain），不只描述结果
- 参数变化必须翻译为具体操作层面的影响（operational_impact），不用纯数字
- 每个干预窗口必须指定责任域（domain），从以下选择：safety/flood/quality/schedule/paperwork/personnel

【输出 JSON 格式】
{{
  "scenario": "...",
  "timeline": [
    {{
      "time": "1h",
      "event": "...",
      "cause_chain": "因排水泵仅开2台且排水沟堵塞 → 排水速率不足 → ...",
      "parameters": {{"water_level": "0.3m"}},
      "operational_impact": "底层货架纸箱底部可能吸水变形，需人工转移约X件物资",
      "risk": "low"
    }},
    ...
  ],
  "critical_windows": [
    {{
      "deadline": "2h",
      "domain": "flood",
      "action": "启动备用水泵，清理排水沟",
      "avoided_risk": "积水超警戒线进入库房",
      "responsible_domain": "flood"
    }}
  ],
  "worst_case": "若不干预，{horizon}小时后可能发生边坡坍塌。"
}}"""

    def _parse_with_retry(self, raw, scenario, horizon, max_retries=2):
        if isinstance(raw, str) and raw.startswith("{"):
            raw = raw
        elif isinstance(raw, dict) and "error" in raw:
            return {
                "error": raw["error"],
                "scenario": scenario,
                "timeline": [],
                "critical_windows": [],
                "worst_case": "模拟失败，请人工评估。",
            }

        for attempt in range(max_retries + 1):
            try:
                return json.loads(self._extract_json(raw))
            except (json.JSONDecodeError, TypeError):
                if attempt < max_retries:
                    raw = call_llm(
                        f"你上次返回的格式不符合 JSON 规范。请重新输出，必须是一个合法的 JSON 对象。\n原内容摘要：{str(raw)[:500]}",
                        temperature=0.3,
                        max_tokens=1500,
                    )
                else:
                    return {
                        "error": "JSON 解析失败",
                        "raw_text": str(raw)[:1000],
                        "scenario": scenario,
                        "timeline": [],
                        "critical_windows": [],
                        "worst_case": "无法确定，请人工评估。",
                    }

    def _extract_json(self, text):
        text = str(text)
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return match.group(1)
        text = text.strip()
        if text.startswith("{"):
            return text
        return text


# ══════════════════════════════════════════════════════════════
# CLI test
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    core = MemoryCore(root_path="/home/admin/opencode")
    sim = CausalSimulator(core)

    scenario = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "明天暴雨若不停工，库房会怎样"
    print(f"模拟: {scenario}")
    result = sim.run(scenario, time_horizon_hours=12)
    print(json.dumps(result, ensure_ascii=False, indent=2))
