# Deployment Guide

This package is safe to share with another developer or deployer. It does not include real API tokens, browser cookies, Feishu credentials, or local machine auth state.

## Required Environment Variables

Copy `.env.example` to `.env` for local development, or configure these as deployment secrets in GitHub Actions, Cloudflare Pages, Vercel, or your scheduler.

```bash
GITHUB_TOKEN=
TWITTERAPI_API_KEY=
PRODUCT_HUNT_TOKEN=
PRODUCT_HUNT_API_KEY=
PRODUCT_HUNT_API_SECRET=
YOUTUBE_API_KEY=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_PAGES_PROJECT=welopc-ai-signal-radar
```

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
python -m playwright install chromium
```

## Generate Latest Data

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m ecom_research.cli ai-news-schedule-run --force
```

Output is written to:

```text
site/ai-signal-live/data/latest.json
site/ai-signal-live/data/history.json
site/ai-signal-live/data/latest.md
```

## Preview

```powershell
python -m http.server 8787 --bind 127.0.0.1 --directory site/ai-signal-live
```

Open:

```text
http://127.0.0.1:8787/
```

## Package

Build a clean deploy package that excludes local auth, cache, raw data, reports, and git history:

```powershell
python deploy\package_release.py
```

The output is:

```text
..\welopc-ai-signal-radar.zip
```

## Self-hosted Server

Recommended path under the main domain:

```text
https://welopc.com/ai-hot/
```

One-click upload from Windows, with password entered only in the SSH prompt:

```cmd
deploy\upload_from_windows.cmd
```

The server script deploys independently from the main site:

```text
/opt/welopc-ai-signal-radar
/var/www/welopc-ai-signal-radar
/etc/httpd/conf.d/welopc-ai-signal-radar.conf
```

The main site stays in `/var/www/welopc/current`; Apache only mounts the radar through `Alias /ai-hot/`.

Dynamic refresh is handled by a separate systemd timer:

```text
welopc-ai-signal-radar-refresh.timer
```

The default interval is 30 minutes. Each run regenerates `latest.json`, `history.json`, and `latest.md`, then syncs the web root.

## Cloudflare Pages

Static output directory:

```text
site/ai-signal-live
```

No build command is required for static hosting. For direct upload:

```powershell
npx wrangler pages deploy site/ai-signal-live --project-name=welopc-ai-signal-radar
```

## Security Notes

Do not commit or share:

- `.env`
- `auth/`
- browser storage state files
- Feishu app secrets or document tokens
- GitHub personal access tokens
- Product Hunt developer tokens
- X/Twitter API keys
- YouTube API keys
- Cloudflare API tokens
