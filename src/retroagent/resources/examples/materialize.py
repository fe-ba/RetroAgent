"""Create a bundled example project in a directory, with its git history and version tags.

    python materialize.py list
    python materialize.py <name> <dir>

Thin wrapper over `retro example` (FR-33); the logic is in `retroagent.examples`.
Requires the package to be installed (`pip install -e ".[dev]"`).
"""

import sys

from retroagent.cli.main import main

if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 2 and sys.argv[1] != "list"):
        raise SystemExit(__doc__)
    sys.exit(main(["example", *sys.argv[1:]]))
