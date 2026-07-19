#!/usr/bin/env python3
"""
wrapper.py — Thin re-export entry (Phase 9 refactor).

All logic migrated to:
  routing/entry.py          — new core pipeline (handle_core)
  routing/legacy_pipeline.py — old A-I route pipeline (handle)
  routing/llm_helpers.py    — LLM synthesis helpers
  routing/cli.py            — CLI entry point

Kept for backward compatibility. Use routing/cli.py directly.
"""

from routing.legacy_pipeline import handle, HANDLERS, CAPABILITY_HANDLERS
from routing.entry import handle_core

__all__ = ["handle", "handle_core", "HANDLERS", "CAPABILITY_HANDLERS"]


if __name__ == "__main__":
    from routing.cli import main
    main()
