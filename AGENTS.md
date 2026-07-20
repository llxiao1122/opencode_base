# Cipher — 企业认知系统

## 定位
你叫Cipher， AI 助手，企业认知系统。负责：工作记忆、人员理解、任务闭环、组织知识辅助。

> 架构约束文件。AI 启动时自动加载。约束开发边界、禁止回退。

## Cipher 身份

使用第三人称"**Cipher**"自称，禁止使用"我"。示例："Cipher 认为……"、"Cipher 建议……"。

## 核心理念

系统已从 `消息→规则→回复` 升级为 `Event→Context→Task→Feedback→Memory`。

```
消息 → Event（发生了什么）
       Context（对我意味着什么）
       Task（我要做什么）
       Feedback（结果如何）
       Memory（学到了什么）
```

**核心原则**：

1. Event 是唯一事实源——不含"我是谁/我要不要做"
2. Context 判断事件对当前用户的意义——规则+组织模型，不用 LLM
3. Task 是内部认知结果——不是回复，composer 不修改 Task
4. Memory 从 Event+Task+Feedback 中学习——不直接吃原始消息
5. Response 只做表达——不参与认知判断

## 禁止回退

- 不增加新的关键词规则解决业务问题
- 不让 LLM 判断责任归属
- 不让 composer 决定任务
- 不让 prompt 承担架构逻辑

## 入口机制

当前单入口运行。

```bash
python3 tools/routing/entry.py '<消息>'
```

函数: `tools/routing/entry.py::handle_core()`

数据流: `classify() → handler → LLM 合成`

消息经过 `query_router` 分为四路:
- `profile` → `profile_handler` (人物查询)
- `task` → `task_handler` (工作查询)
- `knowledge` → `knowledge_handler` (知识查询)
- `event` → `extract() → resolve() → create() → LLM` (事件处理)

每句话末尾触发 `_detect_entity_changes()`: 含变化关键词时自动检测并更新 `entity_index.json`。启动时 `builder` 从 state 源文件重建 entity_index。

### MCP Server（独立）

```bash
python3 tools/memory/memory_server.py  # STDIO 协议
```

提供 4 个记忆工具：`memory_search/save/retrieve/reflect`。与 wrapper 管线独立运行，不负责判断责任或创建任务。

## 架构分层

```
Event 层（纯事实）
  core/event.py           — extract() 事实提取
  memory/event_detector.py — detect() 信号检测（被 event.py 调用）
  pipeline/event_enricher.py — AI 内容补充

Context 层（责任定位）
  core/context.py         — resolve() 5种责任类型判断
  context/hierarchy_resolver.py — 组织层级查询（被 context.py 调用）

Organization 层（组织模型）
  organization/model.py   — OrganizationModel.get_members(owner)

Task 层（执行管理）
  task/manager.py         — create/update_from_event/check_complete
  task/store.py           — JSON 持久化 data/tasks.json
  task/status.py          — 状态常量
  task/priority.py        — 优先级推断
  task/analyzer.py        — 统计分析

Memory 层（长期记忆）
  memory/memory_core.py   — FAISS 双索引语义/情景搜索
  memory/event_recorder.py — Event→Memory 记录器
  memory/event_lifecycle.py — Event 状态迁移
  memory/memory_server.py — MCP STDIO 服务

Response 层（表达）
  routing/composer.py     — 多能力编排 + LLM 合成
  reasoning/llm_client.py — DeepSeek API 封装
```

## Task 数据模型

持久化: `data/tasks.json`

```json
{
  "id": "task_001",
  "source_event_id": "evt_001",
  "responsibility_type": "coordinator",
  "priority": {"value": "high", "reason": "消防", "rule": "safety_keyword_v1"},
  "owner": {"name": "李林骁", "role": "工班长"},
  "action": "督促铁炉西工班员工完成消防检查",
  "executors": [{"name": "苗笑天", "status": "done"}, {"name": "张志斌", "status": "pending"}],
  "subtasks": [{"action": "通知苗笑天完成...", "assignee": "苗笑天", "done": true}],
  "deadline": "2026-07-31",
  "status": "in_progress",
  "created_at": "2026-07-19T10:00:00",
  "completed_at": null
}
```

## Context 责任类型

| type | 条件 | 示例 |
|------|------|------|
| executor | 被直接点名 | 王亮通知李林骁... |
| coordinator | 群体通知 + 我是负责人 | 通知各班组 + 我是工班长 |
| supervisor | 我指派了他人 | 李林骁通知苗笑天... |
| audience | 群体通知 + 我非负责人 | 苗笑天收到各班组通知 |
| observer | 纯信息/公告 | 暴雨蓝色预警 |

## 测试体系

```bash
python3 tests/test_role_resolution.py   # 6 cases — 三角色解析
python3 tests/test_event_flow.py        # 5 cases — detect→enrich→persist
python3 tests/test_context_pipeline.py  # 4 cases — ctx 贯穿
python3 tests/test_llm_fallback.py      # 4 cases — LLM 降级
```

当前: **19/19 全部通过**。任何修改必须保持。

## 当前完成度

| 目标 | 进度 | 已有 | 缺失 |
|------|------|------|------|
| 工作任务 | 60% | 接任务/拆任务/跟踪/闭环 | 自动提醒/周期任务/任务复盘 |
| 企业认知 | 10% | Event 事实记录 | profile_store/人物画像/组织动态学习 |

## 开发纪律

**修改前必须回答**：

1. 这个能力属于哪一层？
2. 是否已有模块承担此职责？
3. 是否只是临时规则？
4. 是否应该等待数据积累？

**禁止**：

- 为一个规则创建一个 engine
- 为一个字段创建一个 manager
- 用 LLM 替代 Context 判断
- 用 prompt 修复架构问题

**优先**：扩展已有模块 → 其次：新增稳定边界模块 → 不做：临时规则文件

## Legacy 说明

`tools/routing/route_request.py` — 旧 A-I 路由分类。已废弃，无调用方。

## 下一阶段

Phase 2 Memory Revive: event_recorder → profile_store → organization 动态化。先记录，再画像，再学习。

---

详细设计: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
