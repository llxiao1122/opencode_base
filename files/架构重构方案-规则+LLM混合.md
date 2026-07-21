# Cipher 架构重构 — 规则+LLM 混合方案

> 生成日期：2026-07-21 | 基于 v2.5

---

## 1. 核心转变

```
从: 规则驱动的办公自动化工具 (workflow automation)
到: 确定性规则 + LLM 理解 = 持续学习的企业智能体 (enterprise agent)
```

### 原则

| 层 | 谁负责 | 为什么 |
|----|--------|--------|
| 确定性计算 | 规则代码 | 值班人、日期匹配、固定工作——不能错 |
| 语义理解 | LLM (一次调用) | 去重、合并、记录意图——规则永远覆盖不全 |
| 知识检索 | FAISS (向量) | 制度库已有索引，不改 |
| 表达合成 | LLM | 现有设计，不改 |

---

## 2. 新架构分层

```
┌─────────────────────────────────────────────────────────────────┐
│ 用户消息                                                       │
└─────────────┬───────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│ entry.py::handle_core()                                        │
│                                                                 │
│  ┌────────── query_router.classify() ──────────┐               │
│  │  task 关键词? ──→ task_handler (规则路径)     │               │
│  │  knowledge?  ──→ knowledge_handler (规则路径) │               │
│  │  profile?    ──→ profile_handler  (规则路径)  │               │
│  │  其余        ──→ event → Observation Manager  │               │
│  └──────────────────────────────────────────────┘               │
└─────────────┬───────────────────────────────────────────────────┘
              │
    ┌─────────┴──────────────┐
    ▼                        ▼
┌──────────┐    ┌───────────────────────────────────────┐
│规则路径   │    │ LLM 路径 (Observation Manager)        │
│          │    │                                        │
│task      │    │ 1. extract → 基础事件                  │
│handler   │    │ 2. Reasoning Engine (1 次 LLM)         │
│          │    │    输入: 消息 + 近期任务 + 实体列表     │
│knowledge │    │    输出: 结构化决策 JSON               │
│handler   │    │      {action, task, question, contacts}│
│          │    │ 3. 代码执行: 写 tasks.json / 合并/删除 │
│profile   │    │ 4. LLM 合成回复                        │
│handler   │    │                                        │
│          │    │ Reflection Engine (定时)               │
└──────────┘    │   → LLM 扫描 events+tasks+observations │
                │   → 提炼模式 → 写记忆 → 生成画像        │
                └───────────────────────────────────────┘
```

---

## 3. 各层详解

### 3.1 快速路径（规则，保留不改）

调用场景：query_router 命中关键词的查询（"今天工作"、"暴雨怎么应对"、"张志斌怎么样"）

| 模块 | 职责 | 状态 |
|------|------|------|
| `task_handler.py` | 组装固定工作+动态任务 | 保留 |
| `knowledge_handler.py` | FAISS 搜索 + LLM 合成 | 保留 |
| `profile_handler.py` | 画像 + 记忆查询 + LLM 合成 | 保留 |

### 3.2 LLM 路径（新增）

调用场景：query_router 未命中的消息（工作记录、模糊对话、带实体/时间的陈述）

#### Observation Manager — `tools/observation/manager.py`

类型：新增

```
def handle(user_input, event, user):
    1. _log_raw(user_input)              → memory/events/log.jsonl
    2. decision = ReasoningEngine.think() → 结构化 JSON
    3. _execute(decision)                → 写 tasks.json
    4. return _compose(decision)         → LLM 合成回复 → 返回用户
```

关键函数：
- `_log_raw()` — 原始消息永久落盘
- `_execute()` — 根据 LLM 决策执行 CRUD
- `_compose()` — 调用 LLM 将结构化结果转为自然语言回复

#### Reasoning Engine — `tools/reasoning/engine.py`

类型：新增

