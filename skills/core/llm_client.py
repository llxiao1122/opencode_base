#!/usr/bin/env python3
"""
llm_client.py - 统一 LLM 调用封装
供 simulator、memory_core 等模块共享 DeepSeek API 调用。
"""

import os, json, re, time, urllib.request
from pathlib import Path


PROVIDERS = {
    "deepseek": {
        "default_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-v4-flash",
        "env_key": "DEEPSEEK_API_KEY",
        "config_key": "deepseek",
        "url_suffix": "/v1/chat/completions",
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
    provider = os.environ.get("LLM_PROVIDER", "zhipu").lower()
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


def call(prompt, system_prompt=None, temperature=0.3, timeout=30, max_tokens=1024):
    url, key, model = _resolve_config()

    if not url or not key:
        return json.dumps({"error": "LLM API 未配置"})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if model in ("deepseek-v4-flash", "deepseek-v4-pro"):
        body_dict["thinking"] = {"type": "disabled"}
    elif "glm" in model.lower() or "zhipu" in model.lower():
        body_dict["thinking_mode"] = False

    body = json.dumps(body_dict).encode()

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            try:
                err = json.loads(e.read())
                if err.get("error", {}).get("code") == "1305":
                    continue
            except Exception:
                pass
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < 2:
                continue
            return {"error": str(e)}

        msg = data.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "")
        # 当 content 为空但 reasoning_content 有时，说明还在推理阶段
        if not content and msg.get("reasoning_content"):
            return {"error": "模型输出为空（推理未完成）"}
        return content

    return {"error": "请求失败（限流重试耗尽）"}


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "用一句话介绍郑州地铁"
    result = call(q, max_tokens=100)
    print(result)
