# 架构重组方案：Skill 化 + 三层引擎

> 基于 Phase 1-3 现状，重新梳理架构布局。

---

## 一、可 Skill 化模块清单

### 已注册 Skill（5个）

| ID | 模块 | 接口 | 类型 |
|----|------|------|------|
| `task_query` | `skills/routing/task_handler:handle(msg, ctx)` | `(str, RequestContext) → str` | 查询→日程 |
| `knowledge_retrieve` | `skills/routing/knowledge_handler:handle(topic, ctx)` | `(str, RequestContext) → str` | 查询→知识 |
| `profile_query` | `skills/agent/skills/profile:handle(name)` | `(str) → str` | 查询→画像 |
| `notification_push` | `skills/agent/skills/notification:handle(title, content)` | `(str, str) → str` | 执行→推送 |
| `event_record` | `skills/agent/skills/event_record:handle(params)` | `(dict) → str` | 执行→记录 |

### 暴露可注册但未注册的 Skill（6个）

| ID | 模块 | 接口 | 理由 |
|----|------|------|------|
| `tasks_list` | `skills/task/manager:list_active(owner)` | `(str) → list[dict]` | 独立查询某人任务，区别于日程 |
| `task_create` | `skills/task/manager:create(event, context, user)` | `(dict, dict, dict) → dict` | Agent 直接创建任务 |
| `person_profile_full` | `skills/profile/user_retriever:get_person_context(name)` | `(str) → dict` | 完整画像（当前 profile 太简化） |
| `org_lookup` | `skills/organization/model` | 多方法 | 组织查询 |
| `event_query` | `skills/memory/event_recorder:list_events(type, limit)` | `(str, int) → list[dict]` | 历史事件检索 |
| `knowledge_faiss` | `skills/knowledge/retriever:search(query, top_k)` | `(str, int) → list[dict]` | 底层 FAISS 搜索 |

### 基础设施层（被 Skill 调用，不直接暴露）

| 模块 | 角色 |
|------|------|
| `memory/memory_core.py` | 语义+情景双索引引擎（MCP 宿主） |
| `memory/observation_store.py` | 长期记忆持久化（facts/patterns/conclusions） |
| `memory/event_recorder.py` | 事件 log 持久化 |
| `memory/event_lifecycle.py` | 事件状态迁移 |
| `memory/change_detector.py` | 组织变更检测 |
| `knowledge/retriever.py` | FAISS 上层封装 |
| `knowledge/indexer.py` | FAISS 索引重建 |
| `routing/entity_resolver.py` | 人名→实体解析 |
| `plugins/dingbot/send_msg.py` | 钉钉 API 包装 |
| `core/llm_client.py` | LLM 调用（Zhipu） |
| `shared/*` | 数据合约/工具 |
| `task/store.py` | 任务 JSON 持久化 |
| `correction/*` | 离线学习 |
| `pattern/miner.py` | 批量统计分析 |

---

## 二、架构重组方案

### 核心观察

1. Pipeline 已降级为"快速路径"——只在高置信度且非 event 时走
2. event route 仍然走完整 5 层，但 L3 reasoning + L5 response 都调 LLM，与 Agent 路径的 LLM 调用重复
3. agent 路径做了 LLM 工具选择，但当前只有 5 个工具，可选工具远不止此
4. 无统一执行层——Pipeline 的 L4 execution 和 Agent 的 registry.execute 是两套调度
5. 无执行后反馈循环——结果不反馈回 Memory（learner 只学路由，不学效果）

### 新架构：三层引擎

