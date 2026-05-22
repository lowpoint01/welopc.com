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

WelOPC AIHOT 是一个给 Agent 使用的 AI 内容能力包，不只是新闻查询工具。它把 `https://welopc.com/ai-hot/` 已经采集、筛选、评分、聚合的热点内容，变成可复用的素材源、趋势源、选题源和工作流触发源。

## 什么时候使用

当用户需要以下任务时使用本 skill：

- 获取当前 AI 圈高信号热点、工具更新、模型发布、开发者生态变化。
- 判断某个 AI 主题、产品、模型、公司或关键词是否正在升温。
- 生成日报、周报、内部简报、公众号选题、短帖素材或文章提纲。
- 观察 Codex、Claude Code、Cursor、MCP、Agent framework 等 coding-agent 生态变化。
- 基于近期热点触发后续工作流，例如生成摘要、推送、选题库或趋势报告。
- 需要带来源 URL 和时间戳的 AI 资讯引用，减少无来源总结。

## 默认原则

- 优先调用 scripts，不要抓取网页 HTML。
- 默认用 `selected` 高信号内容，除非用户明确要求全量。
- 用户需要 WelOPC/OPC/自媒体视角时，优先使用 `opcSolo` channel。
- 输出时尽量保留来源 URL、来源名称、发布时间、频道和分数。
- 不宣称覆盖全市场；表述为 WelOPC AIHOT signals。

## 常用命令

在本 skill 目录下运行：

```bash
python scripts/latest.py --channel all --mode selected --limit 10 --format markdown
```

获取最新高信号 AI 热点。

```bash
python scripts/daily.py --format markdown
```

获取最新 AI 日报。

```bash
python scripts/search.py "Claude Code" --channel all --mode all --limit 20 --format json
```

围绕关键词做近期信号研究。

```bash
python scripts/stats.py --format json
```

查看 AIHOT 覆盖面、来源数、精选数量和 pipeline 状态。

## 任务到命令的映射

| 用户任务 | 推荐命令 | 输出用法 |
| --- | --- | --- |
| “今天 AI 圈有什么值得看” | `python scripts/latest.py --format markdown` | 直接总结给用户 |
| “帮我找公众号选题” | `python scripts/latest.py --channel opcSolo --format markdown` | 提炼选题、角度、标题 |
| “最近 Claude Code 有什么变化” | `python scripts/search.py "Claude Code" --format json` | 聚合成工具链情报 |
| “生成今天 AI 日报” | `python scripts/daily.py --format markdown` | 作为日报正文素材 |
| “这个站覆盖得怎么样” | `python scripts/stats.py --format json` | 判断来源和 pipeline 状态 |

## 输出建议

面向用户返回时，优先用这种结构：

1. 一句话结论。
2. 3-7 个高信号条目。
3. 每个条目带来源、时间、URL。
4. 如适合内容生产，补充“可写角度”或“为什么值得关注”。

不要只复述标题列表。根据任务把内容加工成摘要、趋势判断、选题列表、报告大纲或引用材料。
