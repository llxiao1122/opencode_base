import os, sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skills"))

os.environ["OP_SKIP_BG"] = "1"

_llm_patch = patch("skills.core.llm_client.call", return_value="[]")
_llm_patch.start()


def pytest_unconfigure():
    _llm_patch.stop()