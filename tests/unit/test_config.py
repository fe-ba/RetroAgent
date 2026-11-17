"""Configuration: levels, precedence, restricted keys and validation (configuration.md)."""

import hashlib
from importlib.resources import files
from pathlib import Path

import pytest

from retroagent.config import ConfigError, cache_dir, load_config, project_id, retro_home, worktrees_dir
from retroagent.metrics.criteria import OpenDefectLimits, Thresholds


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("RETRO_HOME", str(path))
    return path


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "shop"
    (path / ".retro").mkdir(parents=True)
    return path


def user_config(home: Path, text: str) -> None:
    (home / "config.yaml").write_text(text, encoding="utf-8")


def project_config(project: Path, text: str) -> None:
    (project / ".retro" / "config.yaml").write_text(text, encoding="utf-8")


def test_defaults_without_files(home, project):
    config = load_config(project)
    assert config["tests.command"] is None
    assert config["tests.junit"] == "{junit}"
    assert config["tests.select_separator"] == " or "
    assert config["tests.env"] == {}
    assert config["tests.timeout"] == 900
    assert config["tests.reruns"] == 2
    assert config["tests.generated_dir"] == "tests/retro"
    assert config["service.url"] == "http://127.0.0.1:{port}"
    assert config["service.ready_path"] == "/"
    assert config["service.ready_timeout"] == 30
    assert config["project.name"] == "shop"
    assert config["project.source"] == ["."]
    assert config["project.requirements"] is None
    assert config["versions.base"] is None
    assert config["permissions.run_tests"] == "ask"
    assert config.thresholds() == Thresholds()
    assert config.models == {}
    assert config.credential_env_names == ()


def test_project_overrides_user_and_user_overrides_defaults(home, project):
    user_config(home, "tests:\n  timeout: 600\n  reruns: 1\nexit_criteria:\n  min_pass_rate: 0.8\n")
    project_config(project, "tests:\n  timeout: 300\nexit_criteria:\n  min_pass_rate: 0.9\n")
    config = load_config(project)
    assert config["tests.timeout"] == 300  # project over user
    assert config["tests.reruns"] == 1  # user over default
    assert config["exit_criteria.min_pass_rate"] == 0.9
    assert config["exit_criteria.max_flaky_rate"] == 0.05  # default


def test_maps_merge_key_by_key_and_lists_are_replaced(home, project):
    user_config(home, "exit_criteria:\n  max_open_defects:\n    critical: 1\n    medium: 3\n")
    project_config(
        project,
        "project:\n  source: [src, lib]\nexit_criteria:\n  max_open_defects:\n    high: 2\n",
    )
    config = load_config(project)
    assert config.thresholds().max_open_defects == OpenDefectLimits(critical=1, high=2, medium=3)
    assert config["project.source"] == ["src", "lib"]


def test_null_removes_a_limit_set_by_a_lower_level(home, project):
    user_config(home, "exit_criteria:\n  max_open_defects:\n    medium: 3\n")
    project_config(project, "exit_criteria:\n  max_open_defects:\n    medium: null\n")
    assert load_config(project)["exit_criteria.max_open_defects.medium"] is None


@pytest.mark.parametrize(
    ("user", "project_value", "effective"),
    [("allow", "ask", "ask"), ("allow", "deny", "deny"), ("ask", "deny", "deny"), (None, "deny", "deny")],
)
def test_a_stricter_project_permission_applies(home, project, user, project_value, effective):
    if user is not None:
        user_config(home, f"permissions:\n  run_tests: {user}\n")
    project_config(project, f"permissions:\n  run_tests: {project_value}\n")
    config = load_config(project)
    assert config["permissions.run_tests"] == effective
    assert config.warnings == ()


@pytest.mark.parametrize(
    ("user", "project_value", "kept", "source"),
    [("ask", "allow", "ask", "user-level"), ("deny", "ask", "deny", "user-level"), (None, "allow", "ask", "default")],
)
def test_a_looser_project_permission_is_ignored_with_a_warning(home, project, user, project_value, kept, source):
    if user is not None:
        user_config(home, f"permissions:\n  write_tests: {user}\n")
    project_config(project, f"permissions:\n  write_tests: {project_value}\n  run_tests: deny\n")
    config = load_config(project)
    assert config["permissions.write_tests"] == kept
    assert config["permissions.run_tests"] == "deny"  # the stricter key of the same file still applies
    (warning,) = config.warnings
    assert "permissions.write_tests" in warning
    assert f"the {source} value {kept} is kept" in warning


@pytest.mark.parametrize("value", ["allow", "ask", "deny"])
def test_an_equal_project_permission_is_silent(home, project, value):
    user_config(home, f"permissions:\n  start_service: {value}\n")
    project_config(project, f"permissions:\n  start_service: {value}\n")
    config = load_config(project)
    assert config["permissions.start_service"] == value
    assert config.warnings == ()


