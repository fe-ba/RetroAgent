"""The session: Start and End of spec/runtime.md, and the session state the turn works with.

Start, in order: resolve the project, load the configuration, take the lock, open memory and create the session
record, recover from an interrupted session, resolve the model profile and its credential, resolve the session
versions, start the bundled MCP servers, check the context budget and state the model. Step 9 (approvals of project
extensions) is not built: project MCP servers, steering and skills are not `Must`. Step 11 (the probe of tool
calling) only chooses the JSON fallback mode, which is not built either: ``tool_calling`` is native, and a profile
that needs the fallback cannot start a session.

End stops the MCP servers, removes leftover worktrees, sets ``ended_at`` and releases the lock.

When no model is set, an interactive session asks for a profile with ``choose_profile`` (configuration.md, ``model``).
``switch_model`` is ``/model <name>``: it keeps the conversation.
"""

import dataclasses
import datetime
import ipaddress
import os
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from retroagent.config import Config, ConfigError, approvals, load_config
from retroagent.config.schema import HOSTED_PROVIDERS
from retroagent.context import budget, skills, state, system, tools
from retroagent.llm.provider import LLMProvider, Message, MissingCredential, ProviderNotice, ToolDefinition, Wait
from retroagent.mcp_client import Client
from retroagent.mcp_client.client import ServerUnavailable
from retroagent.memory import SchemaTooNew, connect, execution, sessions
from retroagent.runtime import lock, permissions
from retroagent.runtime import tools as runtime_tools
from retroagent.servers.git import changes
from retroagent.servers.test_runner import worktree

# The result limit of mcp-tools.md (Large output) until the context window of the model is known (Start step 12).
RESULT_CHAR_LIMIT = 20_000
MODEL_VARIABLE = "RETRO_MODEL"

ROLES = ("base", "candidate")

ProviderFactory = Callable[[Mapping[str, object], Callable[[Wait], None]], LLMProvider]
# Asked when no model is set: receives the names of the profiles, returns the one chosen, or None.
ChooseProfile = Callable[[list[str]], str | None]


class SessionError(Exception):
    """The session cannot start: invalid usage, invalid configuration, the lock is held. Exit code 2."""


class StartFailed(Exception):
    """The session cannot start for a reason that is not configuration: a bundled server did not start. Exit code
    1, a runtime error (runtime.md, Start step 10)."""


class UnknownRef(Exception):
    """A ref does not resolve to a commit of the project."""

    def __init__(self, ref: str):
        self.ref = ref
        super().__init__(f"{ref!r} is not a tag, branch or commit of the project")


@dataclass(frozen=True)
class Options:
    """What the command line says about the session."""

    project: str | Path | None = None  # -C; the current directory when None
    interactive: bool = True
    trust_commands: bool = False
    base: str | None = None
    candidate: str | None = None
    model: str | None = None  # -m: a model profile
    mode: str = "default"  # --mode
    language: str | None = None  # --lang


@dataclass(frozen=True)
class Version:
    ref: str
    commit: str


@dataclass
class Conversation:
    """Messages since the conversation started, and the skill whose body is in it (context-loading.md). Kept in
    memory only; the state message is never part of it."""

    messages: list[Message] = field(default_factory=list)
    loaded_skill: str | None = None
    loaded_skill_call: str | None = None  # the tool call whose result holds the body of the loaded skill

    def clear(self) -> None:
        self.messages, self.loaded_skill, self.loaded_skill_call = [], None, None


@dataclass(frozen=True)
class CommandsState:
    """The project commands as the working copy configures them now, and whether they are approved in that content
    (runtime.md, Project commands)."""

    config: Config | None  # None when the configuration cannot be read now
    approved: bool  # --trust-commands, or the stored approval covers this content
    needs_approval: bool = True  # False when no tests.command is configured: nothing runs, nothing is asked
    digest: str | None = None
    config_error: str | None = None  # the configuration cannot be read: the call is invalid_state
    approvals_error: str | None = None  # approvals.json cannot be read: the call is denied

    @property
    def ready(self) -> bool:
        """Whether a run may go on without asking for an approval."""
        return self.approved or not self.needs_approval


