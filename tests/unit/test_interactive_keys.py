"""The keys of an interactive session, as far as they can be tested without a terminal (cli.md, Keyboard shortcuts).

prompt_toolkit's pipe input stands for the terminal. Not tested here: entering and leaving raw mode on a real
terminal, Esc told apart from an escape sequence by the timing of a real terminal, and how the prompt looks.
"""

import io
import threading
from types import SimpleNamespace

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from retroagent.cli import interactive
from retroagent.cli.interactive import Keys, Outcome
from retroagent.runtime import permissions
from retroagent.runtime.permissions import PermissionRequest

SHIFT_TAB, ESC, CTRL_C, CTRL_D = "\x1b[Z", "\x1b", "\x03", "\x04"
REQUEST = PermissionRequest("test_runner__run_tests", ("run_tests",), ("Version: base v1.0 (c7d45ad)",))


def console() -> Console:
    return Console(file=io.StringIO(), record=True, width=200, color_system=None)


@pytest.fixture
def terminal():
    with create_pipe_input() as pipe:
        yield pipe


def prompt(state, terminal):
    return interactive.prompt_session(state, input=terminal, output=DummyOutput())


def test_shift_tab_cycles_the_modes_in_the_order_of_cli_md(terminal):
    state = SimpleNamespace(mode="default")
    session = prompt(state, terminal)
    seen = []
    for _ in range(3):
        terminal.send_text(SHIFT_TAB + "x\r")
        session.prompt()
        seen.append(state.mode)
    assert seen == ["plan", "auto", "default"]


def test_ctrl_d_and_ctrl_c_at_the_prompt(terminal):
    session = prompt(SimpleNamespace(mode="default"), terminal)
    terminal.send_text(CTRL_D)
    with pytest.raises(EOFError):
        session.prompt()
    terminal.send_text(CTRL_C)
    with pytest.raises(KeyboardInterrupt):
        session.prompt()


class FakeShell:
    def __init__(self):
        self.err, self.lines = console(), []

    def handle(self, line):
        self.lines.append(line)
        return Outcome(end=line == "/exit")


def reader(*items):
    items = list(items)

    def read():
        item = items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return read


def test_ctrl_c_twice_in_a_row_exits_and_a_line_in_between_resets_it():
    shell = FakeShell()
    interactive.loop(shell, reader(KeyboardInterrupt(), "hello", KeyboardInterrupt(), KeyboardInterrupt(), "never"))
    assert shell.lines == ["hello"]
    assert shell.err.export_text().count("Press Ctrl+C again to exit.") == 2


def test_ctrl_d_and_exit_end_the_loop():
    shell = FakeShell()
    interactive.loop(shell, reader("a", EOFError(), "never"))
    assert shell.lines == ["a"]
    shell = FakeShell()
    interactive.loop(shell, reader("/exit", "never"))
    assert shell.lines == ["/exit"]


@pytest.mark.parametrize("key", [ESC, CTRL_C])
def test_esc_and_ctrl_c_interrupt_the_work_in_progress(terminal, key):
    out = console()

    def work(ask, interrupt):
        terminal.send_text(key)
        return interrupt.wait(5)

    assert Keys(terminal).watch(work, threading.Event(), out) is True
    assert "Interrupting..." in out.export_text()


@pytest.mark.parametrize(
    "key, answer",
    [("1", permissions.ONCE), ("2", permissions.SESSION), ("3", permissions.DENY), (ESC, permissions.DENY),
     (CTRL_C, permissions.DENY)],
)  # fmt: skip
def test_a_question_of_the_worker_is_answered_in_the_main_thread(terminal, key, answer):
    out = console()
    interrupt = threading.Event()

    def work(ask, interrupt):
        threading.Timer(0.3, terminal.send_text, [key]).start()  # once the question is shown
        return ask(REQUEST)

    assert Keys(terminal).watch(work, interrupt, out) == answer
    text = out.export_text()
    assert "Permission needed: test_runner__run_tests needs run_tests." in text
    assert "Version: base v1.0 (c7d45ad)" in text and "3. Deny (Esc)" in text
    assert not interrupt.is_set()  # Esc at a question denies; it does not interrupt


def test_an_error_of_the_work_is_raised_in_the_main_thread(terminal):
    def work(ask, interrupt):
        raise ValueError("broken")

    with pytest.raises(ValueError, match="broken"):
        Keys(terminal).watch(work, threading.Event(), console())


def test_choose_a_profile_by_number_or_name():
    err = console()
    answers = reader("x", "3", "2")
    assert interactive.choose_profile(["gemini", "local"], lambda message: answers(), err) == "local"
    answers = reader("gemini")
    assert interactive.choose_profile(["gemini", "local"], lambda message: answers(), err) == "gemini"
    shown = err.export_text()
    assert "1. gemini" in shown and "set model: gemini in ~/.retro/config.yaml" in shown
    answers = reader(EOFError())
    assert interactive.choose_profile(["gemini"], lambda message: answers(), err) is None
