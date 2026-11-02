"""Command line: anchorless fetch | render | preview | serve."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, config_path, load_config


def _age(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "  ?  "
    minutes = int((now - when).total_seconds() // 60)
    return f"{minutes:3d}m" if minutes < 120 else f"{minutes // 60:3d}h"


async def _fetch(cfg: Config, as_json: bool) -> int:
    from .newsroom import Newsroom

    room = Newsroom(cfg)
    rundown = await room.refresh()
    now = rundown.built_at
    if as_json:
        print(json.dumps({
            "built_at": now.isoformat(),
            "segments": [{
                "name": seg.name,
                "stories": [{
                    "title": c.lead.title, "summary": c.lead.summary, "outlets": c.outlets,
                    "url": c.lead.url, "when": c.when.isoformat() if c.when else None,
                    "score": round(c.score, 3),
                } for c in seg.clusters],
            } for seg in rundown.segments],
            "feeds": room.feed_status(),
        }, indent=2))
        return 0
    for seg in rundown.segments:
        print(f"\n== {seg.name}")
        for c in seg.clusters:
            print(f"  {_age(c.when, now)}  [{len(c.outlets)}] {c.lead.title}")
            print(f"         {', '.join(c.outlets)}")
    failed = [f for f in room.feed_status() if f["error"]]
    print(f"\n{sum(f['stories'] for f in room.feed_status())} stories from {len(cfg.source)} feeds", end="")
    print(f", {len(failed)} failed:" if failed else "")
    for f in failed:
        print(f"  {f['name']} {f['url']}: {f['error']}")
    return 0


async def _headlines(cfg: Config, dump: str | None) -> int:
    """Every story several outlets carry: each version, its score and why."""
    from datetime import UTC, datetime

    from . import headline
    from .pipeline import all_clusters
    from .sources.rss import RssFetcher

    now = datetime.now(UTC)
    stories = await RssFetcher().fetch_all(cfg.source, cfg.feeds.allow_private)
    clusters = all_clusters(stories, cfg, now)
    rows = []
    for c in clusters:
        choice = headline.choose(c, cfg.rundown.headline_margin)
        if choice is None:
            continue
        local = any(s.scope == "local" for s in c.stories)
        print(f"\n[{len(c.outlets)} outlets] {'CHANGED' if choice.changed else 'kept'}"
              + (f" - {choice.reason}" if choice.changed else ""))
        for x in sorted(choice.scores, key=lambda x: -x.total):
            mark = ">" if x.story is choice.chosen else ("d" if x.story is choice.default else " ")
            print(f"  {mark} {x.total:5.2f}  {x.story.outlet[:18]:18}  {x.story.title[:90]}")
            print(f"           {x.why()}")
        if dump and not local:      # local stories would say where you live
            rows.append({"when": now.isoformat(timespec="seconds"), "key": c.key, "changed": choice.changed,
                         "chosen": choice.chosen.key, "default": choice.default.key, "versions": [
                             {"key": x.story.key, "outlet": x.story.outlet, "title": x.story.title,
                              "summary": x.story.summary, "scope": x.story.scope, "total": round(x.total, 3),
                              "corroboration": round(x.corroboration, 3), "coverage": round(x.coverage, 3),
                              "penalties": x.penalties} for x in choice.scores]})
    if dump:
        with open(dump, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        print(f"\n{len(rows)} stories appended to {dump}", file=sys.stderr)
    return 0


def _hash_password(from_stdin: bool) -> int:
    import getpass

    from .passwords import MIN_LENGTH, hash_password
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass(f"Settings password (at least {MIN_LENGTH} characters): ")
        if getpass.getpass("Again: ") != password:
            print("The two passwords differ.", file=sys.stderr)
            return 2
    try:
        hashed = hash_password(password)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    print("Put this in config.toml (and remove any [admin] password / ANCHORLESS__ADMIN__PASSWORD):\n",
          file=sys.stderr)
    print(f'[admin]\npassword_hash = "{hashed}"')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anchorless", description="A 24/7 text newscast for IPTV.")
    parser.add_argument("--version", action="version", version=f"anchorless {__version__}")
    parser.add_argument("-c", "--config", help="config file (default: $ANCHORLESS_CONFIG or ./config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="fetch the sources once and print the rundown")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("render", help="write PNG stills of each page type")
    p.add_argument("-o", "--out", default="out", help="output directory (default: out)")
    p.add_argument("-t", "--theme", choices=["studio", "classic", "classic-light", "classic-dark"], help="default: the configured theme")

    p = sub.add_parser("preview", help="write a short MP4 of the channel")
    p.add_argument("-o", "--out", default="out/preview.mp4")
    p.add_argument("-s", "--seconds", type=float, default=60)
    p.add_argument("--breaking", action="store_true", help="start with a (sample) breaking-news alert")
    p.add_argument("-t", "--theme", choices=["studio", "classic", "classic-light", "classic-dark"], help="default: the configured theme")

    sub.add_parser("serve", help="run the channel: /playlist.m3u, /guide.xml, /live.ts, /health")
    sub.add_parser("check-config", help="validate the config and print it")
    p = sub.add_parser("headlines", help="each version of every multi-outlet story, scored (consensus headline)")
    p.add_argument("--dump", help="append the stories (not local ones) to this JSONL file, for calibration")
    p = sub.add_parser("hash-password", help="make a password_hash for [admin] (the settings page)")
    p.add_argument("--stdin", action="store_true", help="read the password from standard input")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", stream=sys.stderr,
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "hash-password":           # needs no config: you run it while writing one
        return _hash_password(args.stdin)
    try:
        cfg = load_config(args.config)
        cfg_path = Path(args.config) if args.config else config_path()
    except ConfigError as err:
        print(err, file=sys.stderr)
        return 2

    if args.command == "check-config":
        shown = cfg.model_copy(deep=True)
        if shown.admin.password:
            shown.admin.password = "<set>"           # never print the settings password
        if shown.admin.password_hash:
            shown.admin.password_hash = "<set>"
        print(shown.model_dump_json(indent=2))
        return 0
    if args.command == "headlines":
        return asyncio.run(_headlines(cfg, args.dump))
    if args.command == "fetch":
        return asyncio.run(_fetch(cfg, args.json))
    if args.command == "render":
        from .render.stills import write_stills

        return asyncio.run(write_stills(cfg, Path(args.out), args.theme))
    if args.command == "preview":
        from .stream.preview import write_preview

        if args.theme:
            cfg.channel.theme = args.theme
        return asyncio.run(write_preview(cfg, Path(args.out), args.seconds, args.breaking))
    if args.command == "serve":
        from .stream.server import serve

        return serve(cfg, cfg_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
