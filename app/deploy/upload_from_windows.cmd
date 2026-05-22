@echo off
setlocal

set "SERVER_HOST=103.43.9.52"
set "SERVER_USER=root"
set "SERVER_PORT=22"
set "AI_SIGNAL_DOMAIN="
set "AI_SIGNAL_BASE_PATH=/ai-hot"
set "ZIP_PATH=%~dp0..\..\welopc-ai-signal-radar.zip"

if not exist "%ZIP_PATH%" (
  set "ZIP_PATH=%~dp0..\welopc-ai-signal-radar.zip"
)

if not exist "%ZIP_PATH%" (
  echo Release zip not found:
  echo %ZIP_PATH%
  echo Run deploy\package_release.py first, or pass the zip with scp manually.
  exit /b 1
)

where scp >nul 2>nul
if errorlevel 1 (
  echo scp.exe was not found. Install Windows OpenSSH Client first.
  exit /b 1
)

where ssh >nul 2>nul
if errorlevel 1 (
  echo ssh.exe was not found. Install Windows OpenSSH Client first.
  exit /b 1
)

echo Uploading %ZIP_PATH% to %SERVER_USER%@%SERVER_HOST%:/root/
scp -P %SERVER_PORT% "%ZIP_PATH%" %SERVER_USER%@%SERVER_HOST%:/root/welopc-ai-signal-radar.zip
if errorlevel 1 exit /b 1

echo Installing on server. This deploys to /opt/welopc-ai-signal-radar and /var/www/welopc-ai-signal-radar.
ssh -p %SERVER_PORT% %SERVER_USER%@%SERVER_HOST% "cd /root && yum install -y unzip rsync || true; rm -rf /root/welopc-ai-signal-radar; unzip -oq /root/welopc-ai-signal-radar.zip -d /root; cd /root/welopc-ai-signal-radar && AI_SIGNAL_BASE_PATH=%AI_SIGNAL_BASE_PATH% AI_SIGNAL_DOMAIN=%AI_SIGNAL_DOMAIN% bash deploy/server_deploy.sh"
if errorlevel 1 exit /b 1

echo Done.
echo Path: http://%SERVER_HOST%%AI_SIGNAL_BASE_PATH%/
echo Fallback: http://%SERVER_HOST%:8787/
