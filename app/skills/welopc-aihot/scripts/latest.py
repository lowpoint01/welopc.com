from __future__ import annotations

import argparse

from aihot_common import build_url, fetch_json, normalize_items, render_items_markdown, resolve_base_url, write_json, write_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch latest high-signal WelOPC AIHOT items.")
    parser.add_argument("--base-url", default=None, help="Public AIHOT API base URL.")
    parser.add_argument("--channel", default="all", help="AIHOT channel, e.g. all, github, opcSolo.")
    parser.add_argument("--mode", default="selected", help="Feed mode, e.g. selected or all.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of items.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    url = build_url(
        resolve_base_url(args.base_url),
        "/feed",
        {"mode": args.mode, "channel": args.channel, "limit": args.limit},
    )
    payload = fetch_json(url)
    items = normalize_items(payload)[: args.limit]

    if args.format == "markdown":
        write_markdown(render_items_markdown(items, "WelOPC AIHOT Latest Signals"))
    else:
        write_json({"source": url, "items": items})


if __name__ == "__main__":
    main()
