"""Every key of docs/reference/configuration.md: type, default and the levels allowed to set it."""

import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from retroagent.config.placeholders import PATTERN as PLACEHOLDER

USER, PROJECT = "user", "project"
BOTH = (USER, PROJECT)
ONLY_PROJECT = (PROJECT,)


class ConfigError(Exception):
    """An unknown key, an invalid value or a key at a level that may not set it. The CLI exits with code 2."""

    def __init__(self, level: str, key: str | None, message: str):
        self.level, self.key, self.message = level, key, message
        where = f"{level} configuration" + (f", key {key}" if key else "")
        super().__init__(f"{where}: {message}")


@dataclass(frozen=True)
class Key:
    type: str  # string, integer, number, ratio, list, map, enum
    default: object = None  # a key whose default is None also accepts null: not set, or no limit
    levels: tuple[str, ...] = BOTH
    choices: tuple[str, ...] = ()
    minimum: int | None = None


PERMISSION = ("ask", "allow", "deny")

KEYS: dict[str, Key] = {
    "model": Key("string"),
    "language": Key("string", "en"),
    "agent.max_iterations": Key("integer", 50, minimum=1),
    "project.name": Key("string", levels=ONLY_PROJECT),  # the loader sets the directory name when absent
    "project.requirements": Key("list", levels=ONLY_PROJECT),
    "project.source": Key("list", ["."], levels=ONLY_PROJECT),
    "versions.base": Key("string", levels=ONLY_PROJECT),
    "versions.candidate": Key("string", levels=ONLY_PROJECT),
    "tests.command": Key("string", levels=ONLY_PROJECT),
    "tests.junit": Key("string", "{junit}", levels=ONLY_PROJECT),
    "tests.select": Key("string", levels=ONLY_PROJECT),
    "tests.select_separator": Key("string", " or ", levels=ONLY_PROJECT),
    "tests.setup": Key("string", levels=ONLY_PROJECT),
    "tests.env": Key("map", {}, levels=ONLY_PROJECT),
    "tests.timeout": Key("integer", 900, minimum=1),
    "tests.reruns": Key("integer", 2, minimum=0),
    "tests.generated_dir": Key("string", "tests/retro", levels=ONLY_PROJECT),
    "service.start": Key("string", levels=ONLY_PROJECT),
    "service.url": Key("string", "http://127.0.0.1:{port}", levels=ONLY_PROJECT),
    "service.ready_path": Key("string", "/", levels=ONLY_PROJECT),
    "service.ready_timeout": Key("integer", 30, minimum=1),
    "exit_criteria.min_pass_rate": Key("ratio", 0.95),
    "exit_criteria.min_high_priority_executed": Key("ratio", 1.0),
    "exit_criteria.min_requirement_coverage": Key("ratio", 1.0),
    "exit_criteria.max_open_defects.critical": Key("integer", 0, minimum=0),
    "exit_criteria.max_open_defects.high": Key("integer", 0, minimum=0),
    "exit_criteria.max_open_defects.medium": Key("integer", None, minimum=0),
    "exit_criteria.max_flaky_rate": Key("ratio", 0.05),
    "exit_criteria.max_new_failures": Key("integer", 0, minimum=0),
    "permissions.run_tests": Key("enum", "ask", choices=PERMISSION),
    "permissions.write_tests": Key("enum", "ask", choices=PERMISSION),
    "permissions.start_service": Key("enum", "ask", choices=PERMISSION),
    "reports.default_format": Key("enum", "md", choices=("md", "pdf")),
}

# models.<profile>.<key>, only at user level.
PROVIDERS = ("anthropic", "openai", "xai", "google", "ollama", "openai_compatible")
HOSTED_PROVIDERS = ("anthropic", "openai", "xai", "google")
PROFILE_KEYS: dict[str, Key] = {
    "provider": Key("enum", choices=PROVIDERS),
    "name": Key("string"),
    "base_url": Key("string"),
    "api_key_env": Key("string"),
    "tool_calling": Key("enum", "auto", choices=("auto", "native", "json")),
    "temperature": Key("number", 0),
    "timeout": Key("integer", 120, minimum=1),
    "requests_per_minute": Key("integer", minimum=1),
    "max_output_tokens": Key("integer", 4096, minimum=1),
    "thinking": Key("enum", "default", choices=("default", "off", "on")),
    "context_window": Key("integer", minimum=1),
}
_REQUIRED_FOR_LOCAL = ("base_url", "context_window")  # for ollama and openai_compatible


def validate(level: str, raw: object) -> tuple[dict[str, object], dict[str, dict]]:
    """The keys set by one level, as dotted names, and the model profiles it defines."""
    if raw is None:
        return {}, {}
    if not isinstance(raw, dict):
        raise ConfigError(level, None, "the file must be a mapping of keys")
    values: dict[str, object] = {}
    models: dict[str, dict] = {}
    _walk(level, raw, "", values, models)
    return values, models


