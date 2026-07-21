"""
event_enricher.py — Event AI Enrichment Pipeline (Phase 1.7.7)
位置: skills/core/

职责：串联 section_parser → ai_content_extractor，为事件补充 AI 理解。
所有入口（wrapper、MCP server、opencode run）统一调用本模块。

返回的 event dict 增加字段:
  - ai_content:  AI 提取的结构化内容
  - ai_content_status: "success" | "failed" | "no_sections" | "empty"
"""

import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))

from ingestion.section_parser import parse_sections
from ingestion.ai_content_extractor import extract_content


def enrich_event(event: dict, text: str, tracer=None) -> dict:
    """为单个事件执行 AI 内容提取。

    流程:
      1. parse_sections(text) → sections[]
      2. extract_content(sections, event_meta) → ai_content[]
      3. 写回 event["ai_content"]，标记 status

    Args:
        event: event_detector.detect() 产生的事件 dict
        text: 原始通知/消息全文
        tracer: RequestTracer 实例（可选，用于 trace 记录）

    Returns:
        修改后的 event dict（原地修改 + 返回）
    """
    sections = parse_sections(
        text,
        parent_event=event.get("title", ""),
        target_role=event.get("executor", ""),
    )

    if not sections:
        event["ai_content_status"] = "no_sections"
        return event

    try:
        t0 = time.time()
        ai_content = extract_content(sections, event_meta={
            "title": event.get("title", ""),
            "target_role": event.get("executor", ""),
        })
        elapsed_ms = int((time.time() - t0) * 1000)

        if ai_content:
            event["ai_content"] = ai_content
            event["ai_content_status"] = "success"
        else:
            event["ai_content_status"] = "empty"

        if tracer:
            result_count = sum(len(s.get("actions", [])) for s in ai_content)
            tracer.set_ai_extraction(elapsed_ms, len(sections), result_count)

    except Exception as e:
        event["ai_content_status"] = "failed"
        _log_enrich_error(event.get("id", ""), text, e)

    return event


def _log_enrich_error(event_id: str, text: str, error: Exception):
    """写入错误到 logs/trace.log，不入 event schema。"""
    try:
        import json
        from datetime import datetime
        log_dir = TOOLS_DIR.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "stage": "content_extract",
            "event_id": event_id,
            "error": str(error)[:500],
            "input_preview": text[:200],
        }
        with open(log_dir / "trace.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
