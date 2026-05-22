from __future__ import annotations

import argparse
import glob
from pathlib import Path

from .utils import now_stamp

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
NORMALIZED_DIR = ROOT / "data" / "normalized"
REPORT_DIR = ROOT / "reports" / "generated"
CRAWLER_CHOICES = ["jd", "taobao"]
SOCIAL_CHOICES = ["xhs", "xiaohongshu", "douyin"]
DEFAULT_SOCIAL_KEYWORDS_FALLBACK = [
    "Claude Code",
    "AI agent",
    "OpenAI",
]


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JD / Taobao Claude research pipeline")
    subparsers = parser.add_subparsers(required=True)

    login_parser = subparsers.add_parser("login", help="手工登录并保存平台登录态")
    login_parser.add_argument("--platform", choices=CRAWLER_CHOICES, required=True)
    login_parser.add_argument("--timeout-seconds", type=int, default=900)
    login_parser.set_defaults(func=cmd_login)

    crawl_parser = subparsers.add_parser("crawl", help="抓取搜索结果")
    crawl_parser.add_argument("--platforms", default="", help="逗号分隔的平台列表")
    crawl_parser.add_argument("--keywords-file", default="configs/keywords.example.yaml")
    crawl_parser.add_argument("--pages", type=int, default=0)
    crawl_parser.add_argument("--headed", action="store_true", help="抓取时显示浏览器")
    crawl_parser.set_defaults(func=cmd_crawl)

    analyze_parser = subparsers.add_parser("analyze", help="基于 CSV 生成报告")
    analyze_parser.add_argument("--input-glob", default=str(NORMALIZED_DIR / "*.csv"))
    analyze_parser.add_argument("--output", default="")
    analyze_parser.set_defaults(func=cmd_analyze)

    full_parser = subparsers.add_parser("full-run", help="抓取并生成报告")
    full_parser.add_argument("--platforms", default="", help="逗号分隔的平台列表")
    full_parser.add_argument("--keywords-file", default="configs/keywords.example.yaml")
    full_parser.add_argument("--pages", type=int, default=0)
    full_parser.add_argument("--headed", action="store_true")
    full_parser.set_defaults(func=cmd_full_run)

    enrich_parser = subparsers.add_parser("enrich-jd", help="琛ユ姄浜笢璇︽儏/璇勪环/鍥剧墖")
    enrich_parser.add_argument("--input", default="", help="绉嶅瓙 CSV锛岄粯璁や娇鐢ㄦ渶鏂扮殑 jd_*.csv")
    enrich_parser.add_argument("--limit", type=int, default=0)
    enrich_parser.add_argument("--expand-limit", type=int, default=40)
    enrich_parser.add_argument("--download-images", action="store_true")
    enrich_parser.add_argument("--max-images-per-item", type=int, default=4)
    enrich_parser.add_argument("--delay-seconds", type=float, default=2.0)
    enrich_parser.add_argument("--headed", action="store_true")
    enrich_parser.set_defaults(func=cmd_enrich_jd)

    social_login_parser = subparsers.add_parser("social-login", help="打开社媒浏览器并保存登录态")
    social_login_parser.add_argument("--platform", choices=SOCIAL_CHOICES, required=True)
    social_login_parser.add_argument("--timeout-seconds", type=int, default=1200)
    social_login_parser.set_defaults(func=cmd_social_login)

    social_crawl_parser = subparsers.add_parser("social-crawl", help="抓取社媒搜索样本与评论")
    social_crawl_parser.add_argument("--platform", choices=SOCIAL_CHOICES, required=True)
    social_crawl_parser.add_argument("--keywords", default="")
    social_crawl_parser.add_argument("--per-keyword-limit", type=int, default=8)
    social_crawl_parser.add_argument("--max-comments", type=int, default=20)
    social_crawl_parser.add_argument("--headed", action="store_true")
    social_crawl_parser.set_defaults(func=cmd_social_crawl)

    social_crawl_urls_parser = subparsers.add_parser("social-crawl-urls", help="按详情页直链抓取社媒样本与评论")
    social_crawl_urls_parser.add_argument("--platform", choices=SOCIAL_CHOICES, required=True)
    social_crawl_urls_parser.add_argument("--urls", default="")
    social_crawl_urls_parser.add_argument("--urls-file", default="")
    social_crawl_urls_parser.add_argument("--keyword", default="直链样本")
    social_crawl_urls_parser.add_argument("--max-comments", type=int, default=20)
    social_crawl_urls_parser.add_argument("--headed", action="store_true")
    social_crawl_urls_parser.set_defaults(func=cmd_social_crawl_urls)

    social_report_parser = subparsers.add_parser("social-report", help="汇总最新社媒样本报告")
    social_report_parser.add_argument("--platforms", default="xhs,douyin")
    social_report_parser.add_argument("--output", default="")
    social_report_parser.set_defaults(func=cmd_social_report)
    opc_config_parser = subparsers.add_parser("opc-config", help="Initialize or inspect OPC intelligence workspace config")
    opc_config_parser.set_defaults(func=cmd_opc_config)
    opc_bootstrap_parser = subparsers.add_parser("opc-bootstrap", help="Create OPC workspace folders and seed docs in Feishu via lark-cli")
    opc_bootstrap_parser.add_argument("--parent-folder-token", default="")
    opc_bootstrap_parser.add_argument("--workspace-name", default="")
    opc_bootstrap_parser.add_argument("--skip-seed-docs", action="store_true")
    opc_bootstrap_parser.set_defaults(func=cmd_opc_bootstrap)
    pr_digest_parser = subparsers.add_parser("github-pr-digest", help="Generate a daily GitHub PR radar report")
    pr_digest_parser.add_argument("--repos", default="")
    pr_digest_parser.add_argument("--limit", type=int, default=12)
    pr_digest_parser.add_argument("--since-days", type=int, default=7)
    pr_digest_parser.add_argument("--publish-feishu", action="store_true")
    pr_digest_parser.set_defaults(func=cmd_github_pr_digest)
    ai_news_parser = subparsers.add_parser("ai-news-digest", help="Generate a daily AI news digest")
    ai_news_parser.add_argument("--limit-per-source", type=int, default=5)
    ai_news_parser.add_argument("--max-items", type=int, default=18)
    ai_news_parser.add_argument("--since-days", type=int, default=7)
    ai_news_parser.add_argument("--publish-feishu", action="store_true")
    ai_news_parser.set_defaults(func=cmd_ai_news_digest)
    ai_news_schedule_parser = subparsers.add_parser("ai-news-schedule-run", help="Run AI news digest by timeline schedule")
    ai_news_schedule_parser.add_argument("--timeline-config", default="")
    ai_news_schedule_parser.add_argument("--force", action="store_true")
    ai_news_schedule_parser.set_defaults(func=cmd_ai_news_schedule_run)
    feishu_login_user_parser = subparsers.add_parser("feishu-login-user", help="Login to Feishu via OAuth user token")
    feishu_login_user_parser.add_argument("--port", type=int, default=3000)
    feishu_login_user_parser.add_argument("--timeout-seconds", type=int, default=300)
    feishu_login_user_parser.add_argument("--scopes", default="")
    feishu_login_user_parser.add_argument("--no-open-browser", action="store_true")
    feishu_login_user_parser.set_defaults(func=cmd_feishu_login_user)
    feishu_publish_parser = subparsers.add_parser("feishu-publish", help="Publish a Markdown report into Feishu docx/wiki")
    feishu_publish_parser.add_argument("--input-md", required=True)
    feishu_publish_parser.add_argument("--target-url", default="")
    feishu_publish_parser.add_argument("--create-new", action="store_true")
    feishu_publish_parser.add_argument("--folder-token", default="")
    feishu_publish_parser.add_argument("--title", default="")
    feishu_publish_parser.add_argument("--public-readable", action=argparse.BooleanOptionalAction, default=None)
    feishu_publish_parser.set_defaults(func=cmd_feishu_publish)

    feishu_publish_pair_parser = subparsers.add_parser("feishu-publish-pair", help="Publish report + service plan as two Feishu docs")
    feishu_publish_pair_parser.add_argument("--project-name", default="企业AI服务项目")
    feishu_publish_pair_parser.add_argument(
        "--report-md",
        default=str(REPORT_DIR / "enterprise_ai_market_demand_and_service_report_20260404.md"),
    )
    feishu_publish_pair_parser.add_argument(
        "--service-md",
        default=str(REPORT_DIR / "enterprise_ai_demand_service_design_20260404.md"),
    )
    feishu_publish_pair_parser.add_argument("--folder-token", default="")
    feishu_publish_pair_parser.add_argument("--public-readable", action=argparse.BooleanOptionalAction, default=None)
    feishu_publish_pair_parser.set_defaults(func=cmd_feishu_publish_pair)

    feishu_config_parser = subparsers.add_parser("feishu-config", help="Save default Feishu publish target settings")
    feishu_config_parser.add_argument("--target-url", default=None)
    feishu_config_parser.add_argument("--folder-token", default=None)
    feishu_config_parser.add_argument("--create-new", action=argparse.BooleanOptionalAction, default=None)
    feishu_config_parser.add_argument("--public-readable", action=argparse.BooleanOptionalAction, default=None)
    feishu_config_parser.add_argument("--clear", action="store_true")
    feishu_config_parser.set_defaults(func=cmd_feishu_config)
    return parser


