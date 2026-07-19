---
name: team_router
description: 当提及工班成员时调用，读取成员画像和近期观察
---
## 触发条件
当用户输入提到以下任一姓名时触发：
李林骁、杨梦卓、谭继衡、苗笑天、陈红洁、张志斌

## 执行动作
调用 route_member.py，传入匹配到的成员名

## 读取文件
- state/_index.md（必读）
- memory/observations/*.md（grep匹配成员名，取最近3条）