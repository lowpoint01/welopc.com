from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .storage import AUTH_DIR, ENRICHED_DIR, RAW_DIR, REPORT_DIR, write_jsonl, write_tabular
from .utils import compact_text, ensure_dirs, now_stamp


DEFAULT_SOCIAL_KEYWORDS = [
    "企业AI咨询",
    "企业AI智能体",
    "企业AI应用",
    "AI知识库",
    "AI客服",
    "AI培训",
    "AI私域获客",
    "DeepSeek 企业",
    "Claude 企业",
]

TOKEN_STOP_WORDS = {
    "企业",
    "公司",
    "一个",
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "就是",
    "如果",
    "因为",
    "怎么",
    "什么",
    "可以",
    "需要",
    "已经",
    "还是",
    "真的",
    "非常",
    "觉得",
    "进行",
    "以及",
    "然后",
    "客户",
    "老板",
    "团队",
    "场景",
    "功能",
    "使用",
    "问题",
    "时候",
    "现在",
    "服务",
    "产品",
    "智能体",
    "应用",
    "企业ai",
    "ai",
}

THEME_RULES = {
    "deployment": ["安装", "部署", "接入", "配置", "环境", "本地", "接口", "API", "连通"],
    "knowledge_base": ["知识库", "文档", "资料", "问答", "检索", "RAG", "手册"],
    "customer_service": ["客服", "私信", "线索", "留资", "转化", "销售", "获客", "咨询"],
    "training": ["培训", "陪跑", "咨询", "课程", "上手", "落地", "方法论", "团队"],
    "content": ["内容", "文案", "脚本", "素材", "短视频", "笔记", "矩阵", "爆款"],
    "governance": ["安全", "权限", "合规", "数据", "风控", "稳定", "售后", "治理"],
}


@dataclass(frozen=True)
class SocialPlatform:
    name: str
    display_name: str
    login_url: str
    search_url_template: str
    item_url_patterns: tuple[str, ...]
    network_url_patterns: tuple[str, ...]
    cookie_domains: tuple[str, ...]
    blocked_markers: tuple[str, ...]
    login_markers: tuple[str, ...]

    def search_url(self, keyword: str) -> str:
        return self.search_url_template.format(keyword=quote(keyword))


PLATFORMS: dict[str, SocialPlatform] = {
    "xhs": SocialPlatform(
        name="xhs",
        display_name="小红书",
        login_url="https://www.xiaohongshu.com",
        search_url_template="https://www.xiaohongshu.com/search_result?keyword={keyword}",
        item_url_patterns=(r"xiaohongshu\.com/(?:explore|discovery/item)/",),
        network_url_patterns=(r"https://www\.xiaohongshu\.com/(?:explore|discovery/item)/[A-Za-z0-9]+",),
        cookie_domains=("xiaohongshu.com",),
        blocked_markers=("安全限制", "IP存在风险", "error_code=300012"),
        login_markers=("登录", "手机号登录", "验证码"),
    ),
    "douyin": SocialPlatform(
        name="douyin",
        display_name="抖音",
        login_url="https://www.douyin.com",
        search_url_template="https://www.douyin.com/search/{keyword}?aid=6&type=general",
        item_url_patterns=(r"douyin\.com/(?:video|note)/",),
        network_url_patterns=(r"https://www\.douyin\.com/(?:video|note)/\d+",),
        cookie_domains=("douyin.com", "snssdk.com", "bytedance.com"),
        blocked_markers=("验证码中间页", "验证中", "请完成下列验证后继续", "captcha"),
        login_markers=("登录后即可点赞喜欢评论", "扫码登录", "手机号登录"),
    ),
}

PLATFORM_ALIASES = {
    "xiaohongshu": "xhs",
    "redbook": "xhs",
    "douyin": "douyin",
}


def login_social(platform: str, timeout_seconds: int = 900) -> Path:
    spec = resolve_platform(platform)
    with sync_playwright() as playwright:
        context, browser = open_direct_social_session(playwright, spec, headless=False)
        page = context.new_page()
        page.goto(spec.login_url, wait_until="load", timeout=120000)
        print(f"[social:{spec.name}] browser opened, complete login and clear any captcha/interstitial.")
        deadline = time.time() + timeout_seconds
        state_path = AUTH_DIR / f"{spec.name}_social.json"
        while time.time() < deadline:
            page.wait_for_timeout(2500)
            try:
                body_text = safe_body_text(page)
                cookies = context.cookies()
                context.storage_state(path=str(state_path))
            except Exception:
                continue
            if login_ready(spec, page.url, body_text, cookies):
                context.storage_state(path=str(state_path))
                context.close()
                if browser is not None:
                    browser.close()
                print(f"[social:{spec.name}] login detected, state saved.")
                return state_path
        context.storage_state(path=str(state_path))
        context.close()
        if browser is not None:
            browser.close()
        raise TimeoutError(f"[social:{spec.name}] login was not detected within {timeout_seconds} seconds.")


