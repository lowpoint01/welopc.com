from __future__ import annotations

import argparse

from aihot_common import (
    build_url,
    fetch_json,
    filter_items_by_query,
    normalize_items,
    render_items_markdown,
    resolve_base_url,
    write_json,
    write_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search WelOPC AIHOT public feed items.")
    parser.add_argument("query", help="Keyword, product, company, model, or agent framework to search.")
    parser.add_argument("--base-url", default=None, help="Public AIHOT API base URL.")
    parser.add_argument("--channel", default="all", help="AIHOT channel, e.g. all, github, opcSolo.")
    parser.add_argument("--mode", default="all", help="Feed mode, e.g. all or selected.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of items.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    url = build_url(
        resolve_base_url(args.base_url),
        "/feed",
        {"mode": args.mode, "channel": args.channel, "limit": args.limit, "q": args.query},
    )
    payload = fetch_json(url)
    items = filter_items_by_query(normalize_items(payload), args.query)[: args.limit]

    if args.format == "markdown":
        write_markdown(render_items_markdown(items, f"WelOPC AIHOT Search: {args.query}"))
    else:
        write_json({"source": url, "query": args.query, "items": items})


if __name__ == "__main__":
    main()
