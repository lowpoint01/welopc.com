from __future__ import annotations

from .base import AuthenticatedCrawler


class TaobaoCrawler(AuthenticatedCrawler):
    platform = "taobao"
    login_url = "https://login.taobao.com/member/login.jhtml"
    browser_name = "webkit"

    def build_search_url(self, keyword: str, page: int) -> str:
        return f"https://s.taobao.com/search?q={self.encode_keyword(keyword)}&s={(page - 1) * 44}"

    def item_url_pattern(self) -> str:
        return r"(item\.taobao\.com/item\.htm|detail\.tmall\.com/item\.htm)"

    def shop_url_pattern(self) -> str:
        return r"(shop\d*\.taobao\.com|store\.taobao\.com|tmall\.com)"

    def is_login_page(self, url: str, page_text: str) -> bool:
        return "login.taobao.com" in url or "亲，请登录" in page_text

    def redirect_reason(self, url: str, page_text: str) -> str:
        if "s.taobao.com/search" not in url:
            return "unexpected_redirect"
        return ""

    def auth_cookie_keywords(self) -> list[str]:
        return ["taobao.com", "tmall.com"]

    def detect_blocker(self, page_text: str, network_events: list[dict]) -> str:
        lowered = page_text.lower()
        if "deny_h5" in lowered or "punish/deny" in lowered or '"rgv587_flag":"sm"' in lowered:
            return "risk_control"
        if "加载中" in page_text and "所有宝贝" in page_text:
            for event in network_events:
                if "非法请求" in event["summary"] or "令牌为空" in event["summary"]:
                    return "risk_control"
        if "被挤爆啦" in lowered or "非法请求" in lowered:
            return "risk_control"
        if "搜索" in page_text and "加载中" in page_text:
            return "skeleton_only"
        return ""
