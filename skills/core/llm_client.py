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
        "auth_header": "Authorization",  # Bearer <key>
    },
    "openrouter": {
        "default_url": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "openrouter/free",
        "env_key": "OPENROUTER_API_KEY",
        "config_key": "openrouter",
        "url_suffix": "/chat/completions",
        "auth_header": "Authorization",  # Bearer <key>
    },
    "gemini": {
        "default_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model": "gemini-3.6-flash",
        "env_key": "GEMINI_API_KEY",
        "config_key": "gemini",
        "url_suffix": "/chat/completions",
        # OpenAI 兼容端点实测：必须 Authorization Bearer（x-goog-api-key 仅原生 API 支持）
        "auth_header": "Authorization",
    },
    "zhipu": {
        "default_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "default_model": "GLM-4-Flash-250414",
        "env_key": "ZHIPU_API_KEY",
        "config_key": "zhipu",
        "url_suffix": "/chat/completions",
        "auth_header": "Authorization",  # Bearer <key>
    },
}


def _resolve_config(provider=None):
    provider = (provider or os.environ.get("LLM_PROVIDER", "deepseek")).lower()
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

    return url or prov_cfg["default_url"], key, model or prov_cfg["default_model"], provider


def _fallback_chain():
    """主 provider + 兜底 provider 链（LLM_FALLBACK_PROVIDERS 逗号分隔，默认 deepseek）。"""
    chain = [os.environ.get("LLM_PROVIDER", "deepseek").lower()]
    for p in os.environ.get("LLM_FALLBACK_PROVIDERS", "deepseek").split(","):
        p = p.strip().lower()
        if p and p not in chain and p in PROVIDERS:
            chain.append(p)
    return chain


def _build_body(provider, messages, temperature, max_tokens, stream,
                response_format=None, tools=None, thinking=None,
                reasoning_effort=None, user_id=None, include_usage=False):
    body = {
        "model": None,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if response_format:
        body["response_format"] = response_format
    if tools:
        body["tools"] = tools
    if include_usage:
        body["stream_options"] = {"include_usage": True}
    if provider == "openrouter":
        # OpenRouter 统一 reasoning 参数（不认 DeepSeek 的 thinking 字段）
        if thinking is not None or reasoning_effort:
            body["reasoning"] = {"enabled": True,
                                 "effort": reasoning_effort or "high"}
    elif provider == "gemini":
        # Gemini OpenAI 兼容端点原生支持 reasoning_effort（映射 thinking level/budget）
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
    else:
        if thinking is not None:
            body["thinking"] = thinking
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
    if user_id:
        if provider == "openrouter" or provider == "gemini":
            body["user"] = user_id  # OpenAI 兼容字段
        else:
            body["user_id"] = user_id  # DeepSeek 原生字段
    return body


def _build_headers(provider, key):
    prov_cfg = PROVIDERS.get(provider, {})
    headers = {"Content-Type": "application/json"}
    if key:
        auth = prov_cfg.get("auth_header", "Authorization")
        if auth == "x-goog-api-key":
            headers[auth] = key
        else:
            headers[auth] = f"Bearer {key}"
    return headers


def call(prompt=None, system_prompt=None, temperature=0.0, timeout=120, max_tokens=1024,
         response_format=None, tools=None, messages=None, thinking=None,
         reasoning_effort=None, user_id=None):
    if messages is None:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

    last_err = None
    for provider in _fallback_chain():
        url, key, model, provider = _resolve_config(provider)
        if not url or not key:
            last_err = {"error": f"LLM API 未配置（provider={provider}）"}
            continue

        body_dict = _build_body(provider, messages, temperature, max_tokens, False,
                                response_format=response_format, tools=tools,
                                thinking=thinking, reasoning_effort=reasoning_effort,
                                user_id=user_id)
        body_dict["model"] = model
        body_bytes = json.dumps(body_dict).encode()
        headers = _build_headers(provider, key)

        result = None
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
                        last_err = {"error": "LLM API 余额不足(402)，请及时充值"}
                        result = last_err
                        break
                except Exception:
                    logger.warning("LLM API error parse failed: code=%s body=%s",
                                   e.code, err_body if 'err_body' in locals() else 'N/A')
                last_err = {"error": f"HTTP {e.code}"}
                result = last_err
                break
            except Exception as e:
                if attempt < 2:
                    continue
                last_err = {"error": str(e)}
                result = last_err
                break

            choice = data.get("choices", [{}])[0] if data.get("choices") else {}
            # 系统推理资源不足 → 重试
            if choice.get("finish_reason") == "insufficient_system_resource":
                if attempt < 2:
                    continue
                last_err = {"error": "insufficient_system_resource"}
                result = last_err
                break
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
            reasoning = msg.get("reasoning_content") or msg.get("reasoning")
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # 思考模式 + tools：必须回传 reasoning_content，否则 400
                return {"tool_calls": tool_calls, "reasoning_content": reasoning}
            content = msg.get("content", "")
            # 思考模式 JSON 决策偶发空 content（文档明示已知问题）：重试而非直接失败
            if not content:
                if attempt < 2:
                    continue
                last_err = {"error": "模型输出为空"}
                result = last_err
                break
            return content

        if result is None:
            last_err = {"error": "请求失败（限流重试耗尽）"}
        # 若上一 provider 失败（限流/配置缺失），切 fallback 重试
        if last_err is not None and "error" in last_err:
            logger.warning("provider=%s 调用失败，切换到 fallback：%s", provider, last_err)
            continue
        return result

    return last_err or {"error": "所有 provider 均失败"}


def call_stream(prompt=None, system_prompt=None, temperature=0.0, timeout=120, max_tokens=1024,
                response_format=None, thinking=None, reasoning_effort=None, user_id=None,
                include_usage=False):
    """流式调用 LLM，yield 文本片段。用法: for chunk in call_stream(...): ..."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for provider in _fallback_chain():
        url, key, model, provider = _resolve_config(provider)
        if not url or not key:
            logger.warning("provider=%s 未配置，切换 fallback", provider)
            continue

        body_dict = _build_body(provider, messages, temperature, max_tokens, True,
                                response_format=response_format, thinking=thinking,
                                reasoning_effort=reasoning_effort, user_id=user_id,
                                include_usage=include_usage)
        body_dict["model"] = model
        body_bytes = json.dumps(body_dict).encode()
        headers = _build_headers(provider, key)

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
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    logger.warning("provider=%s 流式限流重试耗尽，切换 fallback", provider)
                    break
                if e.code == 402:
                    logger.error("LLM API 余额不足(402)，请及时充值")
                    yield {"error": "LLM API 余额不足(402)，请及时充值"}
                    return
                yield {"error": f"HTTP {e.code}"}
                return
            except Exception as e:
                if attempt < 2:
                    continue
                logger.warning("provider=%s 流式调用失败：%s，切换 fallback", provider, e)
                break  # 换 fallback provider 重试

        continue  # 当前 provider 未成功 → 下一 fallback

    yield {"error": "LLM API 未配置（所有 provider）"}


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "用一句话介绍郑州地铁"
    result = call(q, max_tokens=100)
    print(result)