def cmd_login(args: argparse.Namespace) -> None:
    from .crawlers import CRAWLER_MAP

    crawler = CRAWLER_MAP[args.platform](headless=False)
    saved_path = crawler.login(timeout_seconds=args.timeout_seconds)
    print(f"登录态已保存：{saved_path}")


def cmd_crawl(args: argparse.Namespace) -> None:
    from .config import load_settings
    from .crawlers import CRAWLER_MAP
    from .storage import records_to_dataframe, write_jsonl, write_tabular

    settings = load_settings(args.keywords_file)
    platforms = _resolve_platforms(args.platforms, settings.platforms)
    pages = args.pages or settings.pages
    stamp = now_stamp()

    for platform in platforms:
        crawler = CRAWLER_MAP[platform](headless=not args.headed)
        records, debug_rows = crawler.crawl_keywords(settings.keywords, pages=pages)
        raw_path = RAW_DIR / f"{platform}_{stamp}.jsonl"
        write_jsonl(debug_rows, raw_path)

        df = records_to_dataframe(records)
        output_base = NORMALIZED_DIR / f"{platform}_{stamp}"
        csv_path, xlsx_path = write_tabular(df, output_base)
        print(f"[{platform}] records={len(df)} raw={raw_path} csv={csv_path} xlsx={xlsx_path}")


