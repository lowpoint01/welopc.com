from __future__ import annotations

import time
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from ..models import ListingRecord
from ..storage import AUTH_DIR
from ..utils import compact_text, ensure_dirs, normalize_numeric, parse_jsonp, regex_first


class AuthenticatedCrawler(ABC):
    platform: str
    login_url: str
    browser_name: str = "webkit"
    browser_channel: str = ""
    viewport = {"width": 1440, "height": 2200}
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

    def __init__(self, auth_dir: Path | None = None, headless: bool = True) -> None:
        self.auth_dir = auth_dir or AUTH_DIR
        ensure_dirs(self.auth_dir)
        self.auth_path = self.auth_dir / f"{self.platform}.json"
        self.profile_dir = self.auth_dir / f"{self.platform}_profile"
        self.headless = headless

    @abstractmethod
    def build_search_url(self, keyword: str, page: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def item_url_pattern(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def shop_url_pattern(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def is_login_page(self, url: str, page_text: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def detect_blocker(self, page_text: str, network_events: list[dict[str, Any]]) -> str:
        raise NotImplementedError

    def redirect_reason(self, url: str, page_text: str) -> str:
        return ""

    @abstractmethod
    def auth_cookie_keywords(self) -> list[str]:
        raise NotImplementedError

    def browser_launch_args(self) -> list[str]:
        return []

    def should_retry(self, blocker: str) -> bool:
        return blocker == "frequent_access"

    def retry_delay_seconds(self) -> int:
        return 20

    def _launch_browser(self, playwright: Playwright) -> Browser:
        launcher = getattr(playwright, self.browser_name)
        kwargs: dict[str, Any] = {"headless": self.headless}
        if self.browser_channel:
            kwargs["channel"] = self.browser_channel
        args = self.browser_launch_args()
        if args:
            kwargs["args"] = args
        return launcher.launch(**kwargs)

    def _new_context(self, browser: Browser) -> BrowserContext:
        kwargs: dict[str, Any] = {
            "viewport": self.viewport,
            "user_agent": self.user_agent,
        }
        if self.auth_path.exists():
            kwargs["storage_state"] = str(self.auth_path)
        return browser.new_context(**kwargs)

    def _launch_persistent_context(self, playwright: Playwright, headless: bool) -> BrowserContext:
        launcher = getattr(playwright, self.browser_name)
        ensure_dirs(self.profile_dir)
        kwargs: dict[str, Any] = {
            "user_data_dir": str(self.profile_dir),
            "headless": headless,
            "viewport": self.viewport,
            "user_agent": self.user_agent,
        }
        if self.browser_channel:
            kwargs["channel"] = self.browser_channel
        args = self.browser_launch_args()
        if args:
            kwargs["args"] = args
        return launcher.launch_persistent_context(**kwargs)

    def _launch_runtime_context(self, playwright: Playwright) -> tuple[BrowserContext, Browser | None]:
        if self.profile_dir.exists():
            return self._launch_persistent_context(playwright, headless=self.headless), None
        browser = self._launch_browser(playwright)
        return self._new_context(browser), browser

    def login(self, timeout_seconds: int = 600) -> Path:
        with sync_playwright() as playwright:
            context = self._launch_persistent_context(playwright, headless=False)
            page = context.new_page()
            page.goto(self.login_url, wait_until="load", timeout=120000)
            print(f"[{self.platform}] browser opened, complete login in the page.")
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                try:
                    current_url = page.url
                    page_text = compact_text(page.locator("body").inner_text(timeout=3000))
                except Exception:
                    continue
                if self._login_ready(context, current_url, page_text):
                    context.storage_state(path=str(self.auth_path))
                    context.close()
                    print(f"[{self.platform}] login detected, state saved.")
                    return self.auth_path
            context.close()
            raise TimeoutError(f"[{self.platform}] login was not detected within {timeout_seconds} seconds.")

    def _login_ready(self, context: BrowserContext, current_url: str, page_text: str) -> bool:
        if self.is_login_page(current_url, page_text):
            return False
        try:
            cookies = context.cookies()
        except Exception:
            return False
        keywords = self.auth_cookie_keywords()
        return any(any(keyword in cookie.get("domain", "") for keyword in keywords) for cookie in cookies)

        return False

    def crawl_keywords(self, keywords: list[str], pages: int = 1) -> tuple[list[ListingRecord], list[dict[str, Any]]]:
        records: list[ListingRecord] = []
        debug_rows: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            context, browser = self._launch_runtime_context(playwright)
            for keyword in keywords:
                for page_no in range(1, pages + 1):
                    url = self.build_search_url(keyword, page_no)
                    page_records: list[ListingRecord] = []
                    page_debug_rows: list[dict[str, Any]] = []

                    for attempt in range(2):
                        page = context.new_page()
                        network_events: list[dict[str, Any]] = []
                        page.on("response", lambda resp: self._capture_response(resp, network_events))
                        try:
                            page.goto(url, wait_until="load", timeout=120000)
                        except Exception as exc:
                            page_debug_rows.append(
                                {
                                    "platform": self.platform,
                                    "keyword": keyword,
                                    "page": page_no,
                                    "event": "goto_error",
                                    "detail": str(exc),
                                    "url": url,
                                }
                            )
                            page.close()
                            break

                        page.wait_for_timeout(6000)
                        self._gentle_scroll(page)
                        page_text = compact_text(page.locator("body").inner_text(timeout=15000))
                        blocker = self.detect_blocker(page_text, network_events)
                        if self.is_login_page(page.url, page_text):
                            blocker = "login_required"
                        redirect_reason = self.redirect_reason(page.url, page_text)
                        if redirect_reason:
                            blocker = redirect_reason

                        if self.should_retry(blocker) and attempt == 0:
                            page_debug_rows.append(
                                {
                                    "platform": self.platform,
                                    "keyword": keyword,
                                    "page": page_no,
                                    "event": "retry",
                                    "detail": blocker,
                                    "url": page.url,
                                }
                            )
                            page.close()
                            time.sleep(self.retry_delay_seconds())
                            continue

                        dom_records = []
                        net_records = []
                        if not redirect_reason:
                            dom_records = self.extract_dom_records(page, keyword, page_no)
                            net_records = self.extract_network_records(network_events, keyword, page_no)
                        page_records = self._merge_records(dom_records + net_records)

                        if not page_records:
                            page_records.append(
                                ListingRecord(
                                    platform=self.platform,
                                    keyword=keyword,
                                    page=page_no,
                                    crawl_status="blocked",
                                    blocker_reason=blocker or "no_relevant_results",
                                    source="probe",
                                    raw={"url": page.url, "page_text": page_text[:2000]},
                                )
                            )

                        page_debug_rows.extend(
                            {
                                "platform": self.platform,
                                "keyword": keyword,
                                "page": page_no,
                                "event": "network",
                                "detail": event["summary"],
                                "url": event["url"],
                            }
                            for event in network_events
                        )
                        page.close()
                        break

                    records.extend(page_records)
                    debug_rows.extend(page_debug_rows)
            context.close()
            if browser is not None:
                browser.close()
        return records, debug_rows

    def _capture_response(self, response: Any, bucket: list[dict[str, Any]]) -> None:
        try:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            text = response.text()
        except Exception:
            return

        bucket.append(
            {
                "url": response.url,
                "status": response.status,
                "summary": compact_text(text[:500]),
                "body": text,
            }
        )

    def _gentle_scroll(self, page: Page) -> None:
        for _ in range(3):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1500)

    def extract_dom_records(self, page: Page, keyword: str, page_no: int) -> list[ListingRecord]:
        script = """
        ([itemPattern, shopPattern]) => {
          const itemRegex = new RegExp(itemPattern, "i");
          const shopRegex = new RegExp(shopPattern, "i");
          const results = [];
          const seen = new Set();
          const anchors = Array.from(document.querySelectorAll("a[href]"));
          for (const anchor of anchors) {
            const href = anchor.href || "";
            if (!itemRegex.test(href)) continue;
            if (seen.has(href)) continue;
            seen.add(href);
            let box = anchor;
            for (let i = 0; i < 5; i += 1) {
              if (!box || !box.parentElement) break;
              const text = (box.innerText || "").replace(/\\s+/g, " ").trim();
              if (text.length >= 24) break;
              box = box.parentElement;
            }
            const text = ((box && box.innerText) || anchor.innerText || "").replace(/\\s+/g, " ").trim();
            const allLinks = box ? Array.from(box.querySelectorAll("a[href]")) : [];
            const matchedShop = allLinks.find((node) => shopRegex.test(node.href || ""));
            results.push({
              item_url: href,
              title: (anchor.innerText || "").replace(/\\s+/g, " ").trim(),
              snippet: text,
              shop_name: matchedShop ? (matchedShop.innerText || "").replace(/\\s+/g, " ").trim() : "",
              shop_url: matchedShop ? matchedShop.href : "",
            });
          }
          return results;
        }
        """
        candidates = page.evaluate(script, [self.item_url_pattern(), self.shop_url_pattern()])
        records: list[ListingRecord] = []
        tokens = self._keyword_tokens(keyword)
        for rank, candidate in enumerate(candidates, start=1):
            snippet = compact_text(candidate.get("snippet"))
            title = compact_text(candidate.get("title")) or self._guess_title_from_text(snippet, keyword)
            if not title:
                continue
            combined_text = f"{title} {snippet}".lower()
            if tokens and not any(token in combined_text for token in tokens):
                continue
            records.append(
                ListingRecord(
                    platform=self.platform,
                    keyword=keyword,
                    page=page_no,
                    rank=rank,
                    title=title,
                    item_url=candidate.get("item_url", ""),
                    shop_name=compact_text(candidate.get("shop_name")),
                    shop_url=candidate.get("shop_url", ""),
                    price_text=regex_first(r"([￥¥]\\s*\\d+(?:\\.\\d+)?)", snippet),
                    sales_text=regex_first(r"((?:已售|销量|评价|付款)[^ ]{0,12})", snippet),
                    location=regex_first(r"(北京|上海|广州|深圳|杭州|苏州|成都|武汉|南京|重庆|天津|西安|长沙|郑州|福建|广东|江苏|浙江|山东)", snippet),
                    source="dom",
                    raw={"snippet": snippet},
                )
            )
        return records

    def extract_network_records(
        self,
        network_events: list[dict[str, Any]],
        keyword: str,
        page_no: int,
    ) -> list[ListingRecord]:
        records: list[ListingRecord] = []
        tokens = self._keyword_tokens(keyword)
        for event in network_events:
            payload = parse_jsonp(event["body"])
            if payload is None:
                continue
            for rank, candidate in enumerate(self._iter_listing_like_dicts(payload), start=1):
                title = compact_text(str(self._first_value(candidate, ["title", "itemTitle", "name", "raw_title"])))
                if not title:
                    continue
                combined_text = " ".join(
                    compact_text(str(self._first_value(candidate, [key])))
                    for key in ["title", "itemTitle", "name", "raw_title", "shopName", "sellerName"]
                ).lower()
                if tokens and not any(token in combined_text for token in tokens):
                    continue
                item_url = self._first_value(candidate, ["itemUrl", "item_url", "url", "clickUrl", "detailUrl"])
                if item_url and not re.search(self.item_url_pattern(), str(item_url), re.I):
                    item_url = ""
                shop_name = compact_text(str(self._first_value(candidate, ["shopName", "sellerName", "nick", "storeName"])))
                shop_url = self._first_value(candidate, ["shopUrl", "sellerUrl", "storeUrl"])
                price = self._first_value(candidate, ["price", "priceText", "promotionPrice", "salePrice"])
                sales = self._first_value(candidate, ["sales", "salesText", "dealCnt", "soldText", "commentCount"])
                if not item_url and keyword.lower() not in title.lower():
                    continue
                records.append(
                    ListingRecord(
                        platform=self.platform,
                        keyword=keyword,
                        page=page_no,
                        rank=rank,
                        title=title,
                        item_url=str(item_url or ""),
                        shop_name=shop_name,
                        shop_url=str(shop_url or ""),
                        price_text=str(price or ""),
                        sales_text=str(sales or ""),
                        source="network",
                        raw=candidate,
                    )
                )
        return records

    def _iter_listing_like_dicts(self, node: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def walk(current: Any) -> None:
            if isinstance(current, dict):
                keys = {str(key) for key in current.keys()}
                if {"title", "price"} <= keys or {"name", "price"} <= keys:
                    found.append(current)
                elif {"title", "itemId"} <= keys or {"name", "itemId"} <= keys:
                    found.append(current)
                for value in current.values():
                    walk(value)
            elif isinstance(current, list):
                for item in current:
                    walk(item)

        walk(node)
        return found

    def _guess_title_from_text(self, snippet: str, keyword: str) -> str:
        parts = [part.strip() for part in snippet.split(" ") if part.strip()]
        if not parts:
            return ""
        if keyword.lower() in parts[0].lower():
            return parts[0]
        return " ".join(parts[:6])

    def _first_value(self, data: dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            if key in data and data[key] not in ("", None):
                return data[key]
        return ""

    def _merge_records(self, records: list[ListingRecord]) -> list[ListingRecord]:
        merged: list[ListingRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for record in records:
            fingerprint = (record.keyword, record.item_id or record.item_url, record.title)
            if fingerprint in seen:
                continue
            if record.source == "network" and not record.item_url and not normalize_numeric(record.price_text or ""):
                continue
            seen.add(fingerprint)
            merged.append(record)
        return merged

    def _keyword_tokens(self, keyword: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", keyword.lower())
        return [token for token in tokens if len(token) >= 2]

    def encode_keyword(self, keyword: str) -> str:
        return quote_plus(keyword)
