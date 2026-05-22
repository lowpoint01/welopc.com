from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from ecom_research.ai_signal_scheduler import (
    export_ai_signal_site,
    load_ai_signal_timeline_config,
    resolve_ai_signal_schedule_slot,
)
from ecom_research.intel_workspace import (
    IntelWorkspaceError,
    build_mass_hot_topics,
    finalize_ai_signal_items,
    get_project_daily_doc,
    infer_cross_verification_matches,
    localize_summary_text,
    match_trendradar_topic_groups,
    product_hunt_item_is_ai_relevant,
    remember_project_daily_doc,
    normalize_ai_daily_signal_config,
    render_ai_news_digest,
    render_github_pr_digest,
    run_lark_doc_shortcut,
    select_community_video_hotspots,
    summarize_digest_overview,
    split_markdown_for_lark_cli,
    summarize_pr_body,
    summarize_pr_files,
    summarize_pr_quick_take,
    sync_lark_doc_markdown,
)


class IntelWorkspaceTests(unittest.TestCase):
    def test_split_markdown_for_lark_cli_skips_blank_lines(self) -> None:
        markdown = "# Title\n\n- item 1\n\nTail paragraph\n"

        lines = split_markdown_for_lark_cli(markdown)

        self.assertEqual(["# Title", "- item 1", "Tail paragraph"], lines)

    @patch("ecom_research.intel_workspace.run_lark_doc_shortcut")
    def test_sync_lark_doc_markdown_uses_overwrite_then_append(self, mock_run_lark_doc_shortcut) -> None:
        mock_run_lark_doc_shortcut.return_value = {"ok": True}

        result = sync_lark_doc_markdown(
            doc_ref="doc-token",
            markdown="# Title\n\n- item 1\nTail paragraph\n",
            new_title="Daily Report",
        )

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            [
                call(
                    "+update",
                    [
                        "--doc",
                        "doc-token",
                        "--mode",
                        "overwrite",
                        "--markdown",
                        "# Title",
                        "--new-title",
                        "Daily Report",
                    ],
                ),
                call(
                    "+update",
                    [
                        "--doc",
                        "doc-token",
                        "--mode",
                        "append",
                        "--markdown",
                        "- item 1",
                    ],
                ),
                call(
                    "+update",
                    [
                        "--doc",
                        "doc-token",
                        "--mode",
                        "append",
                        "--markdown",
                        "Tail paragraph",
                    ],
                ),
            ],
            mock_run_lark_doc_shortcut.call_args_list,
        )

    @patch("ecom_research.intel_workspace.run_lark_cli_json")
    def test_run_lark_doc_shortcut_falls_back_to_bot(self, mock_run_lark_cli_json) -> None:
        mock_run_lark_cli_json.side_effect = [
            IntelWorkspaceError("user auth expired"),
            {"ok": True, "identity": "bot"},
        ]

        result = run_lark_doc_shortcut("+update", ["--doc", "doc-token", "--mode", "overwrite", "--markdown", "x"])

        self.assertEqual({"ok": True, "identity": "bot"}, result)
        self.assertEqual(
            [
                call(
                    ["docs", "+update", "--as", "user", "--doc", "doc-token", "--mode", "overwrite", "--markdown", "x"],
                    timeout_seconds=180,
                    max_attempts=5,
                ),
                call(
                    ["docs", "+update", "--as", "bot", "--doc", "doc-token", "--mode", "overwrite", "--markdown", "x"],
                    timeout_seconds=180,
                    max_attempts=5,
                ),
            ],
            mock_run_lark_cli_json.call_args_list,
        )

    def test_render_github_pr_digest_includes_digest_sections(self) -> None:
        markdown = render_github_pr_digest(
            title="OpenClaw PR Radar - 2026-04-09",
            repo_slugs=["openclaw/openclaw"],
            rows=[
                {
                    "repo_slug": "openclaw/openclaw",
                    "number": 123,
                    "title": "Fix publishing flow",
                    "state": "closed",
                    "draft": False,
                    "merged_at": "2026-04-09T02:00:00Z",
                    "html_url": "https://github.com/openclaw/openclaw/pull/123",
                    "author": "alice",
                    "updated_at": "2026-04-09T02:00:00Z",
                    "body_summary": "Fixes publishing flow and adds fallback handling.",
                    "quick_take": "Worth a quick focused review because it touches core execution or integration paths.",
                    "impact_summary": "Touches packages/runtime with focused scope.",
                    "file_summary": "3 files, +40/-8; packages/runtime, tests",
                }
            ],
        )

        self.assertIn("# OpenClaw PR Radar - 2026-04-09", markdown)
        self.assertIn("整体速览", markdown)
        self.assertIn("摘要", markdown)
        self.assertIn("已合并：1", markdown)
        self.assertIn("作者：`alice`", markdown)
        self.assertIn("Worth a quick focused review", markdown)

    def test_render_ai_news_digest_defaults_to_chinese_structure(self) -> None:
        markdown = render_ai_news_digest(
            today="2026-04-09",
            items=[
                {
                    "category": "paper",
                    "title": "A new paper",
                    "source_name": "arXiv cs.AI",
                    "published": "2026-04-09",
                    "link": "https://example.com/paper",
                    "summary": "Paper summary",
                }
            ],
        )

        self.assertIn("# AI", markdown)
        self.assertIn("AI 每日信号 - 2026-04-09", markdown)
        self.assertIn("##", markdown)
        self.assertIn("摘要", markdown)
        self.assertIn("论文", markdown)
        self.assertIn("要点：Paper summary", markdown)

    def test_render_ai_news_digest_includes_top_signals_section(self) -> None:
        markdown = render_ai_news_digest(
            today="2026-04-09",
            items=[
                {
                    "category": "official",
                    "title": "Launch update",
                    "source_name": "OpenAI News",
                    "published": "2026-04-09T08:00:00Z",
                    "link": "https://openai.com/news/launch-update",
                    "summary": "Launch update summary",
                    "signal_score": 11,
                    "headline_reasons": ["official source", "fresh within lookback window"],
                    "cross_verification_channels": ["x"],
                }
            ],
            top_signals=[
                {
                    "category": "official",
                    "title": "Launch update",
                    "source_name": "OpenAI News",
                    "published": "2026-04-09T08:00:00Z",
                    "link": "https://openai.com/news/launch-update",
                    "summary": "Launch update summary",
                    "signal_score": 11,
                    "headline_reasons": ["official source", "fresh within lookback window"],
                    "cross_verification_channels": ["x"],
                }
            ],
            source_health=[{"name": "OpenAI News", "status": "ok", "count": 1}],
        )

        self.assertIn("头部信号", markdown)
        self.assertIn("分数：11", markdown)
        self.assertIn("交叉验证：X", markdown)

    def test_render_ai_news_digest_includes_mass_hot_topics_section(self) -> None:
        markdown = render_ai_news_digest(
            today="2026-04-09",
            items=[],
            mass_hot_topics=[
                {
                    "name": "GPT-5.5",
                    "score": 18.5,
                    "categories": ["official", "x"],
                    "reasons": ["official release coverage", "broad-channel resonance"],
                    "story_count": 2,
                    "top_items": [
                        {"title": "Introducing GPT-5.5", "source_name": "OpenAI News"},
                    ],
                }
            ],
        )

        self.assertIn("大众热榜", markdown)
        self.assertIn("GPT-5.5", markdown)
        self.assertIn("热度分：18.5", markdown)

    def test_product_hunt_item_is_ai_relevant_rejects_generic_builder_tool(self) -> None:
        item = {
            "title": "Free chart generator",
            "summary": "Turn CSV files into charts in seconds.",
            "topics": ["Analytics"],
            "topic_slugs": ["analytics"],
            "website": "https://example.com",
        }

        is_ai_relevant, matches = product_hunt_item_is_ai_relevant(item, ["ai agents", "llms", "developer tools", "api"])

        self.assertFalse(is_ai_relevant)
        self.assertEqual([], matches)

    def test_finalize_ai_signal_items_diversifies_top_signals(self) -> None:
        now = datetime.now(UTC).isoformat()
        config = normalize_ai_daily_signal_config(
            {
                "scoring": {
                    "top_signal_limit": 5,
                }
            }
        )
        items = [
            {
                "category": "product_hunt",
                "source_kind": "product_hunt",
                "title": f"PH AI Agent {index}",
                "summary": "AI agent platform",
                "source_name": "Product Hunt",
                "link": f"https://producthunt.com/products/agent-{index}",
                "published": now,
                "published_sort": now,
                "featured": True,
                "ph_promoted": True,
                "ph_above_median": True,
                "ph_topic_match": True,
                "has_builder_surface": True,
            }
            for index in range(5)
        ] + [
            {
                "category": "GitHub",
                "source_kind": "github_trending",
                "title": f"builder/tool-{index} trending on GitHub",
                "summary": "今日新增 1200 stars；总 stars 5000；共 200 个 forks；Python；AI developer tool.",
                "source_name": "GitHub Trending AI",
                "link": f"https://github.com/builder/tool-{index}",
                "repo_slug": f"builder/tool-{index}",
                "stars_today": 1200,
                "published": now,
                "published_sort": now,
            }
            for index in range(2)
        ]

        _, top_signals = finalize_ai_signal_items(
            items=items,
            signal_config=config,
            max_items=10,
            since_days=1,
        )

        self.assertEqual(5, len(top_signals))
        self.assertEqual(3, sum(1 for item in top_signals if item["source_kind"] == "product_hunt"))
        self.assertEqual(2, sum(1 for item in top_signals if item["source_kind"] == "github_trending"))

    def test_build_mass_hot_topics_rejects_single_source_static_topic(self) -> None:
        config = normalize_ai_daily_signal_config({})
        items = [
            {
                "category": "product_hunt",
                "title": "GPT-5.5 by OpenAI",
                "summary": "OpenAI smartest model",
                "source_name": "Product Hunt",
                "link": "https://producthunt.com/products/openai",
                "published": "2026-04-27T07:00:00Z",
                "published_sort": "2026-04-27T07:00:00Z",
                "featured": True,
                "ph_promoted": True,
                "has_builder_surface": True,
            },
            {
                "category": "official",
                "title": "Claude Opus 4.7 正式发布",
                "summary": "Anthropic 发布 Claude Opus 4.7。",
                "source_name": "Anthropic Newsroom",
                "link": "https://anthropic.com/news/opus-4-7",
                "published": "2026-04-27T08:00:00Z",
                "published_sort": "2026-04-27T08:00:00Z",
            },
            {
                "category": "trendradar",
                "title": "Claude Opus 4.7 正式发布",
                "summary": "多平台热议 Claude Opus 4.7",
                "source_name": "TrendRadar / Hacker News",
                "link": "https://example.com/hn/opus47",
                "published": "2026-04-27T08:30:00Z",
                "published_sort": "2026-04-27T08:30:00Z",
            },
        ]

        topics = build_mass_hot_topics(items=items, signal_config=config)
        by_name = {topic["name"]: topic for topic in topics}

        self.assertIn("Claude Opus 4.7", by_name)
        self.assertNotIn("GPT-5.5", by_name)
        self.assertEqual(2, by_name["Claude Opus 4.7"]["source_report_count"])

    def test_select_community_video_hotspots_keeps_reddit_and_youtube(self) -> None:
        items = [
            {
                "category": "product_hunt",
                "title": "GPT-5.5",
                "link": "https://example.com/ph",
                "published_sort": "2026-04-27T12:00:00Z",
            },
            {
                "category": "reddit",
                "title": "Reddit discusses DeepSeek V4",
                "summary": "Community thread about DeepSeek V4",
                "link": "https://reddit.com/r/LocalLLaMA/example",
                "published_sort": "2026-04-27T11:00:00Z",
            },
            {
                "category": "youtube",
                "title": "Qwen 3.6 coding model overview",
                "summary": "Video overview of Qwen 3.6",
                "link": "https://youtube.com/watch?v=example",
                "published_sort": "2026-04-27T10:00:00Z",
            },
        ]

        hotspots = select_community_video_hotspots(items, limit=4)

        self.assertEqual(["reddit", "youtube"], [item["category"] for item in hotspots])

    def test_render_ai_news_digest_includes_community_video_section(self) -> None:
        markdown = render_ai_news_digest(
            today="2026-04-27",
            items=[
                {
                    "category": "reddit",
                    "title": "Reddit discusses DeepSeek V4",
                    "source_name": "Reddit / r/LocalLLaMA",
                    "published": "2026-04-27",
                    "link": "https://reddit.com/example",
                    "summary": "Community thread about DeepSeek V4",
                }
            ],
        )

        self.assertIn("社区与视频热点", markdown)
        self.assertIn("Reddit discusses DeepSeek V4", markdown)

    def test_load_ai_signal_timeline_config_merges_defaults(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "timeline.yaml"
            config_path.write_text("preset: live_pulse\nsite:\n  title: 测试站点\n", encoding="utf-8")

            config = load_ai_signal_timeline_config(config_path)

        self.assertEqual("live_pulse", config["preset"])
        self.assertEqual("测试站点", config["site"]["title"])
        self.assertIn("live_pulse", config["presets"])

    def test_resolve_ai_signal_schedule_slot_uses_live_monitor_all_day(self) -> None:
        config = load_ai_signal_timeline_config()
        now = datetime.fromisoformat("2026-04-27T09:30:00+08:00")

        plan = resolve_ai_signal_schedule_slot(config=config, now=now)

        self.assertEqual("live_monitor", plan["period_key"])
        self.assertTrue(plan["enabled"])
        self.assertTrue(plan["export_site"])
        self.assertFalse(plan["publish_feishu"])

    def test_resolve_ai_signal_schedule_slot_does_not_publish_evening_by_default(self) -> None:
        config = load_ai_signal_timeline_config()
        now = datetime.fromisoformat("2026-04-27T20:30:00+08:00")

        plan = resolve_ai_signal_schedule_slot(config=config, now=now)

        self.assertEqual("live_monitor", plan["period_key"])
        self.assertFalse(plan["publish_feishu"])

    def test_export_ai_signal_site_writes_latest_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            digest = {
                "today": "2026-04-27",
                "report_path": str(Path(temp_dir) / "ai_daily_signal_20260427.md"),
                "report_title": "AI 每日信号 - 2026-04-27",
                "report_markdown": "# AI 每日信号 - 2026-04-27\n",
                "item_count": 3,
                "top_signal_count": 1,
                "items": [
                    {
                        "title": "DeepSeek-V4",
                        "source_name": "OpenAI News",
                        "category": "official",
                        "published": "2026-04-27",
                        "link": "https://example.com/deepseek",
                        "summary": "摘要",
                        "signal_score": 12,
                    }
                ],
                "top_signals": [
                    {
                        "title": "DeepSeek-V4",
                        "source_name": "OpenAI News",
                        "category": "official",
                        "published": "2026-04-27",
                        "link": "https://example.com/deepseek",
                        "summary": "摘要",
                        "signal_score": 12,
                    }
                ],
                "mass_hot_topics": [
                    {
                        "name": "DeepSeek-V4",
                        "score": 18,
                        "one_liner": "今天的爆点。",
                        "what_it_is": "模型发布。",
                        "why_hot_today": "官方与社区共振。",
                        "who_it_matters_to": "关注大模型的人。",
                        "categories": ["official", "trendradar"],
                        "reasons": ["official release coverage"],
                        "story_count": 2,
                        "video_titles": ["官方视频"],
                        "top_items": [{"title": "DeepSeek-V4 发布", "source_name": "DeepSeek"}],
                    }
                ],
                "source_health": [{"name": "OpenAI News", "status": "ok", "count": 1}],
                "published_doc": {"url": "https://example.com/doc"},
            }
            Path(digest["report_path"]).write_text(digest["report_markdown"], encoding="utf-8")
            schedule = {
                "resolved_at": "2026-04-27T20:30:00+08:00",
                "timezone": "Asia/Shanghai",
                "preset": "live_pulse",
                "preset_name": "AI 热点时间线",
                "period_key": "evening_final",
                "period_name": "晚间正式版",
                "publish_feishu": True,
                "export_site": True,
            }
            timeline_config = {
                "site": {
                    "title": "测试站点",
                    "subtitle": "测试副标题",
                    "output_dir": str(Path(temp_dir) / "site"),
                    "history_limit": 8,
                }
            }

            site_outputs = export_ai_signal_site(
                digest=digest,
                schedule_plan=schedule,
                state={},
                timeline_config=timeline_config,
            )

            latest_payload = json.loads(Path(site_outputs["latest_json"]).read_text(encoding="utf-8"))
            self.assertEqual("测试站点", latest_payload["site"]["title"])
            self.assertEqual("晚间正式版", latest_payload["schedule"]["period_name"])
            self.assertEqual("DeepSeek-V4", latest_payload["mass_hot_topics"][0]["name"])
            self.assertTrue(Path(site_outputs["latest_md"]).exists())

    @patch("ecom_research.intel_workspace.translate_text_to_chinese")
    def test_localize_summary_text_translates_structured_github_metrics(self, mock_translate_text_to_chinese) -> None:
        mock_translate_text_to_chinese.return_value = "一位开源机器学习工程师"
        localized = localize_summary_text(
            "2985 stars today; 5854 total stars; 516 forks; Python; an open-source ML engineer that ships models"
        )

        self.assertIn("今日新增 2985 stars", localized)
        self.assertIn("总 stars 5854", localized)
        self.assertIn("共 516 个 forks", localized)
        self.assertIn("一位开源机器学习工程师", localized)

    @patch("ecom_research.intel_workspace.translate_text_to_chinese")
    def test_render_ai_news_digest_localizes_summary_text(self, mock_translate_text_to_chinese) -> None:
        mock_translate_text_to_chinese.return_value = "这是中文摘要。"

        markdown = render_ai_news_digest(
            today="2026-04-09",
            items=[
                {
                    "category": "official",
                    "title": "Introducing GPT-5.5",
                    "source_name": "OpenAI News",
                    "published": "2026-04-09",
                    "link": "https://example.com/gpt-5-5",
                    "summary": "Introducing GPT-5.5, our smartest model yet for coding and research tasks.",
                }
            ],
        )

        self.assertIn("要点：这是中文摘要。", markdown)

    def test_summarize_pr_body_prefers_named_summary_section(self) -> None:
        body = """
## Summary
- tighten retry handling for Feishu publishing
- add fallback to user identity first

## Test Plan
- unit tests
"""

        summary = summarize_pr_body(body, fallback_title="fallback")

        self.assertIn("tighten retry handling", summary)
        self.assertNotIn("Test Plan", summary)

    def test_summarize_pr_files_lists_scope_and_modules(self) -> None:
        summary = summarize_pr_files(
            [
                "packages/runtime/publish.py",
                "packages/runtime/retry.py",
                "tests/test_publish.py",
            ],
            changed_files=3,
            additions=42,
            deletions=8,
        )

        self.assertIn("3 files, +42/-8", summary)
        self.assertIn("packages/runtime", summary)

    def test_summarize_pr_quick_take_marks_maintenance_low_priority(self) -> None:
        take = summarize_pr_quick_take(
            title="build(deps): bump swift dependencies",
            body_summary="routine dependency updates",
            file_paths=["apps/macos/Package.swift"],
            changed_files=2,
            additions=10,
            deletions=8,
        )

        self.assertIn("low priority", take.lower())

    def test_summarize_pr_quick_take_marks_core_paths_high_attention(self) -> None:
        take = summarize_pr_quick_take(
            title="fix(feishu): route control commands to dedicated queue",
            body_summary="prevents /stop from being blocked by active runs",
            file_paths=["packages/runtime/queue.ts", "packages/feishu/dispatcher.ts"],
            changed_files=4,
            additions=80,
            deletions=12,
        )

        self.assertIn("Worth a quick focused review", take)

    def test_summarize_digest_overview_includes_watchlist(self) -> None:
        lines = summarize_digest_overview(
            [
                {
                    "number": 101,
                    "title": "fix(feishu): route stop commands through dedicated queue",
                    "quick_take": "Worth a quick focused review because it touches core execution or integration paths.",
                    "file_paths": ["src/queue.ts"],
                },
                {
                    "number": 102,
                    "title": "build(deps): bump sdk packages",
                    "quick_take": "Mostly maintenance work; low priority unless you own deps, tests, or build tooling.",
                    "file_paths": ["package.json"],
                },
            ]
        )

        self.assertTrue(any("一句话" in line for line in lines))
        self.assertTrue(any("优先关注" in line for line in lines))

    def test_normalize_ai_daily_signal_config_merges_legacy_feeds(self) -> None:
        normalized = normalize_ai_daily_signal_config(
            {
                "feeds": [
                    {
                        "name": "Official Test Feed",
                        "category": "company",
                        "url": "https://example.com/company.xml",
                    },
                    {
                        "name": "Community Test Feed",
                        "category": "reddit",
                        "url": "https://example.com/reddit.xml",
                    },
                ],
                "x_accounts": [{"name": "Test X", "category": "x", "handle": "testbot", "source_kind": "x_allowlist"}],
            }
        )

        official_urls = {item["url"] for item in normalized["official_feeds"]}
        community_urls = {item["url"] for item in normalized["community_feeds"]}
        handles = {item["handle"] for item in normalized["x_accounts"]}

        self.assertIn("https://example.com/company.xml", official_urls)
        self.assertIn("https://example.com/reddit.xml", community_urls)
        self.assertIn("testbot", handles)
        self.assertTrue(normalized["github_momentum"]["enabled"])
        self.assertTrue(normalized["github_trending"]["enabled"])
        self.assertTrue(normalized["trendradar_bridge"]["enabled"])

    def test_match_trendradar_topic_groups_uses_rich_terms_not_only_ai(self) -> None:
        bridge_config = normalize_ai_daily_signal_config({})["trendradar_bridge"]

        matches = match_trendradar_topic_groups(
            title="DeepSeek V4 刷榜，开发者热议推理成本",
            summary="",
            bridge_config=bridge_config,
        )

        self.assertIn("模型与实验室", matches)

    def test_finalize_ai_signal_items_scores_trendradar_hotlists(self) -> None:
        published = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        signal_config = normalize_ai_daily_signal_config({})

        ranked_items, top_signals = finalize_ai_signal_items(
            items=[
                {
                    "category": "trendradar",
                    "source_kind": "trendradar_hotlist",
                    "source_name": "TrendRadar / 微博",
                    "title": "DeepSeek V4 全面评测",
                    "published": published,
                    "link": "https://example.com/deepseek-v4",
                    "summary": "TrendRadar 热榜命中：微博 第 2 位；主题：模型与实验室",
                    "trendradar_platform": "微博",
                    "trendradar_rank": 2,
                    "trendradar_topics": ["模型与实验室"],
                }
            ],
            signal_config=signal_config,
            max_items=10,
            since_days=2,
        )

        self.assertEqual(1, len(ranked_items))
        self.assertEqual("trendradar", ranked_items[0]["category"])
        self.assertTrue(ranked_items[0]["headline_candidate"])
        self.assertIn("大众热榜靠前", render_ai_news_digest(today="2026-04-27", items=ranked_items, top_signals=top_signals))

    def test_finalize_ai_signal_items_promotes_product_hunt_when_checks_pass(self) -> None:
        published = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        signal_config = normalize_ai_daily_signal_config(
            {
                "product_hunt": {
                    "headline_min_checks": 2,
                    "target_topics": ["ai agents", "developer tools"],
                }
            }
        )
        items = [
            {
                "source_name": "Product Hunt",
                "source_kind": "product_hunt",
                "category": "product_hunt",
                "title": "AgentKit",
                "link": "https://www.producthunt.com/posts/agentkit",
                "published": published,
                "published_sort": published,
                "summary": "AI agent builder for developers",
                "product_name": "AgentKit",
                "product_slug": "agentkit",
                "website": "https://agentkit.dev",
                "votes_count": 120,
                "comments_count": 28,
                "featured": True,
                "topics": ["AI Agents", "Developer Tools"],
                "topic_slugs": ["ai-agents", "developer-tools"],
                "has_builder_surface": True,
            },
            {
                "source_name": "OpenAI News",
                "source_kind": "official_feed",
                "category": "official",
                "title": "AgentKit API",
                "link": "https://openai.com/news/agentkit-api",
                "published": published,
                "published_sort": published,
                "summary": "AgentKit API docs are live at agentkit.dev",
            },
            {
                "source_name": "OpenAI",
                "source_kind": "x_allowlist",
                "category": "x",
                "title": "AgentKit launch",
                "link": "https://x.com/OpenAI/status/123",
                "published": published,
                "published_sort": published,
                "summary": "AgentKit is live today. Docs: agentkit.dev",
                "x_handle": "OpenAI",
                "engagement_score": 900,
            },
        ]

        ranked_items, top_signals = finalize_ai_signal_items(
            items=items,
            signal_config=signal_config,
            max_items=10,
            since_days=2,
        )

        ph_item = next(item for item in ranked_items if item["category"] == "product_hunt")
        self.assertTrue(ph_item["ph_promoted"])
        self.assertGreaterEqual(ph_item["ph_check_count"], 2)
        self.assertTrue(any(item["title"] == "AgentKit" for item in top_signals))

    def test_finalize_ai_signal_items_ranks_official_above_reddit(self) -> None:
        published = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        signal_config = normalize_ai_daily_signal_config({})
        ranked_items, _ = finalize_ai_signal_items(
            items=[
                {
                    "source_name": "Reddit / r/LocalLLaMA",
                    "source_kind": "community_feed",
                    "category": "reddit",
                    "title": "Interesting thread",
                    "link": "https://reddit.com/r/LocalLLaMA/comments/1",
                    "published": published,
                    "published_sort": published,
                    "summary": "Community thread",
                },
                {
                    "source_name": "OpenAI News",
                    "source_kind": "official_feed",
                    "category": "official",
                    "title": "Official update",
                    "link": "https://openai.com/news/official-update",
                    "published": published,
                    "published_sort": published,
                    "summary": "Official launch note",
                },
            ],
            signal_config=signal_config,
            max_items=10,
            since_days=2,
        )

        self.assertEqual("Official update", ranked_items[0]["title"])
        self.assertGreater(ranked_items[0]["signal_score"], ranked_items[1]["signal_score"])

    def test_finalize_ai_signal_items_does_not_headline_repo_activity(self) -> None:
        published = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        signal_config = normalize_ai_daily_signal_config({})
        _, top_signals = finalize_ai_signal_items(
            items=[
                {
                    "source_name": "Example Repo",
                    "source_kind": "github_repo",
                    "category": "github",
                    "title": "Example repo activity",
                    "link": "https://github.com/example/repo",
                    "published": published,
                    "published_sort": published,
                    "summary": "Routine repository activity",
                    "repo_slug": "example/repo",
                }
            ],
            signal_config=signal_config,
            max_items=10,
            since_days=2,
        )

        self.assertEqual([], top_signals)

    def test_finalize_ai_signal_items_promotes_github_momentum(self) -> None:
        published = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        signal_config = normalize_ai_daily_signal_config(
            {"github_momentum": {"headline_star_delta": 60}}
        )
        ranked_items, top_signals = finalize_ai_signal_items(
            items=[
                {
                    "source_name": "MCP Servers",
                    "source_kind": "github_momentum",
                    "category": "github",
                    "title": "MCP Servers GitHub momentum",
                    "link": "https://github.com/modelcontextprotocol/servers",
                    "published": published,
                    "published_sort": published,
                    "summary": "Recent GitHub stars 85 in 2d; total stars 10000",
                    "repo_slug": "modelcontextprotocol/servers",
                    "recent_star_count": 85,
                    "star_delta": 0,
                    "fork_delta": 12,
                    "snapshot_window_hours": 0,
                }
            ],
            signal_config=signal_config,
            max_items=10,
            since_days=2,
        )

        self.assertEqual("MCP Servers GitHub momentum", ranked_items[0]["title"])
        self.assertTrue(top_signals)
        self.assertEqual("MCP Servers GitHub momentum", top_signals[0]["title"])

    def test_finalize_ai_signal_items_promotes_github_trending(self) -> None:
        published = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        signal_config = normalize_ai_daily_signal_config(
            {"github_trending": {"headline_stars_today": 300}}
        )
        ranked_items, top_signals = finalize_ai_signal_items(
            items=[
                {
                    "source_name": "GitHub Trending AI",
                    "source_kind": "github_trending",
                    "category": "github",
                    "title": "huggingface/ml-intern trending on GitHub",
                    "link": "https://github.com/huggingface/ml-intern",
                    "published": published,
                    "published_sort": published,
                    "summary": "2981 stars today; 4741 total stars; 390 forks",
                    "repo_slug": "huggingface/ml-intern",
                    "stars_today": 2981,
                    "stargazers_count": 4741,
                    "forks_count": 390,
                }
            ],
            signal_config=signal_config,
            max_items=10,
            since_days=2,
        )

        self.assertEqual("huggingface/ml-intern trending on GitHub", ranked_items[0]["title"])
        self.assertTrue(top_signals)
        self.assertEqual("huggingface/ml-intern trending on GitHub", top_signals[0]["title"])

    def test_render_ai_news_digest_includes_hot_topic_brief_fields_and_video_titles(self) -> None:
        markdown = render_ai_news_digest(
            today="2026-04-09",
            items=[],
            mass_hot_topics=[
                {
                    "name": "Codex 3.0",
                    "score": 18.0,
                    "categories": ["official", "youtube"],
                    "reasons": ["official release coverage"],
                    "story_count": 2,
                    "what_it_is": "Codex 3.0 是今天进入热点池的 AI 产品/工具。",
                    "why_hot_today": "今天它变热，主要因为有官方发布覆盖。",
                    "who_it_matters_to": "对开发者、自动化搭建者和技术负责人最重要。",
                    "one_liner": "Codex 3.0 是今天值得优先看的 AI 产品/工具。",
                    "video_titles": ["Introducing Codex 3.0 | OpenAI"],
                    "top_items": [
                        {"title": "Codex 3.0 by OpenAI", "source_name": "Product Hunt"},
                    ],
                }
            ],
        )

        self.assertIn("\u4e00\u53e5\u8bdd\u5224\u65ad", markdown)
        self.assertIn("\u8fd9\u662f\u4ec0\u4e48", markdown)
        self.assertIn("\u4e3a\u4ec0\u4e48\u4eca\u5929\u70ed", markdown)
        self.assertIn("\u5bf9\u8c01\u91cd\u8981", markdown)
        self.assertIn("\u89c6\u9891\u547d\u4e2d\uff1aIntroducing Codex 3.0 | OpenAI", markdown)

    def test_infer_cross_verification_matches_requires_strict_youtube_match(self) -> None:
        target = {
            "category": "product_hunt",
            "source_name": "Product Hunt",
            "title": "Codex 3.0 by OpenAI",
            "summary": "Codex can now build, test & debug on autopilot.",
            "link": "https://producthunt.com/products/codex-3-0-by-openai",
            "canonical_link": "https://producthunt.com/products/codex-3-0-by-openai",
            "product_name": "Codex 3.0 by OpenAI",
            "product_slug": "codex-3-0-by-openai",
            "published": "2026-04-09T07:01:00Z",
        }
        loose_video = {
            "category": "youtube",
            "source_name": "OpenAI",
            "title": "Introducing GPT-5.5 with NVIDIA",
            "summary": "Teams are using GPT-5.5-Codex for complex engineering tasks.",
            "link": "https://youtube.com/watch?v=loose",
            "canonical_link": "https://youtube.com/watch?v=loose",
            "published": "2026-04-09T08:00:00Z",
        }
        strict_video = {
            "category": "youtube",
            "source_name": "OpenAI",
            "title": "Introducing Codex 3.0",
            "summary": "A closer look at Codex 3.0 and how it builds on autopilot.",
            "link": "https://youtube.com/watch?v=strict",
            "canonical_link": "https://youtube.com/watch?v=strict",
            "published": "2026-04-09T09:00:00Z",
        }

        matches = infer_cross_verification_matches(target, [target, loose_video, strict_video])
        youtube_titles = [match["title"] for match in matches if match["category"] == "youtube"]

        self.assertIn("Introducing Codex 3.0", youtube_titles)
        self.assertNotIn("Introducing GPT-5.5 with NVIDIA", youtube_titles)

    def test_remember_project_daily_doc_promotes_doc_to_fixed_target(self) -> None:
        state = {
            "projects": {
                "ai_daily_signal": {
                    "docs": [
                        {
                            "title": "旧日报",
                            "token": "old-token",
                            "url": "https://my.feishu.cn/docx/old-token",
                        }
                    ]
                }
            }
        }

        remembered = remember_project_daily_doc(
            state,
            "ai_daily_signal",
            {
                "title": "AI 每日信号（自动更新）",
                "token": "new-token",
                "url": "https://my.feishu.cn/docx/new-token",
            },
        )

        self.assertEqual("new-token", remembered["token"])
        self.assertEqual("new-token", get_project_daily_doc(state, "ai_daily_signal")["token"])
        self.assertEqual("new-token", state["projects"]["ai_daily_signal"]["docs"][0]["token"])


if __name__ == "__main__":
    unittest.main()
