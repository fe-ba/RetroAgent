"""A model profile for tests, and sessions whose model is a ``FakeProvider``.

Every session needs a model profile (runtime.md, Start step 7). The profile of these tests is a local ``ollama``
profile: it needs no credential, and nothing contacts the server unless a model call is made, which tests never do
with it. Sessions that call a model use a ``FakeProvider`` through ``provider_factory``.
"""

from pathlib import Path

from retroagent.llm import FakeProvider, Response, ToolCall

PROFILE = "local"
WINDOW = 32_768
USER_CONFIG = (
    f"model: {PROFILE}\n"
    "models:\n"
    f"  {PROFILE}:\n"
    "    provider: ollama\n"
    "    name: test-model\n"
    "    base_url: http://127.0.0.1:9\n"
    f"    context_window: {WINDOW}\n"
)


def write_user_config(home: Path, extra: str = "") -> None:
    """The user level of a test: the local profile, selected with ``model``, followed by ``extra``."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(USER_CONFIG + extra, encoding="utf-8")


def factory(provider=None):
    """A ``provider_factory`` of ``session.start`` that returns ``provider``, or an empty ``FakeProvider``."""
    chosen = provider if provider is not None else FakeProvider()
    return lambda profile, on_wait: chosen


# Scripts of FakeProvider and what a turn leaves in project memory.

_ids = iter(range(1, 1_000_000))


def call(name: str, arguments: dict | None = None, *, invalid: str | None = None) -> ToolCall:
    """A tool call of the model, with a new ID."""
    return ToolCall(id=f"call-{next(_ids)}", name=name, arguments=arguments or {}, invalid_arguments=invalid)


def calls(*tool_calls: ToolCall, finish_reason: str = "tool_calls") -> Response:
    """A model answer with these tool calls."""
    return Response(text="", tool_calls=tool_calls, finish_reason=finish_reason)


def answer(text: str = "Done.", finish_reason: str = "stop") -> Response:
    """A model answer without tool calls, which ends the turn."""
    return Response(text=text, finish_reason=finish_reason)


def tool_rows(conn, session_id: int) -> list[dict]:
    """The ``tool_call`` rows of a session, in the order they were written."""
    return [
        dict(row) for row in conn.execute("SELECT * FROM tool_call WHERE session_id = ? ORDER BY id", (session_id,))
    ]


def tool_results(conversation) -> dict[str, str]:
    """The content of each tool message of a conversation, by the ID of the call it answers."""
    return {m.tool_call_id: m.content for m in conversation.messages if m.role == "tool"}


class Scripted(FakeProvider):
    """A ``FakeProvider`` whose script may hold functions: ``step(request)`` returns the response, so a later answer
    can use a result the model read before, such as the analysis ID of ``git__analyze_changes``."""

    def complete(self, request):
        if self.remaining and callable(self._script[0]) and not isinstance(self._script[0], BaseException):
            step = self._script.pop(0)
            self._script.insert(0, step(request))
        return super().complete(request)


def result_in(request, call_id: str) -> dict:
    """The result of a tool call as the model received it in ``request``."""
    import json

    return json.loads(next(m.content for m in request.messages if m.role == "tool" and m.tool_call_id == call_id))


# The decision of the reference scenario (ORACLE.md, SC-22): every requirement is impacted except REQ-001, the catalog
# search, whose behavior no changed file takes part in.
NOT_IMPACTED = {"REQ-001": "Catalog search: no changed file takes part in it."}


def analyze_script(text: str = "The impact is recorded.") -> list:
    """A model that follows the skill ``impact-analysis`` on shop-api: it loads the skill, synchronizes the
    requirements, computes the change set, reads one diff and the requirements, records the impact with every file of
    the change set and a decision on every requirement it read, registers one risk and answers."""
    changes = call("git__analyze_changes")
    requirements = call("memory__get_requirements")

    def save_impact(request) -> Response:
        result = result_in(request, changes.id)
        modules: dict[str, list[str]] = {}
        for changed in result["files"]:
            modules.setdefault(changed["path"].split("/")[0], []).append(changed["path"])
        read = [r["id"] for r in result_in(request, requirements.id)["requirements"]]
        return calls(
            call(
                "memory__save_impact",
                {
                    "analysis_id": result["analysis_id"],
                    "modules": [
                        {"module": name, "files": files, "risk_level": "high", "reason": "Changed in the diff."}
                        for name, files in sorted(modules.items())
                    ],
                    "requirements": [
                        {"requirement_id": r, "reason": "A changed file takes part in it."}
                        for r in read
                        if r not in NOT_IMPACTED
                    ],
                    "not_impacted": [
                        {"requirement_id": r, "reason": NOT_IMPACTED[r]} for r in read if r in NOT_IMPACTED
                    ],
                },
            )
        )

    return [
        calls(call("runtime__load_skill", {"name": "impact-analysis"})),
        calls(call("memory__sync_requirements")),
        calls(changes),
        calls(call("git__get_diff", {"path": "src/shop/pricing.py"})),
        calls(requirements),
        save_impact,
        calls(
            call(
                "memory__add_risk",
                {"description": "Two coupons give a wrong total.", "level": "high", "requirement_ids": ["REQ-004"]},
            )
        ),
        answer(text),
    ]


# /select and /design as the reference scenario makes them (ORACLE.md): the suite holds every project test traced to
# an impacted requirement, and one test case is designed for the gap of REQ-002. Its code is the generated test of
# the oracle, which passes against both versions.

GENERATED_FILE = "test_req_002_quantity_above_stock_is_rejected.py"
GENERATED_NAME = "test_req_002_quantity_above_stock_is_rejected"
REQ_002_DESIGN = {
    "title": "A quantity above the stock is rejected",
    "objective": "Verify that adding more units than in stock is refused and the cart does not change.",
    "priority": "high",
    "preconditions": ["Product p-102 has stock 5", "A new cart"],
    "input_data": [{"name": "product", "value": "p-102"}, {"name": "quantities", "value": "3, then 3"}],
    "steps": ["Add 3 units of p-102", "Add 3 more units of p-102", "Read the cart"],
    "expected_result": "The second addition raises InsufficientStock and the cart keeps 3 units.",
    "requirement_ids": ["REQ-002"],
    "selection_reason": "Covers the gap of REQ-002.",
}


def generated_code() -> str:
    """The generated test of the oracle (``expected/``)."""
    from pathlib import Path

    from retroagent.resources import __file__ as resources_file

    path = Path(resources_file).parent / "examples" / "shop-api" / "expected" / GENERATED_FILE
    return path.read_text(encoding="utf-8")


def select_script(text: str = "Suite saved.") -> list:
    """A model that follows the skill ``test-selection``: every test case traced to an impacted requirement."""
    analysis, test_cases = call("memory__get_analysis"), call("memory__get_test_cases")

    def save_suite(request) -> Response:
        impacted = {r["requirement_id"] for r in result_in(request, analysis.id)["requirements"]}
        selected = [
            tc["id"]
            for tc in result_in(request, test_cases.id)["test_cases"]
            if any(r["requirement_id"] in impacted for r in tc["requirements"])
        ]
        items = [
            {"test_case_id": test_case_id, "position": position, "selection_reason": "Traced to an impacted one."}
            for position, test_case_id in enumerate(selected, start=1)
        ]
        analysis_id = result_in(request, analysis.id)["analysis_id"]
        return calls(call("memory__save_suite", {"analysis_id": analysis_id, "items": items}))

    return [
        calls(call("runtime__load_skill", {"name": "test-selection"})),
        calls(analysis, test_cases),
        save_suite,
        answer(text),
    ]


def design_script(text: str = "TC designed; designed, not implemented, not executed.") -> list:
    """A model that follows the skill ``test-design`` (Design) for the gap of REQ-002."""
    return [
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(call("memory__get_suite")),
        calls(call("memory__design_test_case", REQ_002_DESIGN)),
        answer(text),
    ]


# The triage of the reference scenario (ORACLE.md, Expected triage), in the order the skill failure-triage gives:
# for each failure of RUN-0004, its evidence, then its classification. With ``wrong_first``, the classifications that
# code must refuse come first (SC-13): expected_change and pre_existing for the shipping test, flaky for the tax test.
TRIAGE_RUN = "RUN-0004"
TRIAGE = [
    ("TC-020", "REQ-005", [
        ("expected_change", "REQ-005 may have changed in v1.1.", True),
        ("pre_existing", "Shipping may have failed against the baseline.", True),
        ("regression", "Shipping 0.00 for a discounted subtotal of 90.00, expected 5.00: REQ-005 requires shipping on"
                       " the subtotal after discounts and has no documented change. It passed in RUN-0003.", False),
    ]),
    ("TC-014", "REQ-004", [
        ("expected_change", 'REQ-004 has "Changed: v1.1": two coupons can be combined. The test still expects the'
                            " second coupon to be rejected (409); it must be updated.", False),
    ]),
    ("TC-011", "REQ-001", [
        ("flaky", "Failed at the first attempt (results not sorted) and passed in both reruns.", False),
    ]),
    ("TC-022", "REQ-007", [
        ("flaky", "The tax rounding may be intermittent.", True),
        ("pre_existing", "Tax 0.12 for 0.625, expected 0.13 (half up). It also failed in RUN-0003 (v1.0).", False),
    ]),
]  # fmt: skip
DEFECT_TITLE = "Shipping is not charged when a coupon brings the subtotal under 100.00"
DEFECT_STEPS = ["Add products for 100.00 to a cart", "Apply a 10% coupon", "Read the totals"]


def triage_script(severity: str = "high", wrong_first: bool = True, extra: list | None = None) -> Scripted:
    """A model that follows the skill ``failure-triage`` on RUN-0004 of the reference scenario: it reads the untriaged
    failures, the evidence of each one, classifies it, registers one defect for the regression and answers. ``extra``
    are answers of the model after the defect is registered, before the final answer."""
    untriaged = call("memory__get_executions", {"run_id": TRIAGE_RUN, "untriaged": True})
    seen: dict[str, int] = {}

    def save(test_case_id, classification, justification):
        def step(request):
            if not seen:
                seen.update(
                    {e["test_case_id"]: e["execution_id"] for e in result_in(request, untriaged.id)["executions"]}
                )
            arguments = {"execution_id": seen[test_case_id], "classification": classification,
                         "justification": justification}  # fmt: skip
            return calls(call("memory__save_triage", arguments))

        return step

    def register(request):
        arguments = {"title": DEFECT_TITLE, "severity": severity, "execution_ids": [seen["TC-020"]],
                     "steps": DEFECT_STEPS}  # fmt: skip
        return calls(call("memory__register_defect", arguments))

    script: list = [calls(call("runtime__load_skill", {"name": "failure-triage"})), calls(untriaged)]
    for test_case_id, requirement_id, attempts in TRIAGE:
        script.append(calls(
            call("test_runner__get_evidence", {"run_id": TRIAGE_RUN, "test_case_id": test_case_id}),
            call("memory__get_test_case_history", {"test_case_id": test_case_id}),
        ))  # fmt: skip
        script.append(calls(
            call("memory__get_test_cases", {"ids": [test_case_id]}),
            call("memory__get_requirements", {"ids": [requirement_id]}),
        ))  # fmt: skip
        for classification, justification, wrong in attempts:
            if wrong_first or not wrong:
                script.append(save(test_case_id, classification, justification))
    script += [
        calls(call("memory__get_defects", {"status": "open"})),
        register,
        *(extra or []),
        calls(call("memory__get_defects", {"status": "closed"})),
        answer(
            "| Test case | Classification |\n|---|---|\n| TC-020 | regression |\n| TC-014 | expected_change |\n"
            "| TC-011 | flaky |\n| TC-022 | pre_existing |\n\nDEF-001 registered for TC-020. No defect was closed."
        ),
    ]
    return Scripted(script)


# /report completion as the skill test-reporting makes it on the reference scenario: the checks of triage and of the
# baseline run, then prepare, the agent sections written from the computed data, and render.
REPORT_SECTIONS = {
    "conclusions": "The decision is `do_not_release`: EC-01, EC-05 and EC-09 are not met. Fix DEF-001 (TC-020) first,"
    " then update TC-014 for the documented change of REQ-004.",
    "summary": "The suite of 28 test cases ran against v1.1 in RUN-0004 and against v1.0 in RUN-0003.",
    "deviations": "TC-028 was designed and never implemented, so it was not executed.",
    "residual_risks": "DEF-001 stays open. TC-011 is flaky, so the search may still fail intermittently.",
    "limitations": "TC-027 and TC-028 were designed by a model; their expected results are a hypothesis.",
}


def report_script(text: str = "RPT-0001 is rendered. The decision is `do_not_release`.") -> list:
    """A model that follows the skill ``test-reporting`` for ``/report completion --format pdf`` on the reference
    scenario: it loads the skill, checks that no failure waits for triage and that a baseline run exists, prepares the
    report, writes every listed section from the computed data and renders it."""
    prepare = call("reports__prepare_report", {"type": "completion", "formats": ["pdf"]})

    def render(request) -> Response:
        prepared = result_in(request, prepare.id)
        sections = {s["name"]: REPORT_SECTIONS[s["name"]] for s in prepared["sections"]}
        return calls(call("reports__render_report", {"report_id": prepared["report_id"], "sections": sections}))

    return [
        calls(call("runtime__load_skill", {"name": "test-reporting"})),
        calls(
            call("memory__get_executions", {"run_id": TRIAGE_RUN, "untriaged": True}),
            call("memory__get_runs", {"version_role": "base"}),
        ),
        calls(prepare),
        render,
        answer(text),
    ]
