---
name: state_analyzer
description: 管理分析 + 报告生成
---
## 触发条件
- 分析模式：团队问题、领导意图、分配公平、梯队分析、管理建议
- 报告模式：写汇报、会议纪要、讲话稿、总结、简报、整理成文

## 执行动作
分析模式：读取 state/*.md → 输出核心判断+数据支撑
报告模式：读取 state/*.md + memory/meeting-notes.md → 输出成文文档

## 读取文件
- state/_index.md
- state/leaders.md
- state/cognition.md
- state/org.md
- state/rules.md
- memory/meeting-notes.md（报告模式）
