"""Start and End of a session on a small repository (runtime.md, Session lifecycle). No test is executed here."""

import subprocess

import pytest
from fixtures.agent_session import write_user_config
from fixtures.mcp_project import children

from retroagent.llm import Capabilities, FakeProvider
from retroagent.memory import connect, sessions
from retroagent.runtime import lock, session
from retroagent.runtime.session import Options, SessionError, Version


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "home"))
    write_user_config(tmp_path / "home")
    path = tmp_path / "project"
    path.mkdir()
    git(path, "init", "--quiet", "--initial-branch=main")
    for number in (1, 2):
        (path / "version.txt").write_text(f"{number}\n")
        git(path, "add", ".")
        git(path, "commit", "--quiet", "-m", str(number))
        git(path, "tag", f"v{number}")
    return path


def record(repo, session_id):
    conn = connect(repo)
    try:
        return dict(sessions.get_session(conn, session_id))
    finally:
        conn.close()


def test_start_creates_the_session_record_and_end_closes_it(repo):
    with session.start(Options(project=repo, interactive=False)) as started:
        assert started.project_dir == repo.resolve()
        assert (repo / ".retro" / "retro.lock").read_text().strip().isdigit()
        with pytest.raises(lock.LockHeld):
            lock.acquire(repo / ".retro" / "retro.lock")
    row = record(repo, started.id)
    assert (row["model"], row["interactive"], row["result_char_limit"]) == ("ollama/test-model", 0, 13_233)
    assert row["ended_at"] is not None
    lock.acquire(repo / ".retro" / "retro.lock").release()  # released at End


def test_versions_come_from_the_flags_then_from_the_configuration(repo):
    (repo / ".retro").mkdir()
    (repo / ".retro" / "config.yaml").write_text("versions:\n  base: v1\n  candidate: v2\n")
    commits = {tag: git(repo, "rev-parse", tag) for tag in ("v1", "v2", "main")}

    with session.start(Options(project=repo, candidate="main")) as started:
        assert started.versions() == {
            "base": Version("v1", commits["v1"]),
            "candidate": Version("main", commits["main"]),
        }
    row = record(repo, started.id)
    assert (row["base_ref"], row["base_commit"]) == ("v1", commits["v1"])
    assert (row["candidate_ref"], row["candidate_commit"]) == ("main", commits["main"])


def test_a_short_commit_hash_is_a_ref(repo):
    short = git(repo, "rev-parse", "--short", "v1")
    with session.start(Options(project=repo, base=short)) as started:
        assert started.versions()["base"] == Version(short, git(repo, "rev-parse", "v1"))


def test_versions_may_stay_unset(repo):
    with session.start(Options(project=repo)) as started:
        assert started.versions() == {"base": None, "candidate": None}


def test_a_ref_that_does_not_resolve_ends_the_session_without_writing_versions(repo):
    with pytest.raises(SessionError, match="'v9' is not a tag, branch or commit"):
        session.start(Options(project=repo, base="v1", candidate="v9"))
    row = record(repo, 1)
    assert (row["base_ref"], row["base_commit"], row["candidate_ref"]) == (None, None, None)
    assert row["ended_at"] is not None
    lock.acquire(repo / ".retro" / "retro.lock").release()


@pytest.mark.parametrize("ref", ["", "--all", "v1^{tree}"])
def test_odd_refs_do_not_resolve(repo, ref):
    with pytest.raises(session.UnknownRef):
        session.resolve_commit(repo, ref)


def test_the_data_layer_writes_a_ref_only_with_its_commit(repo):
    with session.start(Options(project=repo)) as started:
        with pytest.raises(ValueError):
            sessions.set_versions(
                started.conn, started.id, base_ref="v1", base_commit=None, candidate_ref=None, candidate_commit=None
            )


# Start steps 7, 10, 12 and 13 (runtime.md, Session lifecycle).

HOSTED = "  hosted:\n    provider: google\n    name: gemini-test\n    api_key_env: RETRO_TEST_KEY\n"


def profiles(home, text, model="local"):
    (home / "config.yaml").write_text(f"model: {model}\nmodels:\n{text}", encoding="utf-8")


def fake(capabilities=None):
    provider = FakeProvider(capabilities=capabilities) if capabilities else FakeProvider()
    return lambda profile, on_wait: provider


def test_the_model_comes_from_the_flag_then_retro_model_then_the_configuration(repo, tmp_path, monkeypatch):
    local = "    provider: ollama\n    base_url: http://127.0.0.1:9\n    context_window: 32768\n"
    profiles(tmp_path / "home", f"  one:\n    name: one\n{local}  two:\n    name: two\n{local}", model="one")
    with session.start(Options(project=repo), provider_factory=fake()) as started:
        assert started.model == "ollama/one"
    monkeypatch.setenv("RETRO_MODEL", "two")
    with session.start(Options(project=repo), provider_factory=fake()) as started:
        assert started.model == "ollama/two"
    with session.start(Options(project=repo, model="one"), provider_factory=fake()) as started:
        assert started.model == "ollama/one"
    assert record(repo, started.id)["model"] == "ollama/one"


