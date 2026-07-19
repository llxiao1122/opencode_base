# Data Schema Audit — 工班AI助手

> 检查 Event / Task / Memory 三层之间的字段一致性。  
> 重点：字段重复、无人使用、上下游不匹配。

---

## 1. Event Schema

### 1.1 写入路径

```
core/event.extract()
    → memory/event_detector.detect()
        ↓
batch_importer.import_batch()
    → event["source_type"], event["source_file"], event["source_quality"]
    → event["detected_at"], event["time"]["start"]   ← 时间戳
        ↓
event_recorder.record()
    → event_time, import_time, recorded_at
    → source_type, source_file, source_quality
    → 落盘: memory/events/log.jsonl
```

### 1.2 字段矩阵

| 字段 | 来源 | record() 输出字段名 | 使用者 | 问题 |
|------|------|-------------------|--------|------|
| `id` | event.extract() | `id` | memory_bridge, analyzers | ✅ |
| `event_type` | event.extract() | `event_type` | 多处 | ✅ |
| `actors[].name` | event_detector | `actors` | context.resolve() | ✅ |
| `actors[].role` | event_detector | `actors` | context.resolve() | ✅ |
| `actors[].position` | event_detector | `actors` | context.resolve() | ✅ |
| `target` | event.extract() | `target` | context.resolve() | ✅ |
| `time.start` | event_detector (默认今天) | `event_time` | 无直接使用者 | ⚠️ 命名不一致：上游 `time.start` → 下游 `event_time` |
| `time.deadline` | event_detector | `deadline` | task/manager | ✅ |
| `confidence` | event.extract() | `confidence` | validator.audit_result() | ✅ |
| `source` | event.extract() | `source` | — | ⚠️ 与 `source_type` 重复？ |
| `raw` | event.extract() | `raw_preview` (截断200字) | — | ⚠️ 上游完整 raw → 下游截断 |
| `detected_at` | batch_importer (history_ts) | `event_time` | — | ⚠️ 上游 `detected_at` → 下游 `event_time` |
| `source_type` | batch_importer | `source_type` | — | ✅ 新增字段，暂未用于分析 |
| `source_file` | batch_importer | `source_file` | — | ✅ 新增字段 |
| `source_quality` | batch_importer | `source_quality` | — | ✅ 新增字段，Memory Analyzer 待用 |
| `processed_at` | batch_importer | `recorded_at` | — | ⚠️ 与 `import_time` 几乎同时 |
| — | event_recorder (datetime.now()) | `import_time` | — | ✅ 新增字段 |
| `action.summary` | event.extract() | ❌ 未写入 log.jsonl | task/manager | 🔴 断链：Task 需要 action.summary 但 record() 不保存 |

### 1.3 断链详情

**`event.action.summary` → Task 不经过 Memory**

```
core/event.extract() 产出:
    event["action"]["summary"] = "各班组完成消防检查"

task/manager.create() 使用:
    action_text = event.get("action", {}).get("summary", "")

event_recorder.record() 写入:
    ❌ 不包含 action/summary
```

**影响**：`memory_bridge.accumulate()` 只能从 Task 反向推算 event 内容，无法从 Event log 直接获取。

**修复**：event_recorder 增加 `action_summary` 字段。

---

## 2. Task Schema

### 2.1 写入路径

```
task/manager.create(event, context, user)
    → task/store.save(task)
    → 落盘: data/tasks.json
```

### 2.2 字段矩阵

| 字段 | task/manager 写入 | 使用者 | 问题 |
|------|------------------|--------|------|
| `id` | `task_{event_id}_{nnn}` | — | ⚠️ 格式由 manager._next_id() 决定 |
| `source_event_id` | event["id"] | update_from_event() | ✅ 唯一关联 |
| `responsibility_type` | context["my_position"]["type"] | analyzer | ✅ |
| `priority.value` | priority.infer_priority() | — | ⚠️ 优先级信息未被任何模块使用 |
| `priority.reason` | priority.infer_priority() | — | ⚠️ 同上 |
| `owner.name` | context["my_position"]["owner"] | store.list_by_owner() | ✅ |
| `owner.role` | user["role"] | — | ⚠️ 存储但未被查询使用 |
| `action` | 拼接动词+范围+摘要 | — | ⚠️ 文本过长(含原始消息全文) |
| `executors[].name` | org.get_members() | update_executor_status() | ✅ |
| `executors[].status` | EXECUTOR_PENDING | update_executor_status() | ✅ |
| `subtasks[].action` | 通知xxx完成xxx | — | ⚠️ 仅展示用途 |
| `subtasks[].assignee` | member name | — | ⚠️ 与 executors[].name 重复信息 |
| `subtasks[].done` | False → True | check_complete() | ✅ |
| `deadline` | event["time"]["deadline"] | analyzer.check_overdue() | ⚠️ deadline 常为空 |
| `status` | IN_PROGRESS → COMPLETED | store.list_by_owner() | ✅ |
| `created_at` | datetime.now() | analyzer | ⚠️ 历史导入时此值与 event_time 不匹配 |
| `completed_at` | store.close() 时设置 | — | ✅ |

### 2.3 字段重复

```
executors[].name  ≈  subtasks[].assignee  (高度重叠)
```
`executors` 存储执行人列表，`subtasks` 再存一遍分配关系。两者同步维护，增加不一致风险。

