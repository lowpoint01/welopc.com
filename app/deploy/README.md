# Server Deployment

## Recommended path split

Use a dedicated path under the main domain:

```text
https://welopc.com/ai-hot/
```

Do not copy this into the existing main website release root. The deploy script uses:

```text
/opt/welopc-ai-signal-radar
/var/www/welopc-ai-signal-radar
```

and, when `AI_SIGNAL_BASE_PATH=/ai-hot` is provided, creates a separate Apache path alias:

```text
/etc/httpd/conf.d/welopc-ai-signal-radar.conf
```

The main site remains in:

```text
/var/www/welopc/current
```

## One-click deploy on the server

Upload the zip to the server, unzip it, then run:

```bash
cd /root/welopc-ai-signal-radar
AI_SIGNAL_BASE_PATH=/ai-hot bash deploy/server_deploy.sh
```

If DNS is not ready yet, run without a domain:

```bash
cd /root/welopc-ai-signal-radar
bash deploy/server_deploy.sh
```

Then open:

```text
http://<server-ip>:8787/
```

## One-click upload from Windows

If OpenSSH is available on Windows, put `welopc-ai-signal-radar.zip` next to this repository folder and run:

```cmd
deploy\upload_from_windows.cmd
```

If you prefer PowerShell:

```powershell
.\deploy\upload_from_windows.ps1 -ServerHost 103.43.9.52 -ServerUser root -ServerPort 22 -Domain ai.welopc.com -ZipPath ..\welopc-ai-signal-radar.zip
```

The script uploads the zip to `/root/`, extracts it, and runs `deploy/server_deploy.sh`.

It does not store the server password. Enter the password only in the SSH prompt.

## Dynamic refresh

The server deploy script keeps the site files separated from the main website and installs a systemd timer when Python 3.9+ is available:

```text
welopc-ai-signal-radar-refresh.timer
```

Default polling interval:

```text
30 minutes
```

Check it on the server:

```bash
systemctl list-timers welopc-ai-signal-radar-refresh.timer
systemctl status welopc-ai-signal-radar-refresh.service
```

The refresh job writes `site/ai-signal-live/data/latest.json`, then syncs the result to `/var/www/welopc-ai-signal-radar`.

## DNS

Create or keep the main domain A records:

```text
welopc.com -> 103.43.9.52
www.welopc.com -> 103.43.9.52
```

The `/ai-hot/` path does not need an extra `ai` subdomain record.

## Environment variables

Edit:

```text
/opt/welopc-ai-signal-radar/.env
```

Fill real secrets on the server. Do not send real secrets in zip files.
