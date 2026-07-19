# Architecture Review — 工班AI助手

> 综合审计报告。基于 `CURRENT_ARCHITECTURE.md`、`MODULE_AUDIT.md`、`DATA_SCHEMA_AUDIT.md`。  
> 2026-07-19

---

## 一、当前真实架构

### 两条主链（核心价值）

```
链 A: 消息 → 认知 → 执行
─────────────────────────
消息 → parse → classify → event.extract → context.resolve → task.create → memory.record
                                    │                      │
                              (5种责任类型)            (拆子任务+追踪)
                                                              │
                                                        org_memory.json
                                                        (人物统计+关系图)

链 B: 知识 → 索引 → 检索
─────────────────────────
Knowledge/*.md → processor → chunker → embed → FAISS → retriever.search
                  (保留章节)           (all-MiniLM)   (独立索引)   (生命周期过滤)
```

### 现状评分

| 维度 | 得分 | 说明 |
|------|------|------|
| 消息理解 | ✅ 85% | 解析、分类、事件提取稳定运行 |
| 责任判断 | ✅ 90% | 5 种类型覆盖，规则驱动无 LLM |
| 任务管理 | ✅ 80% | 创建/拆任务/跟踪/闭环完整 |
| 历史导入 | ✅ 75% | 批量+去重+时间保留+质量标记 |
| 知识检索 | ✅ 70% | 向量搜索可用，版本管理初步 |
| 记忆积累 | ⚠️ 40% | 统计层完成，画像未开始 |
| 自动运行 | ❌ 10% | 无 cron/watch/webhook |

---

## 二、存在断链

### 关键断链 (🔴)

| # | 断链 | 修复成本 |
|---|------|---------|
| 1 | `event_recorder` 不保存 `action.summary` → Memory 无法从 Event 读任务内容 | 低 (+1 字段) |
| 2 | Task `created_at` 用系统时间而非 event 原始时间 | 低 (历史导入时已设 event_time) |
| 3 | Feedback 闭环未验证 — 群里有反馈但无法匹配到任务 | 中 (执行者不在 executors 列表中) |
| 4 | `[图片]`/`[文件]` 消息跳过，覆盖率仅 33% | 高 (需要 OCR/文档解析) |
| 5 | `plugins/task_manager` 写旧格式 `memory/tasks.md`，与 `data/tasks.json` 不互通 | 中 (删除旧模块) |

### 次要断链 (🟡)

| # | 断链 |
|---|------|
| 6 | `recorded_at` ≈ `import_time` 语义重叠 |
| 7 | `organization/model.py` 硬编码团队数据 |
| 8 | `memory_analyzer.run()` 无自动触发器 |
| 9 | `event_maintenance.run_maintenance()` 无调度 |

---

## 三、重复模块

| 功能 | 旧模块 | 新模块 | 行动 |
|------|--------|--------|------|
| 任务生成 | `core/task.py` | `task/manager.py` | **删除** core/task.py |
| 知识搜索 | `plugins/knowledge_router/` | `knowledge/retriever.py` | **删除** knowledge_router |
| 任务管理 | `plugins/task_manager/` | `task/store.py` | **删除** task_manager 插件 |
| 关键词注入 | `legacy/keyword_discovery.py` | — | **删除** (违反架构) |
| 导入管线 | `replay/replay_engine.py` | `ingestion/batch_importer.py` | **删除** 或保留 deprecated |

### 可合并

| 合并 | 建议文件名 |
|------|-----------|
| `context/request_context.py` + `context/hierarchy_resolver.py` | `context/builder.py` |
| `memory/event_search.py` + `memory/event_context.py` | `memory/event_query.py` |

---

## 四、建议保留核心链路

### 最小可用集（不可删除）

```
入口层:
  commands/import_history.py      ← 统一导入入口
  commands/import_knowledge.py    ← 知识索引入口
  routing/wrapper.py              ← 实时消息入口 (双轨)

处理层:
  ingestion/batch_importer.py     ← 统一管线
  ingestion/message_parser.py     ← 消息解析
  ingestion/message_classifier.py ← 消息分类
  ingestion/validator.py          ← 质量检查

认知层:
  core/event.py                   ← 事件提取
  core/context.py                 ← 责任判断
  task/manager.py                 ← 任务管理
  task/store.py                   ← 任务持久化

组织层:
  organization/model.py           ← 组织模型
  organization/memory_bridge.py   ← 记忆统计

知识层:
  knowledge/scanner.py
  knowledge/processor.py
  knowledge/indexer.py
  knowledge/store.py
  knowledge/retriever.py

记忆层:
  memory/event_recorder.py        ← 事件记录
  memory/memory_core.py           ← FAISS 索引
  memory/memory_server.py         ← MCP 服务

推理层:
  reasoning/llm_client.py         ← LLM 客户端
```

