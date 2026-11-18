"""The reference script: the model answers of the reference scenario of shop-api (``ORACLE.md``), for ``FakeProvider``.

``cycle_1()`` drives ``/cycle v1.0 v1.1`` and ``cycle_2()`` drives ``/cycle v1.1 v1.2`` in a new session on the memory
of cycle 1. Each model step follows its skill: it loads the skill, reads what the skill says to read, records what it
says to record, and answers. The direct steps (``discover``, ``run``) need no answer of the model, so they have no
part here. The choices are those of the reference scenario: the impact, the risks, the suite of every project test,
TC-027 and TC-028 for the gap of REQ-002 (TC-027 implemented, TC-028 left ``designed``), the triage of ORACLE.md and
DEF-001, and the agent sections of the completion report.

Every figure stored on the way comes from the runs of the test runner, never from this script: the script only
answers the way a model would.

Run as a program, it is the fallback of the presentation when a real model fails::

    python tests/fixtures/reference_script.py <dir> [--cycle-2]

It creates the example in ``<dir>`` when it does not exist, and runs ``retro -p "/cycle"`` on it with this script as
the model, in mode ``auto`` with the project commands trusted.
"""

import sys
from pathlib import Path

if __name__ == "__main__":  # run as a program: the folder tests/ holds the package fixtures
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures.agent_session import (  # noqa: E402
    DEFECT_STEPS,
    DEFECT_TITLE,
    GENERATED_FILE,
    GENERATED_NAME,
    NOT_IMPACTED,
    REPORT_SECTIONS,
    REQ_002_DESIGN,
    Scripted,
    answer,
    call,
    calls,
    generated_code,
    result_in,
)
from retroagent.llm import Response  # noqa: E402

# Cycle 1 ------------------------------------------------------------------------------------------------------------

CYCLE_1_DIFFS = {
    "src/shop/pricing.py": "Totals are now computed in a new order: discounts, then shipping and tax. Shipping and"
    " tax can be computed on another amount.",
    "src/shop/discounts.py": "Two different coupons can now be combined; a third one is rejected.",
    "src/shop/cart.py": "add_item changed; the stock check of adding products can be affected.",
    "src/shop/orders.py": "Checkout now records the order, and orders can be listed.",
    "src/shop/store.py": "The store keeps the orders in memory.",
    "src/shop/api.py": "New endpoints for the order history.",
    "pyproject.toml": "Version and description only; no dependency changed.",
}
CYCLE_1_MODULES = [
    ("pricing", ["src/shop/pricing.py"], "high",
     "Totals are computed in a new order; shipping and tax depend on that order (REQ-003, REQ-005, REQ-007)."),
    ("discounts", ["src/shop/discounts.py"], "high", "Coupon rules changed: two coupons can be combined (REQ-004)."),
    ("cart", ["src/shop/cart.py"], "medium", "add_item changed; its stock check had no test (REQ-002)."),
    ("orders", ["src/shop/orders.py", "src/shop/store.py", "src/shop/api.py"], "low",
     "Order history added; checkout has a new side effect (REQ-006, REQ-008)."),
    ("project", ["pyproject.toml", "README.md", "RETRO.md", "docs/requirements.md"], "low",
     "Version, documentation and the requirements document: no behavior."),
    ("tests", ["tests/test_api.py", "tests/test_discounts.py", "tests/test_orders.py"], "low",
     "Tests added for REQ-004 and REQ-008: no product behavior."),
]  # fmt: skip
CYCLE_1_IMPACTED = {
    "REQ-002": "src/shop/cart.py changed in add_item, which adds products to the cart.",
    "REQ-003": "src/shop/pricing.py computes the cart totals in a new order.",
    "REQ-004": "Documented change: Changed v1.1, two coupons can be combined; src/shop/discounts.py implements it."
    " Failures in this area may be expected_change.",
    "REQ-005": "src/shop/pricing.py computes shipping from the subtotal, and the order of discounts and shipping"
    " changed.",
    "REQ-006": "src/shop/orders.py and src/shop/store.py changed: checkout now records the order.",
    "REQ-007": "src/shop/pricing.py computes the tax on the discounted subtotal, and the order changed.",
    "REQ-008": "New in v1.1: the order history, in src/shop/orders.py and src/shop/api.py.",
}
# The risks of the reference scenario (expected/test-completion-report.md, Residual risks).
CYCLE_1_RISKS = [
    ("Totals are computed in a new order in `src/shop/pricing.py`; shipping and tax may be computed on the wrong"
     " amount.", "high", ["REQ-003", "REQ-005", "REQ-007"]),
    ("Coupon rules changed in `src/shop/discounts.py`; combinations of coupons may give a wrong discount.", "high",
     ["REQ-004"]),
    ("`src/shop/cart.py` changed and its stock check had no test before this cycle.", "medium", ["REQ-002"]),
    ("Orders are now kept in memory by `src/shop/store.py`; checkout has a new side effect.", "low",
     ["REQ-006", "REQ-008"]),
]  # fmt: skip