def crawl_social(
    *,
    platform: str,
    keywords: list[str],
    per_keyword_limit: int = 8,
    max_comments: int = 20,
    headless: bool = False,
) -> dict[str, Path]:
    spec = resolve_platform(platform)
    stamp = now_stamp()
    posts: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    debug_rows: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        context, browser = open_direct_social_session(playwright, spec, headless=headless)
        for keyword in keywords:
            search_page = context.new_page()
            search_events: list[dict[str, Any]] = []
            search_page.on("response", lambda resp: capture_response(resp, search_events))
            search_url = spec.search_url(keyword)

            try:
                search_page.goto(search_url, wait_until="load", timeout=120000)
                wait_for_page_settle(search_page)
            except Exception as exc:
                debug_rows.append(
                    {
                        "platform": spec.name,
                        "keyword": keyword,
                        "stage": "search_goto_error",
                        "url": search_url,
                        "detail": str(exc),
                    }
                )
                search_page.close()
                continue

            body_text = safe_body_text(search_page)
            candidates: list[dict[str, str]] = []
            blocked = current_page_block(spec, search_page)
            if not blocked:
                blocked = detect_network_block(spec, search_events)
            if blocked and not headless:
                print(f"[social:{spec.name}] blocked on search for '{keyword}', waiting for manual recovery.")
                manual_candidates = wait_for_manual_results(spec, search_page, keyword, timeout_seconds=300)
                if manual_candidates:
                    blocked = ""
                    candidates = manual_candidates
                elif wait_for_manual_clear(spec, search_page, timeout_seconds=30):
                    body_text = safe_body_text(search_page)
                    blocked = current_page_block(spec, search_page)
                    if not blocked:
                        blocked = detect_network_block(spec, search_events)
            if not blocked:
                if not candidates:
                    candidates = extract_search_candidates(search_page, spec, keyword)
                if not candidates and not headless:
                    print(f"[social:{spec.name}] no candidates yet for '{keyword}', waiting for manual page stabilization.")
                    search_page.wait_for_timeout(15000)
                    candidates = extract_search_candidates(search_page, spec, keyword)
                if not candidates:
                    candidates = extract_candidate_urls_from_network(search_events, spec)

            if blocked:
                debug_rows.append(
                    {
                        "platform": spec.name,
                        "keyword": keyword,
                        "stage": "search_blocked",
                        "url": search_page.url,
                        "detail": blocked,
                    }
                )
            elif not candidates:
                debug_rows.append(
                    {
                        "platform": spec.name,
                        "keyword": keyword,
                        "stage": "search_empty",
                        "url": search_page.url,
                        "detail": body_text[:500],
                    }
                )

            for rank, candidate in enumerate(candidates[: max(per_keyword_limit, 1)], start=1):
                detail_page = context.new_page()
                detail_events: list[dict[str, Any]] = []
                detail_page.on("response", lambda resp: capture_response(resp, detail_events))
                try:
                    detail_page.goto(candidate["post_url"], wait_until="load", timeout=120000)
                    wait_for_page_settle(detail_page, extra_scroll_rounds=6)
                    detail_body = safe_body_text(detail_page)
                except Exception as exc:
                    debug_rows.append(
                        {
                            "platform": spec.name,
                            "keyword": keyword,
                            "stage": "detail_goto_error",
                            "url": candidate["post_url"],
                            "detail": str(exc),
                        }
                    )
                    detail_page.close()
                    continue

                detail_blocked = current_page_block(spec, detail_page)
                if not detail_blocked:
                    detail_blocked = detect_network_block(spec, detail_events)
                if detail_blocked and not headless:
                    print(f"[social:{spec.name}] blocked on detail page, waiting for manual recovery: {candidate['post_url']}")
                    if wait_for_manual_clear(spec, detail_page, timeout_seconds=180):
                        detail_body = safe_body_text(detail_page)
                        detail_blocked = current_page_block(spec, detail_page)
                        if not detail_blocked:
                            detail_blocked = detect_network_block(spec, detail_events)
                if detail_blocked:
                    debug_rows.append(
                        {
                            "platform": spec.name,
                            "keyword": keyword,
                            "stage": "detail_blocked",
                            "url": detail_page.url,
                            "detail": detail_blocked,
                        }
                    )
                    detail_page.close()
                    continue

                meta = extract_detail_meta(detail_page)
                post_row = {
                    "platform": spec.name,
                    "keyword": keyword,
                    "rank": rank,
                    "post_url": candidate["post_url"],
                    "search_title": candidate.get("title", ""),
                    "search_snippet": candidate.get("snippet", ""),
                    "title": meta["title"] or candidate.get("title", ""),
                    "author": meta["author"],
                    "description": meta["description"],
                    "body_excerpt": compact_text(detail_body[:1200]),
                    "page_title": meta["page_title"],
                    "comments_collected": 0,
                }

                comment_rows = extract_comments_from_network(detail_events, spec.name, keyword, candidate["post_url"], max_comments)
                if not comment_rows:
                    comment_rows = extract_comments_from_dom(detail_page, spec.name, keyword, candidate["post_url"], max_comments)

                deduped_comments = dedupe_comments(comment_rows)
                post_row["comments_collected"] = len(deduped_comments)
                posts.append(post_row)
                comments.extend(deduped_comments)
                detail_page.close()

            debug_rows.extend(
                {
                    "platform": spec.name,
                    "keyword": keyword,
                    "stage": "search_network",
                    "url": event["url"],
                    "detail": event["summary"],
                }
                for event in search_events
            )
            search_page.close()

        context.close()
        if browser is not None:
            browser.close()

    posts_df = pd.DataFrame(posts)
    comments_df = pd.DataFrame(comments)
    debug_path = RAW_DIR / f"{spec.name}_social_debug_{stamp}.jsonl"
    posts_base = ENRICHED_DIR / f"{spec.name}_social_posts_{stamp}"
    comments_base = ENRICHED_DIR / f"{spec.name}_social_comments_{stamp}"
    report_path = REPORT_DIR / f"{spec.name}_social_report_{stamp}.md"

    write_jsonl(debug_rows, debug_path)
    posts_csv, posts_xlsx = write_tabular(posts_df, posts_base)
    comments_csv, comments_xlsx = write_tabular(comments_df, comments_base)
    report_path.write_text(render_social_report(posts_df, comments_df, [spec.name]), encoding="utf-8")

    return {
        "debug_jsonl": debug_path,
        "posts_csv": posts_csv,
        "posts_xlsx": posts_xlsx,
        "comments_csv": comments_csv,
        "comments_xlsx": comments_xlsx,
        "report_md": report_path,
    }


