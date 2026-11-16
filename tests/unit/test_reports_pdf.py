"""Markdown to PDF (FR-29): the HTML, and the error when the system library is missing."""

import sys

import pytest

from retroagent.reports import pdf


def test_markdown_tables_and_images_become_html():
    html = pdf.to_html("# T\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n![c](charts/outcomes.svg)\n\n1. one\n2. two\n")
    assert "<table>" in html and "<h1>" in html and 'src="charts/outcomes.svg"' in html and "<ol>" in html


def test_a_missing_library_says_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "weasyprint", None)  # `from weasyprint import ...` now fails
    with pytest.raises(pdf.PdfUnavailable, match=r"Pango.*brew install pango"):
        pdf.write_pdf("# T", tmp_path / "r.pdf", tmp_path)


def test_a_library_that_loads_but_lacks_the_system_library_is_the_same_error(monkeypatch, tmp_path):
    class Broken:
        def __getattr__(self, name):
            raise OSError("cannot load library 'libgobject-2.0-0'")

    monkeypatch.setitem(sys.modules, "weasyprint", Broken())
    with pytest.raises(pdf.PdfUnavailable, match="libgobject"):
        pdf.write_pdf("# T", tmp_path / "r.pdf", tmp_path)
