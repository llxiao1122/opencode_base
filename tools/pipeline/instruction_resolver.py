"""
instruction_resolver.py — Instruction flow resolver (Phase 1.7.8-D)

Pure rule-based. No AI, no LLM.
Parses "who tells whom to do what" from event + current user context.

Output schema:
  issuer:          who sent the instruction
  issuer_role:     issuer's organizational role
  receiver_scope:  who the message was sent to
  receiver_type:   broadcast | direct | chain | unknown
  current_actor:   current user's role in this instruction
  execution_scope: what the current user needs to execute
  task_target:     final affected party
  relation:        natural-language summary for LLM injection

Priority: direct → chain → broadcast → default
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

BROADCAST_WORDS = [
    "各班组", "各工班", "各工班长", "全体人员", "所有工班",
    "各部门", "相关人员", "责任人", "负责人",
]

ASSIGN_WORDS = ["通知", "安排", "要求", "指定", "负责", "完成"]


def _get_role(name: str) -> str:
    try:
        import json
        idx = ROOT / "state" / "entity_index.json"
        data = json.loads(idx.read_text(encoding="utf-8"))
        for e in data.get("confirmed_entities", []):
            if e["name"] == name:
                return e.get("role", "")
    except Exception:
        pass
    return ""


def _is_broadcast(text: str) -> bool:
    return any(w in text for w in BROADCAST_WORDS)


def _is_user_initiating(text: str, user_name: str) -> bool:
    if not user_name:
        return False
    for assign in ASSIGN_WORDS:
        prefix = f"{user_name}{assign}"
        if text.startswith(prefix):
            return True
    return False


def _extract_assigned_person(text: str, user_name: str):
    """Find who the current user is assigning to: '李林骁通知苗笑天' → 苗笑天"""
    import re
    for assign in ASSIGN_WORDS:
        pattern = re.compile(rf"{user_name}{assign}(\S{{2,4}})(" + "|".join(ASSIGN_WORDS) + r"|$)")
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def resolve_instruction(event: dict, user: dict) -> dict:
    """Core resolver. Returns instruction dict ready for ctx injection.

    Args:
        event: from event_detector.detect(), has requester/executor/target/participants
        user:  current user dict {name, role, team}
    """
    text = event.get("title", "") or ""
    issuer = event.get("requester", "") or ""
    executor = event.get("executor", "") or ""
    participants = event.get("participants", []) or []
    user_name = user.get("name", "")
    user_role = user.get("role", "")
    user_team = user.get("team", "")

    issuer_role = _get_role(issuer) if issuer else ""

    current_actor = {"name": user_name, "role": user_role, "team": user_team}
    result = {
        "issuer": issuer,
        "issuer_role": issuer_role,
        "receiver_scope": "",
        "receiver_type": "unknown",
        "current_actor": current_actor,
        "execution_scope": {"type": "self", "name": user_name},
        "task_target": "",
        "relation": "",
    }

    # ── Priority 1: direct — current user is explicitly named by issuer ──
    if issuer and issuer != user_name and user_name in text:
        result["receiver_scope"] = user_name
        result["receiver_type"] = "direct"
        result["execution_scope"] = {"type": "self", "name": user_name}
        event_target = event.get("target", "") or ""
        result["task_target"] = event_target if event_target else "自身"
        result["relation"] = (
            f"{issuer}" + (f"（{issuer_role}）" if issuer_role else "") +
            f" 直接通知 {user_name} 完成"
        )
        return result

    # ── Priority 2: chain — current user is delegating to someone else ──
    if issuer == user_name:
        assigned = _extract_assigned_person(text, user_name)
        if assigned:
            result["receiver_scope"] = assigned
            result["receiver_type"] = "chain"
            result["execution_scope"] = {"type": "assigned", "name": assigned}
            result["task_target"] = assigned
            result["relation"] = f"{user_name} 指派 {assigned} 执行"
        else:
            result["receiver_scope"] = "自身"
            result["receiver_type"] = "direct"
            result["execution_scope"] = {"type": "self", "name": user_name}
            result["relation"] = f"{user_name} 自身执行"
        return result

    # ── Priority 3: broadcast — message targets a group, user is group member ──
    if _is_broadcast(text):
        result["receiver_scope"] = "、".join([p for p in participants if p in BROADCAST_WORDS]) or "各班组"
        result["receiver_type"] = "broadcast"
        is_leader = any(kw in user_role for kw in ["工班长", "负责人", "主任", "管理"])
        team_members = f"{user_team}员工" if user_team else "所属人员"
        if is_leader:
            result["execution_scope"] = {"type": "self_team", "name": team_members}
        else:
            result["execution_scope"] = {"type": "self", "name": user_name}
        event_target = event.get("target", "") or ""
        result["task_target"] = event_target if event_target else "所属人员"
        if is_leader and issuer:
            result["relation"] = (
                f"{issuer}" + (f"（{issuer_role}）" if issuer_role else "") +
                f" 通知 {result['receiver_scope']}，" +
                f"{user_name}（{user_role}）负责落实 {team_members}"
            )
        elif issuer:
            result["relation"] = (
                f"{issuer}" + (f"（{issuer_role}）" if issuer_role else "") +
                f" 通知 {result['receiver_scope']}，" +
                f"{user_name} 为受众之一"
            )
        else:
            result["relation"] = f"群体通知：{result['receiver_scope']}"
        return result

    # ── Priority 4: default — personal task ──
    result["receiver_type"] = "direct"
    result["receiver_scope"] = user_name
    result["execution_scope"] = {"type": "self", "name": user_name}
    result["relation"] = f"{user_name} 执行"
    return result


def inject_instruction_context(instruction: dict) -> str:
    """Generate LLM-ready instruction context string."""
    if not instruction or not instruction.get("relation"):
        return ""

    lines = ["【指令关系】"]
    if instruction.get("issuer"):
        role = instruction.get("issuer_role", "")
        lines.append(f"来源: {instruction['issuer']}" + (f"（{role}）" if role else ""))

    scope = instruction.get("receiver_scope", "")
    rtype = instruction.get("receiver_type", "")
    if scope:
        type_map = {"broadcast": "群体通知", "chain": "链式指派", "direct": "直接通知"}
        type_label = type_map.get(rtype, "")
        lines.append(f"通知范围: {scope}" + (f"（{type_label}）" if type_label else ""))

    actor = instruction.get("current_actor", {})
    if actor.get("name"):
        lines.append(f"当前角色: {actor['name']}（{actor.get('role', '')}，{actor.get('team', '')}）")

    escope = instruction.get("execution_scope", {})
    if escope.get("name"):
        lines.append(f"执行范围: {escope['name']}")

    lines.append(f"含义: {instruction['relation']}")

    return "\n".join(lines)
