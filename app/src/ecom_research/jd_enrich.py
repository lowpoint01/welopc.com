from __future__ import annotations

import base64
import json
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .analysis import build_category_summary, build_keyword_summary, cluster_titles, enrich_records
from .crawlers.jd import JDCrawler
from .reporting import render_markdown, write_report
from .storage import ENRICHED_DIR, IMAGE_DIR, REPORT_DIR, write_jsonl, write_tabular
from .utils import compact_text, ensure_dirs, normalize_numeric, now_stamp, parse_jsonp, regex_first, safe_slug


ITEM_URL_RE = re.compile(r"https?://item\.jd\.com/(\d+)\.html", re.I)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")
NAV_LINE_BLACKLIST = {
    "京东首页",
    "中国大陆版",
    "购物车",
    "我的订单",
    "我的京东",
    "企业采购",
    "网站导航",
    "手机京东",
    "网站无障碍",
    "关注店铺",
    "联系客服",
    "搜本店",
    "搜全站",
    "规格参数",
    "店铺",
    "商品详情",
    "售后保障",
    "推荐",
    "全部评价",
    "问大家",
    "我要提问",
    "达人选购",
    "立即购买",
    "加入购物车",
    "首页",
    "我的",
    "反馈",
    "回顶部",
    "收起",
    "收藏",
    "降价通知",
    "服务",
    "送至",
    "支持7天无理由退货",
}
REVIEW_STOP_MARKERS = {
    "全部评价",
    "问大家",
    "我要提问",
    "为你推荐",
    "达人选购",
    "商品详情",
    "售后保障",
}
RELEVANCE_HINTS = [
    "claude",
    "chat",
    "gpt",
    "grok",
    "cursor",
    "api",
    "token",
    "midjourney",
    "gemini",
    "copilot",
    "ai",
    "订阅",
    "会员",
    "代充",
    "共享",
    "独享",
    "中转",
    "直连",
    "满血",
    "企业",
    "安装",
    "部署",
]
TITLE_KEYS = ("t", "title", "skuName", "name", "ad_title", "copyText", "skuTitle")
PRICE_KEYS = ("jp", "price", "priceText", "salePrice", "promotionPrice")
IMAGE_KEYS = ("img", "image", "picture", "pic", "cover")
COMMENT_KEYS = ("comment_num", "commentNum", "commentCount", "comments", "comment")
SHOP_KEYS = ("seller", "shopName", "storeName", "venderName", "merchantName")