```
def think(user_input, recent_tasks, entities, org_context):
    一次 LLM 调用，输入：
    {
        "message": "下午三点陈红洁去西流湖站进行厂验",
        "recent_tasks": [
            {"id": "t1", "action": "明天陈红洁参加灭火器厂验在西流湖地铁站"}
        ],
        "entities": ["陈红洁", "李林骁"],
        "org": "李林骁 → 工班长 → 铁炉西工班"
    }

    输出结构化 JSON:
    {
        "action": "merge",          // create | update | merge | query | ignore
        "target_task_id": "t1",     // 去重/更新目标
        "merged_text": "今天下午三点陈红洁参加灭火器厂验，西流湖地铁站",
        "missing_info": null,       // 缺失信息追问（有具体时间则 null）
        "relevant_contacts": [],    // 相关联系人
        "confidence": 0.9
    }
```

LLM prompt 设计：
```
你是 Cipher Reasoning Engine。基于提供的上下文，判断用户消息的意图并输出结构化 JSON。

规则：
- 如果消息是对已有任务的补充（时间/地点/人员变更），选择 merge
- 如果消息是全新的工作记录，选择 create
- 如果消息是纯聊/无关，选择 ignore
- 合并时保留旧任务的主体内容，只补充新消息中的缺失信息
- missing_info: 如果任务缺少关键信息（时间/人员/地点），输出缺失项，否则 null
```

#### Reflection Engine — `tools/reflection/engine.py`

类型：新增

```
def reflect(since_days=7):
    1. 扫描 memory/events/log.jsonl (近 N 天)
    2. 加载 data/tasks.json (状态变更)
    3. 加载 memory/observations/
    4. LLM 提炼
    
    LLM prompt:
    "基于以下 N 天的事件记录，提炼:
     1. 用户行为模式（什么类型任务最多、什么时段最忙）
     2. 团队协作模式（谁最常配合、谁经常被指派）
     3. 值得记录的通用经验规则
     4. 人员能力/特质观察
    
    输出 JSON: {patterns, team_dynamics, rules, profiles}"
    
    → 写入 memory/observations/people/{name}.md
    → 写入 Knowledge/经验提炼.md
```

---

## 4. 文件变更清单

### 新增

| 文件 | 行数(估) | 职责 |
|------|---------|------|
| `tools/observation/manager.py` | ~80 | 统一入口：日志→LLM决策→执行→回复 |
| `tools/reasoning/engine.py` | ~120 | 一次 LLM 调用完成理解+决策 |
| `tools/reflection/engine.py` | ~100 | 定期 LLM 扫描提炼 |

### 废弃（保留文件，不再接入管线）

| 文件 | 原因 |
|------|------|
| `tools/shared/semantic.py` | LLM 替代语义匹配 |
| `tools/routing/query_router.py` | 路由判断交给 LLM |
| `tools/core/event.py::_infer_event_type()` 语义回退部分 | LLM 替代 |

### 精简

| 文件 | 改动 |
|------|------|
| `entry.py` | 移除 `_check_record_intent`, `_merge_similar_task`, `_detect_missing_info`, `_select_better_info` (~100 行); handle_core 重构为规则/LLM 两条路径 |

### 保留不变

| 文件 | 用途 |
|------|------|
| `task_handler.py` | 快速路径——确定性数据组装 |
| `knowledge_handler.py` | 快速路径——知识检索 |
| `profile_handler.py` | 快速路径——人物查询 |
| `task/store.py` | Task CRUD |
| `task/manager.py` | Task 生命周期 |
| `task/status.py`, `task/priority.py` | 状态/优先级常量 |
| `organization/model.py` | 组织数据 |
| `entity/builder.py` | 实体索引构建 |
| `memory/memory_core.py` | FAISS 检索 |
| `memory/event_recorder.py` | Event 记录 |
| `memory/event_lifecycle.py` | 事件状态迁移 |
| `memory/change_detector.py` | 实体变化检测 |
| `reasoning/llm_client.py` | LLM API 封装 |
| `core/event.py::extract()` | 事件基础提取 |
| `core/context.py::resolve()` | 5种责任类型 |
| `shared/entity.py` | 实体查询 |
| `context/request_context.py` | 用户上下文 |

