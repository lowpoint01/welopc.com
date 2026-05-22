from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_slug(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "unknown"


def compact_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def parse_jsonp(text: str) -> dict[str, Any] | list[Any] | None:
    content = text.strip()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", content, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def regex_first(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I)
    return match.group(1).strip() if match else ""


def normalize_numeric(text: str) -> float | None:
    if not text:
        return None
    content = text.replace(",", "").strip().lower()
    match = re.search(r"(\d+(?:\.\d+)?)", content)
    if not match:
        return None
    value = float(match.group(1))
    if "万" in text:
        value *= 10000
    if "千" in text or "k" in content:
        value *= 1000
    return value
