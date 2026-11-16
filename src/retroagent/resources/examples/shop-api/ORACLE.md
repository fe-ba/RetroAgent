# Oracle of shop-api

What RetroAgent is expected to find in this example. It is the ground truth for the acceptance scenarios and for the hand-filled completion report. It is never copied into the created project.

Every figure below was obtained by running the project as the test runner does: a new worktree per version, the setup and test commands of `.retro/config.yaml`, the service started on a free port, and two reruns of each test that did not pass.

## Versions

| Tag | Commit | Content |
|---|---|---|
| `v1.0` | `c7d45ada468e3746c498cb3417999e117154a942` | Catalog, cart, coupons, shipping, tax and checkout. Requirements REQ-001 to REQ-007. |
| `v1.1` | `46a5ef0910ce409a767f7549ed0c557106409321` | Two coupons can be combined (REQ-004 changed). Order history (REQ-008, new). |
| `v1.2` | `9936dccd1584a9226feabe90acf9dd8ab1c62e59` | Shipping fixed. Obsolete coupon test removed. |

The commit hashes are the same on every machine (see `../README.md`).

## Seeded cases

| ID | Case | Where | What it must lead to |
|---|---|---|---|
| S1 | Regression | `v1.1`, `src/shop/pricing.py`: shipping is computed on the subtotal before discounts. REQ-005 requires the subtotal after discounts. | `test_req_005_shipping_charged_when_discount_drops_below_threshold` passes on `v1.0` and fails on `v1.1`: a new failure. Triage `regression`, a defect, EC-09 not met. |
| S2 | Expected change | `v1.1`, REQ-004 has `Changed: v1.1`. `test_req_004_second_coupon_is_rejected` still asserts the old rule. | New failure, triage `expected_change`, accepted by code because the `Changed` entry applies to `v1.0..v1.1`. Excused. |
| S3 | Flaky test | Every version, `src/shop/catalog.py`: the first search in a new checkout builds its index and returns results in catalog order; later searches read the stored index, which is sorted. | `test_req_001_search_results_are_sorted_by_name` fails at the first attempt and passes in both reruns. Result `failed`, flaky, triage `flaky` accepted by code. |
| S4 | Pre-existing failure | Every version, `src/shop/money.py`: amounts are rounded half to even; REQ-007 requires half up. | `test_req_007_tax_rounds_half_up` fails on every version and in every attempt. On a candidate: triage `pre_existing`, accepted by code because it failed against the baseline. |
| S5 | Impacted requirement without a test | REQ-002 has no test in any version, and `src/shop/cart.py` changes in `v1.1`. | Impact analysis marks REQ-002, selection reports the gap, and a test case is designed and implemented. A correct test for REQ-002 passes on `v1.0` and `v1.1`. |
| S6 | Tests added by the change | `v1.1` adds four tests: two for REQ-004 and two for REQ-008. | They are known only after a full run against the candidate. The change set touches test files, so the selection skill must ask for it. |
| S7 | Fix in a later version | `v1.2` computes shipping on the discounted subtotal again. | In a cycle `v1.1` to `v1.2`: the shipping test is `fixed`, and the run closes the defect of S1. |

## Raw results

First attempt of every test of the project, in a new worktree.

| Version | Tests | Passed | Not passed |
|---|---|---|---|
| `v1.0` | 22 | 20 | 2: S3 (flaky), S4 |
| `v1.1` | 26 | 22 | 4: S1, S2, S3 (flaky), S4 |
| `v1.2` | 25 | 23 | 2: S3 (flaky), S4 |

Attempts of the tests that did not pass, the same in every version where they appear:

| Test | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| `tests.test_catalog::test_req_001_search_results_are_sorted_by_name` | failed | passed | passed |
| `tests.test_tax::test_req_007_tax_rounds_half_up` | failed | failed | failed |
| `tests.test_shipping::test_req_005_shipping_charged_when_discount_drops_below_threshold` (`v1.1`) | failed | failed | failed |
| `tests.test_discounts::test_req_004_second_coupon_is_rejected` (`v1.1`) | failed | failed | failed |

