from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd

from .storage import ENRICHED_DIR, NORMALIZED_DIR, REPORT_DIR
from .utils import ensure_dirs, now_stamp


DEFAULT_SEARCH_INPUT = NORMALIZED_DIR / "jd_20260402_172346.csv"
DEFAULT_DETAIL_INPUT = ENRICHED_DIR / "jd_detail_20260402_202650.csv"
DEFAULT_OCR_INPUT = ENRICHED_DIR / "jd_image_ocr_20260402_210926.csv"

STORE_NAME = "企巴士"

SEARCH_TERMS = [
    {"round": "actual_sample", "keyword": "Claude", "intent": "现有京东样本基线", "status": "captured"},
    {"round": "recommended", "keyword": "OpenClaw", "intent": "盘点主关键词污染程度", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 安装", "intent": "抓高意图安装服务", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 部署", "intent": "抓交付型服务", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 远程部署", "intent": "抓远程交付服务", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 本地部署", "intent": "区分服务与整机", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw Windows 安装", "intent": "抓客户端环境部署", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw Mac 安装", "intent": "抓苹果端交付", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 飞书", "intent": "抓企业协同场景", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 知识库", "intent": "抓企业知识库场景", "status": "recommended"},
    {"round": "recommended", "keyword": "OpenClaw 故障排查", "intent": "抓售后问题单", "status": "recommended"},
]

EXTERNAL_EVIDENCE = [
    {
        "category": "service",
        "query": "site:jd.com/jiage OpenClaw 远程 部署 服务 京东",
        "signal": "JD 索引页出现 OpenClaw 安装指导、本地部署、远程部署、陪跑等服务型结果。",
        "url": "https://www.jd.com/jiage/12218d0256de18384c47e.html",
    },
    {
        "category": "hardware",
        "query": "site:jd.com/jiage OpenClaw 本地部署 工作站 京东",
        "signal": "JD 索引页出现 ThinkStation / 龙虾主机 / DeepSeek / OpenClaw 本地部署整机或工作站结果。",
        "url": "https://www.jd.com/jiage/670081dd1dbd866c026.html",
    },
    {
        "category": "hardware",
        "query": "site:jd.com/phb OpenClaw 部署 远程 指导 京东",
        "signal": "JD 榜单页出现 ThinkPad + OpenClaw 部署远程指导的混合型整机结果。",
        "url": "https://www.jd.com/phb/key_670985eaf438ea993ec.html",
    },
    {
        "category": "content",
        "query": "site:jd.com/jiage OpenClaw 教程 京东",
        "signal": "JD 索引页出现 OpenClaw 书籍/教程类结果，说明关键词还混入了内容商品。",
        "url": "https://www.jd.com/jiage/12218d0256de18384c47e.html",
    },
]


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    report_path, term_path, evidence_path = generate_openclaw_report(
        search_input=Path(args.search_input),
        detail_input=Path(args.detail_input),
        ocr_input=Path(args.ocr_input),
        store_name=args.store_name,
    )
    print(f"report={report_path}")
    print(f"search_terms_csv={term_path}")
    print(f"external_evidence_csv={evidence_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deeper JD OpenClaw competitor report.")
    parser.add_argument("--search-input", default=str(DEFAULT_SEARCH_INPUT))
    parser.add_argument("--detail-input", default=str(DEFAULT_DETAIL_INPUT))
    parser.add_argument("--ocr-input", default=str(DEFAULT_OCR_INPUT))
    parser.add_argument("--store-name", default=STORE_NAME)
    return parser


