# Cipher 架构自评估报告

## 1. 架构定位与快照

**核心设计哲学**：确定性规则优先，LLM 辅助兜底。不是"让 LLM 思考怎么做"，而是"先问规则知不知道怎么做，规则不知道才问 LLM"。

**三层路由漏斗**：
```
用户输入 → FAISS 语义路由（classify）
           ├─ 高置信(≥0.7) + 非 event → Fast-Path（无 LLM，<10ms）
           ├─ 工作流触发词匹配 → WorkflowEngine（并行 Skill + LLM 汇总）
           └─ 低置信/event → Agent（1 次 LLM 调用选工具 + 执行）
```

**当前状态传递机制**：`RequestContext` 数据类贯穿全流程，携带 `message`/`trace_id`/`route`/`confidence`。Tracer 以结构化 JSON 日志输出跨层 span。持久化走文件系统（JSON + Markdown + FAISS 索引）。

**最显著的工程优势**：

| 优势 | 体现 |
|------|------|
| 成本可控 | 80%+ 请求走 Fast-Path，零 LLM 调用 |
| 不崩溃哲学 | 每个非关键路径都被 try/except 包裹，反射/守护都在 daemon 线程 |
| 嵌入器回退链 | sentence-transformers → ONNX → 确定性哈希噪声，永不因模型缺失挂掉 |
| 声明式工具注册 | `TOOL_REGISTRY` + `param_map`，加工具只需加字典条目，无 if/elif 链 |
| 单向依赖干净 | entry → engine → registry → handler，没有循环导入 |

---

## 2. 架构对比矩阵

| 评估维度 | Cipher 当前实现 | LangGraph / AutoGen / ReAct | 差异与 Gap |
|:---|:---|:---|:---|
| **控制流拓扑** | 线性树状：FAISS 分流 → Fast-Path / Workflow（并行步骤）/ Agent（单步 LLM→工具）。无状态图，无循环边，无条件分支。 | LangGraph 有向状态图（StateGraph），支持条件边（ConditionalEdge）、循环、节点内状态读写。AutoGen 支持多 Agent 会话式对弈。 | **Gap**：Cipher 无法表达"如果步骤 A 超时则走 B，否则走 C"的条件分支。Workflow 步骤全是 fire-and-forget 并行，没有先后依赖或回退路径。 |
| **规则/LLM 边界** | 强分隔：FAISS 阈值 0.7 硬切割。Fast-Path 零 LLM。Agent 仅用于模糊意图 + 参数提取，不做自由对话。 | 大多"LLM 驱动一切"：LangGraph 节点内 LLM 自主决策步进；ReAct 循环中 LLM 控制每一步的 Thought/Action/Observation。 | **优势**：Cipher 的 LLM 调用量是 LangGraph 风格的 1/5~1/10。劣在灵活性——无法让 LLM 自行决定"是否需要多步操作"。 |
| **状态与记忆** | 文件持久化：FAISS 向量索引 + JSON 元数据 + Markdown 观测。RequestContext 进程内传递。无会话管理，无 HITL。 | MemGPT 分层记忆（Core/Recall/Archival），自动压缩。LangGraph 内置 State 持久化到 Redis/Postgres，支持暂停/恢复。CrewAI 多 Agent 共享上下文。 | **Gap**：Cipher 没有跨会话状态，没有 Human-in-the-loop 暂停点，没有上下文压缩（ContextPruner 刚加），对话历史目前不保存。 |
| **纠错与反馈闭环** | 硬编码工作流：correction trigger → 3 步并行（写反馈 + 记录事件 + 推通知）。失败不重试，返回 fallback 文本。 | ReAct: Thought → Action → Observation 循环，LLM 观察工具输出后可自主决定重试、换工具或终止。 | **Gap**：Cipher 的"纠错"不是 Agent 反思回路，而是预定义流水线。工具失败不会触发 LLM 自主重试——这既是优点（可控），也是限制（无法处理未预见的错误模式）。 |
| **扩展性与 DX** | 加工具：在 `TOOL_REGISTRY` 加一条记录 + 编写 handler。加路由：在 `route_seeds.json` 加 seed。无 CLI 脚手架，无热重载，无可视化。 | LangGraph 有 Studio GUI、Persistence API、LangServe 部署。AutoGen 有 AutoGenBench。CrewAI 有 YAML 流程定义。 | **优势**：Cipher 的扩展成本极低（纯 Python dict + 文件），无框架依赖。**劣在**：无开发者工具链，新增调试耗时。 |

---

## 3. 核心工程痛点

### 痛点 1：Workflow 控制流过于原始

