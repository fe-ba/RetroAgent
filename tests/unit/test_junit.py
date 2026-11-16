"""JUnit XML parsing: the only source of results (ADR-0010, project-contract.md)."""

import pytest

from retroagent.servers.test_runner.junit import JunitError, parse

PYTEST_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="5" time="0.5">
    <testcase classname="tests.test_cart" name="test_req_003_total" time="0.012" />
    <testcase classname="tests.test_tax" name="test_req_007_tax_rounds_half_up" time="0.003">
      <failure message="assert 1.05 == 1.06">def test_req_007_tax_rounds_half_up():
&gt;       assert tax(10.5) == 1.06
E       assert 1.05 == 1.06</failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_health" time="0.100">
      <error message="failed on setup with &quot;ConnectionRefusedError&quot;">fixture base_url failed</error>
    </testcase>
    <testcase classname="tests.test_orders" name="test_history" time="0.000">
      <skipped type="pytest.skip" message="needs a database">tests/test_orders.py:12: needs a database</skipped>
    </testcase>
    <testcase classname="tests.test_cart" name="test_quantity[2-3]" time="0.001" />
  </testsuite>
</testsuites>
"""


def write(tmp_path, text, name="junit.xml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_outcomes_messages_and_durations(tmp_path):
    entries = parse([write(tmp_path, PYTEST_XML)])
    assert [(e.test_id, e.outcome) for e in entries] == [
        ("tests.test_cart::test_req_003_total", "passed"),
        ("tests.test_tax::test_req_007_tax_rounds_half_up", "failed"),
        ("tests.test_api::test_health", "error"),
        ("tests.test_orders::test_history", "skipped"),
        ("tests.test_cart::test_quantity[2-3]", "passed"),
    ]
    passed, failed, error, skipped, _ = entries
    assert passed.message is None and passed.duration == 0.012
    assert failed.message.startswith("assert 1.05 == 1.06\ndef test_req_007_tax_rounds_half_up():")
    assert "E       assert 1.05 == 1.06" in failed.message
    assert error.message == 'failed on setup with "ConnectionRefusedError"\nfixture base_url failed'
    assert skipped.message == "needs a database"
    assert skipped.duration == 0.0


def test_failure_and_error_together_give_error(tmp_path):
    xml = """<testsuite name="s">
      <testcase classname="tests.test_a" name="test_x" time="0.1">
        <failure message="assert False">trace</failure>
        <error message="teardown failed">trace 2</error>
      </testcase>
    </testsuite>"""
    [entry] = parse([write(tmp_path, xml)])
    assert entry.outcome == "error"
    assert entry.message == "teardown failed\ntrace 2"


def test_duplicate_entries_the_first_counts(tmp_path):
    first = """<testsuite name="s"><testcase classname="tests.test_a" name="test_x"><failure message="m"/></testcase>
      <testcase classname="tests.test_a" name="test_y" /></testsuite>"""
    second = """<testsuite name="s"><testcase classname="tests.test_a" name="test_x" />
      <testcase classname="tests.test_b" name="test_x" /></testsuite>"""
    entries = parse([write(tmp_path, first, "a.xml"), write(tmp_path, second, "b.xml")])
    assert [(e.test_id, e.outcome) for e in entries] == [
        ("tests.test_a::test_x", "failed"),
        ("tests.test_a::test_y", "passed"),
        ("tests.test_b::test_x", "passed"),
    ]


def test_nested_suites_and_a_single_suite_root(tmp_path):
    xml = """<testsuites><testsuite name="outer"><testsuite name="inner">
      <testcase classname="com.acme.CartTest" name="totalIsSum" time="1.5" />
    </testsuite></testsuite></testsuites>"""
    [entry] = parse([write(tmp_path, xml)])
    assert entry.test_id == "com.acme.CartTest::totalIsSum" and entry.duration == 1.5


def test_implementation_uses_the_file_attribute_when_present(tmp_path):
    xml = """<testsuite name="s">
      <testcase classname="tests.test_a" name="test_x" file="tests/test_a.py" line="3" />
      <testcase classname="tests.test_a" name="test_y" />
      <testcase name="test_z" time="abc" />
    </testsuite>"""
    with_file, without_file, without_classname = parse([write(tmp_path, xml)])
    assert with_file.implementation == "tests/test_a.py::test_x"
    assert without_file.implementation == "tests.test_a::test_y"
    assert without_classname.test_id == "::test_z" and without_classname.duration is None


def test_an_empty_suite_has_no_entries(tmp_path):
    assert parse([write(tmp_path, '<testsuites name="pytest tests" />')]) == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not xml at all",
        "<testsuite><testcase name='x'>",  # truncated, as when a test command is killed
        "<html><body>report</body></html>",
        "<testsuite><testcase classname='a' /></testsuite>",  # a test case without a name
    ],
    ids=["empty", "text", "truncated", "other-root", "no-name"],
)
def test_invalid_files_raise(tmp_path, text):
    with pytest.raises(JunitError):
        parse([write(tmp_path, text)])


def test_a_missing_file_raises(tmp_path):
    with pytest.raises(JunitError, match="does not exist"):
        parse([tmp_path / "junit.xml"])


def test_no_file_at_all_raises():
    with pytest.raises(JunitError, match="no JUnit XML"):
        parse([])