# TC-028 of the reference scenario: designed for REQ-002 and left without code.
REQ_002_UNKNOWN_PRODUCT = {
    "title": "An unknown product cannot be added",
    "objective": "Verify that adding a product that is not in the catalog is refused and the cart does not change.",
    "priority": "medium",
    "preconditions": ["A new cart"],
    "input_data": [{"name": "product", "value": "p-999"}, {"name": "quantity", "value": "1"}],
    "steps": ["Add 1 unit of p-999 to the cart", "Read the cart"],
    "expected_result": "The addition raises NotFound, as get_product does in the baseline code, and the cart stays"
    " empty.",
    "requirement_ids": ["REQ-002"],
    "selection_reason": "Covers the gap of REQ-002: its error path.",
}

# The triage of ORACLE.md, in the order of the executions of the run; the justifications of the excused, flaky and
# pre-existing failures are those of the expected report (Items requiring review).
TC_014_JUSTIFICATION = (
    'REQ-004 has the entry "Changed: v1.1 - Two different coupons can be combined". The test still expects a second'
    " coupon to be rejected. The test must be updated."
)
TC_020_JUSTIFICATION = (
    "Shipping 0.00 for a discounted subtotal of 90.00, expected 5.00: REQ-005 requires shipping on the subtotal after"
    " discounts and has no documented change. It passed in {baseline}."
)
CYCLE_1_TRIAGE = {
    "TC-011": ("REQ-001", "flaky", "Failed at the first attempt and passed in both reruns."),
    "TC-014": ("REQ-004", "expected_change", TC_014_JUSTIFICATION),
    "TC-020": ("REQ-005", "regression", TC_020_JUSTIFICATION),
    "TC-022": ("REQ-007", "pre_existing", "Failed against the baseline in {baseline}."),
}
CYCLE_2_TRIAGE = {
    "TC-011": CYCLE_1_TRIAGE["TC-011"],
    "TC-022": CYCLE_1_TRIAGE["TC-022"],
}

CYCLE_2_SECTIONS = {
    "conclusions": "The decision is `release_with_conditions`: every blocking criterion is met. The condition is"
    " TC-022, which already failed against the baseline: decide what to do with the tax rounding of REQ-007.",
    "summary": "The suite of the project tests ran against v1.1 and against v1.2. The shipping fix of v1.2 makes TC-020"
    " pass again, and DEF-001 was closed by the run against the candidate.",
    "deviations": "No planned test case was left without execution.",
    "residual_risks": "TC-011 is flaky, so the catalog search may still fail intermittently. TC-022 fails in both"
    " versions.",
    "limitations": "Only the tests of the project ran: the change was small and every impacted requirement was"
    " covered.",
}


def cycle_1() -> Scripted:
    """The model of cycle 1 (``/cycle v1.0 v1.1``): every model step, in the order of the cycle."""
    return Scripted([
        *analyze(CYCLE_1_DIFFS, CYCLE_1_MODULES, CYCLE_1_IMPACTED, CYCLE_1_RISKS),
        *select(CYCLE_1_SELECTION_NOTE),
        *design_req_002(),
        *implement_tc_027(),
        *triage(CYCLE_1_TRIAGE),
        *report(REPORT_SECTIONS),
    ])  # fmt: skip