@dataclass
class Usage:
    """Model calls and tokens of the session (llm-providers.md, Usage). Not stored in project memory."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Session:
    def __init__(self, project_dir: Path, config: Config, options: Options, held: lock.Lock):
        self.project_dir, self.config = project_dir, config
        self.interactive, self.trust_commands = options.interactive, options.trust_commands
        self.mode = options.mode
        self._lock = held
        self.conn: sqlite3.Connection | None = None
        self.id: int | None = None
        self.recovered_runs: list[str] = []
        self.warnings: list[str] = list(config.warnings)  # shown by the CLI after start
        # Model (Start step 7)
        self.profile_name: str | None = None
        self.profile: Mapping[str, object] | None = None
        self.model: str | None = None  # <provider>/<model name>
        self.provider: LLMProvider | None = None
        self.statement: str | None = None  # Start step 13
        # MCP servers (Start step 10) and the context (Start step 12)
        self.client: Client | None = None
        self.skills = skills.discover([skills.bundled_location()])
        self.steering = system.bundled_steering()
        self.budget: budget.Budget | None = None
        # Session state of runtime.md, kept in memory for the duration of the session.
        self.grants: set[str] = set()
        self.conversation = Conversation()
        self.calibration = budget.Calibration()
        self.usage = Usage()
        self.warned_no_usage = False
        # Tool calls refused by the mode, a permission or the approval of the project commands: exit code 4 and the
        # field denied of non-interactive mode (cli.md, Exit codes).
        self.permission_refusals = 0
        self.listener: Callable[[object], None] | None = None  # set by the turn; receives the waits of the adapter
        self.provider_factory: ProviderFactory | None = None

    def versions(self) -> dict[str, Version | None]:
        """The session versions, as written in the session record."""
        row = sessions.get_session(self.conn, self.id)
        return {
            role: Version(row[f"{role}_ref"], row[f"{role}_commit"]) if row[f"{role}_ref"] is not None else None
            for role in ROLES
        }

    # The context of a call (context-loading.md) ---------------------------------------------------------------------

    def system_context(self) -> str:
        """The system context, with ``RETRO.md`` read now: the turn calls this once, at its start."""
        retro_md = self.project_dir / "RETRO.md"
        text = retro_md.read_text(encoding="utf-8", errors="replace") if retro_md.is_file() else None
        return system.system_context(
            steering=self.steering, project_text=text, skills_index=skills.skills_index(self.skills)
        )

    def servers(self) -> dict[str, tuple[ToolDefinition, ...]]:
        """The tools of every server, ``runtime`` included, with bare names."""
        return {"runtime": runtime_tools.DEFINITIONS, **(self.client.tools() if self.client else {})}

    def known_tools(self) -> set[str]:
        """The exposed name of every existing tool, including those never offered to the model."""
        return {tools.exposed_name(server, tool.name) for server, defined in self.servers().items() for tool in defined}

    def definitions(self, tool_set: str | None = None, mode: str | None = None) -> tuple[ToolDefinition, ...]:
        return tools.tool_definitions(self.servers(), mode=mode or self.mode, tool_set=tool_set)

    def permissions(self) -> dict[str, str]:
        return permissions.effective(self.config, self.grants)

    def commands_state(self) -> CommandsState:
        """The project commands read again from the working copy, and whether they are approved: before every
        ``run_tests`` the runtime checks the content that the run will read (runtime.md, Project commands)."""
        try:
            config = load_config(self.project_dir)
        except ConfigError as error:
            return CommandsState(None, self.trust_commands, config_error=str(error))
        needs = bool(config["tests.command"])
        if self.trust_commands:
            return CommandsState(config, True, needs)
        digest = approvals.digest(config)
        try:
            approved = approvals.is_approved(self.project_dir, digest)
        except approvals.ApprovalsError as error:
            return CommandsState(config, False, needs, digest, approvals_error=str(error))
        return CommandsState(config, approved, needs, digest)

    def state_message(self, cycle_step: state.CycleStep | None = None) -> Message:
        versions = self.versions()
        base, candidate = versions["base"], versions["candidate"]
        session_state = state.SessionState(
            date=datetime.date.today(),
            project_name=self.config["project.name"],
            project_path=str(self.project_dir),
            base=state.Version(base.ref, base.commit) if base else None,
            candidate=state.Version(candidate.ref, candidate.commit) if candidate else None,
            mode=self.mode,
            permissions=self.permissions(),
            commands_approved=self.commands_state().approved,
            model=self.model,
            language=self.config["language"],
            cycle_step=cycle_step,
        )
        digest = state.read_digest(self.conn, base.commit if base else None, candidate.commit if candidate else None)
        return state.state_message(session_state, digest)

    def switch_model(self, name: str) -> list[str]:
        """``/model <name>``: use another model profile from now on, keeping the conversation. Returns the statement of
        the model and the warning of the budget, if any. Raises ``SessionError`` and keeps the current model when the
        profile does not exist, its credential is missing, it needs the JSON fallback, or its context window is too
        small for the fixed part of the context."""
        profile = self.config.models.get(name)
        if profile is None:
            profiles = ", ".join(sorted(self.config.models)) or "none"
            raise SessionError(f"there is no model profile {name!r} in the user configuration. Profiles: {profiles}.")
        check_credential(profile)
        provider = _make_provider(profile, self, self.provider_factory)
        capabilities = provider.capabilities()
        check_tool_calling(profile, capabilities.tool_calling)
        model = f"{profile['provider']}/{profile['name']}"
        try:
            new_budget = budget.budget(profile, capabilities)
            current = self.model
            self.model = model  # the state message names the model
            try:
                fixed = budget.fixed_characters(
                    self.system_context(), self.definitions(mode="default"), self.state_message()
                )
            finally:
                self.model = current
            warning = budget.check_start(new_budget, budget.estimate(fixed, budget.INITIAL_RATIO))
        except budget.ContextBudgetError as error:
            raise SessionError(str(error)) from error
        self.profile_name, self.profile, self.model, self.provider = name, profile, model, provider
        self.budget, self.calibration = new_budget, budget.Calibration()
        sessions.set_model(self.conn, self.id, model)
        sessions.set_result_limit(self.conn, self.id, budget.result_limit(new_budget))
        self.statement = statement(profile)
        return [self.statement, *([warning] if warning else [])]

    def on_wait(self, wait: Wait) -> None:
        """A wait of the provider adapter (a retry or pacing), reported to the listener of the current turn."""
        if self.listener is not None:
            self.listener(wait)

    def on_notice(self, notice: ProviderNotice) -> None:
        """A line logged by the provider library, reported to the listener of the current turn."""
        if self.listener is not None:
            self.listener(notice)

    # End ----------------------------------------------------------------------------------------------------------

    def end(self) -> None:
        """End steps 1 to 4. Safe to call more than once and after a partial start."""
        try:
            try:
                if self.client is not None:
                    self.client.stop()
                    self.client = None
            finally:
                worktree.remove_leftovers(self.project_dir)
                if self.conn is not None:
                    if self.id is not None:
                        sessions.end_session(self.conn, self.id)
                    self.conn.close()
                    self.conn = None
        finally:
            self._lock.release()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.end()


def start(
    options: Options,
    *,
    provider_factory: ProviderFactory | None = None,
    choose_profile: ChooseProfile | None = None,
) -> Session:
    """Start a session. Raises ``SessionError`` for every condition of exit code 2 and ``StartFailed`` when a bundled
    server does not start.

    ``provider_factory(profile, on_wait)`` builds the provider of the model profile; the default is
    ``LiteLLMProvider``. Tests pass one that returns a ``FakeProvider``. ``choose_profile`` is asked when no model is
    set; without it, that is an error.
    """
    if options.mode not in tools.MODES:
        raise SessionError(f"unknown mode {options.mode!r}; use one of {', '.join(tools.MODES)}")
    project_dir = project_top_level(Path(options.project) if options.project is not None else Path.cwd())
    (project_dir / ".retro").mkdir(exist_ok=True)
    try:
        config = load_config(project_dir)
    except ConfigError as error:
        raise SessionError(str(error)) from error
    if options.language:
        config = dataclasses.replace(config, values={**config.values, "language": options.language})
    profile_name, profile = resolve_profile(config, options, choose_profile)
    try:
        held = lock.acquire(project_dir / ".retro" / "retro.lock")
    except lock.LockHeld as error:
        raise SessionError(str(error)) from error
    # Nothing of project memory is read or written before the lock is held.
    session = Session(project_dir, config, options, held)
    session.profile_name, session.profile = profile_name, profile
    session.provider_factory = provider_factory
    session.model = f"{profile['provider']}/{profile['name']}"
    try:
        try:
            session.conn = connect(project_dir)
        except SchemaTooNew as error:
            raise SessionError(str(error)) from error
        session.id = sessions.start_session(
            session.conn,
            model=session.model,
            interactive=options.interactive,
            result_char_limit=RESULT_CHAR_LIMIT,
        )
        session.recovered_runs = recover(session.conn, project_dir, session.id)
        # 7. The model profile and its credential.
        check_credential(profile)
        session.provider = _make_provider(profile, session, provider_factory)
        capabilities = session.provider.capabilities()
        check_tool_calling(profile, capabilities.tool_calling)
        # 8. The session versions.
        refs = {
            "base": options.base or config["versions.base"],
            "candidate": options.candidate or config["versions.candidate"],
        }
        try:
            set_versions(session.conn, session.id, project_dir, **refs)
        except UnknownRef as error:
            raise SessionError(str(error)) from error
        # 10. The bundled MCP servers, with the environment of retro without model credentials.
        session.client = Client(project_dir, session.id, config.credential_env_names)
        try:
            session.client.start()
        except ServerUnavailable as error:
            raise StartFailed(str(error)) from error
        # 12. The context budget.
        try:
            session.budget = budget.budget(profile, capabilities)
            fixed = budget.fixed_characters(
                session.system_context(), session.definitions(mode="default"), session.state_message()
            )
            warning = budget.check_start(session.budget, budget.estimate(fixed, budget.INITIAL_RATIO))
        except budget.ContextBudgetError as error:
            raise SessionError(str(error)) from error
        if warning:
            session.warnings.append(warning)
        sessions.set_result_limit(session.conn, session.id, budget.result_limit(session.budget))
        # 13. The model in use, and whether it is hosted or local.
        session.statement = statement(profile)
    except BaseException:
        session.end()
        raise
    return session


def resolve_profile(
    config: Config, options: Options, choose: ChooseProfile | None = None
) -> tuple[str, Mapping[str, object]]:
    """Start step 7, without the credential: ``-m``, then ``RETRO_MODEL``, then ``model`` (configuration.md). When
    none is set, ``choose`` asks the user among the profiles of the user configuration."""
    name = options.model or os.environ.get(MODEL_VARIABLE) or config["model"]
    profiles = ", ".join(sorted(config.models)) or "none"
    if not name and choose is not None:
        if not config.models:
            raise SessionError(
                "no model is set and the user configuration defines no model profile: add one under models in"
                " ~/.retro/config.yaml (docs/how-to/configure-models.md)"
            )
        name = choose(sorted(config.models))
        if not name:
            raise SessionError("no model was chosen")
    if not name:
        raise SessionError(
            f"no model is set: use -m <profile>, {MODEL_VARIABLE} or the key model. Profiles of the user"
            f" configuration: {profiles}."
        )
    if name not in config.models:
        raise SessionError(f"there is no model profile {name!r} in the user configuration. Profiles: {profiles}.")
    return name, config.models[name]


def check_credential(profile: Mapping[str, object]) -> None:
    """A profile whose variable is not set stops the session, naming the variable but not its value."""
    variable = profile["api_key_env"]
    if variable and not os.environ.get(variable):
        raise SessionError(str(MissingCredential(variable)))


def check_tool_calling(profile: Mapping[str, object], supported: bool | None) -> None:
    """Tool calls are native in this build: the JSON fallback mode (NFR-17) is not built."""
    if profile["tool_calling"] == "json" or (profile["tool_calling"] == "auto" and supported is False):
        raise SessionError(
            f"the model {profile['name']} needs the JSON fallback mode for tool calling, which is not available in"
            " this build; use a model that supports tool calling, with tool_calling native or auto"
        )


def _make_provider(profile, session: "Session", factory: ProviderFactory | None) -> LLMProvider:
    """The provider of a profile; its waits and notices go to the listener of the session's current turn."""
    if factory is not None:
        return factory(profile, session.on_wait)
    from retroagent.llm.litellm_provider import LiteLLMProvider  # loads LiteLLM only when a session needs it

    return LiteLLMProvider(profile, on_wait=session.on_wait, on_notice=session.on_notice)


