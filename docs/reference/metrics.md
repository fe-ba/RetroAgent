# Metrics reference

Single source of truth for metric formulas, exit criteria and the release decision. Everything in this document is computed by code from stored data (ADR-0006). The model never computes a metric or decides a criterion; it only explains the results.

Every metric states its **basis**: the standard, syllabus or study it comes from, or the project decision that introduces it. Keys are listed in [Sources](#sources). The selection of metrics is justified in ADR-0017.

## Evaluation inputs

Metrics are computed for one **evaluated run** (ADR-0016).

| Input | Definition | Default |
|---|---|---|
| Evaluated run `R` | A completed run with scope `suite` against the candidate version. | Latest such run on the candidate commit of the session versions. |
| Planned suite `S` | The test cases selected for `R`. | The suite of `R`. |
| Baseline run `R0` | A completed run against the baseline version, used for comparison. | Latest completed run against the baseline on the baseline commit of `A`. Needed by EC-09: without it the decision is `do_not_release`. |
| Full runs `F0`, `F` | Runs of every implemented test case (`/run all`) against the baseline and the candidate. Used only for selection quality. | Latest completed full run on the baseline commit and on the candidate commit of `A`. Optional. |
| Impact analysis `A` | The analysis that `S` was selected for. It fixes the two commits that are compared. | — |
| Defects | Defects stored in project memory at evaluation time. | — |
| Thresholds | `exit_criteria.*` from the effective configuration. | See `configuration.md`. |

Runs on other commits are never used: every comparison is between the two commits of `A`. A run with scope `all` or `selected` has no planned suite and cannot be the evaluated run.

The evaluation records its timestamp and the values of every input, so the same report can always be reproduced from stored data.

## Conventions

- Counts refer to test executions of `R`, unless stated otherwise.
- The result of a test execution is the result of its **first attempt**. An execution whose first attempt did not pass is rerun `tests.reruns` times, always all of them; reruns never change the result (ADR-0022).
- An execution is **flaky** when its attempts produced different results. A flaky execution therefore always has the result `failed` or `error`, and goes through triage like any other failure.
- The triage of an execution is its **current triage**: the latest one (`data-model.md`).
- The **verdict** of an executed execution is `passed` or `not passed` (`failed` or `error`).
- Ratios are stored and compared as exact values. They are displayed as percentages with one decimal. A criterion is evaluated on the exact value, never on the displayed one.
- When a denominator is zero, the metric is **not evaluable**, unless the metric states a vacuous value.

## Metrics

Names are the identifiers used in code, storage and templates.

### Scope

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `planned` | Test cases in `S` | Planned scope. | [ISO29119-3] |
| `implemented` | Test cases in `S` with status `implemented` | Planned test cases that can run. | [ISTQB-FL] |
| `implementation_rate` | `implemented / planned` | Test preparation progress. | [ISTQB-FL] |
| `designed_only` | `planned - implemented` | Planned but never implemented; they cannot run. | Project (ADR-0016) |
| `executed` | Executions with status `executed` | Actual scope. | [ISTQB-FL] |
| `blocked` | Executions with status `blocked` | Could not run. | [ISO29119-3] |
| `skipped` | Executions with status `skipped` | Not run on purpose. | [ISTQB-FL] |
| `execution_rate` | `executed / planned` | Actual scope against planned scope. | [ISO29119-3] |

### Results

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `passed` | Executed with result `passed` | — | [ISTQB-FL] |
| `failed` | Executed with result `failed` | — | [ISTQB-FL] |
| `error` | Executed with result `error` | — | [ISTQB-FL] |
| `pass_rate` | `passed / executed` | Raw pass rate. | [ISTQB-FL] |
| `excused` | `failed` or `error` executions triaged as `expected_change` or `test_defect` | Failures that do not indicate a product problem; the tests must be updated. | Project (ADR-0017) |
| `product_pass_rate` | `passed / (executed - excused)` | Pass rate of the product. Used by the exit criteria. | Project (ADR-0017) |
| `pre_existing` | `failed` or `error` executions triaged as `pre_existing` | Failures that the baseline already had. They are not excused: they count against `product_pass_rate` and add a condition to the decision. | Project (ADR-0022) |
| `flaky` | Executed executions whose attempts produced different results | Detected flaky executions. A lower bound, see below. | [LUO14], [GRU21] |
| `flaky_rate` | `flaky / executed` | — | [LUO14], [GRU21] |

### Coverage

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `impacted_requirements` | Requirements marked as impacted in `A` | — | [ISTQB-FL] |
| `covered_requirements` | Impacted requirements traced to at least one executed execution in `R` | — | [ISTQB-FL] |
| `requirement_coverage` | `covered_requirements / impacted_requirements` | `1.0` when no requirement is impacted. Not evaluable when the project has no documented requirements. | [ISTQB-FL] |
| `high_priority_planned` | Test cases in `S` with priority `high` | — | [ISTQB-FL] |
| `high_priority_executed_rate` | High-priority test cases executed in `R` / `high_priority_planned` | Risk coverage, with test priority as the risk proxy. `1.0` when no high-priority test case is planned. | [ISTQB-FL] |

### Comparison with the baseline

Requires `R0`. Only test cases executed in both runs are compared. A test case whose verdict changes between versions is what [RH96] calls modification-revealing.

| Metric | Baseline verdict | Candidate verdict | Basis |
|---|---|---|---|
| `new_failures` | `passed` | not passed | [RH96] |
| `fixed` | not passed | `passed` | [RH96] |
| `persistent_failures` | not passed | not passed | [RH96] |
| `stable_passes` | `passed` | `passed` | [RH96] |
| `not_comparable` | Executed in only one of the two runs | — | Project (ADR-0016) |

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `unexcused_new_failures` | `new_failures` whose execution in `R` is not `excused` | Behavior that the baseline had and the candidate lost without a documented reason. Untriaged, `flaky` and `environment` failures count. Used by EC-09. Not evaluable when no test case was executed in both runs. | Project (ADR-0022) |

Without `R0`, these metrics are not evaluable and the report states it as a limitation. EC-09 is then `not_evaluable`, which blocks release.

### Selection quality

Informative only: these metrics never take part in exit criteria. They measure how well the agent chose `S`, using the evaluation framework of [RH96]. They require `F0` and `F`; otherwise they are not evaluable.

A test case is **revealing** when it was executed in both `F0` and `F`, its verdict differs between them, and neither execution is flaky. It is **non-revealing** when it was executed in both, its verdict is the same, and neither execution is flaky.

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `revealing` | Revealing test cases | Test cases that expose a behavior change between versions. | [RH96] |
| `selection_inclusiveness` | Revealing test cases in `S` / `revealing` | Share of revealing test cases the agent selected. `1.0` means a safe selection. `1.0` when `revealing = 0`. | [RH96] |
| `selection_precision` | Non-revealing test cases not in `S` / non-revealing test cases | Share of non-revealing test cases the agent left out. `1.0` when there are no non-revealing test cases. | [RH96] |

[RH96] defines revealing tests by a different program output. RetroAgent approximates output by test verdict, so a test that observes a change without asserting on it is not counted.

### Defects

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `open_defects.<severity>` | Defects with status `open`, per severity, at evaluation time | — | [ISTQB-FL] |
| `defects_found` | Defects linked to executions of `R` | — | [ISTQB-FL] |
| `defects_closed` | Defects with status `closed` at evaluation time | — | [ISTQB-FL] |

### Time

| Metric | Formula | Meaning | Basis |
|---|---|---|---|
| `run_duration` | End time minus start time of `R`, in seconds | — | [ISO29119-3] |
| `test_time` | Sum of the test times reported in the JUnit XML of `R`, in seconds | — | [ISO29119-3] |

## Exit criteria

| ID | Criterion | Condition to be met | Blocking | Basis |
|---|---|---|---|---|
| EC-01 | Product pass rate | `product_pass_rate >= min_pass_rate` | Yes | [ISTQB-FL], Project (ADR-0017) |
| EC-02 | High-priority execution | `high_priority_executed_rate >= min_high_priority_executed` | Yes | [ISTQB-FL] |
| EC-03 | Requirement coverage | `requirement_coverage >= min_requirement_coverage` | No | [ISTQB-FL] |
| EC-04 | Critical defects | `open_defects.critical <= max_open_defects.critical` | Yes | [ISTQB-FL] |
| EC-05 | High defects | `open_defects.high <= max_open_defects.high` | Yes | [ISTQB-FL] |
| EC-06 | Medium defects | `open_defects.medium <= max_open_defects.medium`; always met when the limit is `null` | No | [ISTQB-FL] |
| EC-07 | Flaky tests | `flaky_rate <= max_flaky_rate` | No | [LUO14] |
| EC-08 | Failures triaged | Every `failed` or `error` execution of `R` has a triage classification, and every execution classified `regression` is linked to a defect | Yes | [ISO29119-3] |
| EC-09 | New failures | `unexcused_new_failures <= max_new_failures` | Yes | [RH96], Project (ADR-0022) |

Thresholds come from `exit_criteria.*` in the configuration. Their default values are common conventions, not values required by any standard. EC-08 has no threshold and is always applied.

Each criterion is evaluated to one state:

| State | Meaning |
|---|---|
| `met` | The condition holds. |
| `not_met` | The condition does not hold. |
| `not_evaluable` | A metric it depends on is not evaluable. |

## Release decision

Applied in order. The first rule that matches decides.

1. If any blocking criterion is `not_met` or `not_evaluable`: **`do_not_release`**.
2. If any non-blocking criterion is `not_met` or `not_evaluable`, or `excused > 0`, or `pre_existing > 0`, or `designed_only > 0`: **`release_with_conditions`**.
3. Otherwise: **`release`**.

A blocking criterion that cannot be evaluated counts against release: when nothing was executed, or nothing was compared with the baseline, nothing is released.

### Conditions

When the decision is `release_with_conditions`, the report lists one condition for each cause:

| Cause | Condition |
|---|---|
| Non-blocking criterion `not_met` | The criterion, its threshold and its value. |
| Non-blocking criterion `not_evaluable` | The criterion and why it could not be evaluated. |
| `excused > 0` | The test cases that must be updated, with their classification. |
| `pre_existing > 0` | The test cases that already failed against the baseline, with the baseline run. |
| `designed_only > 0` | The planned test cases that were never implemented. |

### Exit codes

The release decision maps to the exit codes in `cli.md`: `release` and `release_with_conditions` exit with `0`, `do_not_release` exits with `3`.

## What the metrics do not say

- **A high pass rate only means the executed tests passed.** It says nothing about what was not tested; read it together with `execution_rate` and `requirement_coverage`.
- **`excused` depends on triage.** A wrong classification moves a real failure out of `product_pass_rate` and out of EC-09. `expected_change` is accepted only when code finds a documented requirement change (`mcp-tools.md`); `test_defect` remains a judgment of the model. Reports list every excused execution so that the classification can be reviewed.
- **`flaky` is a lower bound.** Reruns detect only part of the flakiness: [GRU21] estimates that 95% confidence that a passing test is not flaky needs on average 170 reruns. RetroAgent runs `tests.reruns` (default 2).
- **A flaky failure is not noise.** Flaky tests can reveal real faults [FLAKY-CI]. A flaky execution keeps the result of its first attempt, is triaged like any other failure, and blocks release through EC-09 when the test case passed against the baseline. A later run in which it passes at the first attempt does not erase it: the history keeps the flaky execution.
- **Defect counts depend on defects being registered.** EC-08 forces every regression to have one, but severity is a judgment. EC-09 does not depend on severity.
- **The model still shapes the inputs.** The suite, the impacted requirements, priorities, defect severities and the classifications `regression`, `environment` and `test_defect` are judgments of the model. Code computes the decision from them; it cannot make them right. ADR-0022 lists what code validates.
- **No code coverage.** Measuring it requires language-specific instrumentation, outside the language-agnostic design of ADR-0010.

## Sources

- **[ISO29119-3]** ISO/IEC/IEEE 29119-3:2021, *Software and systems engineering — Software testing — Part 3: Test documentation*. Information elements of the test status and test completion reports.
- **[ISTQB-FL]** ISTQB Certified Tester Foundation Level Syllabus v4.0, section 5.3.1, *Metrics used in testing*.
- **[RH96]** G. Rothermel and M. J. Harrold, "Analyzing Regression Test Selection Techniques", *IEEE Transactions on Software Engineering*, 22(8), 1996. DOI 10.1109/32.536955.
- **[LUO14]** Q. Luo, F. Hariri, L. Eloussi and D. Marinov, "An Empirical Analysis of Flaky Tests", *FSE 2014*. DOI 10.1145/2635868.2635920.
- **[GRU21]** M. Gruber, S. Lukasczyk, F. Kroiß and G. Fraser, "An Empirical Study of Flaky Tests in Python", *ICST 2021*. arXiv:2101.09077.
- **[FLAKY-CI]** Empirical study of flakiness prediction on the Chromium continuous integration, UCL Discovery, https://discovery.ucl.ac.uk/id/eprint/10199773/.
