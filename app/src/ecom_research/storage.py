from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import ListingRecord
from .utils import ensure_dirs


ROOT = Path(__file__).resolve().parents[2]
AUTH_DIR = ROOT / "auth"
RAW_DIR = ROOT / "data" / "raw"
NORMALIZED_DIR = ROOT / "data" / "normalized"
ENRICHED_DIR = ROOT / "data" / "enriched"
IMAGE_DIR = ROOT / "data" / "images"
REPORT_DIR = ROOT / "reports" / "generated"

ensure_dirs(AUTH_DIR, RAW_DIR, NORMALIZED_DIR, ENRICHED_DIR, IMAGE_DIR, REPORT_DIR)


def write_jsonl(rows: Iterable[dict], path: Path) -> None:
    ensure_dirs(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def records_to_dataframe(records: list[ListingRecord]) -> Any:
    import pandas as pd

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame([record.to_dict() for record in records])
    return df.drop_duplicates(subset=["platform", "keyword", "item_id", "item_url", "title"], keep="first")


def write_tabular(df: Any, base_path: Path) -> tuple[Path, Path]:
    ensure_dirs(base_path.parent)
    csv_path = base_path.with_suffix(".csv")
    xlsx_path = base_path.with_suffix(".xlsx")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False)
    return csv_path, xlsx_path
