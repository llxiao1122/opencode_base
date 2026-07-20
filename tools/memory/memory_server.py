#!/usr/bin/env python3
"""
memory_server.py — MCP STDIO wrapper for MemoryCore.
完整 MCP 协议实现：支持 initialize 握手与 JSON-RPC id 回传。
"""

import sys, json, os, traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from memory.memory_core import MemoryCore

ROOT = os.environ.get("MEMORY_DIR", str(Path(__file__).resolve().parent.parent.parent))
core = MemoryCore(root_path=ROOT)

TOOLS = [
    # ... 你的四个工具定义保持不变 ...
    {
        "name": "memory_search",
        "description": "跨三层记忆联合检索。传入自然语言查询，返回最相关的历史经验和知识库段落。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言查询，如'上次暴雨导致基坑积水的处理方案'"},
                "types": {"type": "array", "items": {"type": "string", "enum": ["episodic", "semantic"]}, "default": ["episodic", "semantic"]},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_save",
        "description": "保存一条经验到情景记忆。格式为：情境→行动→结果。系统自动评估重要性，返回保存结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "situation": {"type": "string", "description": "发生了什么事件、背景"},
                "action": {"type": "string", "description": "采取的应对措施"},
                "outcome": {"type": "string", "description": "结果如何"},
                "importance": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
            },
            "required": ["situation", "action", "outcome"],
        },
    },
    {
        "name": "knowledge_retrieve",
        "description": "从工班知识库检索相关制度/流程/规范。语义搜索非关键词匹配。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "查询主题，如'灭火器更换周期'"},
                "max_chars": {"type": "integer", "default": 2000, "description": "返回内容最大字符数"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "memory_reflect",
        "description": "触发反思回路。扫描近期观察记录，提取可复用的经验。应在每个复杂任务完成后调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_days": {"type": "integer", "default": 7, "description": "扫描最近 N 天的记录"},
            },
        },
    },
]

def handle(req):
    method = req.get("method")
    req_id = req.get("id")  # 必须保留 id 用于响应

    # === MCP 初始化握手 ===
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "memory",
                    "version": "1.0.0"
                }
            }
        }

    # 通知类请求，无需响应
    if method == "notifications/initialized":
        return None

    # === 工具列表 ===
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        }

    # === 工具调用 ===
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        try:
            method_map = {
                "memory_search": "search",
                "memory_save": "save",
                "knowledge_retrieve": "retrieve",
                "memory_reflect": "reflect",
            }
            core_method = method_map.get(name, name)
            fn = getattr(core, core_method, None)
            if fn is None:
                raise ValueError(f"Unknown tool: {name}")
            result = fn(**args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": str(e)
                }
            }

    # 未知方法
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}"
        }
    }


if __name__ == "__main__":
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
            resp = handle(req)
            if resp is None:   # 通知无响应
                continue
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except BrokenPipeError:
            break