---

## 5. 与 AGENTS.md 的冲突

| 原禁止 | 新设计 | 说明 |
|--------|--------|------|
| "不让 LLM 判断责任归属" | LLM 自由理解角色关系 | 需要从 AGENTS.md 移除 |
| "不让 composer 决定任务" | composer 被 Observation Manager 替代 | 移除 |
| "不让 prompt 承载架构逻辑" | Reasoning Engine 的 prompt 承载了意图判断 | 这是刻意的设计选择 |

需要在 AGENTS.md 建立新的约束：
- **LLM 可以判断语义关系**（去重、合并、补充信息）
- **LLM 不能做确定性计算**（日期数学、值班轮序、固定工作匹配）
- **代码执行 LLM 的决策**，不做自主判断

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 返回非法 JSON | Python 容错：正则提取 + 重试 + 降级到旧规则路径 |
| LLM 判断失误 | 失败时退回到当前规则路径 |
| LLM 延迟 | 仅 rule-miss 路径调用，task/knowledge 快速路径 0ms 不变 |
| 值班人算错 | 不变——任务数据处理仍在代码中，不交给 LLM |
| 成本增加 | 仅 rule-miss 消息触发 LLM，高频的"今天工作"不走 LLM |

---

## 7. 实施步骤

1. 创建 `tools/reasoning/engine.py`
   - 设计 LLM prompt 模板
   - 实现 `think()` 函数
   - 结构化 JSON 输出 + 容错

2. 创建 `tools/observation/manager.py`
   - 实现日志记录 + Reasoning Engine 调用 + 决策执行 + 回复合成

3. 重构 `entry.py::handle_core()`
   - 规则路径 → 保留 task/knowledge/profile handler
   - event 路径 → 调用 Observation Manager
   - 移除 `_check_record_intent`, `_merge_similar_task`, `_detect_missing_info`, `_select_better_info`

4. 创建 `tools/reflection/engine.py`
   - 实现定期扫描 + LLM 提炼

5. 更新 AGENTS.md
   - 移除 2 条禁止规则
   - 新增 3 条混合架构约束

6. 删除/标记废弃
   - `semantic.py` 不再调用
   - `query_router.py` 保留但标记废弃

7. 测试
   - 现有 13 个测试确保不回归
   - 新增 LLM 决策场景测试

---

## 8. 架构全景图

```
                 ┌─────────────────────────────────┐
                 │        entry.py (精简)           │
                 │   规则路径 / LLM路径 分发         │
                 └───────┬─────────────┬───────────┘
                         │             │
             规则路径    │             │    LLM 路径
         ┌───────────────┤             ├──────────────────┐
         ▼               ▼             ▼                  ▼
    task_handler   knowledge     Observation          Reflection
    (查询工作)     handler       Manager              Engine
         │         (查制度)     (新增)                (新增)
         │              │         │                     │
         ▼              ▼         ▼                     ▼
    确定性数据组装   FAISS检索   extract →             定期扫描
    +LLM表达合成    +LLM合成    Reasoning              events+tasks
                                Engine                 +observations
                                    │                 LLM提炼
                                    ▼                   ▼
                                LLM决策JSON         经验规则+画像
                                     │
                                     ▼
                                执行: 写tasks
                                合并/去重/创建
                                     │
                                     ▼
                                LLM 合成回复

      ┌─────────────────────────────────────────────────────────┐
      │ 保留不变: task/store, manager, status, priority,        │
      │   organization/model, entity/builder, memory_core,      │
      │   event_recorder, event_lifecycle, change_detector      │
      └─────────────────────────────────────────────────────────┘
```
