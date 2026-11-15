# ADR-0017: Test metrics basis

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

The test completion report must answer how satisfactorily the product was tested, and the release decision depends on the metrics behind that answer. Metrics invented without a basis are hard to defend and easy to misread.

ISO/IEC/IEEE 29119-3 defines which information a test completion report contains (testing performed, deviations, completion evaluation, blocking factors, test measures, residual risks), but it does not prescribe formulas or thresholds. The ISTQB Foundation syllabus provides the most widely used catalog of test metrics. Regression testing has its own literature on how to evaluate test selection and on flaky tests.

## Decision

- Metrics follow the categories of the ISTQB Foundation syllabus (preparation, execution, defects, coverage) and fill the information elements of ISO/IEC/IEEE 29119-3.
- Comparison between baseline and candidate is based on the notion of modification-revealing tests from Rothermel and Harrold (1996).
- The quality of the agent's test selection is measured with inclusiveness and precision from the same framework, as informative metrics outside the exit criteria. They require full runs of every implemented test case against both versions (`/run all`).
- Flaky tests are detected by reruns, following Luo et al. (2014). The flaky count is reported as a lower bound, and flaky executions are listed for review, not discarded.
- Two metrics are project decisions without a direct standard basis: `excused` and `product_pass_rate`. They are labeled as such, and reports list every excused execution.
- Thresholds are configurable defaults. They are presented as conventions, not as values required by a standard.
- Every metric in `metrics.md` states its basis.

## Alternatives considered

- **APFD (average percentage of faults detected):** the standard metric for test prioritization, but it measures execution order, and execution order is decided by the test framework, not by RetroAgent.
- **Defect detection percentage:** requires defects found after release, which RetroAgent cannot observe.
- **Defect density:** requires a size measure such as lines of code, which depends on the language and contradicts ADR-0010.
- **Code coverage:** requires language-specific instrumentation; contradicts ADR-0010.
- **Effort and cost metrics:** not meaningful for automated execution; time metrics take their place.
- **Ad hoc metrics without a basis:** simpler to define, but not defensible.

## Consequences

- Every figure in a report can be traced to a definition and to a source.
- Selection quality can be compared across models with an established framework, which supports the model comparison of the acceptance scenarios.
- Selection quality costs two additional full runs; it is optional.
- `flaky_rate` under-reports flakiness; reports state it.
- `product_pass_rate` depends on triage quality; the list of excused executions makes it reviewable.