def crawl_social_urls(
    *,
    platform: str,
    post_urls: list[str],
    keyword: str = "直链样本",
    max_comments: int = 20,
    headless: bool = False,
) -> dict[str, Path]:
    spec = resolve_platform(platform)
    stamp = now_stamp()
    posts: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    debug_rows: list[dict[str, Any]] = []

    unique_urls = [compact_text(url) for url in post_urls if compact_text(url)]
    seen_urls: set[str] = set()
    normalized_urls: list[str] = []
    for url in unique_urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        normalized_urls.append(url)

    with sync_playwright() as playwright:
        context, browser = open_direct_social_session(playwright, spec, headless=headless)
        for rank, post_url in enumerate(normalized_urls, start=1):
            detail_page = context.new_page()
            detail_events: list[dict[str, Any]] = []
            detail_page.on("response", lambda resp: capture_response(resp, detail_events))
            try:
                detail_page.goto(post_url, wait_until="load", timeout=120000)
                wait_for_page_settle(detail_page, extra_scroll_rounds=6)
                detail_body = safe_body_text(detail_page)
            except Exception as exc:
                debug_rows.append(
                    {
                        "platform": spec.name,
                        "keyword": keyword,
                        "stage": "detail_goto_error",
                        "url": post_url,
                        "detail": str(exc),
                    }
                )
                detail_page.close()
                continue

            detail_blocked = current_page_block(spec, detail_page)
            if not detail_blocked:
                detail_blocked = detect_network_block(spec, detail_events)
            if detail_blocked and not headless:
                print(f"[social:{spec.name}] blocked on detail page, waiting for manual recovery: {post_url}")
                if wait_for_manual_clear(spec, detail_page, timeout_seconds=180):
                    detail_body = safe_body_text(detail_page)
                    detail_blocked = current_page_block(spec, detail_page)
                    if not detail_blocked:
                        detail_blocked = detect_network_block(spec, detail_events)
            if detail_blocked:
                debug_rows.append(
                    {
                        "platform": spec.name,
                        "keyword": keyword,
                        "stage": "detail_blocked",
                        "url": detail_page.url,
                        "detail": detail_blocked,
                    }
                )

            meta = extract_detail_meta(detail_page)
            post_row = {
                "platform": spec.name,
                "keyword": keyword,
                "rank": rank,
                "post_url": post_url,
                "search_title": "",
                "search_snippet": "",
                "title": meta["title"],
                "author": meta["author"],
                "description": meta["description"],
                "body_excerpt": compact_text(detail_body[:1200]),
                "page_title": meta["page_title"],
                "comments_collected": 0,
                "blocked": detail_blocked,
            }

            comment_rows = extract_comments_from_network(detail_events, spec.name, keyword, post_url, max_comments)
            if not comment_rows:
                comment_rows = extract_comments_from_dom(detail_page, spec.name, keyword, post_url, max_comments)

            deduped_comments = dedupe_comments(comment_rows)
            post_row["comments_collected"] = len(deduped_comments)
            posts.append(post_row)
            comments.extend(deduped_comments)
            debug_rows.extend(
                {
                    "platform": spec.name,
                    "keyword": keyword,
                    "stage": "detail_network",
                    "url": event["url"],
                    "detail": event["summary"],
                }
                for event in detail_events
            )
            detail_page.close()

        context.close()
        if browser is not None:
            browser.close()

    posts_df = pd.DataFrame(posts)
    comments_df = pd.DataFrame(comments)
    debug_path = RAW_DIR / f"{spec.name}_social_direct_debug_{stamp}.jsonl"
    posts_base = ENRICHED_DIR / f"{spec.name}_social_direct_posts_{stamp}"
    comments_base = ENRICHED_DIR / f"{spec.name}_social_direct_comments_{stamp}"
    report_path = REPORT_DIR / f"{spec.name}_social_direct_report_{stamp}.md"

    write_jsonl(debug_rows, debug_path)
    posts_csv, posts_xlsx = write_tabular(posts_df, posts_base)
    comments_csv, comments_xlsx = write_tabular(comments_df, comments_base)
    report_path.write_text(render_social_report(posts_df, comments_df, [spec.name]), encoding="utf-8")

    return {
        "debug_jsonl": debug_path,
        "posts_csv": posts_csv,
        "posts_xlsx": posts_xlsx,
        "comments_csv": comments_csv,
        "comments_xlsx": comments_xlsx,
        "report_md": report_path,
    }


