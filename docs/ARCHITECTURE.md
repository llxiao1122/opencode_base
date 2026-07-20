# Cipher 架构文档 — 新成员速查

> 基于 Phase 13 代码快照。自动构建于 2026-07-20。
> 唯一入口：`python3 tools/routing/entry.py '<消息>'`

---

## 1. 分层架构

```
用户消息
  │
  ▼
┌──────────────────────────────────────────────────┐
│  入口层  entry.py::handle_core()                 │
│  - 启动: 构建 entity_index                       │
│  - 每个消息: lifecycle 更新 → query_router 分类   │
│  - 末尾: 实体变化检测                             │
└──────────────┬───────────────────────────────────┘
               │
         ┌─────┴──────┬──────────┬──────────────┐
         ▼            ▼          ▼              ▼
     profile      task       knowledge      event
     handler     handler     handler        pipeline
         │            │          │              │
         └────────────┴──────────┴──────────────┘
               │
               ▼
         LLM 合成 → 自然语言回复
```

---

## 2. 各层详解

### 2.1 入口层 — `tools/routing/entry.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `handle_core(user_input)` | 文本消息 | 回复字符串 | 唯一入口，一次硬路由分到 4 个 handler 之一 |
| `_build_index_once()` | 无 | 无 | 首次调用时从 state 源文件重建 `entity_index.json` |
| `_update_event_lifecycle(user_input)` | 文本 | 无 | 检查消息是否完成/取消已有事件，更新事件状态 |
| `_detect_entity_changes(user_input)` | 文本 | 无 | 含"负责/接手/离职/休假"关键词时触发 change_detector |
| `_cached_llm(prompt, sys_prompt)` | prompt | LLM 回复 | SHA256 缓存，TTL=60s，避免相同请求重复调 API |
| `_handle_event(user_input, user, ...)` | 文本+用户 | 回复 | event→context→task→LLM 完整管线 |

### 2.2 路由层 — `tools/routing/query_router.py`

| 函数 | 输入 | 输出 | 逻辑 |
|------|------|------|------|
| `classify(user_input)` | 文本 | `"profile"` / `"task"` / `"knowledge"` / `"event"` | 纯规则关键词匹配，无 LLM。优先级：profile > task > knowledge > event |

**路由关键词**：

| 路由 | 触发词（任一命中） |
|------|-------------------|
| profile | 什么样、怎么样、评价、能力、表现、画像、是谁、性格 |
| task | 今天、明天、本周、待办、任务、安排、工作 |
| knowledge | 制度、规定、流程、标准、规范、禁止、不得、怎么办 |
| event | （兜底，以上全未命中） |

### 2.3 Handler 层

#### task_handler — `tools/routing/task_handler.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `handle(user_input, ctx)` | 文本+上下文 | 工作安排清单 | 主入口：检测时间范围，聚合固定+动态任务 |
| `_detect_scope(text)` | 文本 | `"today"/"tomorrow"/"week"` | 时间范围解析 |
| `_get_daily_work(text, target_date)` | 文本+日期 | 固定工作文本 | 从 `Knowledge/00-日常工作指引.md` 解析：值班人、库区负责人、材料棚、每日/周五/月度固定、汛期、演练 |
| `_get_duty_person(target, md)` | 日期 | 值班人名 | 从 Knowledge markdown 解析轮值序列+锚点，推算当天值班人 |
| `_parse_duty_cycle(md)` | markdown | (序列, 锚点日期, 锚点位置) | 解析"陈红洁→张志斌→..."序列表和参照日期表 |
| `_extract_contacts(tasks, daily_text)` | 任务+文本 | 联系人摘要 | 从 entity_index 提取任务相关外部联系人（排除团队成员） |

数据源：
- `data/tasks.json` → 动态任务
- `Knowledge/00-日常工作指引.md` → 固定工作、轮值、库区分配、汛期、演练
- `state/entity_index.json` → 联系人角色

