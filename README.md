# 工班 AI 助手

企业工班管理智能助手 — 从钉钉群消息到任务执行、组织认知、知识检索的完整闭环。

---

## 架构（v2.0）

```
                          消息输入
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
      实时消息            历史导入           知识文档
    wrapper.py          import_history()    import_knowledge()
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
                    batch_importer (统一管线)
                             │
              parse → classify → event → context → task
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
     event_recorder      task/manager       knowledge/indexer
     → log.jsonl         → tasks.json       → FAISS semantic index
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
                    memory_bridge.accumulate()
                       → org_memory.json
                             │
                             ▼
                    profile/retriever (实时计算)
                       → 人物画像 + 趋势
```

---

## 系统能力

| 层 | 模块 | 功能 |
|----|------|------|
| **Ingestion** | `ingestion/` | 消息解析、分类、批量导入、RTF支持、剪贴板模式 |
| **Event** | `core/event.py` | 纯事实提取，不判断责任 |
| **Context** | `core/context.py` | 5种责任类型：executor/coordinator/supervisor/audience/observer |
| **Task** | `task/manager.py` | 任务创建、拆子任务、feedback匹配、状态跟踪 |
| **Memory** | `memory/retriever.py` | 统一搜索：Event+Task+Observation+Candidate |
| **Knowledge** | `knowledge/` | FAISS索引、结构保留解析、版本管理、增量更新 |
| **Profile** | `profile/retriever.py` | 实时画像：执行率、任务类型、月度趋势、完成周期 |
| **Organization** | `organization/` | 人物统计、关系图、组织记忆 |

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

## 导入历史

```bash
# 放入群聊导出文件
cp *.txt *.rtf files/

# 一键导入
python3 -c "import sys; sys.path.insert(0,'tools'); from commands.import_history import import_history; import_history()"

# 手工粘贴（无时间戳）
python3 -c "
from commands.import_history import clipboard_import
clipboard_import('王亮：请各班组完成消防检查\n苗笑天：已完成')
"
```

---

## 查询

```python
# 统一记忆检索
from memory.retriever import search_memory, search_period
search_memory("杨梦卓")                          # 全部历史
search_period("杨梦卓", "2026-07-18")            # 限定日期

# 人物画像
from profile.retriever import format_context
print(format_context("苗笑天"))                  # LLM 可直接注入

# 知识检索
from knowledge.retriever import retrieve
print(retrieve("灭火器检查周期"))                 # 制度查询
```

---

## 知识索引

```bash
# 初次导入 / 增量更新
python3 -c "import sys; sys.path.insert(0,'tools'); from commands.import_knowledge import import_knowledge; import_knowledge()"
```

---

## 项目结构

```
tools/
├── ingestion/           · 消息导入管线
│   ├── batch_importer.py    · 统一导入入口
│   ├── message_parser.py    · 消息解析
│   ├── message_classifier.py· 消息分类（反馈优先）
│   ├── rtf_parser.py        · RTF 格式支持
│   └── validator.py         · 质量检查
├── core/                · 认知核心
│   ├── event.py             · 事件提取
│   └── context.py           · 责任判断
├── task/                · 任务管理
│   ├── manager.py           · 创建/匹配/闭环
│   ├── store.py             · JSON 持久化
│   ├── priority.py          · 优先级推断
│   └── analyzer.py          · 统计分析
├── memory/              · 记忆系统
│   ├── event_recorder.py    · event → log.jsonl
│   └── retriever.py         · 统一记忆检索
├── knowledge/           · 知识索引
│   ├── scanner.py           · 增量扫描
│   ├── processor.py         · 结构解析+切块
│   ├── indexer.py           · FAISS 索引
│   ├── store.py             · 元数据+版本
│   └── retriever.py         · 知识检索
├── profile/             · 人物画像
│   └── retriever.py         · 实时计算画像+趋势
├── organization/        · 组织认知
│   ├── model.py             · 团队模型
│   └── memory_bridge.py     · 事件→统计
├── commands/            · 用户入口
│   ├── import_history.py
│   └── import_knowledge.py
└── routing/             · 实时消息路由
    └── wrapper.py
```

---

## 测试

```bash
python3 tests/test_role_resolution.py   # 6 cases
python3 tests/test_event_flow.py        # 5 cases
python3 tests/test_context_pipeline.py  # 4 cases
python3 tests/test_llm_fallback.py      # 4 cases
# 全部 19/19 通过
```

---

## 版本

| 版本 | 内容 |
|------|------|
| v2.0 | 完整企业认知系统：ingestion管线、knowledge索引、profile层、feedback闭环 |
| v1.8 | 核心管线：Event→Context→Task + 任务管理 + 记忆层 |
| v1.5-1.7 | 事件检测、责任解析、工作查询 |