def build_social_report(platforms: list[str], output: Path | None = None) -> Path:
    canonical = [resolve_platform(platform).name for platform in platforms] if platforms else list(PLATFORMS)
    posts_frames: list[pd.DataFrame] = []
    comments_frames: list[pd.DataFrame] = []

    for platform in canonical:
        post_path = latest_output_any(
            ENRICHED_DIR,
            [f"{platform}_social_posts_*.csv", f"{platform}_social_direct_posts_*.csv"],
        )
        comment_path = latest_output_any(
            ENRICHED_DIR,
            [f"{platform}_social_comments_*.csv", f"{platform}_social_direct_comments_*.csv"],
        )
        if post_path is not None:
            post_df = safe_read_csv(post_path)
            if post_df is not None:
                posts_frames.append(post_df)
        if comment_path is not None:
            comment_df = safe_read_csv(comment_path)
            if comment_df is not None:
                comments_frames.append(comment_df)

    posts_df = pd.concat(posts_frames, ignore_index=True) if posts_frames else pd.DataFrame()
    comments_df = pd.concat(comments_frames, ignore_index=True) if comments_frames else pd.DataFrame()
    report = render_social_report(posts_df, comments_df, canonical)
    report_path = output or REPORT_DIR / f"social_cross_platform_report_{now_stamp()}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


def resolve_platform(platform: str) -> SocialPlatform:
    key = PLATFORM_ALIASES.get(platform.lower(), platform.lower())
    if key not in PLATFORMS:
        raise KeyError(f"Unsupported social platform: {platform}")
    return PLATFORMS[key]


def open_local_profile_context(
    playwright: Playwright,
    spec: SocialPlatform,
    headless: bool,
    profile_name: str = "Default",
) -> BrowserContext:
    user_data_dir = resolve_local_browser_user_data_dir("msedge")
    launch_args: list[str] = []
    if user_data_dir is None:
        ensure_dirs(AUTH_DIR)
        user_data_dir = AUTH_DIR / f"{spec.name}_social_profile"
    else:
        # Chromium expects the "User Data" root here; the concrete profile must
        # be selected via --profile-directory, otherwise it silently behaves like
        # a fresh profile and we never inherit the user's real login state.
        launch_args.append(f"--profile-directory={profile_name}")
    launcher = playwright.chromium
    context = launcher.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=headless,
        channel="msedge",
        viewport={"width": 1440, "height": 2400},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        args=launch_args,
    )
    apply_stealth(context)
    return context


