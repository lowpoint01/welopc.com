from __future__ import annotations

import argparse

from aihot_common import build_url, fetch_json, normalize_items, resolve_base_url, write_json, write_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the latest WelOPC AIHOT daily report.")
    parser.add_argument("--base-url", default=None, help="Public AIHOT API base URL.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    url = build_url(resolve_base_url(args.base_url), "/daily/latest")
    payload = fetch_json(url)

    if args.format == "markdown":
        if isinstance(payload, dict) and payload.get("markdown"):
            write_markdown(str(payload["markdown"]))
        elif isinstance(payload, dict):
            title = payload.get("title") or "WelOPC AIHOT Daily"
            summary = payload.get("summary") or "No daily summary is available."
            write_markdown(f"# {title}\n\n{summary}\n")
        else:
            write_markdown("# WelOPC AIHOT Daily\n\nNo daily summary is available.\n")
    else:
        data = payload if isinstance(payload, dict) else {"payload": payload}
        if isinstance(data, dict):
            data = {**data, "source": url, "items": normalize_items(payload)}
        write_json(data)


if __name__ == "__main__":
    main()
