# Test reports

How a report combines numbers computed by code with text written by the model, and why the two never mix ([ADR-0018](../adr/0018-report-templates-and-rendering.md), [ADR-0019](../adr/0019-item-templates.md), [ADR-0020](../adr/0020-mcp-servers-never-call-the-model.md)). How to generate them is in [Generate reports](../how-to/generate-reports.md); the catalog of everything a template can contain is in the [reports reference](../reference/reports.md).

## What the reports are for

The reports follow the test documentation of ISO/IEC/IEEE 29119-3: a test plan before testing, a test case specification, a status report during it, a defect report, and a completion report at the end. The completion report answers the question a release depends on: how well was the product tested, and can it be released?

A report is read by people who were not in the session and who may need to rely on it later. It must therefore say exactly what was recorded, and make clear which parts are judgments.

## Two kinds of content

| Content | Written by | Examples |
|---|---|---|
| Computed | Code, from project memory | Every metric, count, status, criterion and the decision; tables of test cases, defects and deviations; the charts. |
| Agent analysis | The model | Conclusions, summary, residual risks, limitations; in a defect, its impact and probable cause. |

Every agent section is rendered as a quote, headed "Agent analysis · written by `<model>`, not computed." A reader always knows which sentences are measurements and which are interpretation.

The model writes its sections from the computed data of the same report, and must not state a figure, status or decision that is not in it. If it does, the computed part of the report, which a reader can check line by line, still shows the truth.

## Two steps

A report is generated in two tool calls, with the model's writing in between:

1. **Prepare.** `reports.prepare_report` evaluates the exit criteria, computes every value, fills the template, draws the charts, and saves the result as a draft. It returns the data and the list of sections the model must write.
2. **Write.** The model writes each section from that data.
3. **Render.** `reports.render_report` inserts the sections into the draft and writes the final Markdown, and the PDF when asked.

The computed part is fixed at the first step. Whatever is recorded while the model writes does not change the report. The servers never ask the model for text themselves: the text arrives as an argument of the render call. The report server is therefore deterministic, and is tested without a model.

If the model never writes its sections, the report stays a draft, with all its computed content. If the model is not available at all, its sections read "Not provided." and the report is still complete.

## Templates without logic

Templates are Markdown files that anyone can read and edit. They contain no loops and no conditions, only three kinds of markers:

| Marker | Example | Replaced by |
|---|---|---|
| Value | `{{ metrics.pass_rate }}` | A formatted value: `88.5%`. |
| Block | `{{ table:criteria }}` | A table or list built by code, or a message when there is no data. |
| Agent section | `<!-- agent:conclusions -->` | The model's text, marked as such. |

Formatting is done by code, the same way everywhere: ratios as percentages with one decimal, timestamps in local time with their offset, a missing metric as `not evaluable`. A template therefore never needs a condition, and an unknown marker stops generation with an error instead of printing an empty line. Text that comes from memory or from the model is never read as a marker, so a test name or a justification cannot inject one.

## Reports that do not change

Each report gets a new identifier and its own folder, and is never overwritten. A report given to someone stays exactly as it was given. Generating it again produces a new report, from the records of that moment.

## The completion report

The completion report has eleven sections. It puts the decision first, with its reasons, then shows what supports it:

1. **Executive summary**: the decision and each reason for it.
2. **Summary of testing performed**, with the chart of execution outcomes.
3. **Scope**: planned against actual.
4. **Deviations** from the plan: test cases designed but not implemented, executions blocked or skipped.
5. **Test completion evaluation**: each exit criterion with threshold, value and state, and its chart.
6. **Test measures**: results, coverage, the comparison with the baseline with its chart, and selection quality.
7. **Defects**, open ones first.
8. **Items requiring review**: excused failures, flaky executions, pre-existing failures and executions triaged more than once. These are the judgments that changed the numbers. A reviewer who checks only one part of the report should check this one.
9. **Residual risks**.
10. **Limitations**: what could not be evaluated and why, and the fixed limits of the method.
11. **Test deliverables**, with their locations.

The agent sections sit next to the computed content they interpret: the conclusions under the decision, the summary under the outcomes, and the deviations, residual risks and limitations under their tables.
