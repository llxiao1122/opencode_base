# tools/ — 工班AI工具集

按架构分层组织。**粗体** = 框架核心，其他 = 可替换/扩展。

---

## 路由层 (Routing)
入口判定。所有用户输入必经此层。

| 文件 | 职责 |
|------|------|
| **`route_request.py`** | 三层路由判定器 (L1 关键词 → L2 LLM标签 → L3 兜底 A) |
| **`llm_tags.py`** | LLM 语义标签提取器，与路由逻辑解耦，带内存缓存 |
| `wrapper.py` | 硬约束主循环 ⚠️ 待适配新路由标签 (当前引入 MEMBER_NAMES 已失效) |
| `test_route.py` | 路由测试 (18 条用例) |

## 记忆层 (Memory)
向量检索、经验存储、反思回路。

| 文件 | 职责 |
|------|------|
| **`memory_core.py`** | FAISS 双索引引擎 (语义 + 情景)，核心持久化 |
| `memory_server.py` | MCP STDIO 包装，暴露 4 个工具给 opencode |
| `memory_reflect.py` | 反思回路 CLI 入口 |
| `curiosity_engine.py` | 矛盾检测 + 知识缺口 + 异常模式扫描 |
| `user_model.py` | 6 域分类器 (safety/flood/quality/schedule/paperwork/personnel) |
| `event_recorder.py` | 统一录制 (log + member + observation) |
| `observation_writer/` | 观察日志追加到 `memory/observations/` |

## 推理层 (Reasoning)
深度分析、模拟推演、价值判断。

| 文件 | 职责 |
|------|------|
| **`slow_think.py`** | 思维树展开 + 记忆关联 + 价值仲裁 |
| `simulator.py` | LLM 因果模拟引擎 (轻量/完整双模式) |
| `value_arbiter.py` | 6 维加权评分 + 硬约束一票否决 |
| `llm_client.py` | DeepSeek API 封装 (urllib, 读 opencode.jsonc) |

## 业务插件 (Plugins)
被 wrapper 调用的子进程模块。各含独立 CLI 入口。

| 目录 | 触发路由 | 入口脚本 |
|------|---------|---------|
| `task_manager/` | 待办/排班 | `manage_tasks.py` |
| `state_analyzer/` | 团队/汇报 | `analyze_state.py` |
| `team_router/` | 成员查询 | `route_member.py` |
| `knowledge_router/` | 知识库回退 | `query_knowledge.py` / `read_doc.py` |
| `dingbot/` | 通知推送 | `send_msg.py` |

## 基础设施 (Infra)

| 文件 | 职责 |
|------|------|
| `kill_dup_opencode.sh` | 清理重复 opencode 进程 |

## 已废弃 (Legacy)

| 文件 | 原因 |
|------|------|
| `keyword_discovery.py` | 被三层路由 LLM 标签层取代 |
| `domain_context.md` | keyword_discovery 的上下文文件，不再需要 |

---

## 依赖图

```
route_request.py ← llm_tags.py ← llm_client.py
wrapper.py ← route_request.py ← llm_tags.py ─────────┐
           ← memory_core.py (lazy)                   │
           ← slow_think.py (lazy) ──→ simulator.py   │ (所有路径)
           ← curiosity_engine.py (lazy)              │
           ├─→ task_manager/manage_tasks.py          │ subprocess
           ├─→ state_analyzer/analyze_state.py       │
           ├─→ team_router/route_member.py           │
           ├─→ knowledge_router/query_knowledge.py   │
           ├─→ observation_writer/write_observation.py │
           └─→ dingbot/send_msg.py                   │
```

## 当前状态

- 路由: 三层框架已就绪, 18/18 测试通过
- 路由标签: 已重映射为 B=总结/C=分析/D=制度/E=台账/F=防汛/G=排班/H=任务/I=学习/A=兜底
- wrapper.py: 待适配新路由标签 (handler 映射需同步更新)
