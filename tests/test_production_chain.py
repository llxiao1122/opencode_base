"""生产链路测试：push_queue / correction_store / prepare_daily / deliver。

全部使用临时路径与 mock，不碰真实数据与网络。
"""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))

from skills.shared import push_queue
from skills.memory import correction_store


@pytest.fixture
def tmp_queue(tmp_path, monkeypatch):
    qpath = tmp_path / "push_queue.json"
    monkeypatch.setattr(push_queue, "QUEUE_PATH", qpath)
    return qpath


@pytest.fixture
def tmp_corrections(tmp_path, monkeypatch):
    cpath = tmp_path / "纠错.md"
    monkeypatch.setattr(correction_store, "CORRECTIONS_PATH", cpath)
    return cpath


# ── push_queue ──────────────────────────────────────────────────

def test_push_queue_roundtrip(tmp_queue):
    assert push_queue.read() == []
    push_queue.append({"id": "a", "body": "x"})
    push_queue.append({"id": "b", "body": "y"})
    queue = push_queue.read()
    assert [q["id"] for q in queue] == ["a", "b"]
    push_queue.write([{"id": "c"}])
    assert [q["id"] for q in push_queue.read()] == ["c"]


def test_push_queue_concurrent_append_safe(tmp_queue):
    errors = []

    def worker(n):
        try:
            for _ in range(n):
                push_queue.append({"id": "t", "body": "b"})
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(20,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    queue = push_queue.read()
    assert len(queue) == 80
    assert json.dumps(queue, ensure_ascii=False)  # JSON 完好可序列化


# ── correction_store ────────────────────────────────────────────

def test_correction_store_roundtrip(tmp_corrections):
    assert correction_store.load_recent() == []
    assert correction_store.append("测试纠错A") is True
    assert correction_store.append("测试纠错B") is True
    recent = correction_store.load_recent(limit=2)
    assert [r["text"] for r in recent] == ["测试纠错A", "测试纠错B"]
    assert correction_store.append("x" * 300) is True
    assert correction_store.load_recent(limit=1)[0]["text"] == "x" * 120  # 超长截断


# ── prepare_daily 幂等 ──────────────────────────────────────────

def test_prepare_daily_idempotent(tmp_queue, monkeypatch):
    import scripts.prepare_daily as pd
    from datetime import date
    monkeypatch.setattr(pd.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 31)  # 工作日（周五），避免周末 SKIP

    monkeypatch.setattr(pd, "date", FakeDate)
    pd.main()
    assert len(push_queue.read()) == 1
    pd.main()
    assert len(push_queue.read()) == 1, "重复运行不应重复入队"
    assert push_queue.read()[0]["id"] == "daily_2026-07-31" or push_queue.read()[0]["id"].startswith("daily_")


def test_prepare_daily_weekend_skips(tmp_queue, monkeypatch):
    """周末不预执行：不查询、不入队（避免推送'暂无任务'）"""
    import scripts.prepare_daily as pd
    from datetime import date
    monkeypatch.setattr(pd.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 1)  # 周六

    monkeypatch.setattr(pd, "date", FakeDate)
    pd.main()
    assert push_queue.read() == [], "周末不应产生任何待推送项"


# ── deliver 推送标记与重试 ──────────────────────────────────────

def test_deliver_push_mark_retry(tmp_queue, monkeypatch):
    import scripts.deliver as dl
    from datetime import datetime, timedelta

    now = datetime.now()
    due = {"id": "due", "title": "T1", "body": "b1",
           "push_at": (now - timedelta(minutes=1)).isoformat(), "pushed": False}
    future = {"id": "future", "title": "T2", "body": "b2",
              "push_at": (now + timedelta(hours=1)).isoformat(), "pushed": False}
    push_queue.write([due, future])

    calls = []
    monkeypatch.setattr("skills.plugins.dingbot.send_msg.send_markdown",
                        lambda title, body: calls.append((title, body)) or {"errcode": 0})
    monkeypatch.setattr("skills.memory.recorder.record", lambda *a, **k: None)

    dl.main()
    queue = push_queue.read()
    by_id = {q["id"]: q for q in queue}
    assert by_id["due"]["pushed"] is True, "到期项应推送并标记"
    assert by_id["future"]["pushed"] is False, "未到期项不应推送"

    # 失败重试：推送失败不标记，下次仍可重试
    due2 = {"id": "due2", "title": "T3", "body": "b3",
            "push_at": (now - timedelta(minutes=1)).isoformat(), "pushed": False}
    push_queue.write([due2])
    monkeypatch.setattr("skills.plugins.dingbot.send_msg.send_markdown",
                        lambda title, body: {"errcode": 40001, "errmsg": "invalid token"})
    dl.main()
    assert push_queue.read()[0]["pushed"] is False, "失败不应标记，保留重试"


# ── Human-in-the-loop 确认门 ────────────────────────────────────

@pytest.fixture
def tmp_confirm(tmp_path, monkeypatch):
    from skills.shared import confirm_queue
    cpath = tmp_path / "confirm_queue.json"
    monkeypatch.setattr(confirm_queue, "QUEUE_PATH", cpath)
    return confirm_queue


def test_confirm_propose_pending_accept(tmp_confirm, monkeypatch):
    """confirm 类工具：生成建议 → 待确认 → 确认后执行。"""
    item = tmp_confirm.propose("task_create", {"summary": "测试确认任务"}, summary="建议创建任务：测试确认任务")
    assert item["id"]
    assert item["tool"] == "task_create"
    assert len(tmp_confirm.pending()) == 1

    executed = []
    monkeypatch.setattr("skills.agent.registry.execute",
                        lambda tool, params, ctx=None: executed.append((tool, params)) or "✅ 执行")
    result = tmp_confirm.execute(item["id"])
    assert result == "✅ 执行"
    assert executed == [("task_create", {"summary": "测试确认任务"})]
    assert tmp_confirm.pending() == [], "执行后不应再有待确认项"


def test_confirm_shortid_prefix_match(tmp_confirm):
    """支持前 6 位短 ID 匹配（钉钉回复场景）。"""
    item = tmp_confirm.propose("notification_push", {"title": "T"}, summary="建议推送")
    assert item["id"][:6] != item["id"]
    got = tmp_confirm.accept(item["id"][:6])
    assert got is not None
    assert got["id"] == item["id"]


def test_confirm_reject_removes(tmp_confirm):
    """拒绝建议：从队列移除。"""
    item = tmp_confirm.propose("correction_feedback", {"content": "C"}, summary="建议采纳纠正")
    assert len(tmp_confirm.pending()) == 1
    assert tmp_confirm.reject(item["id"][:6]) is True
    assert tmp_confirm.pending() == []
    assert tmp_confirm.reject(item["id"]) is False, "已拒绝的建议不应再次存在"
