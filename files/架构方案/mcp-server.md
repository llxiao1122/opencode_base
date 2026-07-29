# MCP Server — 记忆与认知工具

## 启动

```bash
/home/admin/opencode_base/.venv/bin/python3 skills/memory/memory_server.py
```

STDIO 协议，JSON-RPC 2.0。通过 `initialize` 握手（protocolVersion 2024-11-05）。

## 工具清单

### 1. `memory_search` — 记忆检索

跨三层（情景+语义）联合搜索。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 自然语言查询 |
| `types` | string[] | 否 | `["episodic","semantic"]`，默认全搜 |
| `top_k` | integer | 否 | 1-10，默认 5 |

### 2. `memory_save` — 保存经验

格式：情境 → 行动 → 结果。系统自动评估重要性。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `situation` | string | ✅ | 发生了什么 |
| `action` | string | ✅ | 采取的应对措施 |
| `outcome` | string | ✅ | 结果如何 |
| `importance` | string | 否 | `high`/`medium`/`low`，默认 `medium` |

### 3. `knowledge_retrieve` — 知识库查询

从工班知识库语义检索制度/流程/规范。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `topic` | string | ✅ | 查询主题 |
| `max_chars` | integer | 否 | 返回内容最大字符数，默认 2000 |

### 4. `cognitive_reflect` — 认知反思

对输入问题进行 Probe(LLM 分析+假设+评分) → Simulate(因果推演)。结果写入 `observation_store`。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | ✅ | 待分析的问题或情境描述 |

### 5. `memory_reflect`（已废弃）

旧版反思工具。推荐使用 `cognitive_reflect`。

---

## 调用示例

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_search","arguments":{"query":"上次暴雨导致基坑积水的处理方案","top_k":3}}}
```

## 实现文件

`skills/memory/memory_server.py`（186 行）
- 依赖: `MemoryCore`, `CognitiveLoop`
- 内存驻留，单线程 STDIO 循环
