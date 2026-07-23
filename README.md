# 工班 AI 助手 — Cipher

企业工班管理认知系统 — 从钉钉群消息到任务执行、组织认知、知识检索的完整闭环。

---

## 架构（v3.0）

```
                              消息输入
                                  │
                          entry.py (统一入口)
                                  │
                          query_router (四路分流)
                        ┌─────┬──┼──┬─────┐
                        ▼     ▼  ▼  ▼     ▼
                     profile task knowledge event
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              Pipeline 6 层编排                    MCP Server
          Ingress → Intent → Reasoning            (memory_server.py)
           → Execution → Response → Reflection    search/save/retrieve/reflect
                    │
                    ▼
          ┌────────┼────────┬────────┐
          ▼        ▼        ▼        ▼
       tasks/   events/   memory/  knowledge/
       manager  recorder  FAISS    index

  持久层:
    state/team_work.json        · 组织框架源（JSON，人工可编辑）
    state/entity_index.json     · 人物实体索引（O(1)运行时缓存）
    state/tasks.json            · 任务持久化
    state/org_memory.json       · 组织统计记忆
    state/knowledge/            · 知识索引元数据
    state/personal/             · 个人认知数据
    state/reports/              · 报表数据
    state/flomo_export.html     · flomo 导出数据
    state/import_batches.json   · 导入批次记录
    state/import_registry.json  · 导入注册表
```

---

## 系统能力

| 层 | 模块 | 功能 |
|----|------|------|
| **Ingress** | `core/ingress.py` | 消息预处理、标准化 |
| **Intent** | `core/intent.py` | 意图分类（profile/task/knowledge/personal/event） |
| **Reasoning** | `core/reasoning.py` | 认知推理、因果推演、认知反馈环 |
| **Execution** | `core/execution.py` | pipeline 编排执行 |
| **Response** | `core/response.py` | LLM 表达合成 |
| **Reflection** | `core/reflection.py` | 后处理反思（fire-and-forget） |
| **Event** | `core/event.py` | 纯事实提取，不判断责任 |
| **Context** | `core/context.py` | 5种责任类型：executor/coordinator/supervisor/audience/observer |
| **Task** | `task/manager.py` | 任务创建、拆子任务、feedback匹配、状态跟踪 |
| **Memory** | `memory/retriever.py` | 双索引搜索：语义(FAISS) + 情景(memory_server MCP) |
| **Knowledge** | `knowledge/` | 增量扫描、结构解析+切块、FAISS索引、版本管理 |
| **Profile** | `profile/` | 实时画像(user_retriever)、个人认知(personal_retriever) |
| **Organization** | `organization/` | 团队模型、从 team_work.json 构建、事件统计桥接 |
| **Routing** | `routing/` | 四路查询路由（profile/task/knowledge/event）、实体解析、builder |

---

## 数据流

```
消息 → Event（发生了什么）
       Context（对我意味着什么）
       Task（我要做什么）
       Feedback（结果如何）
       Memory（学到了什么）
```

---

## 入口

```bash
# 统一入口
python3 skills/routing/entry.py '<消息>'

# 跳转核心管道（跳过路由）
python3 skills/routing/entry.py --core '<消息>'
```

---

## 导入历史

```bash
# 放入群聊导出文件
cp *.txt *.rtf files/

# 一键导入
python3 -c "from skills.commands.import_history import import_history; import_history()"

# 手工粘贴（无时间戳）
python3 -c "
from skills.commands.import_history import clipboard_import
clipboard_import('王亮：请各班组完成消防检查\n苗笑天：已完成')
"
```

---

## 查询

```python
# 统一记忆检索
from skills.memory.retriever import search_memory, search_period
search_memory("杨梦卓")                          # 全部历史
search_period("杨梦卓", "2026-07-18")            # 限定日期

# 人物画像
from skills.profile.user_retriever import format_context
print(format_context("苗笑天"))                  # LLM 可直接注入

# 知识检索
from skills.knowledge.retriever import retrieve
print(retrieve("灭火器检查周期"))                 # 制度查询
```

---

## 知识索引

```bash
# 初次导入 / 增量更新
python3 -c "from skills.commands.import_knowledge import import_knowledge; import_knowledge()"
```

---

## 项目结构

