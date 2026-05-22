#!/usr/bin/env bash
set -euo pipefail

# WelOPC AI Signal Radar one-click server deploy.
# Safe-by-default:
# - Does not overwrite an existing main website.
# - Serves the radar from its own web root.
# - Mounts the radar under a separate path when AI_SIGNAL_BASE_PATH is provided.
# - Installs an optional refresh timer when a supported Python runtime exists.

APP_NAME="${APP_NAME:-welopc-ai-signal-radar}"
APP_DOMAIN="${AI_SIGNAL_DOMAIN:-${APP_DOMAIN:-}}"
APP_BASE_PATH="${AI_SIGNAL_BASE_PATH:-${APP_BASE_PATH:-}}"
APP_ROOT="${APP_ROOT:-/opt/${APP_NAME}}"
WEB_ROOT="${WEB_ROOT:-/var/www/${APP_NAME}}"
SERVICE_NAME="${SERVICE_NAME:-${APP_NAME}}"
STATIC_PORT="${STATIC_PORT:-8787}"
REFRESH_INTERVAL_MINUTES="${AI_SIGNAL_REFRESH_INTERVAL_MINUTES:-30}"
REFRESH_SERVICE_NAME="${SERVICE_NAME}-refresh"
PYTHON_BIN="${AI_SIGNAL_PYTHON:-}"
VENV_DIR="${AI_SIGNAL_VENV_DIR:-${APP_ROOT}/.venv}"
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root."
  exit 1
fi

echo "[1/7] Preparing directories"
mkdir -p "${APP_ROOT}" "${WEB_ROOT}"

echo "[2/7] Copying application files"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  "${PACKAGE_ROOT}/" "${APP_ROOT}/"

rsync -a --delete "${APP_ROOT}/site/ai-signal-live/" "${WEB_ROOT}/"

echo "[3/7] Writing environment file"
if [ ! -f "${APP_ROOT}/.env" ]; then
  cp "${APP_ROOT}/.env.example" "${APP_ROOT}/.env"
  chmod 600 "${APP_ROOT}/.env"
fi

echo "[4/7] Installing independent static service on port ${STATIC_PORT}"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=WelOPC AI Signal Radar static site
After=network.target

[Service]
Type=simple
WorkingDirectory=${WEB_ROOT}
ExecStart=/usr/bin/python -m SimpleHTTPServer ${STATIC_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

if command -v python3 >/dev/null 2>&1; then
  sed -i 's#/usr/bin/python -m SimpleHTTPServer#/usr/bin/python3 -m http.server#g' "/etc/systemd/system/${SERVICE_NAME}.service"
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null
systemctl restart "${SERVICE_NAME}"

echo "[5/7] Installing dynamic refresh timer"
if [ -z "${PYTHON_BIN}" ]; then
  for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "${candidate}")"
      break
    fi
  done
fi

if [ -n "${PYTHON_BIN}" ]; then
  mkdir -p "${VENV_DIR}"
  if [ ! -x "${VENV_DIR}/bin/python" ]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/python" -m pip install -U pip >/tmp/${APP_NAME}-pip.log 2>&1
  "${VENV_DIR}/bin/python" -m pip install \
    "PyYAML>=6.0" \
    "beautifulsoup4>=4.12" \
    "typing_extensions>=4.0" >>/tmp/${APP_NAME}-pip.log 2>&1
  "${VENV_DIR}/bin/python" -m pip install --no-deps -e "${APP_ROOT}" >>/tmp/${APP_NAME}-pip.log 2>&1

  cat > "/etc/systemd/system/${REFRESH_SERVICE_NAME}.service" <<EOF
[Unit]
Description=WelOPC AI Signal Radar data refresh
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${APP_ROOT}
Environment=PYTHONPATH=${APP_ROOT}/src
EnvironmentFile=-${APP_ROOT}/.env
ExecStart=${VENV_DIR}/bin/python -m ecom_research.cli ai-news-schedule-run --force
ExecStartPost=/usr/bin/rsync -a --delete ${APP_ROOT}/site/ai-signal-live/ ${WEB_ROOT}/
ExecStartPost=-/bin/chown -R apache:apache ${WEB_ROOT}
EOF

  cat > "/etc/systemd/system/${REFRESH_SERVICE_NAME}.timer" <<EOF