def test_the_user_level_may_loosen_a_permission(home, project):
    user_config(home, "permissions:\n  run_tests: allow\n")
    config = load_config(project)
    assert config["permissions.run_tests"] == "allow"
    assert config.warnings == ()


@pytest.mark.parametrize(
    ("level", "text", "key"),
    [
        ("project", "models:\n  local:\n    provider: ollama\n    name: m\n", "models"),
        ("user", "tests:\n  command: pytest\n", "tests.command"),
        ("user", "service:\n  start: ./serve\n", "service.start"),
        ("user", "tests:\n  env:\n    A: b\n", "tests.env"),
        ("user", "project:\n  name: other\n", "project.name"),
        ("user", "versions:\n  base: v1.0\n", "versions.base"),
    ],
)
def test_restricted_keys_at_the_wrong_level_are_errors(home, project, level, text, key):
    (user_config if level == "user" else project_config)(home if level == "user" else project, text)
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert (raised.value.level, raised.value.key) == (level, key)
    assert level in str(raised.value) and key in str(raised.value)


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("tests:\n  comand: pytest\n", "tests.comand"),
        ("unknown: 1\n", "unknown"),
        ("exit_criteria:\n  max_open_defects:\n    low: 1\n", "exit_criteria.max_open_defects.low"),
        ("tests.command: pytest\n", "tests.command"),  # keys are nested, never dotted
        ("permissions:\n  run_tests: ask\n  mode: auto\n", "permissions.mode"),  # the mode is not a key
    ],
)
def test_unknown_keys_are_errors_with_their_level(home, project, text, key):
    project_config(project, text)
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert (raised.value.level, raised.value.key) == ("project", key)


def test_every_documented_key_is_accepted(home, project):
    user_config(
        home,
        """
model: local
language: en
agent:
  max_iterations: 20
permissions:
  run_tests: allow
reports:
  default_format: pdf
models:
  local:
    provider: ollama
    name: qwen
    base_url: http://localhost:11434
    context_window: 32768
    thinking: "off"
  hosted:
    provider: google
    name: gemini
    api_key_env: MY_GEMINI_KEY
    requests_per_minute: 12
""",
    )
    project_config(project, "model: hosted\npermissions:\n  write_tests: deny\n")
    config = load_config(project)
    assert config["model"] == "hosted"
    assert config["permissions.run_tests"] == "allow"
    assert config["reports.default_format"] == "pdf"
    assert config.models["local"]["tool_calling"] == "auto"
    assert config.models["hosted"]["timeout"] == 120


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("tests:\n  timeout: ten\n", "tests.timeout"),
        ("tests:\n  timeout: 0\n", "tests.timeout"),
        ("tests:\n  reruns: true\n", "tests.reruns"),
        ("tests:\n  command: [pytest]\n", "tests.command"),
        ("tests:\n  env: [A]\n", "tests.env"),
        ("tests:\n  env:\n    A: [1]\n", "tests.env"),
        ("tests:\n  junit: /tmp/junit.xml\n", "tests.junit"),
        ("tests:\n  junit: ../junit.xml\n", "tests.junit"),
        ("tests:\n  junit: reports/../../junit.xml\n", "tests.junit"),
        ("tests:\n  junit: '{worktree}/junit.xml'\n", "tests.junit"),
        ("tests:\n  generated_dir: /tmp/retro\n", "tests.generated_dir"),
        ("tests:\n  generated_dir: ../retro\n", "tests.generated_dir"),
        ("tests:\n  generated_dir: 'C:\\\\retro'\n", "tests.generated_dir"),
        ("service:\n  url: 'http://example.com:{port}'\n", "service.url"),
        ("service:\n  url: 'http://10.0.0.1:{port}'\n", "service.url"),
        ("service:\n  url: 'ftp://localhost:{port}'\n", "service.url"),
        ("exit_criteria:\n  min_pass_rate: 1.5\n", "exit_criteria.min_pass_rate"),
        ("exit_criteria:\n  max_flaky_rate: -0.1\n", "exit_criteria.max_flaky_rate"),
        ("exit_criteria:\n  max_new_failures: 0.5\n", "exit_criteria.max_new_failures"),
        ("exit_criteria:\n  max_open_defects:\n    critical: null\n", "exit_criteria.max_open_defects.critical"),
        ("permissions:\n  run_tests: always\n", "permissions.run_tests"),
        ("project:\n  source: src\n", "project.source"),
        ("tests: pytest\n", "tests"),
    ],
)
def test_invalid_values_are_errors(home, project, text, key):
    project_config(project, text)
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert raised.value.key == key


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("models:\n  local:\n    provider: ollama\n    name: m\n", "models.local.base_url"),
        ("models:\n  x:\n    provider: acme\n    name: m\n", "models.x.provider"),
        ("models:\n  x:\n    name: m\n", "models.x.provider"),
        ("models:\n  x:\n    provider: openai\n    name: m\n    key: secret\n", "models.x.key"),
        ("models:\n  x:\n    provider: google\n    name: m\n", "models.x.api_key_env"),
        ("models:\n  x:\n    provider: anthropic\n    name: m\n", "models.x.api_key_env"),
        (
            "models:\n  x:\n    provider: ollama\n    name: m\n    base_url: http://localhost:11434\n"
            "    context_window: 32768\n    api_key_env: OLLAMA_TOKEN\n",
            "models.x.api_key_env",
        ),
    ],
)
def test_invalid_model_profiles_are_errors(home, project, text, key):
    user_config(home, text)
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert (raised.value.level, raised.value.key) == ("user", key)


