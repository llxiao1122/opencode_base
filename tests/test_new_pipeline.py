"""test_new_pipeline.py — 6 层 Pipeline 核心测试."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status


def test_build_default():
    """Pipeline.build_default() 不崩溃"""
    from skills.core.pipeline import Pipeline
    pipe = Pipeline.build_default()
    assert pipe._ingress is not None
    assert pipe._intent is not None
    assert pipe._reasoning is not None
    assert pipe._execution is not None
    assert pipe._response is not None
    assert pipe._reflection is not None


def test_non_event_route():
    """非 event 路由（纯知识查询）正常返回"""
    from skills.core.pipeline import Pipeline
    ctx = RequestContext(message="防汛应急预案是什么", user={"name": "李林骁", "role": "工班长", "team": "铁炉西工班"})
    pipe = Pipeline.build_default()
    result = pipe.run(ctx)
    assert isinstance(result, str)
    assert len(result) > 0
    assert ctx.status == Status.DONE


def test_error_handling():
    """异常层不中断 pipeline"""
    from skills.core.pipeline import Pipeline
    from skills.shared.interfaces import Ingress, IntentExtractor, ReasoningEngine, Executor, ResponseBuilder

    class BrokenIngress:
        def build(self, ctx):
            ctx.status = Status.ERROR
            ctx.error = "test error"

    pipe = Pipeline(
        ingress=BrokenIngress(),
        intent=None,
        reasoning=None,
        execution=None,
        response=None,
    )
    ctx = RequestContext(message="test", user={"name": "李林骁"})
    result = pipe.run(ctx)
    assert "test error" in result
    assert ctx.status == Status.ERROR


def test_skip_remaining():
    """SKIP_REMAINING 短路正确"""
    from skills.core.pipeline import Pipeline
    from skills.shared.interfaces import Ingress, IntentExtractor, ReasoningEngine, Executor, ResponseBuilder

    class SkipIngress:
        def build(self, ctx):
            ctx.route = "task"

    class SkipIntent:
        def extract(self, ctx):
            ctx.record_note = "✅ 已记录"
            ctx.status = Status.SKIP_REMAINING

    pipe = Pipeline(ingress=SkipIngress(), intent=SkipIntent(), reasoning=None, execution=None, response=None)
    ctx = RequestContext(message="记事测试", user={"name": "李林骁"})
    result = pipe.run(ctx)
    assert "已记录" in result
    assert ctx.status == Status.DONE


def test_reflection_not_blocking():
    """Reflection 不阻塞回复"""
    from skills.core.pipeline import Pipeline
    from skills.shared.interfaces import Reflector

    reflected = []

    class SilentReflector:
        def reflect(self, ctx):
            reflected.append(True)

    pipe = Pipeline.build_default()
    pipe._reflection = SilentReflector()
    ctx = RequestContext(message="你好", user={"name": "李林骁", "role": "工班长", "team": "铁炉西工班"})
    result = pipe.run(ctx)
    assert isinstance(result, str)
    # Reflection might not always fire (depends on observation count),
    # but it never prevents the reply


def test_status_enum():
    """Status 枚举包含 6 层对应值"""
    assert Status.INGRESS_DONE.value == "ingress_done"
    assert Status.INTENT_DONE.value == "intent_done"
    assert Status.REASONING_DONE.value == "reasoning_done"
    assert Status.EXECUTION_DONE.value == "execution_done"
    assert Status.DONE.value == "done"
    assert Status.ERROR.value == "error"
    assert Status.SKIP_REMAINING.value == "skip_remaining"