[Unit]
Description=Run WelOPC AI Signal Radar refresh every ${REFRESH_INTERVAL_MINUTES} minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=${REFRESH_INTERVAL_MINUTES}min
AccuracySec=1min
Persistent=true
Unit=${REFRESH_SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable "${REFRESH_SERVICE_NAME}.timer" >/dev/null
  systemctl restart "${REFRESH_SERVICE_NAME}.timer"
  echo "Dynamic refresh timer enabled: every ${REFRESH_INTERVAL_MINUTES} minutes"
else
  cat > "/etc/systemd/system/${REFRESH_SERVICE_NAME}.service" <<EOF
[Unit]
Description=WelOPC AI Signal Radar data refresh

[Service]
Type=oneshot
ExecStart=/bin/false
EOF
  systemctl daemon-reload
  echo "Python3 runtime not found. Dynamic refresh timer was not enabled."
  echo "Install Python 3.9+ and rerun: AI_SIGNAL_BASE_PATH=${APP_BASE_PATH:-/ai-hot} bash deploy/server_deploy.sh"
fi

echo "[6/7] Configuring optional web entry"
if [ -n "${APP_BASE_PATH}" ]; then
  APP_BASE_PATH="/${APP_BASE_PATH#/}"
  APP_BASE_PATH="${APP_BASE_PATH%/}"

  if command -v httpd >/dev/null 2>&1 && [ -d /etc/httpd/conf.d ]; then
    cat > "/etc/httpd/conf.d/${APP_NAME}.conf" <<EOF
# ${APP_NAME} is mounted under the main website path.
# The files stay outside the main website release directory.
RedirectMatch 302 ^${APP_BASE_PATH}$ ${APP_BASE_PATH}/
Alias ${APP_BASE_PATH}/ "${WEB_ROOT}/"

<Directory "${WEB_ROOT}">
    Options FollowSymLinks
    AllowOverride None
    Require all granted
    DirectoryIndex index.html
    FallbackResource ${APP_BASE_PATH}/index.html
</Directory>

<Directory "${WEB_ROOT}/data">
    Options FollowSymLinks
    AllowOverride None
    Require all granted
    FallbackResource disabled
    Header set Cache-Control "no-store"
</Directory>

ErrorLog /var/log/httpd/${APP_NAME}_error.log
CustomLog /var/log/httpd/${APP_NAME}_access.log combined
EOF
    chown -R apache:apache "${WEB_ROOT}" 2>/dev/null || true
    restorecon -Rv "${WEB_ROOT}" >/tmp/${APP_NAME}-restorecon.log 2>&1 || true
    apachectl configtest
    systemctl reload httpd || systemctl restart httpd
    echo "Apache path enabled: ${APP_BASE_PATH}/"
  else
    echo "APP_BASE_PATH is set, but Apache httpd was not found. Static port is still running."
  fi
elif [ -n "${APP_DOMAIN}" ]; then
  if command -v nginx >/dev/null 2>&1 && [ -d /etc/nginx/conf.d ]; then
    cat > "/etc/nginx/conf.d/${APP_NAME}.conf" <<EOF
server {
    listen 80;
    server_name ${APP_DOMAIN};

    root ${WEB_ROOT};
    index index.html;

    access_log /var/log/nginx/${APP_NAME}.access.log;
    error_log /var/log/nginx/${APP_NAME}.error.log;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /data/ {
        add_header Cache-Control "no-store";
        try_files \$uri =404;
    }
}
EOF
    nginx -t
    systemctl reload nginx || systemctl restart nginx
    echo "Nginx vhost enabled: http://${APP_DOMAIN}/"
  elif command -v httpd >/dev/null 2>&1 && [ -d /etc/httpd/conf.d ]; then
    cat > "/etc/httpd/conf.d/${APP_NAME}.conf" <<EOF
<VirtualHost *:80>
    ServerName ${APP_DOMAIN}
    DocumentRoot ${WEB_ROOT}
    DirectoryIndex index.html

    <Directory "${WEB_ROOT}">
        Options FollowSymLinks
        AllowOverride None
        Require all granted
        FallbackResource /index.html
    </Directory>

    <Directory "${WEB_ROOT}/data">
        Options FollowSymLinks
        AllowOverride None
        Require all granted
        FallbackResource disabled
    </Directory>

    ErrorLog /var/log/httpd/${APP_NAME}_error.log
    CustomLog /var/log/httpd/${APP_NAME}_access.log combined
</VirtualHost>
EOF
    chown -R apache:apache "${WEB_ROOT}" 2>/dev/null || true
    restorecon -Rv "${WEB_ROOT}" >/tmp/${APP_NAME}-restorecon.log 2>&1 || true
    apachectl configtest
    systemctl reload httpd || systemctl restart httpd
    echo "Apache vhost enabled: http://${APP_DOMAIN}/"
  else
    echo "Nginx/Apache not found. Domain vhost skipped. Static port is still running."
  fi
else
  echo "AI_SIGNAL_DOMAIN not set. Domain vhost skipped."
fi

echo "[7/7] Done"
echo "Static port URL: http://$(hostname -I | awk '{print $1}'):${STATIC_PORT}/"
if [ -n "${APP_DOMAIN}" ]; then
  echo "Domain URL: http://${APP_DOMAIN}/"
  echo "Make sure DNS A record points ${APP_DOMAIN} to this server IP."
fi
if [ -n "${APP_BASE_PATH}" ]; then
  echo "Path URL: ${APP_BASE_PATH}/"
fi
if systemctl list-unit-files "${REFRESH_SERVICE_NAME}.timer" >/dev/null 2>&1; then
  systemctl list-timers "${REFRESH_SERVICE_NAME}.timer" --no-pager 2>/dev/null || true
fi
echo "App root: ${APP_ROOT}"
echo "Web root: ${WEB_ROOT}"
echo "Env file: ${APP_ROOT}/.env"