#### profile_handler — `tools/routing/profile_handler.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `handle(user_input, ctx)` | 文本+上下文 | 人物画像 | 提取人名，加载画像+记忆，LLM 合成 |
| `_extract_person_name(text)` | 文本 | 人名 | 通过 entity_resolver 匹配实体 |

数据源：`profile/retriever.py::get_person_context()`, `memory/retriever.py::search_person()`

#### knowledge_handler — `tools/routing/knowledge_handler.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `handle(user_input, ctx)` | 文本+上下文 | 合规回答 | FAISS 搜索知识库 → LLM 合成 |

数据源：`knowledge/retriever.py::search()`, `data/knowledge/knowledge_index.json`

### 2.4 事件提取层 — `tools/core/event.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `extract(text, current_user)` | 原始文本+用户 | Event dict `{id, event_type, actors, time, confidence, raw}` | 事实提取入口，调用 event_detector.detect() |
| `_infer_event_type(text, raw_evt)` | 文本+检测结果 | `instruction/notification/inspection/report/incident/feedback/unknown` | 纯规则，通过标题关键词判断 |
| `_build_actors(raw_evt)` | 检测结果 | `[{name, role, position}]` | 组装 requester/executor/entity |

依赖：`memory/event_detector.py::detect()` — 6 种信号检测（动作+时间、动作+实体、编号+动作、通知+时间、角色+动作、关键词），≥2 信号触发。

### 2.5 上下文理解层 — `tools/core/context.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `resolve(event, user)` | Event + 用户 | Context dict `{my_position, required_action, reason, deadline_feasibility}` | 5 种责任类型判断 |

**5 种责任类型**（纯规则，顺序判断）：

| 优先级 | 类型 | 条件 | 动作 |
|--------|------|------|------|
| 1 | supervisor | 当前用户是发起人 | 监督执行人 |
| 2 | executor | 当前用户被直接点名 | 完成目标 |
| 3 | coordinator | 群体通知 + 当前用户是工班长 | 督促团队 |
| 4 | audience | 群体通知 + 非负责人 | 关注即可 |
| 5 | observer | 兜底 | 信息接收 |

`_check_deadline_feasibility(event)` — 工作小时计算，少于 4h 标记不可行，少于 8h 标记紧张。

### 2.6 任务管理层 — `tools/task/manager.py` + `store.py`

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `TaskManager.create(event, context, user)` | Event+Context+User | Task dict | 规则创建任务：coordinator→拆子任务，executor→个人任务，observer→不创建 |
| `TaskManager.update_from_event(event)` | feedback Event | {matched, executor, all_done} | 匹配执行人→更新状态→全员done→自动关闭 |
| `store.save(task)` | Task dict | 无 | JSON 持久化到 `data/tasks.json` |
| `store.load(task_id)` | id | Task dict | 单条加载 |
| `store.list_by_owner(owner, status)` | 人名+状态 | Task list | 按工班长查询 |
| `store.close(task_id)` | id | bool | 关闭任务，写 completed_at |

`task/priority.py::infer_priority(raw_text)` — 安全关键词（消防/防汛/应急…）→ high，其余→ normal。

### 2.7 组织层 — `tools/organization/model.py`

| 方法 | 输入 | 输出 |
|------|------|------|
| `get_members(owner)` | 工班长名 | `["苗笑天","张志斌","谭继衡","杨梦卓","陈红洁"]` |
| `get_leader(member)` | 成员名 | `"李林骁"` |
| `get_team_name(owner)` | 工班长名 | `"铁炉西工班"` |

内部字典实现，团队数据硬编码于类体内。

### 2.8 实体层 — `tools/shared/entity.py` + `tools/entity/builder.py`

**builder.py** — 从 state 源文件自动构建 `entity_index.json`：

| 函数 | 输入 | 输出 |
|------|------|------|
| `build()` | 无 | 完整 entity_index dict |
| `parse_members()` | — | 从 `state/members/*.md` 解析（姓名 from 文件名，职责 from `职责:` 行） |
| `parse_leaders()` | — | 从 `state/leaders.md` 解析（`姓名(角色)` 或 `姓名: 角色` 格式） |
| `parse_org()` | — | 从 `state/org.md` 解析（TREE section + ROLE section） |

