import json, os, shutil, sys, tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent

# ── 数据隔离：测试写入/读取全部落在临时副本，真实 data/ 零污染 ──────
# 必须在任何 skills 模块 import 之前设置（模块级 ROOT 常量在 import 时固定）。
# path.root() 识别 CIPHER_ROOT → 各模块 data 路径派生到副本。
# 基线复制：data（26M）+ Knowledge（2.5M），包含世界观实体/FAISS/任务/制度。
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="cipher_test_root_"))
for _sub in ("data", "Knowledge"):
    _src = ROOT / _sub
    if _src.exists():
        shutil.copytree(_src, _TEST_ROOT / _sub, dirs_exist_ok=True)
os.environ["CIPHER_ROOT"] = str(_TEST_ROOT)

sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT))

os.environ["OP_SKIP_BG"] = "1"

# CI/无密钥环境兜底：llm_client.call 在发请求前校验 key（llm_client.py:88），
# 缺 key 会直接短路返回"未配置"，传输层 mock 无法拦截。setdefault 保证
# 已配置 key 的环境（本地/VPS crontab）不受影响，仅填充缺失场景。
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")


MOCK_LLM_CONTENT = "[Cipher:mock] 测试应答"

# 序列模式：每个元素为 (content, tool_calls) 元组，按调用顺序弹出
# tool_calls 非 None 时 content 设为 None（OpenAI 原生 function calling 语义）
# 序列耗尽后回退到 MOCK_LLM_CONTENT
MOCK_LLM_SEQUENCE = None


def _build_llm_response(content=None, tool_calls=None):
    msg = {}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        msg["content"] = None
    else:
        msg["content"] = content if content is not None else MOCK_LLM_CONTENT
    return msg


def _mock_llm_http(*args, **kwargs):
    """Transport-level mock: intercept urllib.request.urlopen calls.

    序列模式 (MOCK_LLM_SEQUENCE)：按顺序返回多轮 LLM 响应，支持 tool_calls。
    默认模式：返回 MOCK_LLM_CONTENT 文本，保持现有测试兼容。
    """
    if MOCK_LLM_SEQUENCE is not None and MOCK_LLM_SEQUENCE:
        content, tool_calls = MOCK_LLM_SEQUENCE.pop(0)
        msg = _build_llm_response(content, tool_calls)
    else:
        msg = {"content": MOCK_LLM_CONTENT}

    mock = MagicMock()
    mock.status = 200
    mock.read.return_value = json.dumps({
        "choices": [{"message": msg}]
    }).encode()
    mock.__enter__.return_value = mock
    return mock


_urlopen_patch = patch("urllib.request.urlopen", _mock_llm_http)
_urlopen_patch.start()


def pytest_unconfigure():
    _urlopen_patch.stop()
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


def pytest_runtest_setup():
    """Reset module-level caches before each test."""
    from memory.observation_store import reset_cache as obs_reset
    obs_reset()
