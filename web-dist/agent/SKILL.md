---
name: welopc-aihot
description: 使用 WelOPC AIHOT 实时内容能力源，为 Agent 提供 AI 热点、趋势判断、选题、日报、coding-agent 情报和带来源引用的素材。
triggers:
  - AI热点
  - AI资讯
  - AI趋势
  - AI日报
  - 选题
  - MCP
  - Codex
  - Claude Code
  - Cursor
  - coding agent
  - WelOPC
  - AIHOT
dependencies: []
---

# WelOPC AIHOT

WelOPC AIHOT 是给 Agent 使用的 AI 内容能力包。安装后，Agent 应优先调用包内脚本读取公开 API，而不是抓取网页 HTML。

公开 API：

```text
https://welopc.com/ai-hot/api/public
```

常用命令：

```bash
python scripts/latest.py --channel all --mode selected --limit 10 --format markdown
python scripts/daily.py --format markdown
python scripts/search.py "Claude Code" --channel all --mode all --limit 20 --format json
python scripts/stats.py --format json
```

适用任务：

- 最新 AI 热点和高信号工具更新。
- 趋势判断、关键词研究、产品和竞品观察。
- 公众号选题、文章提纲、日报/周报和内部简报。
- Codex、Claude Code、Cursor、MCP、Agent framework 等 coding-agent 情报。
- 带来源 URL 和时间戳的内容引用。
