# Current Architecture — 工班AI助手

> Auto-generated audit. Snapshot: 2026-07-19.  
> **Rule**: no changes made. Observation only.

---

## 1. 完整模块关系图

```
                        ┌─────────────────────────────┐
                        │         入口 (Entry)           │
                        │  wrapper.handle_core()        │ ← 实时消息
                        │  wrapper.handle()             │ ← 旧管线 (兼容)
                        │  import_history()             │ ← 批量文件
                        │  clipboard_import()           │ ← 手工粘贴
                        │  import_knowledge()           │ ← 知识索引
                        └──────────────┬──────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
┌───────────────┐             ┌───────────────┐             ┌───────────────┐
│  消息处理层     │             │   知识处理层    │             │   路由/响应层   │
│  ingestion/    │             │  knowledge/    │             │  routing/      │
│               │             │               │             │               │
│ message_parser│             │ scanner       │             │ wrapper        │
│ → classifer   │             │ → processor   │             │ → composer     │
│ → rtf_parser  │             │ → indexer     │             │ → route_req    │
│ → validator   │             │ → store       │             │ → llm_tags     │
│               │             │ → retriever   │             │ → entity_res   │
│ batch_importer│             │               │             │               │
│  (统一管线)    │             │               │             │               │
└───────┬───────┘             └───────┬───────┘             └───────────────┘
        │                             │
        ▼                             ▼
┌───────────────┐             ┌───────────────┐
│   认知核心层    │             │   存储层        │
│               │             │               │
│ core/event    │             │ data/tasks.json│
│ core/context  │             │ data/org_memory│
│ core/task     │ ← 旧版     │ .json          │
│               │             │ data/knowledge/│
│ task/manager  │ ← 新版     │   *.index      │
│ task/store    │             │   *.json       │
│ task/priority │             │ data/import_*  │
│ task/analyzer │             │ memory/events/ │
│               │             │   log.jsonl    │
│ organization/ │             │ memory/.vector/│
│   model       │             │   *.index      │
│   memory_bridge│            │                │
└───────┬───────┘             └────────────────┘
        │
        ▼
┌───────────────┐
│   记忆/推理层   │
│               │
│ memory/       │
│   memory_core │ ← FAISS 双索引
│   event_*     │
│   memory_serv │ ← MCP
│               │
│ reasoning/    │
│   llm_client  │
│   slow_think  │
└───────────────┘
```

## 2. 入口完整列表

| 入口 | 文件 | 触发方式 | 输入 | 管线 |
|------|------|---------|------|------|
| `handle_core()` | `routing/wrapper.py` | 实时消息 | 文本 | event→context→task→composer |
| `handle()` | `routing/wrapper.py` | 旧入口 | 文本 | route_request→handler A-I |
| `import_history()` | `commands/import_history.py` | 手动 | 目录 | parser→classifier→batch_importer→memory_bridge |
| `clipboard_import()` | `commands/import_history.py` | 手动 | 文本 | parser(allow_missing_time)→batch_importer→memory_bridge |
| `import_knowledge()` | `commands/import_knowledge.py` | 手动 | 目录 | scanner→processor→indexer→store |

## 3. 数据流详情

### 3.1 实时消息链路

```
wrapper.handle_core(text)
    │
    ▼
core/event.extract(text)
    └─→ memory/event_detector.detect()  ← 信号检测
    └─→ pipeline/event_enricher         ← AI 补充 (LLM)
    → Event dict {id, event_type, actors, target, time, ...}
    │
    ▼
core/context.resolve(event, user)
    └─→ 5种责任类型: executor|coordinator|supervisor|audience|observer
    → Context dict {my_position, required_action, reason}
    │
    ▼
task/manager.create(event, context, user)
    └─→ organization/model.get_members()
    └─→ priority.infer_priority()
    → Task dict {id, owner, executors, subtasks, status, ...}
    │
    ▼
routing/composer.execute_plan()  ← LLM 合成回复
    │
    ▼
memory/event_recorder.record(event)  → memory/events/log.jsonl
```

### 3.2 批量文件导入链路

