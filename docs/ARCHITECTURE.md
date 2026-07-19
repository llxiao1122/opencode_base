# 企业认知系统 — 完整架构设计

> 本文档为完整设计参考。AI 启动时加载 `AGENTS.md` 作为架构约束，本文档提供细节。

## 架构演进

```
Phase 0 (最初)    消息 → 规则 → 回复                    chatbot
Phase 1.7 (重构)  消息 → Event → Context → Task → Reply   pipeline
Phase 1.8 (当前)  Event → Context → Task → Feedback → Memory  enterprise brain
```

核心转变：从"消息驱动规则系统"到"事件驱动的企业认知系统"。

---

## 五层模型

```
钉钉消息
    │
    ▼
Event 层 ──────── 纯事实提取。回答"发生了什么"。
    │              输入: 原始文本
    │              输出: {event_type, actors, action, target, deadline, raw}
    │              禁止: 含"我是谁/我应该做什么"
    │
    ▼
Context 层 ────── 责任定位。回答"这对我意味着什么"。
    │              输入: Event + 当前用户 + 组织模型
    │              输出: {my_position: {type, owner}, required_action: {verb, scope}, reason}
    │              判断: 5种 ResponsibilityType
    │              方式: 规则+组织模型，禁止 LLM
    │
    ▼
Task 层 ───────── 执行管理。回答"我要做什么"。
    │              输入: Event + Context
    │              输出: {id, owner, executors[], subtasks[], deadline, status, priority}
    │              能力: 创建/拆分/跟踪/闭环/分析
    │              方式: 规则+模板，含子任务拆分
    │
    ▼
Feedback 层 ───── 结果闭环。回答"完成了吗"。
    │              输入: 反馈消息
    │              动作: 匹配executor→更新status→全员done→自动关闭
    │
    ▼
Memory 层 ─────── 长期学习。回答"学到了什么"。
    │              输入: Event记录 + Task结果 + Feedback
    │              输出: PersonProfile / OrganizationModel
    │              方式: 事实积累→行为模式→人物画像
    │
    ▼
Response 层 ───── 表达。回答"怎么说"。
    │              输入: Task + Context
    │              输出: 自然语言回复
    │              方式: LLM合成，不参与认知判断
```

---

## Event 层

### 数据结构

```json
{
  "id": "evt_001",
  "event_type": "instruction|notification|report|inspection|incident|feedback",
  "time": {"deadline": "2026-07-31"},
  "source": "钉钉",
  "actors": [{"name": "王亮", "role": "安全管理岗", "position": "requester"}],
  "action": {"type": "notify", "summary": "完成郑轨学苑学习"},
  "target": "各班组",
  "confidence": 0.93,
  "raw": "王亮在钉钉群各班组督促..."
}
```

### 关键模块

| 模块 | 职责 | 方式 |
|------|------|------|
| `core/event.py::extract()` | 统一入口，事实提取 | 调用 detect + enricher |
| `memory/event_detector.py::detect()` | 信号检测（≥2信号触发） | 规则，6种信号 |
| `pipeline/event_enricher.py::enrich_event()` | AI内容补充（section→LLM提取） | LLM辅助 |

### 禁止

- 含"我是谁/我的责任/我要做什么"
- event_type 判断用 LLM

---

## Context 层

### 数据结构

```json
{
  "event_id": "evt_001",
  "my_position": {
    "type": "coordinator",
    "owner": "李林骁",
    "description": "工班长，负责落实本班组"
  },
  "required_action": {"verb": "督促", "scope": "铁炉西工班员工"},
  "reason": "王亮通知各班组，李林骁为铁炉西工班工班长"
}
```

### ResponsibilityType

| type | 条件 | 示例 |
|------|------|------|
| executor | 被直接点名 | 王亮通知李林骁... |
| coordinator | 群体通知 + 我是负责人 | 通知各班组 + 我是工班长 |
| supervisor | 我指派了他人 | 李林骁通知苗笑天... |
| audience | 群体通知 + 我非负责人 | 苗笑天收到各班组通知 |
| observer | 纯信息/公告 | 暴雨蓝色预警 |

### 关键模块

| 模块 | 职责 |
|------|------|
| `core/context.py::resolve()` | 5种责任类型推断 |
| `context/hierarchy_resolver.py` | 组织层级查询 |

---

## Organization 层

### 当前实现

```python
organization/model.py::OrganizationModel
  - get_members(owner) → list     # 获取团队成员
  - get_leader(member) → str      # 查询直属上级
  - get_team_name(owner) → str    # 查询班组名称
```

内部字典实现。未来从 `state/` 动态加载，支持人工调整。

### 目标

```
静态 TEAM_MAP → OrganizationModel 接口 → 动态组织模型
```

---

## Task 层

### 完整数据结构