**shared/entity.py** — 运行时实体查询：

| 函数 | 说明 |
|------|------|
| `load_entities()` | 加载全部实体（confirmed + pending），缓存 |
| `get_role(name)` | 按人名查角色 |
| `get_team(name)` | 按人名查班组 |
| `find_entities_in_text(text)` | 从文本中提取实体名 |

调用方：`core/event.py`, `core/context.py`, `task_handler.py`, `profile_handler.py`

### 2.9 记忆层 — `tools/memory/`

| 模块 | 关键函数 | 职责 |
|------|---------|------|
| `memory_core.py` | `MemoryCore.search(query, types, top_k)` | FAISS 双索引（semantic 语义 + episodic 情景）搜索 |
| `memory_core.py` | `MemoryCore.save(situation, action, outcome)` | 保存经验 → `memory/observations/*.md` + FAISS episodic 索引 |
| `memory_core.py` | `MemoryCore.retrieve(topic, max_chars)` | 按主题从语义索引检索知识 |
| `memory_core.py` | `MemoryCore.reflect(since_days)` | 扫描近期观察，聚类、压缩提炼经验规则 |
| `event_recorder.py` | `record(event)` | Event → `memory/events/log.jsonl` |
| `event_lifecycle.py` | `update_from_message(text)` | 根据消息文本完成/取消/确认事件 |
| `change_detector.py` | `detect(text)` | 从文本中检测人员职责/状态变化（负责/接手/离职/休假…） |

MCP 服务：`tools/memory/memory_server.py` — 对外暴露 4 个工具：`memory_search` / `memory_save` / `knowledge_retrieve` / `memory_reflect`

### 2.10 LLM 层 — `tools/reasoning/llm_client.py`

| 函数 | 说明 |
|------|------|
| `call(prompt, system_prompt, temperature, max_tokens)` | DeepSeek Chat Completion API 调用 |
| `_resolve_config()` | 配置优先级：`LLM_API_KEY` env > `DEEPSEEK_API_KEY` env > `~/.config/opencode/opencode.jsonc` |

### 2.11 上下文构建层 — `tools/context/request_context.py`

| 函数 | 说明 |
|------|------|
| `build_request_context()` | 从 `state/user_profile.md` 加载当前用户 `{name, role, team}` |
| `inject_user_prompt(ctx)` | 生成 LLM prompt 前缀："你正在与李林骁（工班长，铁炉西工班）对话" |

---

## 3. 数据流 — 完整路径

### 路径 A：工作查询（"明天什么工作"）

```
"明天什么工作"
  │
  ▼
entry.py::handle_core()
  ├── _build_index_once()              → entity_index.json 首次重建
  ├── _update_event_lifecycle()        → 检查是否有事件完成/取消
  │
  ├── query_router.classify()          → "task"
  │    关键词: "今天""明天""工作"
  │
  ├── task_handler.handle()
  │     ├── _detect_scope()            → "tomorrow"
  │     ├── _load_tasks()              → data/tasks.json
  │     ├── _filter_tasks()            → 过滤 in_progress
  │     │
  │     └── _get_daily_work()          → Knowledge/00-日常工作指引.md
  │           ├── _get_duty_person()   → 推算当日值班人
  │           ├── _get_zone_chiefs()   → 库区负责人
  │           ├── _get_material_shed() → 材料棚轮换
  │           ├── _get_flood_season()  → 汛期附加工作
  │           ├── 每日/周五/月度固定    → 表解析
  │           └── 本月演练              → 匹配月份
  │
  ├── _cached_llm(prompt)              → LLM 合成回复
  │
  └── _detect_entity_changes()         → "明天"不含变化关键词，跳过
```

### 路径 B：事件处理（"王亮通知各班组完成消防检查，本周五前"）

