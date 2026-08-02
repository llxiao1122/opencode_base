#!/usr/bin/env python3
"""
llm_client.py - 统一 LLM 调用封装
支持 deepseek / zhipu / gemini 多 provider 切换。
"""

import logging, os, json, re, time, urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


PROVIDERS = {
    "deepseek": {
        "default_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-v4-flash",
        "env_key": "DEEPSEEK_API_KEY",
        "config_key": "deepseek",
        "url_suffix": "/chat/completions",
    },
    "gemini": {
        "default_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "config_key": "gemini",
        "url_suffix": "/chat/completions",
    },
    "zhipu": {
        "default_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "default_model": "GLM-4-Flash-250414",
        "env_key": "ZHIPU_API_KEY",
        "config_key": "zhipu",
        "url_suffix": "/chat/completions",
    },
}


def _resolve_config():
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    prov_cfg = PROVIDERS.get(provider, PROVIDERS.get("zhipu", {}))

    url = os.environ.get("LLM_API_URL", "")
    key = os.environ.get("LLM_API_KEY", "") or os.environ.get(prov_cfg["env_key"], "")
    model = os.environ.get("LLM_MODEL", "")

    _ENV_VAR_RE = re.compile(r'^\{env:(\w+)\}$')

    def _resolve_key(k):
        m = _ENV_VAR_RE.match(k or "")
        return os.environ.get(m.group(1), "") if m else k

    paths = [
        Path.home() / ".config" / "opencode" / "opencode.jsonc",
        Path(__file__).resolve().parent.parent.parent / ".opencode" / "opencode.jsonc",
    ]

    for p in paths:
        if not p.exists():
            continue
        try:
            raw = p.read_text()
            raw = re.sub(r'(?<!\:)//.*$', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)
            raw = re.sub(r',\s*([}\]])', r'\1', raw)
            cfg = json.loads(raw)

            prv = cfg.get("provider", {}).get(prov_cfg["config_key"], {})
            opt = prv.get("options", {})

            if not url:
                base = opt.get("baseURL", "")
                if base:
                    url = base.rstrip("/") + prov_cfg.get("url_suffix", "/chat/completions")
            if not key:
                key = _resolve_key(opt.get("apiKey", ""))
            if not model:
                model = opt.get("model", "")
        except Exception:
            pass

    return url or prov_cfg["default_url"], key, model or prov_cfg["default_model"]


def call(prompt=None, system_prompt=None, temperature=0.0, timeout=120, max_tokens=1024,
         response_format=None, tools=None, messages=None, thinking=None,
         reasoning_effort=None, user_id=None):
    url, key, model = _resolve_config()

    if not url or not key:
        return {"error": "LLM API 未配置"}

    if messages is None:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if response_format:
        body_dict["response_format"] = response_format
    if tools:
        body_dict["tools"] = tools
    if thinking is not None:
        body_dict["thinking"] = thinking
    if reasoning_effort:
        body_dict["reasoning_effort"] = reasoning_effort
    if user_id:
        body_dict["user_id"] = user_id

    body_bytes = json.dumps(body_dict).encode()

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body_bytes, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503):
                time.sleep(2 ** attempt)
                continue
            try:
                err_body = e.read()
                err = json.loads(err_body)
                if err.get("error", {}).get("code") == "1305":
                    continue
                if e.code == 402:
                    logger.error("LLM API 余额不足(402)：%s", err)
                    return {"error": "LLM API 余额不足(402)，请及时充值"}
            except Exception:
                logger.warning("DeepSeek API error parse failed: code=%s body=%s",
                               e.code, err_body if 'err_body' in locals() else 'N/A')
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < 2:
                continue
            return {"error": str(e)}

        choice = data.get("choices", [{}])[0] if data.get("choices") else {}
        # 系统推理资源不足 → 重试
        if choice.get("finish_reason") == "insufficient_system_resource":
            if attempt < 2:
                continue
            return {"error": "insufficient_system_resource"}
        msg = choice.get("message", {})
        # 缓存命中观察：usage.prompt_cache_hit_tokens 反映 KV 缓存效果
        try:
            usage = data.get("usage", {})
            hit = usage.get("prompt_cache_hit_tokens")
            miss = usage.get("prompt_cache_miss_tokens")
            if hit is not None or miss is not None:
                logger.info("LLM cache: hit=%s miss=%s (model=%s)", hit, miss, model)
        except Exception:
            pass
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # 思考模式 + tools：必须回传 reasoning_content，否则 400
            return {"tool_calls": tool_calls, "reasoning_content": msg.get("reasoning_content")}
        content = msg.get("content", "")
        # 当 content 为空但 reasoning_content 有时，说明还在推理阶段
        if not content and msg.get("reasoning_content"):
            return {"error": "模型输出为空（推理未完成）"}
        return content

    return {"error": "请求失败（限流重试耗尽）"}


def call_stream(prompt=None, system_prompt=None, temperature=0.0, timeout=120, max_tokens=1024,
                response_format=None, thinking=None, reasoning_effort=None, user_id=None,
                include_usage=False):
    """流式调用 LLM，yield 文本片段。用法: for chunk in call_stream(...): ..."""
    url, key, model = _resolve_config()

    if not url or not key:
        yield {"error": "LLM API 未配置"}
        return

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if response_format:
        body_dict["response_format"] = response_format
    if thinking is not None:
        body_dict["thinking"] = thinking
    if reasoning_effort:
        body_dict["reasoning_effort"] = reasoning_effort
    if user_id:
        body_dict["user_id"] = user_id
    if include_usage:
        body_dict["stream_options"] = {"include_usage": True}

    body_bytes = json.dumps(body_dict).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body_bytes, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line in resp:
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # 流式 usage 统计：最后一个块 choices 为空数组但带 usage
                    if include_usage and data.get("usage"):
                        try:
                            hit = data["usage"].get("prompt_cache_hit_tokens")
                            miss = data["usage"].get("prompt_cache_miss_tokens")
                            if hit is not None or miss is not None:
                                logger.info("LLM cache: hit=%s miss=%s (model=%s)", hit, miss, model)
                        except Exception:
                            pass
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
            return
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503):
                time.sleep(2 ** attempt)
                continue
            if e.code == 402:
                logger.error("LLM API 余额不足(402)，请及时充值")
                yield {"error": "LLM API 余额不足(402)，请及时充值"}
                return
            yield {"error": f"HTTP {e.code}"}
            return
        except Exception as e:
            if attempt < 2:
                continue
            yield {"error": str(e)}
            return

    yield {"error": "请求失败（限流重试耗尽）"}


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "用一句话介绍郑州地铁"
    result = call(q, max_tokens=100)
    print(result)
