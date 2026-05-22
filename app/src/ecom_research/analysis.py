from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

from .utils import normalize_numeric


CATEGORY_RULES = {
    "installation_service": ["安装", "代装", "部署", "接入", "配置", "远程", "本地化", "客户端"],
    "account_service": ["账号", "共享", "独享", "订阅", "代注册", "会员", "包月", "plus", "pro"],
    "api_token_service": ["token", "api", "key", "接口", "中转", "转发", "额度", "充值"],
    "tool_delivery": ["脚本", "源码", "插件", "工具", "工作流", "机器人", "知识库", "客户端"],
    "training_consulting": ["教程", "培训", "咨询", "答疑", "课程", "陪跑", "方案"],
}

RISK_MULTIPLIER = {
    "installation_service": 1.0,
    "tool_delivery": 0.9,
    "training_consulting": 0.9,
    "account_service": 0.25,
    "api_token_service": 0.2,
    "other": 0.75,
}


def load_input_files(paths: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        file_path = Path(path)
        if not file_path.exists():
            continue
        frames.append(pd.read_csv(file_path))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df.drop_duplicates(subset=["platform", "keyword", "item_id", "item_url", "title"], keep="first")


def categorize_title(title: str) -> str:
    content = (title or "").lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword.lower() in content for keyword in keywords):
            return category
    return "other"


def enrich_records(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    enriched = df.copy()
    enriched["title"] = enriched["title"].fillna("").astype(str)
    enriched["shop_name"] = enriched["shop_name"].fillna("").astype(str)
    enriched["service_category"] = enriched["title"].map(categorize_title)
    enriched["price_value"] = enriched["price_text"].fillna("").map(normalize_numeric)
    enriched["demand_proxy"] = enriched["sales_text"].fillna("").map(_sales_to_float).fillna(0.0)
    enriched["risk_multiplier"] = enriched["service_category"].map(RISK_MULTIPLIER).fillna(0.75)
    return enriched


def build_category_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "service_category",
                "listing_count",
                "seller_count",
                "median_price",
                "demand_proxy",
                "gap_score",
                "risk_adjusted_score",
            ]
        )

    valid_df = df[df["crawl_status"] == "ok"].copy()
    if valid_df.empty:
        return pd.DataFrame(
            columns=[
                "service_category",
                "listing_count",
                "seller_count",
                "median_price",
                "demand_proxy",
                "gap_score",
                "risk_adjusted_score",
            ]
        )

    grouped = (
        valid_df.groupby("service_category", dropna=False)
        .agg(
            listing_count=("title", "count"),
            seller_count=("shop_name", lambda values: values.replace("", pd.NA).dropna().nunique()),
            median_price=("price_value", "median"),
            demand_proxy=("demand_proxy", "sum"),
            risk_multiplier=("risk_multiplier", "mean"),
        )
        .reset_index()
    )
    grouped["median_price"] = grouped["median_price"].fillna(0.0)
    grouped["seller_count"] = grouped["seller_count"].fillna(0).astype(int)
    grouped["gap_score"] = grouped.apply(_gap_score, axis=1)
    grouped["risk_adjusted_score"] = grouped["gap_score"] * grouped["risk_multiplier"]
    return grouped.sort_values("risk_adjusted_score", ascending=False).reset_index(drop=True)


def build_keyword_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["platform", "keyword", "listing_count", "seller_count", "blocked_count"])
    summary = (
        df.groupby(["platform", "keyword"], dropna=False)
        .agg(
            listing_count=("title", "count"),
            seller_count=("shop_name", lambda values: values.replace("", pd.NA).dropna().nunique()),
            blocked_count=("crawl_status", lambda values: int((values != "ok").sum())),
        )
        .reset_index()
        .sort_values(["platform", "listing_count"], ascending=[True, False])
    )
    return summary


def cluster_titles(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["cluster_id", "cluster_size", "sample_titles"])

    title_df = df[df["crawl_status"] == "ok"].copy()
    title_df = title_df[title_df["title"].str.len() > 1]
    if title_df.empty:
        return pd.DataFrame(columns=["cluster_id", "cluster_size", "sample_titles"])
    if len(title_df) < 3:
        return pd.DataFrame(
            [{"cluster_id": 0, "cluster_size": len(title_df), "sample_titles": " | ".join(title_df["title"].head(3))}]
        )

    cluster_count = min(6, max(2, len(title_df) // 4), len(title_df))
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(title_df["title"])
    model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
    title_df["cluster_id"] = model.fit_predict(matrix)

    clustered = (
        title_df.groupby("cluster_id")
        .agg(
            cluster_size=("title", "count"),
            sample_titles=("title", lambda values: " | ".join(values.head(3))),
        )
        .reset_index()
        .sort_values("cluster_size", ascending=False)
    )
    return clustered


def recommendation(summary_df: pd.DataFrame) -> str:
    if summary_df.empty:
        return "当前没有足够的有效商品记录，先补登录态并扩大关键词采样。"

    top = summary_df.iloc[0]
    category = str(top["service_category"])
    if category in {"account_service", "api_token_service"}:
        return (
            "即使当前供给/需求代理值看起来不差，也不建议把账号或 Token 转售作为主线。"
            "优先转成安装部署、工具交付或培训咨询，降低平台与上游条款风险。"
        )
    if category == "installation_service":
        return "优先上架 Claude 安装/代接入/远程部署服务，并把网络环境配置与常见问题处理打包成标准交付。"
    if category == "tool_delivery":
        return "优先上架 Claude 配套工具、工作流、脚本或知识库接入方案，用标准化交付提高复购。"
    if category == "training_consulting":
        return "优先上架 Claude 培训咨询与场景方案服务，适合做高客单价、低纠纷的差异化商品。"
    return "先补更多采样数据，再按类目竞争强度和风险折扣重新排序。"


def _sales_to_float(text: str) -> float:
    value = normalize_numeric(text)
    return float(value or 0.0)


def _gap_score(row: pd.Series) -> float:
    demand = float(row.get("demand_proxy", 0.0) or 0.0)
    listings = float(row.get("listing_count", 0.0) or 0.0)
    sellers = float(row.get("seller_count", 0.0) or 0.0)
    price = float(row.get("median_price", 0.0) or 0.0)
    base = math.log1p(demand + listings)
    price_bonus = math.log1p(max(price, 0.0))
    return (base + 0.3 * price_bonus) / (1.0 + sellers)