LOCAL_PROFILE = "models:\n  local:\n    provider: ollama\n    name: m\n    base_url: http://localhost:11434\n"


@pytest.mark.parametrize(
    ("written", "value"),
    [
        ("off", "off"),  # YAML reads it as the boolean false
        ("on", "on"),  # and this one as true
        ("Off", "off"),
        ("false", "off"),
        ("true", "on"),
        ('"off"', "off"),  # quoted: a string
        ("'on'", "on"),
        ("default", "default"),
    ],
)
def test_thinking_accepts_the_unquoted_and_the_quoted_forms(home, project, written, value):
    user_config(home, f"{LOCAL_PROFILE}    context_window: 32768\n    thinking: {written}\n")
    assert load_config(project).models["local"]["thinking"] == value


@pytest.mark.parametrize("written", ["maybe", "1", "null", "[off]"])
def test_thinking_still_refuses_other_values(home, project, written):
    user_config(home, f"{LOCAL_PROFILE}    context_window: 32768\n    thinking: {written}\n")
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert (raised.value.level, raised.value.key) == ("user", "models.local.thinking")


@pytest.mark.parametrize("written", ["off", "true"])
def test_a_boolean_is_accepted_only_for_thinking(home, project, written):
    user_config(home, f"{LOCAL_PROFILE}    context_window: 32768\n    tool_calling: {written}\n")
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert raised.value.key == "models.local.tool_calling"


def test_valid_paths_and_urls(home, project):
    project_config(
        project,
        "tests:\n  junit: target/surefire-reports/*.xml\n  generated_dir: src/test/retro\n"
        "service:\n  url: 'http://localhost:{port}/api'\n",
    )
    config = load_config(project)
    assert config["tests.junit"] == "target/surefire-reports/*.xml"
    assert config["service.url"] == "http://localhost:{port}/api"


def test_invalid_yaml_is_an_error_of_its_level(home, project):
    project_config(project, "tests: [unclosed\n")
    with pytest.raises(ConfigError) as raised:
        load_config(project)
    assert raised.value.level == "project"


def test_empty_files_and_sections_are_allowed(home, project):
    user_config(home, "")
    project_config(project, "tests:\n")
    assert load_config(project)["tests.timeout"] == 900


def test_retro_home_changes_the_user_level(home, project, monkeypatch):
    other = home.parent / "other-home"
    other.mkdir()
    (other / "config.yaml").write_text("tests:\n  reruns: 5\n", encoding="utf-8")
    user_config(home, "tests:\n  reruns: 1\n")
    assert retro_home() == home
    assert load_config(project)["tests.reruns"] == 1
    monkeypatch.setenv("RETRO_HOME", str(other))
    assert load_config(project)["tests.reruns"] == 5


def test_project_id_and_user_level_directories(home, project):
    digest = hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()[:12]
    assert project_id(project) == f"shop-{digest}"
    assert worktrees_dir(project) == home / "worktrees" / f"shop-{digest}"
    assert cache_dir(project) == home / "cache" / f"shop-{digest}"
    assert project_id(project.parent / "other" / ".." / "shop") == project_id(project)


def test_credential_names_come_from_every_profile(home, project):
    user_config(
        home,
        "models:\n"
        "  a:\n    provider: anthropic\n    name: m\n    api_key_env: KEY_A\n"
        "  b:\n    provider: openai\n    name: m\n    api_key_env: KEY_B\n"
        "  c:\n    provider: openai\n    name: m\n    api_key_env: KEY_A\n"
        "  d:\n    provider: openai_compatible\n    name: m\n"
        "    base_url: http://localhost:1\n    context_window: 8192\n",
    )
    assert load_config(project).credential_env_names == ("KEY_A", "KEY_B")


def test_example_config_loads(home, project):
    example = files("retroagent.resources") / "examples/shop-api/versions/v1.1/.retro/config.yaml"
    project_config(project, example.read_text(encoding="utf-8"))
    config = load_config(project)
    assert config["project.name"] == "shop-api"
    assert config["exit_criteria.min_pass_rate"] == 0.90
    assert config["tests.reruns"] == 2
    assert config["service.ready_path"] == "/health"
    assert "{cache_dir}" in config["tests.setup"]
    assert config.thresholds() == Thresholds(min_pass_rate=0.90)
