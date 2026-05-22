from __future__ import annotations

import argparse
import base64
import email.utils
import hashlib
import hmac
import html
import http.cookiejar
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
import traceback
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

APP_ROOT = Path(os.getenv("AIHOT_APP_ROOT", "/opt/welopc-ai-signal-radar"))
RUNTIME_ROOT = Path(os.getenv("AIHOT_RUNTIME_ROOT", "/opt/welopc-ai-signal-radar-runtime"))
WEB_ROOT = Path(os.getenv("AIHOT_WEB_ROOT", "/var/www/welopc-ai-signal-radar"))
DB_PATH = Path(os.getenv("AIHOT_DB_PATH", str(RUNTIME_ROOT / "aihot_repro.sqlite3")))
LATEST_JSON_PATH = Path(os.getenv("AIHOT_LATEST_JSON", str(WEB_ROOT / "data" / "latest.json")))
CREDENTIALS_PATH = Path(os.getenv("AIHOT_CREDENTIALS_PATH", str(RUNTIME_ROOT / "admin-credentials.txt")))
OPC_CONFIG_PATH = Path(os.getenv("AIHOT_OPC_CONFIG", str(APP_ROOT / "configs" / "opc_intelligence.json")))
MP_SOURCES_PATH = Path(os.getenv("AIHOT_MP_SOURCES", str(APP_ROOT / "configs" / "mp_sources.json")))
SERVICE_NAME = "welopc-aihot-repro"
TOKEN_TTL_SECONDS = 24 * 60 * 60
PBKDF2_ROUNDS = 260_000
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_THINKING = os.getenv("DEEPSEEK_THINKING", "enabled").strip().lower()
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "high").strip().lower()
ENRICH_PROMPT_VERSION = "dynamic-ai-hot-v6-independent-channel-fit"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | bytes | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)
    except Exception:
        return fallback


