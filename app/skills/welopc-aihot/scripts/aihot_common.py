from __future__ import annotations

import json
import os
import sys
from urllib import error, parse, request


DEFAULT_BASE_URL = "https://welopc.com/ai-hot/api/public"


def resolve_base_url(value: str | None = None) -> str:
    base_url = (
        value
        or os.environ.get("WEL_OPC_BASE_URL")
        or os.environ.get("WELOPC_AIHOT_BASE_URL")
        or DEFAULT_BASE_URL
    )
    return base_url.rstrip("/")


def build_url(base_url: str, endpoint: str, params: dict[str, object] | None = None) -> str:
    clean_base = resolve_base_url(base_url)
    clean_endpoint = "/" + endpoint.strip("/")
    url = f"{clean_base}{clean_endpoint}"
    query = {
        key: value
        for key, value in (params or {}).items()
        if value is not None and value != ""
    }
    if query:
        url = f"{url}?{parse.urlencode(query)}"
    return url


def fetch_json(url: str, timeout: int = 20) -> object:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"AIHOT API error {exc.code} for {url}: {body}") from exc
    except error.URLError as exc:
        raise SystemExit(f"AIHOT network error for {url}: {exc.reason}") from exc


def extract_items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    content = payload.get("content")
    if isinstance(content, dict):
        groups = content.get("groups")
        if isinstance(groups, dict):
            flattened: list[dict[str, object]] = []
            for group_items in groups.values():
                if isinstance(group_items, list):
                    flattened.extend(item for item in group_items if isinstance(item, dict))
            return flattened
    return []


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _score(raw: dict[str, object]) -> float | None:
    for key in ("channelScore", "finalScore", "signal_score", "score", "qualityScore", "importance"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return None


def _tags(raw: dict[str, object]) -> list[str]:
    tags = raw.get("aiTags") or raw.get("tags") or []
    normalized: list[str] = []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                value = tag.get("tag") or tag.get("name")
            else:
                value = tag
            text = str(value or "").strip()
            if text:
                normalized.append(text)
    return normalized


def normalize_item(raw: dict[str, object]) -> dict[str, object]:
    source = raw.get("source")
    source_name = source.get("name") if isinstance(source, dict) else ""
    return {
        "id": raw.get("id"),
        "title": _first_text(raw.get("titleZh"), raw.get("title")),
        "summary": _first_text(raw.get("summaryZh"), raw.get("summary"), raw.get("editorialJudgment")),
        "url": _first_text(raw.get("url"), raw.get("link")),
        "source": _first_text(raw.get("sourceName"), raw.get("source_name"), source_name),
        "channel": _first_text(raw.get("channel"), raw.get("sourceKind"), raw.get("source_kind")),
        "published_at": _first_text(raw.get("publishedAt"), raw.get("published"), raw.get("observedAt")),
        "score": _score(raw),
        "tags": _tags(raw),
        "reason": _first_text(raw.get("aiSelectedReason"), raw.get("editorialJudgment")),
    }


def normalize_items(payload: object) -> list[dict[str, object]]:
    return [normalize_item(item) for item in extract_items(payload)]


def filter_items_by_query(items: list[dict[str, object]], query: str | None) -> list[dict[str, object]]:
    needle = str(query or "").strip().lower()
    if not needle:
        return items
    matches: list[dict[str, object]] = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("source") or ""),
                " ".join(str(tag) for tag in item.get("tags") or []),
            ]
        ).lower()
        if needle in haystack:
            matches.append(item)
    return matches


def render_items_markdown(
    items: list[dict[str, object]],
    heading: str,
    empty_message: str = "No AIHOT signals matched.",
) -> str:
    lines = [f"# {heading}", ""]
    if not items:
        lines.append(empty_message)
        return "\n".join(lines).rstrip() + "\n"

    for index, item in enumerate(items, 1):
        title = item.get("title") or "Untitled"
        url = item.get("url") or ""
        source = item.get("source") or "Unknown source"
        channel = item.get("channel") or "unknown"
        score = item.get("score")
        published_at = item.get("published_at") or ""
        summary = item.get("summary") or ""
        tags = item.get("tags") or []

        label = f"[{title}]({url})" if url else str(title)
        meta = f"{source} · {channel}"
        if score is not None:
            meta = f"{meta} · score {score}"
        if published_at:
            meta = f"{meta} · {published_at}"

        lines.extend([f"## {index}. {label}", "", f"- {meta}"])
        if summary:
            lines.append(f"- {summary}")
        if tags:
            lines.append(f"- Tags: {', '.join(str(tag) for tag in tags)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_json(data: object) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def write_markdown(markdown: str) -> None:
    sys.stdout.write(markdown)
    if not markdown.endswith("\n"):
        sys.stdout.write("\n")
