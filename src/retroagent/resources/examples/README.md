# Bundled examples

Example target projects that `retro example <name> <dir>` creates in a directory of the user, each with its git history and version tags (FR-33).

## Format

```
examples/
├── materialize.py            # reference implementation of `retro example`
└── <name>/
    ├── example.toml          # manifest: branch, author, and the versions in order
    ├── ORACLE.md             # expected results; never copied into the created project
    ├── expected/             # reference outputs for the oracle, such as a report filled by hand
    └── versions/
        └── <dir>/            # full snapshot of the project at that version
```

- An example cannot be stored as a git repository inside this repository, so each version is a full snapshot. `materialize.py` commits the snapshots in order and tags each one.
- Author, dates and messages are fixed in the manifest, and file content is committed without line-ending conversion. Every materialization produces the same commit hashes, so documentation and tests can refer to them.
- `ORACLE.md` and `expected/` hold what RetroAgent is expected to find and produce. They stay here: a model that could read it inside the target project would be reading the answers.
- Snapshots must not contain comments that reveal the seeded cases.

## Use

```
python src/retroagent/resources/examples/materialize.py list
python src/retroagent/resources/examples/materialize.py shop-api ../shop-api-demo
```

The target directory must not exist or must be empty, and must be outside this repository.