### 待废弃（下次大版本）

```
core/task.py
legacy/keyword_discovery.py
plugins/knowledge_router/
plugins/task_manager/
replay/replay_engine.py
```

---

## 五、建议删除/合并列表

### 立即可删除（3 个文件）

```
tools/core/task.py                                ← 硬编码，被 manager 替代
tools/legacy/keyword_discovery.py                  ← 违反架构约束
tools/replay/replay_engine.py                      ← 已降级，无独立逻辑
```

### 可删除但需验证测试依赖（4 文件）

```
tools/plugins/knowledge_router/query_knowledge.py  ← 被 knowledge/retriever 替代
tools/plugins/knowledge_router/read_doc.py          ← 文档解析工具，与管线无关
tools/plugins/task_manager/manage_tasks.py          ← 旧格式 memory/tasks.md
tools/plugins/task_manager/prefill_tasks.py         ← 同上
```

**注意**：删除前需确认 `wrapper.py` (旧管线 `handle()`) 是否有引用。旧管线引用需保留兼容。

### 可合并（3 → 2 文件）

```
context/request_context.py + context/hierarchy_resolver.py  →  context/builder.py
memory/event_search.py + memory/event_context.py            →  memory/event_query.py
```

---

## 六、入口统一性建议

### 现状：5 个入口分散在 3 个目录

```
routing/wrapper.py::handle_core()      # 实时消息
routing/wrapper.py::handle()           # 旧管线
commands/import_history.py             # 文件导入 + 剪贴板
commands/import_knowledge.py           # 知识索引
```

### 建议：统一到 commands/

```
commands/
├── core/
│   └── process.py        ← wrapper.handle_core() 移入
├── ingest/
│   ├── batch.py          ← import_history()
│   └── clipboard.py      ← clipboard_import()
├── knowledge/
│   └── index.py          ← import_knowledge()
└── analyze/
    └── memory.py         ← memory_analyzer.run() 入口 (未来)
```

`wrapper.py` 保留作为 CLI 入口的兼容层。

### 自动触发（未来）

| 触发器 | 命令 | 频率 |
|--------|------|------|
| cron | `memory_analyzer.run()` | 每日 |
| cron | `event_maintenance.run_maintenance()` | 每小时 |
| cron | `import_knowledge()` (检查更新) | 每周 |
| watcher | `import_history()` (新文件) | 实时 |
| webhook | `import_history()` (钉钉 webhook) | 实时 |

---

## 七、下一阶段开发顺序

| Phase | 内容 | 优先级 | 预估 |
|-------|------|--------|------|
| **6.1** | 删除 dead code (core/task, legacy, plugins 旧模块) | 🔴 高 | 1h |
| **6.2** | 修复关键断链 (event_recorder + action.summary) | 🔴 高 | 0.5h |
| **6.3** | Profile Store (人物画像基础) | 🟡 中 | 1d |
| **6.4** | 统一入口 commands/ 结构 | 🟡 中 | 2h |
| **6.5** | 自动提醒 (cron + watcher) | 🟢 低 | 1d |
| **6.6** | 联合推理层 (Event + Knowledge 联合检索) | 🟢 低 | 2d |

---

## 八、当前不可行

| 目标 | 原因 |
|------|------|
| 图片/文件内容解析 | 需要 OCR、文档解析库，超出当前 scope |
| 员工绩效评价 | 架构约束：只统计事实，不生成评价 |
| 实时钉钉 bot 接入 | 需要 webhook 基础设施 |
| 全自动闭环 | Feedback 匹配率低，需更完善的 executor 检测 |

---

## 九、最终判定

系统当前是**可运行的 MVP**，核心链路（消息→事件→任务→记忆）和知识链路（文档→索引→检索）都已连接。主要问题是 **dead code 堆积**（~8 个文件可删）和 **记忆层薄弱**（统计层完成，但 profile 层缺失）。

**建议**：先清理 dead code，再建 profile，不要扩展新能力。
