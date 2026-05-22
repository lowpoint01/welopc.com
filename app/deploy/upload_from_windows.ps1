param(
  [string]$ServerHost = "103.43.9.52",
  [string]$ServerUser = "root",
  [int]$ServerPort = 22,
  [string]$Domain = "",
  [string]$BasePath = "/ai-hot",
  [string]$ZipPath = ".\welopc-ai-signal-radar.zip"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ZipPath)) {
  throw "Zip not found: $ZipPath"
}

Write-Host "Uploading $ZipPath to ${ServerUser}@${ServerHost}:/root/" -ForegroundColor Cyan
scp -P $ServerPort -o StrictHostKeyChecking=accept-new $ZipPath "${ServerUser}@${ServerHost}:/root/welopc-ai-signal-radar.zip"

$remote = @"
set -e
cd /root
rm -rf welopc-ai-signal-radar
if command -v unzip >/dev/null 2>&1; then
  unzip -oq welopc-ai-signal-radar.zip
else
  python - <<'PY'
import zipfile
zipfile.ZipFile('/root/welopc-ai-signal-radar.zip').extractall('/root')
PY
fi
cd /root/welopc-ai-signal-radar
AI_SIGNAL_DOMAIN="$Domain" AI_SIGNAL_BASE_PATH="$BasePath" bash deploy/server_deploy.sh
"@

Write-Host "Running remote deploy. If prompted, enter the server password." -ForegroundColor Cyan
$remote | ssh -p $ServerPort -o StrictHostKeyChecking=accept-new "${ServerUser}@${ServerHost}" "bash -s"

Write-Host "Done." -ForegroundColor Green
Write-Host "Port URL: http://${ServerHost}:8787/"
if ($BasePath) {
  Write-Host "Path URL: http://${ServerHost}${BasePath}/"
}
if ($Domain) {
  Write-Host "Domain URL: http://${Domain}/"
  Write-Host "Make sure DNS A record points ${Domain} to ${ServerHost}."
}
