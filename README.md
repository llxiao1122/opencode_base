# 工班 AI 助手 — Cipher

企业工班管理认知系统 — 从消息到任务执行、组织认知、制度问答、纠错学习的完整闭环。
"一个大脑 + 一个 skill 体系"：数据统一记忆、代码统一入口、查口收敛。

---

## 架构（一个大脑 + 一个 skill 体系）

```
               消息输入
                   │
          entry.py (统一入口)
           classify() 分类
        ┌───────────┼───────────┐
    高置信快速路径          Agent 路径
   (task_query/        (agent/engine.py
    knowledge_retrieve/   → LLM 选工具
    profile_query)          → registry.execute)
                   │
             统一查口 world_query()
      ┌────────────┴────────────┐
   确定性知识层              语义知识层
   · task_query(规则推算)      · worldview.search(FAISS)
   · tasks.json(状态)          · entities 实体档案
   · Knowledge/*.md(权威源)    · 纠错库(成长输入)
```

## 核心设计

**一个大脑（统一记忆体系）**：
- **唯一写口** `recorder.record()` → 环形缓冲 → 世界观更新（`worldview.check_and_update`）
- **纠错独立**：`correction_store.append()` → `data/state/worldview/纠错.md`（系统成长输入，不写人员档案）
- **制度问答优先世界观 FAISS**（实体档案），Knowledge 保留为只读权威原文源
- **统一查口** `skills/memory/world_query.py`：任务→规则、人员→档案、制度→知识检索

**一个 skill 体系（代码层）**：
- `skills/` 唯一入口 `entry.py`，内部按职责分层
- 确定性知识（任务/日程）走规则路径，**不进向量库**；向量库只服务语义问答
- 推送统一走 `skills/shared/push_queue.py`（fcntl 文件锁队列）

## 系统能力

| 层 | 模块 | 功能 |
|----|------|------|
| **入口** | `entry.py` | 统一入口（单次/--listen/--warm） |
| **路由** | `router/faiss_router.py` | 两层分类：Worldview 语义 + FAISS 种子 |
| **Agent** | `agent/engine.py` | LLM 选工具 + registry.execute |
| **Handler** | `agent/handlers/` | 10 个工具：查询/记录/任务/提醒/纠错/组织 |
| **记忆** | `memory/worldview.py` | 实体档案 + FAISS 索引 + 增量更新 |
| **纠错** | `memory/correction_store.py` | 纠错库读写（独立于人员档案） |
| **查口** | `memory/world_query.py` | 统一对外查询入口 |
| **任务** | `task/manager.py` | 任务创建/状态/反馈闭环（tasks.json） |
| **推送** | `shared/push_queue.py` + `trigger/daemon.py` | 队列 + 临期提醒 |
| **钉钉** | `plugins/dingbot/send_msg.py` | 机器人推送（惰性读 token） |

## 工具清单（registry）

`task_query` / `knowledge_retrieve` / `profile_query` → 快速查询
`notification_push` / `event_record` / `task_create` / `task_feedback` / `org_lookup` / `correction_feedback` / `reminder_set` → 经 Agent 调度

---

## 入口

```bash
# 单次处理
python3 -m skills.entry '<消息>'

# 持久服务（TCP 长驻）
python3 -m skills.entry --listen

# 预加载索引后退出
python3 -m skills.entry --warm
```

## 统一查口

```python
from skills.memory.world_query import query
query("今天有什么任务")        # → 规则路径（task_query）
query("交接评审标准是什么")     # → 语义路径（worldview FAISS → Knowledge）
query("陈红洁")                # → 人员档案（profile_query）
```

## 记忆与纠错

```python
# 世界观：实体档案 + FAISS 语义检索
from skills.memory.worldview import search, check_and_update

# 纠错库：系统成长输入（独立于人员档案）
from skills.memory.correction_store import append, load_recent, count
```

## 推送链路

```bash
# 08:45 预执行：查当日工作入队
python3 scripts/prepare_daily.py

# 每分钟扫描队列，到期推送
python3 scripts/deliver.py
```

钉钉 token 在 crontab 中定义（`DINGTALK_BOT_TOKEN`），`send_msg.py` 惰性读取 `_webhook_url()`，不在 shell 环境硬编码。

---

## 项目结构

```
skills/
├── entry.py                  · 统一入口（classify → 快速路径/Agent）
├── agent/
│   ├── engine.py             · Agent 核心（LLM 选工具 + 注入记忆）
│   ├── registry.py           · 10 工具注册 + execute
│   ├── reflector.py          · 反思（纠错匹配）
│   └── handlers/             · 10 个工具实现
├── memory/
│   ├── worldview.py          · 世界观引擎（实体 + FAISS + 增量）
│   ├── world_query.py        · 统一查口
│   ├── correction_store.py   · 纠错库
│   ├── recorder.py           · record() 统一写口
│   └── observation_store.py  · 观察存储（内部）
├── router/
│   ├── faiss_router.py       · 两层路由（Worldview + FAISS 种子）
│   ├── entity_resolver.py    · 实体解析
│   └── route_index.py        · FAISS 种子索引
├── task/                     · 任务生命周期（tasks.json）
├── trigger/daemon.py         · 临期提醒
├── shared/                   · path/schema/push_queue/embedder/entity
├── core/llm_client.py        · LLM API
├── plugins/dingbot/          · 钉钉推送
└── organization/model.py     · 组织查询
scripts/
├── prepare_daily.py          · 08:45 预执行
└── deliver.py                · 队列到期推送
data/
├── state/worldview/          · 世界观档案 + FAISS + 纠错库
├── state/tasks.json          · 任务状态
└── logs/                     · 运行时日志（.gitignore）
Knowledge/                    · 制度原文（只读权威源）
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 44/44 通过
```

---

## 开发纪律

- 确定性性能用 Python 规则，不用 LLM
- 不改动已有功能；改完必须 `pytest tests/`
- 禁止：为一个规则建 engine / 为一个字段建 manager / 用 LLM 替代 Context / 用 prompt 修架构
- 优先扩展已有模块 → 其次新增稳定边界模块 → 不做临时规则文件
- 纠错与人员档案隔离；任务/日程不进向量库
