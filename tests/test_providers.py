"""多 provider 支持测试 — OpenRouter/Gemini 参数映射 + reasoning 双读 + fallback 链。"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from skills.core import llm_client
from skills.core.llm_client import _build_body, _build_headers, _fallback_chain


def _fake_urlopen(data_dict, status=200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(data_dict).encode()
    mock.__enter__.return_value = mock
    return mock


class TestBodyParams:
    def test_deepseek_keeps_thinking_field(self):
        body = _build_body("deepseek", [], 0.0, 800, False,
                           thinking={"type": "enabled"}, reasoning_effort="high", user_id="u1")
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "high"
        assert body["user_id"] == "u1"
        assert "reasoning" not in body

    def test_openrouter_uses_reasoning_param(self):
        body = _build_body("openrouter", [], 0.0, 800, False,
                           thinking={"type": "enabled"}, reasoning_effort="high")
        assert body["reasoning"] == {"enabled": True, "effort": "high"}
        assert "thinking" not in body

    def test_openrouter_defaults_effort_high(self):
        body = _build_body("openrouter", [], 0.0, 800, False, thinking=None)
        assert "reasoning" not in body

    def test_gemini_uses_reasoning_effort_directly(self):
        body = _build_body("gemini", [], 0.0, 800, False,
                           thinking={"type": "enabled"}, reasoning_effort="high")
        assert body["reasoning_effort"] == "high"
        assert "thinking" not in body

    def test_gemini_user_field(self):
        body = _build_body("gemini", [], 0.0, 800, False, user_id="u2")
        assert body["user"] == "u2"
        assert "user_id" not in body


class TestHeaders:
    def test_gemini_x_goog_api_key(self):
        h = _build_headers("gemini", "gk123")
        assert h["x-goog-api-key"] == "gk123"
        assert "Authorization" not in h

    def test_deepseek_bearer(self):
        h = _build_headers("deepseek", "dk123")
        assert h["Authorization"] == "Bearer dk123"

    def test_openrouter_bearer(self):
        h = _build_headers("openrouter", "ok123")
        assert h["Authorization"] == "Bearer ok123"


class TestReasoningDoubleRead:
    def test_call_returns_reasoning_field_from_openrouter(self, monkeypatch):
        """OpenRouter 返回 reasoning 字段（非 reasoning_content），tool_calls 分支应双读兼容。"""
        tool_calls = [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "task_query", "arguments": "{}"},
        }]
        with patch("urllib.request.urlopen", return_value=_fake_urlopen({
            "choices": [{"message": {"tool_calls": tool_calls, "content": None,
                                      "reasoning": "思考中…"}}]
        })):
            monkeypatch.setenv("LLM_PROVIDER", "deepseek")
            monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
            result = llm_client.call("测试", max_tokens=100)
        assert result["tool_calls"] == tool_calls
        assert result["reasoning_content"] == "思考中…"

    def test_call_plain_reasoning_field_no_content(self, monkeypatch):
        with patch("urllib.request.urlopen", return_value=_fake_urlopen({
            "choices": [{"message": {"content": "答案", "reasoning": "思路"}}]
        })):
            monkeypatch.setenv("LLM_PROVIDER", "deepseek")
            monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
            result = llm_client.call("测试", max_tokens=100)
        assert result == "答案"


class TestFallbackChain:
    def test_chain_primary_plus_fallback(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "deepseek,gemini,openrouter")
        chain = _fallback_chain()
        assert chain == ["openrouter", "deepseek", "gemini"]
        assert len(chain) == len(set(chain))  # 去重

    def test_call_falls_back_on_failure(self, monkeypatch):
        """主 provider(openrouter) 限流失败 → 自动切 fallback(deepseek) 成功。"""
        calls = []

        def _flaky_urlopen(*args, **kwargs):
            body = json.loads(args[0].data)
            calls.append(body["model"])
            if body["model"].startswith("openrouter/"):
                # 模拟 429
                import urllib.error
                raise urllib.error.HTTPError(args[0].full_url, 429, "Too Many",
                                             {}, None)
            return _fake_urlopen({"choices": [{"message": {"content": "兜底成功"}}]})

        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "ok")
        monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk")
        with patch("urllib.request.urlopen", side_effect=_flaky_urlopen):
            result = llm_client.call("测试", max_tokens=100)
        assert result == "兜底成功"
        assert len(calls) >= 2
        assert any(m.startswith("openrouter/") for m in calls)
        assert "deepseek-v4-flash" in calls

    def test_call_no_fallback_when_only_provider(self, monkeypatch):
        calls = []

        def _failing_urlopen(*args, **kwargs):
            calls.append(1)
            raise Exception("boom")

        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "gk")
        monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "gemini")  # 自身即兜底，不重复
        with patch("urllib.request.urlopen", side_effect=_failing_urlopen):
            result = llm_client.call("测试", max_tokens=100)
        assert isinstance(result, dict) and "error" in result
        assert "boom" in result["error"]
