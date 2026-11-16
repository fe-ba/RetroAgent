"""Placeholders of ``tests.*`` and ``service.*`` commands (configuration.md, Placeholders)."""

import re
from collections.abc import Mapping

PLACEHOLDERS = ("junit", "names", "port", "worktree", "run_dir", "cache_dir")

# Only the known names are placeholders: any other brace in a shell command (``${HOME}``, ``awk '{print}'``)
# is left as it is.
PATTERN = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


class PlaceholderError(Exception):
    """A command uses a placeholder that has no value at that step, for example ``{names}`` in a setup."""


def expand(template: str, values: Mapping[str, object]) -> str:
    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise PlaceholderError(f"{{{name}}} has no value in this command: {template}")
        return str(values[name])

    return PATTERN.sub(replace, template)