def test_no_model_is_a_usage_error_that_lists_the_profiles(repo, tmp_path):
    (tmp_path / "home" / "config.yaml").write_text(
        "models:\n  local:\n    provider: ollama\n    name: m\n    base_url: http://127.0.0.1:9\n"
        "    context_window: 32768\n"
    )
    with pytest.raises(SessionError, match=r"no model is set.*Profiles of the user configuration: local\."):
        session.start(Options(project=repo))


def test_an_unknown_profile_is_a_usage_error(repo):
    with pytest.raises(SessionError, match="there is no model profile 'nope'"):
        session.start(Options(project=repo, model="nope"))


def test_a_missing_credential_names_the_variable_and_ends_the_session(repo, tmp_path, monkeypatch):
    monkeypatch.delenv("RETRO_TEST_KEY", raising=False)
    profiles(tmp_path / "home", HOSTED, model="hosted")
    with pytest.raises(SessionError, match="RETRO_TEST_KEY"):
        session.start(Options(project=repo), provider_factory=fake())
    assert record(repo, 1)["ended_at"] is not None
    lock.acquire(repo / ".retro" / "retro.lock").release()


def test_a_window_that_no_one_knows_is_a_usage_error(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_TEST_KEY", "value")
    profiles(tmp_path / "home", HOSTED, model="hosted")
    unknown = Capabilities(tool_calling=True, context_window=None)
    with pytest.raises(SessionError, match="context window of the model is unknown"):
        session.start(Options(project=repo), provider_factory=fake(unknown))


def test_the_window_reported_by_the_provider_is_used_when_the_profile_has_none(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_TEST_KEY", "value")
    profiles(tmp_path / "home", HOSTED, model="hosted")
    reported = Capabilities(tool_calling=True, context_window=1_000_000)
    with session.start(Options(project=repo), provider_factory=fake(reported)) as started:
        assert started.budget.window == 1_000_000
        assert (
            started.statement == "Model: google/gemini-test, hosted: the context of each call is sent to the provider."
        )
    assert record(repo, started.id)["result_char_limit"] == 20_000


def test_a_window_too_small_for_the_fixed_part_is_a_usage_error(repo, tmp_path):
    write_user_config(tmp_path / "home", "    max_output_tokens: 4096\n")
    (tmp_path / "home" / "config.yaml").write_text(
        (tmp_path / "home" / "config.yaml").read_text().replace("context_window: 32768", "context_window: 8000")
    )
    with pytest.raises(SessionError, match="too small for RetroAgent"):
        session.start(Options(project=repo), provider_factory=fake())


@pytest.mark.parametrize(
    ("setting", "capability"), [("    tool_calling: json\n", True), ("    tool_calling: auto\n", False)]
)
def test_a_model_that_needs_the_json_fallback_cannot_start_a_session(repo, tmp_path, setting, capability):
    write_user_config(tmp_path / "home", setting)
    provider = fake(Capabilities(tool_calling=capability, context_window=None))
    with pytest.raises(SessionError, match="JSON fallback mode"):
        session.start(Options(project=repo), provider_factory=provider)


def test_an_unknown_mode_is_a_usage_error(repo):
    with pytest.raises(SessionError, match="unknown mode 'fast'"):
        session.start(Options(project=repo, mode="fast"))


def test_the_bundled_servers_start_with_the_session_and_stop_at_its_end(repo):
    with session.start(Options(project=repo), provider_factory=fake()) as started:
        servers = started.client.tools()
        assert set(servers) == {"git", "memory", "test_runner"} and all(servers.values())
        assert children(b"retroagent.servers.")
    assert started.client is None
    assert not children(b"retroagent.servers.")


def test_the_session_states_a_local_model(repo):
    with session.start(Options(project=repo), provider_factory=fake()) as started:
        assert started.statement == "Model: ollama/test-model, local: the context of each call stays on this machine."


@pytest.mark.parametrize(
    ("provider", "base_url", "local"),
    [
        ("ollama", "http://192.168.1.20:11434", True),
        ("openai_compatible", "http://localhost:1234/v1", True),
        ("openai_compatible", "http://127.0.0.1:8000/v1", True),
        ("openai_compatible", "http://[::1]:8000/v1", True),
        ("openai_compatible", "https://models.example.com/v1", False),
        ("openai", None, False),
        ("google", None, False),
    ],
)
def test_hosted_or_local(provider, base_url, local):
    assert session.is_local({"provider": provider, "base_url": base_url}) is local


def test_a_looser_project_permission_is_ignored_with_a_warning_at_start(repo):
    (repo / ".retro").mkdir()
    (repo / ".retro" / "config.yaml").write_text("permissions:\n  run_tests: allow\n")
    with session.start(Options(project=repo), provider_factory=fake()) as started:
        assert started.permissions()["run_tests"] == "ask"
        # The other warning, if any, is the size of the fixed context against the window of the test profile.
        (warning,) = [w for w in started.warnings if "permissions." in w]
        assert "permissions.run_tests" in warning and "the default value ask is kept" in warning
