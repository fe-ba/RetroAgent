"""Parsing of requirement documents (project-contract.md, Requirements): the documents of shop-api, and every
requirement that cannot be parsed is reported, never dropped in silence."""

from importlib.resources import files

from retroagent.servers.memory.requirements import Change, Problem, parse_documents

VERSIONS = files("retroagent.resources") / "examples" / "shop-api" / "versions"


def shop_api(version: str) -> str:
    return (VERSIONS / version / "docs" / "requirements.md").read_text(encoding="utf-8")


def parse_one(text: str, source: str = "docs/requirements.md"):
    return parse_documents([(source, text)])


def test_the_requirements_of_shop_api_v1_0():
    requirements, problems = parse_one(shop_api("v1.0"))
    assert problems == []
    assert [r.id for r in requirements] == [f"REQ-00{n}" for n in range(1, 8)]
    req_004 = requirements[3]
    assert req_004.title == "Discount coupons"
    assert req_004.priority == "high"
    assert req_004.since == "v1.0"
    assert req_004.changes == ()
    assert req_004.source_file == "docs/requirements.md"


def test_the_requirements_of_shop_api_v1_1():
    requirements, problems = parse_one(shop_api("v1.1"))
    assert problems == []
    by_id = {r.id: r for r in requirements}
    assert sorted(by_id) == [f"REQ-00{n}" for n in range(1, 9)]
    assert by_id["REQ-004"].changes == (
        Change("v1.1", "Two different coupons can be combined; before, only one coupon applied per order."),
    )
    assert by_id["REQ-004"].description.startswith("A valid coupon reduces the subtotal by its percentage.")
    assert "Priority" not in by_id["REQ-004"].description
    assert by_id["REQ-008"].title == "Order history"
    assert by_id["REQ-008"].since == "v1.1"
    assert by_id["REQ-008"].priority == "low"
    assert by_id["REQ-005"].removed is None


def test_fields_several_changes_and_removed():
    text = """# Requirements

### REQ-010 - Exports

Exports are CSV.
More text on a second line.

- priority: Medium
- Since: v1.0
- Changed: v1.1 - Adds JSON.
- Changed: v1.2 - Adds XML - and YAML.
- Removed: v2.0
"""
    (requirement,), problems = parse_one(text)
    assert problems == []
    assert requirement.title == "Exports"
    assert requirement.description == "Exports are CSV.\nMore text on a second line."
    assert requirement.priority == "medium"
    assert requirement.removed == "v2.0"
    assert requirement.changes == (Change("v1.1", "Adds JSON."), Change("v1.2", "Adds XML - and YAML."))


def test_other_bullets_belong_to_the_description():
    text = "## REQ-011: Limits\n\nLimits:\n\n- Owner: team A\n- at most 3 items\n"
    (requirement,), _ = parse_one(text)
    assert requirement.description == "Limits:\n\n- Owner: team A\n- at most 3 items"


def test_a_heading_without_an_id_is_not_a_requirement():
    requirements, problems = parse_one("# Requirements of shop-api\n\n## Glossary\n\nText.\n")
    assert requirements == [] and problems == []


BROKEN = """## REQ-001: Good

Kept.

## REQ-02: Short id

Text.

## REQ-003:

No title.

## REQ-004: No description

- Priority: high

## REQ-005: Bad priority

Text.

- Priority: urgent

## REQ-006: Bad change

Text.

- Changed: v1.1 without a separator

## REQ-007: Repeated field

Text.

- Since: v1.0
- Since: v1.1

## REQ-008: Good too

Kept.
"""


def test_each_requirement_that_cannot_be_parsed_is_reported_and_the_others_are_kept():
    requirements, problems = parse_one(BROKEN, "docs/req.md")
    assert [r.id for r in requirements] == ["REQ-001", "REQ-008"]
    assert [(p.file, p.requirement) for p in problems] == [
        ("docs/req.md", "REQ-02"),
        ("docs/req.md", "REQ-003"),
        ("docs/req.md", "REQ-004"),
        ("docs/req.md", "REQ-005"),
        ("docs/req.md", "REQ-006"),
        ("docs/req.md", "REQ-007"),
    ]
    reasons = [p.reason for p in problems]
    assert "REQ-NNN" in reasons[0]
    assert "title" in reasons[1]
    assert "description" in reasons[2]
    assert "urgent" in reasons[3]
    assert "Changed" in reasons[4]
    assert "Since" in reasons[5]


def test_a_repeated_id_is_reported_and_the_first_one_kept():
    requirements, problems = parse_documents(
        [("a.md", "## REQ-001: First\n\nOne.\n"), ("b.md", "## REQ-001: Second\n\nTwo.\n")]
    )
    assert [(r.id, r.source_file) for r in requirements] == [("REQ-001", "a.md")]
    assert problems == [Problem("b.md", "REQ-001", "REQ-001 is already defined in a.md")]