def cmd_analyze(args: argparse.Namespace) -> None:
    from .analysis import build_category_summary, build_keyword_summary, cluster_titles, enrich_records, load_input_files
    from .reporting import render_markdown, write_report

    paths = sorted(glob.glob(args.input_glob))
    df = load_input_files(paths)
    enriched = enrich_records(df)
    category_df = build_category_summary(enriched)
    keyword_df = build_keyword_summary(enriched)
    cluster_df = cluster_titles(enriched)
    report = render_markdown(enriched, category_df, keyword_df, cluster_df)
    output = Path(args.output) if args.output else REPORT_DIR / f"market_report_{now_stamp()}.md"
    write_report(report, output)
    print(f"报告已生成：{output}")


def cmd_full_run(args: argparse.Namespace) -> None:
    cmd_crawl(args)
    analyze_args = argparse.Namespace(input_glob=str(NORMALIZED_DIR / "*.csv"), output="")
    cmd_analyze(analyze_args)


def cmd_enrich_jd(args: argparse.Namespace) -> None:
    from .jd_enrich import enrich_jd_dataset

    input_path = Path(args.input) if args.input else _resolve_latest_jd_input()
    outputs = enrich_jd_dataset(
        input_path=input_path,
        headless=not args.headed,
        limit=args.limit or None,
        expand_limit=max(args.expand_limit, 0),
        download_images=args.download_images,
        max_images_per_item=max(args.max_images_per_item, 1),
        delay_seconds=max(args.delay_seconds, 0.0),
    )
    print(
        "[jd-enrich] "
        f"seed={outputs['seed_count']} detail={outputs['detail_count']} "
        f"recommendations={outputs['recommendation_count']} candidates={outputs['candidate_count']} "
        f"images={outputs['downloaded_image_count']}"
    )
    print(f"detail_csv={outputs['detail_csv']}")
    print(f"detail_xlsx={outputs['detail_xlsx']}")
    print(f"detail_debug={outputs['detail_debug_jsonl']}")
    print(f"partial_detail_csv={outputs['partial_detail_csv']}")
    print(f"partial_recommendation_csv={outputs['partial_recommendation_csv']}")
    print(f"partial_debug={outputs['partial_debug_jsonl']}")
    if outputs["recommendation_csv"]:
        print(f"recommendation_csv={outputs['recommendation_csv']}")
        print(f"recommendation_xlsx={outputs['recommendation_xlsx']}")
    if outputs["candidate_csv"]:
        print(f"candidate_csv={outputs['candidate_csv']}")
        print(f"candidate_xlsx={outputs['candidate_xlsx']}")
    print(f"detail_report={outputs['detail_report']}")
    print(f"market_report={outputs['market_report']}")


