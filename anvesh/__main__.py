"""Command-line entry point: python -m anvesh <command>."""

import argparse
import sys

import httpx

from anvesh import __version__
from anvesh.check import run_check
from anvesh.config import ConfigError, load_filters, load_settings, load_sources
from anvesh.http import Http
from anvesh.dedupe import SeenStories
from anvesh.digest import build_messages, deliver, visible_length
from anvesh.pipeline import run_pass, summary_line
from anvesh.state import State, to_iso, utc_now
from anvesh.telegram import Telegram, TelegramError

COMMANDS = {
    "run": "fetch sources, filter, score, send alerts and save state",
    "dry-run": "do everything except send to Telegram and write state",
    "check-sources": "call every URL in sources.yaml and print its status",
    "report": "show which score parts predicted the leads you acted on",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anvesh",
        description="Radar for newly funded tech startups and the roles they are hiring for.",
    )
    parser.add_argument("--version", action="version", version=f"anvesh {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    commands = {}
    for name, help_text in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=help_text)
        cmd.add_argument(
            "--config",
            default=".",
            help="folder with settings.yaml, sources.yaml and other config files (default: .)",
        )
        cmd.add_argument(
            "--state-dir",
            default="state",
            help="folder holding the JSONL state files (default: state)",
        )
        commands[name] = cmd
    commands["check-sources"].add_argument(
        "--all", action="store_true", help="also check sources with enabled: false"
    )
    return parser


def cmd_run(config_dir: str, state_dir: str, dry_run: bool) -> int:
    try:
        settings = load_settings(config_dir)
        sources = load_sources(config_dir)
        filters = load_filters(config_dir)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    state = State(state_dir, read_only=dry_run)
    runs = state.table("runs")
    now = utc_now()
    http = Http(cache=state.table("http_cache"), settings=settings.http)

    seen = SeenStories(state.table("seen_stories"), filters.dedupe)
    result = run_pass(sources, filters, http, now, seen, settings.google_news.language)
    runs.upsert(
        to_iso(now),
        {
            "version": __version__,
            "dry_run": dry_run,
            "fetched": len(result.collected.signals),
            "kept": len(result.filtered.kept),
            "dropped": dict(result.filtered.dropped),
            "stories": len(result.stories),
            "new": len(result.new),
            "failed": result.collected.failed,
        },
        now=now,
    )
    for _, error in sorted(result.collected.failed.items()):
        print(f"FAIL {error}", file=sys.stderr)
    print(summary_line(result))

    counts = {
        "new": len(result.new),
        "stories": len(result.stories),
        "fetched": len(result.collected.signals),
        "sources": len({s.source for s in result.collected.signals}),
    }
    messages, held_back = build_messages(result.new, counts, settings.digest)
    if dry_run:
        for number, message in enumerate(messages, 1):
            print(f"\n[dry-run] message {number}/{len(messages)} ({visible_length(message.text)} chars, "
                  f"{len(message.stories)} stories) would be sent:\n{message.text}")
        if not messages:
            print("[dry-run] nothing new, nothing would be sent")
        return 0

    try:
        telegram = Telegram.from_env() if messages else None
    except TelegramError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1  # state not saved: nothing was delivered, so this run never happened
    delivered, error = deliver(
        messages,
        send=lambda text: telegram.send(text, parse_mode="HTML", split=False),
        remember=lambda story: seen.remember(story, now=now),
    )
    runs.upsert(to_iso(now), {"delivered": delivered, "held_back": held_back}, now=now)
    state.save(settings.state.retention_days)
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        print(f"delivered {delivered} of {len(result.new)} stories; the rest come again next run", file=sys.stderr)
        return 1
    if messages:
        print(f"sent {len(messages)} message(s), {delivered} stories")
    else:
        print("nothing new, nothing sent")
    return 0


def cmd_check_sources(config_dir: str, include_disabled: bool) -> int:
    try:
        settings = load_settings(config_dir)
        config = load_sources(config_dir)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    http = Http(settings=settings.http)
    results = run_check(
        config, http, include_disabled=include_disabled, language=settings.google_news.language
    )
    return 1 if any(r.verdict == "FAIL" for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    if args.command in ("run", "dry-run"):
        return cmd_run(args.config, args.state_dir, dry_run=args.command == "dry-run")
    if args.command == "check-sources":
        return cmd_check_sources(args.config, args.all)
    print(f"{args.command}: not implemented yet (config={args.config}, state-dir={args.state_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
