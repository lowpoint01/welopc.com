from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .intel_workspace import (
    category_label,
    get_ai_daily_signal_runtime_bucket,
    get_project_daily_doc,
    generate_ai_news_digest,
    is_recent_live_signal_item,
    load_opc_state,
    localize_summary_text,
    normalize_signal_category,
    save_opc_state,
)
from .storage import ROOT
from .utils import compact_text, ensure_dirs


TIMELINE_CONFIG_PATH = ROOT / "configs" / "ai_signal_timeline.yaml"
DEFAULT_SITE_DIR = ROOT / "site" / "ai-signal-live"


def build_default_ai_signal_timeline() -> dict[str, Any]:
    return {
        "preset": "live_pulse",
        "timezone": "Asia/Shanghai",
        "site": {
            "title": "AI Signal Radar",
            "subtitle": "每 30 分钟刷新一次的 AI 实时热点、GitHub 增长与社区视频监控流",
            "output_dir": str(DEFAULT_SITE_DIR),
            "history_limit": 72,
            "refresh_interval_minutes": 30,
        },
        "presets": {
            "live_pulse": {
                "name": "AI 实时热点雷达",
                "description": "持续刷新网站，默认不推送飞书正式日报。",
                "default": {
                    "enabled": True,
                    "limit_per_source": 3,
                    "max_items": 36,
                    "since_days": 1,
                    "export_site": True,
                    "publish_feishu": False,
                    "once": {
                        "run_digest": False,
                        "publish_feishu": False,
                        "export_site": False,
                    },
                },
                "periods": {
                    "live_monitor": {
                        "name": "实时雷达",
                        "start": "00:00",
                        "end": "23:59",
                        "enabled": True,
                        "limit_per_source": 3,
                        "max_items": 36,
                        "since_days": 1,
                        "export_site": True,
                    },
                },
                "day_plans": {
                    "weekday": {
                        "periods": [
                            "live_monitor",
                        ]
                    },
                    "weekend": {
                        "periods": [
                            "live_monitor",
                        ]
                    },
                },
                "week_map": {
                    1: "weekday",
                    2: "weekday",
                    3: "weekday",
                    4: "weekday",
                    5: "weekday",
                    6: "weekend",
                    7: "weekend",
                },
                "overlap": {
                    "policy": "error_on_overlap",
                },
            }
        },
    }


def merge_nested_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_nested_dict(dict(merged.get(key, {})), value)
        else:
            merged[key] = value
    return merged


