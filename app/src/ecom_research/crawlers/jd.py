from __future__ import annotations

from bs4 import BeautifulSoup

from .base import AuthenticatedCrawler
from ..models import ListingRecord
from ..utils import compact_text


class JDCrawler(AuthenticatedCrawler):
    platform = "jd"
    login_url = "https://passport.jd.com/new/login.aspx"
    browser_name = "chromium"
    browser_channel = "msedge"

    def build_search_url(self, keyword: str, page: int) -> str:
        return f"https://search.jd.com/Search?keyword={self.encode_keyword(keyword)}&page={page * 2 - 1}"

    def item_url_pattern(self) -> str:
        return r"item\.jd\.com/\d+\.html"

    def shop_url_pattern(self) -> str:
        return r"(mall\.jd\.com|shop\.jd\.com)"

    def is_login_page(self, url: str, page_text: str) -> bool:
        return "passport.jd.com" in url or "个人用户登录" in page_text

    def redirect_reason(self, url: str, page_text: str) -> str:
        if self.is_login_page(url, page_text):
            return ""
        if "search.jd.com/Search" not in url:
            return "redirected_home"
        return ""

    def auth_cookie_keywords(self) -> list[str]:
        return ["jd.com", "3.cn"]

    def browser_launch_args(self) -> list[str]:
        return ["--no-proxy-server", "--proxy-bypass-list=*"]

    def extract_dom_records(self, page, keyword: str, page_no: int) -> list[ListingRecord]:
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("[data-sku]")
        tokens = self._keyword_tokens(keyword)
        records: list[ListingRecord] = []

        for rank, card in enumerate(cards, start=1):
            sku = compact_text(card.get("data-sku", ""))
            if not sku:
                continue

            title_node = card.select_one("[title]")
            title = compact_text(title_node.get("title", "") if title_node else "")
            if not title:
                title = compact_text(card.get_text(" ", strip=True))
            if not title:
                continue

            combined = compact_text(card.get_text(" ", strip=True)).lower()
            if tokens and not any(token in combined for token in tokens):
                continue

            price = ""
            price_node = card.select_one("[class*='price']")
            if price_node:
                price = compact_text(price_node.get_text("", strip=True)).replace("¥", "")
                if price:
                    price = f"¥{price}"

            sales_text = ""
            shop_name = ""
            for span in card.select("span"):
                text = compact_text(span.get_text(" ", strip=True))
                if not sales_text and text.startswith("已售"):
                    sales_text = text
                if not shop_name and text.endswith("小店"):
                    shop_name = text

            if not shop_name:
                shop_node = card.select_one("[class*='name']")
                if shop_node:
                    shop_name = compact_text(shop_node.get_text(" ", strip=True))

            records.append(
                ListingRecord(
                    platform=self.platform,
                    keyword=keyword,
                    title=title,
                    item_url=f"https://item.jd.com/{sku}.html",
                    item_id=sku,
                    shop_name=shop_name,
                    price_text=price,
                    sales_text=sales_text,
                    page=page_no,
                    rank=rank,
                    source="dom_html",
                    raw={"snippet": compact_text(card.get_text(" ", strip=True))[:1500]},
                )
            )
        return records

    def detect_blocker(self, page_text: str, network_events: list[dict]) -> str:
        if "欢迎登录" in page_text or "个人用户登录" in page_text:
            return "login_required"
        if "访问频繁导致无法搜索" in page_text:
            return "frequent_access"
        if "验证" in page_text and "安全" in page_text:
            return "risk_control"
        if not network_events and "京东" in page_text and "搜索" not in page_text:
            return "redirected_home"
        return ""