# Cycle 2: v1.2 fixes shipping and removes the obsolete coupon test.
CYCLE_2_DIFFS = {
    "src/shop/pricing.py": "Shipping is computed again on the subtotal after discounts.",
    "tests/test_discounts.py": "The obsolete test of the second coupon is removed; no test is added.",
    "pyproject.toml": "Version only.",
}
CYCLE_2_MODULES = [
    ("pricing", ["src/shop/pricing.py"], "high", "Shipping is computed on the subtotal after discounts (REQ-005)."),
    ("tests", ["tests/test_discounts.py"], "low", "A test removed: no product behavior."),
    ("project", ["pyproject.toml"], "low", "Version only."),
]  # fmt: skip
CYCLE_2_IMPACTED = {"REQ-005": "src/shop/pricing.py computes shipping on the subtotal after discounts again."}
CYCLE_2_RISKS = [
    ("Shipping changes again in `src/shop/pricing.py`; the totals of carts with a coupon may change.", "high",
     ["REQ-005"]),
]  # fmt: skip
REMOVED_IN_V1_2 = "tests.test_discounts::test_req_004_second_coupon_is_rejected"
CYCLE_1_SELECTION_NOTE = (
    "The change set adds lines to test files; a full run against the candidate makes their tests known."
)
CYCLE_2_SELECTION_NOTE = (
    "The change set only removes lines from tests/test_discounts.py: it adds no test, so no full run against the"
    " candidate is needed. The removed test is left out of the suite."
)


def cycle_2() -> Scripted:
    """The model of cycle 2 (``/cycle v1.1 v1.2``), in a new session on the memory of cycle 1."""
    return Scripted([
        *analyze(CYCLE_2_DIFFS, CYCLE_2_MODULES, CYCLE_2_IMPACTED, CYCLE_2_RISKS, documented=False),
        *select(CYCLE_2_SELECTION_NOTE, removed=(REMOVED_IN_V1_2,)),
        *design_nothing(),
        *implement_nothing(),
        *triage(CYCLE_2_TRIAGE),
        *report(CYCLE_2_SECTIONS),
    ])  # fmt: skip


# The steps --------------------------------------------------------------------------------------------------------


def note(text: str, *tool_calls) -> Response:
    """A model answer that writes a note and makes tool calls, as the skills ask between reads."""
    return Response(text=text, tool_calls=tool_calls, finish_reason="tool_calls")


def first_user_message(request) -> str:
    return next(m.content for m in request.messages if m.role == "user")


def analyze(diffs: dict, modules: list, impacted: dict, risks: list, documented: bool = True) -> list:
    """The skill ``impact-analysis``: synchronize the requirements, compute the change set, read the diff of each file
    that can affect behavior one at a time with a note, read the requirements, record the impact with a decision on
    every requirement, register the risks and answer."""
    changes, requirements = call("git__analyze_changes"), call("memory__get_requirements")
    saved: dict = {}

    def save_impact(request) -> Response:
        result = result_in(request, changes.id)
        saved["analysis_id"] = result["analysis_id"]
        changed = {f["path"] for f in result["files"]}
        read = [r["id"] for r in result_in(request, requirements.id)["requirements"]]
        assert {f for _, files, _, _ in modules for f in files} <= changed, "a module names a file not in the change"
        return calls(call("memory__save_impact", {
            "analysis_id": result["analysis_id"],
            "modules": [{"module": m, "files": f, "risk_level": level, "reason": reason}
                        for m, f, level, reason in modules],
            "requirements": [{"requirement_id": r, "reason": impacted[r]} for r in read if r in impacted],
            "not_impacted": [{"requirement_id": r, "reason": NOT_IMPACTED.get(r, "No changed file takes part in its"
                              " behavior.")} for r in read if r not in impacted],
        }))  # fmt: skip

    reads = []
    previous = "The change set is computed."
    for path, summary in diffs.items():
        reads.append(note(previous, call("git__get_diff", {"path": path})))
        previous = f"`{path}`: {summary}"
    impacted_text = ", ".join(impacted)
    return [
        calls(call("runtime__load_skill", {"name": "impact-analysis"})),
        calls(call("memory__sync_requirements")),
        calls(changes),
        *reads,
        note(previous, requirements),
        save_impact,
        calls(
            *(
                call("memory__add_risk", {"description": d, "level": level, "requirement_ids": r})
                for d, level, r in risks
            )
        ),  # fmt: skip
        lambda request: answer(
            f"Analysis {saved['analysis_id']}: the impact is recorded. Impacted requirements: {impacted_text}."
            + (" REQ-004 is a documented change and REQ-008 is new." if documented else "")
            + f" {len(risks)} risks registered. Next step: `/select`."
        ),
    ]


