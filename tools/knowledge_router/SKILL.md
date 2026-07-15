---
name: knowledge_router
description: 在知识库中搜索制度/规范/手册
---
## 触发条件
用户输入包含"制度/规定/安全标准/流程/手册/台账/规范"

## 执行动作
1. 查询: `python3 tools/knowledge_router/query_knowledge.py "关键词"`
   - 仅搜索 `.md` 文本文件（_index_files.md + README.md）
   - 返回文件路径 + 关键词上下文（一行摘要）
   - 不提取二进制文件内容（不影响 token）
2. 读文档: `python3 tools/knowledge_router/read_doc.py "子目录/文件名.docx"`
   - 支持格式: .docx .xlsx .pptx .pdf .md
   - 按需提取文本内容，最多返回 4000 字符

## 读取文件
- Knowledge/**/README.md（各子目录文件索引，含完整文件清单+关键词映射）
- Knowledge/**/*.md（标准操作流程、此心安处等纯文本文档）