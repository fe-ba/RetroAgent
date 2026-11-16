"""Markdown to PDF with WeasyPrint (ADR-0018). The Markdown is the source of truth; PDF is optional."""

from pathlib import Path

import markdown

import retroagent.resources

STYLESHEET = Path(retroagent.resources.__file__).parent / "templates" / "styles" / "report.css"

INSTALL_HINT = (
    "PDF export needs the Pango system library: on Debian or Ubuntu install libpango-1.0-0 and libpangoft2-1.0-0, "
    "on Fedora pango, on Arch Linux pango, on macOS run `brew install pango`, and on Windows install the GTK3 "
    "runtime (see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html). The Markdown report was written."
)


class PdfUnavailable(Exception):
    """WeasyPrint or the system library it needs cannot be loaded. The message says what to install."""


def to_html(text: str) -> str:
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    return f'<!doctype html><html><head><meta charset="utf-8"></head><body>{body}</body></html>'


def write_pdf(text: str, target: Path, base_dir: Path) -> None:
    """Write ``text`` as a PDF at ``target``. Relative images, such as ``charts/outcomes.svg``, resolve in
    ``base_dir``."""
    try:
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as error:  # OSError: the shared library is missing
        raise PdfUnavailable(f"{error}. {INSTALL_HINT}") from error
    HTML(string=to_html(text), base_url=str(base_dir)).write_pdf(str(target), stylesheets=[CSS(filename=STYLESHEET)])
