# ADR-0018: Report templates and rendering

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

Reports are the main output of RetroAgent: the test completion report answers how satisfactorily the product was tested. Templates must be easy to read and edit, reports must be readable in a repository and exportable to PDF, and charts are required (FR-28). Everything must work offline and on the user's machine.

## Decision

**Templates** are Markdown files, optionally with HTML. They contain no template-language logic: no loops and no conditions. Three markers connect them to data:

| Marker | Form | Replaced by |
|---|---|---|
| Value | `{{ metrics.pass_rate }}` | The formatted value. |
| Block | `{{ table:open_defects }}` or `{{ list:limitations }}`, alone on its line | A table or list built by code, or a message when there is no data. |
| Agent section | `<!-- agent:conclusions -->`, alone on its line | Text written by the model, marked with the model that wrote it. |

Charts are referenced with plain Markdown and fixed relative paths (`charts/outcomes.svg`). An unknown marker stops report generation with an error that names it.

**Values** are formatted by code: ratios as percentages with one decimal, counts as integers, durations in seconds, timestamps in ISO 8601 with their UTC offset, and lists joined with commas. A missing metric is shown as `not evaluable`; any other missing value is shown as `none`. This removes the need for conditions in templates.

**Output.** Each report is written to `.retro/reports/<report-id>-<type>/` (for example `RPT-0003-completion/`) with `report.md`, `report.pdf` and `charts/`. The Markdown file is the source of truth; the PDF is always produced from it.

**PDF.** Markdown is converted to HTML, styled with `templates/styles/`, and converted to PDF with WeasyPrint.

**Charts** are drawn with matplotlib and saved as SVG. The test completion report has three: execution outcomes, comparison with the baseline and exit criteria against their thresholds. Bar charts are used instead of pie charts. When the data of a chart is not evaluable, the chart states it.

**Language.** Templates are looked up in `templates/<language>/` first and fall back to `templates/` (English).

## Alternatives considered

- **Jinja2 templates:** powerful, but loops and conditions inside templates make them hard to read and edit.
- **Pandoc with LaTeX:** high-quality PDF, but a large external installation.
- **Programmatic PDF (e.g. ReportLab):** no external dependency, but the layout lives in code and cannot be edited as a document.
- **Mermaid charts:** text-based, but rendering requires a browser or Node.js.
- **HTML reports only:** simple, but no PDF for the course deliverable.

## Consequences

- Editing a report means editing a Markdown file that any viewer can preview.
- The columns of each block are defined in code and documented in `docs/reference/reports.md`; changing them requires a code change.
- WeasyPrint needs the Pango system library. It is a package-manager install on Linux and macOS and a manual install on Windows. PDF export is therefore optional; Markdown output always works.
- Templates are validated: an unknown marker is detected when the report is generated, not when it is read.
