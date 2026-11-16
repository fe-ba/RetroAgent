"""The `retro` command."""

import argparse
import sys
from pathlib import Path

from retroagent import __version__
from retroagent.examples import ExampleError, GitFailed, list_examples, materialize

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retro", description="RetroAgent: an AI agent for regression testing.")
    parser.add_argument("--version", action="version", version=f"retro {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    example = commands.add_parser(
        "example",
        help="list bundled example projects, or create one",
        usage="retro example list\n       retro example <name> <dir>",
    )
    example.add_argument("name", metavar="list | <name>", help="`list`, or the name of the example to create")
    example.add_argument(
        "directory", nargs="?", metavar="<dir>", help="directory to create; must not exist or be empty"
    )
    return parser


def _run_example(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.name == "list":
        if args.directory is not None:
            parser.error("`retro example list` takes no directory")
        for example in list_examples():
            print(f"{example.name}: {example.description} Versions: {', '.join(example.tags)}.")
        return EXIT_OK
    if args.directory is None:
        parser.error("usage: retro example <name> <dir>")
    target = Path(args.directory).resolve()
    tags = materialize(args.name, target)
    print(f"Created {args.name} in {target} with versions {', '.join(tags)}.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)  # exits with code 2 on invalid usage
    try:
        return _run_example(args, parser)
    except ExampleError as error:
        print(f"retro: {error}", file=sys.stderr)
        return EXIT_USAGE
    except GitFailed as error:
        print(f"retro: {error}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
