"""Identity of generated tests and the ``{names}`` rule (project-contract.md, Test identity)."""

import pytest

from retroagent.servers.test_runner.generated import (
    bind,
    copy_generated,
    load_error_file,
    module_name,
    names,
    select_name,
)
from retroagent.servers.test_runner.junit import Entry

IMPLEMENTATION = "test_req_002_quantity_above_stock_is_rejected.py::test_req_002_quantity_above_stock_is_rejected"
NAME = "test_req_002_quantity_above_stock_is_rejected"


def entry(classname, name, outcome="passed"):
    return Entry(classname=classname, name=name, file=None, outcome=outcome, message=None, duration=0.1)


def test_binds_by_name_and_classname_ending_with_the_file():
    project_test = entry("tests.test_cart", NAME)  # a project test with the same function name
    generated = entry("tests.retro.test_req_002_quantity_above_stock_is_rejected", NAME)
    assert bind([project_test, generated], IMPLEMENTATION) is generated


def test_classname_equal_to_the_file_name_binds():
    generated = entry("test_req_002_quantity_above_stock_is_rejected", NAME)
    assert bind([entry("tests.test_cart", NAME), generated], IMPLEMENTATION) is generated


def test_the_file_name_matches_only_at_a_dot_boundary():
    # "other_test_req_002_..." ends with the file name, but not as a module of its own
    lookalike = entry("tests.other_test_req_002_quantity_above_stock_is_rejected", NAME)
    assert bind([lookalike, entry("tests.test_cart", NAME)], IMPLEMENTATION) is None


def test_files_in_subdirectories_use_their_own_name():
    generated = entry("tests.retro.api.test_orders_page", "test_req_008_orders_page")
    assert bind([generated], "api/test_orders_page.py::test_req_008_orders_page") is generated


def test_binds_the_only_entry_with_the_name_whatever_its_classname():
    only = entry("RetroSuite", NAME)
    assert bind([entry("tests.test_cart", "test_other"), only], IMPLEMENTATION) is only


def test_no_binding_without_an_entry_or_with_two_candidates():
    assert bind([entry("tests.test_cart", "test_other")], IMPLEMENTATION) is None
    assert bind([entry("a.Suite", NAME), entry("b.Suite", NAME)], IMPLEMENTATION) is None


def test_select_name_removes_the_parameter_suffix():
    assert select_name("test_total[2-3]") == "test_total"
    assert select_name("test_total[a[b]]") == "test_total"
    assert select_name("test_total") == "test_total"
    assert select_name("test_odd[name") == "test_odd[name"  # not a parameter suffix


def test_names_are_unique_in_order_and_joined_with_the_separator():
    selected = ["test_b[1]", "test_a", "test_b[2]", "test_c", "test_a"]
    assert names(selected, " or ") == "test_b or test_a or test_c"
    assert names(selected, ",") == "test_b,test_a,test_c"
    assert names([], " or ") == ""


def test_copy_generated_copies_only_the_given_files(tmp_path):
    project, worktree = tmp_path / "project", tmp_path / "worktree"
    tests = project / ".retro" / "tests"
    (tests / "api").mkdir(parents=True)
    (tests / "test_a.py").write_text("def test_a(): pass\n")
    (tests / "api" / "test_b.py").write_text("def test_b(): pass\n")
    (tests / "test_retired.py").write_text("def test_retired(): pass\n")
    worktree.mkdir()

    missing = copy_generated(
        project, worktree, "tests/retro", ["test_a.py::test_a", "api/test_b.py::test_b", "test_gone.py::test_gone"]
    )

    assert missing == ["test_gone.py"]
    assert (worktree / "tests/retro/test_a.py").read_text() == "def test_a(): pass\n"
    assert (worktree / "tests/retro/api/test_b.py").is_file()
    assert not (worktree / "tests/retro/test_retired.py").exists()


def test_copy_generated_refuses_paths_outside_retro_tests(tmp_path):
    (tmp_path / ".retro" / "tests").mkdir(parents=True)
    with pytest.raises(ValueError, match="not inside"):
        copy_generated(tmp_path, tmp_path / "wt", "tests/retro", ["../config.yaml::x"])


def test_the_module_path_of_a_generated_test_in_the_worktree():
    assert module_name("tests/retro", "test_a.py") == "tests.retro.test_a"
    assert module_name("tests/retro", "tests/test_req_002_x.py") == "tests.retro.tests.test_req_002_x"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("tests.retro.tests.test_req_002_x", "tests/test_req_002_x.py"),  # rootdir at the worktree
        ("retro.tests.test_req_002_x", "tests/test_req_002_x.py"),  # a deeper rootdir
        ("tests.retro.test_b", "test_b.py"),
        ("tests.test_cart", None),  # a file of the project
        ("test_a", None),  # ends two generated files
        ("tests.retro.tests.test_req_002", None),  # a prefix is not the file
    ],
)
def test_a_load_error_is_bound_to_one_generated_file(name, expected):
    files = ["tests/test_req_002_x.py", "test_b.py", "test_a.py", "cart/test_a.py"]
    assert load_error_file(name, files, "tests/retro") == expected
