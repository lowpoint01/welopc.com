from __future__ import annotations

import json
import os
import re
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .storage import AUTH_DIR
from .utils import compact_text


FEISHU_API_ROOT = "https://open.feishu.cn/open-apis"
FEISHU_PUBLISH_CONFIG = AUTH_DIR / "feishu_publish.json"
FEISHU_USER_TOKEN_FILE = AUTH_DIR / "feishu_user_token.json"
FEISHU_OAUTH_AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
FEISHU_OAUTH_TOKEN_URL = FEISHU_API_ROOT + "/authen/v2/oauth/token"
FEISHU_OAUTH_USERINFO_PATH = "/authen/v1/user_info"
BLOCK_FIELD_BY_TYPE = {
    2: "text",
    3: "heading1",
    4: "heading2",
    5: "heading3",
    12: "bullet",
    13: "ordered",
    14: "code",
    15: "quote",
}


class FeishuPublishError(RuntimeError):
    pass


def publish_markdown_to_feishu(
    *,
    markdown_path: Path,
    target_url: str = "",
    title: str = "",
    create_new: bool = False,
    folder_token: str = "",
    public_readable: bool | None = None,
) -> dict[str, str]:
    if not markdown_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {markdown_path}")

    config = load_feishu_publish_config()
    resolved_target_url = compact_text(target_url) or compact_text(str(config.get("target_url", "")))
    resolved_folder_token = compact_text(folder_token) or compact_text(str(config.get("folder_token", "")))
    resolved_create_new = bool(create_new or config.get("create_new", False))
    resolved_title = compact_text(title) or markdown_path.stem
    resolved_public_readable = public_readable if public_readable is not None else bool(config.get("public_readable", False))

    access_token, token_mode = get_access_token()

    if resolved_target_url:
        resource_type, resource_token = parse_feishu_url(resolved_target_url)
        if resource_type == "wiki":
            resource_type, resource_token = resolve_wiki_target(access_token=access_token, wiki_token=resource_token)
        final_url = resolved_target_url
    elif resolved_create_new:
        created = create_document(
            access_token=access_token,
            title=resolved_title,
            folder_token=resolved_folder_token,
        )
        resource_type = "docx"
        resource_token = created["document_id"]
        final_url = created["url"]
    else:
        raise FeishuPublishError(
            "No target Feishu document was resolved. Provide --target-url, or configure/create a default target."
        )

    if resource_type != "docx":
        raise FeishuPublishError(f"Unsupported Feishu resource type: {resource_type}. Only wiki/docx is supported.")

    if resolved_public_readable:
        update_docx_public_permission(access_token=access_token, document_token=resource_token)

    markdown_text = markdown_path.read_text(encoding="utf-8")
    blocks = markdown_to_docx_blocks(markdown_text)
    if not blocks:
        raise FeishuPublishError("Markdown file is empty after normalization.")

    append_blocks(access_token=access_token, document_token=resource_token, blocks=blocks)
    return {
        "target_type": resource_type,
        "target_token": resource_token,
        "target_url": final_url,
        "block_count": str(len(blocks)),
        "input_md": str(markdown_path),
        "token_mode": token_mode,
        "public_readable": str(resolved_public_readable).lower(),
    }


def publish_markdown_bundle_to_feishu(
    *,
    project_name: str,
    report_md: Path,
    service_md: Path,
    folder_token: str = "",
    public_readable: bool | None = None,
) -> list[dict[str, str]]:
    normalized_project_name = compact_text(project_name) or "企业AI服务项目"
    outputs = [
        publish_markdown_to_feishu(
            markdown_path=report_md,
            title=f"{normalized_project_name}-01 调研报告",
            create_new=True,
            folder_token=folder_token,
            public_readable=public_readable,
        ),
        publish_markdown_to_feishu(
            markdown_path=service_md,
            title=f"{normalized_project_name}-02 服务方案",
            create_new=True,
            folder_token=folder_token,
            public_readable=public_readable,
        ),
    ]
    return outputs


