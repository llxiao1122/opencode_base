#!/usr/bin/env python3
"""
llm_client.py - 统一 LLM 调用封装
供 simulator、memory_core 等模块共享 DeepSeek API 调用。
"""

import os, json, re, urllib.request
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
}


def _resolve_config():
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    prov_cfg = PROVIDERS.get(provider, PROVIDERS["deepseek"])

    url = os.environ.get("LLM_API_URL", "")
    key = os.environ.get("LLM_API_KEY", "") or os.environ.get(prov_cfg["env_key"], "")
    model = os.environ.get("LLM_MODEL", "")

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

            if p == Path.home() / ".config" / "opencode" / "opencode.jsonc":
                k = opt.get("apiKey", "")
                if k and not k.startswith("{env:"):
                    key = k

            if not url:
                base = opt.get("baseURL", "")
                if base:
                    url = base.rstrip("/") + prov_cfg.get("url_suffix", "/chat/completions")
            if not key:
                key = opt.get("apiKey", "")
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

    extra_body = {"type": "disabled"} if model in ("deepseek-v4-flash", "deepseek-v4-pro") else None
    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_body:
        body_dict["thinking"] = extra_body
    body = json.dumps(body_dict).encode()

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "用一句话介绍郑州地铁"
    result = call(q, max_tokens=100)
    print(result)
