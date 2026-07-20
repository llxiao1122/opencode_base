#!/usr/bin/env python3
"""
llm_client.py - 统一 LLM 调用封装
供 simulator、memory_core 等模块共享 DeepSeek API 调用。
"""

import os, json, re, urllib.request
from pathlib import Path


DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def _resolve_config():
    url = os.environ.get("LLM_API_URL", "")
    key = os.environ.get("LLM_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")

    paths = [
        Path.home() / ".config" / "opencode" / "opencode.jsonc",
        Path(__file__).resolve().parent.parent.parent / ".opencode" / "opencode.jsonc",
    ]

    for p in paths:
        if not p.exists():
            continue
        if key and url and model:
            break
        try:
            raw = p.read_text()
            raw = re.sub(r'(?<!\:)//.*$', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)
            raw = re.sub(r',\s*([}\]])', r'\1', raw)
            cfg = json.loads(raw)

            prv = cfg.get("provider", {}).get("deepseek", {})
            opt = prv.get("options", {})
            if not url:
                base = opt.get("baseURL", "")
                if base:
                    url = base.rstrip("/") + "/v1/chat/completions"
            if not key:
                rk = opt.get("apiKey", "")
                if isinstance(rk, str) and rk.startswith("{env:") and rk.endswith("}"):
                    key = os.environ.get(rk[5:-1], "")
                else:
                    key = rk
            if not model:
                model = "deepseek-chat"
        except (json.JSONDecodeError, KeyError):
            pass

    return url or DEFAULT_URL, key, model or DEFAULT_MODEL


def call(prompt, system_prompt=None, temperature=0.3, timeout=30, max_tokens=1024):
    url, key, model = _resolve_config()

    if not url or not key:
        return json.dumps({"error": "LLM API 未配置"})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

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
