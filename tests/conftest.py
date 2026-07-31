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
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


def pytest_runtest_setup():
    """Reset module-level caches before each test."""
    from memory.observation_store import reset_cache as obs_reset
    obs_reset()