def is_local(profile: Mapping[str, object]) -> bool:
    """``ollama`` is local; an ``openai_compatible`` server is local when its address is a loopback address."""
    if profile["provider"] == "ollama":
        return True
    if profile["provider"] in HOSTED_PROVIDERS:
        return False
    host = urlsplit(profile["base_url"] or "").hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def statement(profile: Mapping[str, object]) -> str:
    """Start step 13 (llm-providers.md, Privacy)."""
    model = f"{profile['provider']}/{profile['name']}"
    if is_local(profile):
        return f"Model: {model}, local: the context of each call stays on this machine."
    return f"Model: {model}, hosted: the context of each call is sent to the provider."


def project_top_level(path: Path) -> Path:
    """Start step 2: the target project must be the top level of a git repository."""
    path = path.resolve()
    if not path.is_dir():
        raise SessionError(f"{path} is not a directory")
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise SessionError(f"{path} is not a git repository")
    top = Path(result.stdout.strip()).resolve()
    if top != path:
        raise SessionError(f"{path} is not the top level of its git repository; use {top}")
    return path


def recover(conn: sqlite3.Connection, project_dir: Path, session_id: int) -> list[str]:
    """Start step 6: runs left ``running`` become ``interrupted``; leftover worktrees are removed."""
    interrupted = []
    for run in execution.running_runs(conn):
        message = f"session: the session that started the run ended before it; recovered by session {session_id}"
        execution.finish_run(conn, run["id"], status="interrupted", error=message)
        interrupted.append(run["id"])
    worktree.remove_leftovers(project_dir)
    return interrupted


def set_versions(
    conn: sqlite3.Connection, session_id: int, project_dir: Path, *, base: str | None, candidate: str | None
) -> dict[str, Version | None]:
    """Resolve each ref to its commit and write both to the session record. A ref left None stays unset.

    Every ref is resolved before anything is written: an ``UnknownRef`` leaves the record unchanged.
    """
    versions = {
        role: Version(ref, resolve_commit(project_dir, ref)) if ref is not None else None
        for role, ref in (("base", base), ("candidate", candidate))
    }
    sessions.set_versions(
        conn,
        session_id,
        base_ref=versions["base"].ref if versions["base"] else None,
        base_commit=versions["base"].commit if versions["base"] else None,
        candidate_ref=versions["candidate"].ref if versions["candidate"] else None,
        candidate_commit=versions["candidate"].commit if versions["candidate"] else None,
    )
    return versions


def resolve_commit(project_dir: Path, ref: str) -> str:
    """The full commit hash of a tag, a branch or a commit. Raises ``UnknownRef``."""
    commit = changes.resolve(project_dir, ref)
    if commit is None:
        raise UnknownRef(ref)
    return commit


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False
    )
