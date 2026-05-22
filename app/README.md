# WelOPC AI Signal Radar

Realtime AI / Agent / model / OPC signal radar for WelOPC. It aggregates official sources, GitHub growth, Product Hunt, Reddit, YouTube, public RSS feeds, WeChat public-account sources and TrendRadar-style hotlists, then renders a dashboard and API service for AI HOT, OPC and Agent workflows.

## Repository name

Recommended GitHub repository name: `welopc-ai-signal-radar`.

## What is included

- `src/ecom_research/intel_workspace.py`: source collection, scoring and digest rendering.
- `src/ecom_research/ai_signal_scheduler.py`: 20-minute live schedule and static-site export.
- `site/ai-signal-live/`: static frontend dashboard.
- `configs/opc_intelligence.json`: sanitized source configuration.
- `configs/ai_signal_timeline.yaml`: live monitor schedule.
- `.env.example`: optional token names for richer sources. Use the repository root `.env.example` as the current production template.

## What is intentionally excluded

- Browser cookies and login state under `auth/`.
- Local raw data and normalized exports.
- Generated historical reports.
- Local logs and temporary files.
- Real API tokens, model keys, WeChat authorization cookies and document tokens.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
python -m playwright install chromium
```

## Generate one live snapshot

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m ecom_research.cli ai-news-schedule-run --force
```

The static output is written to `site/ai-signal-live/data/latest.json`.

## Preview locally

```powershell
python -m http.server 8787 --bind 127.0.0.1 --directory site/ai-signal-live
```

Open: http://127.0.0.1:8787/

## Cloudflare Pages

Use static output directory:

```text
site/ai-signal-live
```

No build command is required for a static deploy. If you want continuous direct upload, configure:

```powershell
setx CLOUDFLARE_ACCOUNT_ID "<account-id>"
setx CLOUDFLARE_API_TOKEN "<pages-token>"
setx CLOUDFLARE_PAGES_PROJECT "welopc-ai-signal-radar"
```

Then deploy:

```powershell
npx wrangler pages deploy site/ai-signal-live --project-name=welopc-ai-signal-radar
```

## Self-hosted Server

For a CentOS / Linux server that already hosts a main site, deploy this project as a separate site instead of mixing it into the main web root.

Recommended subdomain:

```text
ai.welopc.com
```

Server-side one-click deploy:

```bash
cd /root/welopc-ai-signal-radar
AI_SIGNAL_DOMAIN=ai.welopc.com bash deploy/server_deploy.sh
```

If DNS is not ready, omit `AI_SIGNAL_DOMAIN` and use the independent preview port configured in your own environment.

See `deploy/README.md` for details.

## GitHub Pages

Serve the folder `site/ai-signal-live` as the Pages artifact, or copy that folder into a Pages branch.

## Tests

```powershell
python -m pytest tests/test_intel_workspace.py -q
```