```
用户消息
  │
  ▼
entry.py::handle_core()
  ├── classify()                       → "event"
  │   没有命中任何路由关键词 → 兜底
  │
  ├── _handle_event()
  │     │
  │     ├── core/event.extract()
  │     │     ├── event_detector.detect()  → 信号检测（动作+时间+实体 ≥2信号）
  │     │     │   输出: {requester:"王亮", executor:"李林骁", entities:[...], time:{deadline:"..."}}
  │     │     └── _infer_event_type()      → "instruction"
  │     │
  │     ├── event_recorder.record(event)   → log.jsonl
  │     │
  │     ├── core/context.resolve(event, user)
  │     │     → is_broadcast(TRUE) + is_leader(TRUE)
  │     │     → coordinator
  │     │
  │     ├── task/manager.create(event, context, user)
  │     │     ├── OrganizationModel.get_members("李林骁")
  │     │     │    → [苗笑天, 张志斌, 谭继衡, 杨梦卓, 陈红洁]
  │     │     ├── priority.infer_priority("消防检查")
  │     │     │    → {value:"high", reason:"安全关键词: 消防"}
  │     │     ├── 拆子任务 → 5人各1条
  │     │     └── store.save(task) → data/tasks.json
  │     │
  │     └── LLM 合成回复
  │
  └── _detect_entity_changes()         → "通知""消防"不含变化关键词，跳过
```

### 路径 C：反馈闭环（"苗笑天已完成消防检查"）

```
entry.py::handle_core()
  ├── classify()                       → "event"
  │
  ├── _handle_event()
  │     ├── core/event.extract()
  │     │     → event_type: "feedback"（短消息+实体+完成词）
  │     │
  │     ├── task/manager.update_from_event(event)
  │     │     → 匹配 executor "苗笑天" → 更新 status → check_complete
  │     │     → 全员未都完成 → "✅ 已记录：苗笑天 完成"
  │     │
  │     └── return "[Core:feedback]\n✅ 已记录：苗笑天 完成"
  │
  └── _detect_entity_changes()         → "完成"不含变化关键词，跳过
```

---

## 4. 存储层

| 路径 | 格式 | 写入者 | 读取者 |
|------|------|--------|--------|
| `data/tasks.json` | JSON array | `task/store.py` | `task_handler`, `task/manager` |
| `data/knowledge/knowledge_index.json` | JSON | `knowledge/store` | `knowledge_handler`, `knowledge/retriever` |
| `memory/events/log.jsonl` | JSONL | `event_recorder` | 各项分析器 |
| `memory/observations/*.md` | Markdown | `memory_core.save()` | `memory_core.reflect()` |
| `memory/.vector/{semantic,episodic}.index` | FAISS | `memory_core` | `memory_core` |
| `state/entity_index.json` | JSON | `entity/builder`, `entry.py::_apply_changes_direct` | `shared/entity`, `entity_resolver` |
| `state/user_profile.md` | Markdown | 手动 | `request_context` |
| `state/members/*.md` | Markdown | 手动 | `entity/builder` |
| `state/leaders.md` | Markdown | 手动 | `entity/builder` |
| `state/org.md` | Markdown | 手动 | `entity/builder` |
| `Knowledge/00-日常工作指引.md` | Markdown | 手动 | `task_handler` |

---

## 5. llm_client 调用链

```
entry.py::_cached_llm()
  └── reasoning/llm_client.py::call(prompt, system_prompt, temperature, max_tokens)
        └── _resolve_config()
              ├── LLM_API_KEY env       ← 最高优先级
              ├── DEEPSEEK_API_KEY env  ← 回退
              └── ~/.config/opencode/opencode.jsonc  ← 最后兜底
        └── urllib POST → api.deepseek.com/v1/chat/completions
              model: deepseek-chat (默认), deepseek-v4-pro (opencode 配置)
```

调用方：
- `entry.py::_cached_llm()` — 被所有 handler 使用
- `entry.py::_handle_event()` — 直接调 `_llm` (不走缓存，事件处理的 prompt 很少重复)
- `memory_core.py::_summarize()` — 聚类压缩时 LLM 提炼经验规则
- `slow_think.py::_generate_hypotheses()` — 慢思考推理
- `simulator.py::_simulate()` — 因果模拟推演