## Cycle 1: `v1.0` to `v1.1`

Reference figures for a suite that contains every test of the project and no generated test. With generated tests, or with a smaller suite, the counts change; the decision and its reasons must not.

| Metric | Value |
|---|---|
| `planned`, `implemented`, `executed` | 26 |
| `passed` | 22 |
| `failed` | 4 |
| `pass_rate` | 22 / 26 = 84.6% |
| `excused` | 1 (S2) |
| `pre_existing` | 1 (S4) |
| `product_pass_rate` | 22 / 25 = 88.0% |
| `flaky`, `flaky_rate` | 1, 1 / 26 = 3.8% |
| `new_failures` | 2 (S1, S2) |
| `unexcused_new_failures` | 1 (S1) |
| `fixed` | 0 |
| `persistent_failures` | 2 (S3, S4) |
| `stable_passes` | 18 |
| `not_comparable` | 4 (S6) |
| `revealing` (full runs) | 2 (S1, S2) |

Expected triage:

| Test | Classification | Defect |
|---|---|---|
| S1 shipping test | `regression` | Yes. Severity `high`: a main function gives a wrong amount. |
| S2 second coupon test | `expected_change` | No. The test must be updated. |
| S3 search test | `flaky` | No. |
| S4 tax rounding test | `pre_existing` | Not required. |

Exit criteria, with `min_pass_rate` 0.90 from the project configuration and the other thresholds at their defaults:

| Criterion | State | Why |
|---|---|---|
| EC-01 Product pass rate | `not_met` | 88.0% is below 90%. |
| EC-05 High defects | `not_met` | One open `high` defect, when the model assigns that severity. |
| EC-07 Flaky tests | `met` | 3.8% is not above 5%. |
| EC-08 Failures triaged | `met` | After triage and the defect of S1. |
| EC-09 New failures | `not_met` | One new failure is not excused. |

**Decision: `do_not_release`.** It must hold whatever severity the model gives to the defect, because EC-01 and EC-09 do not depend on it.

## Cycle 2: `v1.1` to `v1.2`

Same reference suite: every test of the project at `v1.2`.

| Metric | Value |
|---|---|
| `planned`, `implemented`, `executed` | 25 |
| `passed` | 23 |
| `failed` | 2 |
| `pass_rate`, `product_pass_rate` | 23 / 25 = 92.0% |
| `excused` | 0 |
| `pre_existing` | 1 (S4) |
| `flaky`, `flaky_rate` | 1, 1 / 25 = 4.0% |
| `new_failures`, `unexcused_new_failures` | 0 |
| `fixed` | 1 (S1) |
| `persistent_failures` | 2 (S3, S4) |
| `stable_passes` | 22 |
| `not_comparable` | 1 when the baseline run is a full run (the removed coupon test), 0 otherwise |

- The candidate run closes the defect of S1, because its only linked test case passed.
- Every blocking criterion is met. `pre_existing` is 1.

**Decision: `release_with_conditions`.** Condition: the tax rounding test already failed against the baseline.

## Judgments of the model

These depend on the model, so they are checked with tolerance.

| Step | Expected |
|---|---|
| Impact analysis | `pricing.py` and `discounts.py` as `high` risk. REQ-004 as a documented change. REQ-005 among the impacted requirements. REQ-008 as new. |
| Selection | The shipping tests and the coupon tests are in the suite. A selection that leaves out the S1 test is unsafe: `selection_inclusiveness` below 1.0. |
| Gaps | REQ-002 reported without a test. |
| Design | At least one test case traced to REQ-002, with a concrete quantity above the stock of a product and the expected rejection. |
| Triage | The table of cycle 1. `expected_change` for S1 must be refused by code: REQ-005 has no documented change. |
| Report | The agent sections state the decision as computed and name S1 as the reason. |
