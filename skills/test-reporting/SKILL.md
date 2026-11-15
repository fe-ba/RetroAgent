---
name: test-reporting
description: Generate a test plan, test case specification, test status report, defect report or test completion report: prepare it, write its agent sections from the computed data, and render it. Use for /report, or when asked for a report, metrics or the release decision.
---

# Test reporting

Reports are generated in two steps. Code computes every figure, status and decision, and lists the agent sections; you write those sections; code renders the files. You never compute or change a value.

## Procedure

1. **Type.** `test-plan`, `test-cases`, `status`, `defects` or `completion`. Map the request of the user to one of them; when it is unclear, ask.
2. **Preconditions.**
   - `test-plan` and `test-cases` need an impact analysis and a current suite.
   - `status` needs a run.
   - `defects` and `completion` need a completed run against the candidate.

   If one is missing, say which step produces it and stop.
3. **Triage first.** For `completion`, call `memory.get_executions` with the evaluated run and `untriaged` `true`. If any failure is not triaged, EC-08 will be `not_met` and the decision `do_not_release`. Tell the user and offer `/triage` first. Continue only if the user wants the report anyway.
   Also call `memory.get_runs` with `version_role` `base`. Without a completed run against the baseline, EC-09 will be `not_evaluable` and the decision `do_not_release`. Tell the user and offer `/run --on base` first.
4. **Prepare.** Call `reports.prepare_report` with the type, and the run and formats when given. Keep the report ID, the computed data and the list of agent sections.
5. **Write** every listed section, under the exact name listed, following the rules below.
6. **Render.** Call `reports.render_report` with the report ID and the sections. If PDF is `unavailable`, the Markdown is still produced: say so, and that the PDF needs the optional PDF dependencies.
7. **Answer** with the report ID, the paths of its files and, for `status` and `completion`, the decision and its main reasons, copied from the computed data.

For a question about metrics or the release decision without a report, call `reports.evaluate` and explain its result.

## Writing agent sections

- Use only the computed data returned by `reports.prepare_report`. Do not state a figure, status, identifier or decision that is not in it. Copy values as they appear.
- Never contradict the release decision. Explain it.
- Mark hypotheses as such.
- Plain paragraphs, with short lists when they help. No headings: each section is rendered inside a quote block.
- Two to six sentences per section, in the language of the session.
- Refer to records by their IDs.

| Section | Write |
|---|---|
| `conclusions` | The decision, its reasons (blocking criteria not met, conditions), and the recommended actions in order. |
| `summary` | What was tested: versions, scope, runs. What the results mean, beyond the numbers. |
| `deviations` | Why planned test cases were not implemented or executed, and the effect on the conclusions. |
| `residual_risks` | Risks that testing did not rule out: untested areas, open defects, criteria not evaluable, flaky tests, excused failures. Their potential impact. |
| `limitations` | What the results cannot show beyond the computed limitations: missing requirements, weak expected results, test cases designed by a model. |
| `context` | The purpose of the change and of this regression cycle. |
| `scope` | Why the scope is what it is, and what is deliberately left out. |
| `risks` | Test plan: the risks that guide prioritization. Status report: risks that are new or changed since the plan. |
| `strategy` | How selection and design address the impacted areas. |
| `status` | The current state of testing in a few sentences. |
| `next_steps` | The testing planned next and what it depends on. |
| `analysis.<DEF-ID>` | For each defect: its impact and its probable cause, stated as a hypothesis. |
