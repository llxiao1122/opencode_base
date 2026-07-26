"""Phase 2 — Decision log + Learner: record, detection, seed update, safety."""

import json, os, copy, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status, CT
from skills.correction.learner import (
    _sem_score, _detect_requery, _detect_confirm_negation,
    _dedupe_seeds, _SEEDS_PATH as LEARNER_SEEDS_PATH,
    run_learner,
)


# ── Helpers ────────────────────────────────────────────────────────────

_ORIGINAL_SEEDS = None


def backup_seeds():
    global _ORIGINAL_SEEDS
    if LEARNER_SEEDS_PATH.exists():
        _ORIGINAL_SEEDS = LEARNER_SEEDS_PATH.read_text(encoding="utf-8")


def restore_seeds():
    global _ORIGINAL_SEEDS
    if _ORIGINAL_SEEDS is not None:
        LEARNER_SEEDS_PATH.write_text(_ORIGINAL_SEEDS, encoding="utf-8")
    _ORIGINAL_SEEDS = None


# ── Group A: Logger ────────────────────────────────────────────────────

def test_logger_writes_record(tmp_path, monkeypatch):
    import skills.correction.logger as logger_mod
    log_file = tmp_path / "decision_log.jsonl"
    monkeypatch.setattr(logger_mod, "_LOG_PATH", log_file)
    monkeypatch.setattr(logger_mod, "_session", "s1")
    monkeypatch.setattr(logger_mod, "_seq", 0)

    ctx = RequestContext(message="今天有什么任务", route="task", confidence=0.85)
    ctx.status = Status.DONE
    logger_mod.append(ctx, "任务列表已生成（推测，供参考）")

    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["msg"] == "今天有什么任务"
    assert rec.get("tool_id") == "task"
    assert rec["conf"] == 0.85
    assert rec["session"] == "s1"
    assert rec["seq"] == 1
    assert rec["reply_len"] > 0
    assert rec["has_hedge"] is True
    assert rec["has_confirm"] is False


def test_logger_skips_empty_message(tmp_path, monkeypatch):
    import skills.correction.logger as logger_mod
    f = tmp_path / "decision_log.jsonl"
    monkeypatch.setattr(logger_mod, "_LOG_PATH", f)

    ctx = RequestContext(message="  ", route="event", confidence=0.0)
    logger_mod.append(ctx, "reply")
    assert not f.exists()


def test_logger_has_confirm_true(tmp_path, monkeypatch):
    import skills.correction.logger as logger_mod
    f = tmp_path / "decision_log.jsonl"
    monkeypatch.setattr(logger_mod, "_LOG_PATH", f)

    ctx = RequestContext(message="test", route="event", confidence=0.5)
    logger_mod.append(ctx, "需要确认这个事件吗?")
    rec = json.loads(f.read_text(encoding="utf-8"))
    assert rec["has_confirm"] is True


def test_logger_msg_truncated(tmp_path, monkeypatch):
    import skills.correction.logger as logger_mod
    f = tmp_path / "decision_log.jsonl"
    monkeypatch.setattr(logger_mod, "_LOG_PATH", f)

    long_msg = "x" * 300
    ctx = RequestContext(message=long_msg, route="event", confidence=0.5)
    logger_mod.append(ctx, "reply")
    rec = json.loads(f.read_text(encoding="utf-8"))
    assert len(rec["msg"]) == 200


def test_logger_idempotent_append(tmp_path, monkeypatch):
    import skills.correction.logger as logger_mod
    f = tmp_path / "decision_log.jsonl"
    monkeypatch.setattr(logger_mod, "_LOG_PATH", f)
    monkeypatch.setattr(logger_mod, "_seq", 0)

    for i in range(3):
        ctx = RequestContext(message=f"msg{i}", route="event", confidence=0.5)
        logger_mod.append(ctx, f"reply{i}")
    lines = f.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    seqs = [json.loads(l)["seq"] for l in lines]
    assert seqs == [1, 2, 3]


