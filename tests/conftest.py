import json, os, sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT))

os.environ["OP_SKIP_BG"] = "1"


def _mock_llm_http(*args, **kwargs):
    """Transport-level mock: intercept ALL urllib.request.urlopen calls.

    Covers:
      - llm_client.call()        → urllib.request.urlopen
      - memory_core._async_llm_score() → urllib.request.urlopen
      - observation_store._llm_classify() → urllib.request.urlopen
    """
    mock = MagicMock()
    mock.status = 200
    mock.read.return_value = json.dumps({
        "choices": [{"message": {"content": "[]"}}]
    }).encode()
    mock.__enter__.return_value = mock
    return mock


_urlopen_patch = patch("urllib.request.urlopen", _mock_llm_http)
_urlopen_patch.start()


def pytest_unconfigure():
    _urlopen_patch.stop()


def pytest_runtest_setup():
    """Reset module-level caches before each test."""
    from memory.observation_store import reset_cache as obs_reset
    obs_reset()
