# skills/ — Cipher 工班 AI 工具集

按架构分层组织，对应"一个大脑 + 一个 skill 体系"（f77656b 落地）。

> 定位：**人读参考手册**，不承担运行时职责（Cipher 的 Agent 不读取本文件）。运行时行为以代码为准；AI 执行约束见 AGENTS.md。

---

## 路由层 (Routing) — `skills/router/`

入口判定，纯规则无 LLM（确定性优先）。

| 文件 | 职责 |
|------|------|
| **`faiss_router.py`** | `classify()` 返回 (route, confidence)，值域：task_query/profile_query/knowledge_retrieve/event/unknown；`extract_slots()` 提取槽位（has_correction/has_time/has_person/has_knowledge/has_event） |
| `entity_resolver.py` | 实体名解析（resolve_entities，缓存于内存） |
| `route_index.py` | 路由索引构建（种子/分节档案），FAISS worldview.index 的构建入口 |
| `route_config.json` / `route_seeds.json` | 路由规则与种子配置 |

## 记忆层 (Memory) — `skills/memory/`（大脑）

| 文件 | 职责 |
|------|------|
| **`worldview.py`** | 知识基线（大脑主体）：实体档案 `data/state/worldview/entities/*.md`（已 git 版本化）、index.json、FAISS 分节向量（vector/，运行时重建）、`search()` 混合检索（向量 + BM25 兜底）、`update_entity()` 学习闭环、`detect_novel_entities()` |
| **`world_query.py`** | 统一查口：系统唯一对外查询入口，按路由分发（任务/档案/知识），`query(text)` |
| **`recorder.py`** | 学习回路写口：record() → ringbuf（`_ringbuf.json`）+ pending 计数 + observations；`skip_learning=True` 时仅写 observations（查询类走此路径，不进学习回路） |
| `correction_store.py` | 纠错库：append/load_recent，纠错输入（has_correction 槽位）记录进此 |
| `observation_store.py` | 观察日志：`data/memory/observations/`，规则分类（_classify_semantic 纯规则，无 LLM） |
| `detect/` | 实体/事件检测辅助 |

## 推理层 (Agent) — `skills/agent/`

LLM 选工具 + registry 执行（仅写操作与低置信输入走此路径）。

| 文件 | 职责 |
|------|------|
| **`engine.py`** | `run()`：LLM 调用 → `_parse_decisions` 解析工具决策 → validate → execute；失败降级 `_fallback_search` |
| **`registry.py`** | 工具注册表（11 个）：task_query/knowledge_retrieve/profile_query/weather_query（查询类）；notification_push/event_record/task_create/task_feedback/org_lookup/correction_feedback/reminder_set（写操作）；`list_tools()`/`validate_params()`/`execute()` |
| `handlers/` | 各工具处理函数（task_query/profile_query/knowledge_retrieve/weather_query/notification_push/event_record/task_create/task_feedback/org_lookup/correction_feedback/reminder_set） |
| `reflector.py` | 异步反思（工具使用后触发，daemon 线程） |
| `few_shots.json` | LLM 工具决策示例 |

## 基础设施 (Shared) — `skills/shared/`

| 文件 | 职责 |
|------|------|
| **`embedder.py`** | 文本嵌入（ONNX bge-small-zh-int8，缺依赖时 FallbackEmbedder 512 维） |
| `schema.py` | RequestContext/CT（置信阈值） |
| `entity.py` | 用户解析（resolve_user，组织模型） |
| `llm_cache.py` | LLM 调用缓存（_cached_llm，TTL） |
| `push_queue.py` | 推送队列（钉钉） |
| `task_format.py` / `time_parse.py` | 任务格式化 / 时间解析 |
| `path.py` / `async_task.py` | 路径常量 / 后台任务 |

## 组织模型 (Organization) — `skills/organization/`

`model.py`：团队/成员查询（SSOT 读 worldview 实体档案的 `**工班成员**` 标记）。

## 触发器与通知

| 位置 | 职责 |
|------|------|
| `skills/trigger/daemon.py` | 主动巡检线程（entry 启动，check_interval 3600s） |
| `skills/plugins/dingbot/send_msg.py` | 钉钉机器人推送（DINGTALK_BOT_TOKEN） |

## 生产脚本 (Scripts) — `scripts/`（仅 VPS cron 运行）

| 文件 | 职责 |
|------|------|
| `prepare_daily.py` | 每日 08:45 生成当日工作安排（值班轮序锚点） |
| `deliver.py` | 每分钟检查推送队列（push_queue.json）→ 钉钉 |
| `rebuild_worldview.py` | 世界观实例集重建（人员/文档/系统/区域/组织，纯规则无 LLM） |

## LLM 客户端 — `skills/core/llm_client.py`

统一 LLM 封装（urllib + OpenAI 响应格式），provider：deepseek（默认，`DEEPSEEK_API_KEY`）/ zhipu / gemini；配置读 `~/.config/opencode/opencode.jsonc` 或 `.opencode/opencode.jsonc`（支持 `{env:VAR}` 占位）；生产 VPS 用 `LLM_PROVIDER=zhipu` + `ZHIPU_API_KEY`（crontab 环境变量）。

---

## 依赖图

```
entry.py (handle_core)
   ├─ classify()/extract_slots()  → skills/router/faiss_router.py
   ├─ 高置信且非 event → _fast_dispatch → handlers/*（确定性规则）
   ├─ 其余 → agent/engine.py → LLM 选工具 → registry.execute() → handlers/*
   └─ 记录阶段：has_correction → correction_store；事件 → recorder（学习回路）；
                 查询（task_query/profile_query/knowledge_retrieve/weather_query）→ recorder(skip_learning=True) 仅留轨迹

统一查口 world_query.query(text)
   ├─ 任务/日程 → handlers/task_query（规则路径）
   ├─ 人员档案 → handlers/profile_query
   └─ 制度/流程 → handlers/knowledge_retrieve → worldview.search（FAISS+BM25）→ Knowledge/ 兜底

记忆：recorder → ringbuf/pending → worldview.update_entity（学习闭环）
推送：push_queue → scripts/deliver.py → plugins/dingbot
```
