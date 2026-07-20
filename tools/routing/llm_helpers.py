"""
routing/llm_helpers.py — LLM synthesis helpers (extracted from wrapper.py Phase 9).

Conversation history management + LLM call wrapper.
"""

from reasoning.llm_client import call as _llm_call

conversation_history = []


def _llm(prompt, system_prompt=None, max_tokens=1024, temperature=0.3, use_history=False):
    messages = _build_llm_messages(prompt, system_prompt, use_history)
    merged = "\n".join(f"[{m['role']}] {m['content'][:8000]}" for m in messages)
    result = _llm_call(merged, system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)
    if isinstance(result, dict) and "error" in result:
        return f"[LLM 错误] {result['error']}"
    return str(result) if result else ""


def _build_llm_messages(prompt, system_prompt, use_history):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if use_history:
        for role, content in conversation_history[-20:]:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": prompt})
    return messages


def _add_history(role, content):
    conversation_history.append((role, content[:500]))
    if len(conversation_history) > 40:
        conversation_history[:] = conversation_history[-40:]


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    head = text[:max_chars * 4 // 5]
    tail = text[-(max_chars // 5):]
    return head + "\n...[截断]...\n" + tail
