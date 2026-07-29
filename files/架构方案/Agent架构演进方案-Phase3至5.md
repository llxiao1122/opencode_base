# Cipher Agent 架构演进 — Phase 3→4→5

> 生成日期：2026-07-25 | 基于 Phase 0-2 FAISS+置信度+决策学习器
> 
> 从"固定路由管线"到"真正的 Proactive Agent"的完整路径

---

## 现状基线（Phase 0-1-2）

```
入口 → classify (FAISS) → 5层管线 (ingress→intent→reason→execute→respond)
       + decision_log.jsonl (每次追加)
       + learner (离线 requery/否定检测 → 路线种子更新)
```

- 95 个测试，全部通过
- 4 条固定路由（event/task/profile/knowledge）
- 置信度 4 阈值（CONFIRM/EXECUTE/HEDGE/HIGH）
- 钉钉推送 bypass 管线，不留记录

---

## Phase 3 — Agentic Pipeline（工具选择Agent）

**定位：** 用 LLM Agent 替换固定 4 路由管线。核心能力是"理解意图 + 选工具 + 执行"。

### 架构变化

```
当前:                           Phase 3:
                                    ┌─── 规则快速路径 ───┐
                                    │ task/knowledge/   │
                                    │ profile 高频请求   │
入口 → route → 5层管线              │ (FAISS ≥0.7 直通)  │
                                    └────────┬──────────┘
                                             │ 其他/模糊请求
                                             ▼
                                      Agent Engine
                                      (1 次 LLM)
                                             │
                                             ▼
                                      Skills Registry
                                             │
                                             ▼
                                    execute_tool + decision_log
```

### 新建文件

| 文件 | 职责 |
|------|------|
| `skills/agent/registry.py` | Skills Registry — 工具注册表 + 参数 schema 校验 |
| `skills/agent/engine.py` | Agent 核心 — LLM JSON 输出 + 解析 + 容错链 |
| `skills/agent/skills/notification.py` | 钉钉推送 skill — 发消息 + 写 observation |
| `skills/agent/skills/event_record.py` | 事件记录 skill |

### 修改文件

| 文件 | 改动 |
|------|------|
| `skills/routing/entry.py` | handle_core 分叉：规则快速路径 vs Agent 路径 |
| `skills/core/pipeline.py` | 标记弃用 |

### 结构化 Agent 输出 JSON

```json
{
  "thought": "用户希望将台风红霞方案发送至钉钉群",
  "intent": "notification",
  "tool": "notification_push",
  "params": {
    "title": "台风红霞方案宣贯",
    "content": "...",
    "target": "dingtalk_group"
  }
}
```

### Skills Registry 契约

```python
TOOL_REGISTRY = {
    "notification_push": {
        "description": "推送消息到钉钉群",
        "params_schema": {
            "title": {"type": "str", "required": True},
            "content": {"type": "str", "required": True},
            "target": {"type": "str", "default": "dingtalk_group"},
        },
        "handler": "skills.agent.skills.notification.handle",
    },
    "task_query": {
        "description": "查询当前任务/待办",
        "params_schema": {
            "scope": {"type": "str", "default": "today"},
        },
        "handler": "skills.routing.task_handler.handle",
    },
}
```

### 容错链（永不崩溃）

```
LLM 返回 JSON
  │
  ├── JSON 解析失败 → 正则提取 → 失败 → knowledge_retrieve 兜底
  ├── tool 未注册 → knowledge_retrieve 兜底
  ├── params 缺必要字段 → 追问补全
  ├── tool 执行异常 → 回复错误摘要
  └── 全部正常 → 执行 + 返回
```

### 与 Phase 2 的关系

Phase 2 的 `decision_log.jsonl` + learner 可直接复用：

```
Agent 执行 → logger.append() → decision_log.jsonl
                                ↓
                           learner (requery + 否定检测)
                                ↓
                           发现常见意图 → 注入 Agent prompt few-shot
```

---

## Phase 4 — Reflective Agent（反思Agent）

**定位：** Phase 3 能"选工具执行"，Phase 4 能"执行完再反思—记录+学习+提炼模式"。

一句话进来，Agent 同时做 4 件事：
1. **输出回复**
2. **记录事实**（tasks.json / observation_store）
3. **反思模式**（跨会话提炼规律）
4. **自我修正**（发现错误自动更新行为）

### 新增结构

```
Agent Engine
  ├── 工具执行
  ├── 写 observation
  ├── 写 decision_log
  ├── 触发 Refection Loop ─────────────────────┐
  │    1. 这次执行有什么异常？                   │
  │    2. 能提炼什么模式？                      │
  │       (某人固定时间做某事？某类任务总在周一？)  │
  │    3. 上次类似情况用户纠正过什么？            │
  │    4. 有什么可主动提醒用户的？               │
  └─────────────────────────────────────────────┘
        结果写入:
        - pattern 层 observation
        - 用户 profile
        - Agent prompt 的 few-shot 样本库
```

### 用例

```
你说: "苗笑天消防检查已经完成了"

Phase 4 Agent:
  intent = "task_feedback"
  
  执行:
    1. tasks[t].status = "completed" → tasks.json
    2. reply = "已记录"
    3. reflect:
       - 苗笑天消防类任务连续三次准时
       - 提炼 pattern: "苗笑天 → 消防类任务高执行者"
       - 写入 observation_store pattern 层
    4. suggestion: "下次消防类任务优先分配苗笑天"
```

### 前提条件

当前数据质量不足以支撑 Phase 4：

