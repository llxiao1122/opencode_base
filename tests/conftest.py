import json, os, sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT))

os.environ["OP_SKIP_BG"] = "1"


MOCK_LLM_CONTENT = "[Cipher:mock] 测试应答"


def _mock_llm_http(*args, **kwargs):
    """Transport-level mock: intercept urllib.request.urlopen calls.

    唯一真实 urlopen 调用方为 skills/core/llm_client.py（LLM API 统一封装）。
    返回 OpenAI 响应格式（llm_client 按 choices[0].message.content 取值），
    内容读模块级 MOCK_LLM_CONTENT —— 测试可临时改写以模拟真实 LLM 输出：
      - 文本应答（默认）→ knowledge_retrieve 等文本消费路径
      - JSON 工具决策 → Agent 主路径（engine._parse_decisions）
    注意：默认文本不应包含 '{'，否则 _parse_decisions 会误提取。
    """
    mock = MagicMock()
    mock.status = 200
    mock.read.return_value = json.dumps({
        "choices": [{"message": {"content": MOCK_LLM_CONTENT}}]
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
