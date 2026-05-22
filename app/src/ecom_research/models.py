from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ListingRecord:
    platform: str
    keyword: str
    title: str = ""
    item_url: str = ""
    shop_name: str = ""
    shop_url: str = ""
    item_id: str = ""
    shop_id: str = ""
    price_text: str = ""
    sales_text: str = ""
    location: str = ""
    page: int = 1
    rank: int = 0
    crawl_status: str = "ok"
    blocker_reason: str = ""
    source: str = "dom"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["raw"] = json.dumps(self.raw, ensure_ascii=False)
        return data