**现象**：`workflow/engine.py` 的 `run()` 把步骤全部提交到 `ThreadPoolExecutor` 后并行执行，没有顺序依赖、条件分支、重试策略。`_build_params()` 里是 if/elif 硬编码。

**根因**：最初设计只服务于一个"correction"工作流（3 步事务性操作，本就应并行），没有抽象出通用的 step DSL。

**影响**：新增工作流必须修改 `_build_params()`。无法表达"先 A 再 B，如果 B 失败则执行 C"这样的流程。LLM 汇总超时后不会重试。

### 痛点 2：缺乏会话级状态管理

**现象**：每次 `skills.entry '消息'` 调用是一次独立的 stateless 事务。没有对话上下文，用户说"上次那个事怎么样了"无法回答。

**根因**：最初设计为单次查询系统（查知识/记事件），没有考虑到多轮对话需求。

**影响**：无法支持"先问今天有什么任务 → 再看具体某条任务详情 → 然后标记完成"这样的连续交互。每个请求都要重新解析上下文。

### 痛点 3：反射器产出质量无法闭环验证

**现象**：`agent/reflector.py` 的 `_build_prompt` 截断到 200/300 字符，LLM 分析后直接写 observation。没有后续验证——分析是否准确？是否产生了重复的模式？是否被下游实际使用了？

**根因**：反射器是目前唯一的"学习"回路，但它是开环的——产出即终点，不反馈到路由种子/实体提取/阈值调整。

**影响**：反射产生的 observations 积累在文件中，但系统没有机制将它们转化为路由优化或权重调整。知识在积累但没有在利用。

---

## 4. 架构演化路线图

### P0（短期优化，1-2 周）— 痛点修补

- [ ] **Workflow DSL 升级**：将 `_build_params()` 的 if/elif 替换为声明式 param_schema + extractor，使 `workflow/definitions.py` 的步骤定义包含 `params` 字段，去掉 `engine.py` 里的硬编码。
- [ ] **Agent 工具失败 LLM 重试**：在 `agent/engine.py` 的 `execute()` 失败时，将错误信息喂回 LLM，允许它修正参数重试 1 次（"LLM-as-fallback-for-LLM"），而不是直接降级到 `_fallback_search`。
- [ ] **观测数据利用闭环**：`agent/reflector` 的分析结果写入后，定时从 observations 中提取高置信模式（如"某人擅长某事"）更新到 `entity_index.json` 的权重/标签。

### P1（架构增强，1 个月）— 能力补齐

- [ ] **会话管理**：在 `skills/shared/` 加 `conversation.py`，用简单的 JSON 文件或 SQLite 存储最近 N 轮对话。`entry.py` 为每个 session_id 加载历史，注入到 Agent 的 system prompt 或 ContextPruner 的输入。
- [ ] **Workflow 条件边**：定义 step 的 `on_success`/`on_failure`/`on_timeout` 跳转，例如 `{"skill": "A", "on_failure": {"skill": "B", "timeout": 10}}`。
- [ ] **Human-in-the-loop 挂起点**：Workflow 中定义 `"interrupt": true` 的步骤，引擎在执行前暂停，输出等待确认的消息，通过 `skills.entry --resume <workflow_id>` 继续。数据用 JSON 保存到 `data/workflow_sessions/`。

### P2（长远目标，2-3 个月）— 架构演进

- [ ] **轻量状态图引擎**：参考 LangGraph 的有向图模型，但保持 Cipher 的"规则优先"哲学——图节点可以是确定性 handler 或 LLM agent，边由声明式条件控制而非 LLM 自由决策。FAISS 路由本身就是一个条件边选择器。
- [ ] **多 Agent 分工**：不是 AutoGen 式的对弈，而是根据 FAISS 路由结果分配给不同专用 Agent（如"知识库 Agent"、"任务 Agent"、"值班 Agent"），每个 Agent 有自己的工具子集和 system prompt，减少单 Agent 的 prompt 膨胀。
- [ ] **架构可视化工具**：从 `workflow/definitions.py` + `TOOL_REGISTRY` + `route_seeds.json` 自动生成架构拓扑图（Mermaid），每次部署时输出到日志，使架构对开发者透明。

---

**总结**：Cipher 当前架构的优势在于**成本控制和确定性可靠性**——它在 80% 的场景下用零 LLM 调用完成了任务，这在业界 Agent 架构中非常少见。代价是控制流灵活性不足和缺乏会话记忆。演化路线不是"追上 LangGraph"，而是在保持规则优先的前提下，用声明式 DSL 补齐控制流缺口，用轻量会话管理补齐交互连续性。