```
skills/
├── core/                  · 6 层 Pipeline + 认知核心
│   ├── pipeline.py            · Pipeline 编排器（6层）
│   ├── ingress.py             · 消息预处理
│   ├── intent.py              · 意图分类
│   ├── reasoning.py           · 认知推理
│   ├── execution.py           · 执行
│   ├── response.py            · LLM 合成回复
│   ├── reflection.py          · 后处理反思
│   ├── cognitive_loop.py      · 认知反馈环（Probe + Simulate）
│   ├── context.py             · 责任类型判断（5种）
│   ├── event.py               · 事件事实提取
│   ├── hierarchy_resolver.py  · 组织层级查询
│   ├── llm_client.py          · DeepSeek API 封装
│   ├── event_enricher.py      · 事件富化
│   └── instruction_resolver.py· 指令解析
├── ingestion/             · 消息导入管线
│   ├── batch_importer.py      · 统一导入入口
│   ├── message_parser.py      · 消息解析
│   ├── message_classifier.py  · 消息分类
│   ├── rtf_parser.py          · RTF 格式支持
│   ├── section_parser.py      · 结构化文档解析
│   ├── flomo_parser.py        · flomo 导出解析
│   ├── ai_content_extractor.py· AI 内容提取
│   └── validator.py           · 质量检查
├── routing/               · 实时消息路由
│   ├── entry.py               · 统一入口
│   ├── query_router.py        · 四路分流
│   ├── task_handler.py        · 工作查询
│   ├── knowledge_handler.py   · 知识查询
│   ├── record_manager.py      · 工作记录管理
│   ├── builder.py             · entity_index 构建器
│   └── entity_resolver.py     · 实体解析
├── task/                  · 任务管理
│   ├── manager.py             · 创建/匹配/闭环
│   ├── store.py               · JSON 持久化
│   ├── priority.py            · 优先级推断
│   └── analyzer.py            · 统计分析
├── memory/                · 记忆系统
│   ├── memory_server.py       · MCP STDIO 服务（search/save/retrieve/reflect）
│   ├── memory_core.py         · FAISS 双索引（语义/情景）
│   ├── retriever.py           · 统一记忆检索
│   ├── event_recorder.py      · event → log.jsonl
│   ├── event_detector.py      · 信号检测
│   ├── event_lifecycle.py     · 事件状态迁移
│   ├── event_search.py        · 事件检索
│   ├── change_detector.py     · 变化检测
│   ├── observation_store.py   · 观察持久化（facts/patterns/conclusions）
│   └── ...
├── knowledge/             · 知识索引
│   ├── scanner.py             · 增量扫描
│   ├── processor.py           · 结构解析+切块
│   ├── indexer.py             · FAISS 索引
│   ├── store.py               · 元数据+版本
│   └── retriever.py           · 知识检索
├── profile/               · 人物画像
│   ├── user_retriever.py      · 实时画像+趋势
│   └── personal_retriever.py  · 个人认知检索
├── organization/          · 组织认知
│   ├── model.py               · 团队模型（从 team_work.json 构建）
│   └── memory_bridge.py       · 事件→统计
├── shared/                · 共享基础
│   ├── schema.py             · RequestContext 统一 schema
│   ├── interfaces.py         · 层接口定义
│   ├── llm_cache.py          · 带 TTL 的 LLM 调用缓存
│   ├── semantic.py           · 语义工具
│   └── time_parse.py         · 时间解析
├── commands/              · CLI 工具
│   ├── import_history.py
│   └── import_knowledge.py
├── reasoning/             · 因果推演
│   └── simulator.py
├── plugins/               · 插件
│   └── dingbot/              · 钉钉消息推送
└── cron/                  · 定时任务
    └── nightly.py
```

---

## 测试

```bash
# 全部测试
python3 -m pytest tests/ -v    # 19/19 通过
```

---

## 版本

| 版本 | 内容 |
|------|------|
| v3.0 | 6层Pipeline编排、MCP memory_server、entity_index统一缓存、team_work.json组织源、tools→skills重命名、state/数据源统一 |
| v2.0 | 完整企业认知系统：ingestion管线、knowledge索引、profile层、feedback闭环 |
| v1.8 | 核心管线：Event→Context→Task + 任务管理 + 记忆层 |
| v1.5-1.7 | 事件检测、责任解析、工作查询 |

---

## 开发纪律

- 6 层 Pipeline 各层职责分离，每层只写自己字段
- 禁止 LLM 参与 Event/Context/Task 判断
- 修改前确认：属于哪一层？是否已有模块？是否只是临时规则？
- 扩展已有模块优先于新建