def enrich_jd_dataset(
    input_path: Path,
    *,
    headless: bool = True,
    limit: int | None = None,
    expand_limit: int = 40,
    download_images: bool = False,
    max_images_per_item: int = 4,
    delay_seconds: float = 2.0,
) -> dict[str, Any]:
    seed_df = load_seed_frame(input_path, limit=limit)
    stamp = now_stamp()
    crawler = JDCrawler(headless=headless)
    partial_paths = _partial_output_paths(stamp)

    detail_rows: list[dict[str, Any]] = []
    detail_debug_rows: list[dict[str, Any]] = []
    recommendation_rows: list[dict[str, Any]] = []
    visited_ids: set[str] = set()
    consecutive_blocked_items = 0

    print(
        f"[jd-enrich] start seed_items={len(seed_df)} expand_limit={expand_limit} "
        f"download_images={download_images} partial={partial_paths['detail_csv']}",
        flush=True,
    )

    with sync_playwright() as playwright:
        context, browser = crawler._launch_runtime_context(playwright)
        try:
            for index, row in enumerate(seed_df.to_dict(orient="records"), start=1):
                detail_row, rec_rows, debug_rows = visit_item_detail(
                    context,
                    row=row,
                    origin="seed",
                    download_images=download_images,
                    max_images_per_item=max_images_per_item,
                )
                detail_rows.append(detail_row)
                recommendation_rows.extend(rec_rows)
                detail_debug_rows.extend(debug_rows)
                item_id = compact_text(str(detail_row.get("item_id", "")))
                if item_id:
                    visited_ids.add(item_id)
                if detail_row.get("blocker_reason"):
                    consecutive_blocked_items += 1
                else:
                    consecutive_blocked_items = 0
                print(
                    f"[jd-enrich] seed {index}/{len(seed_df)} item={item_id or row.get('item_id', '')} "
                    f"status={detail_row.get('blocker_reason', detail_row.get('crawl_status', ''))} "
                    f"reviews={detail_row.get('review_count_text', '')} "
                    f"images={detail_row.get('downloaded_image_count', 0)} recs={len(rec_rows)}",
                    flush=True,
                )
                _write_partial_outputs(
                    detail_rows=detail_rows,
                    recommendation_rows=recommendation_rows,
                    debug_rows=detail_debug_rows,
                    partial_paths=partial_paths,
                )
                if consecutive_blocked_items >= 2:
                    print("[jd-enrich] stop early due to repeated blocked detail pages", flush=True)
                    break
                _delay_between_items(delay_seconds)

            candidate_df = build_recommendation_candidates(recommendation_rows, visited_ids=visited_ids)
            if expand_limit > 0 and not candidate_df.empty:
                expand_rows = candidate_df.head(expand_limit).to_dict(orient="records")
                for index, row in enumerate(expand_rows, start=1):
                    detail_row, rec_rows, debug_rows = visit_item_detail(
                        context,
                        row=row,
                        origin="recommended",
                        download_images=download_images,
                        max_images_per_item=max_images_per_item,
                    )
                    detail_rows.append(detail_row)
                    recommendation_rows.extend(rec_rows)
                    detail_debug_rows.extend(debug_rows)
                    item_id = compact_text(str(detail_row.get("item_id", "")))
                    if item_id:
                        visited_ids.add(item_id)
                    if detail_row.get("blocker_reason"):
                        consecutive_blocked_items += 1
                    else:
                        consecutive_blocked_items = 0
                    print(
                        f"[jd-enrich] expand {index}/{len(expand_rows)} item={item_id or row.get('item_id', '')} "
                        f"status={detail_row.get('blocker_reason', detail_row.get('crawl_status', ''))} "
                        f"reviews={detail_row.get('review_count_text', '')} "
                        f"images={detail_row.get('downloaded_image_count', 0)} recs={len(rec_rows)}",
                        flush=True,
                    )
                    _write_partial_outputs(
                        detail_rows=detail_rows,
                        recommendation_rows=recommendation_rows,
                        debug_rows=detail_debug_rows,
                        partial_paths=partial_paths,
                    )
                    if consecutive_blocked_items >= 2:
                        print("[jd-enrich] stop early due to repeated blocked detail pages", flush=True)
                        break
                    _delay_between_items(delay_seconds)
        finally:
            context.close()
            if browser is not None:
                browser.close()

    detail_df = pd.DataFrame(detail_rows)
    detail_df = detail_df.drop_duplicates(subset=["item_id", "item_url"], keep="first")
    recommendation_df = pd.DataFrame(recommendation_rows)
    if not recommendation_df.empty:
        recommendation_df = recommendation_df.drop_duplicates(
            subset=["source_item_id", "channel", "item_id", "item_url"], keep="first"
        )
    candidate_df = build_recommendation_candidates(
        recommendation_df.to_dict(orient="records") if not recommendation_df.empty else [],
        visited_ids=set(),
    )

    detail_base = ENRICHED_DIR / f"jd_detail_{stamp}"
    detail_csv, detail_xlsx = write_tabular(detail_df, detail_base)
    detail_debug_path = ENRICHED_DIR / f"jd_detail_debug_{stamp}.jsonl"
    write_jsonl(detail_debug_rows, detail_debug_path)

    recommendation_csv = recommendation_xlsx = None
    if not recommendation_df.empty:
        recommendation_csv, recommendation_xlsx = write_tabular(
            recommendation_df,
            ENRICHED_DIR / f"jd_recommendations_{stamp}",
        )

    candidate_csv = candidate_xlsx = None
    if not candidate_df.empty:
        candidate_csv, candidate_xlsx = write_tabular(
            candidate_df,
            ENRICHED_DIR / f"jd_recommendation_candidates_{stamp}",
        )

    detail_report_path = REPORT_DIR / f"jd_detail_report_{stamp}.md"
    write_report(_render_detail_summary(detail_df, recommendation_df, candidate_df), detail_report_path)

    market_report_path = REPORT_DIR / f"market_report_jd_detail_{stamp}.md"
    if not detail_df.empty:
        enriched = enrich_records(detail_df.copy())
        category_df = build_category_summary(enriched)
        keyword_df = build_keyword_summary(enriched)
        cluster_df = cluster_titles(enriched)
        write_report(render_markdown(enriched, category_df, keyword_df, cluster_df), market_report_path)

    return {
        "detail_csv": detail_csv,
        "detail_xlsx": detail_xlsx,
        "detail_debug_jsonl": detail_debug_path,
        "recommendation_csv": recommendation_csv,
        "recommendation_xlsx": recommendation_xlsx,
        "candidate_csv": candidate_csv,
        "candidate_xlsx": candidate_xlsx,
        "detail_report": detail_report_path,
        "market_report": market_report_path,
        "seed_count": len(seed_df),
        "detail_count": len(detail_df),
        "recommendation_count": len(recommendation_df),
        "candidate_count": len(candidate_df),
        "downloaded_image_count": int(detail_df.get("downloaded_image_count", pd.Series(dtype=float)).fillna(0).sum())
        if not detail_df.empty
        else 0,
        "partial_detail_csv": partial_paths["detail_csv"],
        "partial_recommendation_csv": partial_paths["recommendation_csv"],
        "partial_debug_jsonl": partial_paths["debug_jsonl"],
    }


