"""Large output (mcp-tools.md): at most the result limit, cut at a line boundary, and pages that join back."""

import pytest

from retroagent.servers.errors import ToolError
from retroagent.servers.serving import lines_of, page

TEXT = "".join(f"line {n:02}\n" for n in range(1, 21))  # 20 lines of 8 characters


def pages(text: str, limit: int) -> list[tuple[str, dict]]:
    found, start = [], 1
    while True:
        content, meta = page(text, start, limit)
        found.append((content, meta))
        if "next_line" not in meta:
            return found
        start = meta["next_line"]


def test_lines_end_only_at_newline():
    assert lines_of("a\r\nb\x0cc\nlast") == ["a\r\n", "b\x0cc\n", "last"]
    assert lines_of("") == []
    assert lines_of("a\n") == ["a\n"]


def test_a_text_within_the_limit_is_returned_whole():
    assert page(TEXT, 1, 1_000) == (TEXT, {"truncated": False})


def test_a_long_text_is_cut_at_a_line_boundary_and_its_pages_join_back():
    first, meta = page(TEXT, 1, 30)
    assert first == "line 01\nline 02\nline 03\n"
    assert meta == {"truncated": True, "next_line": 4}
    found = pages(TEXT, 30)
    assert all(len(content) <= 30 for content, _ in found)
    assert "".join(content for content, _ in found) == TEXT
    assert found[-1][1] == {"truncated": False}


def test_a_text_without_a_final_newline_joins_back():
    text = TEXT + "tail without newline"
    assert "".join(content for content, _ in pages(text, 25)) == text


def test_a_line_longer_than_the_limit_is_cut_and_named():
    text = "short\n" + "x" * 50 + "\nend\n"
    content, meta = page(text, 2, 20)
    assert content == "x" * 20
    assert meta == {"truncated": True, "cut_line": 2, "next_line": 3}
    content, meta = page("y" * 50, 1, 20)
    assert meta == {"truncated": True, "cut_line": 1}


def test_an_empty_text_has_one_empty_page():
    assert page("", 1, 10) == ("", {"truncated": False})


@pytest.mark.parametrize("start_line", [0, -1, 22])
def test_a_start_line_outside_the_text_is_an_invalid_argument(start_line):
    with pytest.raises(ToolError) as error:
        page(TEXT, start_line, 100)
    assert error.value.code == "invalid_argument"


def test_the_line_after_the_last_is_refused_but_the_last_is_not():
    assert page(TEXT, 20, 100) == ("line 20\n", {"truncated": False})
    with pytest.raises(ToolError):
        page(TEXT, 21, 100)