def compact_text(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").replace("\u0000", " ").split())
    if limit and len(text) > limit:
        return text[: max(limit - 1, 1)].rstrip() + "..."
    return text


def parse_item_time(value: Any) -> str:
    text = compact_text(value)
    if not text:
        return now_iso()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return now_iso()


def parse_iso_datetime(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(compact_text(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def epoch_ms(value: Any) -> int:
    return int(parse_iso_datetime(value).timestamp() * 1000)


def date_key(value: Any) -> str:
    return parse_iso_datetime(value).date().isoformat()


def date_label(value: Any) -> str:
    dt = parse_iso_datetime(value)
    return f"{dt.month}月{dt.day}日"


def time_label(value: Any) -> str:
    dt = parse_iso_datetime(value)
    return dt.strftime("%H:%M")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return now_iso()


def stable_uid(*parts: Any) -> str:
    raw = "|".join(compact_text(part).lower() for part in parts if compact_text(part))
    return hashlib.sha256((raw or secrets.token_urlsafe(16)).encode("utf-8")).hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode((data + ("=" * (-len(data) % 4))).encode("ascii"))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def get_db() -> sqlite3.Connection:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            channel TEXT NOT NULL,
            url TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            weight REAL NOT NULL DEFAULT 1,
            last_status TEXT,
            last_count INTEGER NOT NULL DEFAULT 0,
            last_checked_at TEXT,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feed_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            title_zh TEXT NOT NULL,
            summary TEXT,
            summary_zh TEXT,
            url TEXT,
            source_name TEXT,
            source_kind TEXT,
            channel TEXT NOT NULL,
            published_at TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            item_type TEXT NOT NULL,
            importance REAL NOT NULL DEFAULT 0,
            quality_score REAL NOT NULL DEFAULT 0,
            final_score REAL NOT NULL DEFAULT 0,
            ai_selected INTEGER NOT NULL DEFAULT 0,
            ai_selected_reason TEXT,
            ai_tags_json TEXT NOT NULL DEFAULT '[]',
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            quality_axes_json TEXT NOT NULL DEFAULT '{}',
            editorial_judgment TEXT,
            raw_json TEXT NOT NULL DEFAULT '{}',
            source_origin TEXT NOT NULL DEFAULT 'dynamic_collector',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feed_items_public ON feed_items(ai_selected, channel, published_at, final_score);
        CREATE INDEX IF NOT EXISTS idx_feed_items_url ON feed_items(url);
        CREATE TABLE IF NOT EXISTS daily_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_date TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT,
            content_json TEXT NOT NULL DEFAULT '{}',
            markdown TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            generated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mp_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            account_name TEXT NOT NULL,
            url TEXT,
            published_at TEXT,
            summary TEXT,
            heat_score REAL NOT NULL DEFAULT 0,
            anomaly_score REAL NOT NULL DEFAULT 0,
            ai_relevance_score REAL NOT NULL DEFAULT 0,
            tags_json TEXT NOT NULL DEFAULT '[]',
            raw_json TEXT NOT NULL DEFAULT '{}',
            source_origin TEXT NOT NULL DEFAULT 'manual_import',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wechat_sources (
            uid TEXT PRIMARY KEY,
            account_name TEXT NOT NULL,
            biz TEXT,
            avatar_url TEXT,
            intro TEXT,
            source_type TEXT NOT NULL DEFAULT 'manual',
            enabled INTEGER NOT NULL DEFAULT 1,
            feed_url TEXT,
            collector_hint TEXT,
            note TEXT,
            sample_article_url TEXT,
            sample_title TEXT,
            last_discovered_at TEXT,
            last_article_at TEXT,
            extra_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wechat_source_articles (
            uid TEXT PRIMARY KEY,
            source_uid TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            summary TEXT,
            html_excerpt TEXT,
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(source_uid) REFERENCES wechat_sources(uid) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_source_articles_source ON wechat_source_articles(source_uid, published_at);
        CREATE TABLE IF NOT EXISTS strategy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            weight REAL NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS strategy_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            vote TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            item_count INTEGER NOT NULL DEFAULT 0,
            selected_count INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            log_text TEXT
        );
        CREATE TABLE IF NOT EXISTS source_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_uid TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_kind TEXT,
            channel TEXT,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            detail TEXT,
            elapsed_ms INTEGER NOT NULL DEFAULT 0,
            checked_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_source_health_checked ON source_health(checked_at);
        CREATE TABLE IF NOT EXISTS access_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            query_json TEXT NOT NULL DEFAULT '{}',
            user_agent TEXT,
            remote_addr TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            eval_type TEXT NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 0,
            score REAL NOT NULL DEFAULT 0,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS item_enrichments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_item_enrichments_item ON item_enrichments(item_id, status, created_at);
        CREATE TABLE IF NOT EXISTS mp_enrichments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mp_article_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mp_enrichments_item ON mp_enrichments(mp_article_id, status, created_at);
        CREATE TABLE IF NOT EXISTS item_duplicates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            duplicate_item_id INTEGER NOT NULL,
            score REAL NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(item_id, duplicate_item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_item_duplicates_item ON item_duplicates(item_id);
        CREATE TABLE IF NOT EXISTS channel_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            item_uid TEXT NOT NULL,
            source_channel TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            base_score REAL NOT NULL DEFAULT 0,
            model_score REAL NOT NULL DEFAULT 0,
            selected INTEGER NOT NULL DEFAULT 0,
            reasons_json TEXT NOT NULL DEFAULT '[]',
            flags_json TEXT NOT NULL DEFAULT '[]',
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(channel, item_type, item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_channel_candidates_channel_score ON channel_candidates(channel, score);
        CREATE TABLE IF NOT EXISTS channel_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            item_uid TEXT NOT NULL,
            source_channel TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            source_name TEXT,
            url TEXT,
            published_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            reasons_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(channel, item_type, item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_channel_items_channel_rank ON channel_items(channel, rank, score);
        CREATE INDEX IF NOT EXISTS idx_channel_items_channel_time ON channel_items(channel, published_at);
        """
    )
    ensure_wechat_source_indexes(conn)
    ensure_column(conn, "feed_items", "source_origin", "TEXT NOT NULL DEFAULT 'dynamic_collector'")
    ensure_column(conn, "feed_items", "provenance_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "mp_articles", "source_origin", "TEXT NOT NULL DEFAULT 'manual_import'")
    ensure_column(conn, "mp_articles", "provenance_json", "TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
    seed_strategy_rules(conn)


def ensure_wechat_source_indexes(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_wechat_sources_biz'"
    ).fetchone()
    sql = compact_text(row["sql"] if row else "")
    if " WHERE " in sql.upper():
        conn.execute("DROP INDEX IF EXISTS idx_wechat_sources_biz")
        row = None
    if not row:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wechat_sources_biz ON wechat_sources(biz)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_source_articles_source ON wechat_source_articles(source_uid, published_at)"
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_config(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    ts = now_iso()
    conn.execute(
        "INSERT INTO app_config(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, ts),
    )
    conn.commit()


def get_json_config(conn: sqlite3.Connection, key: str, fallback: Any = None) -> Any:
    raw = get_config(conn, key, "")
    data = json_loads(raw, None)
    return fallback if data is None else data


def set_json_config(conn: sqlite3.Connection, key: str, value: Any) -> None:
    set_config(conn, key, json_dumps(value))


def cookie_row(
    *,
    name: str,
    value: str,
    domain: str = "mp.weixin.qq.com",
    path: str = "/",
    secure: bool = True,
    expires: int | None = None,
) -> dict[str, Any]:
    return {
        "name": compact_text(name, limit=120),
        "value": str(value or ""),
        "domain": compact_text(domain, limit=255) or "mp.weixin.qq.com",
        "path": compact_text(path, limit=120) or "/",
        "secure": bool(secure),
        "expires": int(expires) if expires else None,
    }


def build_cookie(value: dict[str, Any]) -> http.cookiejar.Cookie | None:
    name = compact_text(value.get("name"), limit=120)
    if not name:
        return None
    domain = compact_text(value.get("domain"), limit=255) or "mp.weixin.qq.com"
    path = compact_text(value.get("path"), limit=120) or "/"
    secure = bool(value.get("secure", True))
    expires_raw = value.get("expires")
    try:
        expires = int(expires_raw) if expires_raw not in (None, "", 0, "0") else None
    except Exception:
        expires = None
    domain_specified = bool(domain)
    domain_initial_dot = domain.startswith(".")
    return http.cookiejar.Cookie(
        version=0,
        name=name,
        value=str(value.get("value") or ""),
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=domain_specified,
        domain_initial_dot=domain_initial_dot,
        path=path,
        path_specified=True,
        secure=secure,
        expires=expires,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


class WechatMpPortalClient:
    base_url = "https://mp.weixin.qq.com"
    home_url = "https://mp.weixin.qq.com/"
    api_home_url = "https://mp.weixin.qq.com/cgi-bin/home"

    def __init__(self, cookie_rows: list[dict[str, Any]] | None = None):
        self.cookiejar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookiejar))
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        for row in cookie_rows or []:
            cookie = build_cookie(row)
            if cookie is not None:
                self.cookiejar.set_cookie(cookie)

    def cookies(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for cookie in self.cookiejar:
            rows.append(
                cookie_row(
                    name=cookie.name,
                    value=cookie.value,
                    domain=cookie.domain or "mp.weixin.qq.com",
                    path=cookie.path or "/",
                    secure=bool(cookie.secure),
                    expires=int(cookie.expires) if cookie.expires else None,
                )
            )
        return rows

    def cookie_string(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.cookiejar)

    def add_cookie(self, *, name: str, value: str, domain: str = "mp.weixin.qq.com", path: str = "/", secure: bool = True, expires: int | None = None) -> None:
        cookie = build_cookie(cookie_row(name=name, value=value, domain=domain, path=path, secure=secure, expires=expires))
        if cookie is not None:
            self.cookiejar.set_cookie(cookie)

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 25,
    ) -> tuple[bytes, Any, str]:
        final_url = url
        if params:
            query = urlencode({key: value for key, value in params.items() if value is not None})
            if query:
                final_url = url + ("&" if "?" in url else "?") + query
        request_data: bytes | None = None
        if isinstance(data, dict):
            request_data = urlencode({key: value for key, value in data.items() if value is not None}).encode("utf-8")
        elif isinstance(data, bytes):
            request_data = data
        merged_headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
        }
        if data is not None and "Content-Type" not in (headers or {}):
            merged_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        if headers:
            merged_headers.update(headers)
        req = urllib.request.Request(final_url, data=request_data, headers=merged_headers, method=method.upper())
        with self.opener.open(req, timeout=timeout) as response:
            body = response.read(3_000_000)
            response_headers = response.headers
            response_url = response.geturl()
        return body, response_headers, response_url

    def request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 25,
    ) -> tuple[dict[str, Any], Any, str]:
        body, response_headers, response_url = self.request(url, method=method, params=params, data=data, headers=headers, timeout=timeout)
        payload = json_loads(body, {})
        if not isinstance(payload, dict):
            raise ValueError("wechat_mp_invalid_json")
        return payload, response_headers, response_url

    def start_auth(self) -> dict[str, Any]:
        self.request(self.home_url, timeout=25)
        fingerprint = secrets.token_hex(16)
        auth_uuid = secrets.token_hex(16)
        self.add_cookie(name="uuid", value=auth_uuid, domain="mp.weixin.qq.com", path="/", secure=True)
        payload, _, _ = self.request_json(
            f"{self.base_url}/cgi-bin/bizlogin?action=startlogin",
            method="POST",
            data={
                "fingerprint": fingerprint,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
                "redirect_url": "/cgi-bin/settingpage?t=setting/index&action=index&token=&lang=zh_CN",
                "login_type": "3",
            },
            timeout=25,
        )
        if int(((payload.get("base_resp") or {}).get("ret") or 0)) != 0:
            raise RuntimeError(f"wechat_mp_startlogin_failed:{json_dumps(payload)[:240]}")
        image, _, _ = self.request(
            f"{self.base_url}/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "uuid": auth_uuid, "random": str(int(time.time() * 1000))},
            headers={"Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"},
            timeout=25,
        )
        if not image:
            raise RuntimeError("wechat_mp_qr_empty")
        return {
            "uuid": auth_uuid,
            "fingerprint": fingerprint,
            "cookies": self.cookies(),
            "qrImageDataUrl": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
        }

    def check_auth(self, *, fingerprint: str) -> dict[str, Any]:
        payload, _, _ = self.request_json(
            f"{self.base_url}/cgi-bin/scanloginqrcode",
            params={"action": "ask", "fingerprint": fingerprint, "lang": "zh_CN", "f": "json", "ajax": "1"},
            headers={"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest"},
            timeout=20,
        )
        status = int(payload.get("status") or 0)
        return {"status": status, "payload": payload}

    def finalize_auth(self, *, fingerprint: str) -> dict[str, Any]:
        body, _, response_url = self.request(
            f"{self.base_url}/cgi-bin/bizlogin?action=login",
            method="POST",
            data={
                "userlang": "zh_CN",
                "redirect_url": "",
                "cookie_forbidden": "0",
                "cookie_cleaned": "0",
                "plugin_used": "0",
                "login_type": "3",
                "fingerprint": fingerprint,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            timeout=25,
        )
        text = body.decode("utf-8", errors="replace")
        token = ""
        for candidate in (response_url, text):
            match = re.search(r"token=([^&\\s\"']+)", candidate)
            if match:
                token = compact_text(match.group(1), limit=120)
                break
        if not token:
            raise RuntimeError("wechat_mp_token_missing")
        account = self.account_info(token)
        return {
            "token": token,
            "cookieString": self.cookie_string(),
            "cookies": self.cookies(),
            "account": account,
        }

    def account_info(self, token: str) -> dict[str, Any]:
        payload, _, _ = self.request_json(
            f"{self.base_url}/cgi-bin/switchacct",
            params={
                "action": "get_acct_list",
                "fingerprint": secrets.token_hex(16),
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/cgi-bin/home?t=home/index&lang=zh_CN&token={token}",
            },
            timeout=20,
        )
        biz_list = ((payload.get("biz_list") or {}).get("list") or []) if isinstance(payload, dict) else []
        first = biz_list[0] if biz_list else {}
        if not isinstance(first, dict):
            first = {}
        return {
            "username": compact_text(first.get("username"), limit=120),
            "nickname": compact_text(first.get("nickname") or first.get("nick_name"), limit=160),
            "headimgurl": compact_text(first.get("headimgurl"), limit=1000),
            "alias": compact_text(first.get("alias"), limit=120),
        }

    def search_biz(self, *, token: str, query: str, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        payload, _, _ = self.request_json(
            f"{self.base_url}/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "begin": max(0, int(offset)),
                "count": max(1, min(int(limit), 20)),
                "query": query,
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            headers={"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest"},
            timeout=20,
        )
        publish_page = payload.get("publish_page")
        if isinstance(publish_page, str):
            payload["publish_page"] = json_loads(publish_page, {})
        if int(((payload.get("base_resp") or {}).get("ret") or 0)) != 0:
            raise RuntimeError(f"wechat_mp_search_failed:{json_dumps(payload)[:240]}")
        return payload

    def fetch_articles(self, *, token: str, fakeid: str, count: int = 10, begin: int = 0) -> dict[str, Any]:
        payload, _, _ = self.request_json(
            f"{self.base_url}/cgi-bin/appmsgpublish",
            params={
                "sub": "list",
                "sub_action": "list_ex",
                "begin": max(0, int(begin)),
                "count": max(1, min(int(count), 20)),
                "fakeid": fakeid,
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/cgi-bin/appmsg?t=media/appmsg_edit_v2&token={token}&lang=zh_CN",
            },
            timeout=20,
        )
        for key in ("publish_page", "publish_info"):
            if isinstance(payload.get(key), str):
                payload[key] = json_loads(payload.get(key), {})
        if int(((payload.get("base_resp") or {}).get("ret") or 0)) != 0:
            raise RuntimeError(f"wechat_mp_fetch_articles_failed:{json_dumps(payload)[:240]}")
        return payload


def ensure_secret(conn: sqlite3.Connection) -> str:
    secret = get_config(conn, "secret_key")
    if not secret:
        secret = secrets.token_urlsafe(48)
        set_config(conn, "secret_key", secret)
    return secret


def ensure_admin(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if row:
        return None
    password = os.getenv("AIHOT_BOOTSTRAP_PASSWORD") or secrets.token_urlsafe(18)
    ts = now_iso()
    conn.execute(
        "INSERT INTO users(username,password_hash,role,active,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        ("admin", hash_password(password), "admin", 1, ts, ts),
    )
    conn.commit()
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(
        "AIHOT admin credentials\n"
        f"created_at={ts}\n"
        "url=https://welopc.com/ai-hot/admin\n"
        "username=admin\n"
        f"password={password}\n",
        encoding="utf-8",
    )
    os.chmod(CREDENTIALS_PATH, 0o600)
    return password


def seed_strategy_rules(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) AS c FROM strategy_rules").fetchone()["c"]:
        return
    ts = now_iso()
    rows = [
        ("official_authority", "官方信源优先", "OpenAI、Anthropic、Google、Hugging Face 等一手信源获得基础权重。", 1.4, 1, {"channel": "firstParty"}),
        ("github_momentum", "开发者增长动量", "GitHub 今日星标、总星标、近期活跃度用于识别开发者关注。", 1.25, 1, {"channel": "github"}),
        ("product_builder_surface", "产品与构建者信号", "Product Hunt 中带 API、SDK、开源或文档表面的 AI 产品更容易进入候选。", 1.1, 1, {"channel": "product"}),
        ("community_cross_check", "社区交叉验证", "Reddit、YouTube、arXiv 与官方/GitHub 互相印证时提升精选概率。", 1.2, 1, {"channel": "community"}),
        ("recency_decay", "时间衰减", "近期内容优先，旧内容除非有二次爆发会降低排序。", 1.0, 1, {"fresh_hours": 48}),
        ("duplicate_penalty", "重复惩罚", "同源重复、标题重复和镜像链接会合并并降低重复展示。", 1.0, 1, {}),
    ]
    conn.executemany(
        "INSERT INTO strategy_rules(code,name,description,weight,enabled,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        [(code, name, desc, weight, enabled, json_dumps(cfg), ts, ts) for code, name, desc, weight, enabled, cfg in rows],
    )
    conn.commit()


def channel_rules() -> list[dict[str, Any]]:
    return [
        {
            "code": "selected",
            "channel": "selected",
            "name": "精选",
            "description": "从全量非 X 信号中挑选 finalScore 高、来源权威、近期且具备开发者/社区/官方证据的内容。",
            "include": ["ai_selected = true"],
            "exclude": ["X allowlist"],
            "sort": ["published_at desc", "final_score desc"],
            "operators": ["后台可手动设为精选或取消精选", "日报优先引用精选条目"],
        },
        {
            "code": "all",
            "channel": "all",
            "name": "全部 AI 动态",
            "description": "所有非 X 信源采集、标准化、去重后的 AI 动态池。",
            "include": ["official_feed", "official_web", "community_feed", "youtube_channel", "github_release", "github_trending", "github_momentum", "product_hunt", "trendradar"],
            "exclude": ["x_allowlist"],
            "sort": ["published_at desc", "id desc"],
        },
        {
            "code": "firstParty",
            "channel": "firstParty",
            "name": "官方/一手信源",
            "description": "OpenAI、Anthropic、Google/DeepMind、Hugging Face、DeepSeek、Qwen、腾讯混元等官方 RSS 或官网探测。",
            "include": ["official_feed", "official_web"],
            "scoreSignals": ["官方权威加权", "页面探测命中", "发布新模型/产品/能力词"],
        },
        {
            "code": "github",
            "channel": "github",
            "name": "GitHub 动向",
            "description": "仓库 release、daily trending、stars 增长、fork 与近期 activity，用于识别开发者侧爆发。",
            "include": ["github_release", "github_trending", "github_momentum"],
            "scoreSignals": ["stars_today", "star_delta", "total_stars", "headline_candidate"],
        },
        {
            "code": "product",
            "channel": "product",
            "name": "Product Hunt",
            "description": "Product Hunt 今日 AI/agent/devtools 产品，结合 votes、comments、topic fit 和 builder surface。",
            "include": ["product_hunt"],
            "scoreSignals": ["votes", "comments", "AI topic", "API/SDK/docs/open-source surface"],
        },
        {
            "code": "community",
            "channel": "community",
            "name": "社区/视频/论文",
            "description": "Reddit、YouTube、arXiv 等社区证据层，用于发现讨论热度和交叉验证。",
            "include": ["community_feed", "youtube_channel", "arxiv"],
            "scoreSignals": ["发布时间", "标题/摘要 AI 关键词", "与官方/GitHub/Product 信号的交叉验证"],
        },
        {
            "code": "mp",
            "channel": "mp",
            "name": "公众号爆文",
            "description": "独立动态模块，从配置的公众号 RSS/JSON/API 源抓取，不允许使用公开页面样本预设，按热度、异常传播、AI 相关度和时效排序。",
            "include": ["mp_rss", "mp_json_api", "admin_owned_import"],
            "scoreSignals": ["AI 关键词", "发布时间", "账号权重", "阅读/点赞/转发", "标题异常传播信号"],
        },
        {
            "code": "opcSolo",
            "channel": "opcSolo",
            "name": "OPC一人公司",
            "description": "虚拟聚合频道，数据来源覆盖所有非 X 频道，筛选能帮助一人公司完成产品构建、获客、自动化、内容生产、运营和交付的 AI 信息。",
            "include": ["all non-X channels", "mp_articles", "official", "github", "product", "community", "news"],
            "exclude": ["纯论文且无工具/产品/商业化线索", "X"],
            "scoreSignals": ["自动化/Agent", "低成本部署", "产品化", "获客/内容", "API/SDK", "开源可用", "运营效率"],
        },
    ]


def public_channel_rule(channel: str) -> dict[str, Any]:
    rules = {rule["channel"]: rule for rule in channel_rules()}
    semantic = {
        "firstParty": {
            "description": "只看官方/一手发布：OpenAI、Anthropic、Google/DeepMind、Hugging Face、Apple、xAI、Claude、Cursor 等来源；排除媒体转载、个人博客和社区讨论。",
            "include": ["官方来源名称命中", "official_feed / official_web", "模型/产品/研究一手发布"],
            "exclude": ["GitHub Trending", "Reddit", "个人博客", "媒体资讯"],
        },
        "news": {
            "description": "只看媒体/资讯/行业事件：IT之家、新闻 RSS、网页榜单、监管/商业/融资/诉讼等；排除官方产品发布、GitHub 仓库和社区论文讨论。",
            "include": ["媒体资讯", "行业事件", "监管/版权/商业化", "TrendRadar/Web list"],
            "exclude": ["官方源", "GitHub", "Reddit/arXiv", "公众号"],
        },
        "github": {
            "description": "只看开发者生态：GitHub Trending、Release、仓库增长、GitHub Blog 和代码/开源相关条目。",
            "include": ["github_* source_kind", "GitHub source", "repo/release/open-source"],
            "exclude": ["纯媒体新闻", "纯公众号", "无代码/仓库线索的产品稿"],
        },
        "product": {
            "description": "只看产品/工具/可用能力：上线、插件、API、SDK、CLI、App、平台、工作流、MCP、Agent 工具等，来源不限。",
            "include": ["产品更新", "工具/API/SDK", "平台/插件/CLI/App", "可直接使用或集成"],
            "exclude": ["纯论文", "纯观点", "没有工具或产品表面的行业新闻"],
        },
        "community": {
            "description": "只看社区/论文/讨论层：Reddit、Hacker News、arXiv、社区热门论文和用户讨论。",
            "include": ["Reddit", "Hacker News", "arXiv", "论文/研究", "社区讨论"],
            "exclude": ["官方发布", "媒体快讯", "Product Hunt 产品榜"],
        },
        "all": {
            "description": "所有非 X 动态内容池，不做频道压缩，用于按时间线浏览。",
            "include": ["所有非 X feed_items"],
            "exclude": ["X"],
        },
    }
    base = rules.get(channel, {"channel": channel, "name": channel, "description": ""})
    return {**base, **semantic.get(channel, {})}


def feed_channel_rule(mode: str, channel: str) -> dict[str, Any]:
    normalized_mode = compact_text(mode, limit=40) or "selected"
    normalized_channel = compact_text(channel, limit=40) or "all"
    if normalized_channel == "opcSolo":
        rule = next((item for item in channel_rules() if item.get("channel") == "opcSolo"), None)
        return dict(rule or {"code": "opcSolo", "channel": "opcSolo", "name": "OPC一人公司", "description": ""})
    if normalized_mode == "selected":
        if normalized_channel in {"", "all"}:
            return public_channel_rule("selected")
        base = public_channel_rule(normalized_channel)
        include = ["ai_selected = true", *[item for item in base.get("include", []) if item != "ai_selected = true"]]
        return {
            **base,
            "code": f"selected:{normalized_channel}",
            "name": f"{base.get('name') or normalized_channel}精选",
            "description": f"只显示“{base.get('name') or normalized_channel}”范围内已入选精选的内容。",
            "include": include,
        }
    return public_channel_rule(normalized_channel)


def channel_filter_clause(channel: str) -> tuple[str, list[Any]]:
    if not channel or channel == "all":
        return "", []
    if channel == "x":
        return "0=1", []
    source = "lower(coalesce(source_name,''))"
    kind = "lower(coalesce(source_kind,''))"
    title = "lower(coalesce(title_zh,title,''))"
    summary = "lower(coalesce(summary_zh,summary,''))"
    tags = "lower(coalesce(ai_tags_json,''))"
    item_type = "lower(coalesce(item_type,''))"
    text = f"({title} || ' ' || {summary} || ' ' || {tags} || ' ' || {item_type} || ' ' || {source} || ' ' || {kind})"
    official_names = (
        f"({source} LIKE '%openai%' OR {source} LIKE '%anthropic%' OR {source} LIKE '%claude%' "
        f"OR {source} LIKE '%google%' OR {source} LIKE '%deepmind%' OR {source} LIKE '%hugging face%' "
        f"OR {source} LIKE '%apple machine learning%' OR {source} LIKE '%xai%' OR {source} LIKE '%cursor%')"
    )
    if channel == "firstParty":
        return (
            f"({official_names} OR {kind} IN ('official_feed','official_web')) "
            f"AND {source} NOT LIKE '%github%' AND {source} NOT LIKE '%simon%' AND {source} NOT LIKE '%reddit%'",
            [],
        )
    if channel == "news":
        return (
            f"({source} LIKE '%it之家%' OR {source} LIKE '%news%' OR {kind} LIKE '%web%' OR {kind} LIKE '%trendradar%' "
            f"OR {text} LIKE '%监管%' OR {text} LIKE '%版权%' OR {text} LIKE '%诉讼%' OR {text} LIKE '%商业%' OR {text} LIKE '%融资%' OR {text} LIKE '%行业%') "
            f"AND channel NOT IN ('github','community','product') "
            f"AND NOT ({official_names})",
            [],
        )
    if channel == "github":
        return (
            f"(channel='github' OR {source} LIKE '%github%' OR {kind} LIKE '%github%' OR {text} LIKE '%github%' "
            f"OR {text} LIKE '%开源%' OR {text} LIKE '%仓库%' OR {text} LIKE '%repo%' OR {text} LIKE '%release%')",
            [],
        )
    if channel == "product":
        return (
            f"({text} LIKE '%产品%' OR {text} LIKE '%工具%' OR {text} LIKE '%上线%' OR {text} LIKE '%发布%' "
            f"OR {text} LIKE '%api%' OR {text} LIKE '%sdk%' OR {text} LIKE '%插件%' OR {text} LIKE '%plugin%' "
            f"OR {text} LIKE '%cli%' OR {text} LIKE '%app%' OR {text} LIKE '%平台%' OR {text} LIKE '%工作流%' "
            f"OR {text} LIKE '%mcp%' OR {text} LIKE '%agent%' OR {text} LIKE '%智能体%') "
            f"AND channel NOT IN ('github','community') AND {source} NOT LIKE '%github%' AND {text} NOT LIKE '%纯论文%'",
            [],
        )
    if channel == "community":
        return (
            f"(channel='community' OR {source} LIKE '%reddit%' OR {source} LIKE '%hacker news%' OR {source} LIKE '%daily papers%' "
            f"OR {kind} LIKE '%arxiv%' OR {kind} LIKE '%youtube%' OR {kind} LIKE '%community%' "
            f"OR ({text} LIKE '%论文%' OR {text} LIKE '%paper%' OR {text} LIKE '%benchmark%')) "
            f"AND channel!='github' AND {source} NOT LIKE '%github%'",
            [],
        )
    return "channel=?", [channel]


def load_project_config() -> dict[str, Any]:
    if not OPC_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(OPC_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    projects = data.get("projects") if isinstance(data, dict) else {}
    project = projects.get("ai_daily_signal") if isinstance(projects, dict) else {}
    return project if isinstance(project, dict) else {}


def source_name_from_config(raw: dict[str, Any], fallback: str) -> str:
    return compact_text(
        raw.get("name")
        or raw.get("source_name")
        or raw.get("title")
        or raw.get("repo")
        or raw.get("handle")
        or raw.get("url")
        or fallback,
        limit=180,
    )


def seed_sources_from_config(conn: sqlite3.Connection) -> int:
    project = load_project_config()
    if not project:
        return 0
    count = 0

    def add(raw: dict[str, Any], *, default_kind: str, channel: str, fallback: str) -> None:
        nonlocal count
        if not isinstance(raw, dict):
            return
        kind = compact_text(raw.get("source_kind") or default_kind, limit=120)
        if infer_channel({"source_kind": kind, "source_name": source_name_from_config(raw, fallback)}) == "x":
            return
        upsert_source(
            conn,
            name=source_name_from_config(raw, fallback),
            source_kind=kind,
            channel=channel,
            status="configured",
            count=0,
            detail="configured source",
            url=compact_text(raw.get("url") or raw.get("feed_url") or raw.get("repo") or raw.get("website"), limit=1000),
            config=raw,
        )
        count += 1

    for raw in project.get("official_feeds", []) or []:
        add(raw, default_kind="official_feed", channel="firstParty", fallback="Official source")
    for raw in project.get("community_feeds", []) or []:
        add(raw, default_kind="community_feed", channel="community", fallback="Community source")
    for raw in project.get("youtube_channels", []) or []:
        add(raw, default_kind="youtube_channel", channel="community", fallback="YouTube channel")
    for raw in project.get("github_sources", []) or []:
        add(raw, default_kind="github_release", channel="github", fallback="GitHub source")

    if isinstance(project.get("github_trending"), dict) and project["github_trending"].get("enabled", True):
        add({"name": "GitHub Trending AI", **project["github_trending"]}, default_kind="github_trending", channel="github", fallback="GitHub Trending AI")
    if isinstance(project.get("github_momentum"), dict) and project["github_momentum"].get("enabled", True):
        add({"name": "GitHub Momentum", **project["github_momentum"]}, default_kind="github_momentum", channel="github", fallback="GitHub Momentum")
    if isinstance(project.get("product_hunt"), dict) and project["product_hunt"].get("enabled", True):
        add({"name": "Product Hunt AI", **project["product_hunt"]}, default_kind="product_hunt", channel="product", fallback="Product Hunt AI")
    if isinstance(project.get("trendradar_bridge"), dict) and project["trendradar_bridge"].get("enabled", False):
        add({"name": "TrendRadar Bridge", **project["trendradar_bridge"]}, default_kind="trendradar_hotlist", channel="news", fallback="TrendRadar Bridge")
    conn.commit()
    return count


def ensure_mp_sources_config() -> dict[str, Any]:
    if MP_SOURCES_PATH.exists():
        try:
            data = json.loads(MP_SOURCES_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"sources": []}
        except Exception:
            return {"sources": []}
    data = {
        "description": "公众号爆文模块动态配置。只允许真实 RSS/JSON/API 或自有采集器输出，不允许放公开页面样本文章。",
        "schema": {
            "type": "rss | json",
            "name": "公众号或榜单名称",
            "url": "RSS/JSON/API 地址，例如 RSSHub 微信公众号 route 或自有采集器输出",
            "title": "文章标题",
            "accountName": "公众号名称",
            "url": "文章链接",
            "publishedAt": "发布时间 ISO8601",
            "summary": "摘要",
            "heatScore": "热度分",
            "anomalyScore": "异常传播分",
            "aiRelevanceScore": "AI 相关度",
            "tags": ["标签"],
        },
        "sources": [],
    }
    MP_SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MP_SOURCES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(MP_SOURCES_PATH, 0o600)
    return data


def bool_config(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = compact_text(value).lower()
    if text in {"1", "true", "yes", "on", "enabled", "启用", "是"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "停用", "否"}:
        return False
    return default


def mp_source_id(raw: dict[str, Any]) -> str:
    explicit = compact_text(raw.get("id") or raw.get("uid") or raw.get("code"), limit=80)
    if explicit:
        base = explicit
    else:
        base = "mp_" + stable_uid(raw.get("name") or raw.get("source_name"), raw.get("url") or raw.get("feed_url") or raw.get("api_url"))[:12]
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-_").lower()
    return normalized or ("mp_" + stable_uid(json_dumps(raw))[:12])


def normalize_mp_source(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    source_type = normalize_kind(raw.get("type") or raw.get("source_kind") or "rss")
    if source_type == "api":
        source_type = "json_api"
    if source_type not in {"rss", "atom", "json", "json_api"}:
        source_type = "rss"
    name = source_name_from_config(raw, "公众号动态源")
    source = {
        "id": mp_source_id(raw),
        "name": compact_text(name, limit=120) or "公众号动态源",
        "type": source_type,
        "url": compact_text(raw.get("url") or raw.get("feed_url") or raw.get("api_url"), limit=1000),
        "enabled": bool_config(raw.get("enabled"), False),
        "weight": clamp_float(raw.get("weight") or 1, 0.1, 5.0, 1.0),
        "note": compact_text(raw.get("note") or raw.get("description"), limit=500),
    }
    for key in (
        "itemsPath",
        "itemPath",
        "titleField",
        "accountField",
        "urlField",
        "publishedField",
        "summaryField",
        "readsField",
        "likesField",
        "sharesField",
        "tagsField",
    ):
        value = compact_text(raw.get(key), limit=120)
        if value:
            source[key] = value
    return source


def mp_sources_config() -> dict[str, Any]:
    data = ensure_mp_sources_config()
    sources = []
    for source in data.get("sources", []) or []:
        if not isinstance(source, dict):
            continue
        normalized = normalize_mp_source(source)
        if not normalized.get("url") and compact_text(normalized.get("name")).startswith("示例"):
            continue
        sources.append(normalized)
    return {
        "description": data.get("description") or "公众号爆文模块动态配置。",
        "schema": data.get("schema") or {},
        "sources": sources,
    }


def save_mp_sources_config(data: dict[str, Any]) -> dict[str, Any]:
    sources = [normalize_mp_source(source) for source in data.get("sources", []) or [] if isinstance(source, dict)]
    for source in sources:
        blob = json_dumps(source).lower()
        if "aihot.virxact.com" in blob:
            raise ValueError("mp_source_must_not_reference_aihot_public_page")
    normalized = {
        "description": data.get("description") or "公众号爆文模块动态配置。只允许真实 RSS/JSON/API 或自有采集器输出，不允许放公开页面样本文章。",
        "schema": data.get("schema") or ensure_mp_sources_config().get("schema", {}),
        "sources": sources,
    }
    MP_SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MP_SOURCES_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(MP_SOURCES_PATH, 0o600)
    return normalized


def find_mp_source(source_id: str) -> dict[str, Any] | None:
    needle = compact_text(source_id)
    for source in mp_sources_config().get("sources", []):
        if source.get("id") == needle:
            return source
    return None


def upsert_mp_source_config(raw: dict[str, Any]) -> dict[str, Any]:
    source = normalize_mp_source(raw)
    if not source["name"]:
        raise ValueError("missing_source_name")
    if source["enabled"] and not source["url"]:
        raise ValueError("enabled_source_requires_url")
    config = mp_sources_config()
    updated: list[dict[str, Any]] = []
    replaced = False
    for current in config.get("sources", []):
        if current.get("id") == source["id"]:
            updated.append(source)
            replaced = True
        else:
            updated.append(current)
    if not replaced:
        updated.append(source)
    config["sources"] = updated
    save_mp_sources_config(config)
    return source


def delete_mp_source_config(source_id: str) -> bool:
    config = mp_sources_config()
    before = len(config.get("sources", []))
    config["sources"] = [source for source in config.get("sources", []) if source.get("id") != compact_text(source_id)]
    if len(config["sources"]) == before:
        return False
    save_mp_sources_config(config)
    return True


def json_path_get(data: Any, path: str) -> Any:
    current = data
    for part in [p for p in compact_text(path).split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current


def first_json_value(data: dict[str, Any], fields: list[str]) -> Any:
    for field in fields:
        if not field:
            continue
        value = json_path_get(data, field) if "." in field else data.get(field)
        if value not in (None, ""):
            return value
    return None


def parse_json_mp_items(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.loads(text)
    items_path = compact_text(source.get("itemsPath") or source.get("itemPath"))
    raw_items = json_path_get(data, items_path) if items_path else None
    if raw_items is None and isinstance(data, dict):
        for key in ("items", "articles", "data", "list", "results"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                raw_items = candidate
                break
            if isinstance(candidate, dict):
                nested = candidate.get("items") or candidate.get("articles") or candidate.get("list")
                if isinstance(nested, list):
                    raw_items = nested
                    break
    if raw_items is None and isinstance(data, list):
        raw_items = data
    rows: list[dict[str, Any]] = []
    for item in (raw_items or [])[:120]:
        if not isinstance(item, dict):
            continue
        account = first_json_value(item, [compact_text(source.get("accountField")), "accountName", "account_name", "account", "source", "author", "provider"])
        row = dict(item)
        row["title"] = first_json_value(item, [compact_text(source.get("titleField")), "title", "name", "headline"]) or ""
        row["accountName"] = account or source.get("name") or "公众号"
        row["url"] = first_json_value(item, [compact_text(source.get("urlField")), "url", "link", "articleUrl", "article_url"]) or ""
        row["publishedAt"] = first_json_value(item, [compact_text(source.get("publishedField")), "publishedAt", "published_at", "pubDate", "createdAt", "date", "time"]) or now_iso()
        row["summary"] = first_json_value(item, [compact_text(source.get("summaryField")), "summary", "description", "digest", "excerpt"]) or ""
        row["reads"] = first_json_value(item, [compact_text(source.get("readsField")), "reads", "readCount", "read_count", "views"])
        row["likes"] = first_json_value(item, [compact_text(source.get("likesField")), "likes", "likeCount", "like_count"])
        row["shares"] = first_json_value(item, [compact_text(source.get("sharesField")), "shares", "shareCount", "share_count", "forwards"])
        tags = first_json_value(item, [compact_text(source.get("tagsField")), "tags", "keywords"])
        if tags is not None:
            row["tags"] = tags if isinstance(tags, list) else [compact_text(tags)]
        row.setdefault("sourceOrigin", "third_party_api")
        row.setdefault("provider", source.get("name") or "公众号动态源")
        rows.append(row)
    return [row for row in rows if compact_text(row.get("title"))]


def parse_mp_source_payload(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    source_type = normalize_kind(source.get("type") or "rss")
    if source_type in {"json", "json_api", "api"}:
        return parse_json_mp_items(text, source)
    return parse_rss_or_atom(text, source)


def test_mp_source(raw: dict[str, Any]) -> dict[str, Any]:
    source = normalize_mp_source(raw)
    if not source["url"]:
        return {"status": "invalid", "source": source, "error": "missing_url", "items": [], "accepted": 0, "fetched": 0}
    started = time.time()
    text = fetch_text(source["url"], timeout=20)
    rows = parse_mp_source_payload(text, source)
    samples = []
    accepted = sum(1 for row in rows if mp_ai_relevance(row) >= 12 or row.get("aiRelevanceScore") or row.get("ai_relevance_score"))
    for row in rows[:20]:
        relevance = mp_ai_relevance(row)
        samples.append({
            "title": compact_text(row.get("title"), limit=160),
            "accountName": compact_text(row.get("accountName"), limit=120),
            "url": compact_text(row.get("url"), limit=300),
            "publishedAt": parse_item_time(row.get("publishedAt") or row.get("published_at")),
            "aiRelevanceScore": round(relevance, 2),
        })
    return {
        "status": "ok",
        "source": source,
        "fetched": len(rows),
        "accepted": accepted,
        "elapsedMs": int((time.time() - started) * 1000),
        "items": samples[:8],
    }


def default_wechat_auth_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "uuid": "",
        "fingerprint": "",
        "cookies": [],
        "cookieString": "",
        "token": "",
        "account": {},
        "qrImageDataUrl": "",
        "startedAt": None,
        "updatedAt": None,
        "expiresAt": None,
        "lastError": "",
    }


def wechat_auth_state(conn: sqlite3.Connection) -> dict[str, Any]:
    raw = get_json_config(conn, "wechat_mp_auth_state", default_wechat_auth_state())
    state = default_wechat_auth_state()
    if isinstance(raw, dict):
        state.update(raw)
    if not isinstance(state.get("cookies"), list):
        state["cookies"] = []
    if not isinstance(state.get("account"), dict):
        state["account"] = {}
    return state


def save_wechat_auth_state(conn: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
    payload = default_wechat_auth_state()
    if isinstance(state, dict):
        payload.update(state)
    payload["updatedAt"] = now_iso()
    set_json_config(conn, "wechat_mp_auth_state", payload)
    return payload


def clear_wechat_auth_state(conn: sqlite3.Connection) -> dict[str, Any]:
    return save_wechat_auth_state(conn, default_wechat_auth_state())


def sanitize_wechat_auth_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = default_wechat_auth_state()
    if isinstance(state, dict):
        raw.update(state)
    status = compact_text(raw.get("status"), limit=40) or "idle"
    token = compact_text(raw.get("token"), limit=240)
    cookie_string = compact_text(raw.get("cookieString"), limit=4000)
    return {
        "status": status,
        "authorized": status == "authorized" and bool(token and cookie_string),
        "uuid": compact_text(raw.get("uuid"), limit=120),
        "startedAt": raw.get("startedAt"),
        "updatedAt": raw.get("updatedAt"),
        "expiresAt": raw.get("expiresAt"),
        "hasToken": bool(token),
        "hasCookies": bool(cookie_string),
        "lastError": compact_text(raw.get("lastError"), limit=500),
        "qrImageDataUrl": raw.get("qrImageDataUrl") if status in {"waiting", "scanned"} else "",
        "account": raw.get("account") if isinstance(raw.get("account"), dict) else {},
    }


def start_wechat_mp_auth(conn: sqlite3.Connection) -> dict[str, Any]:
    client = WechatMpPortalClient()
    created = client.start_auth()
    state = save_wechat_auth_state(
        conn,
        {
            "status": "waiting",
            "uuid": created["uuid"],
            "fingerprint": created["fingerprint"],
            "cookies": created["cookies"],
            "cookieString": "",
            "token": "",
            "account": {},
            "qrImageDataUrl": created["qrImageDataUrl"],
            "startedAt": now_iso(),
            "lastError": "",
        },
    )
    return sanitize_wechat_auth_state(state)


def refresh_wechat_mp_auth(conn: sqlite3.Connection) -> dict[str, Any]:
    state = wechat_auth_state(conn)
    status = compact_text(state.get("status"), limit=40) or "idle"
    if status == "authorized" and compact_text(state.get("token")) and compact_text(state.get("cookieString")):
        return sanitize_wechat_auth_state(state)
    if not compact_text(state.get("fingerprint")):
        return sanitize_wechat_auth_state(state)
    client = WechatMpPortalClient(state.get("cookies") if isinstance(state.get("cookies"), list) else [])
    checked = client.check_auth(fingerprint=compact_text(state.get("fingerprint"), limit=120))
    code = int(checked.get("status") or 0)
    if code in {1, 3}:
        finalized = client.finalize_auth(fingerprint=compact_text(state.get("fingerprint"), limit=120))
        expiry = max([cookie.get("expires") or 0 for cookie in finalized.get("cookies", []) if isinstance(cookie, dict)] or [0])
        updated = save_wechat_auth_state(
            conn,
            {
                "status": "authorized",
                "uuid": state.get("uuid"),
                "fingerprint": state.get("fingerprint"),
                "cookies": finalized.get("cookies") or [],
                "cookieString": finalized.get("cookieString") or "",
                "token": finalized.get("token") or "",
                "account": finalized.get("account") or {},
                "qrImageDataUrl": "",
                "startedAt": state.get("startedAt"),
                "expiresAt": datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat() if expiry else None,
                "lastError": "",
            },
        )
        return sanitize_wechat_auth_state(updated)
    mapped = "scanned" if code in {2, 4} else "waiting"
    updated = save_wechat_auth_state(
        conn,
        {
            **state,
            "status": mapped,
            "cookies": client.cookies(),
            "lastError": "",
        },
    )
    return sanitize_wechat_auth_state(updated)


def search_result_biz(value: dict[str, Any]) -> str:
    direct = compact_text(value.get("biz") or value.get("__biz"), limit=255)
    if direct:
        return direct
    for key in ("link", "url", "articleUrl", "article_url"):
        candidate = compact_text(value.get(key), limit=1200)
        if candidate:
            parsed = wechat_url_value(candidate, "__biz")
            if parsed:
                return parsed
    return ""


def build_wechat_search_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("list") or ((payload.get("biz_list") or {}).get("list") if isinstance(payload.get("biz_list"), dict) else [])
    candidates: list[dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        candidate = {
            "accountName": compact_text(item.get("nickname") or item.get("nick_name") or item.get("name"), limit=160),
            "biz": search_result_biz(item),
            "fakeid": compact_text(item.get("fakeid") or item.get("fake_id"), limit=255),
            "alias": compact_text(item.get("alias"), limit=120),
            "avatarUrl": compact_text(item.get("round_head_img") or item.get("headimgurl") or item.get("avatar"), limit=1000),
            "intro": compact_text(item.get("signature") or item.get("desc") or item.get("description"), limit=500),
            "serviceType": compact_text(item.get("service_type"), limit=40),
            "verifyType": compact_text(item.get("verify_type"), limit=40),
            "raw": item,
        }
        if candidate["accountName"]:
            candidates.append(candidate)
    return candidates


def search_wechat_source_candidates(conn: sqlite3.Connection, query: str, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
    state = wechat_auth_state(conn)
    if compact_text(state.get("status")) != "authorized" or not compact_text(state.get("token")) or not compact_text(state.get("cookieString")):
        raise RuntimeError("wechat_mp_authorization_required")
    client = WechatMpPortalClient(state.get("cookies") if isinstance(state.get("cookies"), list) else [])
    payload = client.search_biz(token=compact_text(state.get("token"), limit=120), query=query, limit=limit, offset=offset)
    return {
        "status": "ok",
        "query": compact_text(query, limit=120),
        "total": int(payload.get("total") or 0),
        "offset": max(0, int(offset)),
        "limit": max(1, min(int(limit), 20)),
        "items": build_wechat_search_candidates(payload),
        "raw": payload,
        "authorizedAccount": sanitize_wechat_auth_state(state).get("account") or {},
    }


def normalize_wechat_source(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    extra = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
    merged_extra = dict(extra)
    account_name = compact_text(raw.get("accountName") or raw.get("name"), limit=160)
    biz = compact_text(raw.get("biz"), limit=255)
    sample_url = compact_text(raw.get("sampleArticleUrl") or raw.get("articleUrl") or raw.get("url"), limit=1200)
    for key in ("fakeid", "alias", "serviceType", "verifyType", "searchKeyword", "lastSyncAt", "lastSyncStatus", "lastError"):
        value = compact_text(raw.get(key), limit=500)
        if value:
            merged_extra[key] = value
    for key in ("lastSyncCount", "syncedPages"):
        if raw.get(key) not in (None, ""):
            try:
                merged_extra[key] = int(raw.get(key))
            except Exception:
                pass
    merged_extra["weight"] = clamp_float(raw.get("weight") or merged_extra.get("weight") or 1, 0.1, 5.0, 1.0)
    return {
        "uid": compact_text(raw.get("uid"), limit=80) or wechat_source_uid(account_name, biz, sample_url),
        "accountName": account_name or "未命名公众号",
        "biz": biz,
        "avatarUrl": compact_text(raw.get("avatarUrl") or raw.get("avatar") or raw.get("cover"), limit=1000),
        "intro": compact_text(raw.get("intro") or raw.get("description"), limit=500),
        "sourceType": compact_text(raw.get("sourceType") or raw.get("source_type"), limit=80) or "manual",
        "enabled": bool_config(raw.get("enabled"), True),
        "feedUrl": compact_text(raw.get("feedUrl") or raw.get("collectorUrl"), limit=1200),
        "collectorHint": compact_text(raw.get("collectorHint") or raw.get("collectorType"), limit=120) or "manual",
        "note": compact_text(raw.get("note"), limit=500),
        "sampleArticleUrl": sample_url,
        "sampleTitle": compact_text(raw.get("sampleTitle") or raw.get("title"), limit=300),
        "lastDiscoveredAt": parse_item_time(raw.get("lastDiscoveredAt") or now_iso()),
        "lastArticleAt": parse_item_time(raw.get("lastArticleAt") or raw.get("publishedAt") or now_iso()),
        "extra": merged_extra,
    }


def wechat_source_from_search_result(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    return {
        "accountName": compact_text(item.get("accountName") or item.get("name"), limit=160),
        "biz": compact_text(item.get("biz"), limit=255),
        "avatarUrl": compact_text(item.get("avatarUrl"), limit=1000),
        "intro": compact_text(item.get("intro"), limit=500),
        "sourceType": "wechat_mp_search",
        "enabled": True,
        "feedUrl": "",
        "collectorHint": "wechat_mp_api",
        "note": "added from official mp search",
        "extra": {
            "fakeid": compact_text(item.get("fakeid"), limit=255),
            "alias": compact_text(item.get("alias"), limit=120),
            "serviceType": compact_text(item.get("serviceType"), limit=40),
            "verifyType": compact_text(item.get("verifyType"), limit=40),
            "weight": clamp_float(item.get("weight") or 1, 0.1, 5.0, 1.0),
        },
    }


def find_wechat_source_row(conn: sqlite3.Connection, raw: dict[str, Any]) -> sqlite3.Row | None:
    uid = compact_text(raw.get("uid"), limit=80)
    biz = compact_text(raw.get("biz"), limit=255)
    account_name = compact_text(raw.get("accountName") or raw.get("name"), limit=160)
    if uid:
        row = conn.execute("SELECT * FROM wechat_sources WHERE uid=?", (uid,)).fetchone()
        if row:
            return row
    if biz:
        row = conn.execute("SELECT * FROM wechat_sources WHERE biz=?", (biz,)).fetchone()
        if row:
            return row
    if account_name:
        return conn.execute("SELECT * FROM wechat_sources WHERE lower(account_name)=lower(?) ORDER BY updated_at DESC LIMIT 1", (account_name,)).fetchone()
    return None


def upsert_wechat_source(conn: sqlite3.Connection, raw: dict[str, Any]) -> dict[str, Any]:
    source = normalize_wechat_source(raw)
    if not compact_text(source.get("accountName")):
        raise ValueError("missing_account_name")
    existing = find_wechat_source_row(conn, source)
    ts = now_iso()
    if existing:
        source["uid"] = existing["uid"]
        existing_extra = json_loads(existing["extra_json"], {})
        merged_extra = dict(existing_extra if isinstance(existing_extra, dict) else {})
        merged_extra.update(source["extra"] if isinstance(source.get("extra"), dict) else {})
        source["extra"] = merged_extra
        conn.execute(
            """
            UPDATE wechat_sources
            SET account_name=?, biz=?, avatar_url=?, intro=?, source_type=?, enabled=?, feed_url=?, collector_hint=?, note=?,
                sample_article_url=?, sample_title=?, last_discovered_at=?, last_article_at=?, extra_json=?, updated_at=?
            WHERE uid=?
            """,
            (
                source["accountName"] or existing["account_name"],
                source["biz"] or existing["biz"],
                source["avatarUrl"] or existing["avatar_url"],
                source["intro"] or existing["intro"],
                source["sourceType"] or existing["source_type"],
                1 if source["enabled"] else 0,
                source["feedUrl"],
                source["collectorHint"] or existing["collector_hint"],
                source["note"] or existing["note"],
                source["sampleArticleUrl"] or existing["sample_article_url"],
                source["sampleTitle"] or existing["sample_title"],
                source["lastDiscoveredAt"] or existing["last_discovered_at"],
                source["lastArticleAt"] or existing["last_article_at"],
                json_dumps(source["extra"]),
                ts,
                existing["uid"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO wechat_sources(
                uid,account_name,biz,avatar_url,intro,source_type,enabled,feed_url,collector_hint,note,
                sample_article_url,sample_title,last_discovered_at,last_article_at,extra_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source["uid"],
                source["accountName"],
                source["biz"],
                source["avatarUrl"],
                source["intro"],
                source["sourceType"],
                1 if source["enabled"] else 0,
                source["feedUrl"],
                source["collectorHint"],
                source["note"],
                source["sampleArticleUrl"],
                source["sampleTitle"],
                source["lastDiscoveredAt"],
                source["lastArticleAt"],
                json_dumps(source["extra"]),
                ts,
                ts,
            ),
        )
    conn.commit()
    return get_wechat_source(conn, source["uid"]) or source


def get_wechat_source(conn: sqlite3.Connection, source_uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM wechat_sources WHERE uid=?", (compact_text(source_uid),)).fetchone()
    if not row:
        return None
    article_count = conn.execute("SELECT COUNT(*) AS c FROM wechat_source_articles WHERE source_uid=?", (row["uid"],)).fetchone()["c"]
    extra = json_loads(row["extra_json"], {})
    extra = extra if isinstance(extra, dict) else {}
    return {
        "uid": row["uid"],
        "accountName": row["account_name"],
        "biz": row["biz"] or "",
        "avatarUrl": row["avatar_url"] or "",
        "intro": row["intro"] or "",
        "sourceType": row["source_type"] or "manual",
        "enabled": bool(row["enabled"]),
        "feedUrl": row["feed_url"] or "",
        "collectorHint": row["collector_hint"] or "",
        "note": row["note"] or "",
        "sampleArticleUrl": row["sample_article_url"] or "",
        "sampleTitle": row["sample_title"] or "",
        "lastDiscoveredAt": row["last_discovered_at"] or row["updated_at"],
        "lastArticleAt": row["last_article_at"],
        "articleCount": article_count,
        "fakeid": compact_text(extra.get("fakeid"), limit=255),
        "alias": compact_text(extra.get("alias"), limit=120),
        "serviceType": compact_text(extra.get("serviceType"), limit=40),
        "verifyType": compact_text(extra.get("verifyType"), limit=40),
        "weight": clamp_float(extra.get("weight") or 1, 0.1, 5.0, 1.0),
        "lastSyncAt": compact_text(extra.get("lastSyncAt"), limit=120) or None,
        "lastSyncStatus": compact_text(extra.get("lastSyncStatus"), limit=40) or "",
        "lastSyncCount": int(extra.get("lastSyncCount") or 0),
        "lastError": compact_text(extra.get("lastError"), limit=500),
        "extra": extra,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def update_wechat_source_runtime(conn: sqlite3.Connection, source_uid: str, **extra_updates: Any) -> dict[str, Any] | None:
    row = conn.execute("SELECT extra_json FROM wechat_sources WHERE uid=?", (compact_text(source_uid),)).fetchone()
    if not row:
        return None
    extra = json_loads(row["extra_json"], {})
    extra = extra if isinstance(extra, dict) else {}
    for key, value in extra_updates.items():
        if value is None:
            continue
        extra[key] = value
    conn.execute("UPDATE wechat_sources SET extra_json=?, updated_at=? WHERE uid=?", (json_dumps(extra), now_iso(), compact_text(source_uid)))
    conn.commit()
    return get_wechat_source(conn, source_uid)


def record_wechat_source_article(conn: sqlite3.Connection, source_uid: str, raw: dict[str, Any]) -> dict[str, Any]:
    url = compact_text(raw.get("url"), limit=1200)
    title = compact_text(raw.get("title"), limit=300)
    published_at = parse_item_time(raw.get("publishedAt") or raw.get("published_at") or now_iso())
    article_uid = compact_text(raw.get("uid"), limit=80) or ("wxart_" + stable_uid(source_uid, url or title, published_at)[:20])
    ts = now_iso()
    row = conn.execute("SELECT uid FROM wechat_source_articles WHERE uid=? OR url=?", (article_uid, url)).fetchone()
    payload = (
        article_uid,
        source_uid,
        title or url,
        url,
        published_at,
        compact_text(raw.get("summary"), limit=1000),
        compact_text(raw.get("htmlExcerpt") or raw.get("summary"), limit=2000),
        json_dumps(raw.get("raw") if isinstance(raw.get("raw"), dict) else raw),
        ts,
        ts,
    )
    if row:
        conn.execute(
            """
            UPDATE wechat_source_articles
            SET source_uid=?, title=?, url=?, published_at=?, summary=?, html_excerpt=?, raw_json=?, updated_at=?
            WHERE uid=? OR url=?
            """,
            (
                source_uid,
                title or url,
                url,
                published_at,
                compact_text(raw.get("summary"), limit=1000),
                compact_text(raw.get("htmlExcerpt") or raw.get("summary"), limit=2000),
                json_dumps(raw.get("raw") if isinstance(raw.get("raw"), dict) else raw),
                ts,
                article_uid,
                url,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO wechat_source_articles(
                uid,source_uid,title,url,published_at,summary,html_excerpt,raw_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            payload,
        )
    conn.execute(
        "UPDATE wechat_sources SET sample_article_url=?, sample_title=?, last_discovered_at=?, last_article_at=?, updated_at=? WHERE uid=?",
        (url, title or url, ts, published_at, ts, source_uid),
    )
    conn.commit()
    return {
        "uid": article_uid,
        "sourceUid": source_uid,
        "title": title or url,
        "url": url,
        "publishedAt": published_at,
        "summary": compact_text(raw.get("summary"), limit=1000),
        "createdAt": ts,
        "updatedAt": ts,
    }


def normalize_wechat_publish_entry(source: dict[str, Any], raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = compact_text(raw.get("title"), limit=300)
    url = compact_text(raw.get("link") or raw.get("url"), limit=1200)
    if not title or not url:
        return None
    digest = compact_text(raw.get("digest") or raw.get("description") or raw.get("summary"), limit=1000)
    published_at = parse_wechat_published_at(raw.get("update_time") or raw.get("publish_time") or raw.get("create_time") or now_iso())
    cover_url = compact_text(raw.get("cover") or raw.get("pic_url"), limit=1000)
    biz = wechat_url_value(url, "__biz") or compact_text(source.get("biz"), limit=255)
    return {
        "uid": "wxart_" + stable_uid(source.get("uid"), raw.get("appmsgid") or url, raw.get("itemidx") or index)[:20],
        "title": title,
        "url": url,
        "publishedAt": published_at,
        "summary": digest,
        "htmlExcerpt": digest,
        "accountName": source.get("accountName"),
        "sourceOrigin": "dynamic_collector",
        "collector": "wechat_mp_api",
        "provider": source.get("accountName"),
        "original": bool(raw.get("is_original") or str(raw.get("copyright_stat") or "") == "11"),
        "raw": {
            **raw,
            "biz": biz,
            "coverUrl": cover_url,
            "fakeid": source.get("fakeid"),
            "alias": source.get("alias"),
            "accountName": source.get("accountName"),
        },
    }


def sync_wechat_sources(conn: sqlite3.Connection, *, uids: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
    auth = wechat_auth_state(conn)
    if compact_text(auth.get("status")) != "authorized" or not compact_text(auth.get("token")) or not isinstance(auth.get("cookies"), list):
        raise RuntimeError("wechat_mp_authorization_required")
    wanted = {compact_text(uid, limit=80) for uid in (uids or []) if compact_text(uid, limit=80)}
    sources = []
    for row in conn.execute("SELECT uid FROM wechat_sources ORDER BY updated_at DESC, created_at DESC").fetchall():
        source = get_wechat_source(conn, row["uid"])
        if not source or not source.get("enabled"):
            continue
        if wanted and source["uid"] not in wanted:
            continue
        sources.append(source)
    client = WechatMpPortalClient(auth.get("cookies"))
    token = compact_text(auth.get("token"), limit=120)
    checked = 0
    imported = 0
    raw_articles = 0
    errors: list[dict[str, Any]] = []
    touched_sources: list[dict[str, Any]] = []
    for source in sources:
        checked += 1
        fakeid = compact_text(source.get("fakeid"), limit=255) or compact_text((source.get("extra") or {}).get("fakeid"), limit=255)
        started = time.time()
        if not fakeid:
            update_wechat_source_runtime(conn, source["uid"], lastSyncAt=now_iso(), lastSyncStatus="missing_fakeid", lastSyncCount=0, lastError="missing_fakeid")
            upsert_source(conn, source_uid=source["uid"], name=source["accountName"], source_kind="mp_wechat_api", channel="mp", status="missing_fakeid", count=0, detail="missing fakeid", elapsed_ms=int((time.time() - started) * 1000), url=source.get("sampleArticleUrl") or "", config={"uid": source["uid"]})
            errors.append({"source": source["accountName"], "error": "missing_fakeid"})
            continue
        try:
            payload = client.fetch_articles(token=token, fakeid=fakeid, count=limit)
            publish_page = payload.get("publish_page") if isinstance(payload.get("publish_page"), dict) else {}
            publish_list = publish_page.get("publish_list") or []
            source_imported = 0
            source_raw = 0
            for wrapper in publish_list:
                publish_info = wrapper.get("publish_info") if isinstance(wrapper, dict) else {}
                if isinstance(publish_info, str):
                    publish_info = json_loads(publish_info, {})
                if not isinstance(publish_info, dict):
                    continue
                entries = publish_info.get("appmsgex") or publish_info.get("appmsg_list") or publish_info.get("appmsg") or []
                if isinstance(entries, dict):
                    entries = [entries]
                for index, entry in enumerate(entries):
                    article = normalize_wechat_publish_entry(source, entry, index)
                    if not article:
                        continue
                    source_raw += 1
                    record_wechat_source_article(conn, source["uid"], article)
                    if upsert_mp_article(conn, article, default_origin="dynamic_collector", imported_via="wechat_mp_collect", source_weight=clamp_float(source.get("weight") or 1, 0.1, 5.0, 1.0)):
                        source_imported += 1
            imported += source_imported
            raw_articles += source_raw
            touched = update_wechat_source_runtime(conn, source["uid"], lastSyncAt=now_iso(), lastSyncStatus="ok" if source_raw else "empty", lastSyncCount=source_imported, lastError="", syncedPages=1)
            if touched:
                touched_sources.append(touched)
            upsert_source(conn, source_uid=source["uid"], name=source["accountName"], source_kind="mp_wechat_api", channel="mp", status="ok" if source_raw else "empty", count=source_imported, detail=f"fakeid:{fakeid}", elapsed_ms=int((time.time() - started) * 1000), url=source.get("sampleArticleUrl") or "", config={"uid": source["uid"], "fakeid": fakeid, "collectorHint": source.get("collectorHint")})
        except Exception as exc:
            detail = compact_text(str(exc), limit=500)
            update_wechat_source_runtime(conn, source["uid"], lastSyncAt=now_iso(), lastSyncStatus="error", lastSyncCount=0, lastError=detail)
            upsert_source(conn, source_uid=source["uid"], name=source["accountName"], source_kind="mp_wechat_api", channel="mp", status="error", count=0, detail=detail, elapsed_ms=int((time.time() - started) * 1000), url=source.get("sampleArticleUrl") or "", config={"uid": source["uid"], "fakeid": fakeid})
            errors.append({"source": source["accountName"], "error": detail})
    conn.commit()
    return {
        "status": "ok" if not errors else ("partial" if imported or raw_articles else "error"),
        "checked": checked,
        "imported": imported,
        "rawArticles": raw_articles,
        "errors": errors[:10],
        "sources": touched_sources,
        "registry": wechat_source_registry(conn),
    }


def discover_wechat_sources_by_articles(conn: sqlite3.Connection, urls: list[str]) -> dict[str, Any]:
    imported_sources: list[dict[str, Any]] = []
    imported_articles: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = compact_text(raw_url, limit=1200)
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            discovered = discover_wechat_source_from_article(url)
            source = upsert_wechat_source(conn, discovered["source"])
            article = record_wechat_source_article(conn, source["uid"], discovered["article"])
            imported_sources.append(source)
            imported_articles.append(article)
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})
    return {
        "status": "ok" if not errors else ("partial" if imported_sources else "error"),
        "requested": len(seen),
        "importedSources": len(imported_sources),
        "importedArticles": len(imported_articles),
        "sources": imported_sources,
        "articles": imported_articles,
        "errors": errors,
        "registry": wechat_source_registry(conn),
    }


def delete_wechat_source(conn: sqlite3.Connection, source_uid: str) -> bool:
    uid = compact_text(source_uid, limit=80)
    if not uid:
        return False
    row = conn.execute("SELECT uid FROM wechat_sources WHERE uid=?", (uid,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM wechat_source_articles WHERE source_uid=?", (uid,))
    conn.execute("DELETE FROM wechat_sources WHERE uid=?", (uid,))
    conn.commit()
    return True


def wechat_source_registry(conn: sqlite3.Connection) -> dict[str, Any]:
    source_rows = conn.execute("SELECT * FROM wechat_sources ORDER BY updated_at DESC, created_at DESC LIMIT 120").fetchall()
    sources: list[dict[str, Any]] = []
    for row in source_rows:
        source = get_wechat_source(conn, row["uid"])
        if source:
            sources.append(source)
    recent_articles = []
    for row in conn.execute("SELECT * FROM wechat_source_articles ORDER BY updated_at DESC LIMIT 40").fetchall():
        source = conn.execute("SELECT account_name FROM wechat_sources WHERE uid=?", (row["source_uid"],)).fetchone()
        recent_articles.append({
            "uid": row["uid"],
            "sourceUid": row["source_uid"],
            "accountName": source["account_name"] if source else "",
            "title": row["title"],
            "url": row["url"],
            "publishedAt": row["published_at"],
            "summary": row["summary"] or "",
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        })
    with_biz = sum(1 for source in sources if source.get("biz"))
    with_feed = sum(1 for source in sources if source.get("feedUrl"))
    with_fakeid = sum(1 for source in sources if source.get("fakeid"))
    enabled = sum(1 for source in sources if source.get("enabled"))
    last_discovered = max([compact_text(source.get("lastDiscoveredAt")) for source in sources if source.get("lastDiscoveredAt")] or [""])
    last_sync = max([compact_text(source.get("lastSyncAt")) for source in sources if source.get("lastSyncAt")] or [""])
    auth = sanitize_wechat_auth_state(wechat_auth_state(conn))
    ready_to_sync = sum(1 for source in sources if source.get("enabled") and source.get("fakeid") and auth.get("authorized"))
    return {
        "sources": sources,
        "recentArticles": recent_articles,
        "auth": auth,
        "summary": {
            "registered": len(sources),
            "enabled": enabled,
            "withBiz": with_biz,
            "withFeedUrl": with_feed,
            "withFakeid": with_fakeid,
            "readyToSync": ready_to_sync,
            "sampleArticles": len(recent_articles),
            "lastDiscoveredAt": last_discovered or None,
            "lastSyncAt": last_sync or None,
            "authStatus": auth.get("status"),
        },
        "generatedAt": now_iso(),
    }


def mp_source_summary(conn: sqlite3.Connection, *, include_private: bool = False) -> dict[str, Any]:
    config = mp_sources_config()
    items: list[dict[str, Any]] = []
    for source in config.get("sources", []):
        source_kind = "mp_" + normalize_kind(source.get("type") or "rss")
        source_uid = stable_uid(source.get("name"), source_kind, "mp")
        health = conn.execute(
            "SELECT status,item_count,detail,elapsed_ms,checked_at FROM source_health WHERE source_uid=? ORDER BY id DESC LIMIT 1",
            (source_uid,),
        ).fetchone()
        article_count = conn.execute("SELECT COUNT(*) AS c FROM mp_articles WHERE account_name=?", (source.get("name"),)).fetchone()["c"]
        item = {
            "id": source.get("id"),
            "name": source.get("name"),
            "type": source.get("type"),
            "enabled": bool(source.get("enabled")),
            "weight": source.get("weight"),
            "note": source.get("note"),
            "hasUrl": bool(source.get("url")),
            "lastStatus": health["status"] if health else "未检测",
            "lastCount": health["item_count"] if health else 0,
            "lastDetail": health["detail"] if health else "",
            "elapsedMs": health["elapsed_ms"] if health else 0,
            "lastCheckedAt": health["checked_at"] if health else None,
            "articleCount": article_count,
        }
        if include_private:
            item["url"] = source.get("url")
            for key in ("itemsPath", "itemPath", "titleField", "accountField", "urlField", "publishedField", "summaryField", "readsField", "likesField", "sharesField", "tagsField"):
                if source.get(key):
                    item[key] = source[key]
        items.append(item)
    enabled = [source for source in items if source.get("enabled")]
    ready = [source for source in enabled if source.get("hasUrl")]
    last_checked = max([compact_text(source.get("lastCheckedAt")) for source in items if source.get("lastCheckedAt")] or [""])
    return {
        "sources": items,
        "summary": {
            "configured": len(items),
            "enabled": len(enabled),
            "ready": len(ready),
            "lastCheckedAt": last_checked or None,
            "configPath": str(MP_SOURCES_PATH) if include_private else None,
        },
        "generatedAt": now_iso(),
    }


def combined_mp_source_summary(conn: sqlite3.Connection, *, include_private: bool = False) -> dict[str, Any]:
    external = mp_source_summary(conn, include_private=include_private)
    registry = wechat_source_registry(conn)
    external_summary = external.get("summary", {}) if isinstance(external.get("summary"), dict) else {}
    registry_summary = registry.get("summary", {}) if isinstance(registry.get("summary"), dict) else {}
    configured = int(external_summary.get("configured") or 0) + int(registry_summary.get("registered") or 0)
    enabled = int(external_summary.get("enabled") or 0) + int(registry_summary.get("enabled") or 0)
    ready = int(external_summary.get("ready") or 0) + int(registry_summary.get("readyToSync") or 0)
    session_issue = latest_wechat_session_issue(conn)
    raw_auth_status = compact_text(registry_summary.get("authStatus"), limit=40) or "idle"
    session_status = compact_text(session_issue.get("status"), limit=40) or "ok"
    derived_auth_status = "invalid_session" if session_status == "invalid_session" else raw_auth_status
    usable_ready = 0 if session_status == "invalid_session" else ready
    last_checked = max(
        [
            compact_text(external_summary.get("lastCheckedAt")),
            compact_text(registry_summary.get("lastSyncAt")),
            compact_text(registry_summary.get("lastDiscoveredAt")),
            compact_text(session_issue.get("checkedAt")),
        ]
    )
    summary = {
        "configured": configured,
        "enabled": enabled,
        "ready": usable_ready,
        "declaredReady": ready,
        "lastCheckedAt": last_checked or None,
        "externalConfigured": int(external_summary.get("configured") or 0),
        "wechatRegistered": int(registry_summary.get("registered") or 0),
        "wechatReady": 0 if session_status == "invalid_session" else int(registry_summary.get("readyToSync") or 0),
        "wechatDeclaredReady": int(registry_summary.get("readyToSync") or 0),
        "wechatAuthStatus": derived_auth_status,
        "wechatAuthStatusRaw": raw_auth_status,
        "wechatSessionStatus": session_status,
        "wechatSessionIssue": session_issue,
    }
    if include_private:
        summary["configPath"] = external_summary.get("configPath")
    return {
        "summary": summary,
        "external": external,
        "wechatRegistry": registry,
        "generatedAt": now_iso(),
    }


def normalize_kind(value: Any) -> str:
    return compact_text(value).lower().replace(" ", "_")


def strip_html(value: Any, *, limit: int | None = None) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return compact_text(html.unescape(text), limit=limit)


def fetch_text(url: str, *, timeout: int = 35) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WelOPC-AIHot/1.0; +https://welopc.com/ai-hot/)",
            "Accept": "application/rss+xml, application/atom+xml, application/json, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(3_000_000)
    return raw.decode("utf-8", errors="replace")


def fetch_html(url: str, *, timeout: int = 25) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if "mp.weixin.qq.com" in compact_text(url):
        headers["Referer"] = "https://mp.weixin.qq.com/"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(3_000_000)
    return raw.decode("utf-8", errors="replace")


def html_meta_content(text: str, keys: list[str]) -> str:
    for key in keys:
        escaped = re.escape(key)
        patterns = [
            rf'<meta[^>]+(?:property|name)\s*=\s*["\']{escaped}["\'][^>]+content\s*=\s*["\']([^"\']*)["\']',
            rf'<meta[^>]+content\s*=\s*["\']([^"\']*)["\'][^>]+(?:property|name)\s*=\s*["\']{escaped}["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return compact_text(html.unescape(match.group(1)), limit=1000)
    return ""


def html_title_content(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return compact_text(html.unescape(match.group(1)), limit=300)


def html_js_string(text: str, names: list[str]) -> str:
    for name in names:
        escaped = re.escape(name)
        patterns = [
            rf"\b{escaped}\b\s*[:=]\s*\"([^\"]+)\"",
            rf"\b{escaped}\b\s*[:=]\s*'([^']+)'",
            rf"\b{escaped}\b\s*=\s*htmlDecode\(\"([^\"]+)\"\)",
            rf"\b{escaped}\b\s*=\s*htmlDecode\('([^']+)'\)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return compact_text(html.unescape(match.group(1)), limit=1000)
    return ""


def wechat_url_value(url: str, key: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get(key) or [""]
    return compact_text(values[0], limit=500)


def looks_like_wechat_article_url(url: str) -> bool:
    parsed = urlparse(compact_text(url))
    return "mp.weixin.qq.com" in parsed.netloc.lower() and parsed.path.startswith("/s")


def wechat_source_uid(account_name: str, biz: str = "", sample_url: str = "") -> str:
    seed = biz or stable_uid(account_name, sample_url, "wechat_source")
    return "wxsrc_" + stable_uid(seed, "wechat_source")[:18]


def parse_wechat_published_at(raw_value: Any) -> str:
    text = compact_text(raw_value)
    if text.isdigit() and len(text) >= 10:
        try:
            return datetime.fromtimestamp(int(text[:10]), tz=timezone.utc).isoformat()
        except Exception:
            return now_iso()
    return parse_item_time(text)


def discover_wechat_source_from_article(url: str) -> dict[str, Any]:
    normalized_url = compact_text(url, limit=1200)
    if not looks_like_wechat_article_url(normalized_url):
        raise ValueError("unsupported_wechat_article_url")
    html_text = fetch_html(normalized_url, timeout=25)
    blocked_signals = (
        "当前环境异常",
        "该内容已被发布者删除",
        "The content has been deleted by the author",
        "该内容暂时无法查看",
        "内容因违规无法查看",
    )
    if any(signal in html_text for signal in blocked_signals):
        raise ValueError("wechat_article_unavailable")
    title = (
        html_meta_content(html_text, ["og:title"])
        or html_js_string(html_text, ["msg_title"])
        or html_title_content(html_text)
    )
    account_name = (
        html_meta_content(html_text, ["og:article:author"])
        or html_js_string(html_text, ["nickname", "user_name"])
        or "未识别公众号"
    )
    summary = (
        html_meta_content(html_text, ["og:description", "description"])
        or html_js_string(html_text, ["msg_desc"])
    )
    biz = (
        wechat_url_value(normalized_url, "__biz")
        or html_js_string(html_text, ["biz"])
    )
    published_at = parse_wechat_published_at(
        html_meta_content(html_text, ["article:published_time"])
        or html_js_string(html_text, ["ct", "publish_time"])
    )
    cover_url = html_meta_content(html_text, ["og:image", "twitter:image"])
    article = {
        "uid": "wxart_" + stable_uid(normalized_url, title, published_at)[:20],
        "title": title or normalized_url,
        "url": normalized_url,
        "publishedAt": published_at,
        "summary": summary,
        "htmlExcerpt": summary,
        "raw": {
            "biz": biz,
            "coverUrl": cover_url,
            "accountName": account_name,
            "title": title,
            "summary": summary,
            "publishedAt": published_at,
            "url": normalized_url,
        },
    }
    source = {
        "uid": wechat_source_uid(account_name, biz, normalized_url),
        "accountName": account_name,
        "biz": biz,
        "avatarUrl": "",
        "intro": "",
        "sourceType": "article_discovery",
        "enabled": True,
        "feedUrl": "",
        "collectorHint": "wechat_public_article",
        "note": "通过公众号文章链接发现并登记的信息源。",
        "sampleArticleUrl": normalized_url,
        "sampleTitle": article["title"],
        "lastDiscoveredAt": now_iso(),
        "lastArticleAt": published_at,
        "extra": {
            "coverUrl": cover_url,
            "discoveryUrl": normalized_url,
        },
    }
    return {"source": source, "article": article}


def xml_text(node: ET.Element | None, names: list[str]) -> str:
    if node is None:
        return ""
    for name in names:
        found = node.find(name)
        if found is not None:
            if found.text:
                return compact_text(found.text)
            href = found.attrib.get("href")
            if href:
                return compact_text(href)
    for child in list(node):
        local = child.tag.rsplit("}", 1)[-1].lower()
        if any(local == name.rsplit("}", 1)[-1].lower() for name in names):
            if child.text:
                return compact_text(child.text)
            href = child.attrib.get("href")
            if href:
                return compact_text(href)
    return ""


def parse_rss_or_atom(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(text.encode("utf-8"))
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    account = source_name_from_config(source, "公众号")
    rows: list[dict[str, Any]] = []
    for node in items[:80]:
        link = xml_text(node, ["link", "{http://www.w3.org/2005/Atom}link"])
        if not link:
            for child in list(node):
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = compact_text(child.attrib.get("href"))
                    break
        rows.append({
            "title": xml_text(node, ["title", "{http://www.w3.org/2005/Atom}title"]),
            "accountName": account,
            "url": link,
            "publishedAt": xml_text(node, ["pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"]),
            "summary": strip_html(xml_text(node, ["description", "summary", "content", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"]), limit=1000),
            "sourceOrigin": "dynamic_collector",
            "collector": compact_text(source.get("type") or "rss", limit=80),
            "provider": compact_text(source.get("name") or account, limit=120),
        })
    return [row for row in rows if compact_text(row.get("title"))]


def mp_ai_relevance(raw: dict[str, Any]) -> float:
    text = f"{raw.get('title','')} {raw.get('summary','')}".lower()
    needles = {
        "ai": 10, "agent": 14, "agents": 14, "智能体": 14, "大模型": 14, "模型": 8,
        "openai": 12, "claude": 12, "anthropic": 12, "deepseek": 12, "gemini": 10,
        "gpt": 10, "llm": 10, "自动化": 10, "mcp": 10, "aigc": 10, "生成式": 8,
        "创业": 7, "一人公司": 16, "独立开发": 12, "获客": 8, "运营": 6,
        "工具": 5, "产品": 5, "api": 5, "开源": 6, "部署": 5,
    }
    score = 0.0
    for needle, value in needles.items():
        if needle in text:
            score += value
    return min(100.0, score)


def mp_heat_scores(raw: dict[str, Any], *, source_weight: float = 1.0) -> tuple[float, float, float]:
    relevance = float(raw.get("aiRelevanceScore") or raw.get("ai_relevance_score") or mp_ai_relevance(raw))
    published = parse_iso_datetime(raw.get("publishedAt") or raw.get("published_at"))
    age_hours = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600)
    recency = max(0.0, 30.0 - min(30.0, age_hours / 3.0))
    reads = float(raw.get("reads") or raw.get("readCount") or 0)
    likes = float(raw.get("likes") or raw.get("likeCount") or 0)
    shares = float(raw.get("shares") or raw.get("shareCount") or 0)
    engagement = min(25.0, reads / 4000 + likes / 200 + shares / 120)
    anomaly = min(100.0, engagement * 3 + (12 if any(mark in compact_text(raw.get("title")) for mark in ("！", "?", "？", "爆", "首次", "重磅")) else 0))
    heat = min(100.0, relevance * 0.55 + recency + engagement + max(0.0, source_weight - 1.0) * 8)
    return round(heat, 2), round(anomaly, 2), round(relevance, 2)


OPC_SOLO_TERMS = {
    "一人公司": 22, "独立开发": 18, "solo": 12, "startup": 10, "创业": 12,
    "agent": 14, "智能体": 14, "自动化": 14, "workflow": 10, "工作流": 10,
    "mcp": 10, "api": 8, "sdk": 8, "plugin": 8, "插件": 8,
    "获客": 12, "营销": 10, "增长": 8, "运营": 10, "内容": 8,
    "低成本": 12, "本地": 8, "部署": 10, "开源": 10, "模板": 8,
    "product": 8, "产品": 8, "工具": 8, "效率": 8, "客服": 8,
    "财务": 6, "表格": 6, "文档": 6, "代码": 6, "coding": 6,
}
OPC_SOLO_THRESHOLD = 54.0


def opc_solo_score_text(text: str, base_score: float = 0.0) -> float:
    lower = text.lower()
    score = min(28.0, max(0.0, base_score) * 0.2)
    for term, weight in OPC_SOLO_TERMS.items():
        if term.lower() in lower:
            score += weight
    return min(100.0, round(score, 2))


def is_opc_solo_item(item: dict[str, Any]) -> bool:
    text = " ".join([
        compact_text(item.get("titleZh") or item.get("title")),
        compact_text(item.get("summaryZh") or item.get("summary")),
        compact_text(item.get("itemType")),
        " ".join(compact_text(tag.get("tag") if isinstance(tag, dict) else tag) for tag in item.get("aiTags", []) or []),
    ])
    lower = text.lower()
    business_hit = any(term in lower for term in ["一人公司", "独立开发", "创业", "获客", "营销", "运营", "低成本"])
    automation_hit = any(term in lower for term in ["agent", "智能体", "自动化", "workflow", "工作流", "mcp"])
    product_hit = any(term in lower for term in ["api", "sdk", "插件", "plugin", "cli", "app", "产品", "工具", "部署", "开源"])
    score = opc_solo_score_text(text, float(item.get("finalScore") or item.get("heatScore") or 0))
    if score >= OPC_SOLO_THRESHOLD and (business_hit or (automation_hit and product_hit)):
        item["opcSoloScore"] = score
        return True
    return False


def infer_channel(item: dict[str, Any]) -> str:
    raw = " ".join(normalize_kind(item.get(key)) for key in ("source_kind", "source_name", "category"))
    if "x_allowlist" in raw or "x_accounts" in raw or raw == "x" or "twitter" in raw:
        return "x"
    if "github" in raw:
        return "github"
    if "product_hunt" in raw or "product hunt" in raw:
        return "product"
    if "youtube" in raw or "reddit" in raw or "arxiv" in raw or "community" in raw:
        return "community"
    if "official" in raw or "openai" in raw or "anthropic" in raw or "deepmind" in raw or "hugging" in raw:
        return "firstParty"
    return "news"


def infer_item_type(channel: str, item: dict[str, Any]) -> str:
    raw = normalize_kind(item.get("source_kind"))
    title = compact_text(item.get("title")).lower()
    if channel == "github":
        return "repo"
    if channel == "product":
        return "product"
    if "youtube" in raw:
        return "video"
    if "reddit" in raw:
        return "community"
    if "arxiv" in raw or "paper" in title:
        return "paper"
    if channel == "firstParty":
        return "official"
    return "news"


def ai_tags_for(channel: str, item: dict[str, Any]) -> list[str]:
    tags = [channel]
    text = f"{item.get('title','')} {item.get('summary','')}".lower()
    mapping = {
        "agent": ["agent", "agents", "mcp", "workflow"],
        "model": ["model", "llm", "gpt", "claude", "deepseek", "qwen"],
        "developer": ["github", "sdk", "api", "repo", "open source"],
        "product": ["product", "launch", "product hunt"],
        "research": ["arxiv", "paper", "benchmark"],
    }
    for tag, needles in mapping.items():
        if any(needle in text for needle in needles):
            tags.append(tag)
    return list(dict.fromkeys(tags))[:6]


def quality_axes(channel: str, score: float, selected: bool) -> dict[str, Any]:
    base = max(min(score, 15.0), 0.0)
    # AIHOT exposes five compact axes: act, nov, sig, cred, reson.
    return {
        "act": int(max(1, min(9, 4 + base / 2 + (1 if channel in {"github", "product"} else 0)))),
        "nov": int(max(1, min(9, 4 + base / 2.2))),
        "sig": int(max(1, min(9, 3 + base / 2.1 + (1 if selected else 0)))),
        "cred": int(max(1, min(9, 5 + (2 if channel == "firstParty" else 0) + base / 3.5))),
        "reson": int(max(1, min(9, 3 + base / 2.3 + (1 if selected else 0)))),
    }


def score_bundle(channel: str, raw_score: float, selected: bool) -> dict[str, float]:
    signal = max(0.0, min(15.0, raw_score))
    channel_bonus = {
        "firstParty": 4.0,
        "github": 2.5,
        "product": 2.0,
        "community": 1.0,
        "news": 1.5,
    }.get(channel, 0.0)
    importance = min(100.0, max(0.0, 45.0 + signal * 3.8 + channel_bonus))
    quality = min(100.0, max(0.0, 50.0 + signal * 3.2 + (3.0 if channel == "firstParty" else 0.0)))
    if selected:
        final = min(94.0, max(62.0, 58.0 + signal * 2.0 + channel_bonus))
    else:
        final = min(86.0, max(35.0, 42.0 + signal * 3.0 + channel_bonus / 2.0))
    return {
        "importance": round(importance, 2),
        "quality_score": round(quality, 2),
        "final_score": round(final, 2),
    }


def deepseek_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def deepseek_available() -> bool:
    return bool(deepseek_api_key())


def clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except Exception:
        return default


def clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return default


def call_deepseek_json(*, system: str, user: str, max_tokens: int = 4096, temperature: float = 0.2) -> dict[str, Any]:
    key = deepseek_api_key()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    timeout_seconds = clamp_int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "75"), 15, 240, 75)
    attempts = clamp_int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"), 1, 4, 2)
    retry_delay = clamp_float(os.getenv("DEEPSEEK_RETRY_DELAY_SECONDS", "1.5"), 0, 10, 1.5)
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if DEEPSEEK_THINKING == "enabled":
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT if DEEPSEEK_REASONING_EFFORT in {"high", "max"} else "high"
    else:
        payload["thinking"] = {"type": "disabled"}
        payload["temperature"] = temperature
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            message = ((data.get("choices") or [{}])[0].get("message") or {})
            content = (message.get("content") or "").strip()
            if not content:
                raise RuntimeError("DeepSeek returned empty content")
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                match = re_json_object(content)
                if match:
                    return json.loads(match)
                raise RuntimeError("DeepSeek returned non-JSON content") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            last_error = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt >= attempts:
                raise last_error from exc
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                raise RuntimeError(f"DeepSeek request failed after {attempts} attempt(s): {exc}") from exc
        if retry_delay:
            time.sleep(retry_delay * attempt)
    raise RuntimeError(f"DeepSeek request failed: {last_error}")



def re_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else ""


def build_enrichment_payload(row: sqlite3.Row) -> dict[str, Any]:
    raw = json_loads(row["raw_json"], {})
    return {
        "id": row["id"],
        "title": row["title"],
        "currentTitleZh": row["title_zh"],
        "summary": row["summary"],
        "currentSummaryZh": row["summary_zh"],
        "url": row["url"],
        "sourceName": row["source_name"],
        "sourceKind": row["source_kind"],
        "channel": row["channel"],
        "publishedAt": row["published_at"],
        "currentItemType": row["item_type"],
        "currentScore": row["final_score"],
        "raw": raw if isinstance(raw, dict) else {},
    }


def normalize_model_enrichment(data: dict[str, Any], row: sqlite3.Row) -> dict[str, Any]:
    channel = row["channel"]
    fallback_score = float(row["final_score"] or row["quality_score"] or row["importance"] or 50)
    tags_raw = data.get("aiTags") or data.get("tags") or []
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for tag in tags_raw:
            value = tag.get("tag") if isinstance(tag, dict) else tag
            text = compact_text(value, limit=24)
            if text:
                tags.append(text)
    if not tags:
        tags = ai_tags_for(channel, {"title": row["title"], "summary": row["summary"]})
    axes = data.get("qualityAxesJson") or data.get("qualityAxes") or {}
    if not isinstance(axes, dict):
        axes = {}
    normalized_axes = {
        "act": clamp_int(axes.get("act"), 1, 9, 5),
        "nov": clamp_int(axes.get("nov"), 1, 9, 5),
        "sig": clamp_int(axes.get("sig"), 1, 9, 5),
        "cred": clamp_int(axes.get("cred"), 1, 9, 6),
        "reson": clamp_int(axes.get("reson"), 1, 9, 5),
    }
    quality = clamp_float(data.get("qualityScore"), 0, 100, fallback_score)
    importance = clamp_float(data.get("importance"), 0, 100, quality)
    final = clamp_float(data.get("finalScore"), 0, 100, max(quality, importance))
    selected = bool(data.get("aiSelected"))
    if "aiSelected" not in data:
        selected = final >= 70 or (quality >= 70 and importance >= 65)
    if selected and final < 60:
        final = 60.0
    item_type = compact_text(data.get("itemType") or row["item_type"], limit=80) or row["item_type"]
    return {
        "title_zh": compact_text(data.get("titleZh") or data.get("title_zh") or row["title_zh"], limit=240),
        "summary_zh": compact_text(data.get("summaryZh") or data.get("summary_zh") or row["summary_zh"], limit=1200),
        "item_type": item_type,
        "importance": round(importance, 2),
        "quality_score": round(quality, 2),
        "final_score": round(final, 2),
        "ai_selected": 1 if selected else 0,
        "ai_selected_reason": compact_text(data.get("aiSelectedReason") or data.get("selectedReason") or row["ai_selected_reason"], limit=500),
        "ai_tags_json": json_dumps(list(dict.fromkeys(tags))[:8]),
        "quality_axes_json": json_dumps(normalized_axes),
        "editorial_judgment": compact_text(data.get("editorialJudgment") or data.get("judgment") or row["editorial_judgment"], limit=500),
    }


def enrich_item_with_deepseek(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = build_enrichment_payload(row)
    request_hash = stable_uid(ENRICH_PROMPT_VERSION, payload)
    existing = conn.execute(
        "SELECT id FROM item_enrichments WHERE item_id=? AND request_hash=? AND status='ok' ORDER BY id DESC LIMIT 1",
        (row["id"], request_hash),
    ).fetchone()
    if existing:
        return {"status": "cached", "itemId": row["id"]}
    system = (
        "你是 AI 内容热榜的内容编辑与策略引擎。只返回 JSON，不要解释。"
        "目标是把 AI/Agent/模型/工具/产业动态标准化成中文信息流条目。"
        "必须谨慎，不要编造输入中没有的事实。"
    )
    user = (
        "请按 AI 热榜风格分析这个条目，返回 JSON：\n"
        "{\n"
        '  "titleZh": "18-32字中文标题",\n'
        '  "summaryZh": "中文摘要，保留关键事实和链接线索，80-350字",\n'
        '  "itemType": "product_launch|model_release|research_paper|tutorial_explainer|industry_event|opinion_analysis|tool_or_prompt",\n'
        '  "qualityAxesJson": {"act":1-9,"nov":1-9,"sig":1-9,"cred":1-9,"reson":1-9},\n'
        '  "qualityScore": 0-100,\n'
        '  "importance": 0-100,\n'
        '  "finalScore": 0-100,\n'
        '  "aiSelected": true/false,\n'
        '  "aiSelectedReason": "像编辑一样说明为什么值得看或为什么只是入库",\n'
        '  "editorialJudgment": "更口语但专业的编辑判断",\n'
        '  "aiTags": ["OpenAI","Agent","产品更新"],\n'
        '  "channelFits": {\n'
        '    "selected": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合精选"},\n'
        '    "daily": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合 AI 日报"},\n'
        '    "mp": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合公众号爆文，仅公众号内容可高分"},\n'
        '    "opcSolo": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合 OPC一人公司"}\n'
        "  }\n"
        "}\n\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)[:4200]}"
    )
    ts = now_iso()
    try:
        response = call_deepseek_json(system=system, user=user, max_tokens=1800)
        normalized = normalize_model_enrichment(response, row)
        normalized["updated_at"] = now_iso()
        conn.execute(
            "UPDATE feed_items SET "
            + ",".join(f"{key}=?" for key in normalized)
            + " WHERE id=?",
            [*normalized.values(), row["id"]],
        )
        conn.execute(
            "INSERT INTO item_enrichments(item_id,provider,model_name,prompt_version,status,request_hash,response_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (row["id"], "deepseek", DEEPSEEK_MODEL, ENRICH_PROMPT_VERSION, "ok", request_hash, json_dumps(response), ts, now_iso()),
        )
        conn.commit()
        return {"status": "ok", "itemId": row["id"], "finalScore": normalized["final_score"]}
    except Exception as exc:
        conn.execute(
            "INSERT INTO item_enrichments(item_id,provider,model_name,prompt_version,status,request_hash,response_json,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["id"], "deepseek", DEEPSEEK_MODEL, ENRICH_PROMPT_VERSION, "error", request_hash, "{}", str(exc), ts, now_iso()),
        )
        conn.commit()
        return {"status": "error", "itemId": row["id"], "error": str(exc)}


def enrich_items(conn: sqlite3.Connection, *, limit: int = 20, force: bool = False) -> dict[str, Any]:
    if not deepseek_available():
        return {"status": "skipped", "reason": "DEEPSEEK_API_KEY is not configured", "processed": 0}
    where = "channel!='x'"
    args: list[Any] = []
    if not force:
        where += " AND id NOT IN (SELECT item_id FROM item_enrichments WHERE status='ok' AND prompt_version=?)"
        args.append(ENRICH_PROMPT_VERSION)
        backoff_hours = clamp_int(os.getenv("DEEPSEEK_ERROR_BACKOFF_HOURS", "12"), 0, 168, 12)
        if backoff_hours:
            retry_cutoff = (datetime.now(timezone.utc) - timedelta(hours=backoff_hours)).isoformat()
            where += " AND id NOT IN (SELECT item_id FROM item_enrichments WHERE status='error' AND prompt_version=? AND updated_at>=?)"
            args.extend([ENRICH_PROMPT_VERSION, retry_cutoff])
    args.append(limit)
    rows = conn.execute(
        f"SELECT * FROM feed_items WHERE {where} ORDER BY ai_selected DESC, final_score DESC, published_at DESC LIMIT ?",
        args,
    ).fetchall()
    results = []
    delay = clamp_float(os.getenv("DEEPSEEK_DELAY_SECONDS", "0.4"), 0, 5, 0.4)
    for row in rows:
        results.append(enrich_item_with_deepseek(conn, row))
        if delay:
            time.sleep(delay)
    refresh_duplicates(conn)
    return {
        "status": "ok",
        "model": DEEPSEEK_MODEL,
        "promptVersion": ENRICH_PROMPT_VERSION,
        "processed": len(results),
        "ok": sum(1 for item in results if item["status"] in {"ok", "cached"}),
        "errors": [item for item in results if item["status"] == "error"][:5],
    }


def build_mp_enrichment_payload(row: sqlite3.Row) -> dict[str, Any]:
    raw = json_loads(row["raw_json"], {})
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "url": row["url"],
        "accountName": row["account_name"],
        "publishedAt": row["published_at"],
        "heatScore": row["heat_score"],
        "aiRelevanceScore": row["ai_relevance_score"],
        "sourceOrigin": row["source_origin"] if "source_origin" in row.keys() else "mp_dynamic",
        "tags": json_loads(row["tags_json"], []),
        "raw": raw if isinstance(raw, dict) else {},
    }


def enrich_mp_article_with_deepseek(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = build_mp_enrichment_payload(row)
    request_hash = stable_uid("mp", ENRICH_PROMPT_VERSION, payload)
    existing = conn.execute(
        "SELECT id FROM mp_enrichments WHERE mp_article_id=? AND request_hash=? AND status='ok' ORDER BY id DESC LIMIT 1",
        (row["id"], request_hash),
    ).fetchone()
    if existing:
        return {"status": "cached", "mpArticleId": row["id"]}
    system = (
        "你是 AI 公众号爆文栏目编辑。只返回 JSON，不解释。"
        "任务是判断公众号文章是否适合进入 AI 热榜、AI 日报、精选和 OPC 一人公司栏目。"
        "必须保守，不要编造输入中没有的事实；广告、福利、标题党和泛娱乐内容要降权。"
    )
    user = (
        "请分析这篇公众号文章，返回 JSON：\n"
        "{\n"
        '  "aiRelevance": 0-100,\n'
        '  "businessValue": 0-100,\n'
        '  "novelty": 0-100,\n'
        '  "utility": 0-100,\n'
        '  "qualityScore": 0-100,\n'
        '  "importance": 0-100,\n'
        '  "finalScore": 0-100,\n'
        '  "aiTags": ["OpenAI","Agent","模型发布"],\n'
        '  "qualityAxesJson": {"act":1-9,"nov":1-9,"sig":1-9,"cred":1-9,"reson":1-9},\n'
        '  "channelFits": {\n'
        '    "selected": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否值得放精选"},\n'
        '    "daily": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合 AI 日报"},\n'
        '    "mp": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合公众号爆文榜"},\n'
        '    "opcSolo": {"fitScore":0-100,"mustInclude":false,"reject":false,"reason":"是否适合一人公司/独立开发/增长自动化"}\n'
        "  }\n"
        "}\n\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)[:3600]}"
    )
    ts = now_iso()
    try:
        response = call_deepseek_json(system=system, user=user, max_tokens=1200)
        conn.execute(
            "INSERT INTO mp_enrichments(mp_article_id,provider,model_name,prompt_version,status,request_hash,response_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (row["id"], "deepseek", DEEPSEEK_MODEL, ENRICH_PROMPT_VERSION, "ok", request_hash, json_dumps(response), ts, now_iso()),
        )
        conn.commit()
        return {"status": "ok", "mpArticleId": row["id"], "modelScore": model_channel_fit(response, "mp")["score"]}
    except Exception as exc:
        conn.execute(
            "INSERT INTO mp_enrichments(mp_article_id,provider,model_name,prompt_version,status,request_hash,response_json,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["id"], "deepseek", DEEPSEEK_MODEL, ENRICH_PROMPT_VERSION, "error", request_hash, "{}", str(exc), ts, now_iso()),
        )
        conn.commit()
        return {"status": "error", "mpArticleId": row["id"], "error": str(exc)}


def enrich_mp_articles(conn: sqlite3.Connection, *, limit: int = 12, force: bool = False) -> dict[str, Any]:
    if not deepseek_available():
        return {"status": "skipped", "reason": "DEEPSEEK_API_KEY is not configured", "processed": 0}
    where = "1=1"
    args: list[Any] = []
    if not force:
        where += " AND id NOT IN (SELECT mp_article_id FROM mp_enrichments WHERE status='ok' AND prompt_version=?)"
        args.append(ENRICH_PROMPT_VERSION)
        backoff_hours = clamp_int(os.getenv("DEEPSEEK_ERROR_BACKOFF_HOURS", "12"), 0, 168, 12)
        if backoff_hours:
            retry_cutoff = (datetime.now(timezone.utc) - timedelta(hours=backoff_hours)).isoformat()
            where += " AND id NOT IN (SELECT mp_article_id FROM mp_enrichments WHERE status='error' AND prompt_version=? AND updated_at>=?)"
            args.extend([ENRICH_PROMPT_VERSION, retry_cutoff])
    args.append(limit)
    rows = conn.execute(
        f"SELECT * FROM mp_articles WHERE {where} ORDER BY heat_score DESC, published_at DESC, id DESC LIMIT ?",
        args,
    ).fetchall()
    results = []
    delay = clamp_float(os.getenv("DEEPSEEK_DELAY_SECONDS", "0.4"), 0, 5, 0.4)
    for row in rows:
        results.append(enrich_mp_article_with_deepseek(conn, row))
        if delay:
            time.sleep(delay)
    return {
        "status": "ok",
        "model": DEEPSEEK_MODEL,
        "promptVersion": ENRICH_PROMPT_VERSION,
        "processed": len(results),
        "ok": sum(1 for item in results if item["status"] in {"ok", "cached"}),
        "errors": [item for item in results if item["status"] == "error"][:5],
    }


def apply_cached_enrichments(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT f.*, (SELECT e.response_json FROM item_enrichments e WHERE e.item_id=f.id AND e.status='ok' "
        "AND e.prompt_version=? ORDER BY e.id DESC LIMIT 1) AS enrichment_json "
        "FROM feed_items f WHERE EXISTS (SELECT 1 FROM item_enrichments e WHERE e.item_id=f.id AND e.status='ok' AND e.prompt_version=?)",
        (ENRICH_PROMPT_VERSION, ENRICH_PROMPT_VERSION),
    ).fetchall()
    applied = 0
    for row in rows:
        response = json_loads(row["enrichment_json"], {})
        if not isinstance(response, dict) or not response:
            continue
        normalized = normalize_model_enrichment(response, row)
        normalized["updated_at"] = now_iso()
        conn.execute(
            "UPDATE feed_items SET " + ",".join(f"{key}=?" for key in normalized) + " WHERE id=?",
            [*normalized.values(), row["id"]],
        )
        applied += 1
    if applied:
        conn.commit()
    return applied


AI_RELEVANCE_WEIGHTS = {
    "ai": 8, "agent": 14, "agents": 14, "智能体": 14, "大模型": 14, "模型": 8,
    "openai": 12, "claude": 12, "anthropic": 12, "deepseek": 12, "gemini": 10,
    "gpt": 10, "llm": 10, "mcp": 10, "aigc": 9, "生成式": 8, "自动化": 10,
    "api": 6, "sdk": 6, "开源": 7, "部署": 6, "产品": 6, "工具": 6,
}

BUSINESS_RELEVANCE_WEIGHTS = {
    "一人公司": 24, "独立开发": 20, "solo": 12, "创业": 14, "获客": 14,
    "营销": 12, "增长": 10, "运营": 12, "低成本": 14, "自动化": 12,
    "workflow": 10, "工作流": 10, "客服": 8, "销售": 8, "内容": 8,
}

NOISE_TERMS = ("广告", "软文", "福利", "抽奖", "无关", "标题党", "营销号")


def weighted_keyword_score(text: str, weights: dict[str, int], *, cap: float = 100.0) -> float:
    lower = text.lower()
    score = 0.0
    for term, weight in weights.items():
        if term.lower() in lower:
            score += weight
    return round(min(cap, score), 2)


def recency_score(value: Any) -> float:
    dt = parse_iso_datetime(value)
    hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    if hours <= 6:
        return 100.0
    if hours <= 24:
        return round(92.0 - (hours - 6) * 0.8, 2)
    if hours <= 72:
        return round(76.0 - (hours - 24) * 0.45, 2)
    if hours <= 168:
        return round(56.0 - (hours - 72) * 0.18, 2)
    return max(12.0, round(38.0 - min(26.0, (hours - 168) * 0.04), 2))


def source_credibility(item: dict[str, Any]) -> float:
    channel = compact_text(item.get("channel"), limit=40)
    source_name = compact_text(item.get("sourceName") or item.get("accountName") or item.get("source"), limit=200).lower()
    source_kind = compact_text(item.get("sourceKind") or item.get("source_kind"), limit=120).lower()
    base = {
        "firstParty": 84.0,
        "github": 72.0,
        "product": 68.0,
        "community": 56.0,
        "news": 60.0,
        "mp": 62.0,
    }.get(channel, 50.0)
    if any(name in source_name for name in ("openai", "anthropic", "deepmind", "google", "hugging face", "apple", "xai", "claude")):
        base += 10
    if "official" in source_kind or "release" in source_kind:
        base += 6
    if "reddit" in source_name:
        base -= 7
    if "youtube" in source_kind:
        base -= 3
    return round(max(20.0, min(100.0, base)), 2)


def latest_enrichment_map(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        "SELECT item_id,response_json FROM item_enrichments WHERE status='ok' "
        "ORDER BY item_id ASC, CASE WHEN prompt_version=? THEN 1 ELSE 0 END DESC, id DESC",
        (ENRICH_PROMPT_VERSION,),
    ).fetchall()
    seen: set[int] = set()
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        payload = json_loads(row["response_json"], {})
        if isinstance(payload, dict):
            result[item_id] = payload
    return result


def latest_mp_enrichment_map(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT mp_article_id,response_json FROM mp_enrichments WHERE status='ok' "
            "ORDER BY mp_article_id ASC, CASE WHEN prompt_version=? THEN 1 ELSE 0 END DESC, id DESC",
            (ENRICH_PROMPT_VERSION,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    seen: set[int] = set()
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        item_id = int(row["mp_article_id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        payload = json_loads(row["response_json"], {})
        if isinstance(payload, dict):
            result[item_id] = payload
    return result


def model_channel_fit(enrichment: dict[str, Any] | None, channel: str) -> dict[str, Any]:
    if not isinstance(enrichment, dict):
        return {"score": 0.0, "reject": False, "mustInclude": False, "reason": ""}
    fits = enrichment.get("channelFits") or enrichment.get("channel_fits") or {}
    fit = fits.get(channel) if isinstance(fits, dict) else {}
    if not isinstance(fit, dict):
        fit = {}
    return {
        "score": clamp_float(fit.get("fitScore") or fit.get("score"), 0, 100, 0.0),
        "reject": bool(fit.get("reject")),
        "mustInclude": bool(fit.get("mustInclude") or fit.get("must_include")),
        "reason": compact_text(fit.get("reason") or fit.get("editorReason"), limit=300),
    }


def public_item_text(item: dict[str, Any]) -> str:
    tags = " ".join(compact_text(tag.get("tag") if isinstance(tag, dict) else tag) for tag in item.get("aiTags", []) or [])
    return " ".join(
        [
            compact_text(item.get("titleZh") or item.get("title")),
            compact_text(item.get("summaryZh") or item.get("summary")),
            compact_text(item.get("itemType")),
            compact_text(item.get("sourceName") or item.get("accountName")),
            tags,
        ]
    )


def item_metric_bundle(item: dict[str, Any], enrichment: dict[str, Any] | None = None) -> dict[str, float]:
    text = public_item_text(item)
    axes = item.get("qualityAxesJson") if isinstance(item.get("qualityAxesJson"), dict) else {}
    final_score = clamp_float(item.get("finalScore"), 0, 100, 0.0)
    importance = clamp_float(item.get("importance"), 0, 100, final_score)
    quality = clamp_float(item.get("qualityScore"), 0, 100, final_score)
    ai_score = max(
        weighted_keyword_score(text, AI_RELEVANCE_WEIGHTS),
        clamp_float((enrichment or {}).get("aiRelevance"), 0, 100, 0.0),
        final_score * 0.55,
    )
    business = max(
        weighted_keyword_score(text, BUSINESS_RELEVANCE_WEIGHTS),
        clamp_float((enrichment or {}).get("businessValue"), 0, 100, 0.0),
    )
    novelty = max(clamp_float(axes.get("nov"), 1, 9, 5) * 11.1, clamp_float((enrichment or {}).get("novelty"), 0, 100, 0.0))
    utility = max(clamp_float(axes.get("act"), 1, 9, 5) * 11.1, clamp_float((enrichment or {}).get("utility"), 0, 100, 0.0))
    evidence = max(clamp_float(axes.get("cred"), 1, 9, 5) * 11.1, source_credibility(item))
    resonance = clamp_float(axes.get("reson"), 1, 9, 5) * 11.1
    recency = recency_score(item.get("publishedAt"))
    duplicate_penalty = min(22.0, clamp_float(item.get("duplicateCount"), 0, 20, 0.0) * 5.5)
    noise_penalty = 12.0 if any(term in text for term in NOISE_TERMS) else 0.0
    return {
        "final": final_score,
        "importance": importance,
        "quality": quality,
        "ai": round(min(100.0, ai_score), 2),
        "business": round(min(100.0, business), 2),
        "novelty": round(min(100.0, novelty), 2),
        "utility": round(min(100.0, utility), 2),
        "evidence": round(min(100.0, evidence), 2),
        "resonance": round(min(100.0, resonance), 2),
        "recency": recency,
        "duplicatePenalty": duplicate_penalty,
        "noisePenalty": noise_penalty,
    }


def channel_candidate_score(item: dict[str, Any], channel: str, enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = item_metric_bundle(item, enrichment)
    model = model_channel_fit(enrichment, channel)
    model_score = model["score"]
    model_blend = model_score if model_score > 0 else max(metrics["ai"], metrics["business"] if channel == "opcSolo" else 0, metrics["final"])
    reasons: list[str] = []
    flags: list[str] = []
    source_channel = compact_text(item.get("channel"), limit=40)
    base_score = round(
        metrics["ai"] * 0.20
        + metrics["evidence"] * 0.15
        + metrics["recency"] * 0.15
        + metrics["novelty"] * 0.15
        + metrics["resonance"] * 0.10
        + metrics["utility"] * 0.10
        + metrics["final"] * 0.15
        - metrics["duplicatePenalty"]
        - metrics["noisePenalty"],
        2,
    )

    if channel == "selected":
        score = (
            metrics["importance"] * 0.22
            + metrics["novelty"] * 0.18
            + metrics["evidence"] * 0.18
            + metrics["utility"] * 0.13
            + metrics["recency"] * 0.10
            + metrics["final"] * 0.12
            + model_blend * 0.07
            - metrics["duplicatePenalty"]
            - metrics["noisePenalty"]
        )
        selected = (score >= 72 and metrics["ai"] >= 45 and metrics["evidence"] >= 52) or bool(item.get("aiSelected") and score >= 62)
        if source_channel == "firstParty":
            reasons.append("官方/一手信源加权")
        if item.get("aiSelected"):
            reasons.append("上游已入选精选候选")
    elif channel == "daily":
        score = (
            metrics["recency"] * 0.24
            + metrics["importance"] * 0.18
            + metrics["novelty"] * 0.15
            + metrics["evidence"] * 0.13
            + metrics["resonance"] * 0.10
            + metrics["utility"] * 0.08
            + model_blend * 0.12
            - metrics["duplicatePenalty"] * 0.6
            - metrics["noisePenalty"]
        )
        selected = score >= 56 and metrics["ai"] >= 35
        reasons.append(f"日报分组：{daily_section_for_item(item)}")
    elif channel == "mp":
        is_mp = source_channel == "mp" or str(item.get("id", "")).startswith("mp-")
        score = (
            metrics["ai"] * 0.18
            + metrics["recency"] * 0.12
            + metrics["final"] * 0.22
            + metrics["resonance"] * 0.12
            + metrics["evidence"] * 0.10
            + metrics["utility"] * 0.10
            + model_blend * 0.16
            - metrics["duplicatePenalty"]
            - metrics["noisePenalty"] * 1.4
        )
        selected = bool(
            is_mp
            and (
                (score >= 55 and metrics["ai"] >= 42)
                or (score >= 52 and metrics["ai"] >= 28 and metrics["evidence"] >= 60)
                or (score >= 58 and metrics["ai"] >= 24)
            )
        )
        if not is_mp:
            flags.append("not_mp_source")
    elif channel == "opcSolo":
        opc_hit = is_opc_solo_item(dict(item))
        score = (
            metrics["business"] * 0.26
            + metrics["utility"] * 0.19
            + weighted_keyword_score(public_item_text(item), OPC_SOLO_TERMS) * 0.16
            + metrics["recency"] * 0.08
            + metrics["evidence"] * 0.10
            + metrics["final"] * 0.08
            + model_blend * 0.13
            - metrics["duplicatePenalty"]
            - metrics["noisePenalty"]
        )
        selected = (opc_hit and score >= 54) or (model_score >= 76 and metrics["business"] >= 38)
        reasons.append("按一人公司业务场景独立评分")
    else:
        score = (
            metrics["recency"] * 0.42
            + base_score * 0.23
            + metrics["final"] * 0.20
            + model_blend * 0.08
            + source_credibility(item) * 0.07
            - metrics["duplicatePenalty"] * 0.35
            - metrics["noisePenalty"]
        )
        selected = metrics["ai"] >= 30 or metrics["final"] >= 35 or bool(item.get("aiSelected"))
        reasons.append("全站有效 AI 动态整合")

    if model["reject"] and not model["mustInclude"]:
        score -= 35
        selected = False
        flags.append("deepseek_reject")
    if model["mustInclude"]:
        score += 8
        selected = True
        reasons.append("DeepSeek 标记为栏目必看")
    if model["reason"]:
        reasons.append(model["reason"])
    if metrics["noisePenalty"]:
        flags.append("noise_penalty")
    if metrics["duplicatePenalty"]:
        flags.append("duplicate_penalty")
    return {
        "score": round(max(0.0, min(100.0, score)), 2),
        "baseScore": round(max(0.0, min(100.0, base_score)), 2),
        "modelScore": round(model_score, 2),
        "selected": bool(selected),
        "reasons": list(dict.fromkeys([reason for reason in reasons if reason]))[:8],
        "flags": list(dict.fromkeys(flags))[:8],
        "metrics": metrics,
    }


def insert_channel_candidate(conn: sqlite3.Connection, channel: str, item_type: str, item: dict[str, Any], scoring: dict[str, Any]) -> None:
    ts = now_iso()
    item_id_raw = str(item.get("id") or "0").replace("mp-", "")
    item_id = int(item_id_raw) if item_id_raw.isdigit() else 0
    conn.execute(
        "INSERT INTO channel_candidates(channel,item_type,item_id,item_uid,source_channel,score,base_score,model_score,selected,reasons_json,flags_json,detail_json,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            channel,
            item_type,
            item_id,
            stable_uid(item_type, item.get("id"), item.get("url"), item.get("titleZh") or item.get("title")),
            compact_text(item.get("channel"), limit=40),
            scoring["score"],
            scoring["baseScore"],
            scoring["modelScore"],
            1 if scoring["selected"] else 0,
            json_dumps(scoring["reasons"]),
            json_dumps(scoring["flags"]),
            json_dumps(scoring.get("metrics") or {}),
            ts,
            ts,
        ),
    )


def insert_channel_item(conn: sqlite3.Connection, channel: str, rank: int, item_type: str, item: dict[str, Any], scoring: dict[str, Any]) -> None:
    ts = now_iso()
    payload = dict(item)
    payload["channelScore"] = scoring["score"]
    payload["channelReasons"] = scoring["reasons"]
    payload["channelFlags"] = scoring["flags"]
    if channel == "daily":
        payload["dailySection"] = daily_section_for_item(item)
    if channel == "opcSolo":
        payload["opcSoloScore"] = max(float(payload.get("opcSoloScore") or 0), scoring["score"])
    if channel == "selected":
        payload["aiSelected"] = True
        payload["aiSelectedReason"] = "; ".join(scoring["reasons"]) or payload.get("aiSelectedReason")
    item_id_raw = str(item.get("id") or "0").replace("mp-", "")
    item_id = int(item_id_raw) if item_id_raw.isdigit() else 0
    conn.execute(
        "INSERT INTO channel_items(channel,rank,item_type,item_id,item_uid,source_channel,score,title,source_name,url,published_at,payload_json,reasons_json,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            channel,
            rank,
            item_type,
            item_id,
            stable_uid(item_type, item.get("id"), item.get("url"), item.get("titleZh") or item.get("title")),
            compact_text(item.get("channel"), limit=40),
            scoring["score"],
            compact_text(item.get("titleZh") or item.get("title"), limit=300),
            compact_text(item.get("sourceName") or item.get("accountName"), limit=180),
            compact_text(item.get("url") or item.get("link"), limit=1200),
            parse_item_time(item.get("publishedAt")),
            json_dumps(payload),
            json_dumps(scoring["reasons"]),
            ts,
            ts,
        ),
    )


def dedupe_channel_candidates(candidates: list[tuple[dict[str, Any], str, dict[str, Any]]], *, limit: int, per_source_cap: dict[str, int] | None = None) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    result: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    seen: set[str] = set()
    source_counts: dict[str, int] = {}
    for item, item_type, scoring in sorted(candidates, key=lambda row: row[2]["score"], reverse=True):
        key = compact_text(item.get("url") or item.get("link"), limit=1200) or stable_uid(compact_text(item.get("titleZh") or item.get("title"), limit=240).lower(), compact_text(item.get("sourceName") or item.get("accountName"), limit=120).lower())
        if key in seen:
            continue
        source_channel = compact_text(item.get("channel"), limit=40)
        cap = (per_source_cap or {}).get(source_channel)
        if cap is not None and source_counts.get(source_channel, 0) >= cap:
            continue
        seen.add(key)
        source_counts[source_channel] = source_counts.get(source_channel, 0) + 1
        result.append((item, item_type, scoring))
        if len(result) >= limit:
            break
    return result


def rebuild_channel_views(conn: sqlite3.Connection) -> dict[str, Any]:
    enrichments = latest_enrichment_map(conn)
    mp_enrichments = latest_mp_enrichment_map(conn)
    conn.execute("DELETE FROM channel_candidates")
    conn.execute("DELETE FROM channel_items")
    buckets: dict[str, list[tuple[dict[str, Any], str, dict[str, Any]]]] = {"all": [], "selected": [], "daily": [], "mp": [], "opcSolo": []}
    feed_rows = conn.execute("SELECT * FROM feed_items WHERE channel!='x' ORDER BY published_at DESC LIMIT 600").fetchall()
    for row in feed_rows:
        item = decorate_public_item(conn, row_to_public_item(row))
        enrichment = enrichments.get(int(row["id"]))
        for channel in buckets:
            if channel == "mp":
                continue
            scoring = channel_candidate_score(item, channel, enrichment)
            insert_channel_candidate(conn, channel, "feed", item, scoring)
            if scoring["selected"]:
                buckets[channel].append((item, "feed", scoring))
    mp_rows = conn.execute("SELECT * FROM mp_articles ORDER BY heat_score DESC, published_at DESC LIMIT 300").fetchall()
    for row in mp_rows:
        item = mp_row_to_public_item(row)
        enrichment = mp_enrichments.get(int(row["id"]))
        for channel in buckets:
            scoring = channel_candidate_score(item, channel, enrichment)
            insert_channel_candidate(conn, channel, "mp", item, scoring)
            if scoring["selected"]:
                buckets[channel].append((item, "mp", scoring))

    all_items = sorted(buckets["all"], key=lambda row: (parse_iso_datetime(row[0].get("publishedAt")), row[2]["score"]), reverse=True)[:400]
    selected_items = dedupe_channel_candidates(buckets["selected"], limit=70, per_source_cap={"github": 24, "community": 18, "firstParty": 18, "news": 10, "product": 12, "mp": 12})
    daily_items = dedupe_channel_candidates(buckets["daily"], limit=80)
    mp_items = dedupe_channel_candidates(buckets["mp"], limit=120)
    opc_items = dedupe_channel_candidates(buckets["opcSolo"], limit=120)
    final = {"all": all_items, "selected": selected_items, "daily": daily_items, "mp": mp_items, "opcSolo": opc_items}
    for channel, rows in final.items():
        for rank, (item, item_type, scoring) in enumerate(rows, 1):
            insert_channel_item(conn, channel, rank, item_type, item, scoring)
    conn.commit()
    return {
        "status": "ok",
        "items": {channel: len(rows) for channel, rows in final.items()},
        "candidates": {channel: len(rows) for channel, rows in buckets.items()},
        "enrichedItems": len(enrichments),
        "mpEnrichedItems": len(mp_enrichments),
    }


def channel_item_count(conn: sqlite3.Connection, channel: str, fallback_sql: str = "") -> int:
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM channel_items WHERE channel=?", (channel,)).fetchone()["c"]
        if count:
            return int(count)
    except Exception:
        pass
    if fallback_sql:
        return int(conn.execute(fallback_sql).fetchone()["c"])
    return 0


def ensure_channel_views(conn: sqlite3.Connection) -> None:
    try:
        has_views = conn.execute("SELECT COUNT(*) AS c FROM channel_items").fetchone()["c"]
    except Exception:
        has_views = 0
    if not has_views and conn.execute("SELECT COUNT(*) AS c FROM feed_items").fetchone()["c"]:
        rebuild_channel_views(conn)


def normalize_item(raw: dict[str, Any], *, selected: bool, section: str) -> dict[str, Any] | None:
    channel = infer_channel(raw)
    if channel == "x":
        return None
    title = compact_text(raw.get("title"), limit=240)
    if not title:
        return None
    summary = compact_text(raw.get("summary") or raw.get("one_liner") or raw.get("description"), limit=1200)
    url = compact_text(raw.get("link") or raw.get("url"), limit=1000)
    source_name = compact_text(raw.get("source_name") or raw.get("category") or "Unknown Source", limit=160)
    source_kind = compact_text(raw.get("source_kind") or raw.get("category") or channel, limit=120)
    published_at = parse_item_time(raw.get("published") or raw.get("published_at") or raw.get("observed_at"))
    observed_at = parse_item_time(raw.get("observed_at") or raw.get("published") or raw.get("published_at"))
    score = float(raw.get("signal_score") or raw.get("score") or raw.get("heat_score") or 0)
    if selected and score < 8:
        score = 8.0
    scores = score_bundle(channel, score, selected)
    item_type = infer_item_type(channel, raw)
    tags = ai_tags_for(channel, raw)
    reason = "多信源/高分策略命中" if selected else "进入全量 AI 动态池"
    if channel == "github":
        reason = "开发者增长动量达到精选阈值" if selected else "GitHub 开源生态信号"
    elif channel == "firstParty":
        reason = "官方一手信源优先" if selected else "官方信源入库"
    elif channel == "product":
        reason = "产品发布热度与构建者表面命中" if selected else "Product Hunt AI 产品信号"
    elif channel == "community":
        reason = "社区/视频层出现讨论热度" if selected else "社区证据层信号"
    return {
        "uid": stable_uid(url or title, source_name, published_at[:10]),
        "title": title,
        "title_zh": title,
        "summary": summary,
        "summary_zh": summary or title,
        "url": url,
        "source_name": source_name,
        "source_kind": source_kind,
        "channel": channel,
        "published_at": published_at,
        "observed_at": observed_at,
        "item_type": item_type,
        "importance": scores["importance"],
        "quality_score": scores["quality_score"],
        "final_score": scores["final_score"],
        "ai_selected": 1 if selected else 0,
        "ai_selected_reason": reason,
        "ai_tags_json": json_dumps(tags),
        "duplicate_count": int(raw.get("duplicate_count") or 0),
        "quality_axes_json": json_dumps(quality_axes(channel, score, selected)),
        "editorial_judgment": "建议重点关注" if selected else "保留观察",
        "raw_json": json_dumps({**raw, "import_section": section}),
        "source_origin": "dynamic_collector",
        "provenance_json": json_dumps({
            "collector": "welopc_latest_json",
            "importSection": section,
            "sourceName": source_name,
            "sourceKind": source_kind,
            "url": url,
        }),
    }


def upsert_item(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    ts = now_iso()
    fields = [
        "uid", "title", "title_zh", "summary", "summary_zh", "url", "source_name", "source_kind", "channel",
        "published_at", "observed_at", "item_type", "importance", "quality_score", "final_score", "ai_selected",
        "ai_selected_reason", "ai_tags_json", "duplicate_count", "quality_axes_json", "editorial_judgment", "raw_json",
        "source_origin", "provenance_json",
    ]
    values = [item.get(field) for field in fields]
    update_fields = [field for field in fields if field not in {"uid", "ai_selected", "ai_selected_reason", "final_score"}]
    conn.execute(
        "INSERT INTO feed_items(" + ",".join(fields) + ",created_at,updated_at) VALUES(" + ",".join(["?"] * (len(fields) + 2)) + ") "
        "ON CONFLICT(uid) DO UPDATE SET "
        + ",".join([f"{field}=excluded.{field}" for field in update_fields])
        + ", ai_selected=CASE WHEN feed_items.ai_selected=1 OR excluded.ai_selected=1 THEN 1 ELSE 0 END"
        + ", ai_selected_reason=CASE WHEN excluded.ai_selected=1 THEN excluded.ai_selected_reason ELSE feed_items.ai_selected_reason END"
        + ", final_score=MAX(feed_items.final_score, excluded.final_score)"
        + ", updated_at=excluded.updated_at",
        [*values, ts, ts],
    )


def upsert_source(
    conn: sqlite3.Connection,
    *,
    source_uid: str = "",
    name: str,
    source_kind: str,
    channel: str,
    status: str,
    count: int,
    detail: str = "",
    elapsed_ms: int = 0,
    url: str = "",
    config: dict[str, Any] | None = None,
) -> None:
    if channel == "x":
        return
    uid = compact_text(source_uid, limit=120) or stable_uid(name, source_kind, channel)
    ts = now_iso()
    conn.execute(
        "INSERT INTO sources(uid,name,source_kind,channel,url,last_status,last_count,last_checked_at,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, source_kind=excluded.source_kind, channel=excluded.channel, "
        "url=COALESCE(NULLIF(excluded.url,''), sources.url), last_status=excluded.last_status, last_count=excluded.last_count, "
        "last_checked_at=excluded.last_checked_at, config_json=CASE WHEN excluded.config_json='{}' THEN sources.config_json ELSE excluded.config_json END, updated_at=excluded.updated_at",
        (uid, name, source_kind, channel, url, status, int(count or 0), ts, json_dumps(config or {}), ts, ts),
    )
    conn.execute(
        "INSERT INTO source_health(source_uid,source_name,source_kind,channel,status,item_count,detail,elapsed_ms,checked_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (uid, name, source_kind, channel, status, int(count or 0), detail, int(elapsed_ms or 0), ts),
    )


def collect_payload_items(payload: dict[str, Any]) -> list[tuple[dict[str, Any], bool, str]]:
    rows: list[tuple[dict[str, Any], bool, str]] = []
    for key, selected in [("top_signals", True), ("recent_items", False), ("community_hotspots", False), ("community_video_hotspots", False)]:
        for raw in payload.get(key, []) or []:
            if isinstance(raw, dict):
                rows.append((raw, selected, key))
    for topic in payload.get("mass_hot_topics", []) or []:
        if not isinstance(topic, dict):
            continue
        top_items = topic.get("top_items") or []
        if top_items:
            for raw in top_items:
                if isinstance(raw, dict):
                    rows.append(({**raw, "topic_name": topic.get("name", "")}, True, "mass_hot_topics"))
        else:
            rows.append(({
                "title": topic.get("name"),
                "summary": topic.get("one_liner") or topic.get("summary"),
                "source_name": "Topic Cluster",
                "source_kind": "topic_cluster",
                "category": "news",
                "published": payload.get("generated_at"),
                "signal_score": topic.get("score", 10),
            }, True, "mass_hot_topics"))
    return rows


def regenerate_daily(conn: sqlite3.Connection) -> dict[str, Any]:
    daily_rows = conn.execute("SELECT * FROM channel_items WHERE channel='daily' ORDER BY score DESC, published_at DESC LIMIT 120").fetchall()
    if daily_rows:
        section_order = ["model_release", "product_tool", "developer", "research_paper", "community", "industry", "mp", "opc_solo"]
        groups: dict[str, list[dict[str, Any]]] = {section: [] for section in section_order}
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in daily_rows:
            item = json_loads(row["payload_json"], {})
            if not isinstance(item, dict):
                continue
            key = compact_text(item.get("url") or item.get("link"), limit=1200) or stable_uid(item.get("titleZh") or item.get("title"), item.get("sourceName"))
            if key in seen:
                continue
            seen.add(key)
            section = compact_text(item.get("dailySection"), limit=40) or daily_section_for_item(item)
            if section == "opcSolo":
                section = "opc_solo"
            groups.setdefault(section, [])
            if len(groups[section]) >= 8:
                continue
            groups[section].append(item)
            if len(selected) < 10 and bool(item.get("aiSelected")):
                selected.append(item)
        groups = {section: items for section, items in groups.items() if items}
        title = f"AI 日报 {date.today().isoformat()}"
        top_items = selected or [item for items in groups.values() for item in items][:8]
        summary = "；".join(compact_text(item.get("titleZh") or item.get("title"), limit=80) for item in top_items[:4]) or "今日暂无足够精选信号"
        labels = {
            "model_release": "模型发布/更新",
            "product_tool": "产品与工具",
            "research_paper": "论文/研究",
            "developer": "开发者与开源",
            "industry": "行业/商业/监管",
            "community": "社区讨论",
            "mp": "中文公众号观察",
            "opc_solo": "一人公司机会",
        }
        lines = [f"# {title}", "", "DAILY · 独立栏目策略生成", "", summary, ""]
        for section in section_order:
            items = groups.get(section) or []
            if not items:
                continue
            lines.append(f"## {labels.get(section, section)}")
            for item in items[:8]:
                lines.append(f"- {item.get('titleZh') or item.get('title')} - {item.get('sourceName') or item.get('source')} ({round(float(item.get('channelScore') or item.get('finalScore') or 0), 2)})")
            lines.append("")
        content = {"groups": groups, "selected": top_items[:10], "generatedBy": SERVICE_NAME, "strategy": "independent_channel_items"}
        ts = now_iso()
        issue_date = date.today().isoformat()
        markdown = "\n".join(lines).strip() + "\n"
        conn.execute(
            "INSERT INTO daily_issues(issue_date,title,summary,content_json,markdown,status,generated_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(issue_date) DO UPDATE SET title=excluded.title, summary=excluded.summary, content_json=excluded.content_json, "
            "markdown=excluded.markdown, status=excluded.status, generated_at=excluded.generated_at, updated_at=excluded.updated_at",
            (issue_date, title, summary, json_dumps(content), markdown, "published", ts, ts, ts),
        )
        conn.commit()
        return {"issueDate": issue_date, "title": title, "summary": summary, "content": content, "markdown": markdown, "generatedAt": ts}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    rows = conn.execute(
        "SELECT * FROM feed_items WHERE published_at>=? ORDER BY ai_selected DESC, final_score DESC, published_at DESC LIMIT 160",
        (cutoff,),
    ).fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM feed_items ORDER BY ai_selected DESC, final_score DESC, published_at DESC LIMIT 160").fetchall()
    section_order = ["model_release", "product_tool", "developer", "research_paper", "community", "industry"]
    groups: dict[str, list[dict[str, Any]]] = {section: [] for section in section_order}
    seen_ids: set[str] = set()
    for phase in ("selected", "fallback"):
        for row in rows:
            if phase == "selected" and not row["ai_selected"]:
                continue
            if phase == "fallback" and row["ai_selected"]:
                continue
            item = row_to_public_item(row)
            if item["id"] in seen_ids:
                continue
            section = daily_section_for_item(item)
            groups.setdefault(section, [])
            if len(groups[section]) >= 8:
                continue
            groups[section].append(item)
            seen_ids.add(item["id"])
    groups = {section: items for section, items in groups.items() if items}
    title = f"AI 日报 {date.today().isoformat()}"
    selected = [row_to_public_item(row) for row in rows if row["ai_selected"]][:8]
    summary = "；".join(item["titleZh"] for item in selected[:4]) or "今日暂无足够精选信号"
    lines = [f"# {title}", "", "DAILY · 每早八时", "", summary, ""]
    labels = {
        "model_release": "模型发布/更新",
        "product_tool": "产品与工具",
        "research_paper": "论文/研究",
        "developer": "开发者与开源",
        "industry": "行业/商业/监管",
        "community": "社区讨论",
    }
    for channel in section_order:
        items = groups.get(channel) or []
        if not items:
            continue
        lines.append(f"## {labels.get(channel, channel)}")
        for item in items[:8]:
            lines.append(f"- {item['titleZh']} - {item.get('sourceName') or item.get('source')} ({round(float(item.get('finalScore') or 0), 2)})")
        lines.append("")
    content = {"groups": groups, "selected": selected, "generatedBy": SERVICE_NAME}
    ts = now_iso()
    issue_date = date.today().isoformat()
    markdown = "\n".join(lines).strip() + "\n"
    conn.execute(
        "INSERT INTO daily_issues(issue_date,title,summary,content_json,markdown,status,generated_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(issue_date) DO UPDATE SET title=excluded.title, summary=excluded.summary, content_json=excluded.content_json, "
        "markdown=excluded.markdown, status=excluded.status, generated_at=excluded.generated_at, updated_at=excluded.updated_at",
        (issue_date, title, summary, json_dumps(content), markdown, "published", ts, ts, ts),
    )
    conn.commit()
    return {"issueDate": issue_date, "title": title, "summary": summary, "content": content, "markdown": markdown, "generatedAt": ts}


def rebalance_legacy_scores(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id, channel, ai_selected, raw_json, importance, quality_score, final_score FROM feed_items WHERE final_score < 25").fetchall()
    changed = 0
    for row in rows:
        raw = json_loads(row["raw_json"], {})
        if not isinstance(raw, dict):
            raw = {}
        try:
            raw_score = float(raw.get("signal_score") or raw.get("score") or raw.get("heat_score") or 0)
        except Exception:
            raw_score = 0.0
        selected = bool(row["ai_selected"])
        if selected and raw_score < 8:
            raw_score = 8.0
        scores = score_bundle(row["channel"], raw_score, selected)
        conn.execute(
            "UPDATE feed_items SET importance=?, quality_score=?, final_score=?, quality_axes_json=?, updated_at=? WHERE id=?",
            (scores["importance"], scores["quality_score"], scores["final_score"], json_dumps(quality_axes(row["channel"], raw_score, selected)), now_iso(), row["id"]),
        )
        changed += 1
    if changed:
        conn.commit()
    return changed


def import_latest(conn: sqlite3.Connection, *, latest_path: Path = LATEST_JSON_PATH) -> dict[str, Any]:
    started = now_iso()
    cur = conn.execute("INSERT INTO pipeline_runs(run_type,status,started_at,message) VALUES(?,?,?,?)", ("import_latest", "running", started, f"Importing {latest_path}"))
    run_id = int(cur.lastrowid)
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
        configured_sources = seed_sources_from_config(conn)
        ensure_mp_sources_config()
        source_count = configured_sources
        for health in payload.get("source_health", []) or []:
            if not isinstance(health, dict):
                continue
            name = compact_text(health.get("name") or health.get("source_name") or health.get("source") or "Unknown")
            source_kind = compact_text(health.get("source_kind") or health.get("kind") or health.get("group") or "unknown")
            channel = infer_channel({"source_kind": source_kind, "source_name": name, "category": health.get("group", "")})
            if channel == "x":
                continue
            upsert_source(
                conn,
                name=name,
                source_kind=source_kind,
                channel=channel,
                status=compact_text(health.get("status") or "unknown"),
                count=int(health.get("count") or health.get("item_count") or 0),
                detail=compact_text(health.get("detail") or health.get("message"), limit=500),
                elapsed_ms=int(health.get("elapsed_ms") or 0),
            )
            source_count += 1
        imported = 0
        selected_count = 0
        for raw, selected, section in collect_payload_items(payload):
            item = normalize_item(raw, selected=selected, section=section)
            if not item:
                continue
            upsert_item(conn, item)
            imported += 1
            selected_count += int(bool(item["ai_selected"]))
            upsert_source(conn, name=item["source_name"], source_kind=item["source_kind"], channel=item["channel"], status="ok", count=1)
        mp_result = collect_mp_dynamic(conn)
        legacy_rebalanced = rebalance_legacy_scores(conn)
        cached_enrichments = apply_cached_enrichments(conn)
        if os.getenv("DEEPSEEK_AUTO_ENRICH", "0") == "1":
            enrich_items(conn, limit=clamp_int(os.getenv("DEEPSEEK_AUTO_ENRICH_LIMIT", "20"), 1, 80, 20), force=False)
            cached_enrichments += apply_cached_enrichments(conn)
        refresh_duplicates(conn)
        channel_views = rebuild_channel_views(conn)
        regenerate_daily(conn)
        conn.execute(
            "UPDATE pipeline_runs SET status=?, finished_at=?, item_count=?, selected_count=?, source_count=?, message=?, log_text=? WHERE id=?",
            ("ok", now_iso(), imported, selected_count, source_count, "Import completed", json_dumps({"latest": str(latest_path), "generated_at": payload.get("generated_at"), "legacy_rebalanced": legacy_rebalanced, "cached_enrichments": cached_enrichments, "mp_dynamic": mp_result, "channel_views": channel_views}), run_id),
        )
        conn.commit()
        return {"status": "ok", "runId": run_id, "itemCount": imported, "selectedCount": selected_count, "sourceCount": source_count}
    except Exception as exc:
        conn.execute("UPDATE pipeline_runs SET status=?, finished_at=?, message=?, log_text=? WHERE id=?", ("error", now_iso(), str(exc), traceback.format_exc(), run_id))
        conn.commit()
        raise


def run_full_pipeline(conn: sqlite3.Connection) -> dict[str, Any]:
    cur = conn.execute("INSERT INTO pipeline_runs(run_type,status,started_at,message) VALUES(?,?,?,?)", ("collector", "running", now_iso(), "Running ai-news-schedule-run --force"))
    run_id = int(cur.lastrowid)
    conn.commit()
    try:
        result = subprocess.run(
            [str(APP_ROOT / ".venv" / "bin" / "python"), "-m", "ecom_research.cli", "ai-news-schedule-run", "--force"],
            cwd=str(APP_ROOT),
            text=True,
            capture_output=True,
            timeout=900,
            env=os.environ.copy(),
        )
        log = (result.stdout or "")[-6000:] + ("\n" + (result.stderr or "")[-6000:] if result.stderr else "")
        if result.returncode != 0:
            raise RuntimeError(f"collector failed with exit code {result.returncode}\n{log[-2000:]}")
        imported = import_latest(conn)
        conn.execute(
            "UPDATE pipeline_runs SET status=?, finished_at=?, message=?, log_text=?, item_count=?, selected_count=?, source_count=? WHERE id=?",
            ("ok", now_iso(), "Collector and import completed", log, imported.get("itemCount", 0), imported.get("selectedCount", 0), imported.get("sourceCount", 0), run_id),
        )
        conn.commit()
        return {"status": "ok", "runId": run_id, "import": imported}
    except Exception as exc:
        conn.execute("UPDATE pipeline_runs SET status=?, finished_at=?, message=?, log_text=? WHERE id=?", ("error", now_iso(), str(exc), traceback.format_exc(), run_id))
        conn.commit()
        raise


def duplicate_tokens(text: str) -> set[str]:
    normalized = compact_text(text).lower()
    words = set(re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", normalized))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    grams = {cjk[i : i + 2] for i in range(max(len(cjk) - 1, 0))}
    stop = {"the", "and", "for", "with", "from", "this", "that", "ai"}
    return {token for token in words | grams if token and token not in stop}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def refresh_duplicates(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT id,title_zh,summary_zh,source_name,published_at FROM feed_items WHERE channel!='x' ORDER BY published_at DESC LIMIT 240").fetchall()
    conn.execute("DELETE FROM item_duplicates")
    pairs = 0
    prepared = [
        {
            "id": row["id"],
            "source": row["source_name"],
            "tokens": duplicate_tokens(f"{row['title_zh']} {row['summary_zh']}"),
        }
        for row in rows
    ]
    ts = now_iso()
    for i, left in enumerate(prepared):
        for right in prepared[i + 1 :]:
            score_value = jaccard(left["tokens"], right["tokens"])
            if score_value < 0.42:
                continue
            reason = "title_summary_similarity"
            conn.execute(
                "INSERT OR IGNORE INTO item_duplicates(item_id,duplicate_item_id,score,reason,created_at) VALUES(?,?,?,?,?)",
                (left["id"], right["id"], round(score_value, 4), reason, ts),
            )
            conn.execute(
                "INSERT OR IGNORE INTO item_duplicates(item_id,duplicate_item_id,score,reason,created_at) VALUES(?,?,?,?,?)",
                (right["id"], left["id"], round(score_value, 4), reason, ts),
            )
            pairs += 1
    conn.execute(
        "UPDATE feed_items SET duplicate_count=(SELECT COUNT(*) FROM item_duplicates WHERE item_duplicates.item_id=feed_items.id)"
    )
    conn.commit()
    return {"pairs": pairs, "items": len(prepared)}


def source_kind_for_public(row: sqlite3.Row) -> str:
    kind = normalize_kind(row["source_kind"])
    channel = row["channel"]
    if "rss" in kind or "feed" in kind:
        return "rss"
    if "json" in kind or "arxiv" in kind:
        return "json_list"
    if "web" in kind or "trendradar" in kind:
        return "web_list"
    if "github" in kind:
        return "rss" if "release" in kind else "web_list"
    if channel == "product":
        return "json_list"
    if channel == "community":
        return "rss"
    return kind or channel


def accent_for_channel(channel: str) -> str:
    return {
        "firstParty": "accent-official",
        "news": "accent-news",
        "github": "accent-github",
        "product": "accent-product",
        "community": "accent-community",
    }.get(channel, "accent-news")


def daily_section_for_item(item: dict[str, Any]) -> str:
    text = " ".join([item.get("itemType") or "", item.get("titleZh") or "", " ".join(t.get("tag", "") if isinstance(t, dict) else str(t) for t in item.get("aiTags", []))]).lower()
    channel = item.get("channel")
    if "paper" in text or "论文" in text or "research" in text or "arxiv" in text:
        return "research_paper"
    if channel == "github" or "github" in text or "开源" in text:
        return "developer"
    if "model" in text or "模型" in text or "release" in text:
        return "model_release"
    if "product" in text or "产品" in text or "tool" in text or "工具" in text:
        return "product_tool"
    if channel == "community":
        return "community"
    return "industry"


def row_to_public_item(row: sqlite3.Row) -> dict[str, Any]:
    tags = json_loads(row["ai_tags_json"], [])
    tag_objects = [{"tag": str(tag.get("tag") if isinstance(tag, dict) else tag)} for tag in tags]
    source_kind = source_kind_for_public(row)
    published_at = row["published_at"]
    source_name = row["source_name"] or "Source"
    raw_json = json_loads(row["raw_json"], {})
    return {
        "id": row["id"],
        "title": row["title"],
        "titleZh": row["title_zh"],
        "summary": row["summary"],
        "summaryZh": row["summary_zh"],
        "url": row["url"],
        "link": row["url"],
        "source": row["source_name"],
        "sourceName": row["source_name"],
        "source_kind": row["source_kind"],
        "sourceKind": row["source_kind"],
        "source": {
            "id": stable_uid(source_name, source_kind)[:24],
            "name": source_name,
            "kind": source_kind,
        },
        "channel": row["channel"],
        "publishedAt": published_at,
        "observedAt": row["observed_at"],
        "dateKey": date_key(published_at),
        "dateLabel": date_label(published_at),
        "timeLabel": time_label(published_at),
        "accentClass": accent_for_channel(row["channel"]),
        "itemType": row["item_type"],
        "importance": row["importance"],
        "qualityScore": row["quality_score"],
        "finalScore": row["final_score"],
        "aiSelected": bool(row["ai_selected"]),
        "aiSelectedReason": row["ai_selected_reason"],
        "aiTags": tag_objects,
        "duplicateCount": row["duplicate_count"],
        "duplicateSources": [],
        "qualityAxesJson": json_loads(row["quality_axes_json"], {}),
        "editorialJudgment": row["editorial_judgment"],
        "rawJson": raw_json,
        "sourceOrigin": row["source_origin"] if "source_origin" in row.keys() else "dynamic_collector",
        "provenance": json_loads(row["provenance_json"], {}) if "provenance_json" in row.keys() else {},
        "userState": None,
        "userFeedback": None,
        "teamFeedback": [],
    }


def decorate_public_item(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    duplicate_rows = conn.execute(
        "SELECT f.id, f.title_zh, f.url, f.source_name, f.source_kind, d.score FROM item_duplicates d "
        "JOIN feed_items f ON f.id=d.duplicate_item_id WHERE d.item_id=? ORDER BY d.score DESC LIMIT 8",
        (item["id"],),
    ).fetchall()
    item["duplicateSources"] = [
        {
            "id": row["id"],
            "titleZh": row["title_zh"],
            "url": row["url"],
            "source": {"name": row["source_name"], "kind": row["source_kind"]},
            "score": row["score"],
        }
        for row in duplicate_rows
    ]
    item["duplicateCount"] = len(duplicate_rows)
    feedback_rows = conn.execute(
        "SELECT vote, reason, created_at FROM strategy_feedback WHERE item_id=? ORDER BY id DESC LIMIT 10",
        (item["id"],),
    ).fetchall()
    item["teamFeedback"] = [
        {
            "action": "approve" if row["vote"] in {"useful", "approve"} else "reject" if row["vote"] in {"wrong", "reject"} else row["vote"],
            "reason": row["reason"],
            "createdAt": row["created_at"],
            "userDisplayName": "Admin",
        }
        for row in feedback_rows
    ]
    return item


def mp_row_to_public_item(row: sqlite3.Row) -> dict[str, Any]:
    raw = json_loads(row["raw_json"], {})
    tags = json_loads(row["tags_json"], [])
    published_at = row["published_at"] or row["created_at"]
    return {
        "id": f"mp-{row['id']}",
        "title": row["title"],
        "titleZh": row["title"],
        "summary": row["summary"],
        "summaryZh": row["summary"],
        "url": row["url"],
        "link": row["url"],
        "source": {"id": stable_uid(row["account_name"], "mp")[:24], "name": row["account_name"], "kind": "mp_dynamic"},
        "sourceName": row["account_name"],
        "source_kind": "mp_dynamic",
        "sourceKind": "mp_dynamic",
        "channel": "mp",
        "publishedAt": published_at,
        "observedAt": row["updated_at"],
        "dateKey": date_key(published_at),
        "dateLabel": date_label(published_at),
        "timeLabel": time_label(published_at),
        "accentClass": "accent-community",
        "itemType": "mp_article",
        "importance": row["ai_relevance_score"],
        "qualityScore": row["heat_score"],
        "finalScore": row["heat_score"],
        "aiSelected": row["heat_score"] >= 70,
        "aiSelectedReason": "公众号动态源命中 AI/一人公司相关主题",
        "aiTags": [{"tag": str(tag)} for tag in tags[:8]],
        "duplicateCount": 0,
        "duplicateSources": [],
        "qualityAxesJson": quality_axes("community", float(row["heat_score"] or 0) / 8, row["heat_score"] >= 70),
        "editorialJudgment": "来自公众号动态采集源，按 AI 相关度、热度和时效进入榜单。",
        "rawJson": raw,
        "sourceOrigin": row["source_origin"],
        "provenance": json_loads(row["provenance_json"], {}),
        "userState": None,
        "userFeedback": None,
        "teamFeedback": [],
    }


def channel_items_public_feed(
    conn: sqlite3.Connection,
    params: dict[str, list[str]],
    *,
    view_channel: str,
    source_channel: str = "",
    mode: str = "all",
    public_channel: str = "all",
) -> dict[str, Any] | None:
    try:
        exists = conn.execute("SELECT COUNT(*) AS c FROM channel_items WHERE channel=?", (view_channel,)).fetchone()["c"]
    except Exception:
        return None
    if not exists:
        return None
    q = compact_text((params.get("q", [""])[0] or "")).lower()
    tag = compact_text((params.get("tag", [""])[0] or "")).lower()
    limit = min(max(int((params.get("limit", ["24"])[0] or "24")), 1), 80)
    cursor_at = compact_text(params.get("cursorAt", [""])[0])
    cursor_id_raw = compact_text(params.get("cursorId", [""])[0])
    cursor_id = int(cursor_id_raw or 0) if cursor_id_raw.isdigit() else 0
    where = ["channel=?"]
    args: list[Any] = [view_channel]
    if source_channel:
        where.append("source_channel=?")
        args.append(source_channel)
    if q:
        where.append("(lower(title) LIKE ? OR lower(source_name) LIKE ? OR lower(payload_json) LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if tag:
        where.append("lower(payload_json) LIKE ?")
        args.append(f"%{tag}%")
    if cursor_at and cursor_id:
        try:
            cursor_dt = datetime.fromtimestamp(int(cursor_at) / 1000, tz=timezone.utc).isoformat() if cursor_at.isdigit() else parse_item_time(cursor_at)
            where.append("(published_at < ? OR (published_at = ? AND id < ?))")
            args.extend([cursor_dt, cursor_dt, cursor_id])
        except Exception:
            pass
    where_sql = " AND ".join(where)
    rows = conn.execute(
        "SELECT * FROM channel_items WHERE " + where_sql + " ORDER BY published_at DESC, score DESC, id DESC LIMIT ?",
        [*args, limit + 1],
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in rows:
        payload = json_loads(row["payload_json"], {})
        if isinstance(payload, dict):
            items.append(payload)
    next_cursor = None
    if has_more and rows:
        next_cursor = {"at": epoch_ms(rows[-1]["published_at"]), "id": str(rows[-1]["id"])}
    filtered_count = conn.execute("SELECT COUNT(*) AS c FROM channel_items WHERE " + where_sql, args).fetchone()["c"]
    return {
        "items": items,
        "hasNext": has_more,
        "hasMore": has_more,
        "nextCursor": next_cursor,
        "generatedAt": now_iso(),
        "mode": mode,
        "channel": public_channel,
        "channelRule": feed_channel_rule(mode, public_channel),
        "filteredCount": filtered_count,
        "selectedCount": channel_item_count(conn, "selected", "SELECT COUNT(*) AS c FROM feed_items WHERE ai_selected=1"),
        "q": q,
        "tag": tag,
        "view": "independent_channel_items",
    }


def opc_solo_feed(conn: sqlite3.Connection, params: dict[str, list[str]]) -> dict[str, Any]:
    view = channel_items_public_feed(conn, params, view_channel="opcSolo", mode="all", public_channel="opcSolo")
    if view is not None:
        view["logic"] = {
            "sourceScope": "independent channel_items from all non-X feed_items + mp_articles",
            "threshold": OPC_SOLO_THRESHOLD,
            "terms": list(OPC_SOLO_TERMS.keys()),
        }
        return view
    q = compact_text((params.get("q", [""])[0] or "")).lower()
    limit = min(max(int((params.get("limit", ["30"])[0] or "30")), 1), 80)
    feed_rows = conn.execute("SELECT * FROM feed_items WHERE channel!='x' ORDER BY published_at DESC LIMIT 240").fetchall()
    items: list[dict[str, Any]] = []
    for row in feed_rows:
        item = decorate_public_item(conn, row_to_public_item(row))
        if is_opc_solo_item(item):
            items.append(item)
    mp_rows = conn.execute("SELECT * FROM mp_articles ORDER BY heat_score DESC, published_at DESC LIMIT 120").fetchall()
    for row in mp_rows:
        item = mp_row_to_public_item(row)
        if is_opc_solo_item(item):
            items.append(item)
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in items:
        dedupe_key = compact_text(item.get("url"), limit=1200) or stable_uid(
            compact_text(item.get("titleZh") or item.get("title"), limit=300).lower(),
            compact_text(item.get("sourceName"), limit=160).lower(),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(item)
    items = deduped
    if q:
        items = [item for item in items if q in compact_text(item.get("titleZh")).lower() or q in compact_text(item.get("summaryZh")).lower() or q in compact_text(item.get("sourceName")).lower()]
    items.sort(
        key=lambda item: (
            float(item.get("opcSoloScore") or 0),
            float(item.get("finalScore") or 0),
            parse_iso_datetime(item.get("publishedAt")),
        ),
        reverse=True,
    )
    return {
        "items": items[:limit],
        "hasNext": len(items) > limit,
        "hasMore": len(items) > limit,
        "nextCursor": None,
        "generatedAt": now_iso(),
        "mode": "all",
        "channel": "opcSolo",
        "q": q,
        "tag": "",
        "logic": {
            "sourceScope": "all non-X feed_items + dynamic mp_articles",
            "threshold": OPC_SOLO_THRESHOLD,
            "terms": list(OPC_SOLO_TERMS.keys()),
        },
    }


def public_feed(conn: sqlite3.Connection, params: dict[str, list[str]]) -> dict[str, Any]:
    mode = (params.get("mode", ["selected"])[0] or "selected").strip()
    channel = (params.get("channel", ["all"])[0] or "all").strip()
    if channel == "opcSolo":
        return opc_solo_feed(conn, params)
    view_channel = "selected" if mode == "selected" else "all"
    source_filter = "" if channel in {"", "all"} else channel
    view = channel_items_public_feed(
        conn,
        params,
        view_channel=view_channel,
        source_channel=source_filter,
        mode=mode,
        public_channel=channel,
    )
    if view is not None:
        return view
    q = compact_text((params.get("q", [""])[0] or "")).lower()
    tag = compact_text((params.get("tag", [""])[0] or "")).lower()
    limit = min(max(int((params.get("limit", ["24"])[0] or "24")), 1), 80)
    cursor_at = compact_text(params.get("cursorAt", [""])[0])
    cursor_id_raw = compact_text(params.get("cursorId", [""])[0])
    cursor_id = int(cursor_id_raw or 0) if cursor_id_raw.isdigit() else 0
    where = ["1=1"]
    args: list[Any] = []
    if mode == "selected":
        where.append("ai_selected=1")
    if channel and channel != "all":
        clause, clause_args = channel_filter_clause(channel)
        if clause:
            where.append(clause)
            args.extend(clause_args)
    if q:
        where.append("(lower(title) LIKE ? OR lower(summary) LIKE ? OR lower(source_name) LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if tag:
        where.append("lower(ai_tags_json) LIKE ?")
        args.append(f"%{tag}%")
    if cursor_at and cursor_id:
        try:
            cursor_dt = datetime.fromtimestamp(int(cursor_at) / 1000, tz=timezone.utc).isoformat() if cursor_at.isdigit() else parse_item_time(cursor_at)
            where.append("(published_at < ? OR (published_at = ? AND id < ?))")
            args.extend([cursor_dt, cursor_dt, cursor_id])
        except Exception:
            pass
    sql = "SELECT * FROM feed_items WHERE " + " AND ".join(where) + " ORDER BY published_at DESC, final_score DESC, id DESC LIMIT ?"
    rows = conn.execute(sql, [*args, limit + 1]).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        next_cursor = {"at": epoch_ms(rows[-1]["published_at"]), "id": str(rows[-1]["id"])}
    latest = conn.execute("SELECT MAX(updated_at) AS ts FROM feed_items").fetchone()["ts"]
    filtered_count = conn.execute("SELECT COUNT(*) AS c FROM feed_items WHERE " + " AND ".join(where), args).fetchone()["c"]
    return {
        "items": [decorate_public_item(conn, row_to_public_item(row)) for row in rows],
        "hasNext": has_more,
        "hasMore": has_more,
        "nextCursor": next_cursor,
        "generatedAt": latest or now_iso(),
        "mode": mode,
        "channel": channel,
        "channelRule": feed_channel_rule(mode, channel),
        "filteredCount": filtered_count,
        "selectedCount": conn.execute("SELECT COUNT(*) AS c FROM feed_items WHERE ai_selected=1").fetchone()["c"],
        "q": q,
        "tag": tag,
    }


def source_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    sources = [dict(row) for row in conn.execute("SELECT * FROM sources ORDER BY channel, name").fetchall()]
    by_status: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    for source in sources:
        by_status[source.get("last_status") or "unknown"] = by_status.get(source.get("last_status") or "unknown", 0) + 1
        by_channel[source.get("channel") or "unknown"] = by_channel.get(source.get("channel") or "unknown", 0) + 1
    for source in sources:
        source["config"] = json_loads(source.pop("config_json", "{}"), {})
    return {"sources": sources, "summary": {"total": len(sources), "byStatus": by_status, "byChannel": by_channel}}


def safe_scalar(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = (), default: Any = 0) -> Any:
    try:
        row = conn.execute(sql, args).fetchone()
        if row is None:
            return default
        return row[0]
    except Exception:
        return default


def classify_runtime_error(value: Any) -> str:
    text = compact_text(value, limit=1200).lower()
    if not text:
        return "unknown"
    if "insufficient balance" in text or "402" in text or "balance" in text:
        return "billing"
    if "empty content" in text:
        return "empty_content"
    if "json" in text or "expecting value" in text:
        return "json_parse"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "rate limit" in text or "429" in text:
        return "rate_limit"
    return "other"


def latest_model_error_digest(conn: sqlite3.Connection) -> dict[str, Any]:
    window_hours = clamp_int(os.getenv("DEEPSEEK_STATUS_WINDOW_HOURS", "6"), 1, 168, 6)
    window_cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT 'item' AS scope, error, updated_at
                FROM item_enrichments
                WHERE status='error' AND error IS NOT NULL
                  AND updated_at>=?
                UNION ALL
                SELECT 'mp' AS scope, error, updated_at
                FROM mp_enrichments
                WHERE status='error' AND error IS NOT NULL
                  AND updated_at>=?
                ORDER BY updated_at DESC
                LIMIT 120
                """,
                (window_cutoff, window_cutoff),
            ).fetchall()
        ]
    except Exception:
        rows = []
    by_kind: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    for row in rows:
        kind = classify_runtime_error(row.get("error"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if len(samples) < 5:
            samples.append({
                "scope": row.get("scope"),
                "kind": kind,
                "updatedAt": row.get("updated_at"),
                "error": compact_text(row.get("error"), limit=220),
            })
    latest_ok_at = max(
        [
            compact_text(safe_scalar(conn, "SELECT MAX(updated_at) FROM item_enrichments WHERE status='ok'", default="")),
            compact_text(safe_scalar(conn, "SELECT MAX(updated_at) FROM mp_enrichments WHERE status='ok'", default="")),
        ]
    )
    latest_error_at = max(
        [
            compact_text(safe_scalar(conn, "SELECT MAX(updated_at) FROM item_enrichments WHERE status='error'", default="")),
            compact_text(safe_scalar(conn, "SELECT MAX(updated_at) FROM mp_enrichments WHERE status='error'", default="")),
        ]
    )
    return {
        "windowHours": window_hours,
        "recentErrorCount": len(rows),
        "byKind": by_kind,
        "latestOkAt": latest_ok_at or None,
        "latestErrorAt": latest_error_at or None,
        "samples": samples,
    }


def latest_wechat_session_issue(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_name, source_uid, source_kind, detail, checked_at
                FROM source_health
                WHERE channel='mp'
                  AND (source_kind LIKE 'mp_wechat%' OR source_kind='mp_wechat_api')
                ORDER BY id DESC
                LIMIT 120
                """
            ).fetchall()
        ]
    except Exception:
        rows = []
    latest_rows: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for row in rows:
        source_key = compact_text(row.get("source_uid"), limit=160) or compact_text(row.get("source_name"), limit=160)
        if not source_key:
            source_key = compact_text(row.get("source_kind"), limit=80)
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        latest_rows.append(row)
    invalid_rows: list[dict[str, Any]] = []
    for row in latest_rows:
        detail = compact_text(row.get("detail"), limit=1400).lower()
        if "invalid session" in detail or 'ret":200003' in detail or "ret=200003" in detail:
            invalid_rows.append(row)
    if not invalid_rows:
        return {
            "status": "ok",
            "affectedSources": 0,
            "checkedAt": latest_rows[0].get("checked_at") if latest_rows else None,
            "samples": [],
        }
    names: list[str] = []
    seen: set[str] = set()
    for row in invalid_rows:
        name = compact_text(row.get("source_name"), limit=80) or compact_text(row.get("source_uid"), limit=80)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return {
        "status": "invalid_session",
        "affectedSources": len(seen),
        "checkedAt": invalid_rows[0].get("checked_at"),
        "samples": names[:8],
        "detail": "公众号授权会话已失效，动态采集返回 invalid session，需要重新授权后再采集。",
    }


def channel_item_metrics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT channel, COUNT(*) AS itemCount, AVG(score) AS avgScore, MAX(score) AS maxScore,
               MAX(published_at) AS newestAt, MIN(published_at) AS oldestAt
        FROM channel_items
        GROUP BY channel
        ORDER BY CASE channel
            WHEN 'selected' THEN 1 WHEN 'all' THEN 2 WHEN 'daily' THEN 3
            WHEN 'mp' THEN 4 WHEN 'opcSolo' THEN 5 ELSE 9 END
        """
    ).fetchall()
    candidate_rows = conn.execute(
        "SELECT channel, COUNT(*) AS candidates, SUM(selected) AS selectedCount FROM channel_candidates GROUP BY channel"
    ).fetchall()
    candidate_map = {
        row["channel"]: {"candidates": int(row["candidates"] or 0), "selected": int(row["selectedCount"] or 0)}
        for row in candidate_rows
    }
    source_rows = conn.execute(
        """
        SELECT channel, source_name, COUNT(*) AS c, AVG(score) AS avgScore
        FROM channel_items
        GROUP BY channel, source_name
        ORDER BY channel, c DESC, avgScore DESC
        """
    ).fetchall()
    source_map: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        bucket = source_map.setdefault(row["channel"], [])
        if len(bucket) < 5:
            bucket.append({
                "name": row["source_name"] or "Unknown",
                "count": int(row["c"] or 0),
                "avgScore": round(float(row["avgScore"] or 0), 2),
            })
    result = []
    for row in rows:
        channel = row["channel"]
        cand = candidate_map.get(channel, {"candidates": 0, "selected": 0})
        result.append({
            "channel": channel,
            "name": public_channel_rule(channel).get("name") or channel,
            "itemCount": int(row["itemCount"] or 0),
            "candidateCount": cand["candidates"],
            "selectedCandidateCount": cand["selected"],
            "avgScore": round(float(row["avgScore"] or 0), 2),
            "maxScore": round(float(row["maxScore"] or 0), 2),
            "newestAt": row["newestAt"],
            "oldestAt": row["oldestAt"],
            "topSources": source_map.get(channel, []),
        })
    return result


def source_health_digest(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = [dict(row) for row in conn.execute("SELECT * FROM source_health ORDER BY id DESC LIMIT 600").fetchall()]
    latest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = row.get("source_uid") or row.get("source_name") or str(row.get("id"))
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    by_status: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    total_items = 0
    slowest = sorted(latest, key=lambda item: int(item.get("elapsed_ms") or 0), reverse=True)[:8]
    for row in latest:
        status = compact_text(row.get("status"), limit=60) or "unknown"
        channel = compact_text(row.get("channel"), limit=60) or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        by_channel[channel] = by_channel.get(channel, 0) + 1
        total_items += int(row.get("item_count") or 0)
    error_kinds: dict[str, int] = {}
    for row in latest:
        if row.get("status") in {"ok", "configured"}:
            continue
        detail = compact_text(row.get("detail"), limit=1000).lower()
        if "invalid session" in detail or 'ret":200003' in detail or "ret=200003" in detail:
            kind = "wechat_invalid_session"
        elif "timeout" in detail or "timed out" in detail:
            kind = "timeout"
        elif "http" in detail:
            kind = "http_error"
        else:
            kind = "other"
        error_kinds[kind] = error_kinds.get(kind, 0) + 1
    return {
        "latestTotal": len(latest),
        "historyRows": len(rows),
        "byStatus": by_status,
        "byChannel": by_channel,
        "byErrorKind": error_kinds,
        "itemCount": total_items,
        "lastCheckedAt": latest[0]["checked_at"] if latest else None,
        "wechatSessionIssue": latest_wechat_session_issue(conn),
        "slowest": [
            {
                "sourceName": row.get("source_name"),
                "channel": row.get("channel"),
                "status": row.get("status"),
                "elapsedMs": int(row.get("elapsed_ms") or 0),
                "itemCount": int(row.get("item_count") or 0),
            }
            for row in slowest
        ],
        "attention": [
            {
                "sourceName": row.get("source_name"),
                "channel": row.get("channel"),
                "status": row.get("status"),
                "detail": row.get("detail"),
                "checkedAt": row.get("checked_at"),
            }
            for row in latest
            if row.get("status") not in {"ok", "configured"}
        ][:12],
    }


def model_runtime_status(conn: sqlite3.Connection) -> dict[str, Any]:
    item_counts = {
        row["status"]: int(row["c"] or 0)
        for row in conn.execute("SELECT status, COUNT(*) AS c FROM item_enrichments GROUP BY status").fetchall()
    }
    mp_counts = {
        row["status"]: int(row["c"] or 0)
        for row in conn.execute("SELECT status, COUNT(*) AS c FROM mp_enrichments GROUP BY status").fetchall()
    }
    error_digest = latest_model_error_digest(conn)
    latest_error = error_digest["samples"][0]["error"] if error_digest.get("samples") else ""
    latest_ok_at = compact_text(error_digest.get("latestOkAt"))
    latest_error_at = compact_text(error_digest.get("latestErrorAt"))
    recent_errors = int(error_digest.get("recentErrorCount") or 0)
    latest_error_after_ok = bool(latest_error_at and (not latest_ok_at or latest_error_at > latest_ok_at))
    balance_issue = bool(error_digest.get("byKind", {}).get("billing")) and latest_error_after_ok
    ok_total = item_counts.get("ok", 0) + mp_counts.get("ok", 0)
    if not deepseek_available():
        status = "not_configured"
        label = "未配置"
    elif balance_issue:
        status = "billing_attention"
        label = "余额不足"
    elif ok_total > 0 and recent_errors and latest_error_after_ok:
        status = "degraded"
        label = "部分异常"
    elif ok_total > 0:
        status = "active"
        label = "已接入"
    else:
        status = "ready"
        label = "待运行"
    return {
        "available": deepseek_available(),
        "status": status,
        "label": label,
        "model": DEEPSEEK_MODEL,
        "thinking": DEEPSEEK_THINKING,
        "reasoningEffort": DEEPSEEK_REASONING_EFFORT,
        "promptVersion": ENRICH_PROMPT_VERSION,
        "itemEnrichments": item_counts,
        "mpEnrichments": mp_counts,
        "latestError": compact_text(latest_error, limit=500),
        "latestOkAt": latest_ok_at or None,
        "latestErrorAt": latest_error_at or None,
        "errorDigest": error_digest,
    }


def data_quality_digest(conn: sqlite3.Connection) -> dict[str, Any]:
    newest_item = safe_scalar(conn, "SELECT MAX(published_at) FROM feed_items", default="")
    newest_mp = safe_scalar(conn, "SELECT MAX(published_at) FROM mp_articles", default="")
    missing_summary = int(safe_scalar(conn, "SELECT COUNT(*) FROM feed_items WHERE summary_zh IS NULL OR length(summary_zh)<8", default=0))
    missing_url = int(safe_scalar(conn, "SELECT COUNT(*) FROM feed_items WHERE url IS NULL OR length(url)<8", default=0))
    low_score_selected = int(safe_scalar(conn, "SELECT COUNT(*) FROM channel_items WHERE channel='selected' AND score<60", default=0))
    duplicate_pairs = int(safe_scalar(conn, "SELECT COUNT(*) FROM item_duplicates", default=0))
    return {
        "newestItemAt": newest_item,
        "newestMpAt": newest_mp,
        "missingSummary": missing_summary,
        "missingUrl": missing_url,
        "lowScoreSelected": low_score_selected,
        "duplicatePairs": duplicate_pairs,
    }


def operations_recommendations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    model = model_runtime_status(conn)
    health = source_health_digest(conn)
    quality = data_quality_digest(conn)
    mp_sources = combined_mp_source_summary(conn)["summary"]
    recs: list[dict[str, Any]] = []
    if model["status"] == "billing_attention":
        recs.append({"level": "warn", "title": "DeepSeek 余额不足", "detail": "模型评估链路已接入，但当前返回 402 Insufficient Balance；充值后可继续运行公众号和全量 AI 处理。"})
    elif model["status"] == "degraded":
        digest = model.get("errorDigest", {}) if isinstance(model.get("errorDigest"), dict) else {}
        recs.append({"level": "warn", "title": "DeepSeek 结果不稳定", "detail": f"模型已接入并产生有效结果，但最近仍有 {int(digest.get('recentErrorCount') or 0)} 条异常，重点关注空响应、JSON 解析和限流错误。"})
    if mp_sources.get("wechatSessionStatus") == "invalid_session":
        issue = mp_sources.get("wechatSessionIssue", {}) if isinstance(mp_sources.get("wechatSessionIssue"), dict) else {}
        recs.append({"level": "warn", "title": "公众号授权会话失效", "detail": f"最近 {int(issue.get('affectedSources') or 0)} 个公众号动态采集返回 invalid session，需要重新授权后再运行公众号采集。"})
    if int(mp_sources.get("wechatReady") or 0) and not safe_scalar(conn, "SELECT COUNT(*) FROM channel_items WHERE channel='mp'", default=0):
        recs.append({"level": "warn", "title": "公众号源已就绪但栏目为空", "detail": "运行公众号源同步后再重建频道视图。"})
    if health["attention"]:
        recs.append({"level": "warn", "title": "存在异常信源", "detail": f"最近信源健康记录中有 {len(health['attention'])} 个需要关注，可在后台健康页查看。"})
    if quality["missingSummary"]:
        recs.append({"level": "info", "title": "摘要完整度可提升", "detail": f"仍有 {quality['missingSummary']} 条动态摘要较短，后续可用模型补写摘要。"})
    if not recs:
        recs.append({"level": "good", "title": "核心链路正常", "detail": "公开栏目、公众号源池、日报和后台运营接口均有可用数据。"})
    return recs[:8]


def module_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    source_data = source_summary(conn)
    mp_count = channel_item_count(conn, "mp", "SELECT COUNT(*) AS c FROM mp_articles")
    mp_sources = combined_mp_source_summary(conn)["summary"]
    if mp_sources.get("wechatSessionStatus") == "invalid_session":
        mp_status = "auth_expired"
    elif mp_count:
        mp_status = "active"
    elif mp_sources.get("ready"):
        mp_status = "ready_for_collect"
    elif mp_sources.get("configured") and mp_sources.get("wechatAuthStatus") not in {"authorized", "", "idle"}:
        mp_status = "auth_required"
    else:
        mp_status = "waiting_for_sources"
    return {
        "modules": [
            {"code": "feed", "name": "全部 AI 动态", "status": "active", "count": channel_item_count(conn, "all", "SELECT COUNT(*) AS c FROM feed_items")},
            {"code": "selected", "name": "精选", "status": "active", "count": channel_item_count(conn, "selected", "SELECT COUNT(*) AS c FROM feed_items WHERE ai_selected=1")},
            {"code": "daily", "name": "AI 日报", "status": "active", "count": conn.execute("SELECT COUNT(*) AS c FROM daily_issues").fetchone()["c"]},
            {"code": "mp", "name": "公众号爆文", "status": mp_status, "count": mp_count},
            {"code": "opcSolo", "name": "OPC一人公司", "status": "active", "count": channel_item_count(conn, "opcSolo")},
            {"code": "sources", "name": "信源健康", "status": "active", "count": source_data["summary"]["total"]},
            {"code": "strategy", "name": "精选策略", "status": "active", "count": conn.execute("SELECT COUNT(*) AS c FROM strategy_rules WHERE enabled=1").fetchone()["c"]},
        ],
        "sourceSummary": source_data["summary"],
        "wechatSourceSummary": mp_sources,
        "channelMetrics": channel_item_metrics(conn),
        "sourceHealth": source_health_digest(conn),
        "modelStatus": model_runtime_status(conn),
        "quality": data_quality_digest(conn),
        "recommendations": operations_recommendations(conn),
        "channelRules": channel_rules(),
    }


def public_module_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    summary = module_summary(conn)
    public_modules = []
    for item in summary.get("modules", []):
        module = dict(item)
        if module.get("code") == "mp" and module.get("status") in {"auth_expired", "auth_required"}:
            module["status"] = "active" if int(module.get("count") or 0) else "waiting"
        public_modules.append(module)
    return {
        "modules": public_modules,
        "channelRules": channel_rules(),
        "generatedAt": now_iso(),
    }


def public_run_summary(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "run_type": data.get("run_type"),
        "status": data.get("status"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "item_count": data.get("item_count"),
        "selected_count": data.get("selected_count"),
        "source_count": data.get("source_count"),
    }


def public_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    channels = [dict(row) for row in conn.execute("SELECT channel, COUNT(*) AS count, SUM(ai_selected) AS selected FROM feed_items GROUP BY channel ORDER BY count DESC").fetchall()]
    latest_run = conn.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
    newest_item = conn.execute("SELECT MAX(published_at) AS newest FROM feed_items").fetchone()["newest"]
    return {
        "counts": admin_overview(conn)["counts"],
        "channels": channels,
        "latestRun": public_run_summary(latest_run),
        "newestItemAt": newest_item,
        "generatedAt": now_iso(),
    }


def evaluate_model_policy(conn: sqlite3.Connection, *, persist: bool = False) -> dict[str, Any]:
    totals = admin_overview(conn)["counts"]
    channels = [dict(row) for row in conn.execute("SELECT channel, COUNT(*) AS count, SUM(ai_selected) AS selected, AVG(final_score) AS avgScore FROM feed_items GROUP BY channel").fetchall()]
    low_quality_selected = conn.execute("SELECT COUNT(*) AS c FROM feed_items WHERE ai_selected=1 AND final_score < 60").fetchone()["c"]
    stale_selected = conn.execute("SELECT COUNT(*) AS c FROM feed_items WHERE ai_selected=1 AND published_at < datetime('now','-7 days')").fetchone()["c"]
    missing_summary = conn.execute("SELECT COUNT(*) AS c FROM feed_items WHERE summary_zh IS NULL OR length(summary_zh) < 8").fetchone()["c"]
    selected = int(totals.get("selected") or 0)
    items = int(totals.get("items") or 0)
    coverage = selected / items if items else 0
    quality_penalty = min(40, low_quality_selected * 8 + stale_selected * 6 + missing_summary * 1.5)
    coverage_penalty = 8 if coverage < 0.08 or coverage > 0.7 else 0
    score_value = round(max(0, min(100, 92 - quality_penalty - coverage_penalty)), 2)
    detail = {
        "items": items,
        "selected": selected,
        "coverage": round(coverage, 4),
        "channels": channels,
        "lowQualitySelected": low_quality_selected,
        "staleSelected": stale_selected,
        "missingSummary": missing_summary,
        "notes": [
            "当前为规则策略评估，覆盖精选阈值、摘要完整度、时效性和栏目覆盖。",
            "X 已按要求排除，不进入评估样本。",
        ],
    }
    result = {
        "modelName": "welopc-rule-policy-v1",
        "evalType": "selection_quality",
        "sampleCount": items,
        "score": score_value,
        "detail": detail,
        "createdAt": now_iso(),
    }
    if persist:
        conn.execute(
            "INSERT INTO model_evaluations(model_name,eval_type,sample_count,score,detail_json,created_at) VALUES(?,?,?,?,?,?)",
            (result["modelName"], result["evalType"], result["sampleCount"], result["score"], json_dumps(detail), result["createdAt"]),
        )
        conn.commit()
    return result


def daily_row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "issueDate": row["issue_date"],
        "title": row["title"],
        "summary": row["summary"],
        "content": json_loads(row["content_json"], {}),
        "markdown": row["markdown"],
        "status": row["status"],
        "generatedAt": row["generated_at"],
    }


def daily_latest(conn: sqlite3.Connection, *, issue_date: str = "") -> dict[str, Any]:
    row = None
    if issue_date:
        row = conn.execute("SELECT * FROM daily_issues WHERE issue_date=? LIMIT 1", (issue_date,)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM daily_issues ORDER BY issue_date DESC LIMIT 1").fetchone()
    if not row:
        return regenerate_daily(conn)
    return daily_row_to_public(row)


def daily_list(conn: sqlite3.Connection, params: dict[str, list[str]]) -> dict[str, Any]:
    limit = min(max(int((params.get("limit", ["30"])[0] or "30")), 1), 120)
    rows = conn.execute(
        "SELECT id, issue_date, title, summary, status, generated_at FROM daily_issues ORDER BY issue_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "issueDate": row["issue_date"],
                "title": row["title"],
                "summary": row["summary"],
                "status": row["status"],
                "generatedAt": row["generated_at"],
            }
            for row in rows
        ],
        "count": len(rows),
        "generatedAt": now_iso(),
    }


def mp_list(conn: sqlite3.Connection, params: dict[str, list[str]]) -> dict[str, Any]:
    limit = min(max(int((params.get("limit", ["40"])[0] or "40")), 1), 100)
    period = (params.get("period", ["all"])[0] or "all").strip()
    days_by_period = {"24h": 1, "7d": 7, "30d": 30, "1y": 365}
    source_summary_data = combined_mp_source_summary(conn)
    candidate_where = ["channel='mp'"]
    candidate_args: list[Any] = []
    if period in days_by_period:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_by_period[period])).isoformat()
        candidate_where.append("published_at>=?")
        candidate_args.append(cutoff)
    candidate_total = conn.execute("SELECT COUNT(*) AS c FROM channel_items WHERE " + " AND ".join(candidate_where), candidate_args).fetchone()["c"]
    if candidate_total:
        rows = conn.execute(
            "SELECT * FROM channel_items WHERE " + " AND ".join(candidate_where) + " ORDER BY score DESC, published_at DESC, id DESC LIMIT ?",
            [*candidate_args, limit],
        ).fetchall()
        items = []
        for row in rows:
            payload = json_loads(row["payload_json"], {})
            if not isinstance(payload, dict):
                continue
            raw = payload.get("rawJson") if isinstance(payload.get("rawJson"), dict) else {}
            items.append({
                "id": payload.get("id") or row["id"],
                "title": payload.get("titleZh") or payload.get("title"),
                "accountName": payload.get("accountName") or payload.get("sourceName"),
                "url": payload.get("url") or payload.get("link"),
                "publishedAt": payload.get("publishedAt"),
                "summary": payload.get("summaryZh") or payload.get("summary"),
                "heatScore": payload.get("channelScore") or payload.get("finalScore"),
                "anomalyScore": raw.get("anomalyScore") or raw.get("anomaly_score") or 0,
                "aiRelevanceScore": payload.get("importance") or payload.get("finalScore"),
                "tags": [tag.get("tag") if isinstance(tag, dict) else tag for tag in payload.get("aiTags", [])],
                "reads": raw.get("reads"),
                "likes": raw.get("likes"),
                "shares": raw.get("shares"),
                "original": bool(raw.get("original")),
                "sourceOrigin": payload.get("sourceOrigin"),
                "provenance": payload.get("provenance") or {},
            })
        latest = conn.execute("SELECT MAX(published_at) AS ts FROM channel_items WHERE channel='mp'").fetchone()["ts"]
        next_fetch = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        return {
            "items": items,
            "count": candidate_total,
            "module": "mp_articles",
            "sourceStatus": "active",
            "sourceSummary": source_summary_data,
            "period": period,
            "filters": [
                {"code": "24h", "label": "过去24h"},
                {"code": "7d", "label": "过去7天"},
                {"code": "30d", "label": "过去30天"},
                {"code": "1y", "label": "过去1年"},
                {"code": "all", "label": "全部"},
            ],
            "lastFetchAt": latest,
            "nextFetchAt": next_fetch,
            "view": "independent_channel_items",
        }
    where: list[str] = []
    args: list[Any] = []
    if period in days_by_period:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_by_period[period])).isoformat()
        where.append("published_at>=?")
        args.append(cutoff)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute("SELECT COUNT(*) AS c FROM mp_articles" + where_sql, args).fetchone()["c"]
    rows = conn.execute("SELECT * FROM mp_articles" + where_sql + " ORDER BY heat_score DESC, published_at DESC, id DESC LIMIT ?", [*args, limit]).fetchall()
    items = []
    for row in rows:
        raw = json_loads(row["raw_json"], {})
        items.append({
            "id": row["id"],
            "title": row["title"],
            "accountName": row["account_name"],
            "url": row["url"],
            "publishedAt": row["published_at"],
            "summary": row["summary"],
            "heatScore": row["heat_score"],
            "anomalyScore": row["anomaly_score"],
            "aiRelevanceScore": row["ai_relevance_score"],
            "tags": json_loads(row["tags_json"], []),
            "reads": raw.get("reads"),
            "likes": raw.get("likes"),
            "shares": raw.get("shares"),
            "original": bool(raw.get("original")),
            "sourceOrigin": row["source_origin"] if "source_origin" in row.keys() else "manual_import",
            "provenance": json_loads(row["provenance_json"], {}) if "provenance_json" in row.keys() else {},
        })
    latest = conn.execute("SELECT MAX(updated_at) AS ts FROM mp_articles").fetchone()["ts"]
    next_fetch = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    summary = source_summary_data.get("summary", {}) if isinstance(source_summary_data.get("summary"), dict) else {}
    ready_sources = int(summary.get("ready") or 0)
    configured_sources = int(summary.get("configured") or 0)
    auth_status = compact_text(summary.get("wechatAuthStatus"), limit=40)
    if items:
        source_status = "active"
    elif ready_sources:
        source_status = "ready_for_collect"
    elif configured_sources and auth_status not in {"authorized", "", "idle"}:
        source_status = "auth_required"
    elif configured_sources:
        source_status = "waiting_for_collect"
    else:
        source_status = "waiting_for_sources"
    return {
        "items": items,
        "count": total,
        "module": "mp_articles",
        "sourceStatus": source_status,
        "sourceSummary": source_summary_data,
        "period": period,
        "filters": [
            {"code": "24h", "label": "过去24h"},
            {"code": "7d", "label": "过去7天"},
            {"code": "30d", "label": "过去30天"},
            {"code": "1y", "label": "过去1年"},
            {"code": "all", "label": "全部"},
        ],
        "lastFetchAt": latest,
        "nextFetchAt": next_fetch,
    }


def admin_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = {}
    for key, sql in {
        "items": "SELECT COUNT(*) AS c FROM feed_items",
        "selected": "SELECT COUNT(*) AS c FROM feed_items WHERE ai_selected=1",
        "sources": "SELECT COUNT(*) AS c FROM sources",
        "wechatSources": "SELECT COUNT(*) AS c FROM wechat_sources WHERE enabled=1",
        "wechatRawArticles": "SELECT COUNT(*) AS c FROM wechat_source_articles",
        "mpArticles": "SELECT COUNT(*) AS c FROM mp_articles",
        "channelItems": "SELECT COUNT(*) AS c FROM channel_items",
        "dailyIssues": "SELECT COUNT(*) AS c FROM daily_issues",
        "pipelineRuns": "SELECT COUNT(*) AS c FROM pipeline_runs",
    }.items():
        counts[key] = conn.execute(sql).fetchone()["c"]
    latest_run = conn.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
    channels = [dict(row) for row in conn.execute("SELECT channel, COUNT(*) AS count FROM feed_items GROUP BY channel ORDER BY count DESC").fetchall()]
    return {
        "counts": counts,
        "latestRun": dict(latest_run) if latest_run else None,
        "channels": channels,
        "channelMetrics": channel_item_metrics(conn),
        "sourceHealth": source_health_digest(conn),
        "modelStatus": model_runtime_status(conn),
        "quality": data_quality_digest(conn),
        "recommendations": operations_recommendations(conn),
        "modules": module_summary(conn)["modules"],
        "generatedAt": now_iso(),
    }


def make_token(conn: sqlite3.Connection, username: str, role: str) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = b64url(json_dumps(payload).encode("utf-8"))
    sig = hmac.new(ensure_secret(conn).encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{b64url(sig)}"


def verify_token(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(ensure_secret(conn).encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(unb64url(sig), expected):
            return None
        payload = json.loads(unb64url(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        row = conn.execute("SELECT username, role, active FROM users WHERE username=?", (payload.get("sub"),)).fetchone()
        if not row or not row["active"]:
            return None
        return {"username": row["username"], "role": row["role"]}
    except Exception:
        return None


def audit(conn: sqlite3.Connection, actor: str, action: str, target_type: str = "", target_id: str = "", detail: Any = None) -> None:
    conn.execute(
        "INSERT INTO audit_logs(actor,action,target_type,target_id,detail_json,created_at) VALUES(?,?,?,?,?,?)",
        (actor, action, target_type, str(target_id or ""), json_dumps(detail or {}), now_iso()),
    )
    conn.commit()


def record_access(conn: sqlite3.Connection, path: str, params: dict[str, list[str]], user_agent: str, remote_addr: str) -> None:
    conn.execute(
        "INSERT INTO access_events(path,query_json,user_agent,remote_addr,created_at) VALUES(?,?,?,?,?)",
        (path, json_dumps({k: v for k, v in params.items()}), user_agent[:500], remote_addr, now_iso()),
    )
    conn.commit()


class AihotHandler(BaseHTTPRequestHandler):
    server_version = "WelOPC-AIHOT/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("AIHOT_HTTP_LOG", "0") == "1":
            super().log_message(fmt, *args)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(min(length, 2_000_000)).decode("utf-8"))

    def route_path(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urlparse(self.path)
        path = parsed.path
        for prefix in ("/ai-hot/api", "/api"):
            if path.startswith(prefix):
                path = path[len(prefix):] or "/"
        return path, parse_qs(parsed.query)

    def current_actor(self, conn: sqlite3.Connection) -> dict[str, Any] | None:
        header = self.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return verify_token(conn, header.split(" ", 1)[1].strip())
        return None

    def require_actor(self, conn: sqlite3.Connection) -> dict[str, Any] | None:
        actor = self.current_actor(conn)
        if not actor:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return None
        return actor

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        path, params = self.route_path()
        try:
            with get_db() as conn:
                init_db(conn)
                if path == "/health":
                    self.send_json(200, {"status": "ok", "service": SERVICE_NAME, "time": now_iso()})
                elif path == "/public/feed":
                    record_access(conn, path, params, self.headers.get("User-Agent", ""), self.client_address[0])
                    self.send_json(200, public_feed(conn, params))
                elif path == "/public/daily/latest":
                    record_access(conn, path, params, self.headers.get("User-Agent", ""), self.client_address[0])
                    self.send_json(200, daily_latest(conn, issue_date=compact_text(params.get("date", [""])[0])))
                elif path == "/public/daily/list":
                    record_access(conn, path, params, self.headers.get("User-Agent", ""), self.client_address[0])
                    self.send_json(200, daily_list(conn, params))
                elif path == "/public/mp":
                    record_access(conn, path, params, self.headers.get("User-Agent", ""), self.client_address[0])
                    self.send_json(200, mp_list(conn, params))
                elif path == "/public/sources":
                    self.send_json(200, source_summary(conn))
                elif path == "/public/rules":
                    self.send_json(200, {"items": channel_rules(), "generatedAt": now_iso()})
                elif path == "/public/modules":
                    self.send_json(200, public_module_summary(conn))
                elif path == "/public/stats":
                    self.send_json(200, public_stats(conn))
                else:
                    actor = self.require_actor(conn)
                    if not actor:
                        return
                    if path == "/admin/me":
                        self.send_json(200, {"user": actor})
                    elif path == "/admin/overview":
                        self.send_json(200, admin_overview(conn))
                    elif path == "/admin/sources":
                        self.send_json(200, source_summary(conn))
                    elif path == "/admin/items":
                        self.send_json(200, public_feed(conn, {**params, "mode": [params.get("mode", ["all"])[0] or "all"]}))
                    elif path == "/admin/daily":
                        self.send_json(200, daily_latest(conn))
                    elif path == "/admin/mp/sources":
                        self.send_json(200, mp_source_summary(conn, include_private=True))
                    elif path == "/admin/mp/wechat-auth":
                        self.send_json(200, sanitize_wechat_auth_state(wechat_auth_state(conn)))
                    elif path == "/admin/mp/source-registry":
                        self.send_json(200, wechat_source_registry(conn))
                    elif path == "/admin/mp":
                        self.send_json(200, mp_list(conn, params))
                    elif path == "/admin/strategy":
                        rows = [dict(row) for row in conn.execute("SELECT * FROM strategy_rules ORDER BY id").fetchall()]
                        for row in rows:
                            row["config"] = json_loads(row.pop("config_json"), {})
                        self.send_json(200, {"items": rows, "channelRules": channel_rules()})
                    elif path == "/admin/modules":
                        self.send_json(200, module_summary(conn))
                    elif path == "/admin/pipeline/runs":
                        rows = [dict(row) for row in conn.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 40").fetchall()]
                        self.send_json(200, {"items": rows})
                    elif path == "/admin/access":
                        rows = [dict(row) for row in conn.execute("SELECT path, COUNT(*) AS count, MAX(created_at) AS lastSeen FROM access_events GROUP BY path ORDER BY count DESC LIMIT 50").fetchall()]
                        self.send_json(200, {"items": rows})
                    elif path == "/admin/audit":
                        rows = [dict(row) for row in conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 80").fetchall()]
                        self.send_json(200, {"items": rows})
                    elif path == "/admin/feedback":
                        rows = [dict(row) for row in conn.execute("SELECT * FROM strategy_feedback ORDER BY id DESC LIMIT 100").fetchall()]
                        self.send_json(200, {"items": rows})
                    elif path == "/admin/users":
                        rows = [dict(row) for row in conn.execute("SELECT id, username, role, active, created_at, updated_at, last_login_at FROM users ORDER BY id").fetchall()]
                        self.send_json(200, {"items": rows})
                    elif path == "/admin/source-health":
                        rows = [dict(row) for row in conn.execute("SELECT * FROM source_health ORDER BY id DESC LIMIT 200").fetchall()]
                        self.send_json(200, {"items": rows})
                    elif path == "/admin/model-eval":
                        latest = [dict(row) for row in conn.execute("SELECT * FROM model_evaluations ORDER BY id DESC LIMIT 20").fetchall()]
                        for row in latest:
                            row["detail"] = json_loads(row.pop("detail_json"), {})
                        self.send_json(200, {"current": evaluate_model_policy(conn), "history": latest})
                    elif path == "/admin/model-enrich":
                        rows = [dict(row) for row in conn.execute("SELECT * FROM item_enrichments ORDER BY id DESC LIMIT 80").fetchall()]
                        for row in rows:
                            row["response"] = json_loads(row.pop("response_json"), {})
                        mp_rows = [dict(row) for row in conn.execute("SELECT * FROM mp_enrichments ORDER BY id DESC LIMIT 80").fetchall()]
                        for row in mp_rows:
                            row["response"] = json_loads(row.pop("response_json"), {})
                        self.send_json(200, {
                            "items": rows,
                            "mpItems": mp_rows,
                            "available": deepseek_available(),
                            "model": DEEPSEEK_MODEL,
                            "thinking": DEEPSEEK_THINKING,
                            "reasoningEffort": DEEPSEEK_REASONING_EFFORT,
                            "promptVersion": ENRICH_PROMPT_VERSION,
                            "status": model_runtime_status(conn),
                        })
                    elif path.startswith("/admin/items/") and path.endswith("/trace"):
                        parts = [part for part in path.split("/") if part]
                        item_id = int(parts[2])
                        row = conn.execute("SELECT * FROM feed_items WHERE id=?", (item_id,)).fetchone()
                        if not row:
                            self.send_json(404, {"error": "item_not_found"})
                            return
                        enrichments = [dict(r) for r in conn.execute("SELECT * FROM item_enrichments WHERE item_id=? ORDER BY id DESC LIMIT 20", (item_id,)).fetchall()]
                        for item in enrichments:
                            item["response"] = json_loads(item.pop("response_json"), {})
                        duplicates = conn.execute("SELECT * FROM item_duplicates WHERE item_id=? ORDER BY score DESC", (item_id,)).fetchall()
                        self.send_json(200, {
                            "item": decorate_public_item(conn, row_to_public_item(row)),
                            "raw": json_loads(row["raw_json"], {}),
                            "enrichments": enrichments,
                            "duplicates": [dict(r) for r in duplicates],
                        })
                    elif path == "/admin/system":
                        auth_state = sanitize_wechat_auth_state(wechat_auth_state(conn))
                        self.send_json(200, {
                            "service": SERVICE_NAME,
                            "dbPath": str(DB_PATH),
                            "appRoot": str(APP_ROOT),
                            "webRoot": str(WEB_ROOT),
                            "opcConfig": str(OPC_CONFIG_PATH),
                            "mpSourcesConfig": str(MP_SOURCES_PATH),
                            "wechatSourceRegistry": "sqlite:wechat_sources,wechat_source_articles",
                            "wechatAuthStatus": auth_state.get("status"),
                            "wechatAuthorizedAccount": auth_state.get("account"),
                            "xExcluded": True,
                            "routes": ["/public/feed", "/public/feed?channel=opcSolo", "/public/daily/latest", "/public/daily/list", "/public/mp", "/public/sources", "/public/modules", "/public/rules", "/admin/*"],
                            "generatedAt": now_iso(),
                        })
                    else:
                        self.send_json(404, {"error": "not_found", "path": path})
        except Exception as exc:
            self.send_json(500, {"error": "server_error", "message": str(exc)})

    def do_POST(self) -> None:
        path, params = self.route_path()
        try:
            body = self.read_json()
            with get_db() as conn:
                init_db(conn)
                if path == "/admin/login":
                    username = compact_text(body.get("username"))
                    password = str(body.get("password") or "")
                    row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
                    if not row or not verify_password(password, row["password_hash"]):
                        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_credentials"})
                        return
                    conn.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), row["id"]))
                    conn.commit()
                    audit(conn, username, "login", "user", username)
                    self.send_json(200, {"token": make_token(conn, username, row["role"]), "user": {"username": username, "role": row["role"]}})
                    return
                if path == "/public/feedback":
                    conn.execute(
                        "INSERT INTO strategy_feedback(item_id,vote,reason,created_at) VALUES(?,?,?,?)",
                        (body.get("itemId"), compact_text(body.get("vote") or "feedback", limit=40), compact_text(body.get("reason") or body.get("message"), limit=1000), now_iso()),
                    )
                    conn.commit()
                    self.send_json(200, {"status": "ok"})
                    return
                actor = self.require_actor(conn)
                if not actor:
                    return
                username = actor["username"]
                if path == "/admin/pipeline/import-latest":
                    result = import_latest(conn)
                    audit(conn, username, "pipeline.import_latest", "pipeline", result.get("runId"), result)
                    self.send_json(200, result)
                elif path == "/admin/pipeline/run":
                    result = run_full_pipeline(conn)
                    audit(conn, username, "pipeline.run", "pipeline", result.get("runId"), result)
                    self.send_json(200, result)
                elif path == "/admin/daily/regenerate":
                    result = regenerate_daily(conn)
                    audit(conn, username, "daily.regenerate", "daily", result.get("issueDate"), {})
                    self.send_json(200, result)
                elif path == "/admin/model-eval/run":
                    result = evaluate_model_policy(conn, persist=True)
                    audit(conn, username, "model_eval.run", "model_eval", result.get("modelName"), {"score": result.get("score")})
                    self.send_json(200, result)
                elif path == "/admin/model-enrich/run":
                    limit = clamp_int(body.get("limit") or 20, 1, 80, 20)
                    force = bool(body.get("force"))
                    result = enrich_items(conn, limit=limit, force=force)
                    result["channelViews"] = rebuild_channel_views(conn)
                    regenerate_daily(conn)
                    audit(conn, username, "model_enrich.run", "model_enrich", DEEPSEEK_MODEL, result)
                    self.send_json(200, result)
                elif path == "/admin/mp/model-enrich/run":
                    limit = clamp_int(body.get("limit") or 12, 1, 60, 12)
                    force = bool(body.get("force"))
                    result = enrich_mp_articles(conn, limit=limit, force=force)
                    result["channelViews"] = rebuild_channel_views(conn)
                    regenerate_daily(conn)
                    audit(conn, username, "mp.model_enrich.run", "mp", DEEPSEEK_MODEL, result)
                    self.send_json(200, result)
                elif path == "/admin/duplicates/refresh":
                    result = refresh_duplicates(conn)
                    audit(conn, username, "duplicates.refresh", "duplicates", "", result)
                    self.send_json(200, result)
                elif path == "/admin/mp/import":
                    items = body.get("items") if isinstance(body, dict) else []
                    if not isinstance(items, list):
                        items = []
                    imported = import_mp(conn, items)
                    channel_views = rebuild_channel_views(conn)
                    audit(conn, username, "mp.import", "mp", "bulk", {"count": imported})
                    self.send_json(200, {"status": "ok", "imported": imported, "channelViews": channel_views})
                elif path == "/admin/mp/collect":
                    result = collect_mp_dynamic(conn)
                    result["channelViews"] = rebuild_channel_views(conn)
                    audit(conn, username, "mp.collect", "mp", "dynamic", result)
                    self.send_json(200, result)
                elif path == "/admin/mp/wechat-auth/start":
                    result = start_wechat_mp_auth(conn)
                    audit(conn, username, "mp.wechat_auth.start", "wechat_auth", result.get("uuid"), {"status": result.get("status")})
                    self.send_json(200, result)
                elif path == "/admin/mp/wechat-auth/refresh":
                    result = refresh_wechat_mp_auth(conn)
                    audit(conn, username, "mp.wechat_auth.refresh", "wechat_auth", result.get("uuid"), {"status": result.get("status")})
                    self.send_json(200, result)
                elif path == "/admin/mp/wechat-auth/clear":
                    result = sanitize_wechat_auth_state(clear_wechat_auth_state(conn))
                    audit(conn, username, "mp.wechat_auth.clear", "wechat_auth", "", {})
                    self.send_json(200, result)
                elif path == "/admin/mp/source-registry/search":
                    query = compact_text(body.get("query") or body.get("keyword") or body.get("q"), limit=120)
                    if not query:
                        self.send_json(400, {"error": "missing_query"})
                        return
                    limit = clamp_int(body.get("limit") or 10, 1, 20, 10)
                    offset = clamp_int(body.get("offset") or 0, 0, 200, 0)
                    result = search_wechat_source_candidates(conn, query, limit=limit, offset=offset)
                    audit(conn, username, "mp.source_registry.search", "wechat_source", query, {"count": len(result.get("items") or [])})
                    self.send_json(200, result)
                elif path == "/admin/mp/source-registry/add-search-result":
                    item = body.get("item") if isinstance(body.get("item"), dict) else body
                    source = upsert_wechat_source(conn, wechat_source_from_search_result(item))
                    audit(conn, username, "mp.source_registry.add_search_result", "wechat_source", source.get("uid"), {"accountName": source.get("accountName"), "fakeid": source.get("fakeid")})
                    self.send_json(200, {"status": "ok", "source": source, "registry": wechat_source_registry(conn)})
                elif path == "/admin/mp/source-registry/by-article":
                    urls = body.get("urls") if isinstance(body.get("urls"), list) else []
                    if not urls:
                        single = compact_text(body.get("url") or body.get("articleUrl"), limit=1200)
                        if single:
                            urls = [single]
                    result = discover_wechat_sources_by_articles(conn, [compact_text(url, limit=1200) for url in urls if compact_text(url)])
                    audit(conn, username, "mp.source_registry.by_article", "wechat_source", "", {"requested": result.get("requested"), "importedSources": result.get("importedSources"), "errors": len(result.get("errors") or [])})
                    self.send_json(200, result)
                elif path == "/admin/mp/source-registry/sync":
                    raw_uids = body.get("uids") if isinstance(body.get("uids"), list) else []
                    if not raw_uids:
                        single = compact_text(body.get("uid") or body.get("sourceUid"), limit=80)
                        raw_uids = [single] if single else []
                    result = sync_wechat_sources(conn, uids=[compact_text(uid, limit=80) for uid in raw_uids if compact_text(uid, limit=80)], limit=clamp_int(body.get("limit") or 10, 1, 20, 10))
                    result["channelViews"] = rebuild_channel_views(conn)
                    audit(conn, username, "mp.source_registry.sync", "wechat_source", ",".join(raw_uids[:10]), {"checked": result.get("checked"), "imported": result.get("imported"), "errors": len(result.get("errors") or [])})
                    self.send_json(200, result)
                elif path == "/admin/mp/source-registry/upsert":
                    raw_source = body.get("source") if isinstance(body.get("source"), dict) else body
                    source = upsert_wechat_source(conn, raw_source)
                    audit(conn, username, "mp.source_registry.upsert", "wechat_source", source.get("uid"), {"accountName": source.get("accountName"), "enabled": source.get("enabled")})
                    self.send_json(200, {"status": "ok", "source": source, "registry": wechat_source_registry(conn)})
                elif path == "/admin/mp/source-registry/delete":
                    source_uid = compact_text(body.get("uid") or body.get("sourceUid"), limit=80)
                    if not source_uid:
                        self.send_json(400, {"error": "missing_source_uid"})
                        return
                    if not delete_wechat_source(conn, source_uid):
                        self.send_json(404, {"error": "source_not_found"})
                        return
                    audit(conn, username, "mp.source_registry.delete", "wechat_source", source_uid, {})
                    self.send_json(200, {"status": "ok", "registry": wechat_source_registry(conn)})
                elif path == "/admin/mp/sources/upsert":
                    source = upsert_mp_source_config(body.get("source") if isinstance(body.get("source"), dict) else body)
                    audit(conn, username, "mp.source.upsert", "mp_source", source.get("id"), {"name": source.get("name"), "enabled": source.get("enabled")})
                    self.send_json(200, {"status": "ok", "source": source, "summary": mp_source_summary(conn, include_private=True)})
                elif path == "/admin/mp/sources/delete":
                    source_id = compact_text(body.get("id") or body.get("sourceId"))
                    if not source_id:
                        self.send_json(400, {"error": "missing_source_id"})
                        return
                    deleted = delete_mp_source_config(source_id)
                    if not deleted:
                        self.send_json(404, {"error": "source_not_found"})
                        return
                    audit(conn, username, "mp.source.delete", "mp_source", source_id, {})
                    self.send_json(200, {"status": "ok", "summary": mp_source_summary(conn, include_private=True)})
                elif path == "/admin/mp/sources/test":
                    source = None
                    source_id = compact_text(body.get("id") or body.get("sourceId"))
                    if source_id:
                        source = find_mp_source(source_id)
                        if not source:
                            self.send_json(404, {"error": "source_not_found"})
                            return
                    if source is None:
                        source = body.get("source") if isinstance(body.get("source"), dict) else body
                    result = test_mp_source(source)
                    audit(conn, username, "mp.source.test", "mp_source", result.get("source", {}).get("id"), {"status": result.get("status"), "fetched": result.get("fetched"), "accepted": result.get("accepted")})
                    self.send_json(200, result)
                else:
                    self.send_json(404, {"error": "not_found", "path": path})
        except Exception as exc:
            self.send_json(500, {"error": "server_error", "message": str(exc)})

    def do_PATCH(self) -> None:
        path, params = self.route_path()
        try:
            body = self.read_json()
            with get_db() as conn:
                init_db(conn)
                actor = self.require_actor(conn)
                if not actor:
                    return
                username = actor["username"]
                parts = [part for part in path.split("/") if part]
                if len(parts) == 3 and parts[:2] == ["admin", "items"]:
                    item_id = int(parts[2])
                    mapping = {"titleZh": "title_zh", "summaryZh": "summary_zh", "aiSelected": "ai_selected", "aiSelectedReason": "ai_selected_reason", "editorialJudgment": "editorial_judgment", "finalScore": "final_score"}
                    allowed = {}
                    for key, column in mapping.items():
                        if key in body:
                            allowed[column] = 1 if key == "aiSelected" and body[key] else 0 if key == "aiSelected" else body[key]
                    if not allowed:
                        self.send_json(400, {"error": "no_allowed_fields"})
                        return
                    allowed["updated_at"] = now_iso()
                    conn.execute("UPDATE feed_items SET " + ",".join(f"{k}=?" for k in allowed) + " WHERE id=?", [*allowed.values(), item_id])
                    conn.commit()
                    audit(conn, username, "item.update", "item", str(item_id), allowed)
                    row = conn.execute("SELECT * FROM feed_items WHERE id=?", (item_id,)).fetchone()
                    self.send_json(200, {"item": row_to_public_item(row) if row else None})
                elif len(parts) == 3 and parts[:2] == ["admin", "sources"]:
                    source_id = int(parts[2])
                    allowed = {}
                    for key in ("enabled", "weight"):
                        if key in body:
                            allowed[key] = int(body[key]) if key == "enabled" else float(body[key])
                    if not allowed:
                        self.send_json(400, {"error": "no_allowed_fields"})
                        return
                    allowed["updated_at"] = now_iso()
                    conn.execute("UPDATE sources SET " + ",".join(f"{k}=?" for k in allowed) + " WHERE id=?", [*allowed.values(), source_id])
                    conn.commit()
                    audit(conn, username, "source.update", "source", str(source_id), allowed)
                    self.send_json(200, {"status": "ok"})
                elif len(parts) == 3 and parts[:2] == ["admin", "strategy"]:
                    rule_id = int(parts[2])
                    allowed = {}
                    for key in ("enabled", "weight", "description"):
                        if key in body:
                            allowed[key] = int(body[key]) if key == "enabled" else body[key]
                    if not allowed:
                        self.send_json(400, {"error": "no_allowed_fields"})
                        return
                    allowed["updated_at"] = now_iso()
                    conn.execute("UPDATE strategy_rules SET " + ",".join(f"{k}=?" for k in allowed) + " WHERE id=?", [*allowed.values(), rule_id])
                    conn.commit()
                    audit(conn, username, "strategy.update", "strategy", str(rule_id), allowed)
                    self.send_json(200, {"status": "ok"})
                else:
                    self.send_json(404, {"error": "not_found", "path": path})
        except Exception as exc:
            self.send_json(500, {"error": "server_error", "message": str(exc)})


def upsert_mp_article(conn: sqlite3.Connection, raw: dict[str, Any], *, default_origin: str, imported_via: str, source_weight: float = 1.0) -> bool:
    if not isinstance(raw, dict):
        return False
    ts = now_iso()
    raw_origin = compact_text(raw.get("sourceOrigin") or raw.get("source_origin") or raw.get("origin") or default_origin, limit=80)
    origin_key = raw_origin.lower()
    raw_blob = json.dumps(raw, ensure_ascii=False).lower()
    if "aihot.virxact.com" in raw_blob or origin_key in {"public_reference_seed", "aihot_public_sample", "aihot_seed"}:
        return False
    title = compact_text(raw.get("title"), limit=240)
    account = compact_text(raw.get("accountName") or raw.get("account_name") or raw.get("source") or "公众号", limit=120)
    if not title:
        return False
    url = compact_text(raw.get("url") or raw.get("link"), limit=1000)
    heat_score, anomaly_score, relevance_score = mp_heat_scores(raw, source_weight=source_weight)
    explicit_relevance = raw.get("aiRelevanceScore") or raw.get("ai_relevance_score")
    if explicit_relevance is None and relevance_score < 12:
        return False
    uid = stable_uid(url or title, account, raw.get("publishedAt") or raw.get("published_at"))
    source_origin = raw_origin if raw_origin in {"manual_import", "dynamic_collector", "third_party_api"} else default_origin
    provenance = {
        "collector": compact_text(raw.get("collector") or raw.get("provider") or source_origin, limit=120),
        "accountName": account,
        "url": url,
        "importedVia": imported_via,
    }
    conn.execute(
        "INSERT INTO mp_articles(uid,title,account_name,url,published_at,summary,heat_score,anomaly_score,ai_relevance_score,tags_json,raw_json,source_origin,provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(uid) DO UPDATE SET title=excluded.title, account_name=excluded.account_name, url=excluded.url, published_at=excluded.published_at, summary=excluded.summary, heat_score=excluded.heat_score, anomaly_score=excluded.anomaly_score, ai_relevance_score=excluded.ai_relevance_score, tags_json=excluded.tags_json, raw_json=excluded.raw_json, source_origin=excluded.source_origin, provenance_json=excluded.provenance_json, updated_at=excluded.updated_at",
        (
            uid,
            title,
            account,
            url,
            parse_item_time(raw.get("publishedAt") or raw.get("published_at")),
            compact_text(raw.get("summary"), limit=1000),
            float(raw.get("heatScore") or raw.get("heat_score") or heat_score),
            float(raw.get("anomalyScore") or raw.get("anomaly_score") or anomaly_score),
            float(explicit_relevance or relevance_score),
            json_dumps(raw.get("tags") or []),
            json_dumps(raw),
            source_origin,
            json_dumps(provenance),
            ts,
            ts,
        ),
    )
    return True


def import_mp(conn: sqlite3.Connection, items: list[Any]) -> int:
    imported = 0
    for raw in items:
        if upsert_mp_article(conn, raw, default_origin="manual_import", imported_via="admin_mp_import"):
            imported += 1
    conn.commit()
    return imported


def collect_mp_dynamic(conn: sqlite3.Connection) -> dict[str, Any]:
    config = mp_sources_config()
    sources = [source for source in config.get("sources", []) or [] if isinstance(source, dict) and source.get("enabled")]
    imported = 0
    checked = 0
    errors: list[dict[str, Any]] = []
    for source in sources:
        name = source_name_from_config(source, "公众号动态源")
        source_type = normalize_kind(source.get("type") or source.get("source_kind") or "rss")
        url = compact_text(source.get("url") or source.get("feed_url") or source.get("api_url"), limit=1000)
        weight = clamp_float(source.get("weight") or 1, 0.1, 5.0, 1.0)
        checked += 1
        started = time.time()
        if not url:
            upsert_source(conn, name=name, source_kind="mp_" + source_type, channel="mp", status="skipped", count=0, detail="missing url")
            continue
        try:
            text = fetch_text(url)
            rows = parse_mp_source_payload(text, source)
            count = 0
            for row in rows:
                if upsert_mp_article(conn, row, default_origin="dynamic_collector", imported_via="mp_dynamic_collect", source_weight=weight):
                    count += 1
            imported += count
            upsert_source(conn, name=name, source_kind="mp_" + source_type, channel="mp", status="ok", count=count, detail=url, elapsed_ms=int((time.time() - started) * 1000), url=url, config=source)
        except Exception as exc:
            detail = compact_text(str(exc), limit=500)
            errors.append({"source": name, "error": detail})
            upsert_source(conn, name=name, source_kind="mp_" + source_type, channel="mp", status="error", count=0, detail=detail, elapsed_ms=int((time.time() - started) * 1000), url=url, config=source)
    wechat_checked = 0
    wechat_imported = 0
    wechat_raw = 0
    try:
        wechat_result = sync_wechat_sources(conn, limit=10)
        wechat_checked = int(wechat_result.get("checked") or 0)
        wechat_imported = int(wechat_result.get("imported") or 0)
        wechat_raw = int(wechat_result.get("rawArticles") or 0)
        imported += wechat_imported
        checked += wechat_checked
        errors.extend(wechat_result.get("errors") or [])
    except Exception as exc:
        if compact_text(str(exc)) != "wechat_mp_authorization_required":
            errors.append({"source": "wechat_mp_api", "error": compact_text(str(exc), limit=500)})
    conn.commit()
    return {
        "status": "ok",
        "checked": checked,
        "imported": imported,
        "errors": errors[:10],
        "configured": len(config.get("sources", []) or []),
        "enabled": len(sources),
        "wechatChecked": wechat_checked,
        "wechatImported": wechat_imported,
        "wechatRawArticles": wechat_raw,
    }


def serve(host: str, port: int) -> None:
    with get_db() as conn:
        init_db(conn)
        ensure_secret(conn)
        ensure_admin(conn)
        ensure_mp_sources_config()
        seed_sources_from_config(conn)
        if conn.execute("SELECT COUNT(*) AS c FROM feed_items").fetchone()["c"] == 0 and LATEST_JSON_PATH.exists():
            import_latest(conn)
        ensure_channel_views(conn)
    server = ThreadingHTTPServer((host, port), AihotHandler)
    print(f"{SERVICE_NAME} listening on {host}:{port}", flush=True)
    server.serve_forever()


def cmd_init(args: argparse.Namespace) -> None:
    with get_db() as conn:
        init_db(conn)
        ensure_secret(conn)
        password = ensure_admin(conn)
        ensure_mp_sources_config()
        configured_sources = seed_sources_from_config(conn)
        print(json.dumps({"status": "ok", "db": str(DB_PATH), "credentials": str(CREDENTIALS_PATH), "adminCreated": bool(password), "configuredSources": configured_sources}, ensure_ascii=False))


def cmd_import(args: argparse.Namespace) -> None:
    with get_db() as conn:
        init_db(conn)
        ensure_secret(conn)
        ensure_admin(conn)
        ensure_mp_sources_config()
        result = import_latest(conn, latest_path=Path(args.latest_json or LATEST_JSON_PATH))
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_run(args: argparse.Namespace) -> None:
    with get_db() as conn:
        init_db(conn)
        ensure_secret(conn)
        ensure_admin(conn)
        ensure_mp_sources_config()
        result = run_full_pipeline(conn)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_enrich(args: argparse.Namespace) -> None:
    with get_db() as conn:
        init_db(conn)
        ensure_secret(conn)
        ensure_admin(conn)
        result = enrich_items(conn, limit=args.limit, force=args.force)
        result["channelViews"] = rebuild_channel_views(conn)
        regenerate_daily(conn)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_collect_mp(args: argparse.Namespace) -> None:
    with get_db() as conn:
        init_db(conn)
        ensure_secret(conn)
        ensure_admin(conn)
        result = collect_mp_dynamic(conn)
        result["channelViews"] = rebuild_channel_views(conn)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="WelOPC AIHOT reproduction service")
    sub = parser.add_subparsers(dest="command")
    init_parser = sub.add_parser("init")
    init_parser.set_defaults(func=cmd_init)
    import_parser = sub.add_parser("import-latest")
    import_parser.add_argument("--latest-json", default="")
    import_parser.set_defaults(func=cmd_import)
    run_parser = sub.add_parser("run-pipeline")
    run_parser.set_defaults(func=cmd_run)
    enrich_parser = sub.add_parser("enrich")
    enrich_parser.add_argument("--limit", type=int, default=20)
    enrich_parser.add_argument("--force", action="store_true")
    enrich_parser.set_defaults(func=cmd_enrich)
    collect_mp_parser = sub.add_parser("collect-mp")
    collect_mp_parser.set_defaults(func=cmd_collect_mp)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8790)
    serve_parser.set_defaults(func=lambda args: serve(args.host, args.port))
    args = parser.parse_args()
    if not hasattr(args, "func"):
        args = parser.parse_args(["serve"])
    args.func(args)


if __name__ == "__main__":
    main()
