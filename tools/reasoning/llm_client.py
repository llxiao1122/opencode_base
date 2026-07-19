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
    """获取 API 配置，优先级：env > opencode.jsonc > 默认值"""
    url = os.environ.get("LLM_API_URL", "")
    key = os.environ.get("LLM_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")

    if not key:
        config_path = Path.home() / ".config" / "opencode" / "opencode.jsonc"
        if config_path.exists():
            raw = config_path.read_text()
            raw = re.sub(r'//.*$', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)
            raw = re.sub(r',\s*([}\]])', r'\1', raw)
            cfg = json.loads(raw)

            provider = cfg.get("provider", {}).get("deepseek", {})
            options = provider.get("options", {})
            if not url:
                base = options.get("baseURL", "")
                url = base.rstrip("/") + "/v1/chat/completions" if base else DEFAULT_URL
            if not key:
                raw_key = options.get("apiKey", "")
                if isinstance(raw_key, str) and raw_key.startswith("{env:") and raw_key.endswith("}"):
                    env_var = raw_key[5:-1]
                    key = os.environ.get(env_var, "")
                else:
                    key = raw_key
            if not model:
                model = "deepseek-chat"

    return url or DEFAULT_URL, key, model or DEFAULT_MODEL


def call(prompt, system_prompt=None, temperature=0.3, timeout=30, max_tokens=1024):
    """调用 DeepSeek Chat Completion，返回文本内容。"""
    url, key, model = _resolve_config()

    if not url or not key:
        return json.dumps({"error": "LLM API 未配置（设置 LLM_API_KEY 环境变量或在 opencode.jsonc 中配置）"})

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
