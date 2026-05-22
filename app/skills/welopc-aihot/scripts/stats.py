from __future__ import annotations

import argparse

from aihot_common import build_url, fetch_json, resolve_base_url, write_json, write_markdown


def render_stats_markdown(payload: object) -> str:
    if not isinstance(payload, dict):
        return "# WelOPC AIHOT Stats\n\nNo stats payload is available.\n"
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    channels = payload.get("channels") if isinstance(payload.get("channels"), list) else []
    lines = ["# WelOPC AIHOT Stats", ""]
    if counts:
        lines.append("## Coverage")
        for key in ("items", "selected", "sources", "channelItems", "dailyIssues", "pipelineRuns"):
            if key in counts:
                lines.append(f"- {key}: {counts[key]}")
        lines.append("")
    if channels:
        lines.append("## Channels")
        for channel in channels:
            if isinstance(channel, dict):
                lines.append(f"- {channel.get('channel')}: {channel.get('count')} items, {channel.get('selected')} selected")
        lines.append("")
    latest_run = payload.get("latestRun")
    if isinstance(latest_run, dict):
        lines.extend(
            [
                "## Latest Run",
                f"- status: {latest_run.get('status')}",
                f"- started_at: {latest_run.get('started_at')}",
                f"- finished_at: {latest_run.get('finished_at')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch WelOPC AIHOT public stats.")
    parser.add_argument("--base-url", default=None, help="Public AIHOT API base URL.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    url = build_url(resolve_base_url(args.base_url), "/stats")
    payload = fetch_json(url)

    if args.format == "markdown":
        write_markdown(render_stats_markdown(payload))
    else:
        data = payload if isinstance(payload, dict) else {"payload": payload}
        if isinstance(data, dict):
            data = {**data, "source": url}
        write_json(data)


if __name__ == "__main__":
    main()
