# Generate reports

How to produce each report, choose Markdown or PDF and the language, and read what a report contains. The full catalog of values, blocks and sections is in the [reports reference](../reference/reports.md).

## Choose a report

| Report | Command | Describes | Needs |
|---|---|---|---|
| Test plan | `/report test-plan` | The change, the impacted requirements and modules, the risks, the suite and the exit criteria. | An impact analysis and a suite. No run. |
| Test case specification | `/report test-cases` | Every test case of the current suite, with its objective, data, steps and expected result. | A suite. No run. |
| Test status | `/report status` | One run: executions by status and result, and the comparison with the baseline. Default: the latest run. | A run. |
| Defects | `/report defects` | The defects found in the evaluated run and every open defect, with evidence and history. | Defects. |
| Test completion | `/report completion` | The whole cycle: metrics, exit criteria, the release decision and its reasons, deviations and what needs review. | A completed run on the candidate, and one on the baseline for the comparison. |

The test types follow ISO/IEC/IEEE 29119-3. `/cycle` ends with a completion report.

Choose a run with `--run`, for example `/report status --run RUN-0003`. A status report about a run on the baseline has no decision: exit criteria are evaluated only on the candidate.

## Choose the format

```
/report completion --format pdf
```

Markdown is always produced. With `--format pdf`, a PDF is produced from the same Markdown. Make PDF the default with `reports.default_format: pdf` in the configuration.

PDF needs the Pango system library:

| System | Install |
|---|---|
| Debian, Ubuntu | `sudo apt install libpango-1.0-0 libpangoft2-1.0-0` |
| Arch | `sudo pacman -S pango` |
| macOS | `brew install pango` |

Without it, the PDF step fails with a message that says what to install, and the Markdown report is still written.

## Choose the language

The language of the agent sections follows `language` in the configuration, or `--lang` for one session:

```
retro --lang es
```

Identifiers, enumeration values such as `do_not_release`, tool names and paths are never translated. The headings and fixed text of the bundled templates are in English.

## Find the files

Each report gets the next identifier and its own folder:

```
.retro/reports/RPT-0003-completion/
├── report.md
├── report.pdf          # with --format pdf
└── charts/
    ├── outcomes.svg
    ├── comparison.svg
    └── criteria.svg
```

A report is never overwritten. Generating the same type again creates a new one, so a report already delivered never changes.

## Read a completion report

| Part | Comes from | Read it for |
|---|---|---|
| Decision and its reasons | Code | `release`, `release_with_conditions` or `do_not_release`, and each criterion or condition that caused it. |
| Exit criteria table | Code | Each criterion with its threshold, value, state and whether it blocks. |
| Metrics and charts | Code | Outcomes of the executions, the comparison with the baseline, and each criterion against its threshold. |
| Deviations | Code | Test cases that were designed but not implemented, and executions that were blocked or skipped. |
| Items to review | Code | Excused failures, flaky executions, pre-existing failures and executions triaged more than once. They are judgments that changed the numbers; read them before trusting the decision. |
| Agent analysis | The model | Conclusions, summary, residual risks, limitations. Each section is marked as written by the model and not computed. |

Every figure, status and decision in the report is inserted by code. The model writes only the sections marked "Agent analysis", from the data of the same report. If the model is not available, those sections read "Not provided." and the report is still complete.

## When a report stays a draft

A report is prepared first, with all its computed data, and rendered after the model writes its sections. If the turn ends between the two, for example because the model stopped, the report stays `draft`: its computed part is in the report folder, and nothing recorded later changes it. Run `/report` again for a complete one.