# ── Group B: Learner pattern detection ─────────────────────────────────

REQUERY_ENTRIES = [
    {"session": "sess1", "seq": 1, "msg": "苗笑天这个人怎么样", "route": "profile", "conf": 0.65},
    {"session": "sess1", "seq": 2, "msg": "查一下苗笑天的任务", "route": "task", "conf": 0.88},
]

SAME_ROUTE_ENTRIES = [
    {"session": "s", "seq": 1, "msg": "今天有什么任务", "route": "task", "conf": 0.9},
    {"session": "s", "seq": 2, "msg": "查一下今天的任务", "route": "task", "conf": 0.9},
]

LOW_CONF_ENTRIES = [
    {"session": "s", "seq": 1, "msg": "a", "route": "profile", "conf": 0.3},
    {"session": "s", "seq": 2, "msg": "b", "route": "task", "conf": 0.8},
]

CONFIRM_NEGATION_DIFF = [
    {"session": "s", "seq": 1, "msg": "灭火器更换", "route": "knowledge", "conf": 0.55, "has_confirm": True},
    {"session": "s", "seq": 2, "msg": "不是，查今天的任务", "route": "task", "conf": 0.9},
]

NO_CONFIRM_ENTRIES = [
    {"session": "s", "seq": 1, "msg": "灭火器更换", "route": "knowledge", "conf": 0.55, "has_confirm": False},
    {"session": "s", "seq": 2, "msg": "不是，查任务", "route": "task", "conf": 0.9},
]

NEGATION_ENTRIES = [
    {"session": "s", "seq": 1, "msg": "通知", "route": "event", "conf": 0.55, "has_confirm": True},
    {"session": "s", "seq": 2, "msg": "查一下今天", "route": "task", "conf": 0.9},
]


def test_requery_detected():
    result = _detect_requery(REQUERY_ENTRIES)
    assert len(result) == 1
    msg, route = result[0]
    assert "苗笑天" in msg
    assert route == "task"


def test_requery_same_route_skipped():
    assert _detect_requery(SAME_ROUTE_ENTRIES) == []


def test_requery_low_conf_skipped():
    assert _detect_requery(LOW_CONF_ENTRIES) == []


def test_confirm_negation_detected():
    result = _detect_confirm_negation(CONFIRM_NEGATION_DIFF)
    assert len(result) == 1
    assert result[0][0] == "灭火器更换"
    assert result[0][1] == "task"


def test_confirm_negation_no_confirm_flag_skipped():
    assert _detect_confirm_negation(NO_CONFIRM_ENTRIES) == []


def test_confirm_negation_gaicha_start_matches():
    result = _detect_confirm_negation(NEGATION_ENTRIES)
    assert len(result) == 1
    assert result[0][1] == "task"


def test_sem_score_similar():
    score = _sem_score("苗笑天这个人怎么样", "查一下苗笑天的任务")
    assert score >= 0.3


def test_sem_score_dissimilar():
    score = _sem_score("今天消防检查", "通知各班组明天开会")
    assert score < 0.3


# ── Group C: Learner seed update ───────────────────────────────────────

CROSS_SESSION_ENTRIES = [
    {"session": "sa", "seq": 1, "msg": "张三", "route": "profile_query", "conf": 0.7},
    {"session": "sa", "seq": 2, "msg": "查一下张三的任务", "route": "task_query", "conf": 0.85},
    {"session": "sb", "seq": 1, "msg": "张三", "route": "profile_query", "conf": 0.65},
    {"session": "sb", "seq": 2, "msg": "查一下张三的任务", "route": "task_query", "conf": 0.9},
]


