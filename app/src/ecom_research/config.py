from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


DEFAULT_KEYWORDS = [
    "Claude",
    "Claude 安装",
    "Claude API",
    "Claude Token",
    "Claude 账号",
]


@dataclass(slots=True)
class CrawlSettings:
    platforms: list[str]
    keywords: list[str]
    pages: int = 1


def load_settings(path: str | Path | None) -> CrawlSettings:
    if path is None:
        return CrawlSettings(platforms=["taobao", "jd"], keywords=DEFAULT_KEYWORDS, pages=1)

    config_path = Path(path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    platforms = [str(item).strip().lower() for item in data.get("platforms", ["taobao", "jd"])]
    keywords = [str(item).strip() for item in data.get("keywords", DEFAULT_KEYWORDS) if str(item).strip()]
    pages = int(data.get("pages", 1))
    return CrawlSettings(platforms=platforms, keywords=keywords, pages=max(1, pages))
