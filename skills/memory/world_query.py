"""
skills/memory/world_query.py — 统一查口（一个大脑的对外查询入口）。

query(text) 是系统唯一对外查口。内部按路由分发：
  - 任务/日程类 → task_query 规则路径（确定性：日期+状态）
  - 制度/流程问答 → knowledge_retrieve（优先世界观 FAISS，Knowledge 兜底）
  - 人员档案 → profile_query
  - 其他 → worldview 语义检索兜底

确定性知识（任务/日程）与语义知识（制度/联想）在入口处收敛，
对外表现为单一 query() 接口。
"""

import logging

logger = logging.getLogger(__name__)

_ROUTE_RULES = None


def _route_rules():
    """路由规则一次加载：时间信号 + 任务关键词。"""
    global _ROUTE_RULES
    if _ROUTE_RULES is not None:
        return _ROUTE_RULES
    import re
    _TIME = re.compile(r"今|明|昨|后|天|本周|这周|下周|周[一二三四五六日]|\d+月\d+日|\d+号")
    _TASK_KW = ["任务", "工作", "值班", "待办", "安排", "谁值班", "干什么", "台账", "库区责任", "材料棚"]
    _ROUTE_RULES = (_TIME, _TASK_KW)
    return _ROUTE_RULES


def _make_ctx(ctx=None):
    from skills.shared.schema import RequestContext
    from skills.shared.entity import resolve_user
    if ctx is not None:
        return ctx
    ctx = RequestContext(message="")
    ctx.user = resolve_user()
    return ctx


def query(text: str, ctx=None) -> str:
    """统一查口：按路由分发，返回格式化结果。"""
    text = (text or "").strip()
    if not text:
        return "[Cipher:error]\n空查询"

    ctx = _make_ctx(ctx)

    # ① 任务/日程类 → 规则路径（确定性：日期计算 + 状态过滤）
    if _is_task_query(text):
        from skills.agent.handlers.task_query import handle as task_handle
        try:
            return task_handle(text, ctx)
        except Exception as e:
            logger.warning("task_query failed: %s", e, exc_info=True)

    # ② 人员档案 → profile_query
    if _is_person_query(text):
        from skills.agent.handlers.profile_query import handle as profile_handle
        try:
            return profile_handle(text, ctx)
        except Exception as e:
            logger.warning("profile_query failed: %s", e, exc_info=True)

    # ③ 制度/流程问答 → knowledge_retrieve（世界观 FAISS → Knowledge 兜底）
    from skills.agent.handlers.knowledge_retrieve import handle as kh
    try:
        return kh(text, ctx)
    except Exception as e:
        logger.warning("knowledge_retrieve failed: %s", e, exc_info=True)

    return "[Cipher]\n未检索到相关结果。"


def _is_task_query(text: str) -> bool:
    time_re, task_kw = _route_rules()
    has_time = bool(time_re.search(text))
    has_task_kw = any(kw in text for kw in task_kw)
    return has_time or has_task_kw


def _is_person_query(text: str) -> bool:
    try:
        from skills.router.faiss_router import _load_person_names
        names = _load_person_names()
        return any(n in text for n in names)
    except Exception:
        return False