def login_feishu_user(
    *,
    port: int = 3000,
    timeout_seconds: int = 300,
    open_browser: bool = True,
    scopes: str = "",
) -> dict[str, str]:
    app_id, app_secret = get_app_credentials()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    authorization = wait_for_feishu_oauth_code(
        app_id=app_id,
        redirect_uri=redirect_uri,
        timeout_seconds=timeout_seconds,
        open_browser=open_browser,
        scopes=scopes,
    )
    token_bundle = exchange_oauth_code_for_user_token(
        app_id=app_id,
        app_secret=app_secret,
        code=authorization["code"],
        redirect_uri=redirect_uri,
    )
    user_token = save_user_token_bundle(token_bundle, app_id=app_id, redirect_uri=redirect_uri)
    return {
        "redirect_uri": redirect_uri,
        "authorization_url": authorization["authorization_url"],
        "token_path": str(FEISHU_USER_TOKEN_FILE),
        "user_name": compact_text(str(user_token.get("name", ""))),
        "open_id": compact_text(str(user_token.get("open_id", ""))),
        "access_expires_at": str(user_token.get("access_expires_at", "")),
        "refresh_expires_at": str(user_token.get("refresh_expires_at", "")),
        "scope": compact_text(str(user_token.get("scope", ""))),
    }


def get_app_credentials() -> tuple[str, str]:
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise FeishuPublishError("Missing credentials. Set FEISHU_APP_ID + FEISHU_APP_SECRET.")
    return app_id, app_secret


def wait_for_feishu_oauth_code(
    *,
    app_id: str,
    redirect_uri: str,
    timeout_seconds: int,
    open_browser: bool,
    scopes: str,
) -> dict[str, str]:
    state = secrets.token_urlsafe(24)
    auth_url = build_feishu_authorization_url(app_id=app_id, redirect_uri=redirect_uri, state=state, scopes=scopes)
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse.urlparse(self.path)
            if query.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = parse.parse_qs(query.query)
            returned_state = compact_text(params.get("state", [""])[0])
            code = compact_text(params.get("code", [""])[0])
            error_message = compact_text(params.get("error", [""])[0] or params.get("error_description", [""])[0])
            if returned_state != state:
                error_message = error_message or "OAuth state mismatch."
            if code and not error_message:
                result["code"] = code
                result["state"] = returned_state
                body = b"<html><body><h3>Feishu login succeeded.</h3><p>You can close this window.</p></body></html>"
                self.send_response(200)
            else:
                result["error"] = error_message or "Feishu login failed."
                body = f"<html><body><h3>{result['error']}</h3></body></html>".encode("utf-8", errors="replace")
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port_from_redirect_uri(redirect_uri)), CallbackHandler)
    server.timeout = 0.5
    deadline = time.time() + max(timeout_seconds, 30)

    try:
        if open_browser:
            webbrowser.open(auth_url, new=1, autoraise=True)
        while time.time() < deadline:
            server.handle_request()
            if result:
                break
    finally:
        server.server_close()

    if "error" in result:
        raise FeishuPublishError(result["error"])
    if "code" not in result:
        raise FeishuPublishError(
            "Timed out waiting for Feishu OAuth callback. Open the authorization URL manually and finish login."
        )
    result["authorization_url"] = auth_url
    return result


def build_feishu_authorization_url(*, app_id: str, redirect_uri: str, state: str, scopes: str) -> str:
    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    normalized_scopes = compact_text(scopes)
    if normalized_scopes:
        params["scope"] = normalized_scopes
    return FEISHU_OAUTH_AUTHORIZE_URL + "?" + parse.urlencode(params)


def port_from_redirect_uri(redirect_uri: str) -> int:
    parsed = parse.urlparse(redirect_uri)
    if not parsed.port:
        raise FeishuPublishError(f"Redirect URI missing port: {redirect_uri}")
    return parsed.port