```
                      ┌─────────────────────────────────────────┐
                      │            entry.py                      │
                      │    _build_index → _classify → dispatch   │
                      └─────────────────┬───────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    │                                       │
             高置信非 event                           其他（低置信/event/agent）
                    │                                       │
               ┌────▼────┐                           ┌──────▼─────────┐
               │  Pipeline  │                         │  Agent Engine   │
               │ (L1-L5)    │                         │ LLM→intent→tool │
               └────┬────┘                           └──────┬─────────┘
                    │                                       │
                    └──────────┬──────────────┬─────────────┘
                               │              │
                         ┌─────▼──────┐  ┌────▼────┐
                         │ Skills     │  │ Skills  │
                         │ Registry   │  │ Registry│
                         └─────┬──────┘  └────┬────┘
                               │              │
                         ┌─────▼──────────────▼────┐
                         │      Unified Execution  │
                         │    (tools/executor.py)   │
                         └─────┬──────────────┬────┘
                               │              │
                    ┌──────────▼──┐    ┌──────▼──────────┐
                    │ Infrastructure│  │ Memory Feedback │
                    │ (FAISS/store) │  │ (observe/learn) │
                    └─────────────┘    └─────────────────┘
```

### 各层职责

#### 1. 入口层（entry.py）——路由+分叉

- classify() → (route, confidence)
- conf >= CT.HIGH && route != "event" → Pipeline
- 其他 → Agent Engine

#### 2. Pipeline（core/pipeline.py）——仅用于高置信规则路径

保留 L1-L5：ingress → intent → reasoning → execution → response
- L1-L2: 规则层
- L3 reasoning: 仅 event route 时启用
- L4-L5: 调用 Skills Registry 执行 + LLM 合成

#### 3. Agent Engine（agent/engine.py）——统一代理层

```
agent/engine.py::run()
  ├── LLM call：输出结构化 JSON（intent + tool + params）
  ├── Skills Registry：匹配工具
  ├── Unified Executor：参数校验 + 执行 + 格式化
  ├── Memory Feedback：自动写 observation
  └── Fallback：knowledge_retrieve 兜底
```

#### 4. Skills Registry（agent/registry.py）——统一工具注册表

注册表从 5 个扩展到 10+ 个，按类别分组：

| 类别 | 工具 ID |
|------|---------|
| 查询类 | task_query, knowledge_retrieve, profile_query, tasks_list, event_query, org_lookup |
| 执行类 | notification_push, event_record, task_create |
| 分析类 | memory_reflect, pattern_mine |

**handler 规则化**：不再按工具 ID 手写 if/elif，改为统一参数映射：

```python
def execute(tool_id, params):
    tool = TOOL_REGISTRY[tool_id]
    mod, func = tool["handler"].split(":")
    handler = getattr(importlib.import_module(mod), func)
    mapped = {k: params.get(k, v.get("default"))
              for k, v in tool["params_schema"].items()}
    result = handler(**mapped)
    _post_execute(tool_id, params, result)
    return result
```

#### 5. Unified Executor（新增：agent/executor.py）

合并三处执行入口：
- `core/execution.py`（Pipeline L4）
- `agent/registry.py:execute()`（Agent 调度）
- `agent/engine.py:_fallback_search()`（兜底）

```python
def execute_skill(tool_id, params, ctx=None) -> str
def execute_fallback(query) -> str
def post_process(result, tool_id, ctx) -> str
```

#### 6. Memory Feedback（新增：memory/feedback.py）

统一执行后自动反馈，替代当前分散的手动 observation 写入：

```python
def feedback(tool_id, params, result, ctx):
    # 写 decision_log
    # 写 observation（事件/通知类自动）
    # 触发 learner（异步）
    pass
```

### 模块迁移清单

