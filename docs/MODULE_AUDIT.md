# Module Audit — 工班AI助手

> Snapshot: 2026-07-19. 检查每个模块的调用链、引用关系、是否活跃。

---

## 1. 全模块状态表

### core/ (认知核心)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `core/event.py` | ✅ active | `batch_importer`, `wrapper` | — | 保留 |
| `core/context.py` | ✅ active | `batch_importer`, `wrapper` | — | 保留 |
| `core/task.py` | ⚠️ 废弃 | 无 (已被替代) | 硬编码 `_TEAM_MAP`，功能被 `task/manager.py` 完全覆盖 | **删除** |

### task/ (任务管理)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `task/manager.py` | ✅ active | `batch_importer`, `wrapper` | — | 保留 |
| `task/store.py` | ✅ active | `task/manager` | — | 保留 |
| `task/status.py` | ✅ active | `task/store`, `task/manager` | — | 保留 |
| `task/priority.py` | ✅ active | `task/manager` | — | 保留 |
| `task/analyzer.py` | ⚠️ 无调用 | 无 | `stats_for()`, `check_overdue()` 未被任何模块调用 | 保留(未来需要)，或标记为工具函数 |

### routing/ (路由/响应)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `routing/wrapper.py` | ✅ active | CLI 入口 | 双轨运行：`handle()` 旧 + `handle_core()` 新 | 保留旧管线(兼容)，新功能不进 `handle()` |
| `routing/composer.py` | ✅ active | `wrapper` | — | 保留 |
| `routing/route_request.py` | ⚠️ 旧管线 | `wrapper.handle()` | 仅旧管线使用，CORE_MODE 不经过 | 保留(兼容)，逐步废弃 |
| `routing/llm_tags.py` | ⚠️ 旧管线 | `route_request` | 仅旧管线使用 | 保留(兼容) |
| `routing/entity_resolver.py` | ✅ active | `event_detector`, `route_request` | — | 保留 |
| `routing/protocol.py` | ✅ active | `composer` | — | 保留 |
| `routing/context_builder.py` | ⚠️ 无引用 | 测试文件 | `build_work_context()` — 未被非测试代码调用 | 保留(work_view 管线用) |

### ingestion/ (批量导入)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `ingestion/batch_importer.py` | ✅ active | `import_history`, `replay` | 统一管线入口 | 保留 |
| `ingestion/message_parser.py` | ✅ active | `batch_importer` | — | 保留 |
| `ingestion/message_classifier.py` | ✅ active | `batch_importer` | — | 保留 |
| `ingestion/validator.py` | ✅ active | `batch_importer` | — | 保留 |
| `ingestion/rtf_parser.py` | ✅ active | `batch_importer` | — | 保留 |

### knowledge/ (知识索引)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `knowledge/scanner.py` | ✅ active | `import_knowledge` | — | 保留 |
| `knowledge/processor.py` | ✅ active | `import_knowledge`, `scanner` | — | 保留 |
| `knowledge/indexer.py` | ✅ active | `import_knowledge`, `retriever` | FAISS 独立索引 | 保留 |
| `knowledge/store.py` | ✅ active | `import_knowledge`, `retriever` | — | 保留 |
| `knowledge/retriever.py` | ✅ active | `import_knowledge` | — | 保留 |

### memory/ (记忆系统)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `memory/memory_core.py` | ✅ active | `memory_server`, `slow_think`, `curiosity` | FAISS 双索引 | 保留 |
| `memory/memory_server.py` | ✅ active | MCP 协议 | — | 保留 |
| `memory/event_detector.py` | ⚠️ 结构膨胀 | `core/event.py`, `event_lifecycle` | 147KB 巨型文件，50+ 函数 | **重构**：拆成 detect/parse/time 三个文件 |
| `memory/event_recorder.py` | ✅ active | `batch_importer` | — | 保留 |
| `memory/event_lifecycle.py` | ⚠️ 低使用 | `event_detector` | 状态迁移逻辑少被触发 | 保留(轻量) |
| `memory/event_search.py` | ⚠️ 低使用 | `work_query` (旧) | 旧管线用 | 保留(兼容) |
| `memory/event_context.py` | ⚠️ 旧管线 | `wrapper` (旧) | 旧管线用 | 保留(兼容) |
| `memory/event_maintenance.py` | ❌ 无调用 | 无 | `run_maintenance()` 无 cron/触发器 | 保留(未来) |
| `memory/memory_analyzer.py` | ⚠️ 手动 | 无自动触发器 | `run()` 发现行为模式 | 保留(未来) |
| `memory/memory_reflect.py` | ⚠️ CLI | 手动 | `core.reflect()` 的 CLI 入口 | 保留 |
| `memory/curiosity_engine.py` | ⚠️ 实验 | 无 | 好奇心引擎，实验性 | 保留(待验证) |
| `memory/user_model.py` | ⚠️ 实验 | `slow_think` | 用户领域模型 | 保留(待验证) |
| `memory/change_detector.py` | ⚠️ 无调用 | `event_detector` (被引用) | 变更检测逻辑 | 保留(事件管线依赖) |
| `memory/candidate_store.py` | ✅ active | `memory_analyzer` | — | 保留 |
| `memory/confidence.py` | ✅ active | `memory_analyzer` | — | 保留 |
| `memory/observation_writer/` | ⚠️ 独立 | 无 | 独立写入观测 | 保留 |

