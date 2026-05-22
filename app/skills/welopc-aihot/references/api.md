# WelOPC AIHOT Public API

Base URL:

```text
https://welopc.com/ai-hot/api/public
```

## Endpoints

### Feed

```text
GET /feed?mode=selected&channel=all&limit=10
```

Common parameters:

- `mode`: `selected` for high-signal content, `all` for broader search.
- `channel`: `all`, `github`, `community`, `firstParty`, `news`, `opcSolo`.
- `limit`: number of items.
- `q`: keyword query when supported by the API.

Typical fields:

- `titleZh` / `title`
- `summaryZh` / `summary`
- `url` / `link`
- `sourceName`
- `channel`
- `publishedAt`
- `finalScore` / `channelScore`
- `aiTags`

### Latest Daily

```text
GET /daily/latest
```

Returns the latest daily report with `title`, `summary`, `content`, and often `markdown`.

### Stats

```text
GET /stats
```

Returns coverage counts, channel counts, latest pipeline run status, newest item time, and generated time.

## Safety Boundary

Use only public endpoints in this skill. Do not request admin routes, server files, SQLite paths, SSH credentials, or bearer tokens.
