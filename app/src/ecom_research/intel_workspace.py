from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .feishu_publish import publish_markdown_to_feishu
from .storage import AUTH_DIR, REPORT_DIR
from .utils import compact_text, ensure_dirs, now_stamp


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
OPC_CONFIG_PATH = CONFIG_DIR / "opc_intelligence.json"
OPC_STATE_PATH = AUTH_DIR / "opc_workspace.json"
DAILY_REPORT_DIR = REPORT_DIR / "daily"

DEFAULT_PARENT_FOLDER_TOKEN = ""
DEFAULT_WORKSPACE_NAME = "OPC Intelligence Hub"
DEFAULT_PR_REPO = "openclaw/openclaw"
LARK_CLI_CANDIDATES = [
    Path(os.getenv("LARK_CLI_PATH", "")).expanduser() if os.getenv("LARK_CLI_PATH") else None,
    Path("D:/npm-global/lark-cli.cmd"),
    Path("D:/npm-global/lark-cli"),
]
LARK_DOC_WRITE_IDENTITIES = ("user", "bot")
AI_CATEGORY_LABELS = {
    "reddit": "绀惧尯璁ㄨ / Community",
    "paper": "璁烘枃鐮旂┒ / Papers",
    "product": "浜у搧鍔ㄦ€?/ Products",
    "company": "鍏徃鍔ㄦ€?/ Companies",
    "youtube": "瑙嗛鏇存柊 / Videos",
    "other": "鍏朵粬 / Other",
}

AI_CATEGORY_LABELS = {
    **AI_CATEGORY_LABELS,
    "official": "鐎规ɑ鏌熼崝銊︹偓? / Official",
    "github": "GitHub 閸斻劍鈧? / GitHub",
    "x": "X 娣団€冲娇 / X",
    "product_hunt": "Product Hunt / Product Hunt",
    "trendradar": "TrendRadar / Public Hotlists",
}
PH_TIMEZONE = ZoneInfo("America/Los_Angeles")
AI_SIGNAL_CATEGORY_ORDER = {
    "official": 0,
    "github": 1,
    "product_hunt": 2,
    "x": 3,
    "trendradar": 4,
    "reddit": 5,
    "paper": 6,
    "youtube": 7,
    "product": 8,
    "company": 9,
    "other": 10,
}
AI_SIGNAL_TOPIC_KEYWORDS = {
    "ai agents",
    "agent",
    "agentic",
    "llm",
    "llms",
    "ai infra",
    "ai infrastructure",
    "developer tools",
    "mcp",
    "model context protocol",
    "workflow automation",
    "api",
    "open source",
}
AI_SIGNAL_STRONG_TOPIC_KEYWORDS = {
    "ai",
    "artificial intelligence",
    "agent",
    "agentic",
    "llm",
    "model",
    "coding model",
    "ai coding",
    "copilot",
    "openai",
    "anthropic",
    "claude",
    "gpt",
    "gemini",
    "deepseek",
    "qwen",
    "llama",
    "hunyuan",
    "hy3",
    "codex",
    "cursor",
    "windsurf",
    "dify",
    "autogen",
    "langgraph",
    "crewai",
    "browser use",
    "browser-use",
    "mcp",
}
AI_SIGNAL_GENERIC_TOPIC_KEYWORDS = {
    "api",
    "open source",
    "developer tools",
}
AI_DYNAMIC_TOPIC_PATTERNS: list[tuple[str, str]] = [
    (r"\b(gpt[- ]?\d+(?:\.\d+)?)\b", "gpt"),
    (r"\b(deepseek[- ]?v?\d+(?:\.\d+)?)\b", "deepseek"),
    (r"\b(qwen[\d.:-]*[a-z0-9-]*)\b", "qwen"),
    (r"\b(claude(?:\s+[a-z0-9.-]+){0,4})\b", "claude"),
    (r"\b(gemini(?:\s+[a-z0-9.-]+){0,4})\b", "gemini"),
    (r"\b(llama(?:\s+[a-z0-9.-]+){0,4})\b", "llama"),
    (r"\b(codex(?:\s+\d+(?:\.\d+)?)?)\b", "codex"),
    (r"\b((?:tencent\s+)?(?:hunyuan|hy3)(?:\s+[a-z0-9.-]+){0,3})\b", "hunyuan"),
    (r"\b(cursor(?:\s+[a-z0-9.-]+){0,3})\b", "cursor"),
]
DEFAULT_TRENDRADAR_REPO = Path("D:/Agent/external/TrendRadar")
DEFAULT_TRENDRADAR_BRIDGE_TOPIC_GROUPS = [
    {
        "name": "AI 通用",
        "terms": [
            "ai",
            "artificial intelligence",
            "人工智能",
            "大模型",
            "语言模型",
            "多模态",
            "生成式 ai",
            "智能体",
            "agent",
            "agentic",
            "llm",
            "mcp",
        ],
    },
    {
        "name": "模型与实验室",
        "terms": [
            "openai",
            "chatgpt",
            "gpt",
            "claude",
            "anthropic",
            "deepseek",
            "qwen",
            "gemini",
            "llama",
            "grok",
            "kimi",
            "glm",
            "minimax",
            "hunyuan",
            "混元",
            "doubao",
            "豆包",
            "mistral",
            "sora",
        ],
    },
    {
        "name": "Agent 与工具链",
        "terms": [
            "autogen",
            "langgraph",
            "crewai",
            "browser-use",
            "dify",
            "copilot",
            "cursor",
            "windsurf",
            "codex",
            "ai 编程",
            "coding agent",
            "developer tool",
        ],
    },
    {
        "name": "推理与基础设施",
        "terms": [
            "vllm",
            "transformers",
            "inference",
            "embedding",
            "rag",
            "token",
            "算力",
            "推理芯片",
            "cuda",
        ],
    },
]


