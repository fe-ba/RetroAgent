"""The effective configuration of a project: defaults, then user level, then project level.

Each level overrides the previous one; maps are merged key by key and lists are replaced. The environment
(``RETRO_MODEL``, ``RETRO_LANG``) and CLI levels are not built yet: no key of slice 1 uses them.
"""

import copy
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from retroagent.config.schema import KEYS, PROJECT, USER, ConfigError, validate
from retroagent.metrics.criteria import OpenDefectLimits, Thresholds


def retro_home() -> Path:
    """The user level: ``RETRO_HOME``, or ``~/.retro``."""
    return Path(os.environ.get("RETRO_HOME") or Path.home() / ".retro").expanduser().absolute()


def project_id(project_dir: str | Path) -> str:
    """The directory name, a hyphen, and the first 12 hexadecimal digits of the SHA-256 of its absolute path."""
    path = Path(project_dir).resolve()
    return f"{path.name}-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:12]}"


def worktrees_dir(project_dir: str | Path) -> Path:
    return retro_home() / "worktrees" / project_id(project_dir)


def cache_dir(project_dir: str | Path) -> Path:
    return retro_home() / "cache" / project_id(project_dir)


@dataclass(frozen=True)
class Config:
    project_dir: Path
    values: Mapping[str, object]  # every key of the schema, by dotted name
    models: Mapping[str, Mapping[str, object]]  # profiles of the user level

    def __getitem__(self, key: str) -> object:
        return self.values[key]

    @property
    def credential_env_names(self) -> tuple[str, ...]:
        """Variables named in an ``api_key_env`` of a model profile: removed from every subprocess (NFR-16)."""
        names = (profile["api_key_env"] for profile in self.models.values() if profile["api_key_env"])
        return tuple(dict.fromkeys(names))

    def thresholds(self) -> Thresholds:
        prefix = "exit_criteria."
        return Thresholds(
            min_pass_rate=self[prefix + "min_pass_rate"],
            min_high_priority_executed=self[prefix + "min_high_priority_executed"],
            min_requirement_coverage=self[prefix + "min_requirement_coverage"],
            max_open_defects=OpenDefectLimits(
                critical=self[prefix + "max_open_defects.critical"],
                high=self[prefix + "max_open_defects.high"],
                medium=self[prefix + "max_open_defects.medium"],
            ),
            max_flaky_rate=self[prefix + "max_flaky_rate"],
            max_new_failures=self[prefix + "max_new_failures"],
        )


def load_config(project_dir: str | Path) -> Config:
    """Read the user level and the project level of ``project_dir``. Raises ``ConfigError``."""
    project_dir = Path(project_dir).resolve()
    values = {key: copy.deepcopy(spec.default) for key, spec in KEYS.items()}
    models: dict[str, dict] = {}
    for level, path in ((USER, retro_home() / "config.yaml"), (PROJECT, project_dir / ".retro" / "config.yaml")):
        level_values, level_models = validate(level, _read(level, path))
        for key, value in level_values.items():
            if isinstance(value, dict) and isinstance(values[key], dict):
                values[key] = {**values[key], **value}
            else:
                values[key] = value
        models.update(level_models)
    if values["project.name"] is None:
        values["project.name"] = project_dir.name
    return Config(project_dir=project_dir, values=values, models=models)


def _read(level: str, path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        raise ConfigError(level, None, f"{path} is not valid YAML: {error}") from error