def load_seed_frame(input_path: Path, *, limit: int | None = None) -> pd.DataFrame:
    frame = pd.read_csv(input_path)
    if frame.empty:
        raise ValueError(f"No rows found in {input_path}")

    frame = frame.copy()
    frame["platform"] = frame.get("platform", "").fillna("").astype(str).str.lower()
    frame = frame[frame["platform"] == "jd"]
    frame["crawl_status"] = frame.get("crawl_status", "ok").fillna("ok").astype(str)
    frame = frame[frame["crawl_status"] == "ok"]
    frame["item_url"] = frame.get("item_url", "").fillna("").astype(str)
    frame["item_id"] = frame.get("item_id", "").fillna("").astype(str)
    frame["title"] = frame.get("title", "").fillna("").astype(str)
    frame["shop_name"] = frame.get("shop_name", "").fillna("").astype(str)
    frame = frame[frame["item_url"].str.contains(r"item\.jd\.com/\d+\.html", case=False, regex=True)]
    frame = frame.drop_duplicates(subset=["item_id", "item_url"], keep="first")
    frame = frame.sort_values(["keyword", "page", "rank"], ascending=[True, True, True], na_position="last")
    if limit:
        frame = frame.head(limit)
    if frame.empty:
        raise ValueError(f"No JD item rows available in {input_path}")
    return frame.reset_index(drop=True)


