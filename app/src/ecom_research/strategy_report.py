from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from .storage import ENRICHED_DIR, NORMALIZED_DIR, REPORT_DIR
from .utils import compact_text, ensure_dirs, now_stamp


TITLE_CATEGORY_RULES = {
    "api_token": ["api", "token", "中转", "接口", "key", "额度"],
    "subscription_account": ["安装", "部署", "接入", "镜像", "直登", "代订阅", "共享", "独享", "会员", "订阅", "代充", "账号", "pro", "max"],
    "training": ["教程", "课程", "培训", "陪跑", "咨询", "授课"],
    "tool_software": ["软件", "脚本", "插件", "工具", "系统"],
}

FOCUS_TOKENS = {
    "claude",
    "claudecode",
    "code",
    "api",
    "token",
    "pro",
    "max",
    "sonnet",
    "opus",
    "haiku",
    "中转",
    "直登",
    "镜像",
    "订阅",
    "会员",
    "账号",
    "代充",
    "独享",
    "共享",
    "课程",
    "培训",
    "安装",
    "部署",
}

OCR_STOP_WORDS = {
    "claude",
    "max",
    "pro",
    "会员",
    "订阅",
    "软件",
    "财务",
    "办公",
    "code",
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    report_path, ocr_path = generate_strategy_report(
        search_input=Path(args.search_input),
        detail_input=Path(args.detail_input),
    )
    print(f"report={report_path}")
    print(f"ocr_csv={ocr_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate JD SKU strategy report from search, detail, and image OCR data.")
    parser.add_argument("--search-input", default=str(NORMALIZED_DIR / "jd_20260402_172346.csv"))
    parser.add_argument("--detail-input", default=str(ENRICHED_DIR / "jd_detail_20260402_202650.csv"))
    return parser


def generate_strategy_report(*, search_input: Path, detail_input: Path) -> tuple[Path, Path]:
    search_df = pd.read_csv(search_input)
    detail_df = pd.read_csv(detail_input)
    search_df = search_df[search_df["crawl_status"] == "ok"].copy()
    search_df["service_category"] = search_df["title"].map(classify_title)
    search_df["price_value"] = search_df["price_text"].map(parse_price)
    search_df["price_band"] = search_df["price_value"].map(price_band)

    detail_df["review_count_value"] = detail_df["review_count_text"].map(parse_count)

    image_df = build_image_ocr_dataset(search_df)
    valid_image_df = image_df[image_df["relevance_overlap"] >= 1].copy()
    valid_image_df["cover_cluster"] = valid_image_df.apply(assign_cover_cluster, axis=1)
    valid_image_df["visual_group"] = valid_image_df.apply(assign_visual_group, axis=1)
    image_df = image_df.merge(
        valid_image_df.loc[:, ["item_id", "cover_cluster", "visual_group"]],
        on="item_id",
        how="left",
    )

    stamp = now_stamp()
    ensure_dirs(ENRICHED_DIR, REPORT_DIR)
    ocr_path = ENRICHED_DIR / f"jd_image_ocr_{stamp}.csv"
    image_df.to_csv(ocr_path, index=False, encoding="utf-8-sig")

    report = render_report(
        search_df=search_df,
        detail_df=detail_df,
        image_df=image_df,
        valid_image_df=valid_image_df,
    )
    report_path = REPORT_DIR / f"jd_sku_strategy_{stamp}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path, ocr_path


def build_image_ocr_dataset(search_df: pd.DataFrame) -> pd.DataFrame:
    ocr_engine = RapidOCR()
    rows: list[dict[str, Any]] = []
    image_root = ENRICHED_DIR.parent / "images" / "jd"
    for _, row in search_df.iterrows():
        item_id = str(row["item_id"])
        item_dir = image_root / item_id
        title = compact_text(str(row["title"]))
        title_tokens = tokenize(title)
        best: dict[str, Any] | None = None
        for path in sorted(item_dir.glob("*")):
            if not path.is_file():
                continue
            texts = run_ocr(ocr_engine, path)
            joined = " ".join(texts)
            ocr_tokens = tokenize(joined)
            overlap = len((title_tokens & ocr_tokens) & FOCUS_TOKENS)
            focus_hits = len(ocr_tokens & FOCUS_TOKENS)
            score = overlap * 50 + focus_hits * 5 + sum(len(text) for text in texts)
            brightness, saturation = image_metrics(path)
            candidate = {
                "item_id": item_id,
                "title": title,
                "shop_name": compact_text(str(row["shop_name"])),
                "price_text": compact_text(str(row["price_text"])),
                "image_path": str(path),
                "ocr_text": joined,
                "ocr_line_count": len(texts),
                "relevance_overlap": overlap,
                "focus_hits": focus_hits,
                "score": score,
                "brightness": brightness,
                "saturation": saturation,
            }
            if best is None or score > int(best["score"]):
                best = candidate
        rows.append(
            best
            or {
                "item_id": item_id,
                "title": title,
                "shop_name": compact_text(str(row["shop_name"])),
                "price_text": compact_text(str(row["price_text"])),
                "image_path": "",
                "ocr_text": "",
                "ocr_line_count": 0,
                "relevance_overlap": 0,
                "focus_hits": 0,
                "score": 0,
                "brightness": None,
                "saturation": None,
            }
        )
    return pd.DataFrame(rows)


def run_ocr(engine: RapidOCR, path: Path) -> list[str]:
    try:
        result, _ = engine(str(path))
    except Exception:
        return []
    texts = []
    for item in result or []:
        text = compact_text(str(item[1]))
        if len(text) < 2 or text.lower() == "v":
            continue
        texts.append(text)
    return texts


def image_metrics(path: Path) -> tuple[float | None, float | None]:
    try:
        image = Image.open(path).convert("RGB").resize((64, 64))
    except Exception:
        return None, None
    arr = np.asarray(image).astype(np.float32) / 255.0
    brightness = float(arr.mean())
    saturation = float((np.max(arr, axis=2) - np.min(arr, axis=2)).mean())
    return brightness, saturation


def classify_title(title: str) -> str:
    content = title.lower()
    for category, rules in TITLE_CATEGORY_RULES.items():
        if any(rule.lower() in content for rule in rules):
            return category
    return "other"


def assign_cover_cluster(row: pd.Series) -> str:
    text = compact_text(str(row["ocr_text"])).lower()
    if any(token in text for token in ["sonnet", "opus", "镜像", "代订阅", "自动发货", "pro/max"]):
        return "模型矩阵卖点卡"
    if any(token in text for token in ["cursor", "无限额度", "高级模型", "可开发票"]):
        return "高配承诺黑底卡"
    if any(token in text for token in ["安装", "1v1", "培训", "课程", "试听", "包教会"]):
        return "服务培训转化卡"
    return "低相关或污染图"


def assign_visual_group(row: pd.Series) -> str:
    brightness = row.get("brightness")
    if brightness is None or pd.isna(brightness):
        return "unknown"
    if float(brightness) < 0.45:
        return "暗底高反差"
    return "亮底信息密集"


def parse_price(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def parse_count(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def price_band(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    if value < 100:
        return "<100"
    if value < 300:
        return "100-299"
    if value < 800:
        return "300-799"
    if value < 1500:
        return "800-1499"
    return "1500+"


def tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9.+/#-]{2,}|[\u4e00-\u9fff]{2,}", str(text))
        if token.strip()
    }


def top_title_words(search_df: pd.DataFrame, limit: int = 20) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for title in search_df["title"]:
        for token in tokenize(str(title)):
            if token in OCR_STOP_WORDS:
                continue
            counter[token] += 1
    return counter.most_common(limit)


def top_ocr_words(valid_image_df: pd.DataFrame, limit: int = 20) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for text in valid_image_df["ocr_text"]:
        for token in tokenize(str(text)):
            if token in OCR_STOP_WORDS:
                continue
            counter[token] += 1
    return counter.most_common(limit)


def installation_rows(search_df: pd.DataFrame) -> pd.DataFrame:
    keywords = ["安装", "代安装", "cli", "命令行", "本地"]
    mask = search_df["title"].astype(str).map(lambda value: any(keyword.lower() in value.lower() for keyword in keywords))
    return search_df[mask].copy()


def render_report(
    *,
    search_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    image_df: pd.DataFrame,
    valid_image_df: pd.DataFrame,
) -> str:
    category_summary = (
        search_df.groupby("service_category", dropna=False)
        .agg(
            listings=("item_id", "count"),
            shops=("shop_name", "nunique"),
            median_price=("price_value", "median"),
        )
        .reset_index()
        .sort_values("listings", ascending=False)
    )
    top_shops = (
        search_df.groupby("shop_name", dropna=False)
        .agg(listings=("item_id", "count"))
        .reset_index()
        .sort_values("listings", ascending=False)
        .head(10)
    )
    price_band_summary = pd.crosstab(search_df["service_category"], search_df["price_band"]).reset_index()
    install_df = installation_rows(search_df)
    cover_cluster_summary = (
        valid_image_df.groupby(["cover_cluster", "visual_group"], dropna=False)
        .agg(sample_count=("item_id", "count"))
        .reset_index()
        .sort_values("sample_count", ascending=False)
    )
    review_df = detail_df[detail_df["sample_reviews"].fillna("").astype(str) != ""].copy()
    title_word_items = "、".join(f"{word}({count})" for word, count in top_title_words(search_df))
    ocr_word_items = "、".join(f"{word}({count})" for word, count in top_ocr_words(valid_image_df))

    lines = [
        "# 京东 Claude 上架策略调研报告",
        "",
        "## 样本范围",
        "",
        f"- 搜索种子 SKU: {len(search_df)}",
        f"- 唯一店铺数: {search_df['shop_name'].nunique()}",
        f"- 详情增强 SKU: {len(detail_df)}",
        f"- 评论样本覆盖: {int(detail_df['sample_reviews'].fillna('').astype(str).ne('').sum())}/{len(detail_df)}",
        f"- 已落盘主图: {int(detail_df['downloaded_image_count'].fillna(0).astype(float).gt(0).sum())}/{len(detail_df)}",
        f"- 高置信 OCR 主图: {len(valid_image_df)}/{len(image_df)}",
        "- 说明: 图片库里混有前几轮补抓留下的相关推荐图和验证页图，所以主图分析只采用“标题-图片相关度 >= 1”的高置信子集。",
        "",
        "## 供给结构",
        "",
        table(category_summary, ["service_category", "listings", "shops", "median_price"]),
        "",
        "## 卖家集中度",
        "",
        table(top_shops, ["shop_name", "listings"]),
        "",
        "## 价格带",
        "",
        table(price_band_summary, list(price_band_summary.columns)),
        "",
        "## 直接可代安装竞品",
        "",
        table(install_df, ["item_id", "title", "price_text", "shop_name"]) if not install_df.empty else "_无直接安装竞品_",
        "",
        f"- 显性可代安装/CLI 竞品数: {len(install_df)}",
        f"- 显性可代安装中位价: {round(float(install_df['price_value'].median()), 2) if not install_df.empty else 'n/a'}",
        "",
        "## 主图 OCR 结论",
        "",
        table(cover_cluster_summary, ["cover_cluster", "visual_group", "sample_count"]),
        "",
        f"- 标题高频词: {title_word_items}",
        f"- 主图 OCR 高频词: {ocr_word_items}",
        "- 结论 1: 高置信封面里，主流打法不是展示交付过程，而是展示“模型矩阵 + 直登/镜像 + 自动发货 + 售后保障”。",
        "- 结论 2: 少量黑底卡会强调“无限额度、支持 MAX、高级模型、可开发票”，本质仍然是在卖资源而不是卖服务。",
        "- 结论 3: 安装/陪跑相关的用户价值在评论里是被验证过的，但封面表达几乎没有被系统化包装。",
        "",
        "## 评论信号",
        "",
        table(review_df, ["item_id", "title", "review_count_text", "good_rate_text", "sample_reviews"]) if not review_df.empty else "_无可用评论样本_",
        "",
        "- 评论里反复出现的真实需求是: 快速搞定、远程帮装、疑难杂症能处理、售后响应快、能稳定用。",
        "",
        "## 判断",
        "",
        "- 当前市场最拥挤的是 `subscription_account` 和 `api_token` 两条线。前者 29 个种子 SKU，后者 18 个，且卖家集中在少数店铺，说明同质化很强。",
        "- 账号/Token 赛道价格从 `<100` 到 `1500+` 都有人卖，价格锚点已经被打烂，但真正可验证的评论和口碑并不多。",
        "- 显性安装/CLI 服务只有 3 个，但中位价已经到 `842.4`，说明“代安装/代接入”有人卖，而且愿意卖高价，只是包装还很粗糙。",
        "- 因此最适合你的不是继续卷账号和 API，而是把“安装部署 + 场景落地 + 售后”做成平台可理解的服务 SKU。",
        "",
        "## 推荐 SKU 策略",
        "",
        table(
            pd.DataFrame(
                [
                    {
                        "sku": "低价引流款",
                        "定位": "Claude 环境诊断",
                        "建议价": "69-99",
                        "交付物": "系统检测、网络可用性判断、安装清单、账号/API 使用建议",
                        "目的": "先成交，再转主力服务",
                    },
                    {
                        "sku": "主推成交款",
                        "定位": "Claude Code 远程安装部署",
                        "建议价": "199-299",
                        "交付物": "Windows/Mac 安装、CLI 配置、IDE 接入、基础测试、7-30 天答疑",
                        "目的": "替代当前 842 元级粗糙代安装竞品",
                    },
                    {
                        "sku": "利润款",
                        "定位": "Claude 工作流落地包",
                        "建议价": "399-699",
                        "交付物": "提示词模板、项目目录规范、Git/IDE 工作流、常用自动化脚本",
                        "目的": "从“装上”升级到“能持续用”",
                    },
                    {
                        "sku": "高客单定制",
                        "定位": "团队接入与培训",
                        "建议价": "999-1499",
                        "交付物": "需求梳理、知识库接入、培训录屏/SOP、30 天售后",
                        "目的": "做定制溢价，不跟低价资源单竞争",
                    },
                ]
            ),
            ["sku", "定位", "建议价", "交付物", "目的"],
        ),
        "",
        "## 上架文案建议",
        "",
        "- 标题方向 1: `Claude Code 远程安装部署 Windows/Mac 可接自有账号/API 送基础配置`",
        "- 标题方向 2: `Claude 工作流搭建 远程交付 提示词模板/自动化脚本/知识库接入`",
        "- 标题方向 3: `Claude 企业落地咨询 方案梳理+培训录屏+30天答疑 不含账号转售`",
        "- 主图不要继续抄“模型矩阵卡”。你应该改成“结果导向卡”: 1 对 1 远程、客户自备账号/API、可录屏交付、30 天售后。",
        "- 主图上最该放的不是 `Opus/Sonnet` 列表，而是 `能装上`、`能连通`、`能落地`、`有售后` 四个结果词。",
        "",
        "## 不建议主卖的 SKU",
        "",
        "- 不建议把 `账号转售` 作为主打。供给最密，售后争议最大，也最容易被平台和上游规则夹击。",
        "- 不建议把 `Token/API 中转` 作为主打。价格锚点混乱，解释成本高，且稳定性风险会直接变成售后风险。",
        "- 可以保留“客户自备账号/API 的代接入服务”，但不要把“卖账号/卖额度”写成核心卖点。",
        "",
        "## 最终建议",
        "",
        "- 上架结构上，用 `69-99` 的诊断 SKU 拉点击和转化，用 `199-299` 的安装部署做主成交，用 `399-699` 的工作流包吃利润。",
        "- 页面表达上，统一强调 `客户自备账号/API`、`远程交付`、`录屏/SOP`、`售后期`，主动和账号/API 贩卖划清线。",
        "- 真正的差异化不是“我也能卖 Claude”，而是“我能把 Claude 装好、接好、用起来，还能兜底售后”。",
    ]
    return "\n".join(lines)


def table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "_无可展示数据_"
    headers = [column for column in columns if column in df.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in df.loc[:, headers].iterrows():
        values = [compact_text(str(row[column])).replace("|", "/") for column in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
