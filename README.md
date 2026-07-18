# 工班 AI 助手

企业工班管理智能助手 — 从钉钉消息感知到个人工作视图的完整闭环。

---

## 架构总览

```
钉钉消息 / 用户输入
       │
       ▼
  实体解析        ── entity_resolver     · 从 20 个已知实体中识别人员/角色
       │
       ▼
  路由分发        ── route_request        · 9 条路由(A→I)三层防御
       │
       ▼
  能力编排        ── composer + wrapper   · 单/多能力组合执行
       │
       ▼
  事件检测        ── event_detector       · 4-信号触发, 置信度判定
       │
       ▼
  事件存储        ── memory/events/       · index.json + status 分层目录
       │                                    active/detected/completed/cancelled/expired/archived
       ▼
  事件搜索        ── event_search         · index-first, details-lazy
       │
       ▼
  事件上下文      ── event_context        · search → build_event_context()
       │                                    {title, people, time, tasks, constraints, evidence, report_to}
       ▼
  个人查询层      ── work_query           · tasks.md(固定) + events(动态) 合并
       │
       ▼
  责任解析        ── responsibility       · 三级评定: direct_task / role_task / team_attention
       │
       ▼
  上下文组装      ── context_builder      · 分层 LLM 提示
       │
       ▼
  知识记忆        ── memory_core          · 语义搜索 + 情景记忆 + 反思回路
       │
       ▼
  用户回复
```

---

## 路由定义

| 标签 | 类型 | 处理函数 |
|------|------|----------|
| A | 闲聊/兜底 | LLM 自由回答 |
| B | 总结汇报 | memory_save + reflect |
| C | 分析排查 | slow_think 思维树 |
| D | 制度规范 | 知识库检索 + event_context |
| E | 台账报表 | state_analyzer + work_query + event_context |
| F | 防汛安全 | 同 D |
| G | 排班考勤 | task_manager |
| H | 任务分配 | 同 E |
| I | 知识学习 | 同 D |

路由判定：初始关键词 → LLM 语义标签 → 兜底，22 条测试全部通过。

---

## 事件系统

### 检测触发

6 个信号，任意 ≥2 即触发：

| 序号 | 信号 |
|------|------|
| 1 | 动作词 + 时间词 |
| 2 | 动作词 + 实体 |
| 3 | 编号结构 + 动作词 |
| 4 | 通知类标题 + 时间词 |
| 5 | 显式要求(需/须/应/应) |
| 6 | 权重结构 + 动作词 |

### 置信度与状态

| 置信度 | 状态 | 含义 |
|--------|------|------|
| ≥ 0.85 | active | 高置信度，直接生效 |
| 0.60 - 0.84 | detected | 候选，待确认 |
| < 0.60 | 丢弃 | 不保存 |

置信度上限 0.95。

### 事件结构

```json
{
  "title": "危废处置计划",
  "entities": [{"name": "王超", "role": "危废联络"}],
  "actions": ["通知", "回收", "处置"],
  "required_actions": ["处置要求各库区全部清空", "安排人员进行交接"],
  "time": {"start": "2026-07-18", "deadline": "2026-07-29"},
  "constraints": ["需单独与我联系报备", "须尽快完成回收工作"],
  "evidence": [],
  "report_to": ["王超"],
  "participants": ["各工班", "产废中心"],
  "related_teams": [],
  "executor_analysis": {
    "source": "participants",
    "scope": "team",
    "type": "role",
    "confidence": 0.82,
    "evidence": ["各工班"]
  },
  "items": [{
    "seq": 1,
    "text": "...",
    "actions": ["回收", "处置"],
    "required_actions": ["处置要求各库区全部清空", "安排人员进行交接"]
  }],
  "status": "active",
  "priority": "high",
  "confidence": 0.95
}
```

### 生命周期

```
detected → active → completed/cancelled/expired → archived
              ↑
           (confirm)
```

消息驱动更新 (`event_lifecycle.update_from_message()`):
- 完成词(完成/已处理/搞定了) → completed
- 取消词(取消/暂停/不做了) → cancelled
- 确认词(确认/开始/执行) → detected→active

定期维护 (`event_maintenance.run_maintenance()`):
- deadline < today → expired

---

## 事件上下文

`build_event_context()` 将磁盘上的 event_detail.json 重组为 LLM 可消费的结构：