| 问题 | 现状 | 清理要求 |
|------|------|---------|
| observer 噪音任务 | 30+ 条 "相关任务" | 删除或合并 |
| tasks.json 重复 | 同一事件多次记录 | 去重 dedup |
| observation 噪音 | 无结构 | 统一 schema |

---

## Phase 5 — Proactive Agent（主动Agent）

**定位：** 不等用户问，自己"醒过来"找事做。

### 设计原则

**规则哨兵 + LLM 判断员**模式，不用"全知 Agent 自主决策"。

```
定时循环 (每 N 小时):
  1. 规则哨兵扫描:
     - tasks.json: 有即将到期的任务？
     - 天气 API: 有台风/暴雨预警？
     - 日历: 周期性事项该做了？（消防巡检/物资盘点/培训签到）
     - 异常检测: 某人任务量突然增加？
  
  2. 触发条件满足 → 调 LLM 生成决策:
     - 这件事值不值得通知？
     - 通知谁？用什么语气？
     - 是否和其他任务冲突？
  
  3. 执行:
     - 低频/安全 → 直接推送钉钉
     - 高风险 → 先推给你确认
  
  4. 记录:
     - observation_store → proactive_action
     - decision_log
```

### 主动场景

| 触发条件 | 动作 | 风险 |
|---------|------|------|
| 台风红色预警 | 自动推送防汛检查清单到钉钉群 | 低 |
| 任务 deadline 今天到期但未完成 | 提醒执行人 + 抄送工班长 | 低 |
| 某人同时有 5+ 活跃任务 | 建议分担 | 中 |
| 月底物资盘点未做 | 推送通知 + 生成 checklist | 低 |
| 苗笑天连续三次准时完成任务 | 推送"建议下次优先分配" | 低 |

### 边界

- **不做的：** 修改任务、代为决策、支出审批、人员评优
- **需要确认的：** 涉及跨班组、涉及费用、涉及人员调动
- **自动做的：** 提醒、通知、查天气、查状态、生成模板

---

## 开放领域架构（远期的思考）

当业务场景扩展到不受铁炉西工班边界约束时。

### 核心差异

| 维度 | 封闭领域（铁炉西） | 开放领域 |
|------|------------------|---------|
| 工具数量 | ≤15，可穷举 | 不确定，动态注册 |
| 用户意图 | 4 种 | 无限 |
| 实体范围 | 5 人 + 固定库区 | 不确定 |
| 错误成本 | 改一下就行 | 可能涉及财务/法律 |
| LLM 幻觉 | 规则兜底 | 需要多层验证 |

### 架构变化

```
入口 → Context Builder（不限领域）
         │
         ▼
    意图理解层 (LLM + FSM)
         │
         ▼
    ┌──────────────┐
    │ Skill Hub    │ ← 动态注册，不在 code 中写死
    │ (Plugin Store)│
    └──────┬───────┘
           │ LLM 选 skill
           ▼
    ┌──────────────┐
    │ Verification │ ← 最关键的新增层
    │ - 参数校验   │
    │ - 权限检查   │
    │ - 成本预估   │
    │ - 人工确认   │（高风险动作必须）
    └──────┬───────┘
           │
           ▼
    执行层（可回滚 / 补偿事务）
           │
           ▼
    ┌──────────────┐
    │ 记忆系统     │ ← 必须结构化
    │ - 关系型 DB  │（不是 JSON 文件）
    │ - 图数据库   │（实体关系查询）
    │ - 行为偏好   │（长期演化画像）
    └──────────────┘
```

### 三大关键迁移

**1. Skill Hub 代替固定路由**
```python
# 当前: if/else 分 4 条路由
# 开放: 全动态注册
hub.register({
    "id": "weather_query",
    "description": "查询未来天气",
    "handler": "plugins.weather.handle",
})
LLM 每次从 hub 中选
```

**2. Verification Layer 代替信任**
```python
用户: "帮我订一张明天去北京的机票"
验证层:
  1. 角色能报销机票？→ 查权限表
  2. 预算够？→ 查预算系统
  3. 需多人审批？→ 查流程规则
  4. 哪家航司有协议价？→ 查供应商表
  任一不明确 → 追问，不执行
```

**3. 图数据库代替 JSON 文件**
```
当前: tasks.json → 只能按 id 查
开放需要: 用户-创建->任务
          用户-拥有->角色
          角色-包含->权限
          任务-关联->设备
          设备-位于->库区
  → Neo4j / Postgres + 关系模型
```

### 迁移建议

不做开放领域框架。**先把手头封闭领域跑到 Phase 5，再抽象 Skill Hub。** 在没有具体业务需求驱动下提前做开放领域，容易过度工程。

---

## 阶段路线图总结

```
Phase 0-2 ✅ (FAISS + 置信度 + 决策学习器)
     ↓
Phase 3 🔜 (Agent + Skills Registry + 结构化JSON输出)
     ↓
Phase 4 (Reflective Agent + 模式提炼)
     ↓
Phase 5 (Proactive Agent + 规则哨兵)
     ↓
开放领域 (Skill Hub + Verification + 图数据库)
```

| 阶段 | 核心新能力 | 对用户的感知变化 |
|------|-----------|----------------|
| Phase 3 | LLM 理解意图 → 选工具执行 | 之前误分类的问题减少 |
| Phase 4 | 执行后反思 → 提炼模式 → 主动建议 | Agent 开始"多想几步" |
| Phase 5 | 定时自醒 → 主动推送 | Agent 不等你问就做事 |
| 开放领域 | 领域无关 + 动态 skill | 什么业务都能接 |