### organization/ (组织模型)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `organization/model.py` | ✅ active | `task/manager`, `batch_importer` | 硬编码团队数据 | **改进**：从 `state/org.md` + `entity_index.json` 动态加载 |
| `organization/memory_bridge.py` | ✅ active | `import_history`, `clipboard_import` | — | 保留 |

### replay/ (回放引擎)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `replay/replay_engine.py` | ⚠️ 降级 | — | 已全量委托 `batch_importer`，仅保留向后兼容 | **删除** (下次大版本) 或保留标记 deprecated |

### commands/ (用户入口)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `commands/import_history.py` | ✅ active | CLI | — | 保留 |
| `commands/import_knowledge.py` | ✅ active | CLI | — | 保留 |

### plugins/ (外部插件)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `plugins/task_manager/` | ❌ 旧格式 | 无 | 写 `memory/tasks.md`(旧格式)，与 `data/tasks.json` 不互通 | **标记废弃** |
| `plugins/knowledge_router/` | ❌ 已替代 | 无 | grep 搜索，被 `knowledge/retriever` 替代 | **删除** |
| `plugins/state_analyzer/` | ⚠️ 独立 | `wrapper` | 读 state 文件，独立工具 | 保留 |
| `plugins/team_router/` | ⚠️ 独立 | `wrapper` | 成员路由，独立工具 | 保留 |
| `plugins/dingbot/` | ✅ 独立 | 外部 | 钉钉机器人 webhook | 保留 |
| `plugins/email_notifier/` | ⚠️ 存在? | — | 未找到 | — |
| `plugins/wechat_notifier/` | ⚠️ 存在? | — | 未找到 | — |

### pipeline/ (管道)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `pipeline/event_enricher.py` | ✅ active | `core/event.py` (lazy) | AI 内容补充 | 保留 |
| `pipeline/instruction_resolver.py` | ⚠️ 低使用 | `context/request_context` | 指令解析 | 保留 |

### reasoning/ (推理)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `reasoning/llm_client.py` | ✅ active | 多处 | DeepSeek API | 保留 |
| `reasoning/slow_think.py` | ⚠️ 实验 | 无 | System 2 推理 | 保留(实验) |
| `reasoning/simulator.py` | ⚠️ 实验 | `slow_think` | 因果模拟 | 保留(实验) |
| `reasoning/value_arbiter.py` | ⚠️ 实验 | `slow_think` | 价值仲裁 | 保留(实验) |

### legacy/ (旧代码)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `legacy/keyword_discovery.py` | ❌ 违规 | 无 | 动态注入关键词，违反架构约束 | **删除** |

### work/ (工作视图)

| 模块 | 状态 | 调用者 | 问题 | 建议 |
|------|------|--------|------|------|
| `work/work_query.py` | ⚠️ 旧格式 | `wrapper` | 读取 `memory/tasks.md`(旧) | 保留(兼容)，逐步迁移到 `data/tasks.json` |
| `work/work_view.py` | ⚠️ 旧格式 | `work_query` | — | 保留(兼容) |
| `work/responsibility.py` | ⚠️ 旧格式 | `work_query` | — | 保留(兼容) |

---

## 2. 功能重复检测

| 功能 | 位置 A | 位置 B | 严重度 |
|------|--------|--------|--------|
| 任务生成 | `task/manager.py::create()` | `core/task.py::generate()` | 🔴 高 — core/task 应删除 |
| 事件检测 | `core/event.py::extract()` | `memory/event_detector.py::detect()` | 🟡 中 — event.py 调用 detector，关系正确但 detector 过重 |
| 知识搜索 | `plugins/knowledge_router/query_knowledge.py` | `knowledge/retriever.py::search()` | 🔴 高 — 后者完全覆盖前者 |
| 任务管理 | `plugins/task_manager/manage_tasks.py` | `task/store.py` + `task/manager.py` | 🔴 高 — 旧格式(memory/tasks.md) vs 新格式(data/tasks.json) |
| 导入管线 | `replay/replay_engine.py` | `ingestion/batch_importer.py` | 🟢 低 — replay 已降级为薄封装 |
| 消息解析 | `ingestion/message_parser.py` | `ingestion/rtf_parser.py::parse_rtf()` | 🟢 低 — rtf_parser 是 parser 的适配层，合理 |

---

## 3. 无调用链模块 (建议删除)

| 模块 | 文件 | 原因 |
|------|------|------|
| `core/task.py` | 1 文件 | 功能完全被 task/manager.py 替代 |
| `legacy/keyword_discovery.py` | 1 文件 | 违反架构约束(禁止新关键词规则) |
| `plugins/knowledge_router/` | 2 文件 | 被 knowledge/ 模块完全替代 |
| `replay/replay_engine.py` | 1 文件 | 已降级为薄封装，可安全删除 |

---

## 4. 建议合并的模块

| 合并 | 理由 |
|------|------|
| `context/request_context.py` + `context/hierarchy_resolver.py` | 都是 context 构建，可合并为 `context/builder.py` |
| `memory/event_search.py` + `memory/event_context.py` | 都是事件查询，功能相近 |
| `parse/section_parser.py` + `extract/ai_content_extractor.py` | pipeline 中的解析+提取，可合并为 `pipeline/content_pipeline.py` |

---

## 5. 统计

| 分类 | 数量 |
|------|------|
| ✅ 活跃模块 | 28 |
| ⚠️ 低使用/需改进 | 12 |
| ❌ 建议删除 | 4 |
| 📦 总模块文件 | ~57 (.py) |
| 建议净减少 | ~8 文件 |