```
import_history(dir_path)
    │
    ▼
batch_importer.import_dir(dir_path)
    │
    ├── scanner?  (无 — 文件级去重用 import_registry.json)
    │
    ├── validator.validate(text)     ← 预扫质量
    │
    ├── import_batch(text, source_type, source_file)
    │       │
    │       ├── message_parser.parse(text)       → Message[]
    │       ├── message_classifier.classify(msg) → type
    │       ├── core/event.extract(content)      → Event
    │       ├── core/context.resolve(event)      → Context
    │       ├── task/manager.create(event, ctx)  → Task
    │       └── event_recorder.record(event)     → log.jsonl
    │
    ├── validator.audit_result()     ← 事后审计
    │
    └── 写 data/reports/replay_*.json
    │
    ▼
memory_bridge.accumulate()
    → log.jsonl + tasks.json → data/org_memory.json
```

### 3.3 知识入库链路

```
import_knowledge(dir_path)
    │
    ▼
scanner.scan(dir_path, existing_sources)
    → {added, modified, deleted, sibling_conflicts}
    │
    ▼
processor.process(filepath)
    → [{section_path, text, type, version, base_name, status}]
    │
    ▼
store.save(chunks, source_file, source_hash)
    → data/knowledge/knowledge_index.json
    │
    ▼
indexer.rebuild(all_chunks)
    → data/knowledge/semantic_knowledge.index (FAISS)
    │
    ▼
retriever.search(query)
    → [{id, source_file, section_path, text, score, status}]
```

### 3.4 Memory 层 (独立 MCP)

```
memory_server.py (STDIO MCP)
    │
    ├── memory_search(query, types, top_k)
    │       └→ MemoryCore.search() → FAISS episodic + semantic
    │
    ├── memory_save(situation, action, outcome)
    │       └→ MemoryCore.save() → observations/*.md + FAISS episodic
    │
    ├── knowledge_retrieve(topic, max_chars)
    │       └→ MemoryCore.retrieve() → FAISS semantic (Knowledge dir)
    │
    └── memory_reflect(since_days)
            └→ MemoryCore.reflect() → LLM scan observations
```

## 4. 存储层清单

| 路径 | 格式 | 写入者 | 读取者 |
|------|------|--------|--------|
| `data/tasks.json` | JSON array | `task/store.py` | `task/analyzer`, `memory_bridge`, `memory_analyzer` |
| `data/org_memory.json` | JSON | `memory_bridge` | — (待读取) |
| `data/knowledge/knowledge_index.json` | JSON | `knowledge/store` | `knowledge/retriever` |
| `data/knowledge/semantic_knowledge.index` | FAISS | `knowledge/indexer` | `knowledge/retriever` |
| `data/import_registry.json` | JSON | `batch_importer` | `batch_importer` |
| `data/import_batches.json` | JSON | `import_history` | — (日志用途) |
| `data/reports/replay_*.json` | JSON | `batch_importer` | 人工查阅 |
| `memory/events/log.jsonl` | JSONL | `event_recorder` | `memory_bridge`, `memory_analyzer`, `event_search` |
| `memory/events/index.json` | JSON | `event_detector` | `wrapper` (旧管线) |
| `memory/events/{active,completed,detected}/` | JSON | `event_lifecycle` | — |
| `memory/observations/*.md` | MD | `memory_core.save()` | `memory_core.reflect()` |
| `memory/.vector/{semantic,episodic}.index` | FAISS | `memory_core` | `memory_core` |
| `state/entity_index.json` | JSON | `entity_resolver` | 多处 |
| `state/user_profile.md` | MD | 手动 | `core/context.load_user()` |

## 5. 外部依赖

| 库 | 用途 | 使用者 |
|----|------|--------|
| `faiss` | 向量索引 | `memory_core`, `knowledge/indexer` |
| `numpy` | 向量运算 | `memory_core`, `knowledge/indexer` |
| `sentence_transformers` | all-MiniLM-L6-v2 | `memory_core`, `knowledge/indexer` |
| `requests` | HTTP | `dingbot/send_msg` |
| DeepSeek API | LLM | `reasoning/llm_client` |
| `docx` (optional) | Word 解析 | `plugins/read_doc` |
| `openpyxl` (optional) | Excel 解析 | `plugins/read_doc` |