def cmd_social_login(args: argparse.Namespace) -> None:
    from .social_research import login_social

    saved_path = login_social(args.platform, timeout_seconds=args.timeout_seconds)
    print(f"social_login_state={saved_path}")


def cmd_social_crawl(args: argparse.Namespace) -> None:
    from .social_research import DEFAULT_SOCIAL_KEYWORDS, crawl_social

    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()] if args.keywords else DEFAULT_SOCIAL_KEYWORDS
    outputs = crawl_social(
        platform=args.platform,
        keywords=keywords,
        per_keyword_limit=max(args.per_keyword_limit, 1),
        max_comments=max(args.max_comments, 1),
        headless=not args.headed,
    )
    print(f"debug_jsonl={outputs['debug_jsonl']}")
    print(f"posts_csv={outputs['posts_csv']}")
    print(f"posts_xlsx={outputs['posts_xlsx']}")
    print(f"comments_csv={outputs['comments_csv']}")
    print(f"comments_xlsx={outputs['comments_xlsx']}")
    print(f"social_report={outputs['report_md']}")


def cmd_social_crawl_urls(args: argparse.Namespace) -> None:
    from .social_research import crawl_social_urls

    urls = [item.strip() for item in args.urls.split(",") if item.strip()]
    if args.urls_file:
        url_path = Path(args.urls_file)
        file_urls = [line.strip().lstrip("\ufeff") for line in url_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        urls.extend(file_urls)
    deduped_urls = list(dict.fromkeys(urls))
    if not deduped_urls:
        raise ValueError("No social post URLs were provided. Use --urls or --urls-file.")

    outputs = crawl_social_urls(
        platform=args.platform,
        post_urls=deduped_urls,
        keyword=args.keyword.strip() or "直链样本",
        max_comments=max(args.max_comments, 1),
        headless=not args.headed,
    )
    print(f"debug_jsonl={outputs['debug_jsonl']}")
    print(f"posts_csv={outputs['posts_csv']}")
    print(f"posts_xlsx={outputs['posts_xlsx']}")
    print(f"comments_csv={outputs['comments_csv']}")
    print(f"comments_xlsx={outputs['comments_xlsx']}")
    print(f"social_report={outputs['report_md']}")


def cmd_social_report(args: argparse.Namespace) -> None:
    from .social_research import build_social_report

    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()]
    output = Path(args.output) if args.output else None
    report_path = build_social_report(platforms, output=output)
    print(f"social_report={report_path}")