def test_run_learner_updates_seeds(monkeypatch):
    import skills.correction.learner as mod
    log_file = ROOT / "state" / "decision_log.jsonl"
    stamp_file = ROOT / "state" / ".seeds_stamp"
    if log_file.exists():
        log_file.unlink()

    monkeypatch.setattr(mod, "_LOG_PATH", log_file)
    monkeypatch.setattr(mod, "_STAMP_PATH", stamp_file)

    for e in CROSS_SESSION_ENTRIES:
        e_clean = {k: v for k, v in e.items() if k in ("session", "seq", "msg", "route", "conf")}
        with open(log_file, "a") as f:
            f.write(json.dumps(e_clean, ensure_ascii=False) + "\n")

    backup_seeds()

    try:
        result = run_learner(min_count=2)

        assert result["corrections_found"] == 2
        assert result["requery"] == 2
        assert result["added"] >= 1

        updated = json.loads(LEARNER_SEEDS_PATH.read_text(encoding="utf-8"))
        assert "张三" in updated["task_query"]["seeds"]

        assert stamp_file.exists()
    finally:
        restore_seeds()
        if stamp_file.exists():
            stamp_file.unlink()
        if log_file.exists():
            log_file.unlink()


def test_run_learner_dedup(monkeypatch):
    import skills.correction.learner as mod
    log_file = ROOT / "state" / "decision_log.jsonl"
    stamp_file = ROOT / "state" / ".seeds_stamp"
    if log_file.exists():
        log_file.unlink()

    monkeypatch.setattr(mod, "_LOG_PATH", log_file)
    monkeypatch.setattr(mod, "_STAMP_PATH", stamp_file)

    for e in CROSS_SESSION_ENTRIES:
        e_clean = {k: v for k, v in e.items() if k in ("session", "seq", "msg", "route", "conf")}
        with open(log_file, "a") as f:
            f.write(json.dumps(e_clean, ensure_ascii=False) + "\n")

    backup_seeds()
    try:
        run_learner(min_count=2)
        updated = json.loads(LEARNER_SEEDS_PATH.read_text(encoding="utf-8"))
        count = updated["task_query"]["seeds"].count("张三")
        assert count <= 1, f"Dup found: count={count}"
    finally:
        restore_seeds()
        if stamp_file.exists():
            stamp_file.unlink()
        if log_file.exists():
            log_file.unlink()


def test_dedup_seeds():
    assert _dedupe_seeds(["a", "a", "b", "c", "b"]) == ["a", "b", "c"]
    assert _dedupe_seeds(["a"]) == ["a"]
    assert _dedupe_seeds([]) == []


# ── Group D: Safety ────────────────────────────────────────────────────

def test_load_log_empty(monkeypatch):
    import skills.correction.learner as mod
    import tempfile
    f = Path(tempfile.mktemp(suffix=".jsonl"))
    f.write_text("")
    monkeypatch.setattr(mod, "_LOG_PATH", f)
    assert mod._load_log() == []
    f.unlink()


def test_load_log_bad_line_skipped(monkeypatch):
    import skills.correction.learner as mod
    import tempfile
    f = Path(tempfile.mktemp(suffix=".jsonl"))
    f.write_text('{"valid":1}\nnot-json-line\n{"valid":2}\n', encoding="utf-8")
    monkeypatch.setattr(mod, "_LOG_PATH", f)
    entries = mod._load_log()
    assert len(entries) == 2
    f.unlink()


def test_run_learner_no_log(monkeypatch):
    import skills.correction.learner as mod
    import tempfile
    f = Path(tempfile.mktemp(suffix=".jsonl"))
    f.write_text("")
    monkeypatch.setattr(mod, "_LOG_PATH", f)
    result = run_learner()
    assert result["reason"] == "no_log"
    f.unlink()


def test_run_learner_no_pattern(monkeypatch):
    import skills.correction.learner as mod
    import tempfile
    f = Path(tempfile.mktemp(suffix=".jsonl"))
    f.write_text(json.dumps({"session": "s", "seq": 1, "msg": "hello", "route": "event", "conf": 0.9}))
    monkeypatch.setattr(mod, "_LOG_PATH", f)
    result = run_learner()
    assert result["reason"] == "no_pattern"
    f.unlink()