def generate_openclaw_report(
    *,
    search_input: Path,
    detail_input: Path,
    ocr_input: Path,
    store_name: str,
) -> tuple[Path, Path, Path]:
    ensure_dirs(ENRICHED_DIR, REPORT_DIR)
    search_df = pd.read_csv(search_input)
    detail_df = pd.read_csv(detail_input)
    ocr_df = pd.read_csv(ocr_input)

    search_df = search_df[search_df["crawl_status"] == "ok"].copy()
    search_df["price_value"] = search_df["price_text"].map(parse_price)
    search_df["segment"] = search_df["title"].map(classify_segment)

    detail_cols = [
        "item_id",
        "review_count_text",
        "good_rate_text",
        "sample_reviews",
        "downloaded_image_count",
    ]
    merged_df = search_df.merge(detail_df[detail_cols], on="item_id", how="left")

    visual_df = build_visual_frame(ocr_df)
    install_df = merged_df[merged_df["segment"] == "install_service"].copy()
    api_df = merged_df[merged_df["segment"] == "api_token"].copy()

    stamp = now_stamp()
    terms_path = ENRICHED_DIR / f"openclaw_search_terms_{stamp}.csv"
    evidence_path = ENRICHED_DIR / f"openclaw_external_evidence_{stamp}.csv"
    report_path = REPORT_DIR / f"openclaw_jd_competitor_report_{stamp}.md"

    pd.DataFrame(SEARCH_TERMS).to_csv(terms_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(EXTERNAL_EVIDENCE).to_csv(evidence_path, index=False, encoding="utf-8-sig")

    report = render_report(
        search_df=search_df,
        merged_df=merged_df,
        visual_df=visual_df,
        install_df=install_df,
        api_df=api_df,
        store_name=store_name,
        search_input=search_input,
        detail_input=detail_input,
        ocr_input=ocr_input,
        term_path=terms_path,
        evidence_path=evidence_path,
    )
    report_path.write_text(report, encoding="utf-8")
    return report_path, terms_path, evidence_path


def classify_segment(title: str) -> str:
    text = str(title).lower()
    if any(token in text for token in ["安装", "部署", "cli", "远程", "接入"]):
        return "install_service"
    if any(token in text for token in ["api", "token", "key", "中转", "额度"]):
        return "api_token"
    if any(token in text for token in ["共享", "独享", "订阅", "会员", "代充", "账号", "直登", "镜像"]):
        return "account_subscription"
    if any(token in text for token in ["教程", "培训", "课程", "陪跑", "咨询"]):
        return "training_consulting"
    return "other"


def parse_price(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def build_visual_frame(ocr_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in ocr_df.to_dict(orient="records"):
        image_path = Path(str(row.get("image_path", "")))
        if not image_path.exists():
            continue
        phash = compute_phash(image_path)
        edge_density = compute_edge_density(image_path)
        rows.append(
            {
                "item_id": str(row.get("item_id", "")),
                "title": str(row.get("title", "")),
                "shop_name": str(row.get("shop_name", "")),
                "image_path": str(image_path),
                "ocr_text": str(row.get("ocr_text", "") or ""),
                "ocr_line_count": int(row.get("ocr_line_count", 0) or 0),
                "relevance_overlap": int(row.get("relevance_overlap", 0) or 0),
                "focus_hits": int(row.get("focus_hits", 0) or 0),
                "brightness": safe_float(row.get("brightness")),
                "saturation": safe_float(row.get("saturation")),
                "phash": phash,
                "edge_density": edge_density,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    template_sizes = frame["phash"].value_counts(dropna=True).to_dict()
    frame["template_size"] = frame["phash"].map(template_sizes).fillna(1).astype(int)
    frame["is_install_like"] = frame["title"].map(
        lambda value: any(token in str(value).lower() for token in ["安装", "部署", "cli"])
    )
    return frame


def safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return float(value)
    except Exception:
        return None


def compute_phash(path: Path) -> str:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return ""
    image = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(image))
    dct_low = dct[:8, :8]
    median = float(np.median(dct_low[1:, 1:]))
    bits = (dct_low > median).astype(np.uint8).flatten().tolist()
    return "".join(str(bit) for bit in bits)


def compute_edge_density(path: Path) -> float | None:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    image = cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(image, 80, 160)
    return round(float((edges > 0).mean()), 6)


def render_report(
    *,
    search_df: pd.DataFrame,
    merged_df: pd.DataFrame,
    visual_df: pd.DataFrame,
    install_df: pd.DataFrame,
    api_df: pd.DataFrame,
    store_name: str,
    search_input: Path,
    detail_input: Path,
    ocr_input: Path,
    term_path: Path,
    evidence_path: Path,
) -> str:
    segment_summary = (
        search_df.groupby("segment")
        .agg(listings=("item_id", "count"), shops=("shop_name", "nunique"), median_price=("price_value", "median"))
        .reset_index()
        .sort_values(["listings", "median_price"], ascending=[False, False])
    )
    top_shops = (
        search_df.groupby("shop_name")
        .agg(listings=("item_id", "count"), segments=("segment", lambda s: ", ".join(sorted(set(s)))))
        .reset_index()
        .sort_values(["listings", "shop_name"], ascending=[False, True])
        .head(10)
    )
    install_view = install_df.loc[:, ["item_id", "title", "shop_name", "price_text"]].copy()
    if not install_view.empty:
        install_view["price_sort"] = install_df["price_value"].tolist()
        install_view = install_view.sort_values(["price_sort", "item_id"], ascending=[False, True]).drop(columns=["price_sort"])

    visual_summary = summarize_visuals(visual_df)
    install_visual_summary = summarize_install_visuals(visual_df)
    install_reviews = install_df.loc[:, ["item_id", "title", "review_count_text", "good_rate_text", "sample_reviews"]].copy()

    return "\n".join(
        [
            "# 京东 OpenClaw / Claude Code 竞品深度调研报告",
            "",
            "## 结论先行",
            "",
            f"- 对 `{store_name}` 来说，京东上的 `OpenClaw` 不是一个干净的单一服务词，而是被 `远程部署服务`、`整机/工作站`、`书籍教程` 三条供给线共同占用。",
            "- 如果直接用 `OpenClaw` 做核心标题词，流量会被大量硬件和内容商品稀释，转化效率会差。",
            "- 真正可切入的空位不是 `账号/额度`，也不是 `整机硬件`，而是 `远程安装部署 + 场景接入 + 售后兜底`。",
            f"- 在现有 JD Claude 服务样本里，显性的 `安装/部署/CLI` 竞品只有 `{len(install_df)}` 个，且全部来自同一家店，价格中位数约 `{median_price(install_df):.1f}`。这说明服务型供给不多，但卖得并不低。",
            "- 包装层面，竞品极度依赖通用资源卡，服务表达很弱。只要把交付结果、兼容范围、售后边界讲清，`企巴士` 有明显机会做出区隔。",
            "",
            "## 方法与可观测性",
            "",
            f"- 本地定量样本：`{search_input.name}`，有效 SKU `{len(search_df)}`，唯一店铺 `{search_df['shop_name'].nunique()}`。",
            f"- 详情增强样本：`{detail_input.name}`，对应详情页 `{merged_df['item_id'].nunique()}`。",
            f"- 图片多模态样本：`{ocr_input.name}`，主图样本 `{len(visual_df)}`。",
            "- 外部证据：2026-04-03 通过公开可访问的 JD 索引页，对 `OpenClaw` 相关搜索结果做结构映射；这部分用于判定关键词污染和市场分层，不与本地 59 个 Claude 样本混算。",
            f"- 搜索词清单已落盘：`{term_path.name}`。",
            f"- 外部证据清单已落盘：`{evidence_path.name}`。",
            "",
            "## 本轮搜索词",
            "",
            df_to_markdown(pd.DataFrame(SEARCH_TERMS)),
            "",
            "## OpenClaw 在京东的盘子结构",
            "",
            "- `服务盘`：公开 JD 索引页已经出现 OpenClaw 安装指导、本地部署、远程部署、陪跑等结果，说明市场上存在明确的服务型需求入口。",
            "- `硬件盘`：同一关键词也会命中 ThinkStation、ThinkPad、龙虾主机、DeepSeek/OpenClaw 本地部署整机等结果，说明大量搜索流量会被硬件型商品抢走。",
            "- `内容盘`：还会混入 OpenClaw 书籍/教程类商品，进一步降低词的精度。",
            "- 结论：`OpenClaw` 是低精度大词，不适合作为唯一主标题词；更适合作为副词或长尾词中的功能词。",
            "",
            "## 现有 JD Claude / Code 样本结构",
            "",
            df_to_markdown(segment_summary),
            "",
            "### 头部卖家",
            "",
            df_to_markdown(top_shops),
            "",
            "### 显性安装型竞品",
            "",
            df_to_markdown(install_view if not install_view.empty else pd.DataFrame(columns=["item_id", "title", "shop_name", "price_text"])),
            "",
            "### 安装型竞品的证据强度",
            "",
            f"- 显性安装型竞品数：`{len(install_df)}`",
            f"- 显性安装型店铺数：`{install_df['shop_name'].nunique()}`",
            f"- 显性安装型价格中位数：`{median_price(install_df):.1f}`",
            f"- 这些安装型竞品的评论覆盖：`{nonnull_count(install_reviews['review_count_text'])}/{len(install_reviews)}`",
            f"- 这些安装型竞品的好评率覆盖：`{nonnull_count(install_reviews['good_rate_text'])}/{len(install_reviews)}`",
            f"- 这些安装型竞品的评论样本覆盖：`{nonnull_count(install_reviews['sample_reviews'])}/{len(install_reviews)}`",
            "",
            "这组数据说明：京东里“可代安装”是一个真实存在但证据稀薄的供给位点。卖家能挂高价，但公开可验证的评论证明并不强。",
            "",
            "## 多模态包装分析",
            "",
            f"- 图片总样本：`{len(visual_df)}`",
            f"- 唯一视觉模板数（pHash）：`{visual_df['phash'].nunique()}`",
            f"- 进入重复模板的图片数：`{int(visual_df.loc[visual_df['template_size'] >= 2].shape[0])}` / `{len(visual_df)}`",
            f"- 最大单模板复用规模：`{int(visual_df['template_size'].max())}` 张",
            f"- OCR 与标题完全无关的主图：`{int((visual_df['relevance_overlap'] == 0).sum())}` / `{len(visual_df)}`",
            "",
            df_to_markdown(visual_summary),
            "",
            "### 安装型竞品图片观察",
            "",
            df_to_markdown(install_visual_summary),
            "",
            "- 安装型的 3 个 SKU 使用的是同一套 `200x200` 小图模板，OCR 没有提取出有效服务信息，这意味着它们并没有认真用主图解释交付过程。",
            "- 大盘竞品也在复用通用资源卡，主图高频表达仍然是 `模型矩阵 / 直登 / 自动发货 / 售后保障`，不是 `兼容检查 / 安装步骤 / 交付结果 / 问题兜底`。",
            "- 因此，`企巴士` 如果把主图改成“服务结果卡”，很容易和现有竞品拉开辨识度。",
            "",
            "## 对 企巴士 的经营判断",
            "",
            "- 不要把 `OpenClaw` 当作单一大词硬上架。它会把你的服务和主机、工作站、书籍混在一起。",
            "- 不要把 `账号/额度/API` 当主卖点。现有 JD 样本里，这条线供给更挤，包装也更同质，售后风险更高。",
            "- `企巴士` 的主打法应该是：`远程部署`、`故障排查`、`企业接入`、`交付留档`。",
            "- 你的页面必须显式写清：`不含硬件`、`不含账号转售`、`客户自备账号/API（如需）`、`支持的系统/环境`、`交付边界`、`售后期`。",
            "",
            "## 建议上架的 SKU 梯度",
            "",
            "| SKU | 定位 | 建议价 | 交付内容 |",
            "| --- | --- | --- | --- |",
            "| OpenClaw 环境诊断 | 引流款 | 69-99 | 系统兼容检查、部署建议、风险点清单 |",
            "| OpenClaw 单机远程部署 | 主推款 | 199-299 | Windows/Mac/Linux 安装、基础配置、首轮验证 |",
            "| OpenClaw 场景接入包 | 利润款 | 399-699 | 本地知识库、飞书/协同接入、工作流配置、录屏说明 |",
            "| OpenClaw 团队实施陪跑 | 高客单 | 999-1499 | 需求梳理、多人环境交付、培训录屏、售后答疑 |",
            "",
            "## 建议标题与表达方式",
            "",
            f"- `{store_name} OpenClaw 远程安装部署 Windows/Mac/Linux 一对一交付 不含硬件`",
            f"- `{store_name} OpenClaw 本地部署排障服务 知识库接入/协同配置/录屏交付`",
            f"- `{store_name} OpenClaw 企业实施陪跑 环境诊断+部署+培训答疑`",
            "",
            "主图文案建议只保留四类结果词：`能装上`、`能连通`、`能交付`、`有售后`。",
            "",
            "## 搜索与投放建议",
            "",
            "- 主投长尾词：`OpenClaw 安装`、`OpenClaw 部署`、`OpenClaw 远程部署`、`OpenClaw 本地部署`。",
            "- 场景补充词：`OpenClaw 飞书`、`OpenClaw 知识库`、`OpenClaw 故障排查`。",
            "- 标题里把 `OpenClaw` 放在前半段，但务必同时带上 `远程安装`、`部署`、`排障` 等动作词，提升意图纯度。",
            "- 避免用 `工作站`、`主机`、`笔记本`、`整机` 这类词，以免被硬件盘带偏流量。",
            "",
            "## 局限与下一步",
            "",
            "- 本地量化样本目前来自 `Claude` 种子词，不是完整的 `OpenClaw` 站内全量盘子。",
            "- 2026-04-03 本机 JD 登录态不足以稳定刷新新的站内搜索页，所以 `OpenClaw` 的市场映射采用了公开 JD 索引页做交叉验证。",
            "- 如果下一轮能恢复 JD 搜索登录态，优先补抓上面列出的高意图长尾词，每词只抓前 20-50 个结果，不要再用大词全刷。",
            "",
            "## 来源",
            "",
            "- [JD 索引页：OpenClaw 服务型结果](https://www.jd.com/jiage/12218d0256de18384c47e.html)",
            "- [JD 索引页：OpenClaw 工作站/主机结果](https://www.jd.com/jiage/670081dd1dbd866c026.html)",
            "- [JD 榜单页：OpenClaw 部署远程指导相关整机结果](https://www.jd.com/phb/key_670985eaf438ea993ec.html)",
            "",
        ]
    )


def df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "| empty |\n| --- |\n| no data |"
    frame = df.copy()
    for column in frame.columns:
        frame[column] = frame[column].map(format_cell)
    header = "| " + " | ".join(frame.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    rows = ["| " + " | ".join(str(value) for value in row) + " |" for row in frame.to_numpy()]
    return "\n".join([header, separator, *rows])


def format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value).replace("\n", " / ")


def summarize_visuals(visual_df: pd.DataFrame) -> pd.DataFrame:
    if visual_df.empty:
        return pd.DataFrame(columns=["metric", "value"])
    duplicate_groups = (visual_df["template_size"] >= 2).sum()
    top_template = (
        visual_df.groupby("phash")
        .agg(template_size=("item_id", "count"), shop_count=("shop_name", "nunique"))
        .reset_index()
        .sort_values(["template_size", "shop_count"], ascending=[False, False])
        .head(5)
    )
    top_template["phash"] = top_template["phash"].map(lambda value: value[:12] + "..." if value else "")
    top_template = top_template.rename(columns={"phash": "template_key"})

    overview = pd.DataFrame(
        [
            {"metric": "重复模板图片数", "value": int(duplicate_groups)},
            {"metric": "标题-图片零相关图片数", "value": int((visual_df["relevance_overlap"] == 0).sum())},
            {"metric": "高相关图片数(relevance>=1)", "value": int((visual_df["relevance_overlap"] >= 1).sum())},
            {"metric": "安装型图片数", "value": int(visual_df["is_install_like"].sum())},
        ]
    )
    return pd.concat([overview, top_template], ignore_index=True, sort=False)


def summarize_install_visuals(visual_df: pd.DataFrame) -> pd.DataFrame:
    install_visuals = visual_df[visual_df["is_install_like"]].copy()
    if install_visuals.empty:
        return pd.DataFrame(columns=["item_id", "shop_name", "template_size", "relevance_overlap", "ocr_line_count", "edge_density"])
    cols = ["item_id", "shop_name", "template_size", "relevance_overlap", "ocr_line_count", "edge_density"]
    return install_visuals.loc[:, cols].sort_values(["template_size", "item_id"], ascending=[False, True])


def median_price(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    values = df["price_value"].dropna()
    if values.empty:
        return 0.0
    return float(values.median())


def nonnull_count(series: pd.Series) -> int:
    return int(series.fillna("").astype(str).str.strip().replace("nan", "").ne("").sum())


if __name__ == "__main__":
    main()
