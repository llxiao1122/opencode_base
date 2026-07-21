"""Layer 2 Reasoning — decision making."""

import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status


class DefaultReasoningEngine:
    def __init__(self, llm):
        self._llm = llm

    def reason(self, ctx: RequestContext) -> None:
        try:
            if ctx.route == "profile":
                return self._profile_reasoning(ctx)

            if ctx.route != "event" or ctx.event is None:
                ctx.status = Status.REASONING_DONE
                return

            if ctx.event.get("event_type") == "feedback":
                ctx.status = Status.REASONING_DONE
                return

            user = ctx.user or {}
            user_name = user.get("name", "未知")
            user_role = user.get("role", "")
            user_team = user.get("team", "")

            sc = ctx.subject_context or {}
            pos = sc.get("my_position", {})
            pos_type = pos.get("type", "observer")
            reason = pos.get("description", "")

            dl_feasibility = sc.get("deadline_feasibility", {})
            dl_warning = ""
            if dl_feasibility.get("feasible") in (False, "tight"):
                dl_warning = f"\n⚠️ 截止可行性: {dl_feasibility.get('reason', '')}"

            act = ctx.event.get("action", {})
            act_summary = act.get("summary", "") if isinstance(act, dict) else ""
            deadline = ctx.event.get("time", {}).get("deadline", "")

            actors = ctx.event.get("actors", [])
            requester = ""
            for a in actors:
                if a.get("position") == "requester":
                    requester = a.get("name", "")

            event_title = ctx.event.get("raw", ctx.message)[:120]

            contact_info = ""
            if requester:
                role = ""
                for a in actors:
                    if a["name"] == requester:
                        role = a.get("role", "")
                        break
                contact_info = f"发起人: {requester}" + (f"（{role}）" if role else "")

            sys_prompt = (
                f"你是 Cipher，{user_name}的企业认知系统助手。"
                "基于事件分析客观汇报理解，不替用户决策。"
                "禁止使用询问语气。"
                "直接陈述事实、位置、建议行动、截止时间。用动词开头。"
            )

            full_prompt = (
                f"当前用户: {user_name}（{user_role}，{user_team}）\n"
                f"事件摘要: {event_title}\n"
                f"责任类型: {pos_type}（{reason}）\n"
                f"建议行动: {act_summary}\n"
                + (f"截止时间: {deadline}\n" if deadline else "")
                + (f"{contact_info}\n" if contact_info else "")
                + (dl_warning if dl_warning else "")
            )

            # Inject cognitive context if available
            try:
                from skills.memory.observation_store import search as obs_search
                cognitive = obs_search(target=event_title[:30], obs_type="conclusion",
                                       since_days=7, top_k=2)
                if cognitive:
                    ctx_lines = "\n".join(f"- {c['fact']}" for c in cognitive)
                    full_prompt += f"\n【历史推演参考】\n{ctx_lines}\n"
            except Exception:
                pass

            # Inject person profile context for involved actors
            try:
                from skills.memory.observation_store import search as obs_search
                profile_contexts = []
                for a in actors[:3]:
                    name = a.get("name", "")
                    if name:
                        profiles = obs_search(target=name, obs_type="profile_analysis",
                                              since_days=30, top_k=1)
                        for p in profiles:
                            profile_contexts.append(p["fact"][:200])
                if profile_contexts:
                    full_prompt += "\n【相关人物画像参考】\n"
                    full_prompt += "\n".join(f"- {c}" for c in profile_contexts) + "\n"
            except Exception:
                pass

            full_prompt += (
                "\n请按以下格式输出（每项一行）：\n"
                f"【事件】<一句话概括>\n"
                f"【位置】{pos_type} — <含义>\n"
                f"【行动】<动词开头的待办>\n"
                + (f"【截止】{deadline}\n" if deadline else "")
                + (f"【发起】{requester}\n" if requester else "")
            )

            try:
                raw = self._llm(full_prompt, system_prompt=sys_prompt,
                                max_tokens=400, temperature=0.3)
                answer = str(raw).strip() if raw and not (
                    isinstance(raw, dict) and "error" in raw
                ) else ""
            except Exception:
                answer = ""

            if not answer:
                answer = f"【事件】{event_title}\n【位置】{pos_type}\n【行动】{act_summary}"

            ctx.decision = {
                "llm_reply": answer,
                "pos_type": pos_type,
                "requester": requester,
                "event_title": event_title,
            }
            ctx.status = Status.REASONING_DONE
        except Exception as e:
            ctx.status = Status.ERROR
            ctx.error = f"reasoning.reason: {e}"

    def _profile_reasoning(self, ctx):
        target = ctx.event.get("target_name", "")
        if not target:
            ctx.status = Status.REASONING_DONE
            return

        from skills.profile.user_retriever import get_profile_for_reasoning
        profile = get_profile_for_reasoning(target)
        if "error" in profile:
            ctx.decision = {"type": "profile_analysis", "target": target, "error": "no_data"}
            ctx.status = Status.REASONING_DONE
            return

        prompt = (
            f"分析 {target} 的工作画像数据，输出结构化多维评价。\n"
            "只基于以下数据，不编造、不猜测。\n\n"
            f"数据:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            "输出 JSON（只输出 JSON，不要额外文字）：\n"
            "{\n"
            '  "summary": "一句话综合判断，包含岗位和核心特征",\n'
            '  "dimensions": {\n'
            '    "efficiency": {"score": 1-5, "evidence": "引用数据说明", "risk": "效率风险说明或空字符串"},\n'
            '    "reliability": {"score": 1-5, "evidence": "引用数据说明", "risk": "可靠性风险说明或空字符串"},\n'
            '    "collaboration": {"score": 1-5, "evidence": "引用数据说明", "risk": "协作风险说明或空字符串"}\n'
            "  },\n"
            '  "specialties": ["擅长领域1", "擅长领域2"],\n'
            '  "growth": {"trend": "up|down|flat", "evidence": "趋势说明"},\n'
            '  "risks": ["风险描述或空数组"],\n'
            '  "recommendation": "一句话管理建议或空字符串"\n'
            "}"
        )

        try:
            raw = self._llm(prompt,
                            system_prompt=(
                                f"你是工班长助理Cipher，基于数据分析{target}的工作表现。"
                                "客观、严谨、只陈述数据反映的事实。自称Cipher（第三人称）。"
                            ),
                            max_tokens=600, temperature=0.3)
            raw = str(raw).strip() if raw else ""
            analysis = json.loads(raw)
        except Exception:
            analysis = {"summary": "", "dimensions": {}, "specialties": [], "risks": []}

        ctx.decision = {
            "type": "profile_analysis",
            "target": target,
            "analysis": analysis,
        }
        ctx.status = Status.REASONING_DONE
