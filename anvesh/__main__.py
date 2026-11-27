"""Command-line entry point: python -m anvesh <command>."""

import argparse
import sys

from anvesh import __version__

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    print(f"{args.command}: not implemented yet (config={args.config}, state-dir={args.state_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