def exchange_oauth_code_for_user_token(
    *,
    app_id: str,
    app_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return feishu_oauth_token_request(
        {
            "grant_type": "authorization_code",
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    )


def refresh_oauth_user_token(*, app_id: str, app_secret: str, refresh_token: str) -> dict[str, Any]:
    return feishu_oauth_token_request(
        {
            "grant_type": "refresh_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "refresh_token": refresh_token,
        }
    )


def feishu_oauth_token_request(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=FEISHU_OAUTH_TOKEN_URL, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise FeishuPublishError(f"Feishu OAuth API error {exc.code}: {raw}") from exc
    except error.URLError as exc:
        raise FeishuPublishError(f"Feishu OAuth request failed: {exc}") from exc

    try:
        payload_obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuPublishError(f"Invalid Feishu OAuth response: {raw}") from exc

    if payload_obj.get("code", 0) != 0:
        raise FeishuPublishError(
            f"Feishu OAuth API error {payload_obj.get('code')}: {payload_obj.get('msg')} | {raw}"
        )
    data = payload_obj.get("data", payload_obj)
    if not compact_text(str(data.get("access_token", ""))):
        raise FeishuPublishError(f"Feishu OAuth response missing access_token: {raw}")
    return data


def save_user_token_bundle(token_bundle: dict[str, Any], *, app_id: str, redirect_uri: str) -> dict[str, Any]:
    current_ts = int(time.time())
    user_info = get_user_info(compact_text(str(token_bundle.get("access_token", ""))))
    output = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "access_token": compact_text(str(token_bundle.get("access_token", ""))),
        "refresh_token": compact_text(str(token_bundle.get("refresh_token", ""))),
        "scope": compact_text(str(token_bundle.get("scope", ""))),
        "token_type": compact_text(str(token_bundle.get("token_type", ""))),
        "access_expires_in": int(token_bundle.get("expires_in", 0) or 0),
        "refresh_expires_in": int(token_bundle.get("refresh_expires_in", 0) or 0),
        "access_expires_at": current_ts + int(token_bundle.get("expires_in", 0) or 0),
        "refresh_expires_at": current_ts + int(token_bundle.get("refresh_expires_in", 0) or 0),
        "authorized_at": current_ts,
        "name": compact_text(str(user_info.get("name", ""))),
        "en_name": compact_text(str(user_info.get("en_name", ""))),
        "open_id": compact_text(str(user_info.get("open_id", ""))),
        "union_id": compact_text(str(user_info.get("union_id", ""))),
        "tenant_key": compact_text(str(user_info.get("tenant_key", ""))),
        "avatar_url": compact_text(str(user_info.get("avatar_url", ""))),
    }
    FEISHU_USER_TOKEN_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def get_user_info(access_token: str) -> dict[str, Any]:
    if not access_token:
        return {}
    try:
        data = feishu_request(method="GET", path=FEISHU_OAUTH_USERINFO_PATH, access_token=access_token)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_user_token_bundle() -> dict[str, Any]:
    if not FEISHU_USER_TOKEN_FILE.exists():
        return {}
    try:
        payload = json.loads(FEISHU_USER_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_saved_user_access_token() -> str:
    token_bundle = load_user_token_bundle()
    if not token_bundle:
        return ""

    access_token = compact_text(str(token_bundle.get("access_token", "")))
    access_expires_at = int(token_bundle.get("access_expires_at", 0) or 0)
    if access_token and access_expires_at > int(time.time()) + 120:
        return access_token

    refresh_token = compact_text(str(token_bundle.get("refresh_token", "")))
    refresh_expires_at = int(token_bundle.get("refresh_expires_at", 0) or 0)
    app_id = compact_text(str(token_bundle.get("app_id", "")))
    env_app_id = os.getenv("FEISHU_APP_ID", "").strip()
    if env_app_id and app_id and env_app_id != app_id:
        return ""
    if not refresh_token or refresh_expires_at <= int(time.time()) + 120:
        return ""
    if not env_app_id:
        return ""
    app_id, app_secret = get_app_credentials()
    refreshed = refresh_oauth_user_token(app_id=app_id, app_secret=app_secret, refresh_token=refresh_token)
    saved = save_user_token_bundle(
        refreshed,
        app_id=app_id,
        redirect_uri=compact_text(str(token_bundle.get("redirect_uri", ""))),
    )
    return compact_text(str(saved.get("access_token", "")))


def get_access_token() -> tuple[str, str]:
    user_access_token = os.getenv("FEISHU_USER_ACCESS_TOKEN", "").strip()
    if user_access_token:
        return user_access_token, "user_access_token"

    cached_user_access_token = resolve_saved_user_access_token()
    if cached_user_access_token:
        return cached_user_access_token, "user_access_token"

    app_id, app_secret = get_app_credentials()
    if not app_id or not app_secret:
        raise FeishuPublishError(
            "Missing credentials. Set FEISHU_USER_ACCESS_TOKEN or FEISHU_APP_ID + FEISHU_APP_SECRET."
        )
    return get_tenant_access_token(app_id=app_id, app_secret=app_secret), "tenant_access_token"


def get_tenant_access_token(*, app_id: str, app_secret: str) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    url = FEISHU_API_ROOT + "/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise FeishuPublishError(f"Feishu API error {exc.code}: {raw}") from exc
    except error.URLError as exc:
        raise FeishuPublishError(f"Feishu request failed: {exc}") from exc

    try:
        payload_obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuPublishError(f"Invalid Feishu response: {raw}") from exc

    if payload_obj.get("code", 0) != 0:
        raise FeishuPublishError(f"Feishu API error {payload_obj.get('code')}: {payload_obj.get('msg')} | {raw}")

    token = compact_text(str(payload_obj.get("tenant_access_token", "")))
    if not token:
        raise FeishuPublishError("Feishu tenant access token was empty.")
    return token


def parse_feishu_url(url: str) -> tuple[str, str]:
    match = re.search(r"https?://[^/]+/(wiki|docx|docs)/([A-Za-z0-9]+)", url, re.I)
    if not match:
        raise FeishuPublishError(f"Unsupported Feishu URL: {url}")
    resource_type = match.group(1).lower()
    if resource_type == "docs":
        resource_type = "docx"
    return resource_type, match.group(2)


def resolve_wiki_target(*, access_token: str, wiki_token: str) -> tuple[str, str]:
    data = feishu_request(
        method="GET",
        path=f"/wiki/v2/spaces/get_node?token={parse.quote(wiki_token)}",
        access_token=access_token,
    )
    node = data.get("node", {}) if isinstance(data, dict) else {}
    obj_type = compact_text(str(node.get("obj_type", ""))).lower()
    obj_token = compact_text(str(node.get("obj_token", "")))
    if not obj_type or not obj_token:
        raise FeishuPublishError(f"Unable to resolve wiki token: {wiki_token}")
    if obj_type == "docs":
        obj_type = "docx"
    return obj_type, obj_token


def update_docx_title(*, access_token: str, document_token: str, title: str) -> None:
    feishu_request(
        method="PATCH",
        path=f"/docx/v1/documents/{document_token}",
        access_token=access_token,
        payload={"title": title[:200]},
    )


def create_document(*, access_token: str, title: str, folder_token: str = "") -> dict[str, str]:
    payload: dict[str, Any] = {"title": title[:200]}
    if folder_token:
        payload["folder_token"] = folder_token
    data = feishu_request(
        method="POST",
        path="/docx/v1/documents",
        access_token=access_token,
        payload=payload,
    )
    document = data.get("document", {}) if isinstance(data, dict) else {}
    document_id = compact_text(str(document.get("document_id", "")))
    if not document_id:
        raise FeishuPublishError(f"Feishu create document response missing document_id: {data}")
    return {
        "document_id": document_id,
        "url": f"https://feishu.cn/docx/{document_id}",
    }


def update_docx_public_permission(*, access_token: str, document_token: str) -> dict[str, Any]:
    return feishu_request(
        method="PATCH",
        path=f"/drive/v2/permissions/{document_token}/public?type=docx",
        access_token=access_token,
        payload={
            "external_access_entity": "open",
            "security_entity": "anyone_can_view",
            "comment_entity": "anyone_can_view",
            "copy_entity": "anyone_can_view",
            "share_entity": "anyone",
            "manage_collaborator_entity": "collaborator_can_view",
            "link_share_entity": "anyone_readable",
            "lock_switch": False,
        },
    )


def append_blocks(*, access_token: str, document_token: str, blocks: list[dict[str, Any]]) -> None:
    for index in range(0, len(blocks), 20):
        chunk = blocks[index : index + 20]
        feishu_request(
            method="POST",
            path=f"/docx/v1/documents/{document_token}/blocks/{document_token}/children",
            access_token=access_token,
            payload={"children": chunk},
        )


def markdown_to_docx_blocks(markdown_text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    in_code_block = False

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not stripped:
            continue

        block_type, normalized = normalize_markdown_line(stripped, in_code_block=in_code_block)
        for chunk in split_text(normalized, max_length=1400):
            blocks.append(build_text_block(chunk, block_type=block_type))
    return blocks


def normalize_markdown_line(line: str, *, in_code_block: bool) -> tuple[int, str]:
    if in_code_block:
        return 14, line
    if re.match(r"^###\s+", line):
        title = re.sub(r"^###\s+", "", line)
        return 5, title
    if re.match(r"^##\s+", line):
        title = re.sub(r"^##\s+", "", line)
        return 4, title
    if re.match(r"^#\s+", line):
        title = re.sub(r"^#\s+", "", line)
        return 3, title
    if re.match(r"^[-*+]\s+", line):
        return 12, re.sub(r"^[-*+]\s+", "", line)
    if re.match(r"^\d+\.\s+", line):
        return 13, re.sub(r"^\d+\.\s+", "", line)
    if re.match(r"^>\s+", line):
        return 15, re.sub(r"^>\s+", "", line)
    return 2, line


def build_text_block(text: str, *, block_type: int = 2) -> dict[str, Any]:
    field_name = BLOCK_FIELD_BY_TYPE.get(block_type, "text")
    payload: dict[str, Any] = {
        "elements": [
            {
                "text_run": {
                    "content": text,
                }
            }
        ]
    }
    if block_type == 14:
        payload["style"] = {"language": 1, "wrap": True}
    else:
        payload["style"] = {}
    return {
        "block_type": block_type,
        field_name: payload,
    }


def block_text(block: dict[str, Any]) -> str:
    try:
        for field_name in BLOCK_FIELD_BY_TYPE.values():
            if field_name in block:
                return str(block[field_name]["elements"][0]["text_run"]["content"])
        return ""
    except Exception:
        return ""


def split_text(text: str, *, max_length: int) -> list[str]:
    content = text if text else " "
    if len(content) <= max_length:
        return [content]

    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + max_length, len(content))
        if end < len(content):
            window = content[start:end]
            for delimiter in [".", ";", ",", " ", "\t"]:
                cut = window.rfind(delimiter)
                if cut >= max_length // 2:
                    end = start + cut + 1
                    break
        chunks.append(content[start:end].strip() or " ")
        start = end
    return chunks


def feishu_request(
    *,
    method: str,
    path: str,
    access_token: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = path if path.startswith("http") else FEISHU_API_ROOT + path
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = request.Request(url=url, data=body, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise FeishuPublishError(f"Feishu API error {exc.code}: {raw}") from exc
    except error.URLError as exc:
        raise FeishuPublishError(f"Feishu request failed: {exc}") from exc

    try:
        payload_obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuPublishError(f"Invalid Feishu response: {raw}") from exc

    if payload_obj.get("code", 0) != 0:
        raise FeishuPublishError(f"Feishu API error {payload_obj.get('code')}: {payload_obj.get('msg')} | {raw}")
    return payload_obj.get("data", {})


def load_feishu_publish_config() -> dict[str, Any]:
    if not FEISHU_PUBLISH_CONFIG.exists():
        return {}
    try:
        return json.loads(FEISHU_PUBLISH_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_feishu_publish_config(
    *,
    target_url: str | None = None,
    folder_token: str | None = None,
    create_new: bool | None = None,
    public_readable: bool | None = None,
    clear: bool = False,
) -> Path | None:
    if clear:
        if FEISHU_PUBLISH_CONFIG.exists():
            FEISHU_PUBLISH_CONFIG.unlink()
        return None

    config = load_feishu_publish_config()
    if target_url is not None:
        config["target_url"] = compact_text(target_url)
    if folder_token is not None:
        config["folder_token"] = compact_text(folder_token)
    if create_new is not None:
        config["create_new"] = bool(create_new)
    if public_readable is not None:
        config["public_readable"] = bool(public_readable)
    FEISHU_PUBLISH_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return FEISHU_PUBLISH_CONFIG
