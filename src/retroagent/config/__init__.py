"""Configuration: levels, restricted keys, validation and placeholders (docs/reference/configuration.md)."""

from retroagent.config.loader import Config, cache_dir, load_config, project_id, retro_home, worktrees_dir
from retroagent.config.placeholders import PlaceholderError, expand
from retroagent.config.schema import ConfigError

__all__ = [
    "Config",
    "ConfigError",
    "PlaceholderError",
    "cache_dir",
    "expand",
    "load_config",
    "project_id",
    "retro_home",
    "worktrees_dir",
]
