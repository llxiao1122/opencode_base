"""Layer 2 Reasoning — decision making."""

import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status, CT


class DefaultReasoningEngine:
    def __init__(self, llm):
        self._llm = llm

    def reason(self, ctx: RequestContext) -> None:
        try:
            if ctx.route == "profile":
                return self._profile_reasoning(ctx)

            # 高置信度 task/knowledge 路由跳过 L3 省 token
            if ctx.route in ("task", "knowledge") and ctx.confidence >= CT.HIGH:
                ctx.decision = {"llm_reply": "", "confidence": ctx.confidence}
                ctx.status = Status.REASONING_DONE
                return

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

            # Gather extra context for complex thinking
            extra_context = ""
            all_names = {a.get("name", "") for a in actors if a.get("name")}
            all_names.add(user_name)

            # 1. Query active tasks for all involved actors
            try:
                from task.store import list_by_owner
                for name in all_names:
                    tasks = list_by_owner(name, status="active")
                    if tasks:
                        extra_context += f"\n【{name}当前进行中的任务】\n"
                        for t in tasks[:5]:
                            desc = t.get("action") or t.get("title", "")
                            dl = t.get("deadline", "")
                            extra_context += f"  - {desc}" + (f"（截止: {dl}）" if dl else "") + "\n"
            except Exception:
                pass

            # 2. Query past events matching requester or action keywords
            try:
                from memory.event_recorder import list_events as list_past_events
                recent = list_past_events(event_type="instruction", limit=30)
                action_words = set()
                if act_summary:
                    action_words = set(act_summary[:20].split())
                similar = []
                for evt in recent:
                    evt_actors = evt.get("actors", [])
                    evt_names = {a["name"] for a in evt_actors if isinstance(a, dict)}
                    if evt_names & all_names:
                        similar.append(evt)
                        continue
                    evt_summary = evt.get("action_summary", "")
                    if action_words and any(w in evt_summary for w in action_words if len(w) > 1):
                        similar.append(evt)
                if similar:
                    extra_context += "\n【类似历史事件参考】\n"
                    for evt in similar[:3]:
                        summary = evt.get("action_summary", "")
                        dt = evt.get("import_time", "")[:10]
                        dl = evt.get("deadline", "")
                        ref = f"  - {summary}" + (f" [{dt}]" if dt else "")
                        if dl:
                            ref += f"（原截止: {dl}）"
                        extra_context += ref + "\n"
            except Exception:
                pass

            # 3. FAISS search for relevant patterns and past situations
            try:
                from memory.memory_core import MemoryCore
                mc = MemoryCore()
                results = mc.search(query=event_title[:60], top_k=10)
                hits = results.get("hits", [])
                if hits:
                    extra_context += "\n【相关经验参考】\n"
                    for h in hits[:5]:
                        text = h.get("c", "")[:150]
                        extra_context += f"  - {text}\n"
            except Exception:
                pass
            # 4. Episodic-only search targeting stored patterns
            try:
                from memory.memory_core import MemoryCore as _MC
                _mc2 = _MC()
                _ep = _mc2.search(query=event_title[:40], types=["episodic"], top_k=5)
                _ep_hits = _ep.get("hits", [])
                if _ep_hits:
                    extra_context += "\n【历史模式参考】\n"
                    for h in _ep_hits[:3]:
                        text = h.get("c", "")[:150]
                        extra_context += f"  - {text}\n"
            except Exception:
                pass

            caution = ""
            if ctx.confidence < CT.EXECUTE and ctx.confidence > 0:
                caution = (
                    f"\n[System Notice] 当前意图识别置信度为 {ctx.confidence:.2f}（较低）。"
                    "请在推理时保持谨慎，输出结论时使用'推测'、'可能'等语气，不要给出绝对断言。"
                )

            sys_prompt = (
                f"你是 Cipher，{user_name}的企业认知系统助手。"
                "基于事件和上下文信息，分析情况并给出客观建议。"
                "直接陈述事实、位置、建议行动、截止时间。"
                "不替用户决策，但提供足够信息让用户判断。"
                f"{caution}"
            )

            full_prompt = (
                f"当前用户: {user_name}（{user_role}，{user_team}）\n"
                f"事件摘要: {event_title}\n"
                f"责任类型: {pos_type}（{reason}）\n"
                f"建议行动: {act_summary}\n"
                + (f"截止时间: {deadline}\n" if deadline else "")
                + (f"{contact_info}\n" if contact_info else "")
                + (dl_warning if dl_warning else "")
                + (extra_context if extra_context else "")
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