| 当前位置 | 目标位置 | 变更 |
|----------|----------|------|
| `skills/core/pipeline.py` | 保留 | 仅快速路径 |
| `skills/core/ingress.py` | 保留 | 快速路径 L1 |
| `skills/core/intent.py` | 保留 | 快速路径 L2 |
| `skills/core/reasoning.py` | 保留 | 仅 event route |
| `skills/core/execution.py` | **弃用** | Unified Executor 替代 |
| `skills/core/response.py` | 保留但简化 | 仅 Pipeline LLM 合成 |
| `skills/agent/registry.py` | 保留+改造 | 通用参数映射 |
| `skills/agent/engine.py` | 保留 | Agent 核心 |
| `skills/agent/skills/` | 保留 | 新 skill 放这里 |
| `skills/routing/task_handler.py` | 保留 | 查询类 Skill |
| `skills/routing/knowledge_handler.py` | 保留 | 查询类 Skill |
| `skills/routing/entity_resolver.py` | 保留 | 基础设施 |
| `skills/profile/user_retriever.py` | `agent/skills/profile_deep.py` | 升级 profile 底层 |
| `skills/task/manager.py` | 保留 | 注册为 `task_create` skill |
| `skills/task/store.py` | 保留 | 基础设施 |
| `skills/memory/event_recorder.py` | 注册为 `event_query` skill | 查询类 |
| `skills/organization/model.py` | 注册为 `org_lookup` skill | 查询类 |
| `skills/correction/learner.py` | 保留 | 基础设施 |
| `skills/correction/logger.py` | 保留 | 基础设施 |

### 新目录结构

```
skills/
├── routing/
│   ├── entry.py              # 单入口 + 双路径分叉
│   ├── query_router.py       # FAISS 分类
│   ├── route_index_manager.py# FAISS 索引管理
│   ├── task_handler.py       # 日程查询 skill
│   ├── knowledge_handler.py  # 知识查询 skill
│   └── entity_resolver.py    # 实体解析
│
├── agent/
│   ├── engine.py             # Agent 核心
│   ├── registry.py           # 工具注册表（通用参数映射）
│   ├── executor.py           # 【新增】统一执行器
│   └── skills/               # 所有 Skill handler
│       ├── task_query.py
│       ├── knowledge.py
│       ├── profile.py
│       ├── profile_deep.py   # 【新增】完整画像
│       ├── notification.py
│       ├── event_record.py
│       ├── task_create.py    # 【新增】
│       ├── tasks_list.py     # 【新增】
│       ├── event_query.py    # 【新增】
│       └── org_lookup.py     # 【新增】
│
├── core/                     # Pipeline 5 层（仅快速路径）
│   ├── pipeline.py
│   ├── ingress.py
│   ├── intent.py
│   ├── context.py
│   ├── event.py
│   ├── reasoning.py
│   ├── response.py
│   └── llm_client.py
│
├── task/
│   ├── manager.py
│   ├── store.py
│   ├── priority.py
│   └── status.py
│
├── memory/
│   ├── memory_core.py
│   ├── memory_server.py
│   ├── observation_store.py
│   ├── event_recorder.py
│   ├── event_lifecycle.py
│   ├── event_maintenance.py
│   ├── feedback.py           # 【新增】执行后自动反馈
│   ├── change_detector.py
│   └── detect/
│
├── knowledge/
│   ├── retriever.py
│   └── indexer.py
│
├── plugins/
│   └── dingbot/
│       └── send_msg.py
│
├── correction/
│   ├── learner.py
│   └── logger.py
│
├── pattern/
│   └── miner.py
│
├── organization/
│   └── model.py
│
└── shared/
    ├── schema.py
    ├── entity.py
    ├── llm_cache.py
    ├── semantic.py
    ├── task_format.py
    └── time_parse.py
```

### 执行路线

1. 注册表统一化——registry.py 改为通用参数映射（不再手写 if/elif per tool）
2. 新增 Unified Executor——agent/executor.py，接管 Pipeline L4 + Agent 调度
3. 新增 Memory Feedback——memory/feedback.py，执行后自动写 observation + log
4. 新增 5 个 Skill——tasks_list, task_create, event_query, org_lookup, profile_deep
5. 弃用 core/execution.py——迁移到 Unified Executor
6. 简化 Pipeline L4-L5——改为调用 Unified Executor
