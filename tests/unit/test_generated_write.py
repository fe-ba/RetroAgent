"""Where ``test_runner.write_test`` writes a generated test, and the form of its name (mcp-tools.md,
``test_runner.write_test``): a path that leaves ``.retro/tests/``, by ``..`` or by a symbolic link, is refused
before anything is written."""

import pytest

from retroagent.servers.test_runner import generated
from retroagent.servers.test_runner.generated import GeneratedError


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "shop"
    (path / ".retro" / "tests").mkdir(parents=True)
    return path


def files_under(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


@pytest.mark.parametrize(
    ("file", "normalized"),
    [
        ("test_a.py", "test_a.py"),
        ("cart/test_a.py", "cart/test_a.py"),
        ("./cart//test_a.py", "cart/test_a.py"),
        ("cart/../test_a.py", "test_a.py"),
    ],
)
def test_a_relative_path_inside_is_normalized(project, file, normalized):
    assert generated.normalize_file(file) == normalized
    assert generated.target(project, file) == project / ".retro" / "tests" / normalized


@pytest.mark.parametrize(
    "file",
    ["", "  ", ".", "..", "../test_a.py", "cart/../../test_a.py", "/tmp/test_a.py", "../../../.bashrc", "a\\b.py"],
)
def test_a_path_that_leaves_retro_tests_is_refused_and_nothing_is_written(project, file):
    before = files_under(project.parent)
    with pytest.raises(GeneratedError):
        generated.target(project, file)
    assert files_under(project.parent) == before


def test_a_symbolic_link_to_a_directory_outside_is_refused(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".retro" / "tests" / "cart").symlink_to(outside, target_is_directory=True)
    with pytest.raises(GeneratedError, match="cart is a symbolic link"):
        generated.target(project, "cart/test_a.py")
    assert list(outside.iterdir()) == []


def test_a_symbolic_link_as_the_file_is_refused_even_when_it_points_inside(project, tmp_path):
    tests = project / ".retro" / "tests"
    (tests / "test_other.py").write_text("x = 1\n", encoding="utf-8")
    (tests / "test_a.py").symlink_to(tests / "test_other.py")
    (tmp_path / "secret").write_text("keep\n", encoding="utf-8")
    (tests / "test_b.py").symlink_to(tmp_path / "secret")
    for file in ("test_a.py", "test_b.py"):
        with pytest.raises(GeneratedError, match="symbolic link"):
            generated.target(project, file)
    assert (tests / "test_other.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (tmp_path / "secret").read_text(encoding="utf-8") == "keep\n"


def test_a_symbolic_link_as_retro_tests_is_refused(tmp_path):
    project = tmp_path / "shop"
    (project / ".retro").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".retro" / "tests").symlink_to(outside, target_is_directory=True)
    with pytest.raises(GeneratedError, match=r"\.retro/tests is a symbolic link"):
        generated.target(project, "test_a.py")


def test_a_directory_where_the_file_goes_is_refused(project):
    (project / ".retro" / "tests" / "test_a.py").mkdir()
    with pytest.raises(GeneratedError, match="is not a file"):
        generated.target(project, "test_a.py")


def test_write_creates_the_directories_and_leaves_no_temporary_file(project):
    path = generated.target(project, "cart/test_a.py")
    generated.write(path, "def test_a():\n    assert 1 + 1 == 2\n")
    assert path.read_text(encoding="utf-8") == "def test_a():\n    assert 1 + 1 == 2\n"
    assert files_under(project / ".retro" / "tests") == ["cart", "cart/test_a.py"]


@pytest.mark.parametrize(
    ("name", "requirements"),
    [
        ("test_req_002_quantity_above_stock_is_rejected", ["REQ-002"]),
        ("test_req_004_two_coupons", ["REQ-002", "REQ-004"]),  # any traced requirement
        ("test_cart_total", []),
        ("adds_an_item", []),
    ],
)
def test_accepted_test_names(name, requirements):
    generated.check_test_name(name, requirements)


@pytest.mark.parametrize(
    ("name", "requirements", "message"),
    [
        ("test_cart_total", ["REQ-002"], "must follow test_req_002_<description>"),
        ("test_req_2_cart", ["REQ-002"], "must follow"),
        ("test_req_003_cart", ["REQ-002"], "must follow"),
        ("test_req_002_", ["REQ-002"], "must follow"),
        ("test_req_002_a b", ["REQ-002"], "without whitespace"),
        ("test_a::b", [], "'::'"),
        ("test_total[1]", [], "'['"),
        ("", [], "function name"),
    ],
)
def test_refused_test_names(name, requirements, message):
    with pytest.raises(GeneratedError, match=message.replace("[", r"\[")):
        generated.check_test_name(name, requirements)