def cmd_opc_config(args: argparse.Namespace) -> None:
    from .intel_workspace import ensure_opc_config, load_opc_config

    config_path = ensure_opc_config()
    config = load_opc_config()
    print(f"config_path={config_path}")
    print(f"workspace_name={config.get('workspace_name', '')}")
    print(f"parent_folder_token={config.get('parent_folder_token', '')}")


def cmd_opc_bootstrap(args: argparse.Namespace) -> None:
    from .intel_workspace import bootstrap_opc_workspace

    state = bootstrap_opc_workspace(
        parent_folder_token=args.parent_folder_token.strip(),
        workspace_name=args.workspace_name.strip(),
        publish_seed_docs=not bool(args.skip_seed_docs),
    )
    print(f"workspace_name={state['workspace_name']}")
    print(f"root_folder_token={state['root_folder']['token']}")
    print(f"root_folder_url={state['root_folder']['url']}")
    for project_key, project in state["projects"].items():
        folder = project["folder"]
        print(f"{project_key}_folder_token={folder['token']}")
        print(f"{project_key}_folder_url={folder['url']}")
        for index, doc in enumerate(project.get("docs", []), start=1):
            print(f"{project_key}_doc{index}_title={doc['title']}")
            print(f"{project_key}_doc{index}_url={doc['url']}")


def cmd_github_pr_digest(args: argparse.Namespace) -> None:
    from .intel_workspace import generate_github_pr_digest

    repos = [item.strip() for item in args.repos.split(",") if item.strip()]
    outputs = generate_github_pr_digest(
        repo_slugs=repos or None,
        limit=max(args.limit, 1),
        since_days=max(args.since_days, 1),
        publish_feishu=bool(args.publish_feishu),
    )
    print(f"report_path={outputs['report_path']}")
    print(f"report_title={outputs['report_title']}")
    print(f"repo_slugs={','.join(outputs['repo_slugs'])}")
    print(f"pr_count={outputs['pr_count']}")
    if outputs["published_doc"]:
        print(f"published_url={outputs['published_doc'].get('url', '')}")
        print(f"published_token={outputs['published_doc'].get('token', '')}")


def cmd_ai_news_digest(args: argparse.Namespace) -> None:
    from .intel_workspace import generate_ai_news_digest

    outputs = generate_ai_news_digest(
        limit_per_source=max(args.limit_per_source, 1),
        max_items=max(args.max_items, 1),
        since_days=max(args.since_days, 1),
        publish_feishu=bool(args.publish_feishu),
    )
    print(f"report_path={outputs['report_path']}")
    print(f"report_title={outputs['report_title']}")
    print(f"item_count={outputs['item_count']}")
    print(f"top_signal_count={outputs.get('top_signal_count', 0)}")
    if outputs["published_doc"]:
        print(f"published_url={outputs['published_doc'].get('url', '')}")
        print(f"published_token={outputs['published_doc'].get('token', '')}")


def cmd_ai_news_schedule_run(args: argparse.Namespace) -> None:
    from .ai_signal_scheduler import run_ai_signal_schedule

    outputs = run_ai_signal_schedule(
        config_path=args.timeline_config,
        force=bool(args.force),
    )
    schedule = dict(outputs.get("schedule", {}) or {})
    print(f"run_status={outputs.get('status', 'unknown')}")
    print(f"schedule_preset={schedule.get('preset', '')}")
    print(f"schedule_period={schedule.get('period_key', '')}")
    print(f"schedule_period_name={schedule.get('period_name', '')}")
    if outputs.get("reason"):
        print(f"skip_reason={outputs['reason']}")
    digest = dict(outputs.get("digest", {}) or {})
    if digest:
        print(f"report_path={digest.get('report_path', '')}")
        print(f"report_title={digest.get('report_title', '')}")
        print(f"item_count={digest.get('item_count', 0)}")
        print(f"top_signal_count={digest.get('top_signal_count', 0)}")
        if digest.get("published_doc"):
            print(f"published_url={digest['published_doc'].get('url', '')}")
            print(f"published_token={digest['published_doc'].get('token', '')}")
    site = dict(outputs.get("site", {}) or {})
    if site:
        print(f"site_dir={site.get('site_dir', '')}")
        print(f"site_index={site.get('site_index', '')}")
        print(f"site_latest_json={site.get('latest_json', '')}")
    degraded_sources = list(outputs.get("degraded_sources", []) or [])
    if degraded_sources:
        print("degraded_sources=" + ",".join(str(entry.get("name", "")) for entry in degraded_sources if entry.get("name")))


