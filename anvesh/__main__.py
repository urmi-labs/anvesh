"""Command-line entry point: python -m anvesh <command>."""

import argparse
import sys

import httpx

from anvesh import __version__
from anvesh.check import run_check
from anvesh.config import ConfigError, load_sources
from anvesh.http import Http
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
        description="Radar for newly funded tech startups and their DevOps/SRE roles.",
    )
    parser.add_argument("--version", action="version", version=f"anvesh {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    commands = {}
    for name, help_text in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=help_text)
        cmd.add_argument(
            "--config",
            default=".",
            help="folder with profile.yaml, sources.yaml and scoring.yaml (default: .)",
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


def cmd_run(state_dir: str, dry_run: bool) -> int:
    state = State(state_dir, read_only=dry_run)
    runs = state.table("runs")
    previous = max(runs.records, default=None)
    now = utc_now()
    runs.upsert(to_iso(now), {"version": __version__, "dry_run": dry_run}, now=now)

    message = (
        f"anvesh {__version__} alive\n"
        f"runs recorded: {len(runs)}\n"
        f"previous run: {previous or 'none (first run)'}"
    )
    if dry_run:
        print(f"[dry-run] would send to Telegram:\n{message}")
        return 0
    try:
        Telegram.from_env().send(message)
    except (TelegramError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        state.save()
    print("sent alive message to Telegram")
    return 0


def cmd_check_sources(config_dir: str, include_disabled: bool) -> int:
    try:
        config = load_sources(config_dir)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    results = run_check(config, Http(), include_disabled=include_disabled)
    return 1 if any(r.verdict == "FAIL" for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    if args.command in ("run", "dry-run"):
        return cmd_run(args.state_dir, dry_run=args.command == "dry-run")
    if args.command == "check-sources":
        return cmd_check_sources(args.config, args.all)
    print(f"{args.command}: not implemented yet (config={args.config}, state-dir={args.state_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
