"""
request_context.py — Request-level context builder (Phase 1.7.8-A)

加载当前用户画像，构建统一 RequestContext，传入所有 handler/composer。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PROFILE = ROOT / "state" / "user_profile.md"


def build_request_context(profile_path=None):
    """加载用户画像，返回请求级上下文 dict。

    Returns:
        {
            "user": {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"},
            "event": None,    # Phase B 填充
            "org": None,      # Phase C 填充
        }
    """
    ctx = {
        "user": {"name": "未知", "role": "", "team": ""},
        "event": None,
        "org": None,
    }

    path = Path(profile_path) if profile_path else DEFAULT_PROFILE
    if not path.exists():
        return ctx

    try:
        profile = path.read_text(encoding="utf-8")
        in_current = False
        for line in profile.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "current_user:" in line:
                in_current = True
                continue
            if in_current:
                if ":" in line and not line.startswith("-"):
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key in ("name", "role", "team"):
                        ctx["user"][key] = val
                    if key in ("aliases", "responsibility", "authority",
                               "not_authority", "not_direct_responsible"):
                        in_current = False
    except Exception:
        pass

    return ctx


def inject_user_prompt(ctx, base_prompt=""):
    """从 ctx 生成注入 LLM 的用户身份前缀。"""
    user = ctx.get("user", {})
    if not user.get("name"):
        return base_prompt

    from context.hierarchy_resolver import inject_org_context as _org_ctx
    org = _org_ctx(ctx.get("event"), user)

    parts = [f"你正在与 {user['name']}（{user.get('role', '')}，{user.get('team', '')}）对话。你是他的工班助手。"]

    if org:
        parts.append(org)

    inst = ctx.get("instruction")
    if inst:
        from pipeline.instruction_resolver import inject_instruction_context as _inst_ctx
        ic = _inst_ctx(inst)
        if ic:
            parts.append(ic)

    prefix = "\n".join(parts)
    return f"{prefix}\n\n{base_prompt}" if base_prompt else prefix