def cmd_feishu_login_user(args: argparse.Namespace) -> None:
    from .feishu_publish import login_feishu_user

    outputs = login_feishu_user(
        port=max(args.port, 1),
        timeout_seconds=max(args.timeout_seconds, 30),
        open_browser=not bool(args.no_open_browser),
        scopes=args.scopes.strip(),
    )
    print(f"authorization_url={outputs['authorization_url']}")
    print(f"redirect_uri={outputs['redirect_uri']}")
    print(f"token_path={outputs['token_path']}")
    print(f"user_name={outputs['user_name']}")
    print(f"open_id={outputs['open_id']}")
    print(f"scope={outputs['scope']}")
    print(f"access_expires_at={outputs['access_expires_at']}")
    print(f"refresh_expires_at={outputs['refresh_expires_at']}")


def cmd_feishu_publish(args: argparse.Namespace) -> None:
    from .feishu_publish import publish_markdown_to_feishu

    outputs = publish_markdown_to_feishu(
        markdown_path=Path(args.input_md),
        target_url=args.target_url,
        title=args.title.strip(),
        create_new=bool(args.create_new),
        folder_token=args.folder_token.strip(),
        public_readable=args.public_readable,
    )
    print(f"target_type={outputs['target_type']}")
    print(f"target_token={outputs['target_token']}")
    print(f"target_url={outputs['target_url']}")
    print(f"block_count={outputs['block_count']}")
    print(f"input_md={outputs['input_md']}")
    print(f"token_mode={outputs['token_mode']}")
    print(f"public_readable={outputs['public_readable']}")


def cmd_feishu_publish_pair(args: argparse.Namespace) -> None:
    from .feishu_publish import publish_markdown_bundle_to_feishu

    outputs = publish_markdown_bundle_to_feishu(
        project_name=args.project_name,
        report_md=Path(args.report_md),
        service_md=Path(args.service_md),
        folder_token=args.folder_token.strip(),
        public_readable=args.public_readable,
    )
    for index, output in enumerate(outputs, start=1):
        print(f"doc{index}_title={Path(output['input_md']).stem}")
        print(f"doc{index}_url={output['target_url']}")
        print(f"doc{index}_token={output['target_token']}")
        print(f"doc{index}_blocks={output['block_count']}")
        print(f"doc{index}_public_readable={output['public_readable']}")


def cmd_feishu_config(args: argparse.Namespace) -> None:
    from .feishu_publish import save_feishu_publish_config

    output = save_feishu_publish_config(
        target_url=args.target_url,
        folder_token=args.folder_token,
        create_new=args.create_new,
        public_readable=args.public_readable,
        clear=bool(args.clear),
    )
    if output is None:
        print("feishu_config=cleared")
        return
    print(f"feishu_config={output}")


def _resolve_platforms(cli_value: str, default_platforms: list[str]) -> list[str]:
    if not cli_value:
        return default_platforms
    return [item.strip().lower() for item in cli_value.split(",") if item.strip()]


def _resolve_latest_jd_input() -> Path:
    candidates = sorted(NORMALIZED_DIR.glob("jd_*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No JD seed CSV found under {NORMALIZED_DIR}")
    return candidates[-1]


if __name__ == "__main__":
    main()
