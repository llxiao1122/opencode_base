"""
skills/shared/context_pruner.py — LLM 上下文裁剪。

移除过长的 intermediate_steps、去重相似文本、控制消息总数。
防止 Agent 上下文超出模型窗口。
"""
import re
from typing import Optional

_CHAR_RATE = 4.0


def _estimate_tokens(text: str) -> int:
    return int(len(text) / _CHAR_RATE) + 1


def _has_recent_timestamp(text: str) -> bool:
    m = re.search(r'(\d{4})\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}', text)
    if not m:
        return False
    try:
        return int(m.group(1)) >= 2025
    except ValueError:
        return False


class ContextPruner:
    def __init__(self, token_budget: int = 2000):
        self.token_budget = token_budget

    def prune(self, texts: list[str], query: Optional[str] = None) -> list[str]:
        if not texts:
            return texts

        total = sum(_estimate_tokens(t) for t in texts)
        if total <= self.token_budget:
            return texts

        scored = []
        for t in texts:
            score = 1.0
            if _has_recent_timestamp(t):
                score += 2.0
            if query:
                q_lower = query.lower()
                t_lower = t.lower()
                match_count = sum(1 for w in q_lower.split() if w in t_lower)
                score += match_count * 0.5
            scored.append((score, len(t), t))

        scored.sort(key=lambda x: (-x[0], x[1]))

        result = []
        budget = self.token_budget
        for _, length, text in scored:
            estimated = _estimate_tokens(text)
            if estimated <= budget:
                truncated = text
            else:
                keep_len = int(budget * _CHAR_RATE)
                truncated = text[:keep_len] + "\n...(截断)"
            result.append(truncated)
            budget -= _estimate_tokens(truncated)
            if budget <= 0:
                break

        return result