def visit_item_detail(
    context: BrowserContext,
    *,
    row: dict[str, Any],
    origin: str,
    download_images: bool,
    max_images_per_item: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    page = context.new_page()
    debug_rows: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {"mixer": [], "diviner": []}

    def on_response(response: Any) -> None:
        try:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            body = response.text()
        except Exception:
            return

        payload = parse_jsonp(body)
        if payload is None:
            return

        url = response.url
        if "pc_detailpage_wareBusiness" in url:
            payloads["ware"] = payload
        elif "getLegoWareDetailComment" in url:
            payloads["comment"] = payload
        elif "pc_item_getWareGraphic" in url:
            payloads["graphic"] = payload
        elif "pctradesoa_mixer" in url:
            payloads["mixer"].append(payload)
        elif "pctradesoa_diviner" in url:
            payloads["diviner"].append(payload)

    page.on("response", on_response)
    item_url = compact_text(str(row.get("item_url", "")))
    load_error = ""
    final_url = item_url
    body_text = ""
    html = ""
    page_title = ""

    try:
        nav_failed = False
        try:
            page.goto(item_url, wait_until="load", timeout=90000)
        except Exception as exc:
            load_error = str(exc)
            nav_failed = True
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        try:
            page.wait_for_selector("body", timeout=30000)
        except Exception:
            pass

        page.wait_for_timeout(7000)
        try:
            page.mouse.wheel(0, 1600)
        except Exception:
            pass
        page.wait_for_timeout(3500)

        final_url = page.url
        for _ in range(3):
            try:
                body_text = page.locator("body").inner_text(timeout=15000)
            except Exception as exc:
                if not load_error:
                    load_error = str(exc)
                page.wait_for_timeout(3000)
                continue
            if compact_text(body_text):
                break
            page.wait_for_timeout(3000)

        if nav_failed and not compact_text(body_text):
            try:
                page.goto(item_url, wait_until="commit", timeout=30000)
                page.wait_for_timeout(8000)
            except Exception:
                pass
            final_url = page.url
            for _ in range(2):
                try:
                    body_text = page.locator("body").inner_text(timeout=15000)
                except Exception:
                    page.wait_for_timeout(3000)
                    continue
                if compact_text(body_text):
                    break
                page.wait_for_timeout(3000)
        if compact_text(body_text) and load_error.startswith("Page.goto: Timeout"):
            load_error = ""
        try:
            html = page.content()
        except Exception:
            html = ""
        try:
            page_title = page.title()
        except Exception:
            page_title = ""
    finally:
        debug_rows.append(
            {
                "event": "visit",
                "item_url": item_url,
                "item_id": row.get("item_id", ""),
                "origin": origin,
                "final_url": final_url,
                "load_error": load_error,
            }
        )

    detail_row = build_detail_row(
        row=row,
        origin=origin,
        final_url=final_url,
        body_text=body_text,
        html=html,
        page_title=page_title,
        payloads=payloads,
        page=page,
        load_error=load_error,
        download_images=download_images,
        max_images_per_item=max_images_per_item,
    )
    recommendation_rows = extract_recommendation_rows(payloads, source_row=detail_row)
    page.close()
    return detail_row, recommendation_rows, debug_rows


def build_detail_row(
    *,
    row: dict[str, Any],
    origin: str,
    final_url: str,
    body_text: str,
    html: str,
    page_title: str,
    payloads: dict[str, Any],
    page: Page,
    load_error: str,
    download_images: bool,
    max_images_per_item: int,
) -> dict[str, Any]:
    lines = [compact_text(line) for line in body_text.splitlines() if compact_text(line)]
    soup = BeautifulSoup(html, "lxml") if html else BeautifulSoup("", "lxml")
    title = first_non_empty(
        _extract_title_from_meta(soup),
        _clean_jd_title(page_title),
        compact_text(str(row.get("title", ""))),
    )
    item_id = first_non_empty(
        compact_text(str(row.get("item_id", ""))),
        extract_item_id(final_url),
        extract_item_id(compact_text(str(row.get("item_url", "")))),
    )

    ware_payload = payloads.get("ware") if isinstance(payloads.get("ware"), dict) else {}
    comment_payload = payloads.get("comment") if isinstance(payloads.get("comment"), dict) else {}
    graphic_payload = payloads.get("graphic") if isinstance(payloads.get("graphic"), dict) else {}

    attribute_pairs = extract_attribute_pairs(ware_payload)
    shop_name = first_non_empty(
        compact_text(str(row.get("shop_name", ""))),
        extract_store_name_from_attrs(attribute_pairs),
        _extract_shop_name_from_lines(lines),
    )
    shop_url = first_non_empty(
        compact_text(str(row.get("shop_url", ""))),
        extract_store_url_from_attrs(ware_payload),
    )
    shop_id = first_non_empty(compact_text(str(row.get("shop_id", ""))), extract_shop_id(shop_url))

    price_text = first_non_empty(
        _extract_price_from_dom(body_text, title),
        compact_text(str(row.get("price_text", ""))),
    )
    sales_text = first_non_empty(
        compact_text(str(row.get("sales_text", ""))),
        regex_first(r"(已售[0-9.+万kK]+)", body_text),
    )
    review_count_text = first_non_empty(
        compact_text(str(comment_payload.get("allCntStr", ""))),
        regex_first(r"累计评价\s*([0-9.+万kK]+)", body_text),
        regex_first(r"买家评价\(([^)]+)\)", body_text),
    )
    good_rate_text = first_non_empty(
        normalize_percent_text(compact_text(str(comment_payload.get("goodRateShow", "")))),
        normalize_percent_text(compact_text(str(comment_payload.get("goodRate", "")))),
        normalize_percent_text(regex_first(r"好评率(?:高达)?\s*([0-9.]+%?)", body_text)),
    )
    comment_samples = extract_comment_texts(comment_payload)
    if not comment_samples:
        comment_samples = extract_reviews_from_lines(lines)

    main_image_urls = select_image_urls(_extract_dom_image_candidates(page), limit=max(max_images_per_item, 4))
    detail_image_urls = extract_graphic_image_urls(graphic_payload)
    image_urls = unique_list(main_image_urls + detail_image_urls)[: max(max_images_per_item * 2, 6)]
    blocker_reason = _detect_detail_blocker(final_url, body_text, title)
    login_required = blocker_reason == "login_required"
    downloaded_images = (
        download_image_set(item_id=item_id or safe_slug(title), image_urls=image_urls[:max_images_per_item])
        if download_images and not blocker_reason
        else []
    )

    return {
        "platform": "jd",
        "keyword": compact_text(str(row.get("keyword", ""))),
        "title": title,
        "item_url": first_non_empty(final_url, compact_text(str(row.get("item_url", "")))),
        "item_id": item_id,
        "shop_name": shop_name,
        "shop_url": shop_url,
        "shop_id": shop_id,
        "price_text": price_text,
        "sales_text": sales_text,
        "page": row.get("page", 1),
        "rank": row.get("rank", 0),
        "crawl_status": "blocked" if blocker_reason else ("ok" if title and item_id else "partial"),
        "blocker_reason": blocker_reason,
        "source": compact_text(str(row.get("source", ""))) or origin,
        "origin": origin,
        "origin_keyword": compact_text(str(row.get("keyword", ""))),
        "origin_item_id": compact_text(str(row.get("origin_item_id", ""))),
        "origin_item_ids": compact_text(str(row.get("origin_item_ids", ""))),
        "recommendation_channels": compact_text(str(row.get("recommendation_channels", ""))),
        "recommended_by_count": row.get("recommended_by_count", 0),
        "recommended_occurrences": row.get("recommended_occurrences", 0),
        "relevance_score": row.get("relevance_score", 0),
        "category_path": " > ".join(extract_breadcrumbs(soup, lines, shop_name)),
        "shop_score": _extract_shop_score(lines, shop_name),
        "review_count_text": review_count_text,
        "review_count_value": normalize_numeric(review_count_text),
        "good_rate_text": good_rate_text,
        "good_rate_value": percent_to_float(good_rate_text),
        "comment_good_count": normalize_numeric(compact_text(str(comment_payload.get("goodCnt", "")))),
        "comment_picture_count": normalize_numeric(
            compact_text(str(comment_payload.get("showPicCnt", "")))
            or compact_text(str(comment_payload.get("pictureCnt", "")))
        ),
        "sample_reviews": " | ".join(comment_samples[:3]),
        "default_good_text": decode_maybe_base64(compact_text(str(comment_payload.get("defaultGoodCountText", "")))),
        "service_text": _extract_service_text(lines),
        "delivery_text": _extract_delivery_text(lines),
        "main_image_urls": json.dumps(main_image_urls, ensure_ascii=False),
        "detail_image_urls": json.dumps(detail_image_urls, ensure_ascii=False),
        "downloaded_images": json.dumps(downloaded_images, ensure_ascii=False),
        "downloaded_image_count": len(downloaded_images),
        "attribute_pairs": json.dumps(attribute_pairs, ensure_ascii=False),
        "body_excerpt": compact_text(body_text)[:2000],
        "load_error": load_error,
        "raw": json.dumps(
            {
                "origin_title": compact_text(str(row.get("title", ""))),
                "origin_shop_name": compact_text(str(row.get("shop_name", ""))),
                "final_url": final_url,
            },
            ensure_ascii=False,
        ),
    }


def extract_recommendation_rows(payloads: dict[str, Any], *, source_row: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for channel in ("mixer", "diviner"):
        for payload in payloads.get(channel, []):
            rows.extend(extract_recommendation_records(payload, channel=channel, source_row=source_row))
    return rows


def extract_recommendation_records(
    payload: dict[str, Any] | list[Any],
    *,
    channel: str,
    source_row: dict[str, Any],
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    source_item_id = compact_text(str(source_row.get("item_id", "")))

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            url_value = first_non_empty(
                compact_text(str(node.get("target_url", ""))),
                compact_text(str(node.get("item_url", ""))),
                compact_text(str(node.get("url", ""))),
                compact_text(str(node.get("link", ""))),
            )
            item_url = normalize_item_url(url_value)
            item_id = extract_item_id(item_url)
            title = compact_text(str(first_existing(node, TITLE_KEYS)))
            if item_id and item_url and item_id != source_item_id:
                found.append(
                    {
                        "source_item_id": source_item_id,
                        "source_title": compact_text(str(source_row.get("title", ""))),
                        "source_keyword": compact_text(str(source_row.get("keyword", ""))),
                        "source_origin": compact_text(str(source_row.get("origin", ""))),
                        "channel": channel,
                        "item_id": item_id,
                        "item_url": item_url,
                        "title": title,
                        "price_text": compact_text(str(first_existing(node, PRICE_KEYS))),
                        "comment_text": compact_text(str(first_existing(node, COMMENT_KEYS))),
                        "shop_name": compact_text(str(first_existing(node, SHOP_KEYS))),
                        "image_url": normalize_image_url(compact_text(str(first_existing(node, IMAGE_KEYS)))),
                        "relevance_score": relevance_score(title),
                    }
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in found:
        fingerprint = (row["source_item_id"], row["channel"], row["item_id"])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(row)
    return deduped


def build_recommendation_candidates(
    rows: list[dict[str, Any]],
    *,
    visited_ids: set[str],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "item_id",
                "item_url",
                "title",
                "price_text",
                "comment_text",
                "shop_name",
                "image_url",
                "recommended_by_count",
                "recommended_occurrences",
                "recommendation_channels",
                "origin_item_ids",
                "origin_keywords",
                "relevance_score",
            ]
        )

    frame = pd.DataFrame(rows)
    frame["item_id"] = frame.get("item_id", "").fillna("").astype(str)
    frame["item_url"] = frame.get("item_url", "").fillna("").astype(str)
    frame["title"] = frame.get("title", "").fillna("").astype(str)
    frame = frame[~frame["item_id"].isin(visited_ids)]
    frame = frame.drop_duplicates(subset=["source_item_id", "channel", "item_id"], keep="first")
    if frame.empty:
        return pd.DataFrame(columns=["item_id", "item_url"])

    aggregated = (
        frame.groupby(["item_id", "item_url"], dropna=False)
        .agg(
            title=("title", first_non_empty_from_series),
            price_text=("price_text", first_non_empty_from_series),
            comment_text=("comment_text", first_non_empty_from_series),
            shop_name=("shop_name", first_non_empty_from_series),
            image_url=("image_url", first_non_empty_from_series),
            recommended_by_count=("source_item_id", lambda values: values.replace("", pd.NA).dropna().nunique()),
            recommended_occurrences=("source_item_id", "count"),
            recommendation_channels=("channel", lambda values: " | ".join(sorted({value for value in values if value}))),
            origin_item_ids=("source_item_id", lambda values: " | ".join(sorted({value for value in values if value}))),
            origin_keywords=("source_keyword", lambda values: " | ".join(sorted({value for value in values if value}))),
            relevance_score=("relevance_score", "max"),
        )
        .reset_index()
    )
    aggregated = aggregated.sort_values(
        ["relevance_score", "recommended_by_count", "recommended_occurrences", "item_id"],
        ascending=[False, False, False, True],
    )
    return aggregated.reset_index(drop=True)


def extract_attribute_pairs(payload: dict[str, Any]) -> list[str]:
    attributes = payload.get("productAttributeVO", {}).get("attributes", []) if isinstance(payload, dict) else []
    pairs: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = compact_text(str(attribute.get("labelName", "")))
        value = compact_text(str(attribute.get("labelValue", "")))
        if label and value:
            pairs.append(f"{label}:{value}")
    return pairs


def extract_store_name_from_attrs(pairs: list[str]) -> str:
    for pair in pairs:
        if pair.startswith("店铺:"):
            return compact_text(pair.split(":", 1)[1])
    return ""


def extract_store_url_from_attrs(payload: dict[str, Any]) -> str:
    attributes = payload.get("productAttributeVO", {}).get("attributes", []) if isinstance(payload, dict) else []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        url = compact_text(str(attribute.get("jumpUrl", "")))
        if "mall.jd.com" in url or "shop.jd.com" in url:
            if url.startswith("//"):
                return f"https:{url}"
            if url.startswith("http"):
                return url
            return f"https://{url.lstrip('/')}"
    return ""


def extract_shop_id(shop_url: str) -> str:
    if not shop_url:
        return ""
    match = re.search(r"index-(\d+)\.html", shop_url, re.I)
    return match.group(1) if match else ""


def extract_comment_texts(payload: dict[str, Any] | list[Any]) -> list[str]:
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            content = compact_text(
                str(
                    node.get("content")
                    or node.get("commentData")
                    or node.get("commentContent")
                    or node.get("comment")
                    or ""
                )
            )
            if len(content) >= 6:
                nickname = compact_text(str(node.get("nickname") or node.get("userName") or node.get("nickName") or ""))
                texts.append(f"{nickname}:{content}" if nickname else content)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return unique_list(texts)


def select_image_urls(candidates: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        urls = [
            normalize_image_url(compact_text(str(candidate.get("src", "")))),
            normalize_image_url(compact_text(str(candidate.get("dataOrigin", "")))),
            normalize_image_url(compact_text(str(candidate.get("dataLazyload", "")))),
        ]
        url = first_non_empty(*urls)
        if not url or url in seen:
            continue
        seen.add(url)
        score = 0
        lower_url = url.lower()
        class_name = compact_text(str(candidate.get("className", ""))).lower()
        alt_text = compact_text(str(candidate.get("alt", ""))).lower()
        width = int(candidate.get("width") or 0)
        height = int(candidate.get("height") or 0)

        if "storage.360buyimg.com/i.imageupload/" in lower_url:
            score += 8
        if "/n1/" in lower_url or "/n0/" in lower_url:
            score += 6
        if "/jfs/" in lower_url:
            score += 3
        if "spec" in class_name or "preview" in class_name or "zoom" in class_name:
            score += 4
        if "商品" in alt_text or "sku" in alt_text or "主图" in alt_text:
            score += 2
        if width >= 180 and height >= 180:
            score += 2
        if any(token in lower_url for token in ("imagetools", "pcpubliccms", "babel", "default.image")):
            score -= 10
        if score <= 0:
            continue
        ranked.append((score, url))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, url in ranked[:limit]]


def extract_graphic_image_urls(payload: dict[str, Any]) -> list[str]:
    graphic_html = compact_text(str(payload.get("data", {}).get("graphicContent", ""))) if isinstance(payload, dict) else ""
    if not graphic_html:
        return []
    soup = BeautifulSoup(graphic_html, "lxml")
    urls = []
    for image in soup.select("img"):
        url = normalize_image_url(
            compact_text(str(image.get("data-lazyload", "")))
            or compact_text(str(image.get("src", "")))
            or compact_text(str(image.get("data-origin", "")))
        )
        if url:
            urls.append(url)
    return unique_list(urls)


def extract_breadcrumbs(soup: BeautifulSoup, lines: list[str], shop_name: str) -> list[str]:
    breadcrumbs: list[str] = []
    selectors = [
        "#crumb-wrap a",
        ".crumb a",
        ".p-parameter ul li a",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = compact_text(node.get_text(" ", strip=True))
            if not text or text in NAV_LINE_BLACKLIST:
                continue
            if len(text) > 24:
                continue
            breadcrumbs.append(text)
    breadcrumbs = unique_list(breadcrumbs)
    if breadcrumbs:
        return breadcrumbs[:4]

    inferred: list[str] = []
    for line in lines[:40]:
        if line == shop_name:
            break
        if line in NAV_LINE_BLACKLIST or line == ">":
            continue
        if len(line) > 18:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", line):
            continue
        if any(token in line for token in ("京东", "购物", "网站", "手机", "订单", "服务", "优惠")):
            continue
        inferred.append(line)
    return unique_list(inferred)[:4]


def extract_reviews_from_lines(lines: list[str]) -> list[str]:
    start = -1
    for index, line in enumerate(lines):
        if "买家评价" in line or "好评率" in line:
            start = index
            break
    if start < 0:
        return []

    reviews: list[str] = []
    for line in lines[start + 1 :]:
        if line in REVIEW_STOP_MARKERS:
            break
        if len(line) < 6:
            continue
        if re.fullmatch(r"[A-Za-z0-9*]+", line):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "买家评价" in line or "好评率" in line:
            continue
        reviews.append(line)
    return unique_list(reviews)


def normalize_item_url(value: str) -> str:
    if not value:
        return ""
    content = value.strip()
    if content.startswith("//"):
        content = f"https:{content}"
    elif content.startswith("item.jd.com/"):
        content = f"https://{content}"
    elif content.startswith("/"):
        content = f"https://item.jd.com{content}"
    match = ITEM_URL_RE.search(content)
    if not match:
        return ""
    return f"https://item.jd.com/{match.group(1)}.html"


def extract_item_id(url: str) -> str:
    match = ITEM_URL_RE.search(url or "")
    return match.group(1) if match else ""


def normalize_image_url(value: str) -> str:
    if not value:
        return ""
    content = value.strip()
    if content.startswith("//"):
        content = f"https:{content}"
    elif content.startswith("/"):
        content = f"https://item.jd.com{content}"
    return content


def relevance_score(title: str) -> int:
    content = compact_text(title).lower()
    if not content:
        return 0
    return sum(1 for hint in RELEVANCE_HINTS if hint in content)


def normalize_percent_text(value: str) -> str:
    content = compact_text(value)
    if not content:
        return ""
    if content.endswith("%"):
        return content
    match = PERCENT_RE.search(content)
    if match:
        return f"{match.group(1)}%"
    if re.fullmatch(r"\d+(?:\.\d+)?", content):
        return f"{content}%"
    return content


def percent_to_float(value: str) -> float | None:
    if not value:
        return None
    match = PERCENT_RE.search(value if value.endswith("%") else f"{value}%")
    if not match:
        return None
    return float(match.group(1))


def decode_maybe_base64(value: str) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return value


def download_image_set(*, item_id: str, image_urls: list[str]) -> list[str]:
    if not image_urls:
        return []
    item_dir = IMAGE_DIR / "jd" / safe_slug(item_id)
    ensure_dirs(item_dir)
    saved_paths: list[str] = []
    for index, image_url in enumerate(image_urls, start=1):
        try:
            suffix = _guess_image_suffix(image_url)
            output_path = item_dir / f"{index:02d}{suffix}"
            request = Request(image_url, headers={"User-Agent": JDCrawler.user_agent})
            with urlopen(request, timeout=30) as response:
                content = response.read()
            output_path.write_bytes(content)
            saved_paths.append(str(output_path))
        except Exception:
            continue
    return saved_paths


def first_existing(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in ("", None):
            return value
    return ""


def first_non_empty(*values: Any) -> str:
    for value in values:
        content = compact_text(str(value))
        if content and content.lower() != "nan":
            return content
    return ""


def first_non_empty_from_series(values: pd.Series) -> str:
    for value in values:
        content = compact_text(str(value))
        if content and content.lower() != "nan":
            return content
    return ""


def unique_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        content = compact_text(value)
        if not content or content in seen:
            continue
        seen.add(content)
        result.append(content)
    return result


def _delay_between_items(delay_seconds: float) -> None:
    if delay_seconds <= 0:
        return
    time.sleep(max(0.0, delay_seconds + random.uniform(0.2, 1.1)))


def _extract_title_from_meta(soup: BeautifulSoup) -> str:
    selectors = [
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "keywords"}),
    ]
    for name, attrs in selectors:
        node = soup.find(name, attrs=attrs)
        if not node:
            continue
        content = compact_text(str(node.get("content", "")))
        if content:
            return _clean_jd_title(content)
    return ""


def _clean_jd_title(value: str) -> str:
    content = compact_text(value)
    if not content:
        return ""
    content = re.sub(r"【[^】]*】-京东$", "", content)
    content = re.sub(r"-京东$", "", content)
    return compact_text(content)


def _extract_shop_name_from_lines(lines: list[str]) -> str:
    for index, line in enumerate(lines[:40]):
        if line in NAV_LINE_BLACKLIST or len(line) > 20:
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if re.fullmatch(r"\d+(?:\.\d+)?", next_line):
            return line
    return ""


def _extract_shop_score(lines: list[str], shop_name: str) -> str:
    if not shop_name:
        return ""
    for index, line in enumerate(lines):
        if line != shop_name:
            continue
        for candidate in lines[index + 1 : index + 5]:
            if re.fullmatch(r"\d+(?:\.\d+)?", candidate):
                return candidate
    return ""


def _extract_price_from_dom(body_text: str, title: str) -> str:
    if not body_text:
        return ""
    content = body_text
    if title and title in body_text:
        start = body_text.find(title)
        content = body_text[start : start + 400]
    match = re.search(r"¥\s*([0-9]+(?:\.[0-9]+)?)", content)
    return f"¥{match.group(1)}" if match else ""


def _extract_service_text(lines: list[str]) -> str:
    return _line_window(lines, marker="服务", limit=4)


def _extract_delivery_text(lines: list[str]) -> str:
    return _line_window(lines, marker="送至", limit=5)


def _line_window(lines: list[str], *, marker: str, limit: int) -> str:
    for index, line in enumerate(lines):
        if line != marker:
            continue
        values: list[str] = []
        for candidate in lines[index + 1 : index + 1 + limit]:
            if candidate in NAV_LINE_BLACKLIST or candidate in REVIEW_STOP_MARKERS:
                break
            values.append(candidate)
        return " | ".join(values)
    return ""


def _extract_dom_image_candidates(page: Page) -> list[dict[str, Any]]:
    script = """
    () => Array.from(document.querySelectorAll("img")).map((img) => ({
      src: img.currentSrc || img.src || "",
      dataOrigin: img.getAttribute("data-origin") || "",
      dataLazyload: img.getAttribute("data-lazyload") || "",
      alt: img.alt || "",
      className: img.className || "",
      width: img.naturalWidth || img.width || 0,
      height: img.naturalHeight || img.height || 0,
    }))
    """
    try:
        result = page.evaluate(script)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _guess_image_suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    suffix = Path(path).suffix
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}:
        return suffix
    return ".jpg"


def _detect_detail_blocker(final_url: str, body_text: str, title: str) -> str:
    text = compact_text(body_text)
    page_title = compact_text(title)
    if (
        "passport.jd.com" in final_url
        or "欢迎登录" in page_title
        or "登录页面" in text
        or "个人用户登录" in text
        or "扫码安全登录" in text
    ):
        return "login_required"
    if final_url.startswith("chrome-error://") or "ERR_" in text or "This site can’t be reached" in text:
        return "page_error"
    return ""


def _render_detail_summary(
    detail_df: pd.DataFrame,
    recommendation_df: pd.DataFrame,
    candidate_df: pd.DataFrame,
) -> str:
    detail_count = len(detail_df)
    review_coverage = int(detail_df.get("review_count_text", pd.Series(dtype=str)).fillna("").astype(str).ne("").sum())
    good_rate_coverage = int(detail_df.get("good_rate_text", pd.Series(dtype=str)).fillna("").astype(str).ne("").sum())
    downloaded_images = int(detail_df.get("downloaded_image_count", pd.Series(dtype=float)).fillna(0).sum())

    lines = [
        "# JD Detail Enrichment Report",
        "",
        f"- visited_items: {detail_count}",
        f"- recommendation_rows: {len(recommendation_df)}",
        f"- recommendation_candidates: {len(candidate_df)}",
        f"- review_coverage: {review_coverage}",
        f"- good_rate_coverage: {good_rate_coverage}",
        f"- downloaded_images: {downloaded_images}",
        "",
        "## Top Candidates",
        "",
        _markdown_table(
            candidate_df.head(20),
            [
                "item_id",
                "title",
                "price_text",
                "recommended_by_count",
                "recommended_occurrences",
                "relevance_score",
            ],
        ),
        "",
        "## Detail Coverage",
        "",
        _markdown_table(
            detail_df.head(20),
            [
                "item_id",
                "title",
                "shop_name",
                "price_text",
                "review_count_text",
                "good_rate_text",
                "origin",
            ],
        ),
    ]
    return "\n".join(lines)


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "_no data_"
    headers = [column for column in columns if column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in frame.loc[:, headers].iterrows():
        values = [compact_text(str(row[column])).replace("|", "/") for column in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _partial_output_paths(stamp: str) -> dict[str, Path]:
    return {
        "detail_csv": ENRICHED_DIR / f"jd_detail_{stamp}_partial.csv",
        "recommendation_csv": ENRICHED_DIR / f"jd_recommendations_{stamp}_partial.csv",
        "debug_jsonl": ENRICHED_DIR / f"jd_detail_debug_{stamp}_partial.jsonl",
    }


def _write_partial_outputs(
    *,
    detail_rows: list[dict[str, Any]],
    recommendation_rows: list[dict[str, Any]],
    debug_rows: list[dict[str, Any]],
    partial_paths: dict[str, Path],
) -> None:
    detail_df = pd.DataFrame(detail_rows)
    if not detail_df.empty:
        detail_df = detail_df.drop_duplicates(subset=["item_id", "item_url"], keep="first")
        detail_df.to_csv(partial_paths["detail_csv"], index=False, encoding="utf-8-sig")

    recommendation_df = pd.DataFrame(recommendation_rows)
    if not recommendation_df.empty:
        recommendation_df = recommendation_df.drop_duplicates(
            subset=["source_item_id", "channel", "item_id", "item_url"],
            keep="first",
        )
        recommendation_df.to_csv(partial_paths["recommendation_csv"], index=False, encoding="utf-8-sig")

    write_jsonl(debug_rows, partial_paths["debug_jsonl"])