def select(runs_note: str, removed: tuple[str, ...] = ()) -> list:
    """The skill ``test-selection``: read the analysis and the test cases, check that a full run against the candidate
    exists when the change adds tests, read the risks and the impacted requirements, and save a suite of every
    project test (the suite of the reference scenario: it is small, so everything is selected). Tests removed by the
    change are not selected; ``left_out`` names every implemented test case traced to an impacted requirement that is
    not selected, which is none in both cycles."""
    analysis, test_cases = call("memory__get_analysis"), call("memory__get_test_cases")
    saved: dict = {}

    def save_suite(request) -> Response:
        impacted = {r["requirement_id"] for r in result_in(request, analysis.id)["requirements"]}
        project = [
            tc for tc in result_in(request, test_cases.id)["test_cases"]
            if tc["origin"] == "project_suite" and tc.get("test_id") not in removed
        ]  # fmt: skip
        items = []
        for position, tc in enumerate(project, start=1):
            traced = [r["requirement_id"] for r in tc["requirements"]]
            linked = [r for r in traced if r in impacted]
            reason = (
                f"Traced to {', '.join(linked)}, impacted by the change."
                if linked
                else f"Traced to {', '.join(traced) or 'no requirement'}; the suite is small, so every project test"
                " is selected."
            )
            items.append({"test_case_id": tc["id"], "position": position, "selection_reason": reason})
        chosen = {item["test_case_id"] for item in items}
        left_out = [
            {"test_case_id": tc["id"], "reason": f"Removed by the change; traced to {', '.join(linked)}."
             if tc.get("test_id") in removed else f"Not selected; traced to {', '.join(linked)}."}
            for tc in result_in(request, test_cases.id)["test_cases"]
            if tc["status"] == "implemented" and tc["id"] not in chosen
            and (linked := [r["requirement_id"] for r in tc["requirements"] if r["requirement_id"] in impacted])
        ]  # fmt: skip
        saved["call"] = call("memory__save_suite", {"analysis_id": result_in(request, analysis.id)["analysis_id"],
                                                    "items": items, "left_out": left_out})  # fmt: skip
        return calls(saved["call"])

    def report(request) -> Response:
        result = result_in(request, saved["call"].id)
        gaps = result["uncovered_requirements"]
        gap_text = f"Gaps: {', '.join(gaps)} has no test case." if gaps else "No impacted requirement is uncovered."
        following = "`/design`" if gaps else "`/run --on both`"
        return answer(f"Suite {result['suite_id']} is saved with every test of the project. {gap_text} Next step:"
                      f" {following}.")  # fmt: skip

    return [
        calls(call("runtime__load_skill", {"name": "test-selection"})),
        calls(analysis, test_cases),
        note(runs_note, call("memory__get_runs", {"version_role": "candidate"})),
        calls(call("memory__get_risks"), call("memory__get_requirements")),
        save_suite,
        report,
    ]


def design_req_002() -> list:
    """The skill ``test-design`` (Design) for the gap of REQ-002: read the suite, the analysis, the requirement, its
    code, the data and an existing test, check for duplicates, then design TC-027 and TC-028."""
    return [
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(call("memory__get_suite")),
        calls(call("memory__get_analysis"), call("memory__get_requirements", {"ids": ["REQ-002"]})),
        calls(
            call("git__read_file", {"path": "src/shop/cart.py", "version": "base"}),
            call("git__read_file", {"path": "src/shop/catalog.py", "version": "base"}),
            call("git__list_files", {"version": "base", "path": "tests"}),
        ),
        calls(call("git__read_file", {"path": "tests/test_cart.py", "version": "base"})),
        calls(call("memory__get_test_cases", {"requirement_id": "REQ-002"})),
        calls(call("memory__design_test_case", REQ_002_DESIGN)),
        calls(call("memory__design_test_case", REQ_002_UNKNOWN_PRODUCT)),
        answer(
            "| Test case | Title | Priority | Requirements |\n|---|---|---|---|\n"
            "| TC-027 | A quantity above the stock is rejected | high | REQ-002 |\n"
            "| TC-028 | An unknown product cannot be added | medium | REQ-002 |\n\n"
            "They are designed, not implemented, not executed. Next step: `/implement`."
        ),
    ]