def _walk(level: str, mapping: dict, prefix: str, values: dict, models: dict) -> None:
    for name, value in mapping.items():
        key = f"{prefix}{name}"
        if not isinstance(name, str) or "." in name:
            raise ConfigError(level, key, "unknown key")
        if key == "models":
            if level != USER:
                raise ConfigError(level, key, "model profiles can only be defined at user level")
            models.update(_profiles(level, value))
        elif key in KEYS:
            spec = KEYS[key]
            if level not in spec.levels:
                raise ConfigError(level, key, f"can only be set at {' or '.join(spec.levels)} level")
            values[key] = _check(level, key, spec, value)
        elif any(known.startswith(key + ".") for known in KEYS):
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ConfigError(level, key, "must be a mapping of keys")
            _walk(level, value, key + ".", values, models)
        else:
            raise ConfigError(level, key, "unknown key")


def _profiles(level: str, raw: object) -> dict[str, dict]:
    if not isinstance(raw, dict):
        raise ConfigError(level, "models", "must be a mapping of profiles")
    profiles = {}
    for profile, keys in raw.items():
        where = f"models.{profile}"
        if not isinstance(keys, dict):
            raise ConfigError(level, where, "must be a mapping of keys")
        values = {name: spec.default for name, spec in PROFILE_KEYS.items()}
        for name, value in keys.items():
            if name not in PROFILE_KEYS:
                raise ConfigError(level, f"{where}.{name}", "unknown key")
            values[name] = _check(level, f"{where}.{name}", PROFILE_KEYS[name], value)
        required = ["provider", "name"]
        if values["provider"] in ("ollama", "openai_compatible"):
            required += _REQUIRED_FOR_LOCAL
        if values["provider"] in HOSTED_PROVIDERS:
            required.append("api_key_env")
        for name in required:
            if values[name] is None:
                raise ConfigError(level, f"{where}.{name}", "is required")
        if values["provider"] == "ollama" and values["api_key_env"] is not None:
            raise ConfigError(level, f"{where}.api_key_env", "is not accepted for ollama, which takes no credential")
        profiles[str(profile)] = values
    return profiles


def _check(level: str, key: str, spec: Key, value: object) -> object:
    def fail(message: str):
        raise ConfigError(level, key, message)

    if value is None:
        if spec.default is not None or spec.type in ("list", "map"):
            fail("must have a value")
        return None
    if spec.type == "string" and not isinstance(value, str):
        fail("must be a string")
    if spec.type == "enum" and value not in spec.choices:
        fail(f"must be one of {', '.join(spec.choices)}")
    if spec.type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            fail("must be an integer")
        if spec.minimum is not None and value < spec.minimum:
            fail(f"must be at least {spec.minimum}")
    if spec.type in ("number", "ratio"):
        if not isinstance(value, int | float) or isinstance(value, bool):
            fail("must be a number")
        if spec.type == "ratio" and not 0 <= value <= 1:
            fail("must be between 0 and 1")
    if spec.type == "list":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            fail("must be a list of strings")
        value = list(value)
    if spec.type == "map":
        if not isinstance(value, dict):
            fail("must be a mapping of names to values")
        for name, item in value.items():
            if not isinstance(name, str) or not isinstance(item, str | int | float) or isinstance(item, bool):
                fail(f"{name}: must be a string or a number")
        value = {name: str(item) for name, item in value.items()}
    _check_specific(key, value, fail)
    return value


def _check_specific(key: str, value: object, fail) -> None:
    if key == "tests.junit" and value != "{junit}" and (PLACEHOLDER.search(value) or not _inside(value)):
        fail("must be {junit}, or a relative path or glob that stays inside the worktree")
    if key == "tests.generated_dir" and (PLACEHOLDER.search(value) or not _inside(value)):
        fail("must be a relative path that stays inside the worktree")
    if key == "service.url":
        try:
            parts = urlsplit(value.replace("{port}", "1"))
            parts.port  # noqa: B018 - raises ValueError on an invalid port
        except ValueError:
            fail("must be a URL")
        if parts.scheme not in ("http", "https") or parts.hostname not in ("127.0.0.1", "localhost"):
            fail("must be an http URL whose host is 127.0.0.1 or localhost")


def _inside(path: str) -> bool:
    """A relative path that does not leave the directory it is relative to."""
    if not path or PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        return False
    if PureWindowsPath(path).drive:
        return False
    normal = posixpath.normpath(path.replace("\\", "/"))
    return normal != ".." and not normal.startswith("../")
