"""Layer 6 Reflection — observation analysis + pattern extraction + cognitive loop."""

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REFLECTION_MARKER = ROOT / "memory" / ".last_reflection"

MIN_OBSERVATIONS = 1
REFLECTION_COOLDOWN = 0


class DefaultReflector:
    def __init__(self, llm, cognitive_loop=None):
        self._llm = llm
        self._cognitive = cognitive_loop

    def reflect(self, ctx) -> None:
        from skills.memory.observation_store import search as obs_search, write as obs_write

        self._run_phase_a(obs_search, obs_write)

        # Phase B: Cognitive loop (fire-and-forget)
        if self._cognitive:
            try:
                self._cognitive.run(ctx)
            except Exception:
                pass

    def _run_phase_a(self, obs_search, obs_write):
        recent = obs_search(target="", since_days=2, top_k=30)
        if len(recent) < MIN_OBSERVATIONS:
            return
        from collections import defaultdict
        by_subject = defaultdict(list)
        for obs in recent:
            by_subject[obs["subject"]].append(obs)
        for subject, obs_list in by_subject.items():
            if len(obs_list) >= 1:
                self._reflect_subject(subject, obs_list, obs_write)

    def _reflect_subject(self, subject, obs_list, obs_write):
        has_task = any(o.get("type") == "task_completion" for o in obs_list)

        role_context = ""
        if has_task:
            try:
                import json
                idx_path = ROOT / "state" / "entity_index.json"
                if idx_path.exists():
                    entities = json.loads(idx_path.read_text("utf-8"))
                    for e in entities.get("confirmed_entities", []):
                        if e.get("name") == subject:
                            area = e.get("area", "")
                            traits = e.get("traits", "")
                            trust = e.get("trust", "")
                            if area or traits:
                                role_context = f"\n此人的角色: {area}\n特点: {traits}\n管理方式: {trust}\n"
                            break
            except Exception:
                pass

        obs_text = "\n".join(f"- [{o['type']}] {o['fact']}" for o in obs_list[:10])

        if has_task:
            prompt = (
                f"以下是对{subject}的近期观察记录{role_context}。分析这些记录，找出：\n"
                f"1) 此人常负责什么类型的工作\n"
                f"2) 适合分配什么任务\n\n"
                f"观察记录：\n{obs_text}\n\n"
                "输出格式（不要多余文字）：\n"
                "1. 【职责】<一句话>\n"
                "2. 【建议】<一句话>"
            )
        else:
            prompt = (
                f"以下是对{subject}的近期观察记录。分析这些记录，找出：\n"
                f"1) 出现的模式或规律\n"
                f"2) 可提炼的经验教训\n\n"
                f"观察记录：\n{obs_text}\n\n"
                "输出格式（不要多余文字）：\n"
                "1. 【模式】<一句话>\n"
                "2. 【经验】<一句话>"
            )

        try:
            result = self._llm(prompt, system_prompt="你是一个经验丰富的工班长助理，擅长从日常观察中提炼规律。",
                               max_tokens=300, temperature=0.3)
            result = str(result).strip() if result else ""
        except Exception:
            return

        if not result:
            return

        obs_write(result, source="pipeline", obs_type="reflection",
                  layer="pattern", confidence=0.6)


def trigger_reflection():
    """Standalone trigger — can be called from obs_write hook or manually."""
    from skills.memory.observation_store import search, write as obs_write
    recent = search(target="", since_days=2, top_k=30)
    if len(recent) < MIN_OBSERVATIONS:
        return
    from collections import defaultdict
    by_subject = defaultdict(list)
    for obs in recent:
        by_subject[obs["subject"]].append(obs)
    from skills.core.llm_client import call as llm
    r = DefaultReflector(llm=llm)
    for subject, obs_list in by_subject.items():
        if len(obs_list) >= 1:
            r._reflect_subject(subject, obs_list, obs_write)
