"""The `retro` command.

``retro <command> [arguments]`` when the first argument names a command; otherwise ``retro [options] [prompt]``,
which starts a session on the target project.
"""

import argparse
import sys
from pathlib import Path

from rich.console import Console

from retroagent import __version__
from retroagent.cli import interactive
from retroagent.examples import ExampleError, GitFailed, list_examples, materialize
from retroagent.runtime import commands, session
from retroagent.runtime.commands import CommandError

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE = 2

COMMANDS = ("example",)
# Direct commands that non-interactive mode runs in this build.
PRINT_COMMANDS = ("/run", "/status", "/history")
# Width of tables written to a file or a pipe, where there is no terminal to measure: wide enough for a run row.
OUTPUT_WIDTH = 200


def _session_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro",
        usage="retro [options] [prompt]\n       retro <command> [arguments]",
        description="RetroAgent: an AI agent for regression testing. Without a command, starts a session on the"
        " target project.",
        epilog="commands:\n  example     list bundled example projects, or create one (retro example --help)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"retro {__version__}")
    parser.add_argument("-C", dest="project", metavar="<path>", help="target project; default: current directory")
    parser.add_argument("-p", "--print", action="store_true", help="non-interactive: run the prompt and exit")
    parser.add_argument(
        "--trust-commands",
        action="store_true",
        help="approve the test commands of the project for this session without asking",
    )
    parser.add_argument("--base", metavar="<ref>", help="baseline version: tag, branch or commit")
    parser.add_argument("--candidate", metavar="<ref>", help="candidate version: tag, branch or commit")
    parser.add_argument("prompt", nargs="?", help="first message of the session; with -p, the only one")
    return parser


def _example_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro example",
        usage="retro example list\n       retro example <name> <dir>",
        description="List bundled example projects, or create one.",
    )
    parser.add_argument("name", metavar="list | <name>", help="`list`, or the name of the example to create")
    parser.add_argument("directory", nargs="?", metavar="<dir>", help="directory to create; must not exist or be empty")
    return parser


def _run_example(argv: list[str]) -> int:
    parser = _example_parser()
    args = parser.parse_args(argv)  # exits with code 2 on invalid usage
    try:
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
    except ExampleError as error:
        print(f"retro: {error}", file=sys.stderr)
        return EXIT_USAGE
    except GitFailed as error:
        print(f"retro: {error}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


def _run_session(argv: list[str]) -> int:
    parser = _session_parser()
    args = parser.parse_args(argv)  # exits with code 2 on invalid usage
    err = Console(stderr=True, soft_wrap=True)  # messages are never wrapped
    command = None
    if args.print:
        if args.prompt is None:
            parser.error("-p needs a prompt")
        try:
            command = commands.parse(args.prompt)
        except CommandError as error:
            parser.error(str(error))
        if command.name not in PRINT_COMMANDS:
            parser.error(f"not available yet in non-interactive mode: {args.prompt}")
    options = session.Options(
        project=args.project,
        interactive=not args.print,
        trust_commands=args.trust_commands,
        base=args.base,
        candidate=args.candidate,
    )
    try:
        started = session.start(options)
    except session.SessionError as error:
        err.print(f"retro: {error}", markup=False, highlight=False)
        return EXIT_USAGE
    out = Console() if sys.stdout.isatty() else Console(width=OUTPUT_WIDTH)
    with started:
        for run_id in started.recovered_runs:
            err.print(f"{run_id} was left running by an earlier session and is now interrupted", markup=False)
        if command is not None:
            try:
                return interactive.execute(started, command, out, err)
            except KeyboardInterrupt:
                return EXIT_RUNTIME_ERROR
        if args.prompt is not None and not interactive.handle(started, args.prompt, out, err):
            return EXIT_OK
        interactive.loop(started, interactive.prompt_reader(), out, err)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in COMMANDS:
        return _run_example(argv[1:])
    try:
        return _run_session(argv)
    except Exception as error:  # an unexpected failure is a runtime error, never a traceback without a code
        print(f"retro: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