def open_direct_social_session(
    playwright: Playwright,
    spec: SocialPlatform,
    headless: bool,
) -> tuple[BrowserContext, Browser | None]:
    storage_state = load_saved_social_state(spec) or export_local_storage_state(playwright, spec)
    browser = playwright.chromium.launch(
        headless=headless,
        channel="msedge",
        ignore_default_args=["--enable-automation"],
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-proxy-server",
            "--proxy-server=direct://",
            "--proxy-bypass-list=*",
        ],
    )
    context_kwargs: dict[str, Any] = {
        "viewport": {"width": 1440, "height": 2400},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    if storage_state:
        context_kwargs["storage_state"] = storage_state
    context = browser.new_context(**context_kwargs)
    apply_stealth(context)
    return context, browser


def resolve_local_browser_user_data_dir(browser: str) -> Path | None:
    browser_key = browser.lower()
    if browser_key == "msedge":
        candidate = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data"
    elif browser_key == "chrome":
        candidate = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
    else:
        return None
    return candidate if candidate.exists() else None


def export_local_storage_state(playwright: Playwright, spec: SocialPlatform) -> dict[str, Any] | None:
    try:
        context = open_local_profile_context(playwright, spec, headless=True)
    except Exception:
        return None
    try:
        return context.storage_state()
    except Exception:
        return None
    finally:
        context.close()


def load_saved_social_state(spec: SocialPlatform) -> dict[str, Any] | None:
    state_path = AUTH_DIR / f"{spec.name}_social.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def apply_stealth(context: BrowserContext) -> None:
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = window.chrome || { runtime: {} };
        """
    )


def login_ready(spec: SocialPlatform, url: str, body_text: str, cookies: list[dict[str, Any]]) -> bool:
    if detect_blocked_reason(spec, url, body_text):
        return False
    domain_cookies = [
        cookie for cookie in cookies if any(domain in cookie.get("domain", "") for domain in spec.cookie_domains)
    ]
    if len(domain_cookies) < 3:
        return False
    lowered = body_text.lower()
    if any(marker.lower() in lowered for marker in spec.login_markers) and "退出" not in body_text:
        return False
    return True


def detect_blocked_reason(spec: SocialPlatform, url: str, body_text: str) -> str:
    content = f"{url} {body_text}".lower()
    for marker in spec.blocked_markers:
        if marker.lower() in content:
            return marker
    return ""


def detect_network_block(spec: SocialPlatform, events: list[dict[str, Any]]) -> str:
    urls = " ".join(event["url"].lower() for event in events)
    bodies = " ".join(event["summary"].lower() for event in events)
    if spec.name == "douyin" and any(token in urls for token in ["verify.snssdk.com", "captcha/get", "verify.zijieapi.com"]):
        return "captcha_network"
    if spec.name == "xhs" and '"guest":true' in bodies:
        return "login_required"
    return ""


def current_page_block(spec: SocialPlatform, page: Page) -> str:
    title = safe_page_title(page)
    body = safe_body_text(page)
    reason = detect_blocked_reason(spec, f"{page.url} {title}", body)
    if reason:
        return reason
    if spec.name == "douyin" and ("验证码中间页" in title or ("/search/" in page.url and not body.strip())):
        return "captcha_page"
    if spec.name == "xhs" and "登录后查看搜索结果" in body:
        return "login_required"
    return ""


def capture_response(response: Any, bucket: list[dict[str, Any]]) -> None:
    try:
        if response.request.resource_type not in {"xhr", "fetch"}:
            return
        content_type = (response.headers.get("content-type") or "").lower()
        if "json" not in content_type and "text" not in content_type and "javascript" not in content_type:
            return
        body = response.text()
    except Exception:
        return

    bucket.append(
        {
            "url": response.url,
            "status": response.status,
            "summary": compact_text(body[:500]),
            "body": body[:300000],
        }
    )


def wait_for_page_settle(page: Page, extra_scroll_rounds: int = 4) -> None:
    page.wait_for_timeout(4000)
    for _ in range(extra_scroll_rounds):
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(1500)


def wait_for_manual_clear(spec: SocialPlatform, page: Page, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if not current_page_block(spec, page):
            return True
    return False


def wait_for_manual_results(spec: SocialPlatform, page: Page, keyword: str, timeout_seconds: int) -> list[dict[str, str]]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if current_page_block(spec, page):
            continue
        candidates = extract_search_candidates(page, spec, keyword)
        if candidates:
            return candidates
    return []


def safe_body_text(page: Page) -> str:
    try:
        return compact_text(page.locator("body").inner_text(timeout=8000))
    except Exception:
        return ""


def safe_page_title(page: Page) -> str:
    try:
        return compact_text(page.title())
    except Exception:
        return ""


def extract_search_candidates(page: Page, spec: SocialPlatform, keyword: str) -> list[dict[str, str]]:
    script = """
    (patterns) => {
      const regexes = patterns.map((pattern) => new RegExp(pattern, "i"));
      const rows = [];
      const seen = new Set();
      for (const anchor of Array.from(document.querySelectorAll("a[href]"))) {
        const href = anchor.href || "";
        if (!regexes.some((regex) => regex.test(href))) continue;
        if (seen.has(href)) continue;
        seen.add(href);
        let box = anchor;
        for (let i = 0; i < 5; i += 1) {
          if (!box || !box.parentElement) break;
          const text = (box.innerText || "").replace(/\\s+/g, " ").trim();
          if (text.length >= 18) break;
          box = box.parentElement;
        }
        const title = (anchor.innerText || "").replace(/\\s+/g, " ").trim();
        const snippet = ((box && box.innerText) || title).replace(/\\s+/g, " ").trim();
        rows.push({ post_url: href, title, snippet });
      }
      return rows;
    }
    """
    raw_rows = page.evaluate(script, list(spec.item_url_patterns))
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    tokens = keyword_tokens(keyword)
    for row in raw_rows:
        post_url = compact_text(str(row.get("post_url")))
        if not post_url or post_url in seen:
            continue
        title = compact_text(str(row.get("title")))
        snippet = compact_text(str(row.get("snippet")))
        combined = f"{title} {snippet}".lower()
        if tokens and not any(token in combined for token in tokens):
            continue
        seen.add(post_url)
        results.append({"post_url": post_url, "title": title or guess_title(snippet), "snippet": snippet})
    return results


def extract_candidate_urls_from_network(events: list[dict[str, Any]], spec: SocialPlatform) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for event in events:
        content = event["body"].replace("\\/", "/")
        for pattern in spec.network_url_patterns:
            for match in re.finditer(pattern, content):
                post_url = match.group(0)
                if post_url in seen:
                    continue
                seen.add(post_url)
                results.append({"post_url": post_url, "title": "", "snippet": ""})
    return results


def extract_detail_meta(page: Page) -> dict[str, str]:
    script = """
    () => {
      const read = (selectors) => {
        for (const selector of selectors) {
          const node = document.querySelector(selector);
          if (!node) continue;
          const value = (node.content || node.innerText || "").replace(/\\s+/g, " ").trim();
          if (value) return value;
        }
        return "";
      };
      const mainNode = document.querySelector("main") || document.querySelector("article") || document.body;
      const mainText = (mainNode && mainNode.innerText ? mainNode.innerText : "").replace(/\\s+/g, " ").trim();
      return {
        page_title: document.title || "",
        title: read(["h1", "meta[property='og:title']", "meta[name='og:title']"]),
        description: read(["meta[name='description']", "meta[property='og:description']", "article"]),
        author: read([
          "meta[name='author']",
          "a[href*='/user/profile/']",
          "a[data-e2e*='user-name']",
          "[class*='author']",
          "[class*='user']",
        ]),
        main_text: mainText,
      };
    }
    """
    payload = page.evaluate(script)
    return {
        "page_title": compact_text(str(payload.get("page_title", ""))),
        "title": normalize_title(payload.get("title", ""), payload.get("page_title", "")),
        "description": compact_text(str(payload.get("description", "")))[:500],
        "author": compact_text(str(payload.get("author", "")))[:80],
        "main_text": compact_text(str(payload.get("main_text", ""))),
    }


def extract_comments_from_network(
    events: list[dict[str, Any]],
    platform: str,
    keyword: str,
    post_url: str,
    max_comments: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    prioritized = [event for event in events if "comment" in event["url"].lower() or "reply" in event["url"].lower()]
    sources = prioritized or events

    for event in sources:
        payload = parse_payload(event["body"])
        if payload is None:
            continue
        for item in iter_comment_like_dicts(payload, event["url"]):
            author = extract_author(item)
            content = compact_text(str(first_value(item, ["content", "text", "comment_text", "comment", "desc"])))
            if len(content) < 4:
                continue
            fingerprint = (author, content)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            rows.append(
                {
                    "platform": platform,
                    "keyword": keyword,
                    "post_url": post_url,
                    "comment_id": compact_text(str(first_value(item, ["cid", "comment_id", "commentId", "id"]))),
                    "author": author,
                    "content": content,
                    "like_count": numeric_value(first_value(item, ["digg_count", "like_count", "likeCount"])),
                    "reply_count": numeric_value(first_value(item, ["reply_count", "reply_comment_total", "sub_comment_count"])),
                    "source": "network",
                }
            )
            if len(rows) >= max_comments:
                return rows
    return rows


def extract_comments_from_dom(
    page: Page,
    platform: str,
    keyword: str,
    post_url: str,
    max_comments: int,
) -> list[dict[str, Any]]:
    script = """
    () => {
      const rows = [];
      const seen = new Set();
      const nodes = Array.from(document.querySelectorAll("[class], [id]"));
      for (const node of nodes) {
        const marker = `${node.className || ""} ${node.id || ""}`.toLowerCase();
        if (!/(comment|reply|评论|回复)/.test(marker)) continue;
        const text = (node.innerText || "").replace(/\\s+/g, " ").trim();
        if (text.length < 4 || text.length > 300) continue;
        if (seen.has(text)) continue;
        seen.add(text);
        rows.push({ text });
      }
      return rows;
    }
    """
    try:
        raw_rows = page.evaluate(script)
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for row in raw_rows[: max(max_comments * 2, max_comments)]:
        content = compact_text(str(row.get("text")))
        if len(content) < 4:
            continue
        rows.append(
            {
                "platform": platform,
                "keyword": keyword,
                "post_url": post_url,
                "comment_id": "",
                "author": "",
                "content": content,
                "like_count": None,
                "reply_count": None,
                "source": "dom",
            }
        )
        if len(rows) >= max_comments:
            break
    return rows


def parse_payload(body: str) -> Any | None:
    text = body.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\((\{.*\}|\[.*\])\)\s*;?\s*$", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


def iter_comment_like_dicts(node: Any, source_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(current: Any) -> None:
        if len(rows) >= 200:
            return
        if isinstance(current, dict):
            keys = {str(key) for key in current.keys()}
            content = first_value(current, ["content", "text", "comment_text", "comment", "desc"])
            source_hint = "comment" in source_url.lower() or "reply" in source_url.lower()
            has_shape = source_hint or bool(
                {"cid", "comment_id", "commentId"} & keys
                or {"digg_count", "like_count", "reply_count", "reply_comment_total"} & keys
                or {"user_info", "user", "author"} & keys
            )
            if content and has_shape:
                rows.append(current)
            for value in current.values():
                walk(value)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(node)
    return rows


def extract_author(item: dict[str, Any]) -> str:
    direct = compact_text(str(first_value(item, ["nickname", "nick_name", "name", "user_name"])))
    if direct:
        return direct
    for key in ["user", "user_info", "author"]:
        nested = item.get(key)
        if isinstance(nested, dict):
            value = compact_text(
                str(first_value(nested, ["nickname", "nick_name", "name", "screen_name", "user_name"]))
            )
            if value:
                return value
    return ""


def first_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in ("", None):
            return data[key]
    return ""


def numeric_value(value: Any) -> int | None:
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None


def dedupe_comments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        fingerprint = (
            compact_text(str(row.get("post_url"))),
            compact_text(str(row.get("author"))),
            compact_text(str(row.get("content"))),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(row)
    return deduped


def guess_title(snippet: str) -> str:
    parts = [part for part in re.split(r"[|/]", snippet) if compact_text(part)]
    if not parts:
        return snippet[:80]
    return compact_text(parts[0])[:80]


def normalize_title(title: str, page_title: str) -> str:
    cleaned = compact_text(str(title))
    if cleaned:
        return cleaned[:120]
    fallback = compact_text(str(page_title))
    for splitter in [" - ", "_", "|"]:
        if splitter in fallback:
            fallback = fallback.split(splitter)[0]
            break
    return fallback[:120]


def keyword_tokens(keyword: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-z0-9+#./-]{2,}|[\u4e00-\u9fff]{2,}", keyword.lower())]


def latest_output(root: Path, pattern: str) -> Path | None:
    candidates = sorted(root.glob(pattern))
    return candidates[-1] if candidates else None


def latest_output_any(root: Path, patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(root.glob(pattern))
    candidates = sorted(set(candidates))
    return candidates[-1] if candidates else None


def safe_read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size <= 5:
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def render_social_report(posts_df: pd.DataFrame, comments_df: pd.DataFrame, platforms: list[str]) -> str:
    platform_label = "、".join(platforms) if platforms else "social"
    if posts_df.empty and comments_df.empty:
        return "\n".join(
            [
                f"# {platform_label} 社媒深挖报告",
                "",
                "暂无可用样本。常见原因：未登录、验证码页、IP风控、搜索结果为空。",
            ]
        )

    post_summary = (
        posts_df.groupby(["platform", "keyword"], dropna=False)
        .agg(posts=("post_url", "nunique"), comments=("comments_collected", "sum"))
        .reset_index()
        .sort_values(["posts", "comments"], ascending=False)
    ) if not posts_df.empty else pd.DataFrame()

    theme_summary = summarize_themes(posts_df, comments_df)
    comment_token_summary = summarize_comment_tokens(comments_df)
    samples_df = (
        comments_df.loc[:, ["platform", "keyword", "author", "content"]]
        .drop_duplicates()
        .head(12)
        if not comments_df.empty
        else pd.DataFrame()
    )

    lines = [
        f"# {platform_label} 社媒深挖报告",
        "",
        "## 样本概况",
        "",
        f"- 帖子样本: {int(posts_df['post_url'].nunique()) if not posts_df.empty else 0}",
        f"- 评论样本: {len(comments_df)}",
        f"- 覆盖关键词: {posts_df['keyword'].nunique() if not posts_df.empty else 0}",
        "",
        "## 关键词覆盖",
        "",
        markdown_table(post_summary, ["platform", "keyword", "posts", "comments"]),
        "",
        "## 主题命中",
        "",
        markdown_table(theme_summary, ["theme", "posts", "comments"]),
        "",
        "## 评论高频词",
        "",
        markdown_table(comment_token_summary, ["token", "count"]),
        "",
        "## 评论样例",
        "",
        markdown_table(samples_df, ["platform", "keyword", "author", "content"]),
        "",
        "## 研判",
        "",
    ]

    if not theme_summary.empty:
        top_themes = theme_summary.head(3)["theme"].tolist()
        lines.extend(
            [
                f"- 当前社媒高频主题集中在: {', '.join(top_themes)}",
                "- 如果 `customer_service` 和 `knowledge_base` 同时靠前，说明企业更容易为客服/线索/知识问答类场景买单。",
                "- 如果 `training` 占比高，说明用户还在找方法论、培训和陪跑，而不是直接采购复杂系统。",
                "- 如果 `deployment` 和 `governance` 同时出现，说明部署稳定性和售后边界是成交关键。",
            ]
        )
    else:
        lines.append("- 当前样本不足以稳定判断主题结构，需要先补登录态和样本量。")

    return "\n".join(lines)


def summarize_themes(posts_df: pd.DataFrame, comments_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    post_texts = (
        posts_df.assign(text=(posts_df["title"].fillna("") + " " + posts_df["description"].fillna("") + " " + posts_df["body_excerpt"].fillna("")))
        if not posts_df.empty
        else pd.DataFrame(columns=["text"])
    )
    comment_texts = comments_df["content"].fillna("").astype(str) if not comments_df.empty else pd.Series(dtype=str)

    for theme, keywords in THEME_RULES.items():
        post_hits = 0
        comment_hits = 0
        if not post_texts.empty:
            post_hits = int(
                post_texts["text"].astype(str).map(lambda value: any(token.lower() in value.lower() for token in keywords)).sum()
            )
        if not comment_texts.empty:
            comment_hits = int(comment_texts.map(lambda value: any(token.lower() in value.lower() for token in keywords)).sum())
        rows.append({"theme": theme, "posts": post_hits, "comments": comment_hits})

    return pd.DataFrame(rows).sort_values(["comments", "posts"], ascending=False)


def summarize_comment_tokens(comments_df: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    if comments_df.empty or "content" not in comments_df.columns:
        return pd.DataFrame(columns=["token", "count"])

    counter: dict[str, int] = {}
    for content in comments_df["content"].fillna("").astype(str):
        for token in re.findall(r"[A-Za-z0-9.+/#-]{2,}|[\u4e00-\u9fff]{2,}", content):
            normalized = token.lower()
            if normalized in TOKEN_STOP_WORDS:
                continue
            counter[normalized] = counter.get(normalized, 0) + 1

    rows = [{"token": token, "count": count} for token, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)]
    return pd.DataFrame(rows[:limit])


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
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
