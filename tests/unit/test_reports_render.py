"""Markers and templates (ADR-0018, ADR-0019; reports.md, Template resolution)."""

import pytest

from retroagent.reports import render
from retroagent.reports.render import Renderer, ReportError, Scope, add_agent_sections, agent_block

SECTIONS = {"conclusions": "purpose", "summary": "purpose"}


@pytest.fixture
def templates(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "TEMPLATES", tmp_path)
    (tmp_path / "items").mkdir()

    def write(name, text, folder=""):
        path = tmp_path / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    return write


def run(templates, text, scope=None, language="en"):
    templates("t.md", text)
    return Renderer(language, SECTIONS).render("t.md", scope or Scope(values={"a.b": "ONE", "c": "TWO"}))


def test_a_value_is_replaced_with_or_without_spaces(templates):
    assert run(templates, "x {{ a.b }} y {{c}} z") == "x ONE y TWO z"


def test_an_unknown_value_is_an_error_that_names_the_marker_and_the_template(templates):
    with pytest.raises(ReportError, match=r"unknown marker \{\{ nope \}\} in t\.md"):
        run(templates, "text {{ nope }}")


def test_a_block_alone_on_its_line_is_replaced_by_its_text(templates):
    scope = Scope(values={}, blocks={"table:risks": lambda: "| A |\n|---|\n| 1 |"})
    assert run(templates, "before\n\n{{ table:risks }}\n\nafter", scope) == "before\n\n| A |\n|---|\n| 1 |\n\nafter"


def test_a_block_that_is_not_alone_on_its_line_is_an_error(templates):
    scope = Scope(values={}, blocks={"table:risks": lambda: "x"})
    with pytest.raises(ReportError, match="not alone on its line"):
        run(templates, "see {{ table:risks }}", scope)


def test_an_unknown_block_and_unknown_items_are_errors(templates):
    with pytest.raises(ReportError, match=r"unknown marker \{\{ list:nope \}\}"):
        run(templates, "{{ list:nope }}")
    with pytest.raises(ReportError, match=r"unknown marker \{\{ items:nope \}\}"):
        run(templates, "{{ items:nope }}")


def test_agent_markers_stay_in_place_in_the_draft(templates):
    assert run(templates, "a\n\n<!-- agent:conclusions -->\n\nb") == "a\n\n<!-- agent:conclusions -->\n\nb"


def test_an_unknown_agent_section_is_an_error(templates):
    with pytest.raises(ReportError, match="unknown agent section 'nope' in t.md"):
        run(templates, "<!-- agent:nope -->")


def test_an_agent_marker_must_be_alone_on_its_line(templates):
    with pytest.raises(ReportError, match="not alone on its line"):
        run(templates, "text <!-- agent:summary -->")


def test_comments_of_the_template_are_removed_but_agent_markers_are_not(templates):
    text = "<!--\nnotes\nfor editors\n-->\n\n# Title\n\nx <!-- inline --> y\n<!-- agent:summary -->\n"
    assert run(templates, text) == "# Title\n\nx  y\n<!-- agent:summary -->"


def test_what_a_value_or_a_block_inserts_is_never_read_as_a_marker(templates):
    scope = Scope(
        values={"a.b": "{{ c }} <!-- agent:summary -->", "c": "TWO"},
        blocks={"list:x": lambda: "- {{ c }}"},
    )
    assert run(templates, "{{ a.b }}\n{{ list:x }}", scope) == "{{ c }} <!-- agent:summary -->\n- {{ c }}"


def test_items_are_rendered_once_per_element_with_their_own_scope(templates):
    templates("test-case.md", "<!-- note -->\n\n### {{ t.id }}\n\n{{ list:steps }}", "items")
    items = [Scope(values={"t.id": f"TC-00{n}"}, blocks={"list:steps": lambda n=n: f"step {n}"}) for n in (1, 2)]
    scope = Scope(values={}, items={"test_case": items})
    assert run(templates, "{{ items:test_case }}", scope) == "### TC-001\n\nstep 1\n\n### TC-002\n\nstep 2"


def test_an_item_template_cannot_contain_items(templates):
    templates("test-case.md", "{{ items:test_case }}", "items")
    scope = Scope(values={}, items={"test_case": [Scope(values={}, items={"test_case": []})]})
    with pytest.raises(ReportError, match="cannot contain items"):
        run(templates, "{{ items:test_case }}", scope)


def test_a_missing_item_template_is_an_error(templates):
    scope = Scope(values={}, items={"test_case": [Scope(values={})]})
    with pytest.raises(ReportError, match="template items/test-case.md does not exist"):
        run(templates, "{{ items:test_case }}", scope)


def test_the_language_folder_is_looked_up_before_the_default(templates):
    templates("t.md", "default")
    templates("t.md", "translated", "es")
    assert Renderer("es", SECTIONS).render("t.md", Scope(values={})) == "translated"
    assert Renderer("fr", SECTIONS).render("t.md", Scope(values={})) == "default"


def test_the_charts_a_template_references():
    assert render.chart_references("![a](charts/outcomes.svg)\n![b](charts/criteria.svg)") == [
        "outcomes.svg",
        "criteria.svg",
    ]


def test_an_agent_section_is_marked_as_written_by_the_model():
    assert agent_block("google/gemini", "One.\n\nTwo.") == (
        "> **Agent analysis** · written by `google/gemini`, not computed.\n>\n> One.\n>\n> Two."
    )


def test_a_missing_or_empty_agent_section_is_not_provided():
    draft = "a\n<!-- agent:conclusions -->\nb\n<!-- agent:summary -->"
    text = add_agent_sections(draft, "m", {"summary": "  "})
    assert text.count("> Not provided.") == 2


def test_the_text_of_the_model_is_not_read_as_a_marker():
    draft = "<!-- agent:conclusions -->\n<!-- agent:summary -->"
    text = add_agent_sections(draft, "m", {"conclusions": "<!-- agent:summary -->\n{{ x }}", "summary": "end"})
    assert "> <!-- agent:summary -->" in text and "> {{ x }}" in text and text.endswith("> end")
