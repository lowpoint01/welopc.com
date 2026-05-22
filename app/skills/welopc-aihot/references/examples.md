# WelOPC AIHOT Examples

## Current AI Signals

```bash
python scripts/latest.py --channel all --mode selected --limit 8 --format markdown
```

Use this when the user wants a compact read of current high-signal AI updates.

## Coding-Agent Intelligence

```bash
python scripts/search.py "MCP" --channel all --mode all --limit 20 --format json
python scripts/search.py "Claude Code" --channel all --mode all --limit 20 --format json
python scripts/search.py "Codex" --channel all --mode all --limit 20 --format json
```

Use the results to produce a short trend brief:

- what changed
- why it matters
- who should care
- source links

## OPC Content Topics

```bash
python scripts/latest.py --channel opcSolo --mode all --limit 10 --format markdown
```

Use this for公众号选题、短帖角度、文章大纲、自媒体 OPC 内容生产。

## Daily Brief

```bash
python scripts/daily.py --format markdown
```

Use this as a source document, then rewrite for the target audience instead of pasting blindly.