def implement_tc_027() -> list:
    """The skill ``test-design`` (Implement): read the designed test cases of the suite, the conventions and the
    modules the test imports at both versions, and write the code of TC-027, the generated test of the oracle. TC-028
    is left ``designed``, as in the reference scenario."""
    designed = call("memory__get_test_cases", {"status": "designed"})
    written: dict = {}

    def write(request) -> Response:
        cases = {tc["title"]: tc["id"] for tc in result_in(request, designed.id)["test_cases"]}
        written["call"] = call("test_runner__write_test", {
            "test_case_id": cases[REQ_002_DESIGN["title"]], "file": GENERATED_FILE, "test_name": GENERATED_NAME,
            "code": generated_code(),
        })  # fmt: skip
        written["tc_028"] = cases[REQ_002_UNKNOWN_PRODUCT["title"]]
        return calls(written["call"])

    def report(request) -> Response:
        result = result_in(request, written["call"].id)
        return answer(
            f"| Test case | Implementation |\n|---|---|\n| {result['test_case_id']} | {result['implementation']} |\n\n"
            f"Implemented, not executed. {written['tc_028']} stays `designed`: it is a condition of the decision until"
            f" it is implemented with `/implement {written['tc_028']}`. Next step: `/run --on both`."
        )

    return [
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(call("memory__get_suite"), designed),
        calls(call("git__list_files", {"version": "candidate", "path": "tests"})),
        calls(call("git__read_file", {"path": "tests/test_cart.py", "version": "candidate"})),
        calls(
            call("git__read_file", {"path": "src/shop/store.py", "version": "base"}),
            call("git__read_file", {"path": "src/shop/store.py", "version": "candidate"}),
            call("git__read_file", {"path": "src/shop/errors.py", "version": "base"}),
            call("git__read_file", {"path": "src/shop/errors.py", "version": "candidate"}),
        ),
        write,
        report,
    ]


def design_nothing() -> list:
    """The skill ``test-design`` (Design) when the suite covers every impacted requirement."""
    return [
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(call("memory__get_suite")),
        answer("The current suite covers every impacted requirement: nothing to design. Next step: `/implement`."),
    ]


def implement_nothing() -> list:
    """The skill ``test-design`` (Implement) when no test case of the suite is ``designed``."""
    return [
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(call("memory__get_suite"), call("memory__get_test_cases", {"status": "designed"})),
        answer("No test case of the current suite is designed: nothing to implement. Next step: `/run --on both`."),
    ]