---

## 3. Memory / Organization Memory Schema

### 3.1 写入路径

```
memory_bridge.accumulate()
    → 读 memory/events/log.jsonl
    → 读 data/tasks.json
    → 写 data/org_memory.json
```

### 3.2 字段矩阵

| 字段 | 来源 | 使用者 | 问题 |
|------|------|--------|------|
| `people.{name}.role` | entity_index.json 回查 | — | ✅ |
| `people.{name}.appears_in_events` | log.jsonl 计数 | — | ✅ |
| `people.{name}.appears_in_tasks` | tasks.json 计数 | — | ✅ |
| `people.{name}.as_requester` | log.jsonl actors.position="requester" | — | ⚠️ 依赖 event_detector 的 position 判断 |
| `people.{name}.as_executor` | tasks.json executors[] | — | ✅ |
| `people.{name}.event_types` | log.jsonl event_type 计数 | — | ✅ |
| `patterns.top_requesters` | as_requester 排序 | — | ✅ |
| `patterns.top_executors` | as_executor 排序 | — | ✅ |
| `patterns.common_task_topics` | task.action 关键词匹配 | — | ⚠️ 关键词硬编码列表 |
| `patterns.relationship_graph` | tasks.json owner→executor | — | ✅ |

### 3.3 断链

**Event → Task 关联薄弱**

```
Event:  source_type, source_file, source_quality, confidence
Task:   source_event_id  (仅 id 字符串)
Memory: 读取两者但无法交叉验证
```

缺少：Task 是否回写 `event_id` 以外的 event 信息。`memory_analyzer` 可以读取两者但需要手动 JOIN。

---

## 4. Knowledge Schema

### 4.1 字段矩阵

| 字段 | 来源 | 使用者 | 问题 |
|------|------|--------|------|
| `id` | store._chunk_id() | retriever | ✅ |
| `source_file` | filename | retriever | ✅ |
| `source_hash` | SHA256 | scanner | ✅ |
| `base_name` | processor._extract_metadata() | deprecate_by_base() | ✅ |
| `version` | processor._extract_metadata() | list_versions() | ✅ |
| `status` | processor | retriever(search) | ✅ |
| `section_path` | processor | retriever(display) | ✅ |
| `text` | processor | indexer(embed), retriever | ✅ |
| `type` | processor._infer_type() | — | ⚠️ 存储但检索未用 |
| `indexed_at` | datetime.now() | — | ✅ |

---

## 5. 跨层字段对比

### 5.1 时间字段

| 层 | 字段名 | 值 | 含义 |
|----|--------|-----|------|
| Message | `timestamp` | `"2026-03-25"` 或 `""` | 消息原始时间 |
| Event (内存) | `detected_at` | `"2026-03-25"` 或 `""` | 事件被检测的时间(=消息时间) |
| Event (log.jsonl) | `event_time` | 同上 | 同上 |
| Event (log.jsonl) | `import_time` | `"2026-07-19T13:49"` | 导入到系统的系统时间 |
| Event (log.jsonl) | `recorded_at` | `"2026-07-19T13:49"` | ≈ import_time, 冗余 |
| Task | `created_at` | `datetime.now()` | 任务创建的系统时间 |
| Task | `completed_at` | `datetime.now()` | 任务完成的系统时间 |

**问题**：`recorded_at` 和 `import_time` 几乎总是相同（都是 event_recorder 调用时的系统时间），语义冗余。

### 5.2 人物字段

| 层 | 字段路径 | 示例 |
|----|---------|------|
| Event (内存) | `actors[].name` + `actors[].position` | `{"name":"王亮","position":"requester"}` |
| Event (log.jsonl) | `actors[].name` + `actors[].role` + `actors[].position` | 同上但加了 role |
| Task | `owner.name` | `"李林骁"` |
| Task | `executors[].name` | `"苗笑天"` |
| Memory (org) | `people.{name}.as_requester` | 32 |
| entity_index | `confirmed_entities[].name` + `role` | `{"name":"王亮","role":"安全管理岗"}` |

**问题**：event 中的 `actors[].role` 来自 entity_index 回查，但 task 中的 `executors[].role` 缺失。Memory 层需要从 entity_index 补齐。

---

## 6. 核心断链清单

| # | 断链 | 严重度 | 影响 |
|---|------|--------|------|
| 1 | Record 不保存 `action.summary` | 🔴 高 | Memory 无法从 Event 直接读取任务内容 |
| 2 | `recorded_at` ≈ `import_time`，冗余 | 🟡 中 | 混淆语义 |
| 3 | `source` vs `source_type` 字段重叠 | 🟡 中 | `source="dingtalk_group"` vs `source_type="history_txt"` |
| 4 | Task `created_at` ≠ Event `event_time` | 🟡 中 | 历史导入时，Task 使用当前时间而非原始时间 |
| 5 | `raw` → `raw_preview` 截断 | 🟡 中 | Event 完整 raw 可恢复，但 log 只保存 200 字 |
| 6 | executors[].name ≈ subtasks[].assignee | 🟢 低 | 数据重复 |
| 7 | knowledge `type` 字段未使用 | 🟢 低 | 分类信息浪费 |
