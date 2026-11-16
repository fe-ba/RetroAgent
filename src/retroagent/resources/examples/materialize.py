"""Create a bundled example project in a directory, with its git history and version tags.

    python materialize.py list
    python materialize.py <name> <dir>

Reference implementation of `retro example` (FR-33). It uses only the standard library and git.
Every materialization of an example produces the same commits: author, dates and messages come
from its manifest (example.toml), and file content is committed without line-ending conversion.
"""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent


def load_manifest(name: str) -> dict:
    path = EXAMPLES_DIR / name / "example.toml"
    if not path.is_file():
        raise SystemExit(f"unknown example: {name}")
    with path.open("rb") as file:
        return tomllib.load(file)


def list_examples() -> None:
    for manifest_path in sorted(EXAMPLES_DIR.glob("*/example.toml")):
        with manifest_path.open("rb") as file:
            manifest = tomllib.load(file)
        tags = ", ".join(version["tag"] for version in manifest["versions"])
        print(f"{manifest['name']}: {manifest['description']} Versions: {tags}.")


def git(target: Path, *args: str, env: dict | None = None) -> None:
    command = [
        "git",
        "-c", "core.autocrlf=false",
        "-c", "core.safecrlf=false",
        "-c", "commit.gpgsign=false",
        "-c", "tag.gpgsign=false",
        "-c", "core.hooksPath=",
        "-c", "advice.detachedHead=false",
        *args,
    ]
    subprocess.run(command, cwd=target, check=True, env=env, stdout=subprocess.DEVNULL)


def clear_working_copy(target: Path) -> None:
    for entry in target.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def materialize(name: str, target: Path) -> None:
    manifest = load_manifest(name)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise SystemExit(f"{target} must not exist or must be empty")
    target.mkdir(parents=True, exist_ok=True)

    git(target, "init", "--quiet", f"--initial-branch={manifest['branch']}")
    # Keep line endings exactly as stored, whatever the configuration of the machine.
    (target / ".git" / "info" / "attributes").write_text("* -text\n", encoding="utf-8")

    for version in manifest["versions"]:
        clear_working_copy(target)
        shutil.copytree(EXAMPLES_DIR / name / "versions" / version["dir"], target, dirs_exist_ok=True)
        env = dict(os.environ)
        env.update(
            GIT_AUTHOR_NAME=manifest["author_name"],
            GIT_AUTHOR_EMAIL=manifest["author_email"],
            GIT_AUTHOR_DATE=version["date"],
            GIT_COMMITTER_NAME=manifest["author_name"],
            GIT_COMMITTER_EMAIL=manifest["author_email"],
            GIT_COMMITTER_DATE=version["date"],
        )
        git(target, "add", "--all")
        git(target, "commit", "--quiet", "--message", version["message"], env=env)
        git(target, "tag", version["tag"])

    tags = ", ".join(version["tag"] for version in manifest["versions"])
    print(f"Created {name} in {target} with versions {tags}.")


def main(argv: list[str]) -> None:
    if len(argv) == 2 and argv[1] == "list":
        list_examples()
    elif len(argv) == 3:
        materialize(argv[1], Path(argv[2]).resolve())
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