```json
{
  "id": "task_001",
  "source_event_id": "evt_001",
  "responsibility_type": "coordinator",
  "priority": {"value": "high", "reason": "消防", "rule": "safety_keyword_v1"},
  "owner": {"name": "李林骁", "role": "工班长"},
  "action": "督促铁炉西工班员工完成消防检查",
  "executors": [
    {"name": "苗笑天", "status": "done"},
    {"name": "张志斌", "status": "pending"}
  ],
  "subtasks": [
    {"action": "通知苗笑天完成消防检查", "assignee": "苗笑天", "done": true},
    {"action": "汇总铁炉西工班完成情况", "assignee": "李林骁", "done": false}
  ],
  "deadline": "2026-07-31",
  "status": "in_progress",
  "created_at": "2026-07-19T10:00:00",
  "completed_at": null
}
```

### 状态流转

```
pending → in_progress → completed
                ↑
          feedback loop:
            executor pending → done → all_done → task completed
```

### 关键模块

| 模块 | 职责 |
|------|------|
| `task/manager.py::create()` | 从Event+Context创建任务 |
| `task/manager.py::update_from_event()` | feedback事件→更新executor→检查闭环 |
| `task/store.py` | JSON持久化 |
| `task/status.py` | 状态常量 |
| `task/priority.py` | 安全关键词→high/normal |
| `task/analyzer.py` | 统计分析（区分executed/owned） |

---

## Feedback 层

### 数据流

```
feedback消息 → core/event.extract() → event_type=feedback
  → task/manager.update_from_event()
    → 匹配executor → 更新status → check_complete
    → 全员done → store.close() → 写completed_at
```

### 当前能力

- 识别短消息 + 实体 + 完成关键词 → feedback
- 匹配活跃任务中的executor
- 全员完成自动闭环

---

## Memory 层

### 当前状态

| 模块 | 状态 | 职责 |
|------|------|------|
| `memory/memory_core.py` | ACTIVE | FAISS双索引搜索 |
| `memory/memory_server.py` | MCP | 4个工具 |
| `memory/event_lifecycle.py` | ACTIVE | Event生命周期 |
| `memory/event_recorder.py` | 刚刚复活 | Event→Memory记录 |
| `memory/profile_store.py` | 未建设 | 人物画像 |

### Phase 2 蓝图

```
event_recorder: 每个Event写入 log.jsonl
      ↓
profile_store: 从Event+Task统计中提取人物行为模式
      ↓
organization/model: 从静态字典升级为动态组织模型
```

---

## Response 层

### 关键模块

| 模块 | 职责 | LLM |
|------|------|-----|
| `routing/composer.py` | 多能力编排+合成 | 合成时调用 |
| `reasoning/llm_client.py` | DeepSeek API封装 | 无 |

### 原则

- composer 不决定任务
- LLM 不判断责任归属
- prompt 不承载架构逻辑

---

## 目录结构

### 当前（Phase 1.8）

```
tools/
├── core/           # Event/Context/Task 核心
├── task/           # Task 管理
├── organization/   # 组织模型
├── memory/         # 记忆引擎
├── routing/        # 路由/编排/回复
├── context/        # 上下文构建
├── pipeline/       # 事件增强
├── reasoning/      # LLM 客户端
├── guard/          # 日志/安全
├── parse/          # 文档解析
├── extract/        # AI 提取
└── work/           # 工作查询

state/              # 组织数据
data/               # 运行时数据
memory/             # 事件存储
```

### 目标（Phase 5）

```
tools/
├── core/           # 五层核心
├── event/          # 事件检测提取
├── organization/   # 组织模型
├── task/           # 任务管理
├── memory/         # 记忆引擎
├── response/       # 回复合成
└── router/         # 路由（遗留）
```

---

## Phase 演进路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | Task Foundation: 创建/拆分/持久化 | ✅ |
| Phase 2 | Feedback Loop: 闭环 | ✅ |
| Phase 3 | Task Intelligence: priority/analyzer | ✅ |
| Phase 4 | Architecture Doc: AGENTS.md + event_recorder | 🔄 当前 |
| Phase 5 | Memory Revive: profile_store + org动态化 | ⬜ |
| Phase 6 | Cleanup: DEAD模块删除 + 目录重组 | ⬜ |

---

## 迁移记录

### 从旧架构迁移到 core/

| 旧模块 | 处理方式 |
|--------|---------|
| `wrapper.py::handle()` | 保留兼容，逐步废弃 |
| `route_request.py` | Legacy，仅旧管线使用 |
| `instruction_resolver.py` | 降级为 context.py 内部组件 |
| `hierarchy_resolver.py` | 降级为 context.py 内部组件 |
| `_TEAM_MAP` | 替换为 organization/model.py |

### 已确认 DEAD（待删除）

| 文件 | 原因 |
|------|------|
| `context_builder.py` | 从未被调用 |
| `keyword_discovery.py` | 导入路径损坏 |
| `plugins/` 多个独立脚本 | 无调用方 |
| `dingbot/send_msg.py` | 含硬编码 token |

---

## 测试

```bash
python3 tests/test_role_resolution.py   # 6 cases
python3 tests/test_event_flow.py        # 5 cases
python3 tests/test_context_pipeline.py  # 4 cases
python3 tests/test_llm_fallback.py      # 4 cases
```

当前：19/19 全部通过。