def triage(table: dict) -> list:
    """The skill ``failure-triage`` on the run named in the message: read the latest baseline run and the untriaged
    failures, then for each one in order read its evidence, history, test case and requirement, and record its
    triage; a regression gets its defect at once. ``table`` maps each failed test case to its requirement, its
    classification and its justification, where ``{baseline}`` is the baseline run."""
    baseline_runs = call("memory__get_runs", {"version_role": "base", "limit": 1})
    found: dict = {}

    def start(request) -> Response:
        run_id = first_user_message(request).split("`")[3]  # "... triage the failed executions of run `<id>`."
        found["run_id"] = run_id
        found["untriaged"] = call("memory__get_executions", {"run_id": run_id, "untriaged": True})
        return calls(found["untriaged"], baseline_runs)

    def evidence(test_case_id: str):
        def step(request) -> Response:
            if "executions" not in found:
                found["executions"] = {
                    e["test_case_id"]: e["execution_id"]
                    for e in result_in(request, found["untriaged"].id)["executions"]
                }
                found["baseline"] = result_in(request, baseline_runs.id)["runs"][0]["id"]
                assert set(found["executions"]) == set(table), "the failures differ from the reference scenario"
            return calls(
                call("test_runner__get_evidence", {"run_id": found["run_id"], "test_case_id": test_case_id}),
                call("memory__get_test_case_history", {"test_case_id": test_case_id}),
                call("memory__get_test_cases", {"ids": [test_case_id]}),
                call("memory__get_requirements", {"ids": [table[test_case_id][0]]}),
            )

        return step

    def save(test_case_id: str):
        def step(request) -> Response:
            _, classification, justification = table[test_case_id]
            return calls(call("memory__save_triage", {
                "execution_id": found["executions"][test_case_id], "classification": classification,
                "justification": justification.format(baseline=found["baseline"]),
            }))  # fmt: skip

        return step

    def register(test_case_id: str):
        def step(request) -> Response:
            return calls(call("memory__register_defect", {
                "title": DEFECT_TITLE, "severity": "high", "execution_ids": [found["executions"][test_case_id]],
                "steps": DEFECT_STEPS,
            }))  # fmt: skip

        return step

    script: list = [calls(call("runtime__load_skill", {"name": "failure-triage"})), start]
    for test_case_id, (_, classification, _) in sorted(table.items(), key=lambda item: item[0]):
        script += [evidence(test_case_id), save(test_case_id)]
        if classification == "regression":
            script += [calls(call("memory__get_defects", {"status": "open"})), register(test_case_id)]
    rows = "\n".join(f"| {tc} | {c} |" for tc, (_, c, _) in sorted(table.items()))
    defects = "DEF-001 registered for TC-020." if any(c == "regression" for _, c, _ in table.values()) else ""
    script += [
        calls(call("memory__get_defects", {"status": "closed"})),
        answer(f"| Test case | Classification |\n|---|---|\n{rows}\n\n{defects} Next step: `/report completion`."),
    ]
    return script


def report(sections: dict) -> list:
    """The skill ``test-reporting`` for the completion report: check that no failure waits for triage and that a
    baseline run exists, prepare the report, write every listed section from the computed data, render it."""
    prepare = call("reports__prepare_report", {"type": "completion"})
    rendered: dict = {}

    def checks(request) -> Response:
        runs = call("memory__get_runs", {"version_role": "candidate", "limit": 1})
        rendered["runs"] = runs
        return calls(runs, call("memory__get_runs", {"version_role": "base", "limit": 1}))

    def untriaged(request) -> Response:
        run_id = result_in(request, rendered["runs"].id)["runs"][0]["id"]
        return calls(call("memory__get_executions", {"run_id": run_id, "untriaged": True}))

    def render(request) -> Response:
        prepared = result_in(request, prepare.id)
        written = {
            s["name"]: sections.get(s["name"], "Nothing to add to the computed data.") for s in prepared["sections"]
        }
        rendered["call"] = call("reports__render_report", {"report_id": prepared["report_id"], "sections": written})
        return calls(rendered["call"])

    def final(request) -> Response:
        result = result_in(request, rendered["call"].id)
        decision = sections["conclusions"].split("`")[1]
        files = ", ".join(f"`{path}`" for path in result["files"])
        return answer(f"{result['report_id']} is rendered: {files}. The decision is `{decision}`.")

    return [
        calls(call("runtime__load_skill", {"name": "test-reporting"})),
        checks,
        untriaged,
        calls(prepare),
        render,
        final,
    ]


# The fallback of the presentation ----------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import tempfile

    from fixtures.agent_session import write_user_config
    from retroagent.cli.main import main as retro
    from retroagent.examples import materialize
    from retroagent.runtime import session as session_module

    parser = argparse.ArgumentParser(description="Run /cycle on shop-api with the reference script as the model.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cycle-2", action="store_true", help="run cycle 2 (v1.1 to v1.2) on the memory of cycle 1")
    args = parser.parse_args(argv)
    if not args.directory.exists():
        materialize("shop-api", args.directory)
    home = Path(tempfile.mkdtemp(prefix="retro-reference-"))
    write_user_config(home)  # a local profile that is never contacted: the script answers instead
    os.environ["RETRO_HOME"] = str(home)
    provider = cycle_2() if args.cycle_2 else cycle_1()
    session_module._make_provider = lambda profile, session, factory: provider
    refs = ["v1.1", "v1.2"] if args.cycle_2 else ["v1.0", "v1.1"]
    return retro(["-C", str(args.directory), "--mode", "auto", "--trust-commands", "-p", f"/cycle {' '.join(refs)}"])


if __name__ == "__main__":
    sys.exit(main())