```json
{
  "title": "根据领导紧急通知",
  "people": {
    "owner": ["王超"],
    "executors": ["各工班", "产废中心"],
    "report_to": ["王超"]
  },
  "time": {"start": "2026-07-18", "deadline": "2026-07-29"},
  "tasks": [
    {
      "content": "危废计划明日开始开展处置工作...",
      "actions": ["处置要求各库区全部清空", "安排人员进行交接"]
    }
  ],
  "constraints": ["需单独与我联系报备", "须尽快完成回收工作"],
  "evidence": [],
  "report_to": ["王超"],
  "source": "text"
}
```

---

## 个人工作视图

`get_my_tasks(user_input)` 合并两个数据源：

| 来源 | 类型 | 文件 |
|------|------|------|
| 固定台账 | 周期性工作 | `memory/tasks.md` |
| 动态事件 | 钉钉通知提取 | `memory/events/` |

用户身份解析优先级：
1. entity_resolver 提取显式人名
2. `state/user_profile.md` 会话绑定

---

## 责任解析

`responsibility.resolve()` 三级评定：

| 等级 | 触发条件 | 示例输出 |
|------|---------|---------|
| `direct_task` | 事件明确点名用户 | 【直接任务】安排人员准备处置材料 |
| `role_task` | "各工班长" 匹配 user.role="工班长" | 【岗位关注】作为工班长协调本工班 |
| `team_attention` | "各库区"/"各工班" 影响 user.team | 【涉及事项】危废处置影响铁炉西工班 |

去混淆规则：
- "各工班长**安排**人员" → role_task（协调层，非执行层）
- "各工班**完成**清空" → team_attention（集体执行层）

---

## 关键文件

```
tools/
├── routing/                  · 路由系统
│   ├── route_request.py      ·   路由判定（三层防御）
│   ├── composer.py           ·   多能力编排
│   ├── wrapper.py            ·   硬编码分发层
│   ├── entity_resolver.py    ·   实体识别
│   ├── context_builder.py    ·   LLM 上下文组装
│   └── test_route.py         ·   路由测试（22 条）
├── memory/                   · 记忆与事件系统
│   ├── memory_core.py        ·   知识语义搜索
│   ├── event_detector.py     ·   事件检测提取
│   ├── event_search.py       ·   事件查询
│   ├── event_context.py      ·   事件上下文构建
│   ├── event_lifecycle.py    ·   生命周期管理
│   ├── event_maintenance.py  ·   定期维护
│   ├── curiosity_engine.py   ·   好奇心引擎
│   └── change_detector.py    ·   变更检测
├── work/                     · 工作查询
│   ├── work_query.py         ·   个人工作查询
│   └── responsibility.py     ·   责任解析器
└── reasoning/                · 推理引擎
    ├── llm_client.py         ·   LLM 调用
    └── slow_think.py         ·   慢思考
state/
├── entity_index.json         ·   20 个确认实体
├── user_profile.md           ·   会话用户 + 权限边界
├── org.md                    ·   组织架构
├── leaders.md                ·   领导层
├── members/                  ·   成员档案
└── _changes/                 ·   变更记录
memory/
├── events/                   ·   事件存储（按状态分层）
│   ├── index.json
│   ├── active/
│   ├── detected/
│   ├── completed/
│   ├── cancelled/
│   ├── expired/
│   ├── archived/
│   └── ignored/
├── tasks.md                  ·   固定周期台账
└── observations/             ·   观察记录
```

---

## 版本历史

| 版本 | 内容 |
|------|------|
| Phase 1.1 | entity_resolver — 实体识别 |
| Phase 1.2 | change_detector — 变更检测 |
| Phase 1.3 | event_detector — 事件检测 |
| Phase 1.4 | event_search + lifecycle + maintenance |
| Phase 1.4.1 | 事件 schema 升级 (constraints/evidence/report_to/required_actions) |
| Phase 1.5 | work_query — 个人工作视图 |
| Phase 1.6 | responsibility — 三级责任解析 |

---

## 使用

```bash
# 单次查询
python3 tools/routing/wrapper.py "周一我有什么工作要做"

# 交互模式
python3 tools/routing/wrapper.py --interactive

# 事件检测
python3 tools/memory/event_detector.py detect "通知原文..."

# 路由测试
python3 tools/routing/test_route.py
```
