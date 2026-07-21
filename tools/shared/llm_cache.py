"""
shared/llm_cache.py — LLM 调用缓存。

将 _cached_llm 从 entry.py 提取到共享层，消除循环依赖。
"""

import hashlib
import time
from reasoning.llm_client import call as _llm_raw

_cache = {}


def call(prompt, system_prompt=None, user="", ttl=60, max_tokens=300, temperature=0.3):
    key = hashlib.sha256(
        f"{user}:{(system_prompt or '')[:80]}:{prompt[:300]}".encode()
    ).hexdigest()
    entry = _cache.get(key)
    if entry and time.time() - entry[1] < entry[2]:
        return entry[0]
    raw = _llm_raw(prompt, system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)
    answer = str(raw).strip() if raw and not (isinstance(raw, dict) and "error" in raw) else ""
    _cache[key] = (answer, time.time(), ttl)
    return answer
