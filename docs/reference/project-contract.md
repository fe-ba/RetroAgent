# Project contract

What a target project must provide for RetroAgent to analyze, test and report on it.

## Summary

| Item | Level | Without it |
|---|---|---|
| Git repository | Required | RetroAgent cannot compare versions and exits with code `2`. |
| Two identifiable versions (tags, branches or commits) | Required for comparison | Only single-version runs are possible; no baseline comparison. |
| Test command that produces JUnit XML | Required for execution | Test cases can be designed but never executed. |
| Setup that works non-interactively in a fresh checkout | Required for execution | Test cases are marked `blocked`. |
| Service start command | Required when tests need a running service | Test cases are marked `blocked`. |
| Requirements document | Recommended | Impact analysis and traceability reach modules only; reports state it as a limitation. |
| `RETRO.md` | Recommended | The agent infers the project context in every session. |
| Requirement IDs in test names | Recommended | Existing tests are not traced to requirements. |

Only committed versions are tested. Uncommitted changes in the working copy are never part of a run.

## Layout

```
my-project/
├── RETRO.md
├── docs/
│   └── requirements.md
└── .retro/
    ├── .gitignore
    ├── config.yaml
    ├── mcp.json                # optional
    ├── skills/                 # optional
    ├── steering/               # optional
    ├── tests/                  # generated tests
    ├── retro.db
    ├── runs/
    ├── reports/
    └── worktrees/
```

Only `RETRO.md` and `.retro/config.yaml` are needed to start. RetroAgent creates the rest. Outside `.retro/`, RetroAgent only writes `RETRO.md`, and only when the user runs `retro init`.

## RETRO.md

Project context loaded at the start of every session, after steering. Created by `retro init` and edited by the user.

Recommended sections:

| Section | Content |
|---|---|
| Overview | What the project does and who uses it. |
| Modules | Main components and where they live. |
| Running | How to install, start and test the project. |
| Test conventions | Frameworks, naming, fixtures, test data. |
| Known issues | Known flaky tests, unstable areas, accepted limitations. |

It is always in context, so it should stay short: under 200 lines.

## Requirements

### Location

Listed in `project.requirements`. `retro init` proposes Markdown files named `requirements*.md` at the root or under `docs/` that contain requirement IDs. Files such as `requirements.txt` are dependency lists and are ignored.

### Format

Each requirement is a Markdown heading that starts with its ID, followed by a description and optional fields:

```markdown
## REQ-004: Discount coupons

A valid coupon reduces the cart total by its percentage. Only one coupon applies per order.

- Priority: high
- Since: v1.0
- Changed: v1.1 - Coupons can be combined up to a maximum of two.
```

| Field | Values | Purpose |
|---|---|---|
| `Priority` | `high`, `medium`, `low` | Test selection and prioritization. |
| `Since` | Version ref | Version that introduced the requirement. |
| `Changed` | `<version> - <description>` | A change of the requirement. Can appear several times. |
| `Removed` | Version ref | Version that removed the requirement. |

`Changed` and `Removed` let the agent tell a regression from an expected change: when a requirement changed in the candidate version, a behavior change in that area is classified as `expected_change`, not `regression`.

## Traceability

Existing tests are linked to requirements through their names, which appear in JUnit XML for every framework.

- A test name containing `REQ-004`, `REQ_004` or `req004` (case-insensitive) is linked to `REQ-004`.
- A test can reference several requirements.
- Tests written by RetroAgent follow the form `test_req_004_<description>`.

## Generated tests

Test code written by RetroAgent is stored in `.retro/tests/`, never in the project tree (ADR-0015). Before each run it is copied into the worktree at `tests.generated_dir`, so it runs with the project's own test setup against both versions. The files in `.retro/tests/` can be versioned and reviewed like any other code; adopting them into the project's own test suite is a manual decision of the user.

## Test execution

1. RetroAgent creates a detached worktree of the version to test under `.retro/worktrees/`.
2. If `tests.setup` is set, it runs once in that worktree.
3. Generated tests from `.retro/tests/` are copied to `tests.generated_dir` inside the worktree.
4. If `service.start` is set, the service starts on a free port and RetroAgent waits for `service.ready_path` to answer.
5. `tests.command` (or `tests.select` for a subset) runs in the worktree with the variables listed in `configuration.md`.
6. Results are read only from the JUnit XML at `tests.junit`.
7. The service is stopped and the worktree is removed, including its metadata in `.git/worktrees/`.

The exit code of the test command is recorded as evidence but does not decide results. If no valid JUnit XML exists after the command, the run is recorded as an error and its test cases are marked `blocked`.

Commands must not require interactive input. Setup must install dependencies locally to the worktree (for example, in a virtual environment), never globally.

## Detection by `retro init`

`retro init` proposes a configuration and the user confirms it.

| Marker | Proposed `tests.command` | Proposed `tests.junit` |
|---|---|---|
| `pyproject.toml`, `pytest.ini` or `setup.cfg` with pytest | `pytest --junitxml={junit}` | `{junit}` |
| `package.json` with Vitest | `npx vitest run --reporter=junit --outputFile={junit}` | `{junit}` |
| `pom.xml` | `mvn -q test` | `target/surefire-reports/*.xml` |
| `build.gradle` or `build.gradle.kts` | `./gradlew test` | `build/test-results/test/*.xml` |
| `go.mod` | `gotestsum --junitfile {junit}` | `{junit}` |

Only the pytest configuration is verified by the bundled example. The others are starting points for the user to confirm.

For versions, `retro init` proposes the two most recent tags as `versions.base` and `versions.candidate`.

## The .retro folder

| Path | Versioned | Content |
|---|---|---|
| `config.yaml` | Yes | Project configuration. |
| `mcp.json` | Yes | Additional MCP servers. |
| `skills/`, `steering/` | Yes | Project extensions. |
| `tests/` | Yes | Generated tests. |
| `reports/` | Yes | Generated reports. |
| `retro.db` | No | Project memory. |
| `runs/` | No | Run evidence. |
| `worktrees/` | No | Temporary checkouts. |

`retro init` creates `.retro/.gitignore` with:

```
retro.db
retro.db-*
runs/
worktrees/
```
