"""The ``retro`` command (docs/reference/cli.md).

``retro [-C <path>] <command> [arguments]`` when the first word after ``-C`` names a command; otherwise
``retro [options] [prompt]``, which starts a session on the target project: interactive, or one prompt with ``-p``.
"""

import argparse
import io
import json
import sys
from pathlib import Path

from rich.console import Console

from retroagent import __version__
from retroagent.cli import interactive
from retroagent.examples import ExampleError, GitFailed, list_examples, materialize
from retroagent.runtime import commands, init, session
from retroagent.runtime.commands import CommandError, NotAvailable

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE = 2

COMMANDS = ("init", "example", "config", "defects")
# Width of tables written to a file or a pipe, where there is no terminal to measure: wide enough for a run row.
OUTPUT_WIDTH = 200

EPILOG = """commands:
  init                                  initialize the target project: detect its type and create RETRO.md,
                                        .retro/config.yaml and .retro/.gitignore; never overwrites a file
  example list                          list bundled example projects
  example <name> <dir>                  create example <name> in <dir> with its git history and version tags
  config list                           show the effective configuration (not available yet in this build)
  config get <key>                      show the effective value of <key> (not available yet in this build)
  config set <key> <value>              set <key> at user level, or with --project in the target project
                                        (not available yet in this build)
  defects close <id> --reason <text>    close a defect without starting a session (not available yet in this build)

Inside a session, /help lists the slash commands."""


def _session_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro",
        usage="retro [options] [prompt]\n       retro [-C <path>] <command> [arguments]",
        description="RetroAgent: an AI agent for regression testing. Without a command, starts a session on the"
        " target project; prompt is its first message.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-C", dest="project", metavar="<path>", help="target project; default: current directory")
    parser.add_argument("-p", "--print", action="store_true", help="non-interactive: run the prompt, print the result"
                        " and exit")  # fmt: skip
    parser.add_argument("-m", "--model", metavar="<name>", help="model profile for this session")
    parser.add_argument(
        "--mode", choices=("default", "plan", "auto"), default="default", metavar="<mode>",
        help="permission mode: default, plan or auto; default: default",
    )  # fmt: skip
    parser.add_argument(
        "--trust-commands",
        action="store_true",
        help="approve the test commands of the project for this session without asking",
    )
    parser.add_argument("--base", metavar="<ref>", help="baseline version: tag, branch or commit")
    parser.add_argument("--candidate", metavar="<ref>", help="candidate version: tag, branch or commit")
    parser.add_argument("--lang", metavar="<code>", help="language of responses and reports, e.g. en or es")
    parser.add_argument(
        "--output-format", choices=("text", "json"), default="text", metavar="<format>",
        help="output of non-interactive mode: text or json; default: text",
    )  # fmt: skip
    parser.add_argument("-v", "--verbose", action="store_true", help="show tool calls and model calls in detail")
    parser.add_argument("--version", action="version", version=f"retro {__version__}")
    parser.add_argument("prompt", nargs="?", help="first message of the session; with -p, the only one")
    return parser


# Commands -----------------------------------------------------------------------------------------------------------


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


def _run_init(argv: list[str], project: str | None) -> int:
    parser = argparse.ArgumentParser(
        prog="retro init",
        usage="retro [-C <path>] init",
        description="Initialize the target project: detect its type and create RETRO.md, .retro/config.yaml and"
        " .retro/.gitignore. Existing files are never overwritten.",
    )
    parser.add_argument("-C", dest="project", metavar="<path>", help="target project; default: current directory")
    args = parser.parse_args(argv)
    try:
        project_dir = session.project_top_level(Path(args.project or project or Path.cwd()))
    except session.SessionError as error:
        print(f"retro: {error}", file=sys.stderr)
        return EXIT_USAGE
    proposal = init.propose(project_dir)
    for line in init.describe(proposal):
        print(line)
    missing = [name for name in init.FILES if not (project_dir / name).exists()]
    if not missing:
        print(f"Nothing to create: {', '.join(init.FILES)} exist and are kept.")
        return EXIT_OK
    if sys.stdin.isatty() and not _confirm(f"Create {', '.join(missing)}?"):
        print("Nothing was created.")
        return EXIT_OK
    created, kept = init.write(project_dir, proposal)
    print(f"Created: {', '.join(created)}." + (f" Kept: {', '.join(kept)}." if kept else ""))
    return EXIT_OK


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _not_available(name: str) -> int:
    print(
        f"retro: `retro {name}` is not available yet in this build (FR-39); edit ~/.retro/config.yaml or"
        " .retro/config.yaml directly",
        file=sys.stderr,
    )
    return EXIT_USAGE


# The session --------------------------------------------------------------------------------------------------------