def load_ai_signal_timeline_config(path: Path | None = None) -> dict[str, Any]:
    config_path = Path(path or TIMELINE_CONFIG_PATH)
    defaults = build_default_ai_signal_timeline()
    if not config_path.exists():
        ensure_dirs(config_path.parent)
        config_path.write_text(yaml.safe_dump(defaults, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return defaults
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    merged = merge_nested_dict(defaults, raw if isinstance(raw, dict) else {})
    merged["site"] = merge_nested_dict(defaults["site"], dict(merged.get("site", {})))
    return merged


def _parse_time(value: str) -> time:
    hour_str, minute_str = compact_text(value).split(":", 1)
    return time(hour=int(hour_str), minute=int(minute_str))


def _period_matches(now_value: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_value < end
    return now_value >= start or now_value < end


def resolve_ai_signal_schedule_slot(
    *, config: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    timezone_name = compact_text(str(config.get("timezone", ""))) or "Asia/Shanghai"
    zone = ZoneInfo(timezone_name)
    current = now.astimezone(zone) if now else datetime.now(zone)
    preset_key = compact_text(str(config.get("preset", ""))) or "live_pulse"
    presets = dict(config.get("presets", {}))
    preset = dict(presets.get(preset_key, {}))
    if not preset:
        raise ValueError(f"Unknown AI signal timeline preset: {preset_key}")

    default_plan = dict(preset.get("default", {}))
    default_once = dict(default_plan.get("once", {}))
    week_map = {int(key): value for key, value in dict(preset.get("week_map", {})).items()}
    day_plans = dict(preset.get("day_plans", {}))
    day_key = compact_text(str(week_map.get(current.isoweekday(), "")))
    day_plan = dict(day_plans.get(day_key, {}))
    period_names = list(day_plan.get("periods", []) or [])
    periods = dict(preset.get("periods", {}))

    matches: list[tuple[str, dict[str, Any]]] = []
    for period_key in period_names:
        period = dict(periods.get(period_key, {}))
        start = _parse_time(str(period.get("start", "00:00")))
        end = _parse_time(str(period.get("end", "23:59")))
        if _period_matches(current.timetz().replace(tzinfo=None), start, end):
            matches.append((period_key, period))

    overlap_policy = compact_text(str((preset.get("overlap") or {}).get("policy", "error_on_overlap"))) or "error_on_overlap"
    if len(matches) > 1 and overlap_policy == "error_on_overlap":
        raise ValueError(f"Overlapping AI signal schedule periods detected: {', '.join(key for key, _ in matches)}")
    period_key, period = matches[-1] if matches else ("default", {})
    plan = merge_nested_dict(default_plan, period)
    plan["once"] = merge_nested_dict(default_once, dict(period.get("once", {})))
    plan["preset"] = preset_key
    plan["preset_name"] = compact_text(str(preset.get("name", ""))) or preset_key
    plan["period_key"] = period_key
    plan["period_name"] = compact_text(str(period.get("name", ""))) or "默认静默期"
    plan["is_default_period"] = period_key == "default"
    plan["timezone"] = timezone_name
    plan["resolved_at"] = current.isoformat()
    return plan


def _sanitize_topic(topic: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": topic.get("name", ""),
        "score": topic.get("score", 0),
        "one_liner": topic.get("one_liner", ""),
        "what_it_is": topic.get("what_it_is", ""),
        "why_hot_today": topic.get("why_hot_today", ""),
        "who_it_matters_to": topic.get("who_it_matters_to", ""),
        "categories": [category_label(str(category)) for category in list(topic.get("categories", []) or [])],
        "reasons": list(topic.get("reasons", []) or []),
        "story_count": int(topic.get("story_count", 0) or 0),
        "source_report_count": int(topic.get("source_report_count", 0) or 0),
        "channel_count": int(topic.get("channel_count", 0) or 0),
        "support_sources": list(topic.get("support_sources", []) or []),
        "dynamic_topic": bool(topic.get("dynamic_topic", False)),
        "video_titles": list(topic.get("video_titles", []) or []),
        "top_items": [
            {
                "title": item.get("title", ""),
                "source_name": item.get("source_name", ""),
                "link": item.get("link", ""),
            }
            for item in list(topic.get("top_items", []) or [])[:3]
        ],
    }


def _sanitize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "source_name": item.get("source_name", ""),
        "category": category_label(normalize_signal_category(item)),
        "published": item.get("published", ""),
        "observed_at": item.get("observed_at", ""),
        "link": item.get("link", ""),
        "summary": localize_summary_text(str(item.get("summary", ""))),
        "signal_score": item.get("signal_score", 0),
        "cross_verification_channels": [
            category_label(str(channel)) for channel in list(item.get("cross_verification_channels", []) or [])
        ],
        "source_kind": item.get("source_kind", ""),
        "trendradar_platform": item.get("trendradar_platform", ""),
        "trendradar_rank": item.get("trendradar_rank", 0),
    }


def _recent_live_items(items: list[dict[str, Any]], *, limit: int, max_age_hours: int = 72) -> list[dict[str, Any]]:
    live_items = [item for item in items if is_recent_live_signal_item(item, max_age_hours=max_age_hours)]
    return [_sanitize_item(item) for item in live_items[:limit]]


def _build_site_payload(
    *,
    digest: dict[str, Any],
    schedule_plan: dict[str, Any],
    site_config: dict[str, Any],
    doc_url: str,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    top_signals = _recent_live_items(list(digest.get("top_signals", []) or []), limit=8)
    mass_hot_topics = [_sanitize_topic(item) for item in list(digest.get("mass_hot_topics", []) or [])[:6]]
    community_hotspots = _recent_live_items(list(digest.get("community_video_hotspots", []) or []), limit=6)
    x_kol_hotspots = _recent_live_items(list(digest.get("x_kol_hotspots", []) or []), limit=6)
    recent_items = _recent_live_items(list(digest.get("items", []) or []), limit=18)
    generated_at = compact_text(str(schedule_plan.get("resolved_at", "")))
    timezone_name = compact_text(str(schedule_plan.get("timezone", "Asia/Shanghai"))) or "Asia/Shanghai"
    try:
        generated_time = datetime.fromisoformat(generated_at)
    except ValueError:
        generated_time = datetime.now(ZoneInfo(timezone_name))
        generated_at = generated_time.isoformat()
    refresh_interval_minutes = max(int(site_config.get("refresh_interval_minutes", 30) or 30), 1)
    next_update_at = (generated_time + timedelta(minutes=refresh_interval_minutes)).isoformat()
    return {
        "generated_at": generated_at,
        "timezone": timezone_name,
        "refresh": {
            "mode": "systemd_timer",
            "interval_minutes": refresh_interval_minutes,
            "interval_seconds": refresh_interval_minutes * 60,
            "last_updated_at": generated_at,
            "next_update_at": next_update_at,
            "label": f"每 {refresh_interval_minutes} 分钟",
        },
        "site": {
            "title": compact_text(str(site_config.get("title", ""))) or "AI Signal Radar",
            "subtitle": compact_text(str(site_config.get("subtitle", ""))),
            "doc_url": doc_url,
        },
        "schedule": {
            "preset": schedule_plan.get("preset", ""),
            "preset_name": schedule_plan.get("preset_name", ""),
            "period_key": schedule_plan.get("period_key", ""),
            "period_name": schedule_plan.get("period_name", ""),
            "publish_feishu": bool(schedule_plan.get("publish_feishu", False)),
            "export_site": bool(schedule_plan.get("export_site", False)),
        },
        "report": {
            "date": digest.get("today", ""),
            "title": digest.get("report_title", ""),
            "report_path": digest.get("report_path", ""),
            "item_count": int(digest.get("item_count", 0) or 0),
            "top_signal_count": int(digest.get("top_signal_count", 0) or 0),
            "mass_hot_topic_count": len(mass_hot_topics),
        },
        "mass_hot_topics": mass_hot_topics,
        "top_signals": top_signals,
        "x_kol_hotspots": x_kol_hotspots,
        "community_hotspots": community_hotspots,
        "recent_items": recent_items,
        "source_health": list(digest.get("source_health", []) or []),
        "history": history,
    }


def export_ai_signal_site(
    *,
    digest: dict[str, Any],
    schedule_plan: dict[str, Any],
    state: dict[str, Any],
    timeline_config: dict[str, Any],
) -> dict[str, Any]:
    site_config = dict(timeline_config.get("site", {}))
    output_dir = Path(
        compact_text(str(site_config.get("output_dir", ""))) or str(DEFAULT_SITE_DIR)
    ).expanduser()
    data_dir = output_dir / "data"
    ensure_dirs(output_dir, data_dir)

    runtime_bucket = get_ai_daily_signal_runtime_bucket(state)
    history_limit = int(site_config.get("history_limit", 48) or 48)
    site_history = list(runtime_bucket.get("site_history", []) or [])
    resolved_at = compact_text(str(schedule_plan.get("resolved_at", "")))
    try:
        current_time = datetime.fromisoformat(resolved_at)
    except ValueError:
        current_time = datetime.now(ZoneInfo(str(timeline_config.get("timezone", "Asia/Shanghai"))))

    def _is_recent_history(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        if not compact_text(str(item.get("headline", ""))):
            return False
        generated_at = compact_text(str(item.get("generated_at", "")))
        if not generated_at:
            return False
        try:
            item_time = datetime.fromisoformat(generated_at)
        except ValueError:
            return False
        return (current_time - item_time).total_seconds() <= 24 * 60 * 60

    site_history = [item for item in site_history if _is_recent_history(item)]
    hot_topics = list(digest.get("mass_hot_topics", []) or [])
    top_signals = list(digest.get("top_signals", []) or [])
    headline = compact_text(str((hot_topics[:1] or [{}])[0].get("name", "")))
    top_signal = compact_text(str((top_signals[:1] or [{}])[0].get("title", "")))
    entry = {
        "generated_at": resolved_at,
        "period_name": schedule_plan.get("period_name", ""),
        "headline": headline or top_signal or "尚未形成多源热点",
        "headline_kind": "cluster" if headline else "signal",
        "item_count": int(digest.get("item_count", 0) or 0),
        "top_signal_count": int(digest.get("top_signal_count", 0) or 0),
    }
    site_history = [entry, *site_history][: max(history_limit, 1)]
    runtime_bucket["site_history"] = site_history

    existing_daily_doc = get_project_daily_doc(state, "ai_daily_signal")
    published_doc = dict(digest.get("published_doc", {}) or {})
    doc_url = compact_text(str(published_doc.get("url", ""))) or compact_text(str(existing_daily_doc.get("url", "")))

    payload = _build_site_payload(
        digest=digest,
        schedule_plan=schedule_plan,
        site_config=site_config,
        doc_url=doc_url,
        history=site_history,
    )
    latest_json_path = data_dir / "latest.json"
    history_json_path = data_dir / "history.json"
    latest_md_path = data_dir / "latest.md"
    latest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    history_json_path.write_text(json.dumps(site_history, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = Path(str(digest.get("report_path", "")))
    if report_path.exists():
        shutil.copyfile(report_path, latest_md_path)
    else:
        latest_md_path.write_text(str(digest.get("report_markdown", "")), encoding="utf-8-sig")

    return {
        "site_dir": str(output_dir),
        "site_index": str(output_dir / "index.html"),
        "latest_json": str(latest_json_path),
        "history_json": str(history_json_path),
        "latest_md": str(latest_md_path),
    }


def run_ai_signal_schedule(
    *,
    config_path: str = "",
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    timeline_config = load_ai_signal_timeline_config(Path(config_path) if compact_text(config_path) else None)
    plan = resolve_ai_signal_schedule_slot(config=timeline_config, now=now)
    state = load_opc_state()
    runtime_bucket = get_ai_daily_signal_runtime_bucket(state)
    runs_by_day = runtime_bucket.setdefault("timeline_runs", {})
    local_now = datetime.fromisoformat(str(plan.get("resolved_at")))
    day_key = local_now.date().isoformat()
    period_key = compact_text(str(plan.get("period_key", ""))) or "default"
    plan_key = f"{plan.get('preset', 'live_pulse')}:{period_key}"
    action_state = dict((runs_by_day.setdefault(day_key, {})).get(plan_key, {}))

    enabled = bool(plan.get("enabled", False))
    if not enabled and not force:
        return {
            "status": "skipped",
            "reason": "outside_active_window",
            "schedule": plan,
        }

    once_config = dict(plan.get("once", {}))
    run_digest = True
    publish_feishu = bool(plan.get("publish_feishu", False))
    export_site = bool(plan.get("export_site", False))

    if once_config.get("run_digest") and action_state.get("run_digest") and not force:
        run_digest = False
        publish_feishu = False
        export_site = False
    if once_config.get("publish_feishu") and action_state.get("publish_feishu") and not force:
        publish_feishu = False
    if once_config.get("export_site") and action_state.get("export_site") and not force:
        export_site = False

    if not run_digest and not publish_feishu and not export_site:
        return {
            "status": "skipped",
            "reason": "once_guard",
            "schedule": plan,
        }

    digest = generate_ai_news_digest(
        limit_per_source=max(int(plan.get("limit_per_source", 2) or 2), 1),
        max_items=max(int(plan.get("max_items", 18) or 18), 1),
        since_days=max(int(plan.get("since_days", 1) or 1), 1),
        publish_feishu=publish_feishu,
    )
    site_outputs: dict[str, Any] = {}
    if export_site:
        site_outputs = export_ai_signal_site(
            digest=digest,
            schedule_plan=plan,
            state=state,
            timeline_config=timeline_config,
        )

    run_log = runs_by_day.setdefault(day_key, {})
    action_log = dict(run_log.get(plan_key, {}))
    executed_at = plan.get("resolved_at", datetime.now().isoformat())
    action_log["last_run_at"] = executed_at
    action_log["run_digest"] = executed_at
    if publish_feishu:
        action_log["publish_feishu"] = executed_at
    if export_site:
        action_log["export_site"] = executed_at
    run_log[plan_key] = action_log
    save_opc_state(state)

    degraded_sources = [
        entry
        for entry in list(digest.get("source_health", []) or [])
        if compact_text(str(entry.get("status", ""))).lower() != "ok"
    ]
    return {
        "status": "executed",
        "schedule": plan,
        "digest": digest,
        "site": site_outputs,
        "degraded_sources": degraded_sources,
    }
