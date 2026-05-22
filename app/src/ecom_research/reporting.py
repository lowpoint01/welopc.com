from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import recommendation
from .utils import ensure_dirs


def render_markdown(
    records_df: pd.DataFrame,
    category_df: pd.DataFrame,
    keyword_df: pd.DataFrame,
    cluster_df: pd.DataFrame,
) -> str:
    total_rows = len(records_df)
    blocked_rows = int((records_df.get("crawl_status", pd.Series(dtype=str)) != "ok").sum()) if not records_df.empty else 0
    lines = [
        "# 电商平台 Claude 调研报告",
        "",
        f"- 总记录数：{total_rows}",
        f"- 阻断记录数：{blocked_rows}",
        f"- 推荐结论：{recommendation(category_df)}",
        "",
        "## 类目机会排序",
        "",
        _table(category_df, ["service_category", "listing_count", "seller_count", "median_price", "demand_proxy", "risk_adjusted_score"]),
        "",
        "## 关键词表现",
        "",
        _table(keyword_df, ["platform", "keyword", "listing_count", "seller_count", "blocked_count"]),
        "",
        "## 标题聚类",
        "",
        _table(cluster_df, ["cluster_id", "cluster_size", "sample_titles"]),
        "",
        "## 操作建议",
        "",
        "- 不要把账号或 Token 转售作为主打 SKU。",
        "- 优先试三种商品形态：Claude 安装服务、Claude 工具包、Claude 落地培训。",
        "- 每个关键词至少补 3 到 5 页采样，再看店铺集中度和价格带。",
        "- 后续要扩到“全店铺画像”，应追加详情页补抓和店铺页补抓。",
    ]
    return "\n".join(lines)


def write_report(content: str, output_path: Path) -> Path:
    ensure_dirs(output_path.parent)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "_无可展示数据_"
    view = df.loc[:, [column for column in columns if column in df.columns]].copy()
    headers = list(view.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in view.iterrows():
        values = [str(row[column]) for column in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