def _run_session(argv: list[str]) -> int:
    parser = _session_parser()
    args = parser.parse_args(argv)  # exits with code 2 on invalid usage
    err = Console(stderr=True, soft_wrap=True)  # messages are never wrapped
    command = None
    if args.print:
        if args.prompt is None:
            parser.error("-p needs a prompt")
        if commands.is_command(args.prompt):
            try:
                command = commands.parse(args.prompt)
            except NotAvailable as error:
                parser.error(str(error))
            except CommandError as error:
                parser.error(str(error))
    elif args.output_format != "text":
        parser.error("--output-format applies to non-interactive mode (-p)")
    terminal = None if args.print else _Terminal()
    options = session.Options(
        project=args.project,
        interactive=not args.print,
        trust_commands=args.trust_commands,
        base=args.base,
        candidate=args.candidate,
        model=args.model,
        mode=args.mode,
        language=args.lang,
    )
    choose = None if terminal is None else (lambda names: interactive.choose_profile(names, terminal.read, err))
    try:
        started = session.start(options, choose_profile=choose)
    except session.SessionError as error:
        err.print(f"retro: {error}", markup=False, highlight=False)
        return EXIT_USAGE
    except session.StartFailed as error:
        err.print(f"retro: {error}", markup=False, highlight=False)
        return EXIT_RUNTIME_ERROR
    with started:
        err.print(started.statement, markup=False, highlight=False)
        for warning in started.warnings:
            err.print(f"warning: {warning}", markup=False, highlight=False)
        for run_id in started.recovered_runs:
            err.print(f"{run_id} was left running by an earlier session and is now interrupted", markup=False)
        if args.print:
            return _print_mode(started, args, command, err)
        _interactive(started, args, terminal, err)
    return EXIT_OK


def _print_mode(started: session.Session, args, command, err: Console) -> int:
    """``-p``: one prompt, its output on stdout, then the exit code of runtime.md (Non-interactive mode)."""
    as_json = args.output_format == "json"
    if as_json:
        out = Console(file=io.StringIO(), record=True, width=OUTPUT_WIDTH, color_system=None)
    else:
        out = Console() if sys.stdout.isatty() else Console(width=OUTPUT_WIDTH)
    shell = interactive.Shell(
        started, out, err, log=err, verbose=args.verbose, render_markdown=False, show_recorded=not as_json
    )
    outcome = shell.execute(command) if command is not None else shell.handle(args.prompt)
    summary = commands.session_outcome(started)
    code = EXIT_USAGE if outcome.usage_error else commands.exit_code(outcome.runtime_error, summary)
    if as_json:
        result = outcome.answer if outcome.answer is not None else out.export_text().rstrip("\n") or None
        print(
            json.dumps(
                {
                    "result": result,
                    "session_id": started.id,
                    "runs": summary.runs,
                    "reports": summary.reports,
                    "decision": summary.decision,
                    "denied": summary.denied,
                    "recorded": dict(outcome.recorded) if outcome.recorded is not None else None,
                    "exit_code": code,
                },
                ensure_ascii=False,
            )
        )
    return code


def _interactive(started: session.Session, args, terminal: "_Terminal", err: Console) -> None:
    out = Console()
    keys = interactive.Keys(terminal.input)
    shell = interactive.Shell(started, out, err, verbose=args.verbose, keys=keys, confirm=terminal.confirm)
    if args.prompt is not None and shell.handle(args.prompt).end:
        return
    prompt = interactive.prompt_session(started, input=terminal.input)
    interactive.loop(shell, prompt.prompt)


class _Terminal:
    """The input of an interactive session, created once: the profile chooser, the prompt and the key watcher."""

    def __init__(self):
        self._input = None

    @property
    def input(self):
        if self._input is None:  # only when the terminal is used: a session may end before
            from prompt_toolkit.input import create_input

            self._input = create_input()
        return self._input

    def read(self, message: str) -> str:
        from prompt_toolkit import prompt

        return prompt(message, input=self.input)

    def confirm(self, question: str) -> bool:
        try:
            return self.read(f"{question} [y/N] ").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    project = None
    if len(argv) >= 3 and argv[0] == "-C" and argv[2] in COMMANDS:
        project, argv = argv[1], argv[2:]
    try:
        if argv and argv[0] in COMMANDS:
            name, rest = argv[0], argv[1:]
            if name == "init":
                return _run_init(rest, project)
            if project is not None:
                print(f"retro: -C does not apply to `retro {name}`", file=sys.stderr)
                return EXIT_USAGE
            if name == "example":
                return _run_example(rest)
            return _not_available(name)
        return _run_session(argv)
    except KeyboardInterrupt:
        return EXIT_RUNTIME_ERROR
    except Exception as error:  # an unexpected failure is a runtime error, never a traceback without a code
        print(f"retro: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