def load_windows_user_env_var(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return compact_text(str(value))
    except OSError:
        return ""


def get_env_value(*names: str) -> str:
    for name in names:
        value = compact_text(os.getenv(name, ""))
        if value:
            return value
    for name in names:
        value = load_windows_user_env_var(name)
        if value:
            os.environ[name] = value
            return value
    return ""


class IntelWorkspaceError(RuntimeError):
    pass


def build_default_ai_daily_signal_project() -> dict[str, Any]:
    return {
        "folder_name": "03 AI Daily Signal",
        "daily_title_template": "AI 濮ｅ繑妫╂穱鈥冲娇 / Daily Signal - {date}",
        "official_feeds": [
            {
                "name": "OpenAI News",
                "category": "official",
                "url": "https://openai.com/news/rss.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "OpenAI Blog",
                "category": "official",
                "url": "https://openai.com/blog/rss.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "Google AI Blog",
                "category": "official",
                "url": "https://blog.google/technology/ai/rss/",
                "source_kind": "official_feed",
            },
            {
                "name": "Google DeepMind Blog",
                "category": "official",
                "url": "https://deepmind.google/blog/rss.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "Hugging Face Blog",
                "category": "official",
                "url": "https://huggingface.co/blog/feed.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "Anthropic Newsroom",
                "category": "official",
                "url": "https://www.anthropic.com/news",
                "source_kind": "official_web",
            },
            {
                "name": "DeepSeek",
                "category": "official",
                "url": "https://www.deepseek.com/",
                "source_kind": "official_web",
                "text_patterns": ["deepseek-v4", "deepseek v4"],
                "emit_page_probe": True,
                "page_probe_title": "DeepSeek-V4",
            },
            {
                "name": "Qwen / Hugging Face",
                "category": "official",
                "url": "https://huggingface.co/Qwen/Qwen3.6-27B",
                "source_kind": "official_web",
                "text_patterns": ["qwen3.6-27b", "flagship-level coding", "agentic coding"],
                "emit_page_probe": True,
                "page_probe_title": "Qwen3.6-27B",
            },
            {
                "name": "Tencent HY",
                "category": "official",
                "url": "https://cloud.tencent.com/product/hunyuan?Is=home",
                "source_kind": "official_web",
                "text_patterns": ["hy3 preview", "tencent hy3", "hunyuan hy3", "娣峰厓"],
                "emit_page_probe": True,
                "page_probe_title": "Tencent Hy3 preview",
            },
        ],
        "community_feeds": [
            {
                "name": "Reddit / r/LocalLLaMA",
                "category": "reddit",
                "url": "https://www.reddit.com/r/LocalLLaMA/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/MachineLearning",
                "category": "reddit",
                "url": "https://www.reddit.com/r/MachineLearning/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/OpenAI",
                "category": "reddit",
                "url": "https://www.reddit.com/r/OpenAI/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/Anthropic",
                "category": "reddit",
                "url": "https://www.reddit.com/r/Anthropic/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/artificial",
                "category": "reddit",
                "url": "https://www.reddit.com/r/artificial/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/ChatGPT",
                "category": "reddit",
                "url": "https://www.reddit.com/r/ChatGPT/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/ClaudeAI",
                "category": "reddit",
                "url": "https://www.reddit.com/r/ClaudeAI/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/singularity",
                "category": "reddit",
                "url": "https://www.reddit.com/r/singularity/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "arXiv cs.AI",
                "category": "paper",
                "url": "https://export.arxiv.org/rss/cs.AI",
                "source_kind": "community_feed",
            },
        ],
        "feeds": [],
        "youtube_channels": [
            {
                "name": "OpenAI",
                "category": "youtube",
                "url": "https://www.youtube.com/@OpenAI",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Anthropic",
                "category": "youtube",
                "url": "https://www.youtube.com/@AnthropicAI",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Google DeepMind",
                "category": "youtube",
                "url": "https://www.youtube.com/@GoogleDeepMind",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Hugging Face",
                "category": "youtube",
                "url": "https://www.youtube.com/@HuggingFace",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Two Minute Papers",
                "category": "youtube",
                "url": "https://www.youtube.com/@TwoMinutePapers",
                "source_kind": "youtube_channel",
            },
            {
                "name": "AI Explained",
                "category": "youtube",
                "url": "https://www.youtube.com/@aiexplained-official",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Matthew Berman",
                "category": "youtube",
                "url": "https://www.youtube.com/@MatthewBerman",
                "source_kind": "youtube_channel",
            },
        ],
        "github_sources": [
            {
                "name": "OpenAI Agents SDK",
                "category": "github",
                "repo": "openai/openai-agents-python",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "MCP Servers",
                "category": "github",
                "repo": "modelcontextprotocol/servers",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "OPC Skills",
                "category": "github",
                "repo": "ReScienceLab/opc-skills",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "OpenClaw",
                "category": "github",
                "repo": "openclaw/openclaw",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "AutoGen",
                "category": "github",
                "repo": "microsoft/autogen",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "LangGraph",
                "category": "github",
                "repo": "langchain-ai/langgraph",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "CrewAI",
                "category": "github",
                "repo": "crewAIInc/crewAI",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "browser-use",
                "category": "github",
                "repo": "browser-use/browser-use",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "vLLM",
                "category": "github",
                "repo": "vllm-project/vllm",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "Transformers",
                "category": "github",
                "repo": "huggingface/transformers",
                "mode": "releases",
                "source_kind": "github_release",
            },
        ],
        "x_accounts": [
            {"name": "OpenAI", "category": "x", "handle": "OpenAI", "source_kind": "x_allowlist"},
            {"name": "Anthropic", "category": "x", "handle": "AnthropicAI", "source_kind": "x_allowlist"},
            {"name": "Google DeepMind", "category": "x", "handle": "GoogleDeepMind", "source_kind": "x_allowlist"},
            {"name": "Hugging Face", "category": "x", "handle": "huggingface", "source_kind": "x_allowlist"},
            {"name": "Sam Altman", "category": "x", "handle": "sama", "source_kind": "x_allowlist"},
            {"name": "Andrej Karpathy", "category": "x", "handle": "karpathy", "source_kind": "x_allowlist"},
            {"name": "Harrison Chase", "category": "x", "handle": "hwchase17", "source_kind": "x_allowlist"},
        ],
        "product_hunt": {
            "enabled": True,
            "count": 18,
            "target_topics": [
                "ai agents",
                "llms",
                "ai infrastructure",
                "developer tools",
                "artificial intelligence",
                "open source",
                "api",
            ],
            "headline_min_checks": 2,
            "builder_surface_probe_limit": 8,
        },
        "mass_hot_topics": [],
        "scoring": {
            "headline_threshold": 11,
            "top_signal_limit": 8,
            "mass_hot_limit": 6,
            "source_weights": {
                "official": 5,
                "github": 4,
                "x": 7,
                "product_hunt": 6,
                "trendradar": 7,
                "reddit": 4,
                "paper": 2,
                "youtube": 3,
                "other": 1,
            },
            "cross_verify_bonus": 1.5,
            "fresh_hours_bonus_window": 48,
            "live_signal_max_age_hours": 72,
            "mass_hot_min_score": 10,
        },
    }


def dedupe_source_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        identity = "|".join(
            [
                compact_text(str(item.get("url", ""))).lower(),
                compact_text(str(item.get("repo", ""))).lower(),
                compact_text(str(item.get("handle", ""))).lower(),
                compact_text(str(item.get("name", ""))).lower(),
            ]
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(item)
    return deduped


def merge_nested_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_nested_dict(dict(merged.get(key, {})), value)
        else:
            merged[key] = value
    return merged


def normalize_ai_daily_signal_config(config: dict[str, Any]) -> dict[str, Any]:
    defaults = build_default_ai_daily_signal_project()
    normalized = merge_nested_dict(defaults, config)

    legacy_feeds = list(config.get("feeds", []))
    official_categories = {"official", "company", "product"}
    official_legacy_feeds = [
        dict(item, source_kind=item.get("source_kind") or "official_feed")
        for item in legacy_feeds
        if compact_text(str(item.get("category", ""))).lower() in official_categories
    ]
    community_legacy_feeds = [
        dict(item, source_kind=item.get("source_kind") or "community_feed")
        for item in legacy_feeds
        if compact_text(str(item.get("category", ""))).lower() not in official_categories
    ]

    normalized["official_feeds"] = dedupe_source_dicts(
        defaults["official_feeds"] + official_legacy_feeds + list(config.get("official_feeds", []))
    )
    normalized["community_feeds"] = dedupe_source_dicts(
        defaults["community_feeds"] + community_legacy_feeds + list(config.get("community_feeds", []))
    )
    normalized["feeds"] = dedupe_source_dicts(legacy_feeds)
    normalized["youtube_channels"] = dedupe_source_dicts(
        defaults["youtube_channels"] + list(config.get("youtube_channels", []))
    )
    normalized["github_sources"] = dedupe_source_dicts(
        defaults["github_sources"] + list(config.get("github_sources", []))
    )
    normalized["x_accounts"] = dedupe_source_dicts(
        defaults["x_accounts"] + list(config.get("x_accounts", []))
    )
    normalized["product_hunt"] = merge_nested_dict(defaults["product_hunt"], dict(config.get("product_hunt", {})))
    normalized["scoring"] = merge_nested_dict(defaults["scoring"], dict(config.get("scoring", {})))
    return normalized


def normalize_opc_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(config)
    projects = dict(normalized.get("projects", {}))
    projects["ai_daily_signal"] = normalize_ai_daily_signal_config(dict(projects.get("ai_daily_signal", {})))
    normalized["projects"] = projects
    return normalized


def ensure_opc_config() -> Path:
    ensure_dirs(CONFIG_DIR, DAILY_REPORT_DIR)
    if OPC_CONFIG_PATH.exists():
        return OPC_CONFIG_PATH

    config = {
        "workspace_name": DEFAULT_WORKSPACE_NAME,
        "parent_folder_token": DEFAULT_PARENT_FOLDER_TOKEN,
        "projects": {
            "enterprise_ai_service": {
                "folder_name": "01 Enterprise AI Service Research",
                "seed_docs": [
                    {
                        "title": "Enterprise AI market demand and service report",
                        "path": str(REPORT_DIR / "enterprise_ai_market_demand_and_service_report_20260404.md"),
                    },
                    {
                        "title": "Enterprise AI demand service design",
                        "path": str(REPORT_DIR / "enterprise_ai_demand_service_design_20260404.md"),
                    },
                ],
            },
            "pr_radar": {
                "folder_name": "02 OpenClaw PR Radar",
                "repo_slugs": [DEFAULT_PR_REPO],
                "daily_title_template": "OpenClaw PR 闆疯揪 / PR Radar - {date}",
            },
            "ai_daily_signal": {
                "folder_name": "03 AI Daily Signal",
                "daily_title_template": "AI 姣忔棩淇″彿 / Daily Signal - {date}",
                "feeds": [
                    {
                        "name": "Reddit / r/LocalLLaMA",
                        "category": "reddit",
                        "url": "https://www.reddit.com/r/LocalLLaMA/.rss",
                    },
                    {
                        "name": "Reddit / r/MachineLearning",
                        "category": "reddit",
                        "url": "https://www.reddit.com/r/MachineLearning/.rss",
                    },
                    {
                        "name": "Reddit / r/artificial",
                        "category": "reddit",
                        "url": "https://www.reddit.com/r/artificial/.rss",
                    },
                    {
                        "name": "arXiv cs.AI",
                        "category": "paper",
                        "url": "https://export.arxiv.org/rss/cs.AI",
                    },
                    {
                        "name": "Hugging Face Blog",
                        "category": "product",
                        "url": "https://huggingface.co/blog/feed.xml",
                    },
                    {
                        "name": "OpenAI News",
                        "category": "company",
                        "url": "https://openai.com/news/rss.xml",
                    },
                ],
                "youtube_channels": [
                    {
                        "name": "OpenAI",
                        "category": "youtube",
                        "url": "https://www.youtube.com/@OpenAI",
                    },
                    {
                        "name": "Google DeepMind",
                        "category": "youtube",
                        "url": "https://www.youtube.com/@GoogleDeepMind",
                    },
                    {
                        "name": "LangChain",
                        "category": "youtube",
                        "url": "https://www.youtube.com/@LangChain",
                    },
                    {
                        "name": "Hugging Face",
                        "category": "youtube",
                        "url": "https://www.youtube.com/@HuggingFace",
                    },
                ],
            },
        },
    }
    config["projects"]["ai_daily_signal"] = build_default_ai_daily_signal_project()
    OPC_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return OPC_CONFIG_PATH


def load_opc_config() -> dict[str, Any]:
    ensure_opc_config()
    return normalize_opc_config(json.loads(OPC_CONFIG_PATH.read_text(encoding="utf-8")))


def save_opc_state(state: dict[str, Any]) -> Path:
    ensure_dirs(OPC_STATE_PATH.parent)
    OPC_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return OPC_STATE_PATH


def load_opc_state() -> dict[str, Any]:
    if not OPC_STATE_PATH.exists():
        return {}
    return json.loads(OPC_STATE_PATH.read_text(encoding="utf-8"))


def get_ai_daily_signal_state_bucket(state: dict[str, Any]) -> dict[str, Any]:
    projects = state.setdefault("projects", {})
    ai_daily_signal = projects.setdefault("ai_daily_signal", {})
    return ai_daily_signal.setdefault("github_repo_snapshots", {})


def get_ai_daily_signal_runtime_bucket(state: dict[str, Any]) -> dict[str, Any]:
    projects = state.setdefault("projects", {})
    return projects.setdefault("ai_daily_signal", {})


def select_x_accounts_for_run(
    *,
    sources: list[dict[str, Any]],
    signal_config: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    strategy = dict(signal_config.get("x_strategy", {}))
    max_accounts = int(strategy.get("max_accounts_per_run", len(sources)) or len(sources))
    if max_accounts <= 0 or len(sources) <= max_accounts:
        return list(sources)
    if not bool(strategy.get("rotation_enabled", True)):
        return list(sources)[:max_accounts]
    runtime_bucket = get_ai_daily_signal_runtime_bucket(state)
    rotation_state = runtime_bucket.setdefault("x_allowlist_rotation", {})
    offset = int(rotation_state.get("offset", 0) or 0) % len(sources)
    selected = [sources[(offset + index) % len(sources)] for index in range(max_accounts)]
    rotation_state["offset"] = (offset + max_accounts) % len(sources)
    rotation_state["updated_at"] = datetime.now(UTC).isoformat()
    return selected


def is_retryable_lark_cli_error(message: str) -> bool:
    text = compact_text(message).lower()
    retry_markers = [
        "tls handshake timeout",
        "context deadline exceeded",
        "connection reset by peer",
        "i/o timeout",
        "timeout awaiting response headers",
        "failed to get tenant access token",
        "temporarily unavailable",
        "network temporarily unavailable",
        " eof",
    ]
    return any(marker in text for marker in retry_markers)


def run_lark_cli_json(args: list[str], *, timeout_seconds: int = 90, max_attempts: int = 3) -> dict[str, Any]:
    command = [str(resolve_lark_cli_path()), *args]
    last_error = ""
    for attempt in range(1, max(max_attempts, 1) + 1):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(timeout_seconds, 1),
            )
        except subprocess.TimeoutExpired as exc:
            last_error = f"lark-cli timed out after {timeout_seconds}s"
            if attempt >= max_attempts:
                raise IntelWorkspaceError(last_error) from exc
            time.sleep(min(attempt * 3, 10))
            continue

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if completed.returncode == 0:
            if not stdout:
                return {}
            try:
                return json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise IntelWorkspaceError(f"Failed to parse lark-cli JSON output: {stdout}") from exc

        message = stderr or stdout or f"lark-cli exited with code {completed.returncode}"
        last_error = message
        if attempt >= max_attempts or not is_retryable_lark_cli_error(message):
            raise IntelWorkspaceError(message)
        time.sleep(min(attempt * 3, 10))

    raise IntelWorkspaceError(last_error or "lark-cli failed without error message")


def resolve_lark_cli_path() -> Path:
    for candidate in LARK_CLI_CANDIDATES:
        if candidate and candidate.exists():
            return candidate
    raise IntelWorkspaceError("Unable to locate lark-cli executable. Set LARK_CLI_PATH or install @larksuite/cli.")


def list_lark_folder(folder_token: str = "") -> list[dict[str, Any]]:
    params: dict[str, Any] = {"page_size": 200}
    if folder_token:
        params["folder_token"] = folder_token
    response = run_lark_cli_json(
        [
            "drive",
            "files",
            "list",
            "--as",
            "bot",
            "--format",
            "json",
            "--params",
            json.dumps(params, ensure_ascii=False),
        ]
    )
    return list(response.get("data", {}).get("files", []) or response.get("files", []) or [])


def find_child_by_name(folder_token: str, name: str) -> dict[str, Any] | None:
    target = compact_text(name)
    for item in list_lark_folder(folder_token):
        if compact_text(str(item.get("name", ""))) == target:
            return item
    return None


def create_lark_folder(parent_token: str, name: str) -> dict[str, Any]:
    response = run_lark_cli_json(
        [
            "drive",
            "files",
            "create_folder",
            "--as",
            "bot",
            "--format",
            "json",
            "--data",
            json.dumps({"folder_token": parent_token, "name": name}, ensure_ascii=False),
        ]
    )
    data = response.get("data", response)
    return {
        "token": compact_text(str(data.get("token", ""))),
        "url": compact_text(str(data.get("url", ""))),
        "name": name,
        "type": "folder",
    }


def ensure_lark_folder(parent_token: str, name: str) -> dict[str, Any]:
    found = find_child_by_name(parent_token, name)
    if found:
        return {
            "token": compact_text(str(found.get("token", ""))),
            "url": compact_text(str(found.get("url", ""))),
            "name": compact_text(str(found.get("name", name))),
            "type": compact_text(str(found.get("type", "folder"))) or "folder",
        }
    return create_lark_folder(parent_token, name)


def create_lark_doc(folder_token: str, title: str, markdown: str) -> dict[str, Any]:
    markdown_lines = split_markdown_for_lark_cli(markdown)
    existing = find_child_by_name(folder_token, title)
    if existing:
        sync_lark_doc_markdown(
            doc_ref=compact_text(str(existing.get("url", ""))) or compact_text(str(existing.get("token", ""))),
            markdown=markdown,
            new_title=title,
        )
        ensure_doc_public_readable(compact_text(str(existing.get("token", ""))))
        return {
            "token": compact_text(str(existing.get("token", ""))),
            "url": compact_text(str(existing.get("url", ""))),
            "title": title,
            "type": "docx",
        }

    response = run_lark_doc_shortcut(
        "+create",
        [
            "--folder-token",
            folder_token,
            "--title",
            title,
            "--markdown",
            markdown_lines[0],
        ],
    )
    data = response.get("data", response)
    token = compact_text(str(data.get("document_id", data.get("token", ""))))
    url = compact_text(str(data.get("url", "")))
    if not token or not url:
        existing = find_child_by_name(folder_token, title)
        if existing:
            token = compact_text(str(existing.get("token", token)))
            url = compact_text(str(existing.get("url", url)))
    doc_ref = url or token
    for line in markdown_lines[1:]:
        update_lark_doc(doc_ref=doc_ref, markdown=line, mode="append")
    ensure_doc_public_readable(token)
    return {"token": token, "url": url, "title": title, "type": "docx"}


def split_markdown_for_lark_cli(markdown: str) -> list[str]:
    lines = [line.rstrip() for line in markdown.splitlines()]
    normalized = [line for line in lines if line.strip()]
    return normalized or [" "]


def run_lark_doc_shortcut(subcommand: str, args: list[str]) -> dict[str, Any]:
    last_error: IntelWorkspaceError | None = None
    for identity in LARK_DOC_WRITE_IDENTITIES:
        try:
            return run_lark_cli_json(["docs", subcommand, "--as", identity, *args], timeout_seconds=180, max_attempts=5)
        except IntelWorkspaceError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise IntelWorkspaceError(f"Failed to run docs {subcommand}.")


def sync_lark_doc_markdown(*, doc_ref: str, markdown: str, new_title: str = "") -> dict[str, Any]:
    markdown_lines = split_markdown_for_lark_cli(markdown)
    response = update_lark_doc(doc_ref=doc_ref, markdown=markdown_lines[0], new_title=new_title, mode="overwrite")
    for line in markdown_lines[1:]:
        update_lark_doc(doc_ref=doc_ref, markdown=line, mode="append")
    return response


def update_lark_doc(*, doc_ref: str, markdown: str, new_title: str = "", mode: str = "overwrite") -> dict[str, Any]:
    args = ["--doc", doc_ref, "--mode", mode, "--markdown", markdown]
    if new_title:
        args.extend(["--new-title", new_title])
    return run_lark_doc_shortcut("+update", args)


def ensure_doc_public_readable(document_token: str) -> None:
    token = compact_text(document_token)
    if not token:
        return
    run_lark_cli_json(
        [
            "api",
            "PATCH",
            f"/open-apis/drive/v2/permissions/{token}/public",
            "--as",
            "bot",
            "--format",
            "json",
            "--params",
            json.dumps({"type": "docx"}, ensure_ascii=False),
            "--data",
            json.dumps(
                {
                    "external_access_entity": "open",
                    "security_entity": "anyone_can_view",
                    "comment_entity": "anyone_can_view",
                    "copy_entity": "anyone_can_view",
                    "share_entity": "anyone",
                    "manage_collaborator_entity": "collaborator_can_view",
                    "link_share_entity": "anyone_readable",
                    "lock_switch": False,
                },
                ensure_ascii=False,
            ),
        ]
    )


def normalize_project_doc_entry(doc: dict[str, Any], *, fallback_title: str = "") -> dict[str, Any]:
    token = compact_text(str(doc.get("token", "")))
    url = compact_text(str(doc.get("url", "")))
    title = compact_text(str(doc.get("title", ""))) or compact_text(fallback_title)
    entry = {"token": token, "url": url, "title": title, "type": "docx"}
    return entry


def get_project_daily_doc(state: dict[str, Any], project_key: str) -> dict[str, Any]:
    project_bucket = (((state.get("projects") or {}).get(project_key) or {}))
    daily_doc = normalize_project_doc_entry(dict(project_bucket.get("daily_doc", {}) or {}))
    if daily_doc.get("token") or daily_doc.get("url"):
        return daily_doc
    docs = list(project_bucket.get("docs", []) or [])
    if docs:
        return normalize_project_doc_entry(dict(docs[0] or {}))
    return {}


def remember_project_daily_doc(state: dict[str, Any], project_key: str, doc: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_project_doc_entry(doc)
    if not (normalized.get("token") or normalized.get("url")):
        return normalized
    projects = state.setdefault("projects", {})
    project_bucket = projects.setdefault(project_key, {})
    project_bucket["daily_doc"] = normalized
    docs = [normalize_project_doc_entry(dict(current or {})) for current in list(project_bucket.get("docs", []) or [])]
    docs = [
        current
        for current in docs
        if current.get("token") != normalized.get("token") and current.get("url") != normalized.get("url")
    ]
    project_bucket["docs"] = [normalized, *docs]
    return normalized


def bootstrap_opc_workspace(
    *,
    parent_folder_token: str = "",
    workspace_name: str = "",
    publish_seed_docs: bool = True,
) -> dict[str, Any]:
    config = load_opc_config()
    root_parent_token = compact_text(parent_folder_token) or compact_text(str(config.get("parent_folder_token", "")))
    if not root_parent_token:
        raise IntelWorkspaceError("No parent folder token configured for OPC workspace bootstrap.")

    root_name = compact_text(workspace_name) or compact_text(str(config.get("workspace_name", ""))) or DEFAULT_WORKSPACE_NAME
    root_folder = ensure_lark_folder(root_parent_token, root_name)

    projects_state: dict[str, Any] = {}
    for project_key, project_config in dict(config.get("projects", {})).items():
        folder = ensure_lark_folder(root_folder["token"], compact_text(str(project_config.get("folder_name", project_key))))
        projects_state[project_key] = {"folder": folder, "docs": []}

        if publish_seed_docs and project_key == "enterprise_ai_service":
            for doc_config in list(project_config.get("seed_docs", [])):
                doc_path = Path(str(doc_config.get("path", "")))
                if not doc_path.exists():
                    continue
                existing = find_child_by_name(folder["token"], compact_text(str(doc_config.get("title", doc_path.stem))))
                if existing:
                    projects_state[project_key]["docs"].append(
                        {
                            "title": compact_text(str(existing.get("name", ""))),
                            "token": compact_text(str(existing.get("token", ""))),
                            "url": compact_text(str(existing.get("url", ""))),
                        }
                    )
                    continue
                created_doc = publish_markdown_to_feishu(
                    markdown_path=doc_path,
                    title=compact_text(str(doc_config.get("title", doc_path.stem))),
                    create_new=True,
                    folder_token=folder["token"],
                    public_readable=True,
                )
                projects_state[project_key]["docs"].append(
                    {
                        "title": compact_text(str(doc_config.get("title", doc_path.stem))),
                        "token": created_doc["target_token"],
                        "url": created_doc["target_url"],
                    }
                )

    state = {
        "workspace_name": root_name,
        "parent_folder_token": root_parent_token,
        "root_folder": root_folder,
        "projects": projects_state,
        "bootstrapped_at": datetime.now(UTC).isoformat(),
        "config_path": str(OPC_CONFIG_PATH),
    }
    save_opc_state(state)
    return state


def github_request(url: str, *, token: str = "", accept: str = "application/vnd.github+json") -> Any:
    headers = {
        "Accept": accept,
        "User-Agent": "opc-intel-bot",
    }
    if not token:
        token = get_env_value("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request_obj = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request_obj, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise IntelWorkspaceError(f"GitHub API error {exc.code}: {body}") from exc


def generate_github_pr_digest(
    *,
    repo_slugs: list[str] | None = None,
    limit: int = 12,
    since_days: int = 7,
    publish_feishu: bool = False,
) -> dict[str, Any]:
    config = load_opc_config()
    repos = repo_slugs or list(config["projects"]["pr_radar"].get("repo_slugs", []))
    if not repos:
        raise IntelWorkspaceError("No GitHub repo slugs configured for PR radar.")

    ensure_dirs(DAILY_REPORT_DIR)
    github_token = compact_text(os.getenv("GITHUB_TOKEN", ""))
    collected: list[dict[str, Any]] = []
    since_dt = datetime.now(UTC) - timedelta(days=max(since_days, 1))

    for repo_slug in repos:
        api_url = f"https://api.github.com/repos/{repo_slug}/pulls?state=all&sort=updated&direction=desc&per_page=30"
        pulls = github_request(api_url, token=github_token)
        for pr in pulls:
            updated_at = parse_iso8601(pr.get("updated_at", ""))
            if updated_at and updated_at < since_dt:
                continue
            collected.append(
                {
                    "repo_slug": repo_slug,
                    "number": pr.get("number"),
                    "title": compact_text(str(pr.get("title", ""))),
                    "state": compact_text(str(pr.get("state", ""))),
                    "draft": bool(pr.get("draft", False)),
                    "merged_at": compact_text(str(pr.get("merged_at", ""))),
                    "html_url": compact_text(str(pr.get("html_url", ""))),
                    "author": compact_text(str((pr.get("user") or {}).get("login", ""))),
                    "updated_at": compact_text(str(pr.get("updated_at", ""))),
                    "created_at": compact_text(str(pr.get("created_at", ""))),
                    "comments": int(pr.get("comments", 0) or 0),
                    "commits": int(pr.get("commits", 0) or 0),
                }
            )

    collected.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    top_rows = enrich_github_pr_rows(collected[: max(limit, 1)], github_token=github_token)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = DAILY_REPORT_DIR / f"github_pr_radar_{today.replace('-', '')}.md"
    title_template = compact_text(
        str(config["projects"]["pr_radar"].get("daily_title_template", "OpenClaw PR 雷达 - {date}"))
    )
    report_title = title_template.format(date=today)
    report_markdown = render_github_pr_digest(title=report_title, rows=top_rows, repo_slugs=repos)
    report_path.write_text(report_markdown, encoding="utf-8-sig")

    published_doc: dict[str, Any] | None = None
    if publish_feishu:
        state = load_opc_state()
        folder_token = compact_text(
            str((((state.get("projects") or {}).get("pr_radar") or {}).get("folder") or {}).get("token", ""))
        )
        if not folder_token:
            raise IntelWorkspaceError("OPC workspace not initialized for PR radar publishing.")
        published_doc = create_lark_doc(folder_token, report_title, report_markdown)

    return {
        "report_path": str(report_path),
        "report_title": report_title,
        "repo_slugs": repos,
        "pr_count": len(top_rows),
        "published_doc": published_doc or {},
    }


def render_github_pr_digest(*, title: str, rows: list[dict[str, Any]], repo_slugs: list[str]) -> str:
    merged_count = sum(1 for row in rows if row.get("merged_at"))
    open_count = sum(1 for row in rows if row.get("state") == "open" and not row.get("merged_at"))
    closed_count = sum(1 for row in rows if row.get("state") == "closed" and not row.get("merged_at"))
    lines = [
        f"# {title}",
        "",
        "## 整体速览",
        "",
        *summarize_digest_overview(rows),
        "",
        "## 摘要",
        "",
        f"- 跟踪仓库：{', '.join(repo_slugs)}",
        f"- 纳入日报的 PR 数：{len(rows)}",
        f"- 进行中：{open_count}",
        f"- 已合并：{merged_count}",
        f"- 已关闭未合并：{closed_count}",
        "",
        "## 最新 PR",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        status = translate_pr_status(row)
        draft_flag = "草稿" if row.get("draft") else "可评审"
        lines.extend(
            [
                f"### {index}. {row['title']}",
                f"- 仓库：`{row['repo_slug']}`",
                f"- PR: #{row['number']} | {status} | {draft_flag}",
                f"- 作者：`{row['author']}`",
                f"- 最近更新时间：{row['updated_at']}",
                f"- 摘要：{row.get('body_summary') or '暂无摘要。'}",
                f"- 快读判断：{row.get('quick_take') or '常规变更，按需略读。'}",
                f"- 影响：{row.get('impact_summary') or '暂无影响说明。'}",
                f"- 文件：{row.get('file_summary') or '暂无文件清单。'}",
                f"- 链接：{row['html_url']}",
                "",
            ]
        )
    if not rows:
        lines.extend(["- 当前回溯窗口内没有发现新的 PR 更新。", ""])
    return "\n".join(lines).strip() + "\n"


def select_community_video_hotspots(items: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in items
        if normalize_signal_category(item) in {"reddit", "youtube"}
        and compact_text(str(item.get("title", "")))
        and compact_text(str(item.get("link", "")))
    ]
    if not candidates:
        return []
    return sorted(
        candidates,
        key=lambda item: (
            1 if item_has_launch_language(item) else 0,
            1 if item_has_builder_surface(item) else 0,
            compact_text(str(item.get("published_sort", ""))) or compact_text(str(item.get("published", ""))),
        ),
        reverse=True,
    )[: max(limit, 1)]


def select_x_kol_hotspots(items: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in items
        if normalize_signal_category(item) == "x"
        and compact_text(str(item.get("title", "")))
        and compact_text(str(item.get("link", "")))
    ]
    if not candidates:
        return []
    return sorted(
        candidates,
        key=lambda item: (
            int(item.get("engagement_score", 0) or 0),
            1 if compact_text(str(item.get("source_kind", ""))) == "x_kol" else 0,
            compact_text(str(item.get("published_sort", ""))) or compact_text(str(item.get("published", ""))),
        ),
        reverse=True,
    )[: max(limit, 1)]


def merge_signal_items_with_supplements(
    primary_items: list[dict[str, Any]],
    supplement_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*primary_items, *supplement_items]:
        key = compact_text(str(item.get("canonical_link", ""))) or compact_text(str(item.get("link", "")))
        if not key:
            key = compact_text(str(item.get("title", ""))).lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def generate_ai_news_digest(
    *,
    limit_per_source: int = 5,
    max_items: int = 18,
    since_days: int = 7,
    publish_feishu: bool = False,
) -> dict[str, Any]:
    config = load_opc_config()
    signal_config = normalize_ai_daily_signal_config(dict(config["projects"]["ai_daily_signal"]))
    ensure_dirs(DAILY_REPORT_DIR)

    raw_items, source_health = collect_ai_signal_items(
        signal_config=signal_config,
        limit_per_source=max(limit_per_source, 1),
        since_days=max(since_days, 1),
    )
    ranked_items, top_signals = finalize_ai_signal_items(
        items=raw_items,
        signal_config=signal_config,
        max_items=max(max_items, 1),
        since_days=max(since_days, 1),
    )
    community_video_hotspots = select_community_video_hotspots(raw_items, limit=6)
    x_kol_hotspots = select_x_kol_hotspots(raw_items, limit=6)
    report_items = merge_signal_items_with_supplements(ranked_items, [*community_video_hotspots, *x_kol_hotspots])
    mass_hot_topics = build_mass_hot_topics(items=report_items, signal_config=signal_config)

    today = datetime.now().strftime("%Y-%m-%d")
    report_path = DAILY_REPORT_DIR / f"ai_daily_signal_{today.replace('-', '')}.md"
    report_markdown = render_ai_news_digest(
        today=today,
        items=report_items,
        top_signals=top_signals,
        mass_hot_topics=mass_hot_topics,
        source_health=source_health,
    )
    report_path.write_text(report_markdown, encoding="utf-8-sig")

    published_doc: dict[str, Any] | None = None
    if publish_feishu:
        state = load_opc_state()
        project_bucket = ((state.get("projects") or {}).get("ai_daily_signal") or {})
        folder_token = compact_text(str((project_bucket.get("folder") or {}).get("token", "")))
        if not folder_token:
            raise IntelWorkspaceError("OPC workspace not initialized for AI daily signal publishing.")
        daily_doc_title = compact_text(str(project_bucket.get("daily_doc_title", ""))) or "AI 每日信号（自动更新）"
        existing_daily_doc = get_project_daily_doc(state, "ai_daily_signal")
        existing_doc_ref = compact_text(str(existing_daily_doc.get("url", ""))) or compact_text(
            str(existing_daily_doc.get("token", ""))
        )
        if existing_doc_ref:
            sync_lark_doc_markdown(doc_ref=existing_doc_ref, markdown=report_markdown, new_title=daily_doc_title)
            ensure_doc_public_readable(compact_text(str(existing_daily_doc.get("token", ""))))
            published_doc = normalize_project_doc_entry(existing_daily_doc, fallback_title=daily_doc_title)
        else:
            published_doc = create_lark_doc(folder_token, daily_doc_title, report_markdown)
        remember_project_daily_doc(state, "ai_daily_signal", published_doc)
        save_opc_state(state)

    title_template = compact_text(
        str(config["projects"]["ai_daily_signal"].get("daily_title_template", "AI 每日信号 - {date}"))
    )
    return {
        "today": today,
        "report_path": str(report_path),
        "report_title": title_template.format(date=today),
        "report_markdown": report_markdown,
        "item_count": len(report_items),
        "top_signal_count": len(top_signals),
        "items": report_items,
        "top_signals": top_signals,
        "mass_hot_topics": mass_hot_topics,
        "community_video_hotspots": community_video_hotspots,
        "x_kol_hotspots": x_kol_hotspots,
        "source_health": source_health,
        "published_doc": published_doc or {},
    }


def resolve_trendradar_paths(bridge_config: dict[str, Any]) -> tuple[Path, Path]:
    repo_path = Path(
        compact_text(str(bridge_config.get("repo_path", ""))) or str(DEFAULT_TRENDRADAR_REPO)
    ).expanduser()
    output_dir_value = compact_text(str(bridge_config.get("output_dir", "")))
    output_dir = Path(output_dir_value).expanduser() if output_dir_value else repo_path / "output"
    return repo_path, output_dir


def parse_trendradar_crawl_datetime(date_str: str, crawl_time: str) -> datetime | None:
    text = compact_text(crawl_time)
    if not text:
        return None
    parsed = parse_flexible_datetime(text)
    if parsed:
        return parsed
    if re.fullmatch(r"\d{2}-\d{2}", text):
        text = text.replace("-", ":")
    if re.fullmatch(r"\d{2}:\d{2}", text):
        try:
            local_dt = datetime.fromisoformat(f"{date_str}T{text}:00").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return local_dt.astimezone(UTC)
        except Exception:
            return None
    return None


def get_trendradar_latest_crawl_info(output_dir: Path, date_str: str) -> tuple[str, datetime | None]:
    db_path = output_dir / "news" / f"{date_str}.db"
    if not db_path.exists():
        return "", None
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT crawl_time FROM crawl_records ORDER BY crawl_time DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return "", None
    crawl_time = compact_text(str(row[0] or ""))
    return crawl_time, parse_trendradar_crawl_datetime(date_str, crawl_time)


def run_trendradar_bridge(repo_path: Path, timeout_seconds: int) -> None:
    if not repo_path.exists():
        raise IntelWorkspaceError(f"TrendRadar repo not found: {repo_path}")
    command = ["uv", "run", "python", "-m", "trendradar"]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["GITHUB_ACTIONS"] = "true"
    completed = subprocess.run(
        command,
        cwd=str(repo_path),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(timeout_seconds, 30),
    )
    if completed.returncode != 0:
        detail = compact_text(completed.stderr or completed.stdout)[:400]
        raise IntelWorkspaceError(f"TrendRadar run failed: {detail or f'rc={completed.returncode}'}")


def load_trendradar_current_rows(output_dir: Path, date_str: str) -> tuple[str, list[dict[str, Any]]]:
    db_path = output_dir / "news" / f"{date_str}.db"
    if not db_path.exists():
        return "", []
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        latest_row = connection.execute(
            "SELECT crawl_time FROM crawl_records ORDER BY crawl_time DESC LIMIT 1"
        ).fetchone()
        if not latest_row:
            return "", []
        crawl_time = compact_text(str(latest_row["crawl_time"] or ""))
        rows = connection.execute(
            """
            SELECT
                n.title,
                n.rank,
                n.url,
                n.mobile_url,
                n.first_crawl_time,
                n.last_crawl_time,
                n.crawl_count,
                n.platform_id,
                COALESCE(p.name, n.platform_id) AS platform_name
            FROM news_items n
            LEFT JOIN platforms p ON n.platform_id = p.id
            WHERE n.last_crawl_time = ?
            ORDER BY n.platform_id, n.rank, n.title
            """,
            (crawl_time,),
        ).fetchall()
    finally:
        connection.close()
    return crawl_time, [dict(row) for row in rows]


def match_trendradar_topic_groups(
    *,
    title: str,
    summary: str,
    bridge_config: dict[str, Any],
) -> list[str]:
    haystack = compact_text(f"{title} {summary}").lower()
    if not haystack:
        return []
    exclude_terms = [compact_text(str(value)).lower() for value in list(bridge_config.get("exclude_terms", [])) if value]
    if exclude_terms and any(haystack_contains_term(haystack, term) for term in exclude_terms):
        return []
    matched: list[str] = []
    for group in list(bridge_config.get("topic_groups", [])):
        group_name = compact_text(str(group.get("name", ""))) or "AI"
        group_terms = [compact_text(str(value)).lower() for value in list(group.get("terms", [])) if value]
        if any(haystack_contains_term(haystack, term) for term in group_terms):
            matched.append(group_name)
    return matched


def fetch_trendradar_bridge_items(
    *,
    bridge_config: dict[str, Any],
    since_days: int,
) -> list[dict[str, Any]]:
    if not bridge_config.get("enabled", True):
        return []

    repo_path, output_dir = resolve_trendradar_paths(bridge_config)
    now_local = datetime.now(ZoneInfo("Asia/Shanghai"))
    date_str = now_local.strftime("%Y-%m-%d")
    latest_crawl_time, latest_crawl_dt = get_trendradar_latest_crawl_info(output_dir, date_str)
    min_refresh_minutes = max(int(bridge_config.get("min_refresh_minutes", 45) or 45), 0)
    if not latest_crawl_dt or (
        min_refresh_minutes > 0
        and (datetime.now(UTC) - latest_crawl_dt).total_seconds() / 60 > min_refresh_minutes
    ):
        run_trendradar_bridge(repo_path, int(bridge_config.get("timeout_seconds", 180) or 180))
        latest_crawl_time, latest_crawl_dt = get_trendradar_latest_crawl_info(output_dir, date_str)

    if not latest_crawl_time:
        raise IntelWorkspaceError("TrendRadar bridge did not produce a latest crawl record.")

    _, rows = load_trendradar_current_rows(output_dir, date_str)
    if not rows:
        return []

    limit = max(int(bridge_config.get("limit", 12) or 12), 1)
    max_rank = max(int(bridge_config.get("max_rank", 15) or 15), 1)
    cutoff_dt = datetime.now(UTC) - timedelta(days=max(since_days, 1))
    selected: list[dict[str, Any]] = []
    for row in rows:
        rank = int(row.get("rank", 0) or 0)
        if rank <= 0 or rank > max_rank:
            continue
        published = compact_text(str(row.get("last_crawl_time", ""))) or latest_crawl_time
        published_dt = parse_trendradar_crawl_datetime(date_str, published) or latest_crawl_dt
        if published_dt and published_dt < cutoff_dt:
            continue
        title = compact_text(str(row.get("title", "")))
        summary = ""
        topic_matches = match_trendradar_topic_groups(title=title, summary=summary, bridge_config=bridge_config)
        if not topic_matches:
            continue
        platform_name = compact_text(str(row.get("platform_name", ""))) or compact_text(str(row.get("platform_id", ""))) or "TrendRadar"
        display_published = published_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S%z") if published_dt else date_str
        selected.append(
            build_news_item(
                source={
                    "name": f"TrendRadar / {platform_name}",
                    "category": "trendradar",
                    "source_kind": "trendradar_hotlist",
                },
                title=title,
                link=compact_text(str(row.get("url", ""))) or compact_text(str(row.get("mobile_url", ""))),
                published=display_published,
                summary=f"TrendRadar 热榜命中：{platform_name} 第 {rank} 位；主题：{', '.join(topic_matches[:3])}",
                extra={
                    "headline_candidate": rank <= max(int(bridge_config.get("headline_rank_threshold", 5) or 5), 1),
                    "trendradar_platform": platform_name,
                    "trendradar_rank": rank,
                    "trendradar_topics": topic_matches,
                    "trendradar_crawl_time": latest_crawl_time,
                },
            )
        )
        if len(selected) >= limit:
            break
    return selected


def collect_ai_signal_items(
    *,
    signal_config: dict[str, Any],
    limit_per_source: int,
    since_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    source_health: list[dict[str, Any]] = []
    workspace_state = load_opc_state()

    source_groups = [
        ("official_feeds", signal_config.get("official_feeds", []), fetch_ai_source_items),
        ("community_feeds", signal_config.get("community_feeds", []), fetch_ai_source_items),
        ("youtube_channels", signal_config.get("youtube_channels", []), fetch_ai_source_items),
        ("github_sources", signal_config.get("github_sources", []), fetch_ai_source_items),
        ("x_accounts", signal_config.get("x_accounts", []), fetch_ai_source_items),
    ]
    for group_name, sources, fetcher in source_groups:
        selected_sources = list(sources)
        if group_name == "x_accounts":
            selected_sources = select_x_accounts_for_run(
                sources=selected_sources,
                signal_config=signal_config,
                state=workspace_state,
            )
        for source in selected_sources:
            if group_name == "x_accounts":
                delay_seconds = float(dict(signal_config.get("x_strategy", {})).get("delay_seconds", 0) or 0)
                if delay_seconds > 0 and source is not selected_sources[0]:
                    time.sleep(delay_seconds)
            started_at = time.time()
            try:
                fetched = fetcher(
                    source=source,
                    limit=limit_per_source,
                    since_days=since_days,
                    signal_config=signal_config,
                    state=workspace_state,
                )
                items.extend(fetched)
                source_health.append(
                    {
                        "group": group_name,
                        "name": compact_text(str(source.get("name", ""))) or group_name,
                        "status": "ok",
                        "count": len(fetched),
                        "detail": "",
                        "elapsed_ms": int((time.time() - started_at) * 1000),
                    }
                )
            except IntelWorkspaceError as exc:
                source_health.append(
                    {
                        "group": group_name,
                        "name": compact_text(str(source.get("name", ""))) or group_name,
                        "status": "skipped" if "requires" in compact_text(str(exc)).lower() else "error",
                        "count": 0,
                        "detail": compact_text(str(exc))[:160],
                        "elapsed_ms": int((time.time() - started_at) * 1000),
                    }
                )
            except Exception as exc:
                source_health.append(
                    {
                        "group": group_name,
                        "name": compact_text(str(source.get("name", ""))) or group_name,
                        "status": "error",
                        "count": 0,
                        "detail": compact_text(str(exc))[:160],
                        "elapsed_ms": int((time.time() - started_at) * 1000),
                    }
                )

    if signal_config.get("github_sources") or signal_config.get("x_accounts"):
        save_opc_state(workspace_state)

    trendradar_bridge = dict(signal_config.get("trendradar_bridge", {}))
    if trendradar_bridge.get("enabled", True):
        started_at = time.time()
        try:
            trendradar_items = fetch_trendradar_bridge_items(
                bridge_config=trendradar_bridge,
                since_days=since_days,
            )
            items.extend(trendradar_items)
            source_health.append(
                {
                    "group": "trendradar",
                    "name": "TrendRadar AI bridge",
                    "status": "ok",
                    "count": len(trendradar_items),
                    "detail": "",
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )
        except IntelWorkspaceError as exc:
            source_health.append(
                {
                    "group": "trendradar",
                    "name": "TrendRadar AI bridge",
                    "status": "error",
                    "count": 0,
                    "detail": compact_text(str(exc))[:160],
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )
        except Exception as exc:
            source_health.append(
                {
                    "group": "trendradar",
                    "name": "TrendRadar AI bridge",
                    "status": "error",
                    "count": 0,
                    "detail": compact_text(str(exc))[:160],
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )

    github_trending_config = dict(signal_config.get("github_trending", {}))
    if github_trending_config.get("enabled", True):
        started_at = time.time()
        try:
            trending_items = fetch_github_trending_items(
                github_trending_config=github_trending_config,
                limit=int(github_trending_config.get("count", limit_per_source) or limit_per_source),
            )
            items.extend(trending_items)
            source_health.append(
                {
                    "group": "github_trending",
                    "name": "GitHub Trending AI",
                    "status": "ok",
                    "count": len(trending_items),
                    "detail": "",
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )
        except IntelWorkspaceError as exc:
            source_health.append(
                {
                    "group": "github_trending",
                    "name": "GitHub Trending AI",
                    "status": "error",
                    "count": 0,
                    "detail": compact_text(str(exc))[:160],
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )

    product_hunt_config = dict(signal_config.get("product_hunt", {}))
    if product_hunt_config.get("enabled", True):
        started_at = time.time()
        try:
            ph_items = fetch_product_hunt_items(
                product_hunt_config=product_hunt_config,
                limit=max(int(product_hunt_config.get("count", limit_per_source)), 1),
            )
            items.extend(ph_items)
            source_health.append(
                {
                    "group": "product_hunt",
                    "name": "Product Hunt",
                    "status": "ok",
                    "count": len(ph_items),
                    "detail": "",
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )
        except IntelWorkspaceError as exc:
            source_health.append(
                {
                    "group": "product_hunt",
                    "name": "Product Hunt",
                    "status": "skipped" if "requires" in compact_text(str(exc)).lower() else "error",
                    "count": 0,
                    "detail": compact_text(str(exc))[:160],
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )
        except Exception as exc:
            source_health.append(
                {
                    "group": "product_hunt",
                    "name": "Product Hunt",
                    "status": "error",
                    "count": 0,
                    "detail": compact_text(str(exc))[:160],
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                }
            )
    return items, source_health


def fetch_ai_source_items(
    *,
    source: dict[str, Any],
    limit: int,
    since_days: int,
    signal_config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_kind = compact_text(str(source.get("source_kind", ""))).lower()
    if source_kind == "official_web":
        return fetch_official_web_items(source=source, limit=limit)
    if source_kind == "youtube_channel":
        return fetch_youtube_items(source=source, limit=limit)
    if source_kind == "github_release":
        return fetch_github_release_items(
            source=source,
            limit=limit,
            since_days=since_days,
            signal_config=signal_config or {},
            state=state,
        )
    if source_kind == "x_allowlist":
        return fetch_x_allowlist_items(source=source, limit=limit)
    return fetch_feed_items(source=source, limit=limit)


def fetch_official_web_items(*, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    url = compact_text(str(source.get("url", "")))
    html = fetch_url_text(url)
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    root_host = urllib.parse.urlsplit(url).netloc.lower()
    link_patterns = [compact_text(str(value)).lower() for value in list(source.get("link_patterns", [])) if value]
    text_patterns = [compact_text(str(value)).lower() for value in list(source.get("text_patterns", [])) if value]
    same_host_only = bool(source.get("same_host_only", False))
    page_probe_only = bool(source.get("page_probe_only", False))
    default_news_mode = not link_patterns and not text_patterns
    if not page_probe_only:
        for anchor in soup.find_all("a", href=True):
            href = compact_text(str(anchor.get("href", "")))
            if not href:
                continue
            link = canonicalize_link(urllib.parse.urljoin(url, href))
            link_host = urllib.parse.urlsplit(link).netloc.lower()
            if same_host_only and link_host and link_host != root_host:
                continue
            if link in seen_links:
                continue
            title_node = anchor.find(["h1", "h2", "h3", "h4"])
            title = compact_text(title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True))
            summary_node = anchor.find("p")
            summary = compact_text(summary_node.get_text(" ", strip=True) if summary_node else "")
            time_node = anchor.find("time")
            published = compact_text(time_node.get_text(" ", strip=True) if time_node else "")
            detail_haystack = " ".join([title, summary, href, link]).lower()
            if default_news_mode:
                if not href.startswith("/news/"):
                    continue
            else:
                link_match = bool(link_patterns) and any(
                    pattern in href.lower() or pattern in link.lower() for pattern in link_patterns
                )
                text_match = bool(text_patterns) and any(pattern in detail_haystack for pattern in text_patterns)
                if not link_match and not text_match:
                    continue
            if len(title) < 6:
                continue
            items.append(
                build_news_item(
                    source=source,
                    title=title,
                    link=link,
                    published=published,
                    summary=summary,
                    extra={
                        "source_kind": "official_web",
                        "headline_candidate": True,
                    },
                )
            )
            seen_links.add(link)
            if len(items) >= limit:
                break
    if items or not source.get("emit_page_probe"):
        return items

    page_haystack = compact_text(soup.get_text(" ", strip=True)).lower()
    if text_patterns and not any(pattern in page_haystack for pattern in text_patterns):
        return items

    og_title = ""
    og_title_node = soup.find("meta", attrs={"property": "og:title"})
    if og_title_node and og_title_node.get("content"):
        og_title = compact_text(str(og_title_node.get("content", "")))
    meta_description = ""
    meta_node = soup.find("meta", attrs={"name": "description"})
    if meta_node and meta_node.get("content"):
        meta_description = compact_text(str(meta_node.get("content", "")))
    h1_title = ""
    h1_node = soup.find("h1")
    if h1_node:
        h1_title = compact_text(h1_node.get_text(" ", strip=True))
    page_title = compact_text(str(source.get("page_probe_title", ""))) or h1_title or og_title
    if not page_title and soup.title and soup.title.string:
        page_title = compact_text(str(soup.title.string))
    page_summary = compact_text(str(source.get("page_probe_summary", ""))) or meta_description
    if len(page_title) >= 6:
        items.append(
            build_news_item(
                source=source,
                title=page_title,
                link=compact_text(str(source.get("page_probe_link", ""))) or url,
                published=compact_text(str(source.get("page_probe_published", ""))),
                summary=page_summary,
                extra={
                    "source_kind": "official_web",
                    "page_probe": True,
                    "headline_candidate": False,
                },
            )
        )
    return items


def fetch_recent_github_star_count(*, repo_slug: str, token: str, since_days: int, max_pages: int = 2) -> int:
    cutoff_dt = datetime.now(UTC) - timedelta(days=max(since_days, 1))
    recent_star_count = 0
    for page in range(1, max(max_pages, 1) + 1):
        payload = github_request(
            f"https://api.github.com/repos/{repo_slug}/stargazers?per_page=100&page={page}",
            token=token,
            accept="application/vnd.github.star+json",
        )
        if not isinstance(payload, list) or not payload:
            break
        should_stop = False
        for entry in payload:
            starred_at = parse_iso8601(compact_text(str(entry.get("starred_at", ""))))
            if not starred_at:
                continue
            if starred_at >= cutoff_dt:
                recent_star_count += 1
                continue
            should_stop = True
            break
        if should_stop or len(payload) < 100:
            break
    return recent_star_count


def parse_compact_number(value: str) -> int:
    text = compact_text(value).lower().replace(",", "")
    if not text:
        return 0
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    return int(float(match.group(0)) * multiplier)


def fetch_github_trending_items(*, github_trending_config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    since_value = compact_text(str(github_trending_config.get("since", "daily"))).lower() or "daily"
    html = fetch_url_text(f"https://github.com/trending?since={urllib.parse.quote(since_value)}")
    soup = BeautifulSoup(html, "html.parser")
    keywords = [compact_text(str(value)).lower() for value in list(github_trending_config.get("keywords", [])) if value]
    min_stars_today = int(github_trending_config.get("min_stars_today", 120) or 120)
    items: list[dict[str, Any]] = []
    for article in soup.select("article.Box-row"):
        name_node = article.select_one("h2 a")
        if not name_node:
            continue
        repo_slug = compact_text(name_node.get_text(" ", strip=True)).replace(" ", "")
        repo_slug = repo_slug.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
        if "/" not in repo_slug:
            continue
        description = compact_text(article.select_one("p").get_text(" ", strip=True) if article.select_one("p") else "")
        haystack = f"{repo_slug} {description}".lower()
        if keywords and not any(keyword in haystack for keyword in keywords):
            continue
        stars_node = article.select_one('a[href$="/stargazers"]')
        forks_node = article.select_one('a[href$="/forks"]')
        today_node = article.select_one("span.d-inline-block.float-sm-right")
        stars_today = parse_compact_number(today_node.get_text(" ", strip=True) if today_node else "")
        if stars_today < min_stars_today:
            continue
        total_stars = parse_compact_number(stars_node.get_text(" ", strip=True) if stars_node else "")
        forks_count = parse_compact_number(forks_node.get_text(" ", strip=True) if forks_node else "")
        language_node = article.select_one('[itemprop="programmingLanguage"]')
        language = compact_text(language_node.get_text(" ", strip=True) if language_node else "")
        observed_at = datetime.now(UTC).isoformat()
        summary_bits = [
            f"今日新增 {stars_today} stars",
            f"总 stars {total_stars}",
            f"共 {forks_count} 个 forks",
        ]
        if language:
            summary_bits.append(language)
        if description:
            summary_bits.append(f"项目说明：{description}")
        items.append(
            build_news_item(
                source={
                    "name": "GitHub Trending AI",
                    "category": "github",
                    "source_kind": "github_trending",
                },
                title=f"{repo_slug} GitHub 今日热榜",
                link=f"https://github.com/{repo_slug}",
                published=observed_at,
                summary="; ".join(summary_bits),
                extra={
                    "source_kind": "github_trending",
                    "repo_slug": repo_slug,
                    "observed_at": observed_at,
                    "stars_today": stars_today,
                    "stargazers_count": total_stars,
                    "forks_count": forks_count,
                    "programming_language": language,
                    "headline_candidate": stars_today >= int(github_trending_config.get("headline_stars_today", 300) or 300),
                },
            )
        )
        if len(items) >= max(limit, 1):
            break
    return items


def fetch_github_release_items(
    *,
    source: dict[str, Any],
    limit: int,
    since_days: int,
    signal_config: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    repo_slug = compact_text(str(source.get("repo", "")))
    if not repo_slug:
        return []
    github_token = compact_text(os.getenv("GITHUB_TOKEN", ""))
    releases_url = f"https://api.github.com/repos/{repo_slug}/releases?per_page={max(limit * 2, 6)}"
    releases = github_request(releases_url, token=github_token)
    release_items: list[dict[str, Any]] = []
    auxiliary_items: list[dict[str, Any]] = []
    cutoff_dt = datetime.now(UTC) - timedelta(days=max(since_days, 1))
    if isinstance(releases, list):
        for release in releases:
            if release.get("draft"):
                continue
            published = compact_text(str(release.get("published_at", "") or release.get("created_at", "")))
            published_dt = parse_iso8601(published)
            if published_dt and published_dt < cutoff_dt:
                continue
            release_name = compact_text(str(release.get("name", "")))
            tag_name = compact_text(str(release.get("tag_name", "")))
            title = compact_text(
                " ".join(part for part in [compact_text(str(source.get("name", ""))), release_name or tag_name] if part)
            )
            summary = sanitize_summary(str(release.get("body", "") or "")) or f"Repository release for {repo_slug}"
            release_items.append(
                build_news_item(
                    source=source,
                    title=title or f"{repo_slug} release",
                    link=compact_text(str(release.get("html_url", ""))),
                    published=published,
                    summary=summary,
                    extra={
                        "source_kind": "github_release",
                        "repo_slug": repo_slug,
                        "release_tag": tag_name,
                        "headline_candidate": True,
                    },
                )
            )

    repo = github_request(f"https://api.github.com/repos/{repo_slug}", token=github_token)
    github_momentum_config = dict(signal_config.get("github_momentum", {}))
    repo_snapshot_bucket = get_ai_daily_signal_state_bucket(state) if state is not None else {}
    previous_snapshot = dict(repo_snapshot_bucket.get(repo_slug, {})) if repo_snapshot_bucket else {}

    stars_count = int(repo.get("stargazers_count", 0) or 0)
    forks_count = int(repo.get("forks_count", 0) or 0)
    watchers_count = int(repo.get("subscribers_count", repo.get("watchers_count", 0)) or 0)
    open_issues_count = int(repo.get("open_issues_count", 0) or 0)
    repo_created_at = compact_text(str(repo.get("created_at", "")))
    captured_at = datetime.now(UTC).isoformat()
    current_snapshot = {
        "stars": stars_count,
        "forks": forks_count,
        "watchers": watchers_count,
        "open_issues": open_issues_count,
        "captured_at": captured_at,
        "pushed_at": compact_text(str(repo.get("pushed_at", ""))),
        "created_at": repo_created_at,
    }
    if repo_snapshot_bucket is not None:
        repo_snapshot_bucket[repo_slug] = current_snapshot

    min_total_stars = int(github_momentum_config.get("min_total_stars", 500) or 500)
    min_star_delta = int(github_momentum_config.get("min_star_delta", 25) or 25)
    min_star_growth_ratio = float(github_momentum_config.get("min_star_growth_ratio", 0.03) or 0.03)
    min_snapshot_hours = float(github_momentum_config.get("min_snapshot_hours", 12) or 12)
    min_ratio_absolute_delta = int(github_momentum_config.get("min_ratio_absolute_delta", 10) or 10)
    headline_star_delta = int(github_momentum_config.get("headline_star_delta", 60) or 60)
    recent_star_count = 0
    if bool(github_momentum_config.get("enabled", True)) and stars_count >= min_total_stars:
        try:
            recent_star_count = fetch_recent_github_star_count(repo_slug=repo_slug, token=github_token, since_days=since_days)
        except IntelWorkspaceError:
            recent_star_count = 0

    previous_stars = int(previous_snapshot.get("stars", 0) or 0)
    previous_forks = int(previous_snapshot.get("forks", 0) or 0)
    previous_watchers = int(previous_snapshot.get("watchers", 0) or 0)
    previous_captured_at = parse_flexible_datetime(str(previous_snapshot.get("captured_at", "")))
    current_captured_at = parse_flexible_datetime(captured_at)
    snapshot_window_hours = (
        (current_captured_at - previous_captured_at).total_seconds() / 3600
        if previous_captured_at and current_captured_at
        else 0.0
    )

    star_delta = stars_count - previous_stars
    fork_delta = forks_count - previous_forks
    watcher_delta = watchers_count - previous_watchers
    baseline_stars = max(previous_stars, 1)
    star_growth_ratio = star_delta / baseline_stars
    repo_age_days = 0
    created_dt = parse_iso8601(repo_created_at) or parse_flexible_datetime(repo_created_at)
    if created_dt:
        repo_age_days = max(int((datetime.now(UTC) - created_dt).total_seconds() // 86400), 0)

    qualifies_for_momentum = (
        bool(github_momentum_config.get("enabled", True))
        and stars_count >= min_total_stars
        and (
            (
                previous_snapshot
                and snapshot_window_hours >= min_snapshot_hours
                and (
                    star_delta >= min_star_delta
                    or (star_growth_ratio >= min_star_growth_ratio and star_delta >= min_ratio_absolute_delta)
                )
            )
            or recent_star_count >= min_star_delta
        )
    )
    if qualifies_for_momentum:
        growth_percent = round(star_growth_ratio * 100, 2)
        summary_parts = []
        if previous_snapshot and snapshot_window_hours >= min_snapshot_hours:
            summary_parts.extend(
                [
                    f"Stars +{star_delta} to {stars_count}",
                    f"forks +{fork_delta}",
                ]
            )
        else:
            summary_parts.append(f"Recent GitHub stars {recent_star_count} in {since_days}d")
            summary_parts.append(f"total stars {stars_count}")
        if watcher_delta:
            summary_parts.append(f"watchers +{watcher_delta}")
        if snapshot_window_hours:
            summary_parts.append(f"window {round(snapshot_window_hours, 1)}h")
        title = f"{compact_text(str(source.get('name', repo_slug)))} GitHub momentum"
        auxiliary_items.append(
            build_news_item(
                source=source,
                title=title,
                link=compact_text(str(repo.get("html_url", ""))),
                published=captured_at,
                summary=f"{'; '.join(summary_parts)}; growth {growth_percent}% vs previous snapshot.",
                extra={
                    "source_kind": "github_momentum",
                    "repo_slug": repo_slug,
                    "star_delta": star_delta,
                    "recent_star_count": recent_star_count,
                    "fork_delta": fork_delta,
                    "watcher_delta": watcher_delta,
                    "stargazers_count": stars_count,
                    "forks_count": forks_count,
                    "watchers_count": watchers_count,
                    "open_issues_count": open_issues_count,
                    "snapshot_window_hours": round(snapshot_window_hours, 2),
                    "star_growth_ratio": round(star_growth_ratio, 6),
                    "repo_age_days": repo_age_days,
                    "headline_candidate": max(star_delta, recent_star_count) >= headline_star_delta,
                },
            )
        )

    pushed_at = compact_text(str(repo.get("pushed_at", "")))
    pushed_dt = parse_iso8601(pushed_at)
    if pushed_dt and pushed_dt >= cutoff_dt:
        auxiliary_items.append(
            build_news_item(
                source=source,
                title=f"{compact_text(str(source.get('name', repo_slug)))} repository activity",
                link=compact_text(str(repo.get("html_url", ""))),
                published=pushed_at,
                summary=compact_text(str(repo.get("description", ""))) or f"Recent repository activity in {repo_slug}",
                extra={
                    "source_kind": "github_repo",
                    "repo_slug": repo_slug,
                    "headline_candidate": False,
                },
            )
        )
    return (auxiliary_items + release_items)[:limit]


def fetch_x_allowlist_items(*, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    api_key = get_env_value("TWITTERAPI_API_KEY", "TWITTERAPI_IO_KEY")
    if not api_key:
        raise IntelWorkspaceError("X allowlist requires TWITTERAPI_API_KEY or TWITTERAPI_IO_KEY.")
    handle = compact_text(str(source.get("handle", ""))).lstrip("@")
    if not handle:
        return []
    endpoint = f"https://api.twitterapi.io/twitter/user/last_tweets?{urllib.parse.urlencode({'userName': handle, 'includeReplies': 'false'})}"
    payload = fetch_json_url(
        endpoint,
        headers={
            "User-Agent": "Mozilla/5.0 OPC Intelligence Bot",
            "X-API-Key": api_key,
        },
    )
    tweets = list(payload.get("tweets", []) or [])[:limit]
    items: list[dict[str, Any]] = []
    for tweet in tweets:
        tweet_id = compact_text(str(tweet.get("id", "")))
        text = compact_text(str(tweet.get("text", "")))
        if not tweet_id or not text:
            continue
        metrics = {
            "likes": int(tweet.get("likeCount", 0) or 0),
            "replies": int(tweet.get("replyCount", 0) or 0),
            "retweets": int(tweet.get("retweetCount", 0) or 0),
            "views": int(tweet.get("viewCount", 0) or 0),
        }
        items.append(
            build_news_item(
                source=source,
                title=text[:140],
                link=f"https://x.com/{handle}/status/{tweet_id}",
                published=compact_text(str(tweet.get("createdAt", ""))),
                summary=text,
                extra={
                    "source_kind": "x_allowlist",
                    "x_handle": handle,
                    "engagement_score": metrics["likes"] + metrics["replies"] * 2 + metrics["retweets"] * 2,
                    "metrics": metrics,
                },
            )
        )
    return items


def resolve_product_hunt_token(*, force_oauth_refresh: bool = False) -> str:
    direct_token = ""
    if not force_oauth_refresh:
        direct_token = get_env_value(
            "PRODUCT_HUNT_TOKEN",
            "PRODUCT_HUNT_ACCESS_TOKEN",
            "PH_ACCESS_TOKEN",
        )
        if direct_token:
            return direct_token

    client_id = get_env_value(
        "PRODUCT_HUNT_API_KEY",
        "PRODUCT_HUNT_CLIENT_ID",
        "PH_API_KEY",
    )
    client_secret = get_env_value(
        "PRODUCT_HUNT_API_SECRET",
        "PRODUCT_HUNT_CLIENT_SECRET",
        "PH_API_SECRET",
    )
    if not client_id or not client_secret:
        return direct_token

    oauth_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    for oauth_url in (
        "https://api.producthunt.com/v2/oauth/token",
        "https://www.producthunt.com/v2/oauth/token",
    ):
        try:
            payload = post_json_url(
                oauth_url,
                data=oauth_payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 OPC Intelligence Bot",
                },
            )
        except IntelWorkspaceError:
            continue
        access_token = compact_text(str(payload.get("access_token", "")))
        if access_token:
            return access_token
    return direct_token


def fetch_product_hunt_items(*, product_hunt_config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    token = resolve_product_hunt_token()
    if not token:
        raise IntelWorkspaceError(
            "Product Hunt requires PRODUCT_HUNT_TOKEN, PH_ACCESS_TOKEN, or PRODUCT_HUNT_API_KEY/PRODUCT_HUNT_API_SECRET."
        )

    posted_after, posted_before = current_product_hunt_window()
    query = """
    query Posts($first: Int!, $postedAfter: DateTime!, $postedBefore: DateTime!) {
      posts(first: $first, order: VOTES, postedAfter: $postedAfter, postedBefore: $postedBefore) {
        edges {
          node {
            id
            name
            slug
            tagline
            description
            url
            votesCount
            commentsCount
            createdAt
            featuredAt
            website
            topics {
              edges {
                node {
                  name
                  slug
                }
              }
            }
          }
        }
      }
    }
    """
    graphql_request = {
        "query": query,
        "variables": {
            "first": max(limit, 1),
            "postedAfter": posted_after,
            "postedBefore": posted_before,
        },
    }

    def run_graphql(current_token: str) -> dict[str, Any]:
        return post_json_url(
            "https://api.producthunt.com/v2/api/graphql",
            data=graphql_request,
            headers={
                "Authorization": f"Bearer {current_token}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 OPC Intelligence Bot",
            },
        )

    try:
        payload = run_graphql(token)
    except IntelWorkspaceError as exc:
        detail = compact_text(str(exc)).lower()
        if "invalid_oauth_token" in detail or "401" in detail:
            refreshed_token = resolve_product_hunt_token(force_oauth_refresh=True)
            if refreshed_token and refreshed_token != token:
                payload = run_graphql(refreshed_token)
            else:
                raise IntelWorkspaceError(
                    "Product Hunt token was loaded but rejected by the API. Refresh PRODUCT_HUNT_TOKEN or configure PRODUCT_HUNT_API_KEY/PRODUCT_HUNT_API_SECRET."
                ) from exc
        else:
            raise
    edges = (((payload.get("data") or {}).get("posts") or {}).get("edges") or [])
    items: list[dict[str, Any]] = []
    for edge in edges:
        node = edge.get("node") or {}
        topic_nodes = [topic_edge.get("node") or {} for topic_edge in ((node.get("topics") or {}).get("edges") or [])]
        topics = [compact_text(str(topic.get("name", ""))) for topic in topic_nodes if compact_text(str(topic.get("name", "")))]
        topic_slugs = [compact_text(str(topic.get("slug", ""))).lower() for topic in topic_nodes if compact_text(str(topic.get("slug", "")))]
        items.append(
            build_news_item(
                source={"name": "Product Hunt", "category": "product_hunt"},
                title=compact_text(str(node.get("name", ""))),
                link=compact_text(str(node.get("url", ""))),
                published=compact_text(str(node.get("createdAt", ""))),
                summary=compact_text(str(node.get("tagline", "")) or str(node.get("description", ""))),
                extra={
                    "source_kind": "product_hunt",
                    "product_name": compact_text(str(node.get("name", ""))),
                    "product_slug": compact_text(str(node.get("slug", ""))),
                    "website": compact_text(str(node.get("website", ""))),
                    "votes_count": int(node.get("votesCount", 0) or 0),
                    "comments_count": int(node.get("commentsCount", 0) or 0),
                    "featured": bool(node.get("featuredAt")),
                    "topics": topics,
                    "topic_slugs": topic_slugs,
                    "headline_candidate": False,
                },
            )
        )
    probe_limit = max(int(product_hunt_config.get("builder_surface_probe_limit", 0) or 0), 0)
    for item in sorted(items, key=lambda current: int(current.get("votes_count", 0) or 0), reverse=True)[:probe_limit]:
        has_builder_surface, builder_surface_detail = detect_public_builder_surface(item)
        item["has_builder_surface"] = has_builder_surface
        item["builder_surface_detail"] = builder_surface_detail
    filtered_items: list[dict[str, Any]] = []
    target_topics = list(product_hunt_config.get("target_topics", []) or [])
    for item in items:
        ai_relevant, ai_matches = product_hunt_item_is_ai_relevant(item, target_topics)
        item["ph_ai_relevant"] = ai_relevant
        item["ph_ai_matches"] = ai_matches
        if ai_relevant:
            filtered_items.append(item)
    return filtered_items


def current_product_hunt_window() -> tuple[str, str]:
    now_ph = datetime.now(PH_TIMEZONE)
    start = now_ph.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).isoformat().replace("+00:00", "Z"), end.astimezone(UTC).isoformat().replace("+00:00", "Z")


def product_hunt_item_is_ai_relevant(item: dict[str, Any], target_topics: list[str]) -> tuple[bool, list[str]]:
    topics = list(item.get("topics", []) or [])
    topic_slugs = [token.replace("-", " ") for token in list(item.get("topic_slugs", []) or [])]
    haystack = " ".join(
        [
            compact_text(str(item.get("title", ""))),
            compact_text(str(item.get("summary", ""))),
            compact_text(str(item.get("website", ""))),
            *topics,
            *topic_slugs,
        ]
    ).lower()
    custom_targets = {
        compact_text(topic).lower()
        for topic in target_topics
        if compact_text(topic) and compact_text(topic).lower() not in AI_SIGNAL_GENERIC_TOPIC_KEYWORDS
    }
    strong_targets = custom_targets.union(AI_SIGNAL_STRONG_TOPIC_KEYWORDS)
    matches = sorted(target for target in strong_targets if target and haystack_contains_term(haystack, target))
    return bool(matches), matches[:6]


def detect_public_builder_surface(item: dict[str, Any]) -> tuple[bool, str]:
    website = compact_text(str(item.get("website", "")))
    seed_text = " ".join(
        [
            compact_text(str(item.get("title", ""))),
            compact_text(str(item.get("summary", ""))),
            website,
        ]
    ).lower()
    direct_keywords = ("github", "open source", "api", "sdk", "docs", "developer")
    if any(keyword in seed_text for keyword in direct_keywords):
        return True, "tagline_or_url"
    if not website:
        return False, ""
    try:
        html = fetch_url_text(website, timeout_seconds=20)
    except Exception:
        return False, ""
    lowered = html.lower()
    if "github.com" in lowered:
        return True, "website_github_link"
    if any(keyword in lowered for keyword in ("documentation", "api reference", "/docs", "/developers", "developer docs")):
        return True, "website_docs_link"
    return False, ""


def fetch_feed_items(*, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    xml_text = fetch_url_text(compact_text(str(source.get("url", ""))))
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []

    if root.tag.lower().endswith("feed"):
        for entry in root.findall("{*}entry")[:limit]:
            title = compact_text(entry.findtext("{*}title", default=""))
            link = ""
            for link_node in entry.findall("{*}link"):
                href = compact_text(str(link_node.attrib.get("href", "")))
                if href:
                    link = href
                    break
            published = compact_text(entry.findtext("{*}published", default="") or entry.findtext("{*}updated", default=""))
            summary = compact_text(entry.findtext("{*}summary", default="") or entry.findtext("{*}content", default=""))
            items.append(build_news_item(source=source, title=title, link=link, published=published, summary=summary))
        return items

    channel = root.find("channel")
    if channel is None:
        return items
    for item in channel.findall("item")[:limit]:
        title = compact_text(item.findtext("title", default=""))
        link = compact_text(item.findtext("link", default=""))
        published = compact_text(item.findtext("pubDate", default=""))
        summary = compact_text(item.findtext("description", default=""))
        items.append(build_news_item(source=source, title=title, link=link, published=published, summary=summary))
    return items


def fetch_youtube_items(*, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    feed_url = resolve_youtube_feed_url(compact_text(str(source.get("url", ""))))
    if not feed_url:
        return []
    xml_text = fetch_url_text(feed_url)
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for entry in root.findall("{*}entry")[:limit]:
        title = compact_text(entry.findtext("{*}title", default=""))
        link = ""
        for link_node in entry.findall("{*}link"):
            href = compact_text(str(link_node.attrib.get("href", "")))
            if href:
                link = href
                break
        published = compact_text(entry.findtext("{*}published", default="") or entry.findtext("{*}updated", default=""))
        summary = compact_text(entry.findtext("{*}group/{*}description", default=""))
        items.append(build_news_item(source=source, title=title, link=link, published=published, summary=summary))
    return items


def build_news_item(*, source: dict[str, Any], title: str, link: str, published: str, summary: str) -> dict[str, Any]:
    published_dt = parse_flexible_datetime(published)
    return {
        "source_name": compact_text(str(source.get("name", ""))),
        "category": compact_text(str(source.get("category", ""))),
        "title": title,
        "link": link,
        "published": published or "",
        "published_sort": published_dt.isoformat() if published_dt else "",
        "summary": sanitize_summary(summary),
    }


def render_ai_news_digest(*, today: str, items: list[dict[str, Any]]) -> str:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_category.setdefault(item.get("category") or "other", []).append(item)

    lines = [
        f"# AI 姣忔棩淇″彿 / Daily Signal - {today}",
        "",
        "## 鎽樿 / Summary",
        "",
        f"- 鏉＄洰鎬绘暟 / Total items: {len(items)}",
        f"- 瑕嗙洊绫诲埆 / Categories: {', '.join(category_label(category) for category in sorted(by_category)) if by_category else '鏃?/ None'}",
        "",
    ]
    for category, category_items in sorted(by_category.items()):
        lines.extend([f"## {category_label(category)}", ""])
        for index, item in enumerate(category_items, start=1):
            lines.extend(
                [
                    f"### {index}. {item['title']}",
                    f"- 鏉ユ簮 / Source: {item['source_name']}",
                    f"- 鍙戝竷鏃堕棿 / Published: {item['published'] or '鏈煡 / Unknown'}",
                    f"- 閾炬帴 / Link: {item['link']}",
                    f"- 瑕佺偣 / Signal: {item['summary'] or '鏆傛棤鎽樿銆?/ No summary provided.'}",
                    "",
                ]
            )
    if not items:
        lines.extend(["- 褰撳墠娌℃湁閲囬泦鍒板彲鐢ㄦ潯鐩€?/ No source items were collected.", ""])
    return "\n".join(lines).strip() + "\n"


def translate_pr_status(row: dict[str, Any]) -> str:
    if row.get("merged_at"):
        return "已合并"
    state = compact_text(str(row.get("state", ""))).lower()
    if state == "open":
        return "进行中"
    if state == "closed":
        return "已关闭"
    return "未知"


def category_label(category: str) -> str:
    return AI_CATEGORY_LABELS.get(compact_text(category).lower(), compact_text(category) or "其他")


def summarize_digest_overview(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- 今天没有需要汇总的 PR 变更。"]

    change_counts: dict[str, int] = {"feature": 0, "fix": 0, "maintenance": 0, "other": 0}
    theme_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    high_attention: list[dict[str, Any]] = []
    low_priority: list[dict[str, Any]] = []

    for row in rows:
        change_type = classify_pr_change_type(compact_text(str(row.get("title", ""))))
        change_counts[change_type] = change_counts.get(change_type, 0) + 1
        for theme in classify_pr_themes(
            title=compact_text(str(row.get("title", ""))),
            file_paths=row.get("file_paths", []),
        ):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        for module in collect_row_modules(row):
            module_counts[module] = module_counts.get(module, 0) + 1
        quick_take = compact_text(str(row.get("quick_take", "")))
        if "Worth a quick focused review" in quick_take or "quick focused review" in quick_take:
            high_attention.append(row)
        if "low priority" in quick_take.lower():
            low_priority.append(row)

    dominant_change = max(change_counts.items(), key=lambda item: item[1])[0]
    change_summary = describe_change_mix(change_counts)
    top_themes = ", ".join(name for name, _ in sorted(theme_counts.items(), key=lambda item: item[1], reverse=True)[:3])
    top_modules = ", ".join(name for name, _ in sorted(module_counts.items(), key=lambda item: item[1], reverse=True)[:3])
    watchlist = format_watchlist(high_attention[:3])
    low_priority_summary = format_watchlist(low_priority[:2])

    dominant_change_label = {
        "feature": "新增为主",
        "fix": "修复为主",
        "maintenance": "维护为主",
        "other": "混合变更",
    }.get(dominant_change, "混合变更")

    lines = [
        f"- 一句话：今天这批 PR 以{dominant_change_label}，主要集中在 {top_themes or '多个主题'}，重点模块是 {top_modules or '多个区域'}。",
        f"- 变更构成：{change_summary}",
    ]
    if watchlist:
        lines.append(f"- 优先关注：{watchlist}")
    if low_priority_summary:
        lines.append(f"- 可后看：{low_priority_summary}")
    return lines


def classify_pr_change_type(title: str) -> str:
    lowered = compact_text(title).lower()
    if "test coverage" in lowered:
        return "maintenance"
    if lowered.startswith(("feat(", "feat:", "feature")):
        return "feature"
    if lowered.startswith(("fix(", "fix:", "bugfix")):
        return "fix"
    if lowered.startswith(("build(", "build:", "docs(", "docs:", "test(", "test:", "chore(", "chore:", "ci(", "ci:")):
        return "maintenance"
    return "other"


def classify_pr_themes(*, title: str, file_paths: list[str]) -> list[str]:
    lowered = compact_text(title).lower()
    modules = " ".join(path.lower() for path in file_paths)
    combined = f"{lowered} {modules}"
    themes: list[str] = []
    if any(token in combined for token in ("plugin", "provider", "extension", "bedrock", "fireworks", "kimi", "model")):
        themes.append("插件与模型接入")
    if any(token in combined for token in ("slack", "whatsapp", "telegram", "msteams", "feishu", "message", "outbound", "inbound")):
        themes.append("消息与连接器")
    if any(token in combined for token in ("runtime", "session", "memory", "queue", "gateway", "config", "auth", "token")):
        themes.append("运行时与稳定性")
    if any(token in combined for token in ("ui", "macos", "desktop", "web", "browser")):
        themes.append("界面与客户端")
    if any(token in combined for token in ("build", "deps", "dependabot", "docs", "test", "ci", "chore")):
        themes.append("维护与工程化")
    return themes or ["通用改动"]


def collect_row_modules(row: dict[str, Any]) -> list[str]:
    modules_text = summarize_pr_modules(row.get("file_paths", []))
    if not modules_text:
        return []
    return [item.strip() for item in modules_text.split(",") if item.strip()]


def describe_change_mix(change_counts: dict[str, int]) -> str:
    ordered = [
        ("feature", "新增", "features"),
        ("fix", "修复", "fixes"),
        ("maintenance", "维护", "maintenance"),
        ("other", "其他", "other"),
    ]
    parts = [f"{zh} {change_counts.get(key, 0)}" for key, zh, _en in ordered if change_counts.get(key, 0)]
    return ", ".join(parts)


def format_watchlist(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    items = []
    for row in rows:
        title = compact_text(str(row.get("title", "")))
        number = row.get("number", "")
        items.append(f"#{number} {title[:72]}")
    return ", ".join(items)


def enrich_github_pr_rows(rows: list[dict[str, Any]], *, github_token: str) -> list[dict[str, Any]]:
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        detail = fetch_github_pr_detail(
            repo_slug=compact_text(str(row.get("repo_slug", ""))),
            number=int(row.get("number", 0) or 0),
            github_token=github_token,
        )
        merged = {**row, **detail}
        merged["body_summary"] = summarize_pr_body(
            str(merged.get("body", "")),
            fallback_title=compact_text(str(merged.get("title", ""))),
        )
        merged["file_summary"] = summarize_pr_files(
            merged.get("file_paths", []),
            changed_files=int(merged.get("changed_files", 0) or 0),
            additions=int(merged.get("additions", 0) or 0),
            deletions=int(merged.get("deletions", 0) or 0),
        )
        merged["impact_summary"] = summarize_pr_impact(
            file_paths=merged.get("file_paths", []),
            changed_files=int(merged.get("changed_files", 0) or 0),
            additions=int(merged.get("additions", 0) or 0),
            deletions=int(merged.get("deletions", 0) or 0),
        )
        merged["quick_take"] = summarize_pr_quick_take(
            title=compact_text(str(merged.get("title", ""))),
            body_summary=compact_text(str(merged.get("body_summary", ""))),
            file_paths=merged.get("file_paths", []),
            changed_files=int(merged.get("changed_files", 0) or 0),
            additions=int(merged.get("additions", 0) or 0),
            deletions=int(merged.get("deletions", 0) or 0),
        )
        enriched_rows.append(merged)
    return enriched_rows


def fetch_github_pr_detail(*, repo_slug: str, number: int, github_token: str) -> dict[str, Any]:
    if not repo_slug or number <= 0:
        return {
            "body": "",
            "changed_files": 0,
            "additions": 0,
            "deletions": 0,
            "file_paths": [],
        }
    detail_url = f"https://api.github.com/repos/{repo_slug}/pulls/{number}"
    files_url = f"https://api.github.com/repos/{repo_slug}/pulls/{number}/files?per_page=8"
    try:
        detail = github_request(detail_url, token=github_token)
    except Exception:
        detail = {}
    try:
        files = github_request(files_url, token=github_token)
    except Exception:
        files = []
    file_paths = [
        compact_text(str(item.get("filename", "")))
        for item in (files if isinstance(files, list) else [])
        if compact_text(str(item.get("filename", "")))
    ]
    return {
        "body": str(detail.get("body", "") or ""),
        "changed_files": int(detail.get("changed_files", 0) or 0),
        "additions": int(detail.get("additions", 0) or 0),
        "deletions": int(detail.get("deletions", 0) or 0),
        "file_paths": file_paths,
    }


def summarize_pr_body(body: str, *, fallback_title: str = "") -> str:
    cleaned = re.sub(r"<!--.*?-->", " ", body or "", flags=re.S)
    cleaned = cleaned.replace("\r", "\n")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    preferred_keywords = ("summary", "what", "change", "overview", "description", "context")

    for index, block in enumerate(blocks):
        if not block.startswith("#"):
            continue
        heading = compact_text(block.lstrip("#").strip()).lower()
        heading_lines = block.splitlines()
        if any(keyword in heading for keyword in preferred_keywords) and len(heading_lines) > 1:
            candidate = normalize_pr_text_block("\n".join(heading_lines[1:]))
            if candidate:
                return candidate
        if any(keyword in heading for keyword in preferred_keywords) and index + 1 < len(blocks):
            candidate = normalize_pr_text_block(blocks[index + 1])
            if candidate:
                return candidate

    for block in blocks:
        candidate = normalize_pr_text_block(block)
        if candidate:
            return candidate

    fallback = compact_text(fallback_title)
    return fallback or "鏆傛棤鍙敤鎽樿 / No summary available."


def normalize_pr_text_block(block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return ""
    filtered = []
    for line in lines:
        lowered = compact_text(line).lower()
        if lowered.startswith(("fixes #", "closes #", "refs #", "test plan", "checklist", "release note")):
            continue
        if lowered.startswith(("[//]:", "<!--", "dependabot-", "## checklist", "## test plan")):
            continue
        if re.match(r"^[-*]\s+\[[ xX]\]", line):
            continue
        filtered.append(line)
    if not filtered:
        return ""
    bullet_lines = [re.sub(r"^[-*]\s+", "", line).strip() for line in filtered if re.match(r"^[-*]\s+", line)]
    if bullet_lines:
        return compact_text("; ".join(bullet_lines[:3]))[:420]
    if filtered[0].startswith("#"):
        return ""
    paragraph = compact_text(" ".join(filtered))
    return paragraph[:420]


def summarize_pr_files(file_paths: list[str], *, changed_files: int, additions: int, deletions: int) -> str:
    modules = summarize_pr_modules(file_paths)
    count_label = f"{changed_files} files, +{additions}/-{deletions}"
    if modules:
        return f"{count_label}; {modules}"
    if file_paths:
        preview = ", ".join(file_paths[:3])
        if len(file_paths) > 3:
            preview += ", ..."
        return f"{count_label}; {preview}"
    return count_label


def summarize_pr_impact(*, file_paths: list[str], changed_files: int, additions: int, deletions: int) -> str:
    modules = summarize_pr_modules(file_paths)
    if changed_files >= 12 or additions + deletions >= 800:
        size_hint = "鏀瑰姩鑼冨洿杈冨ぇ锛屽缓璁噸鐐硅繃涓€閬嶇浉鍏虫ā鍧?/ Broad change footprint, worth a closer review."
    elif changed_files >= 5 or additions + deletions >= 200:
        size_hint = "鏀瑰姩鑼冨洿涓瓑锛岄€傚悎蹇€熸祻瑙堝悗鎸夋ā鍧楃粏鐪?/ Medium-sized change, skim first then inspect touched modules."
    else:
        size_hint = "鏀瑰姩鑼冨洿杈冮泦涓紝閫傚悎蹇€熺‘璁ゆ牳蹇冮€昏緫 / Focused change, quick review should be enough."
    if modules:
        return f"Touches {modules}. {size_hint}"
    return size_hint


def summarize_pr_quick_take(
    *,
    title: str,
    body_summary: str,
    file_paths: list[str],
    changed_files: int,
    additions: int,
    deletions: int,
) -> str:
    title_lower = compact_text(title).lower()
    summary_lower = compact_text(body_summary).lower()
    modules = summarize_pr_modules(file_paths)
    total_changes = additions + deletions
    combined = f"{title_lower} {summary_lower}"

    low_priority_keywords = (
        "dependabot",
        "build(",
        "build:",
        "test(",
        "test:",
        "test coverage",
        "docs(",
        "docs:",
        "chore(",
        "chore:",
        "lint",
        "typo",
    )
    core_path_keywords = (
        "auth",
        "permission",
        "security",
        "session",
        "memory",
        "gateway",
        "queue",
        "message",
        "runtime",
        "plugin",
        "provider",
        "model",
        "config",
        "token",
        "feishu",
        "msteams",
        "whatsapp",
        "telegram",
        "browser",
    )
    feature_keywords = ("feat(", "feat:", "add ", "support ", "provider", "plugin", "extension", "new ")
    fix_keywords = ("fix(", "fix:", "bug", "prevent", "preserve", "catch", "route", "ignore", "disable")

    if any(keyword in combined for keyword in low_priority_keywords):
        return "鍋忕淮鎶ょ被鏀瑰姩锛屽彲浣庝紭鍏堢骇鐣ヨ繃锛涢櫎闈炰綘姝ｅソ鍏虫敞渚濊禆銆佹祴璇曟垨鏋勫缓閾捐矾銆?/ Mostly maintenance work; low priority unless you own deps, tests, or build tooling."

    if any(keyword in combined for keyword in core_path_keywords):
        if changed_files >= 8 or total_changes >= 250:
            return f"寤鸿缁嗙湅锛岃繖绫绘敼鍔ㄧ洿鎺ュ奖鍝嶆牳蹇冭兘鍔涙垨杩炴帴閾捐矾锛屼笖鑼冨洿涓嶅皬锛涗紭鍏堝叧娉?{modules or '鐩稿叧鏍稿績妯″潡'}銆?/ Worth a closer read: it touches core execution or integration paths with non-trivial scope."
        return f"寤鸿蹇€熺粏鐪嬶紝杩欑被鏀瑰姩鐩存帴褰卞搷鏍稿績鑳藉姏鎴栬繛鎺ラ摼璺紱浼樺厛纭 {modules or '鐩稿叧鏍稿績妯″潡'} 鐨勮涓哄彉鍖栥€?/ Worth a quick focused review because it touches core execution or integration paths."

    if any(keyword in combined for keyword in feature_keywords):
        return f"灞炰簬鏂板鑳藉姏锛屽厛鍒ゆ柇鍜屼綘褰撳墠鏂瑰悜鏄惁鐩稿叧锛涚浉鍏崇殑璇濋噸鐐圭湅 {modules or '鏂板妯″潡'}銆?/ New capability work; check relevance first, then inspect the touched area."

    if any(keyword in combined for keyword in fix_keywords):
        if changed_files >= 8 or total_changes >= 250:
            return "鍋忕ǔ瀹氭€т慨澶嶏紝浣嗘敼鍔ㄩ潰涓嶅皬锛屽缓璁壂涓€閬嶆憳瑕佸拰鏂囦欢鑼冨洿鍚庡啀鍐冲畾鏄惁娣辩湅銆?/ Primarily a stability fix, but broad enough to merit a quick skim of summary and files."
        return "鍋忕ǔ瀹氭€т慨澶嶏紝閫氬父璇诲畬鎽樿鍜屾枃浠惰寖鍥村氨澶燂紱鍙湪浣犺礋璐ｇ浉鍏虫ā鍧楁椂鍐嶆繁鐪嬨€?/ Primarily a stability fix; summary plus file scope is usually enough unless you own the area."

    if changed_files >= 12 or total_changes >= 400:
        return f"鏀瑰姩闈㈣緝澶э紝鍗充娇涓嶆槸鏍稿績妯″潡涔熷缓璁繃涓€閬嶏紱鑷冲皯纭 {modules or '涓昏鐩綍'} 娌℃湁瓒呭嚭棰勬湡銆?/ Broad change footprint; worth a skim even if the area is not central."

    return "甯歌鍙樻洿锛屽厛鐪嬫憳瑕佸嵆鍙紝闇€瑕佹椂鍐嶇偣杩?PR銆?/ Standard change; summary first, open the PR only if it looks relevant."


def summarize_pr_modules(file_paths: list[str]) -> str:
    modules: list[str] = []
    for path in file_paths[:8]:
        normalized = compact_text(path).strip("/")
        if not normalized:
            continue
        parts = [part for part in normalized.split("/") if part]
        if not parts:
            continue
        if len(parts) >= 2 and parts[0] in {"packages", "apps", "services", "plugins"}:
            module = "/".join(parts[:2])
        else:
            module = parts[0]
        if module not in modules:
            modules.append(module)
    return ", ".join(modules[:4])


def fetch_url_text(url: str) -> str:
    request_obj = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 OPC Intelligence Bot"})
    with urllib.request.urlopen(request_obj, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def resolve_youtube_feed_url(channel_url: str) -> str:
    html = fetch_url_text(channel_url)
    marker = 'rel="alternate" type="application/rss+xml"'
    marker_index = html.find(marker)
    if marker_index >= 0:
        href_index = html.rfind("href=", 0, marker_index)
        if href_index >= 0:
            quote = html[href_index + 5]
            end_index = html.find(quote, href_index + 6)
            if end_index > href_index:
                return html[href_index + 6 : end_index]
    channel_id_marker = '"channelId":"'
    channel_id_index = html.find(channel_id_marker)
    if channel_id_index >= 0:
        start = channel_id_index + len(channel_id_marker)
        end = html.find('"', start)
        if end > start:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={html[start:end]}"
    return ""


def parse_flexible_datetime(value: str) -> datetime | None:
    text = compact_text(value)
    if not text:
        return None
    for parser in [
        lambda content: datetime.fromisoformat(content.replace("Z", "+00:00")),
        lambda content: datetime.strptime(content, "%a, %d %b %Y %H:%M:%S %z"),
        lambda content: datetime.strptime(content, "%Y-%m-%dT%H:%M:%S%z"),
    ]:
        try:
            return parser(text).astimezone(UTC)
        except Exception:
            continue
    return None


def parse_iso8601(value: str) -> datetime | None:
    text = compact_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def is_noisy_ai_news_item(item: dict[str, Any]) -> bool:
    title = compact_text(str(item.get("title", ""))).lower()
    if not title:
        return True
    noisy_keywords = [
        "self-promotion thread",
        "who's hiring",
        "who wants to be hired",
        "weekly",
        "monthly",
        "discord server",
        "hiring thread",
    ]
    return any(keyword in title for keyword in noisy_keywords)


def sanitize_summary(text: str) -> str:
    html_text = str(text or "")
    if not html_text:
        return ""
    plain = BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:400]


def build_news_item(
    *,
    source: dict[str, Any],
    title: str,
    link: str,
    published: str,
    summary: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    published_dt = parse_flexible_datetime(published)
    item = {
        "source_name": compact_text(str(source.get("name", ""))),
        "source_kind": compact_text(str(source.get("source_kind", ""))),
        "category": compact_text(str(source.get("category", ""))),
        "title": compact_text(title),
        "link": canonicalize_link(link),
        "canonical_link": canonicalize_link(link),
        "published": published or "",
        "published_sort": published_dt.isoformat() if published_dt else "",
        "summary": sanitize_summary(summary),
        "headline_candidate": bool(source.get("headline_candidate", False)),
        "cross_verification_channels": [],
        "cross_verification_matches": [],
        "headline_reasons": [],
    }
    if extra:
        item.update(extra)
    return normalize_signal_item(item)


def normalize_signal_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["source_name"] = compact_text(str(normalized.get("source_name", ""))) or "Unknown source"
    normalized["source_kind"] = compact_text(str(normalized.get("source_kind", "")))
    normalized["title"] = compact_text(str(normalized.get("title", "")))
    normalized["summary"] = sanitize_summary(str(normalized.get("summary", "")))
    normalized["link"] = canonicalize_link(str(normalized.get("link", "")))
    normalized["canonical_link"] = canonicalize_link(
        str(normalized.get("canonical_link", "") or normalized.get("link", ""))
    )
    normalized["published"] = compact_text(str(normalized.get("published", "")))
    published_dt = parse_flexible_datetime(str(normalized.get("published_sort", ""))) or parse_flexible_datetime(
        normalized["published"]
    )
    normalized["published_sort"] = published_dt.isoformat() if published_dt else ""
    normalized["category"] = normalize_signal_category(normalized)
    normalized["headline_candidate"] = bool(normalized.get("headline_candidate", False))
    normalized["cross_verification_channels"] = list(normalized.get("cross_verification_channels", []) or [])
    normalized["cross_verification_matches"] = list(normalized.get("cross_verification_matches", []) or [])
    normalized["headline_reasons"] = list(normalized.get("headline_reasons", []) or [])
    return normalized


def canonicalize_link(url: str) -> str:
    text = compact_text(url)
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    parsed = urllib.parse.urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    if "youtube.com" in netloc and path == "/watch":
        query_pairs = [(key, value) for key, value in query_pairs if key == "v"]
    elif "producthunt.com" in netloc:
        query_pairs = []
    else:
        blocked_query_keys = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "ref",
            "ref_src",
            "source",
            "si",
            "feature",
        }
        query_pairs = [(key, value) for key, value in query_pairs if key.lower() not in blocked_query_keys]
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def normalize_signal_category(item: dict[str, Any]) -> str:
    category = compact_text(str(item.get("category", ""))).lower()
    source_kind = compact_text(str(item.get("source_kind", ""))).lower()
    source_name = compact_text(str(item.get("source_name", ""))).lower()
    if source_kind in {"official_feed", "official_web"} or category in {"official", "company", "product"}:
        return "official"
    if source_kind in {"github_release", "github_repo", "github_momentum", "github_trending"} or category == "github":
        return "github"
    if source_kind == "x_allowlist" or category == "x":
        return "x"
    if source_kind == "product_hunt" or category == "product_hunt":
        return "product_hunt"
    if source_kind == "trendradar_hotlist" or category == "trendradar":
        return "trendradar"
    if source_kind == "youtube_channel" or category == "youtube":
        return "youtube"
    if source_kind == "community_feed" and "reddit" in source_name:
        return "reddit"
    if category in AI_SIGNAL_CATEGORY_ORDER:
        return category
    return "other"


def signal_item_haystack(item: dict[str, Any]) -> str:
    topic_tokens = list(item.get("topics", []) or []) + list(item.get("topic_slugs", []) or [])
    parts = [
        compact_text(str(item.get("title", ""))),
        compact_text(str(item.get("summary", ""))),
        compact_text(str(item.get("source_name", ""))),
        compact_text(str(item.get("link", ""))),
        compact_text(str(item.get("canonical_link", ""))),
        compact_text(str(item.get("repo_slug", ""))),
        compact_text(str(item.get("product_name", ""))),
        compact_text(str(item.get("product_slug", ""))),
        compact_text(str(item.get("website", ""))),
        compact_text(str(item.get("x_handle", ""))),
        " ".join(compact_text(str(token)) for token in topic_tokens),
    ]
    return compact_text(" ".join(part for part in parts if part)).lower()


def signal_item_datetime(item: dict[str, Any]) -> datetime | None:
    for key in ("observed_at", "published_sort", "published"):
        value = compact_text(str(item.get(key, "")))
        if not value:
            continue
        parsed = parse_flexible_datetime(value)
        if parsed:
            return parsed
    return None


def is_recent_live_signal_item(
    item: dict[str, Any],
    *,
    max_age_hours: int = 72,
    now: datetime | None = None,
) -> bool:
    if item.get("page_probe"):
        return False
    item_dt = signal_item_datetime(item)
    if item_dt is None:
        return False
    reference = now or datetime.now(UTC)
    return item_dt >= reference - timedelta(hours=max(max_age_hours, 1))


def haystack_contains_term(haystack: str, term: str) -> bool:
    normalized = compact_text(term).lower()
    if not normalized or normalized not in haystack:
        return False
    if any(marker in normalized for marker in (".", "/", "-", " ")):
        return normalized in haystack
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack))


def build_reference_terms(item: dict[str, Any]) -> list[str]:
    generic_terms = {
        "openai",
        "anthropic",
        "google",
        "deepmind",
        "huggingface",
        "developer",
        "developers",
        "tool",
        "tools",
        "agent",
        "agents",
        "llm",
        "llms",
        "api",
        "docs",
    }
    terms: set[str] = set()

    def add(term: str) -> None:
        normalized = compact_text(term).lower()
        if len(normalized) < 4 or normalized in generic_terms:
            return
        terms.add(normalized)

    def add_variants(term: str) -> None:
        text = compact_text(term)
        if not text:
            return
        variants = {text}
        lower_text = text.lower()
        if " by " in lower_text:
            variants.add(re.sub(r"\s+by\s+[a-z0-9 ._-]+$", "", text, flags=re.IGNORECASE).strip())
        if "-by-" in lower_text:
            variants.add(re.sub(r"-by-[a-z0-9._-]+$", "", text, flags=re.IGNORECASE).strip("- "))
        for variant in variants:
            add(variant)

    repo_slug = compact_text(str(item.get("repo_slug", ""))).lower()
    if repo_slug:
        add_variants(repo_slug)
        add_variants(repo_slug.split("/")[-1].replace("-", " "))
        add_variants(repo_slug.split("/")[-1])

    product_name = compact_text(str(item.get("product_name", "")))
    product_slug = compact_text(str(item.get("product_slug", "")))
    if product_name:
        add_variants(product_name)
    if product_slug:
        add_variants(product_slug)
        add_variants(product_slug.replace("-", " "))

    release_tag = compact_text(str(item.get("release_tag", ""))).lower()
    if release_tag:
        add_variants(release_tag)

    website = compact_text(str(item.get("website", "")))
    if website:
        host = urllib.parse.urlsplit(website).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            add_variants(host)
            add_variants(host.split(".")[0])

    if normalize_signal_category(item) in {"product_hunt", "github"}:
        for token in re.findall(r"[a-z0-9][a-z0-9.+]{3,}", compact_text(str(item.get("title", ""))).lower())[:3]:
            add_variants(token)

    return sorted(terms, key=len, reverse=True)


def is_distinctive_reference_term(term: str) -> bool:
    text = compact_text(term).lower()
    alnum = re.sub(r"[^a-z0-9]+", "", text)
    if len(alnum) < 5:
        return False
    if any(character.isdigit() for character in text):
        return True
    if any(marker in text for marker in (" ", "-", ".", "/")) and len(alnum) >= 6:
        return True
    return len(alnum) >= 8


def is_strict_youtube_verification_match(other: dict[str, Any], matched_terms: list[str]) -> bool:
    strong_terms = [term for term in matched_terms if is_distinctive_reference_term(term)]
    if not strong_terms:
        return False
    title_haystack = compact_text(
        " ".join(
            [
                str(other.get("title", "")),
                str(other.get("link", "")),
                str(other.get("canonical_link", "")),
            ]
        )
    ).lower()
    full_haystack = signal_item_haystack(other)
    title_matches = [term for term in strong_terms if haystack_contains_term(title_haystack, term)]
    if any(any(character.isdigit() for character in term) or any(marker in term for marker in (" ", "-", ".", "/")) for term in title_matches):
        return True
    if len(title_matches) >= 2:
        return True
    phrase_terms = [
        term
        for term in strong_terms
        if any(character.isdigit() for character in term) or any(marker in term for marker in (" ", "-", ".", "/"))
    ]
    full_phrase_matches = [term for term in phrase_terms if haystack_contains_term(full_haystack, term)]
    return len(full_phrase_matches) >= 2


def infer_cross_verification_matches(item: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = build_reference_terms(item)
    if not terms:
        return []
    current_category = normalize_signal_category(item)
    current_source = compact_text(str(item.get("source_name", ""))).lower()
    current_link = compact_text(str(item.get("canonical_link", "")))
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for other in items:
        if other is item:
            continue
        if current_link and current_link == compact_text(str(other.get("canonical_link", ""))):
            continue
        other_source = compact_text(str(other.get("source_name", ""))).lower()
        other_category = normalize_signal_category(other)
        if other_category == current_category:
            continue
        if current_category == other_category and current_source == other_source:
            continue
        haystack = signal_item_haystack(other)
        matched_terms = [term for term in terms if haystack_contains_term(haystack, term)]
        if not matched_terms:
            continue
        if other_category == "youtube" and not is_strict_youtube_verification_match(other, matched_terms):
            continue
        identity = (
            other_category,
            compact_text(str(other.get("canonical_link", ""))),
            compact_text(str(other.get("title", ""))).lower(),
        )
        if identity in seen:
            continue
        seen.add(identity)
        matches.append(
            {
                "category": other_category,
                "source_name": compact_text(str(other.get("source_name", ""))) or "Unknown source",
                "title": compact_text(str(other.get("title", ""))) or "Untitled",
                "link": compact_text(str(other.get("link", ""))),
                "matched_terms": matched_terms[:3],
                "published": compact_text(str(other.get("published", ""))),
            }
        )
    return sorted(
        matches,
        key=lambda value: (
            AI_SIGNAL_CATEGORY_ORDER.get(compact_text(str(value.get("category", ""))).lower(), 99),
            compact_text(str(value.get("published", ""))),
            compact_text(str(value.get("title", ""))).lower(),
        ),
        reverse=False,
    )


def infer_cross_verification_channels(item: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
    channels = {
        compact_text(str(match.get("category", ""))).lower()
        for match in infer_cross_verification_matches(item, items)
        if compact_text(str(match.get("category", "")))
    }
    return sorted(channels, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99))


def compute_numeric_median(values: list[int]) -> float:
    filtered = sorted(value for value in values if value is not None)
    if not filtered:
        return 0.0
    middle = len(filtered) // 2
    if len(filtered) % 2:
        return float(filtered[middle])
    return (filtered[middle - 1] + filtered[middle]) / 2


def evaluate_product_hunt_item(
    *,
    item: dict[str, Any],
    product_hunt_items: list[dict[str, Any]],
    target_topics: list[str],
    min_checks: int,
) -> dict[str, Any]:
    vote_median = compute_numeric_median([int(current.get("votes_count", 0) or 0) for current in product_hunt_items])
    comment_median = compute_numeric_median(
        [int(current.get("comments_count", 0) or 0) for current in product_hunt_items]
    )
    topics_text = " ".join(
        list(item.get("topics", []) or []) + [token.replace("-", " ") for token in list(item.get("topic_slugs", []) or [])]
    ).lower()
    topic_targets = {
        compact_text(topic).lower()
        for topic in target_topics
        if compact_text(topic) and compact_text(topic).lower() not in AI_SIGNAL_GENERIC_TOPIC_KEYWORDS
    }
    topic_targets.update(AI_SIGNAL_STRONG_TOPIC_KEYWORDS)
    topic_matches = sorted(topic for topic in topic_targets if haystack_contains_term(topics_text, topic))
    ai_relevant, ai_matches = product_hunt_item_is_ai_relevant(item, target_topics)
    votes_count = int(item.get("votes_count", 0) or 0)
    comments_count = int(item.get("comments_count", 0) or 0)
    checks = {
        "ai_relevant": ai_relevant,
        "featured": bool(item.get("featured")),
        "above_median": (vote_median > 0 and votes_count > vote_median)
        or (comment_median > 0 and comments_count > comment_median),
        "topic_match": bool(topic_matches),
        "builder_surface": bool(item.get("has_builder_surface")),
        "cross_verified": bool(item.get("cross_verification_channels")),
    }
    item["ph_featured"] = checks["featured"]
    item["ph_above_median"] = checks["above_median"]
    item["ph_topic_match"] = checks["topic_match"]
    item["ph_topic_matches"] = topic_matches[:4]
    item["ph_ai_relevant"] = ai_relevant
    item["ph_ai_matches"] = ai_matches[:6]
    item["ph_vote_median"] = vote_median
    item["ph_comment_median"] = comment_median
    item["ph_check_count"] = sum(1 for passed in checks.values() if passed)
    item["ph_checks_passed"] = [name for name, passed in checks.items() if passed]
    item["ph_promoted"] = ai_relevant and item["ph_check_count"] >= max(min_checks, 1)
    return item


def item_has_launch_language(item: dict[str, Any]) -> bool:
    haystack = signal_item_haystack(item)
    launch_markers = [
        "introducing",
        "launch",
        "released",
        "release",
        "preview",
        "available now",
        "now live",
        "open source",
        "open-source",
        "system card",
        "model card",
    ]
    return any(marker in haystack for marker in launch_markers)


def item_has_builder_surface(item: dict[str, Any]) -> bool:
    if item.get("has_builder_surface"):
        return True
    haystack = signal_item_haystack(item)
    return any(marker in haystack for marker in ["api", "docs", "documentation", "huggingface.co", "model card"])


def build_topic_alias_terms(topic: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for raw_value in [topic.get("name", "")] + list(topic.get("aliases", []) or []):
        value = compact_text(str(raw_value))
        if not value:
            continue
        aliases.append(value.lower())
        if " by " in value.lower():
            aliases.append(re.sub(r"\s+by\s+[a-z0-9 ._-]+$", "", value, flags=re.IGNORECASE).strip().lower())
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized = compact_text(alias).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return sorted(deduped, key=len, reverse=True)


def collect_topic_video_evidence_items(topic: dict[str, Any], youtube_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alias_terms = build_topic_alias_terms(topic)
    if not alias_terms:
        return []
    matched_items: list[dict[str, Any]] = []
    for item in youtube_items:
        haystack = signal_item_haystack(item)
        matched_terms = [term for term in alias_terms if haystack_contains_term(haystack, term)]
        if matched_terms and is_strict_youtube_verification_match(item, matched_terms):
            matched_items.append(item)
    return matched_items


def mass_hot_topic_matches(item: dict[str, Any], topic: dict[str, Any]) -> bool:
    haystack = signal_item_haystack(item)
    aliases = [compact_text(str(topic.get("name", "")))] + list(topic.get("aliases", []) or [])
    return any(haystack_contains_term(haystack, compact_text(str(alias)).lower()) for alias in aliases if alias)


def clip_topic_text(text: str, limit: int = 120) -> str:
    normalized = compact_text(text)
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 1, 1)].rstrip() + "…"


def format_dynamic_topic_name(raw_value: str) -> str:
    value = compact_text(raw_value)
    if not value:
        return ""
    replacements = {
        "gpt": "GPT",
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "claude": "Claude",
        "gemini": "Gemini",
        "llama": "Llama",
        "codex": "Codex",
        "cursor": "Cursor",
        "hy3": "Hy3",
        "hunyuan": "Hunyuan",
        "tencent": "Tencent",
    }
    parts: list[str] = []
    for token in re.split(r"(\s+|-)", value):
        lowered = token.lower()
        if lowered in replacements:
            parts.append(replacements[lowered])
        elif re.fullmatch(r"v\d+(?:\.\d+)?", lowered):
            parts.append(token.upper())
        else:
            parts.append(token)
    return compact_text("".join(parts))


def dynamic_topic_candidate_overlaps(name: str, topic_configs: list[dict[str, Any]]) -> bool:
    candidate = compact_text(name).lower()
    if not candidate:
        return False
    for topic in topic_configs:
        for alias in build_topic_alias_terms(topic):
            if candidate == alias or haystack_contains_term(alias, candidate):
                return True
    return False


def extract_dynamic_topic_candidates(item: dict[str, Any]) -> list[str]:
    haystack = signal_item_haystack(item)
    if not any(keyword in haystack for keyword in AI_SIGNAL_STRONG_TOPIC_KEYWORDS):
        return []
    source_category = normalize_signal_category(item)
    if source_category == "github":
        return []
    if source_category == "official" and item.get("page_probe"):
        return []
    if source_category not in {"official", "product_hunt", "trendradar", "x", "reddit", "youtube"}:
        return []
    search_text = " ".join(
        [
            compact_text(str(item.get("title", ""))),
            compact_text(str(item.get("summary", ""))),
        ]
    )
    if not search_text:
        return []
    candidates: list[str] = []
    for pattern, _family in AI_DYNAMIC_TOPIC_PATTERNS:
        for match in re.finditer(pattern, search_text, flags=re.IGNORECASE):
            value = format_dynamic_topic_name(match.group(1))
            if value and len(value) >= 4:
                candidates.append(value)
    if source_category == "product_hunt":
        stripped = re.sub(r"\s+by\s+.+$", "", compact_text(str(item.get("title", ""))), flags=re.IGNORECASE)
        if stripped and any(keyword in stripped.lower() for keyword in AI_SIGNAL_STRONG_TOPIC_KEYWORDS):
            candidates.append(format_dynamic_topic_name(stripped))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = compact_text(candidate).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped


def build_dynamic_mass_hot_topics(items: list[dict[str, Any]], topic_configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_map: dict[str, dict[str, Any]] = {}
    now = datetime.now(UTC)
    for item in items:
        if not is_recent_live_signal_item(item, max_age_hours=72, now=now):
            continue
        for candidate in extract_dynamic_topic_candidates(item):
            if dynamic_topic_candidate_overlaps(candidate, topic_configs):
                continue
            bucket = candidate_map.setdefault(
                candidate.lower(),
                {
                    "name": candidate,
                    "aliases": [candidate.lower()],
                    "items": [],
                },
            )
            bucket["items"].append(item)

    dynamic_topics: list[dict[str, Any]] = []
    for bucket in candidate_map.values():
        matched_items = list(bucket.get("items", []) or [])
        distinct_sources = {
            compact_text(str(item.get("source_name", ""))).lower()
            for item in matched_items
            if compact_text(str(item.get("source_name", "")))
        }
        categories = {normalize_signal_category(item) for item in matched_items}
        public_resonance_categories = categories.intersection({"x", "reddit", "product_hunt", "youtube", "trendradar"})
        if len(distinct_sources) < 2:
            continue
        if len(categories) < 2:
            continue
        if categories.issubset({"official", "github"}):
            continue
        if not public_resonance_categories:
            continue
        dynamic_topics.append(
            {
                "name": bucket["name"],
                "aliases": list(bucket.get("aliases", []) or []),
                "priority": 5 + min(len(distinct_sources), 3),
                "dynamic": True,
            }
        )
    return dynamic_topics


def should_localize_summary_text(text: str) -> bool:
    normalized = compact_text(text)
    if not normalized or re.search(r"[\u3400-\u9fff]", normalized):
        return False
    lowered = normalized.lower()
    if "http://" in lowered or "https://" in lowered:
        return False
    if any(
        marker in lowered
        for marker in (
            "stars today",
            "total stars",
            "recent github stars",
            "repository release for",
            "recent repository activity in",
            "growth ",
            "forks +",
            "watchers +",
            "window ",
        )
    ):
        return True
    word_count = len(re.findall(r"[A-Za-z][A-Za-z0-9.+/#_-]*", normalized))
    if word_count >= 5:
        return True
    if word_count >= 4 and any(punct in normalized for punct in [".", ",", ";", ":", "!", "?"]):
        return True
    return False


def translate_structured_summary_fragment(text: str) -> str:
    normalized = compact_text(text)
    if not normalized:
        return ""
    patterns: list[tuple[str, Any]] = [
        (r"(?i)^(\d+)\s+stars today$", lambda m: f"今日新增 {m.group(1)} stars"),
        (r"(?i)^(\d+)\s+total stars$", lambda m: f"总 stars {m.group(1)}"),
        (r"(?i)^(\d+)\s+forks$", lambda m: f"共 {m.group(1)} 个 forks"),
        (r"(?i)^recent github stars (\d+) in (\d+)d$", lambda m: f"近 {m.group(2)} 天新增 GitHub stars {m.group(1)}"),
        (r"(?i)^stars \+(\d+) to (\d+)$", lambda m: f"stars 增加 {m.group(1)}，达到 {m.group(2)}"),
        (r"(?i)^forks \+(\d+)$", lambda m: f"forks 增加 {m.group(1)}"),
        (r"(?i)^watchers \+(\d+)$", lambda m: f"watchers 增加 {m.group(1)}"),
        (r"(?i)^window (\d+(?:\.\d+)?)h$", lambda m: f"观测窗口 {m.group(1)} 小时"),
        (r"(?i)^growth ([+-]?\d+(?:\.\d+)?)% vs previous snapshot\.?$", lambda m: f"较上次快照增长 {m.group(1)}%"),
        (r"(?i)^repository release for (.+)$", lambda m: f"{m.group(1)} 的版本发布"),
        (r"(?i)^recent repository activity in (.+)$", lambda m: f"{m.group(1)} 的仓库近期活跃"),
    ]
    for pattern, repl in patterns:
        match = re.fullmatch(pattern, normalized)
        if match:
            return compact_text(str(repl(match)))
    return normalized


def dashscope_translation_endpoint() -> str:
    base_url = compact_text(get_env_value("DASHSCOPE_BASE_URL", "QWEN_BASE_URL"))
    if not base_url:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    if base_url.endswith("/chat/completions"):
        return base_url
    return base_url.rstrip("/") + "/chat/completions"


def parse_dashscope_translation(payload: dict[str, Any]) -> str:
    choices = list(payload.get("choices", []) or [])
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return compact_text(str(message.get("content", "")))


def translate_text_to_chinese_via_dashscope_powershell(text: str, *, model: str) -> str:
    if os.name != "nt":
        return ""
    encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
    endpoint = dashscope_translation_endpoint()
    script = f"""
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Net.Http
$key = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY", "Process")
if (-not $key) {{
    $key = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY", "User")
}}
if (-not $key) {{
    exit 0
}}
$text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("{encoded_text}"))
$body = @{{
    model = "{model}"
    messages = @(@{{ role = "user"; content = $text }})
    translation_options = @{{
        source_lang = "auto"
        target_lang = "Chinese"
    }}
}} | ConvertTo-Json -Depth 6 -Compress
$client = [System.Net.Http.HttpClient]::new()
$client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $key)
$content = [System.Net.Http.StringContent]::new($body, [System.Text.Encoding]::UTF8, "application/json")
$response = $client.PostAsync("{endpoint}", $content).GetAwaiter().GetResult()
$bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$payload = $text | ConvertFrom-Json
if ($payload.choices -and $payload.choices[0].message.content) {{
    Write-Output $payload.choices[0].message.content
}}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoLogo", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return compact_text(result.stdout)


@lru_cache(maxsize=512)
def translate_text_to_chinese(text: str) -> str:
    normalized = compact_text(text)
    if not normalized:
        return ""

    dashscope_api_key = get_env_value("DASHSCOPE_API_KEY", "QWEN_API_KEY")
    if dashscope_api_key:
        model = compact_text(get_env_value("AI_SUMMARY_TRANSLATION_MODEL")) or "qwen-mt-plus"
        translated = translate_text_to_chinese_via_dashscope_powershell(normalized, model=model)
        if translated:
            return translated
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": normalized}],
            "translation_options": {"source_lang": "auto", "target_lang": "Chinese"},
        }
        try:
            response = post_json_url(
                dashscope_translation_endpoint(),
                data=payload,
                headers={"Authorization": f"Bearer {dashscope_api_key}"},
                timeout_seconds=45,
            )
            translated = parse_dashscope_translation(response)
            if translated:
                return translated
        except Exception:
            pass

    return normalized


def localize_summary_text(text: str) -> str:
    normalized = compact_text(text)
    if not normalized or not should_localize_summary_text(normalized):
        return normalized
    fragments = [compact_text(fragment) for fragment in re.split(r"\s*;\s*", normalized) if compact_text(fragment)]
    if not fragments:
        return normalized

    localized_fragments: list[str] = []
    changed = False
    for fragment in fragments:
        structured = translate_structured_summary_fragment(fragment)
        if structured != fragment:
            localized_fragments.append(structured)
            changed = True
            continue
        if not should_localize_summary_text(fragment):
            localized_fragments.append(fragment)
            continue
        translated = translate_text_to_chinese(fragment)
        if translated and translated != fragment:
            localized_fragments.append(translated)
            changed = True
            continue
        localized_fragments.append(fragment)

    if not changed:
        return normalized
    return "；".join(localized_fragments)


def infer_mass_hot_topic_kind(topic: dict[str, Any], items: list[dict[str, Any]]) -> str:
    haystack = compact_text(
        " ".join(
            [str(topic.get("name", ""))]
            + [str(alias) for alias in list(topic.get("aliases", []) or [])]
            + [signal_item_haystack(item) for item in items]
        )
    ).lower()
    if any(
        marker in haystack
        for marker in (
            "gpt",
            "deepseek",
            "qwen",
            "claude",
            "gemma",
            "llama",
            "hunyuan",
            "model card",
            "system card",
            "27b",
            "70b",
            "405b",
        )
    ):
        return "模型/模型版本"
    if any(
        marker in haystack
        for marker in (
            "github.com",
            "sdk",
            "cli",
            "framework",
            "open source",
            "open-source",
            "repository",
            "repo",
            "library",
        )
    ):
        return "开发工具/开源项目"
    if any(
        marker in haystack
        for marker in (
            "product hunt",
            "workspace",
            "studio",
            "assistant",
            "automation",
            "app",
            "platform",
        )
    ):
        return "AI 产品/工具"
    return "AI 领域动态"


def build_mass_hot_topic_brief(
    topic: dict[str, Any],
    support_items: list[dict[str, Any]],
    reasons: list[str],
    categories: list[str],
) -> dict[str, str]:
    kind = infer_mass_hot_topic_kind(topic, support_items)
    lead_item = support_items[0] if support_items else {}
    lead_summary = clip_topic_text(localize_summary_text(str(lead_item.get("summary", ""))), 120)
    localized_reasons = format_mass_hot_reasons(reasons)
    localized_categories = ", ".join(category_label(category) for category in categories if compact_text(str(category))) or "多个渠道"

    if kind == "模型/模型版本":
        audience = "对模型选型、应用开发、Agent 工作流团队和技术负责人最重要。"
    elif kind == "开发工具/开源项目":
        audience = "对开发者、自动化搭建者和技术负责人最重要。"
    elif kind == "AI 产品/工具":
        audience = "对找新品、做效率提升和跟踪产品机会的人最重要。"
    else:
        audience = "对关注 AI 行业动态和产品机会的人更重要。"

    what_it_is = f"{topic.get('name', '该话题')} 是今天进入热点池的{kind}。"
    if lead_summary:
        what_it_is += f" 核心信息是：{lead_summary}"
    else:
        what_it_is += " 当前已经出现可验证的信源和讨论。"

    why_hot_today = f"今天它变热，主要因为{localized_reasons}。"
    one_liner = (
        f"{topic.get('name', '该话题')} 是今天值得优先看的{kind}，"
        f"因为它已经在 {localized_categories} 出现可验证信号。"
    )
    return {
        "what_it_is": what_it_is,
        "why_hot_today": why_hot_today,
        "who_it_matters_to": audience,
        "one_liner": one_liner,
    }


def build_mass_hot_topics(
    *,
    items: list[dict[str, Any]],
    signal_config: dict[str, Any],
) -> list[dict[str, Any]]:
    topic_configs = list(signal_config.get("mass_hot_topics", []) or [])
    topic_configs = [*topic_configs, *build_dynamic_mass_hot_topics(items, topic_configs)]
    scoring = dict(signal_config.get("scoring", {}))
    max_topics = int(scoring.get("mass_hot_limit", 6) or 6)
    min_topic_score = float(scoring.get("mass_hot_min_score", 10) or 10)
    live_max_age_hours = int(scoring.get("live_signal_max_age_hours", 72) or 72)
    now = datetime.now(UTC)
    clusters: list[dict[str, Any]] = []

    for topic in topic_configs:
        matched_items = [
            item
            for item in items
            if mass_hot_topic_matches(item, topic)
            and is_recent_live_signal_item(item, max_age_hours=live_max_age_hours, now=now)
        ]
        if not matched_items:
            continue

        categories = {normalize_signal_category(item) for item in matched_items}
        official_items = [item for item in matched_items if normalize_signal_category(item) == "official"]
        official_probe_items = [item for item in official_items if item.get("page_probe")]
        official_story_items = [item for item in official_items if not item.get("page_probe")]
        x_items = [item for item in matched_items if normalize_signal_category(item) == "x"]
        product_hunt_items = [item for item in matched_items if normalize_signal_category(item) == "product_hunt"]
        trendradar_items = [item for item in matched_items if normalize_signal_category(item) == "trendradar"]
        reddit_items = [item for item in matched_items if normalize_signal_category(item) == "reddit"]
        youtube_items = [item for item in matched_items if normalize_signal_category(item) == "youtube"]
        strict_youtube_items = collect_topic_video_evidence_items(topic, youtube_items)
        github_items = [item for item in matched_items if normalize_signal_category(item) == "github"]
        github_momentum_items = [item for item in github_items if item.get("source_kind") == "github_momentum"]
        github_trending_items = [item for item in github_items if item.get("source_kind") == "github_trending"]
        evidence_categories = {
            category
            for category in categories
            if category != "youtube" or strict_youtube_items
        }
        if not evidence_categories:
            continue

        score = min(float(topic.get("priority", 0) or 0), 10.0) * 0.45
        reasons: list[str] = []
        distinct_source_names = {
            compact_text(str(item.get("source_name", "")))
            for item in matched_items
            if compact_text(str(item.get("source_name", "")))
        }
        distinct_links = {
            compact_text(str(item.get("link", "")))
            for item in matched_items
            if compact_text(str(item.get("link", "")))
        }
        source_report_count = max(len(distinct_links), len(distinct_source_names))
        channel_count = len(evidence_categories)

        if official_story_items:
            score += 2
            reasons.append("official release coverage")
        elif official_probe_items:
            score -= 2
            reasons.append("official product-page confirmation")

        resonance_categories = evidence_categories.intersection(
            {"official", "x", "reddit", "product_hunt", "youtube", "trendradar"}
        )
        if resonance_categories:
            resonance_bonus = min(len(resonance_categories) * 1.5, 4.5)
            score += resonance_bonus
            reasons.append(f"broad-channel resonance: {', '.join(sorted(resonance_categories))}")

        if trendradar_items:
            score += min(len(trendradar_items), 2)
            reasons.append("public hotlist resonance")

        if source_report_count >= 2:
            breadth_bonus = min((source_report_count - 1) * 1.2, 4.8)
            score += breadth_bonus
            reasons.append(f"{source_report_count} independent source reports")
        elif not official_story_items:
            score -= 5
            reasons.append("single-source mention")

        if channel_count >= 2:
            score += min((channel_count - 1) * 0.8, 2.4)
            reasons.append(f"{channel_count} channels aligned")

        if any(item_has_launch_language(item) for item in matched_items if normalize_signal_category(item) != "github"):
            score += 2
            reasons.append("launch / preview / release wording")

        max_x_engagement = max((int(item.get("engagement_score", 0) or 0) for item in x_items), default=0)
        if max_x_engagement >= 2000:
            score += 2
            reasons.append("high X engagement")
        elif max_x_engagement >= 300:
            score += 1
            reasons.append("solid X engagement")

        if any(item.get("ph_promoted") for item in product_hunt_items):
            score += 2
            reasons.append("Product Hunt breakout")

        if any(item_has_builder_surface(item) for item in matched_items):
            score += 1
            reasons.append("API / docs / model-card surface")

        if (github_momentum_items or github_trending_items) and evidence_categories.intersection(
            {"official", "x", "reddit", "product_hunt", "youtube", "trendradar"}
        ):
            score += 1
            reasons.append("GitHub demand confirms topic heat")

        published_candidates = [
            parse_flexible_datetime(str(item.get("published_sort", "")))
            or parse_flexible_datetime(str(item.get("published", "")))
            for item in matched_items
        ]
        published_candidates = [candidate for candidate in published_candidates if candidate is not None]
        newest_dt = max(published_candidates) if published_candidates else None
        if newest_dt:
            age_hours = (datetime.now(UTC) - newest_dt).total_seconds() / 3600
            if age_hours <= 24:
                score += 3
                reasons.append("within 24 hours")
            elif age_hours <= 48:
                score += 2
                reasons.append("within 48 hours")
            elif age_hours <= 72:
                score += 1
                reasons.append("within 72 hours")

        if evidence_categories.issubset({"github", "paper"}):
            score -= 4
            reasons.append("developer-only evidence")
        elif evidence_categories == {"github"}:
            score -= 5
            reasons.append("GitHub-only mention")
        elif len(matched_items) == 1 and evidence_categories.intersection({"github", "youtube"}):
            score -= 2
            reasons.append("single-source weak signal")

        support_candidates = [
            item
            for item in matched_items
            if normalize_signal_category(item) != "youtube" or item in strict_youtube_items
        ]
        support_items = sorted(
            support_candidates,
            key=lambda item: (
                1 if normalize_signal_category(item) == "official" and not item.get("page_probe") else 0,
                1 if normalize_signal_category(item) == "x" else 0,
                float(item.get("signal_score", 0) or 0),
                item.get("published_sort", ""),
            ),
            reverse=True,
        )
        topic_brief = build_mass_hot_topic_brief(
            topic=topic,
            support_items=support_items,
            reasons=reasons[:4],
            categories=sorted(evidence_categories, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99)),
        )
        if score < min_topic_score:
            continue

        clusters.append(
            {
                "name": compact_text(str(topic.get("name", ""))),
                "score": round(score, 2),
                "story_count": len(matched_items),
                "categories": sorted(evidence_categories, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99)),
                "reasons": reasons[:4],
                "top_titles": [compact_text(str(item.get("title", ""))) for item in support_items[:3]],
                "top_links": [compact_text(str(item.get("link", ""))) for item in support_items[:3]],
                "top_items": support_items[:3],
                "support_sources": sorted(distinct_source_names)[:8],
                "source_report_count": source_report_count,
                "channel_count": channel_count,
                "dynamic_topic": bool(topic.get("dynamic")),
                "video_titles": [
                    f"{compact_text(str(item.get('title', '未命名视频')))} | {compact_text(str(item.get('source_name', '未知信源')))}"
                    for item in strict_youtube_items[:2]
                ],
                "newest_published": support_items[0].get("published", "") if support_items else "",
                "official_count": len(official_items),
                "community_count": len(x_items)
                + len(reddit_items)
                + len(strict_youtube_items)
                + len(product_hunt_items)
                + len(trendradar_items),
                "github_count": len(github_items),
                **topic_brief,
            }
        )

    return sorted(
        clusters,
        key=lambda item: (
            float(item.get("score", 0) or 0),
            int(item.get("source_report_count", 0) or 0),
            int(item.get("channel_count", 0) or 0),
            int(item.get("story_count", 0) or 0),
            int(item.get("official_count", 0) or 0),
            compact_text(str(item.get("name", ""))).lower(),
        ),
        reverse=True,
    )[: max(max_topics, 1)]


def select_builder_top_signals(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen_repo_slugs: set[str] = set()
    category_counts: dict[str, int] = {}
    max_per_category = 3

    def _can_select(item: dict[str, Any]) -> bool:
        if not item.get("headline_candidate"):
            return False
        if normalize_signal_category(item) == "github" and item.get("source_kind") == "github_repo":
            return False
        repo_slug = compact_text(str(item.get("repo_slug", ""))).lower()
        if repo_slug and repo_slug in seen_repo_slugs:
            return False
        if repo_slug:
            seen_repo_slugs.add(repo_slug)
        return True

    for item in items:
        if not _can_select(item):
            continue
        category = normalize_signal_category(item)
        if category_counts.get(category, 0) >= max_per_category:
            deferred.append(item)
            continue
        selected.append(item)
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(selected) >= max(limit, 1):
            break
    for item in deferred:
        if len(selected) >= max(limit, 1):
            break
        selected.append(item)
    return selected


def score_ai_signal_item(item: dict[str, Any], signal_config: dict[str, Any]) -> dict[str, Any]:
    scoring = dict(signal_config.get("scoring", {}))
    source_weights = dict(scoring.get("source_weights", {}))
    category = normalize_signal_category(item)
    score = float(source_weights.get(category, source_weights.get("other", 1)))
    reasons: list[str] = []
    live_max_age_hours = int(scoring.get("live_signal_max_age_hours", 72) or 72)
    live_recent = is_recent_live_signal_item(item, max_age_hours=live_max_age_hours)

    published_dt = parse_flexible_datetime(str(item.get("published_sort", ""))) or parse_flexible_datetime(
        str(item.get("published", ""))
    )
    fresh_hours_window = int(scoring.get("fresh_hours_bonus_window", 48) or 0)
    if published_dt and fresh_hours_window > 0:
        fresh_cutoff = datetime.now(UTC) - timedelta(hours=fresh_hours_window)
        if published_dt >= fresh_cutoff:
            score += 2
            reasons.append("fresh within lookback window")

    if category == "official":
        score += 0.5
        reasons.append("official source")
        if item.get("page_probe"):
            score -= 3
            reasons.append("homepage / product-page probe")
    elif category == "github":
        source_kind = compact_text(str(item.get("source_kind", ""))).lower()
        if source_kind == "github_trending":
            stars_today = int(item.get("stars_today", 0) or 0)
            score += 4
            reasons.append(f"GitHub trending +{stars_today} stars today")
            if stars_today >= 1000:
                score += 2
                reasons.append("viral GitHub breakout")
            elif stars_today >= 300:
                score += 1
                reasons.append("strong daily GitHub demand")
        elif source_kind == "github_momentum":
            star_delta = max(int(item.get("star_delta", 0) or 0), int(item.get("recent_star_count", 0) or 0))
            score += 4
            reasons.append(f"GitHub star momentum +{star_delta}")
            if star_delta >= 100:
                score += 1
                reasons.append("breakout star growth")
            elif star_delta >= 50:
                score += 0.5
                reasons.append("strong star growth")
        elif item.get("release_tag"):
            score += 1.5
            reasons.append("GitHub release")
            title_text = compact_text(str(item.get("title", ""))).lower()
            if any(marker in title_text for marker in ["patch release", "beta", "alpha", "rc", "hotfix"]):
                score -= 1.5
                reasons.append("incremental release")
        elif item.get("repo_slug"):
            score += 0.5
            reasons.append("GitHub repository activity")
    elif category == "x":
        engagement_score = int(item.get("engagement_score", 0) or 0)
        if engagement_score >= 2000:
            score += 2
            reasons.append("high X engagement")
        elif engagement_score >= 300:
            score += 1
            reasons.append("solid X engagement")
    elif category == "product_hunt":
        if item.get("ph_featured"):
            score += 2
            reasons.append("Product Hunt featured")
        if item.get("ph_above_median"):
            score += 1.5
            reasons.append("votes/comments above PH median")
        if item.get("ph_topic_match"):
            score += 1.5
            reasons.append("AI topic fit")
        if item.get("has_builder_surface"):
            score += 1.5
            reasons.append("GitHub/API/docs surface found")
        if item.get("ph_promoted"):
            score += 2
            reasons.append(f"passed {int(item.get('ph_check_count', 0) or 0)} PH checks")
    elif category == "trendradar":
        hotlist_rank = int(item.get("trendradar_rank", 0) or 0)
        if hotlist_rank and hotlist_rank <= 3:
            score += 2
            reasons.append(f"public hotlist rank #{hotlist_rank}")
        elif hotlist_rank and hotlist_rank <= 10:
            score += 1
            reasons.append(f"public hotlist mention #{hotlist_rank}")
        if len(list(item.get("trendradar_topics", []) or [])) >= 2:
            score += 0.5
            reasons.append("multiple AI topic matches")

    cross_channels = list(item.get("cross_verification_channels", []) or [])
    if cross_channels:
        score += float(scoring.get("cross_verify_bonus", 2) or 0)
        reasons.append(f"cross-verified by {', '.join(cross_channels)}")
        if len(cross_channels) >= 2:
            score += 1
            reasons.append("multi-source resonance")

    if not live_recent:
        score -= 6
        reasons.append("outside live window")

    item["signal_score"] = round(score, 2)
    item["headline_reasons"] = reasons[:5]
    threshold = float(scoring.get("headline_threshold", 10) or 10)
    if item.get("page_probe"):
        item["headline_candidate"] = False
    elif category == "product_hunt":
        item["headline_candidate"] = bool(item.get("ph_promoted"))
    elif category == "official" and not item_has_launch_language(item) and not item.get("cross_verification_channels"):
        item["headline_candidate"] = False
    elif category == "github" and item.get("source_kind") == "github_trending":
        item["headline_candidate"] = bool(
            item.get("headline_candidate")
            or int(item.get("stars_today", 0) or 0)
            >= int(dict(signal_config.get("github_trending", {})).get("headline_stars_today", 300) or 300)
            or item.get("signal_score", 0) >= threshold
        )
    elif category == "github" and item.get("source_kind") == "github_momentum":
        item["headline_candidate"] = bool(
            item.get("headline_candidate")
            or max(int(item.get("star_delta", 0) or 0), int(item.get("recent_star_count", 0) or 0))
            >= int(dict(signal_config.get("github_momentum", {})).get("headline_star_delta", 60) or 60)
            or item.get("signal_score", 0) >= threshold
        )
    elif category == "github" and item.get("source_kind") == "github_repo":
        item["headline_candidate"] = False
    elif category == "trendradar":
        hotlist_rank = int(item.get("trendradar_rank", 0) or 0)
        item["headline_candidate"] = bool(
            item.get("signal_score", 0) >= threshold
            or (hotlist_rank and hotlist_rank <= int(dict(signal_config.get("trendradar_bridge", {})).get("headline_rank_threshold", 5) or 5))
            or item.get("cross_verification_channels")
        )
    else:
        item["headline_candidate"] = bool(item.get("signal_score", 0) >= threshold)
    return item


def sort_signal_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            1 if item.get("headline_candidate") else 0,
            float(item.get("signal_score", 0) or 0),
            1 if item.get("cross_verification_channels") else 0,
            item.get("published_sort", ""),
            -AI_SIGNAL_CATEGORY_ORDER.get(normalize_signal_category(item), 99),
            compact_text(str(item.get("title", ""))).lower(),
        ),
        reverse=True,
    )


def finalize_ai_signal_items(
    *,
    items: list[dict[str, Any]],
    signal_config: dict[str, Any],
    max_items: int,
    since_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cutoff_dt = datetime.now(UTC) - timedelta(days=max(since_days, 1))
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_item in items:
        item = normalize_signal_item(raw_item)
        if not item.get("title") or is_noisy_ai_news_item(item):
            continue
        published_dt = parse_flexible_datetime(str(item.get("published_sort", ""))) or parse_flexible_datetime(
            str(item.get("published", ""))
        )
        if published_dt and published_dt < cutoff_dt:
            continue
        identity = item.get("canonical_link") or "|".join(
            [
                compact_text(str(item.get("category", ""))).lower(),
                compact_text(str(item.get("source_name", ""))).lower(),
                compact_text(str(item.get("title", ""))).lower(),
            ]
        )
        if identity in seen:
            continue
        seen.add(identity)
        prepared.append(item)

    for item in prepared:
        item["cross_verification_matches"] = infer_cross_verification_matches(item, prepared)
        item["cross_verification_channels"] = sorted(
            {
                compact_text(str(match.get("category", ""))).lower()
                for match in list(item.get("cross_verification_matches", []) or [])
                if compact_text(str(match.get("category", "")))
            },
            key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99),
        )
        item["cross_verified"] = bool(item["cross_verification_channels"])

    product_hunt_items = [item for item in prepared if normalize_signal_category(item) == "product_hunt"]
    product_hunt_config = dict(signal_config.get("product_hunt", {}))
    for item in product_hunt_items:
        evaluate_product_hunt_item(
            item=item,
            product_hunt_items=product_hunt_items,
            target_topics=list(product_hunt_config.get("target_topics", [])),
            min_checks=int(product_hunt_config.get("headline_min_checks", 2) or 2),
        )

    scored_items = [score_ai_signal_item(item, signal_config) for item in prepared]
    ranked_items = sort_signal_items(scored_items)
    top_signal_limit = int(dict(signal_config.get("scoring", {})).get("top_signal_limit", 8) or 8)
    top_signals = select_builder_top_signals(ranked_items, max(top_signal_limit, 1))
    return ranked_items[: max(max_items, 1)], top_signals


def format_signal_reasons(item: dict[str, Any]) -> str:
    reason_map = {
        "recent publication": "近期发布",
        "official source": "官方信源",
        "fresh within lookback window": "处于回溯窗口内的最新内容",
        "GitHub release": "GitHub 发布",
        "incremental release": "增量版本发布",
        "GitHub repository activity": "GitHub 仓库活跃",
        "high X engagement": "X 高互动",
        "solid X engagement": "X 互动较强",
        "Product Hunt featured": "Product Hunt Featured",
        "votes/comments above PH median": "票数或评论高于 Product Hunt 中位数",
        "AI topic fit": "命中 AI 主题",
        "GitHub/API/docs surface found": "存在 GitHub、API 或文档落点",
        "multiple AI topic matches": "命中多个 AI 主题词",
        "multi-source resonance": "多源共振",
        "standard monitoring item": "常规监控条目",
    }
    localized: list[str] = []
    for raw_reason in list(item.get("headline_reasons", []) or []):
        reason = compact_text(str(raw_reason))
        if not reason:
            continue
        if reason in reason_map:
            localized.append(reason_map[reason])
        elif reason.startswith("passed ") and reason.endswith(" PH checks"):
            count = compact_text(reason.removeprefix("passed ").removesuffix(" PH checks"))
            localized.append(f"通过 {count} 个 Product Hunt 条件")
        elif reason.startswith("cross-verified by "):
            channels = [category_label(channel.strip()) for channel in reason.removeprefix("cross-verified by ").split(",") if channel.strip()]
            localized.append(f"交叉验证：{', '.join(channels) if channels else '多渠道'}")
        elif reason.startswith("public hotlist rank #"):
            rank = compact_text(reason.removeprefix("public hotlist rank #"))
            localized.append(f"大众热榜靠前：第 {rank} 位")
        elif reason.startswith("public hotlist mention #"):
            rank = compact_text(reason.removeprefix("public hotlist mention #"))
            localized.append(f"进入大众热榜：第 {rank} 位")
        else:
            localized.append(reason)
    if localized:
        return "；".join(localized[:4])
    return "常规监控条目"


def format_mass_hot_reasons(reasons: list[str]) -> str:
    reason_map = {
        "official release coverage": "有官方发布覆盖",
        "official product-page confirmation": "有官方产品页确认",
        "launch / preview / release wording": "命中发布、预览或上线语义",
        "high X engagement": "X 高互动",
        "solid X engagement": "X 互动较强",
        "Product Hunt breakout": "Product Hunt 热门突破",
        "public hotlist resonance": "大众热榜共振",
        "API / docs / model-card surface": "存在 API、文档或模型卡落点",
        "GitHub demand confirms topic heat": "GitHub 热度验证了话题热度",
        "within 24 hours": "24 小时内",
        "within 48 hours": "48 小时内",
        "within 72 hours": "72 小时内",
        "developer-only evidence": "只有开发者侧证据",
        "GitHub-only mention": "仅 GitHub 提及",
        "single-source weak signal": "单一信源弱信号",
        "broad-channel resonance": "多渠道共振",
    }
    localized: list[str] = []
    for raw_reason in reasons:
        reason = compact_text(str(raw_reason))
        if not reason:
            continue
        if reason in reason_map:
            localized.append(reason_map[reason])
        elif reason.startswith("broad-channel resonance: "):
            channels = [
                category_label(channel.strip())
                for channel in reason.removeprefix("broad-channel resonance: ").split(",")
                if channel.strip()
            ]
            localized.append(f"多渠道共振：{', '.join(channels) if channels else '多渠道'}")
        else:
            localized.append(reason)
    return "；".join(localized) if localized else "多源提及"


def collect_cross_verification_titles(item: dict[str, Any], category: str, limit: int = 2) -> list[str]:
    target_category = compact_text(category).lower()
    collected: list[str] = []
    seen: set[str] = set()
    for match in list(item.get("cross_verification_matches", []) or []):
        match_category = compact_text(str(match.get("category", ""))).lower()
        if match_category != target_category:
            continue
        title = compact_text(str(match.get("title", ""))) or "未命名内容"
        source_name = compact_text(str(match.get("source_name", ""))) or "未知信源"
        label = f"{title} | {source_name}"
        if label in seen:
            continue
        seen.add(label)
        collected.append(label)
        if len(collected) >= max(limit, 1):
            break
    return collected


def render_ai_news_digest(
    *,
    today: str,
    items: list[dict[str, Any]],
    top_signals: list[dict[str, Any]] | None = None,
    mass_hot_topics: list[dict[str, Any]] | None = None,
    source_health: list[dict[str, Any]] | None = None,
) -> str:
    top_signals = list(top_signals or [])
    mass_hot_topics = list(mass_hot_topics or [])
    source_health = list(source_health or [])
    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_category.setdefault(normalize_signal_category(item), []).append(item)

    source_status_counts: dict[str, int] = {"ok": 0, "skipped": 0, "error": 0}
    for entry in source_health:
        status = compact_text(str(entry.get("status", ""))).lower() or "error"
        source_status_counts[status] = source_status_counts.get(status, 0) + 1

    category_summary = ", ".join(
        category_label(category)
        for category in sorted(by_category, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99))
    )

    lines = [
        f"# AI 濮ｅ繑妫╂穱鈥冲娇 / Daily Signal - {today}",
        "",
        "## 閹芥顩?/ Summary",
        "",
        f"- 閺夛紕娲伴幀缁樻殶 / Total items: {len(items)}",
        f"- 婢舵挳鍎存穱鈥冲娇 / Top signals: {len(top_signals)}",
        f"- 鐟曞棛娲婄猾璇插焼 / Categories: {category_summary if category_summary else '閺?/ None'}",
    ]
    if source_health:
        lines.append(
            "- 娣団剝绨崑銉ユ倣 / Source health: "
            f"ok={source_status_counts.get('ok', 0)}, skipped={source_status_counts.get('skipped', 0)}, error={source_status_counts.get('error', 0)}"
        )
    lines.append("")

    if top_signals:
        lines.extend(["## Headline Radar / Top Signals", ""])
        for index, item in enumerate(top_signals, start=1):
            verification = ", ".join(item.get("cross_verification_channels", []) or []) or "none"
            lines.extend(
                [
                    f"### {index}. {item['title']}",
                    f"- 閺夈儲绨?/ Source: {item['source_name']} ({category_label(normalize_signal_category(item))})",
                    f"- 閸掑棙鏆?/ Score: {item.get('signal_score', 0)}",
                    f"- 閸掋倖鏌?/ Why it matters: {format_signal_reasons(item)}",
                    f"- 妤犲矁鐦?/ Verification: {verification}",
                    f"- 閸欐垵绔烽弮鍫曟？ / Published: {item['published'] or '閺堫亞鐓?/ Unknown'}",
                    f"- 闁剧偓甯?/ Link: {item['link']}",
                    "",
                ]
            )

    for category in sorted(by_category, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99)):
        category_items = by_category[category]
        lines.extend([f"## {category_label(category)}", ""])
        for index, item in enumerate(category_items, start=1):
            detail_lines = [
                f"### {index}. {item['title']}",
                f"- 閺夈儲绨?/ Source: {item['source_name']}",
                f"- 閸欐垵绔烽弮鍫曟？ / Published: {item['published'] or '閺堫亞鐓?/ Unknown'}",
                f"- 闁剧偓甯?/ Link: {item['link']}",
                f"- 鐟曚胶鍋?/ Signal: {item['summary'] or '閺嗗倹妫ら幗妯款洣閵?/ No summary provided.'}",
            ]
            if item.get("signal_score"):
                detail_lines.append(f"- 閸掑棙鏆?/ Score: {item['signal_score']}")
            if item.get("cross_verification_channels"):
                detail_lines.append(
                    f"- 妤犲矁鐦?/ Verification: {', '.join(item.get('cross_verification_channels', []))}"
                )
            if normalize_signal_category(item) == "product_hunt" and item.get("ph_checks_passed"):
                detail_lines.append(
                    f"- Product Hunt checks: {', '.join(item.get('ph_checks_passed', []))}"
                )
            lines.extend([*detail_lines, ""])

    degraded_sources = [entry for entry in source_health if compact_text(str(entry.get("status", ""))).lower() != "ok"]
    if degraded_sources:
        lines.extend(["## Source Health", ""])
        for entry in degraded_sources:
            status = compact_text(str(entry.get("status", ""))).lower() or "error"
            lines.append(
                "- "
                f"{entry.get('name', 'unknown source')} | status={status} | count={int(entry.get('count', 0) or 0)} | "
                f"detail={compact_text(str(entry.get('detail', ''))) or 'n/a'}"
            )
        lines.append("")

    if not items:
        lines.extend(["- 瑜版挸澧犲▽鈩冩箒闁插洭娉﹂崚鏉垮讲閻劍娼惄顔衡偓?/ No source items were collected.", ""])
    return "\n".join(lines).strip() + "\n"


def fetch_url_text(
    url: str,
    *,
    timeout_seconds: int = 60,
    headers: dict[str, str] | None = None,
) -> str:
    request_headers = {"User-Agent": "Mozilla/5.0 OPC Intelligence Bot"}
    if headers:
        request_headers.update(headers)
    request_obj = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request_obj, timeout=max(timeout_seconds, 1)) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise IntelWorkspaceError(f"HTTP {exc.code} for {url}: {body[:180]}") from exc
    except urllib.error.URLError as exc:
        raise IntelWorkspaceError(f"Network error for {url}: {exc.reason}") from exc


def fetch_json_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    text = fetch_url_text(url, timeout_seconds=timeout_seconds, headers=headers)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IntelWorkspaceError(f"Invalid JSON response from {url}: {text[:180]}") from exc
    if not isinstance(payload, dict):
        raise IntelWorkspaceError(f"Unexpected JSON payload from {url}.")
    return payload


def post_json_url(
    url: str,
    *,
    data: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    request_headers = {"User-Agent": "Mozilla/5.0 OPC Intelligence Bot", "Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request_obj = urllib.request.Request(
        url,
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=max(timeout_seconds, 1)) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise IntelWorkspaceError(f"HTTP {exc.code} for {url}: {body[:180]}") from exc
    except urllib.error.URLError as exc:
        raise IntelWorkspaceError(f"Network error for {url}: {exc.reason}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IntelWorkspaceError(f"Invalid JSON response from {url}: {text[:180]}") from exc
    if not isinstance(payload, dict):
        raise IntelWorkspaceError(f"Unexpected JSON payload from {url}.")
    return payload


def parse_flexible_datetime(value: str) -> datetime | None:
    text = compact_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    parsers = [
        lambda content: datetime.fromisoformat(content),
        lambda content: datetime.strptime(content, "%a, %d %b %Y %H:%M:%S %z"),
        lambda content: datetime.strptime(content, "%a %b %d %H:%M:%S %z %Y"),
        lambda content: datetime.strptime(content, "%Y-%m-%dT%H:%M:%S%z"),
        lambda content: datetime.strptime(content, "%Y-%m-%d"),
        lambda content: datetime.strptime(content, "%b %d, %Y"),
    ]
    for parser in parsers:
        try:
            parsed = parser(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except Exception:
            continue
    return None


def is_noisy_ai_news_item(item: dict[str, Any]) -> bool:
    title = compact_text(str(item.get("title", ""))).lower()
    summary = compact_text(str(item.get("summary", ""))).lower()
    if not title:
        return True
    noisy_keywords = [
        "self-promotion thread",
        "who's hiring",
        "who wants to be hired",
        "weekly",
        "monthly",
        "discord server",
        "hiring thread",
        "show hn",
        "ask hn",
    ]
    return any(keyword in title or keyword in summary for keyword in noisy_keywords)


def summarize_digest_overview(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- 今天没有需要汇总的 PR 变更。"]

    change_counts: dict[str, int] = {"feature": 0, "fix": 0, "maintenance": 0, "other": 0}
    theme_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    high_attention: list[dict[str, Any]] = []
    low_priority: list[dict[str, Any]] = []

    for row in rows:
        change_type = classify_pr_change_type(compact_text(str(row.get("title", ""))))
        change_counts[change_type] = change_counts.get(change_type, 0) + 1
        for theme in classify_pr_themes(
            title=compact_text(str(row.get("title", ""))),
            file_paths=row.get("file_paths", []),
        ):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        for module in collect_row_modules(row):
            module_counts[module] = module_counts.get(module, 0) + 1
        quick_take = compact_text(str(row.get("quick_take", "")))
        quick_take_lower = quick_take.lower()
        if any(
            marker in quick_take_lower
            for marker in (
                "worth a closer read",
                "worth a quick focused review",
            )
        ):
            high_attention.append(row)
        if "low priority" in quick_take_lower or "低优先级" in quick_take:
            low_priority.append(row)

    dominant_change = max(change_counts.items(), key=lambda item: item[1])[0]
    change_summary = describe_change_mix(change_counts)
    top_themes = ", ".join(name for name, _ in sorted(theme_counts.items(), key=lambda item: item[1], reverse=True)[:3])
    top_modules = ", ".join(name for name, _ in sorted(module_counts.items(), key=lambda item: item[1], reverse=True)[:3])
    watchlist = format_watchlist(high_attention[:3])
    low_priority_summary = format_watchlist(low_priority[:2])

    dominant_change_label = {
        "feature": "新增为主",
        "fix": "修复为主",
        "maintenance": "维护为主",
        "other": "混合变更",
    }.get(dominant_change, "混合变更")

    lines = [
        f"- 一句话：今天这批 PR 以{dominant_change_label}，主要集中在 {top_themes or '多个主题'}，重点模块是 {top_modules or '多个区域'}。",
        f"- 变更构成：{change_summary}",
    ]
    if watchlist:
        lines.append(f"- 优先关注：{watchlist}")
    if low_priority_summary:
        lines.append(f"- 可后看：{low_priority_summary}")
    return lines


def build_default_ai_daily_signal_project() -> dict[str, Any]:
    return {
        "folder_name": "03 AI Daily Signal",
        "daily_title_template": "AI 每日信号 - {date}",
        "official_feeds": [
            {
                "name": "OpenAI News",
                "category": "official",
                "url": "https://openai.com/news/rss.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "OpenAI Blog",
                "category": "official",
                "url": "https://openai.com/blog/rss.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "Google AI Blog",
                "category": "official",
                "url": "https://blog.google/technology/ai/rss/",
                "source_kind": "official_feed",
            },
            {
                "name": "Google DeepMind Blog",
                "category": "official",
                "url": "https://deepmind.google/blog/rss.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "Hugging Face Blog",
                "category": "official",
                "url": "https://huggingface.co/blog/feed.xml",
                "source_kind": "official_feed",
            },
            {
                "name": "Anthropic Newsroom",
                "category": "official",
                "url": "https://www.anthropic.com/news",
                "source_kind": "official_web",
            },
            {
                "name": "DeepSeek",
                "category": "official",
                "url": "https://www.deepseek.com/",
                "source_kind": "official_web",
                "text_patterns": ["deepseek-v4", "deepseek v4"],
                "emit_page_probe": True,
                "page_probe_title": "DeepSeek-V4",
            },
            {
                "name": "Qwen / Hugging Face",
                "category": "official",
                "url": "https://huggingface.co/Qwen/Qwen3.6-27B",
                "source_kind": "official_web",
                "page_probe_only": True,
                "text_patterns": ["qwen3.6-27b", "flagship-level coding", "agentic coding"],
                "emit_page_probe": True,
                "page_probe_title": "Qwen3.6-27B",
            },
            {
                "name": "Tencent HY",
                "category": "official",
                "url": "https://cloud.tencent.com/product/hunyuan?Is=home",
                "source_kind": "official_web",
                "page_probe_only": True,
                "text_patterns": ["hy3 preview", "tencent hy3", "hunyuan hy3", "hunyuan"],
                "emit_page_probe": True,
                "page_probe_title": "Tencent Hy3 preview",
            },
        ],
        "community_feeds": [
            {
                "name": "Reddit / r/LocalLLaMA",
                "category": "reddit",
                "url": "https://www.reddit.com/r/LocalLLaMA/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/MachineLearning",
                "category": "reddit",
                "url": "https://www.reddit.com/r/MachineLearning/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/OpenAI",
                "category": "reddit",
                "url": "https://www.reddit.com/r/OpenAI/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/Anthropic",
                "category": "reddit",
                "url": "https://www.reddit.com/r/Anthropic/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/artificial",
                "category": "reddit",
                "url": "https://www.reddit.com/r/artificial/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/ChatGPT",
                "category": "reddit",
                "url": "https://www.reddit.com/r/ChatGPT/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/ClaudeAI",
                "category": "reddit",
                "url": "https://www.reddit.com/r/ClaudeAI/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "Reddit / r/singularity",
                "category": "reddit",
                "url": "https://www.reddit.com/r/singularity/.rss",
                "source_kind": "community_feed",
            },
            {
                "name": "arXiv cs.AI",
                "category": "paper",
                "url": "https://export.arxiv.org/rss/cs.AI",
                "source_kind": "community_feed",
            },
        ],
        "feeds": [],
        "youtube_channels": [
            {
                "name": "OpenAI",
                "category": "youtube",
                "url": "https://www.youtube.com/@OpenAI",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Anthropic",
                "category": "youtube",
                "url": "https://www.youtube.com/@Anthropic",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Google DeepMind",
                "category": "youtube",
                "url": "https://www.youtube.com/@GoogleDeepMind",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Hugging Face",
                "category": "youtube",
                "url": "https://www.youtube.com/@HuggingFace",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Two Minute Papers",
                "category": "youtube",
                "url": "https://www.youtube.com/@TwoMinutePapers",
                "source_kind": "youtube_channel",
            },
            {
                "name": "AI Explained",
                "category": "youtube",
                "url": "https://www.youtube.com/@aiexplained-official",
                "source_kind": "youtube_channel",
            },
            {
                "name": "Matthew Berman",
                "category": "youtube",
                "url": "https://www.youtube.com/@MatthewBerman",
                "source_kind": "youtube_channel",
            },
        ],
        "github_sources": [
            {
                "name": "OpenAI Agents SDK",
                "category": "github",
                "repo": "openai/openai-agents-python",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "MCP Servers",
                "category": "github",
                "repo": "modelcontextprotocol/servers",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "OPC Skills",
                "category": "github",
                "repo": "ReScienceLab/opc-skills",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "OpenClaw",
                "category": "github",
                "repo": "openclaw/openclaw",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "AutoGen",
                "category": "github",
                "repo": "microsoft/autogen",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "LangGraph",
                "category": "github",
                "repo": "langchain-ai/langgraph",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "CrewAI",
                "category": "github",
                "repo": "crewAIInc/crewAI",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "browser-use",
                "category": "github",
                "repo": "browser-use/browser-use",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "vLLM",
                "category": "github",
                "repo": "vllm-project/vllm",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "Transformers",
                "category": "github",
                "repo": "huggingface/transformers",
                "mode": "releases",
                "source_kind": "github_release",
            },
            {
                "name": "Dify",
                "category": "github",
                "repo": "langgenius/dify",
                "mode": "releases",
                "source_kind": "github_release",
            },
        ],
        "x_accounts": [
            {"name": "OpenAI", "category": "x", "handle": "OpenAI", "source_kind": "x_allowlist"},
            {"name": "Anthropic", "category": "x", "handle": "AnthropicAI", "source_kind": "x_allowlist"},
            {"name": "Google DeepMind", "category": "x", "handle": "GoogleDeepMind", "source_kind": "x_allowlist"},
            {"name": "Hugging Face", "category": "x", "handle": "huggingface", "source_kind": "x_allowlist"},
            {"name": "xAI", "category": "x", "handle": "xai", "source_kind": "x_allowlist"},
            {"name": "Meta AI", "category": "x", "handle": "AIatMeta", "source_kind": "x_allowlist"},
            {"name": "Mistral AI", "category": "x", "handle": "MistralAI", "source_kind": "x_allowlist"},
            {"name": "Perplexity", "category": "x", "handle": "perplexity_ai", "source_kind": "x_allowlist"},
            {"name": "Cohere", "category": "x", "handle": "cohere", "source_kind": "x_allowlist"},
            {"name": "Runway", "category": "x", "handle": "runwayml", "source_kind": "x_allowlist"},
            {"name": "Midjourney", "category": "x", "handle": "midjourney", "source_kind": "x_allowlist"},
            {"name": "Stability AI", "category": "x", "handle": "StabilityAI", "source_kind": "x_allowlist"},
            {"name": "ElevenLabs", "category": "x", "handle": "elevenlabsio", "source_kind": "x_allowlist"},
            {"name": "Scale AI", "category": "x", "handle": "scale_AI", "source_kind": "x_allowlist"},
            {"name": "Cursor", "category": "x", "handle": "cursor_ai", "source_kind": "x_allowlist"},
            {"name": "Windsurf", "category": "x", "handle": "windsurf_ai", "source_kind": "x_allowlist"},
            {"name": "Sam Altman", "category": "x", "handle": "sama", "source_kind": "x_allowlist"},
            {"name": "Elon Musk", "category": "x", "handle": "elonmusk", "source_kind": "x_kol"},
            {"name": "Greg Yang", "category": "x", "handle": "TheGregYang", "source_kind": "x_kol"},
            {"name": "Guillaume Lample", "category": "x", "handle": "GuillaumeLample", "source_kind": "x_kol"},
            {"name": "Arthur Mensch", "category": "x", "handle": "arthurmensch", "source_kind": "x_kol"},
            {"name": "Demis Hassabis", "category": "x", "handle": "demishassabis", "source_kind": "x_kol"},
            {"name": "Dario Amodei", "category": "x", "handle": "darioamodei", "source_kind": "x_kol"},
            {"name": "Aravind Srinivas", "category": "x", "handle": "AravSrinivas", "source_kind": "x_kol"},
            {"name": "Alexandr Wang", "category": "x", "handle": "alexandr_wang", "source_kind": "x_kol"},
            {"name": "Andrej Karpathy", "category": "x", "handle": "karpathy", "source_kind": "x_allowlist"},
            {"name": "Harrison Chase", "category": "x", "handle": "hwchase17", "source_kind": "x_allowlist"},
            {"name": "Ethan Mollick", "category": "x", "handle": "emollick", "source_kind": "x_kol"},
            {"name": "Yann LeCun", "category": "x", "handle": "ylecun", "source_kind": "x_kol"},
            {"name": "Andrew Ng", "category": "x", "handle": "AndrewYNg", "source_kind": "x_kol"},
            {"name": "Jim Fan", "category": "x", "handle": "DrJimFan", "source_kind": "x_kol"},
            {"name": "Logan Kilpatrick", "category": "x", "handle": "OfficialLoganK", "source_kind": "x_kol"},
            {"name": "Clement Delangue", "category": "x", "handle": "ClementDelangue", "source_kind": "x_kol"},
            {"name": "Simon Willison", "category": "x", "handle": "simonw", "source_kind": "x_kol"},
            {"name": "Bojan Tunguz", "category": "x", "handle": "tunguz", "source_kind": "x_kol"},
            {"name": "Riley Goodside", "category": "x", "handle": "goodside", "source_kind": "x_kol"},
        ],
        "x_strategy": {
            "rotation_enabled": True,
            "max_accounts_per_run": 5,
            "delay_seconds": 1.2,
        },
        "trendradar_bridge": {
            "enabled": True,
            "repo_path": str(DEFAULT_TRENDRADAR_REPO),
            "timeout_seconds": 180,
            "min_refresh_minutes": 45,
            "limit": 12,
            "max_rank": 15,
            "headline_rank_threshold": 5,
            "topic_groups": deepcopy(DEFAULT_TRENDRADAR_BRIDGE_TOPIC_GROUPS),
            "exclude_terms": [],
        },
        "product_hunt": {
            "enabled": True,
            "count": 18,
            "target_topics": [
                "ai agents",
                "llms",
                "ai infrastructure",
                "developer tools",
                "artificial intelligence",
                "open source",
                "api",
            ],
            "headline_min_checks": 2,
            "builder_surface_probe_limit": 8,
        },
        "github_momentum": {
            "enabled": True,
            "min_total_stars": 500,
            "min_star_delta": 25,
            "min_star_growth_ratio": 0.03,
            "min_ratio_absolute_delta": 10,
            "min_snapshot_hours": 12,
            "headline_star_delta": 60,
        },
        "github_trending": {
            "enabled": True,
            "count": 6,
            "since": "daily",
            "min_stars_today": 120,
            "headline_stars_today": 300,
            "keywords": [
                "ai",
                "agent",
                "claude",
                "gpt",
                "llm",
                "mcp",
                "model",
                "inference",
                "rag",
                "diffusion",
                "huggingface",
                "deepseek",
            ],
        },
        "mass_hot_topics": [],
        "scoring": {
            "headline_threshold": 11,
            "top_signal_limit": 8,
            "mass_hot_limit": 6,
            "source_weights": {
                "official": 5,
                "github": 4,
                "x": 7,
                "product_hunt": 6,
                "trendradar": 7,
                "reddit": 4,
                "paper": 2,
                "youtube": 3,
                "other": 1,
            },
            "cross_verify_bonus": 1.5,
            "fresh_hours_bonus_window": 48,
            "live_signal_max_age_hours": 72,
            "mass_hot_min_score": 10,
        },
    }


def normalize_ai_daily_signal_config(config: dict[str, Any]) -> dict[str, Any]:
    defaults = build_default_ai_daily_signal_project()
    normalized = merge_nested_dict(defaults, config)

    legacy_feeds = list(config.get("feeds", []))
    official_categories = {"official", "company", "product"}
    official_legacy_feeds = [
        dict(item, source_kind=item.get("source_kind") or "official_feed")
        for item in legacy_feeds
        if compact_text(str(item.get("category", ""))).lower() in official_categories
    ]
    community_legacy_feeds = [
        dict(item, source_kind=item.get("source_kind") or "community_feed")
        for item in legacy_feeds
        if compact_text(str(item.get("category", ""))).lower() not in official_categories
    ]

    normalized["official_feeds"] = dedupe_source_dicts(
        list(config.get("official_feeds", [])) + official_legacy_feeds + defaults["official_feeds"]
    )
    normalized["community_feeds"] = dedupe_source_dicts(
        list(config.get("community_feeds", [])) + community_legacy_feeds + defaults["community_feeds"]
    )
    normalized["feeds"] = dedupe_source_dicts(legacy_feeds)
    normalized["youtube_channels"] = dedupe_source_dicts(
        list(config.get("youtube_channels", [])) + defaults["youtube_channels"]
    )
    normalized["github_sources"] = dedupe_source_dicts(
        list(config.get("github_sources", [])) + defaults["github_sources"]
    )
    normalized["x_accounts"] = dedupe_source_dicts(
        list(config.get("x_accounts", [])) + defaults["x_accounts"]
    )
    normalized["x_strategy"] = merge_nested_dict(defaults["x_strategy"], dict(config.get("x_strategy", {})))
    normalized["trendradar_bridge"] = merge_nested_dict(
        defaults["trendradar_bridge"],
        dict(config.get("trendradar_bridge", {})),
    )
    normalized["product_hunt"] = merge_nested_dict(defaults["product_hunt"], dict(config.get("product_hunt", {})))
    normalized["github_momentum"] = merge_nested_dict(
        defaults["github_momentum"],
        dict(config.get("github_momentum", {})),
    )
    normalized["github_trending"] = merge_nested_dict(
        defaults["github_trending"],
        dict(config.get("github_trending", {})),
    )
    mass_hot_topics: list[dict[str, Any]] = []
    seen_mass_hot_topics: set[str] = set()
    for item in list(config.get("mass_hot_topics", [])) + list(defaults.get("mass_hot_topics", [])):
        topic_name = compact_text(str(item.get("name", ""))).lower()
        if not topic_name or topic_name in seen_mass_hot_topics:
            continue
        seen_mass_hot_topics.add(topic_name)
        mass_hot_topics.append(dict(item))
    normalized["mass_hot_topics"] = mass_hot_topics
    normalized["scoring"] = merge_nested_dict(defaults["scoring"], dict(config.get("scoring", {})))
    return normalized


def resolve_youtube_feed_url(channel_url: str) -> str:
    html = fetch_url_text(channel_url)
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("link", href=True):
        if compact_text(str(link.get("type", ""))).lower() == "application/rss+xml":
            return compact_text(str(link.get("href", "")))
    for marker in ['"channelId":"', '"externalId":"']:
        marker_index = html.find(marker)
        if marker_index >= 0:
            start = marker_index + len(marker)
            end = html.find('"', start)
            if end > start:
                return f"https://www.youtube.com/feeds/videos.xml?channel_id={html[start:end]}"
    return ""


AI_CATEGORY_LABELS.update(
    {
        "reddit": "社区",
        "paper": "论文",
        "product": "产品",
        "company": "公司",
        "youtube": "视频",
        "other": "其他",
        "official": "官方",
        "github": "GitHub",
        "x": "X",
        "product_hunt": "Product Hunt",
        "trendradar": "大众热榜",
    }
)


def category_label(category: str) -> str:
    return AI_CATEGORY_LABELS.get(compact_text(category).lower(), compact_text(category) or "其他")


def render_ai_news_digest(
    *,
    today: str,
    items: list[dict[str, Any]],
    top_signals: list[dict[str, Any]] | None = None,
    mass_hot_topics: list[dict[str, Any]] | None = None,
    source_health: list[dict[str, Any]] | None = None,
) -> str:
    top_signals = list(top_signals or [])
    mass_hot_topics = list(mass_hot_topics or [])
    source_health = list(source_health or [])
    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_category.setdefault(normalize_signal_category(item), []).append(item)

    source_status_counts: dict[str, int] = {"ok": 0, "skipped": 0, "error": 0}
    for entry in source_health:
        status = compact_text(str(entry.get("status", ""))).lower() or "error"
        source_status_counts[status] = source_status_counts.get(status, 0) + 1

    category_summary = ", ".join(
        category_label(category)
        for category in sorted(by_category, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99))
    )

    lines = [
        f"# AI 每日信号 - {today}",
        "",
        "## 摘要",
        "",
        f"- 总条目数：{len(items)}",
        f"- 大众热榜数：{len(mass_hot_topics)}",
        f"- 开发者信号数：{len(top_signals)}",
        f"- 分类：{category_summary if category_summary else '无'}",
    ]
    if source_health:
        lines.append(
            "- 信源健康度："
            f"正常={source_status_counts.get('ok', 0)}, 跳过={source_status_counts.get('skipped', 0)}, 异常={source_status_counts.get('error', 0)}"
        )
    lines.append("")

    if mass_hot_topics:
        lines.extend(["## 大众热榜", ""])
        for index, topic in enumerate(mass_hot_topics, start=1):
            topic_categories = ", ".join(category_label(category) for category in list(topic.get("categories", []) or [])) or "无"
            lines.extend(
                [
                    f"### {index}. {topic.get('name', '未命名话题')}",
                    f"- 一句话判断：{topic.get('one_liner', '这是今天值得关注的 AI 热点。')}",
                    f"- 热度分：{topic.get('score', 0)}",
                    f"- 证据渠道：{topic_categories}",
                    f"- 这是什么：{topic.get('what_it_is', '暂无说明。')}",
                    f"- 热点原因：{format_mass_hot_reasons(list(topic.get('reasons', []) or []))}",
                    f"- 为什么今天热：{topic.get('why_hot_today', '今天在多个渠道出现了相关信号。')}",
                    f"- 对谁重要：{topic.get('who_it_matters_to', '对关注 AI 热点的人都重要。')}",
                    f"- 独立信源数：{int(topic.get('source_report_count', 0) or 0)}",
                    f"- 渠道数：{int(topic.get('channel_count', 0) or 0)}",
                    f"- 支撑条目数：{int(topic.get('story_count', 0) or 0)}",
                ]
            )
            if list(topic.get("support_sources", []) or []):
                lines.append(f"- 支撑信源：{'、'.join(list(topic.get('support_sources', []) or [])[:6])}")
            if list(topic.get("video_titles", []) or []):
                lines.append(f"- 视频命中：{'；'.join(list(topic.get('video_titles', []) or [])[:2])}")
            for support_item in list(topic.get("top_items", []) or [])[:2]:
                lines.append(f"- 支撑内容：{support_item.get('title', '未命名内容')} | {support_item.get('source_name', '未知信源')}")
            lines.append("")

    if top_signals:
        lines.extend(["## 头部信号", ""])
        for index, item in enumerate(top_signals, start=1):
            verification = ", ".join(
                category_label(channel) for channel in list(item.get("cross_verification_channels", []) or []) if compact_text(str(channel))
            ) or "无"
            video_titles = collect_cross_verification_titles(item, "youtube")
            lines.extend(
                [
                    f"### {index}. {item['title']}",
                    f"- 来源：{item['source_name']} ({category_label(normalize_signal_category(item))})",
                    f"- 分数：{item.get('signal_score', 0)}",
                    f"- 价值判断：{format_signal_reasons(item)}",
                    f"- 交叉验证：{verification}",
                    f"- 发布时间：{item['published'] or '未知'}",
                    f"- 链接：{item['link']}",
                    "",
                ]
            )
            if video_titles:
                lines.insert(len(lines) - 1, f"- 视频命中：{'；'.join(video_titles)}")

    x_kol_items = [item for item in items if normalize_signal_category(item) == "x"][:6]
    if x_kol_items:
        lines.extend(["## X 名人观点", ""])
        for index, item in enumerate(x_kol_items, start=1):
            metrics = dict(item.get("metrics", {}) or {})
            engagement = int(item.get("engagement_score", 0) or 0)
            lines.extend(
                [
                    f"### {index}. {item.get('source_name', 'X')}：{item['title']}",
                    f"- 作者：{item.get('source_name', '未知账号')}",
                    f"- 互动：综合分 {engagement}，likes={int(metrics.get('likes', 0) or 0)}, retweets={int(metrics.get('retweets', 0) or 0)}, replies={int(metrics.get('replies', 0) or 0)}",
                    f"- 发布时间：{item.get('published') or '未知'}",
                    f"- 链接：{item.get('link', '')}",
                    f"- 要点：{localize_summary_text(str(item.get('summary', ''))) or '暂无摘要。'}",
                    "",
                ]
            )

    community_video_items = [
        item for item in items if normalize_signal_category(item) in {"reddit", "youtube"}
    ][:6]
    if community_video_items:
        lines.extend(["## 社区与视频热点", ""])
        for index, item in enumerate(community_video_items, start=1):
            lines.extend(
                [
                    f"### {index}. {item['title']}",
                    f"- 来源：{item.get('source_name', '未知信源')} ({category_label(normalize_signal_category(item))})",
                    f"- 发布时间：{item.get('published') or '未知'}",
                    f"- 链接：{item.get('link', '')}",
                    f"- 要点：{localize_summary_text(str(item.get('summary', ''))) or '暂无摘要。'}",
                    "",
                ]
            )

    for category in sorted(by_category, key=lambda value: AI_SIGNAL_CATEGORY_ORDER.get(value, 99)):
        category_items = by_category[category]
        lines.extend([f"## {category_label(category)}", ""])
        for index, item in enumerate(category_items, start=1):
            localized_summary = localize_summary_text(str(item.get("summary", "")))
            detail_lines = [
                f"### {index}. {item['title']}",
                f"- 来源：{item['source_name']}",
                f"- 发布时间：{item['published'] or '未知'}",
                f"- 链接：{item['link']}",
                f"- 要点：{localized_summary or '暂无摘要。'}",
            ]
            if item.get("signal_score"):
                detail_lines.append(f"- 分数：{item['signal_score']}")
            if item.get("cross_verification_channels"):
                detail_lines.append(
                    "- 交叉验证："
                    + ", ".join(
                        category_label(channel)
                        for channel in list(item.get("cross_verification_channels", []) or [])
                        if compact_text(str(channel))
                    )
                )
            video_titles = collect_cross_verification_titles(item, "youtube")
            if video_titles:
                detail_lines.append(f"- 视频命中：{'；'.join(video_titles)}")
            if item.get("source_kind") == "github_momentum":
                detail_lines.append(
                    "- GitHub 动量："
                    f"stars +{int(item.get('star_delta', 0) or 0)}, "
                    f"最近 stars {int(item.get('recent_star_count', 0) or 0)}, "
                    f"forks +{int(item.get('fork_delta', 0) or 0)}, "
                    f"窗口 {item.get('snapshot_window_hours', 0)}h"
                )
            if item.get("source_kind") == "github_trending":
                detail_lines.append(
                    "- GitHub 热榜："
                    f"今日新增 {int(item.get('stars_today', 0) or 0)} stars, "
                    f"总 stars {int(item.get('stargazers_count', 0) or 0)}"
                )
            if item.get("source_kind") == "trendradar_hotlist":
                topic_text = "、".join(list(item.get("trendradar_topics", []) or [])[:3]) or "AI"
                detail_lines.append(
                    "- 大众热榜："
                    f"{item.get('trendradar_platform', 'TrendRadar')} 第 {int(item.get('trendradar_rank', 0) or 0)} 位，"
                    f"主题 {topic_text}"
                )
            if normalize_signal_category(item) == "product_hunt" and item.get("ph_checks_passed"):
                ph_label_map = {
                    "featured": "Featured",
                    "above_median": "高于中位数",
                    "topic_match": "主题命中",
                    "builder_surface": "存在 GitHub/API/文档",
                    "cross_verified": "已交叉验证",
                }
                detail_lines.append(
                    "- Product Hunt 条件命中："
                    + ", ".join(ph_label_map.get(name, name) for name in list(item.get("ph_checks_passed", []) or []))
                )
            lines.extend([*detail_lines, ""])

    degraded_sources = [entry for entry in source_health if compact_text(str(entry.get("status", ""))).lower() != "ok"]
    if degraded_sources:
        lines.extend(["## 信源健康度", ""])
        for entry in degraded_sources:
            status = compact_text(str(entry.get("status", ""))).lower() or "error"
            status_label = {"ok": "正常", "skipped": "跳过", "error": "异常"}.get(status, status)
            lines.append(
                "- "
                f"{entry.get('name', '未知信源')} | 状态={status_label} | 数量={int(entry.get('count', 0) or 0)} | "
                f"详情={compact_text(str(entry.get('detail', ''))) or '无'}"
            )
        lines.append("")

    if not items:
        lines.extend(["- 当前未采集到可用条目。", ""])
    return "\n".join(lines).strip() + "\n"
