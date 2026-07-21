"""Layer 1 Intent — fact extraction + context resolution."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status


class DefaultIntentExtractor:
    def extract(self, ctx: RequestContext) -> None:
        try:
            if ctx.route == "profile":
                from skills.routing.entity_resolver import resolve_entities
                resolved = resolve_entities(ctx.message)
                if resolved["entities"]:
                    target = resolved["entities"][0]["name"]
                else:
                    target = (ctx.user or {}).get("name", "")
                ctx.event = {"target_name": target, "event_type": "profile_query"}
                ctx.status = Status.INTENT_DONE
                return

            if ctx.route != "event":
                ctx.status = Status.INTENT_DONE
                return

            from skills.core.event import extract as extract_event
            from skills.core.context import resolve as ctx_resolve
            from skills.routing.record_manager import record as check_record

            event = extract_event(ctx.message, current_user=ctx.user)
            ctx.event = event

            if event.get("event_type") != "feedback":
                note = check_record(ctx.message, ctx.user or {})
                if note:
                    if "已合并" in note or event.get("event_type") == "unknown":
                        ctx.record_note = note
                        ctx.status = Status.SKIP_REMAINING
                        return
                    ctx.record_note = note.replace("[Cipher:task]\n", "")

            subject_ctx = ctx_resolve(event, ctx.user or {})
            ctx.subject_context = subject_ctx

            ctx.status = Status.INTENT_DONE
        except Exception as e:
            ctx.status = Status.ERROR
            ctx.error = f"intent.extract: {e}"
