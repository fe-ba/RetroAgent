# Project contract

What a target project must provide for RetroAgent to analyze, test and report on it.

## Summary

| Item | Level | Without it |
|---|---|---|
| Git repository | Required | RetroAgent cannot compare versions and exits with code `2`. |
| Two identifiable versions (tags, branches or commits) | Required for comparison | Only single-version runs are possible; no baseline comparison. |
| Test command that produces JUnit XML | Required for execution | Test cases can be designed but never executed. |
| Setup that works non-interactively in a fresh checkout | Required for execution | Test executions are marked `blocked`. |
| Service start command | Required when tests need a running service | Test executions are marked `blocked`. |
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
    ├── retro.lock
    ├── runs/
    └── reports/
```

Only `RETRO.md` and `.retro/config.yaml` are needed to start. RetroAgent creates the rest. Outside `.retro/`, RetroAgent only writes `RETRO.md`, and only when the user runs `retro init`. Worktrees are created outside the project (see Test execution).

## RETRO.md

Project context placed after steering and read again at the start of every turn (`context-loading.md`). Created by `retro init` and edited by the user.

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

The version of a `Changed` or `Removed` entry must be a git ref. The entry **applies to the change** between a baseline and a candidate when the commit of that ref is reachable from the candidate and not from the baseline: the requirement changed after the baseline, up to the candidate. An entry whose version does not resolve to a ref never applies; `memory.sync_requirements` reports it. Code checks this before it accepts the classification `expected_change` (`mcp-tools.md`).

## Traceability

Existing tests are linked to requirements through their names, which appear in JUnit XML for every framework.

- A test name containing `REQ-004`, `REQ_004` or `req004` (case-insensitive) is linked to `REQ-004`.
- A test can reference several requirements.
- A reference to a requirement that is not in project memory creates no link. Links by name are added when a test is discovered and again when requirements are synchronized, so the order of the two does not matter.
- Tests written by RetroAgent follow the form `test_req_004_<description>`.

## Test identity

A test is identified by its entry in the JUnit XML: `<classname>::<name>`. Each entry is one test case, so each case of a parametrized test is a test case of its own.

A generated test is bound to its test case the first time a run reports it: the entry whose `name` equals the function name written by RetroAgent, and whose `classname` ends with the name of its file or is the only entry of the run with that name. To keep this reliable, the function name and the file of a generated test are unique among generated tests, and generated tests are never parametrized.

An entry whose `name` is the function name of a generated test and that cannot be bound by this rule is never registered as a test of the project: it is ignored, and the test case is `blocked` with reason `not_reported`.

`{names}` in `tests.select` is the `name` of each selected test, without its parameter suffix (`[...]`) and without duplicates, joined with `tests.select_separator`. A selection command may run more tests than asked, for example when one name is contained in another; results of tests outside the scope are ignored.

## Discovery

RetroAgent learns the tests of the project from the JUnit XML of a full run (`/run all`); there is no separate listing step. The first full run against the baseline discovers the project suite. Tests added by the change are discovered by a full run against the candidate. In plan mode nothing runs, so only test cases already known can be selected.

## Generated tests

Test code written by RetroAgent is stored in `.retro/tests/`, never in the project tree (ADR-0015). Before each run it is copied into the worktree at `tests.generated_dir`, so it runs with the project's own test setup against both versions. The files in `.retro/tests/` can be versioned and reviewed like any other code; adopting them into the project's own test suite is a manual decision of the user.

**A generated test that cannot be loaded.** A file that the test framework cannot load, for example because it imports a name that does not exist, is reported in the JUnit XML as an error of the file instead of a test, and it can stop the whole command. When that file is a generated test, the generated test cases of that file get an execution with result `error` and the message of the entry, the file is removed from the worktree, and the command of that round runs once more, so that one broken generated test never hides the results of the others. The first JUnit XML of the round is kept in the evidence. When the file is not a generated test, the results stand as reported, and the `error` of the run names the file, so that test cases marked `not_reported` have a visible cause.

## Test execution

1. RetroAgent creates a detached worktree of the version to test under `~/.retro/worktrees/<project-id>/`. It is outside the project tree, so that the tools of the project never find the configuration or the dependencies of the working copy by searching parent directories.
2. If `tests.setup` is set, it runs once in that worktree.
3. Generated tests from `.retro/tests/` are copied to `tests.generated_dir` inside the worktree.
4. If `service.start` is set, the service starts on a free port and RetroAgent waits for `service.ready_path` to answer. Any HTTP response with a status below 500 means ready.
5. `tests.command` (or `tests.select` for a subset) runs in the worktree with the variables listed in `configuration.md`.
6. Results are read only from the JUnit XML at `tests.junit`.
7. Each test case whose first attempt did not pass is rerun `tests.reruns` times: with `tests.select` when it is set, otherwise with the full command. Each attempt writes its own JUnit XML. A rerun never changes the outcome of the run: when a rerun round times out or gives no valid JUnit XML, no attempt is stored for it, the remaining rounds are not run, and the run log says so. A test case that a rerun does not report, or reports as skipped, gets no attempt for that round.
8. The service is stopped and the worktree is removed, including its metadata in `.git/worktrees/`.

The exit code of the test command is recorded as evidence but does not decide results. If no valid JUnit XML exists after the command, the run is recorded as an error and its test executions are marked `blocked`. When `tests.timeout` stops the command, the run is `interrupted` and its test executions are `blocked`. A test case that the run was asked to execute and that the JUnit XML does not report is `blocked` with reason `not_reported`.

**Evidence.** Each run has a directory `.retro/runs/<run_id>/` with `run.log` (every command with its times, exit code and output, and every note about a step that failed), `service.log`, and one JUnit XML per round: `junit-1.xml` for the test command and `junit-2.xml` onwards for the reruns. `{junit}` is the path of the file of the current round. When `tests.junit` is a path or a pattern inside the worktree instead, the files it matches are copied to `junit-<n>/` after each round and removed from the worktree before the next one.

When the user interrupts a run during a rerun, the run is still `completed` with the attempts stored so far, and the interruption then ends the turn.

In a JUnit XML entry that has both a failure and an error, the result is `error`. When two entries have the same `classname` and `name`, the first one counts.

`tests.setup` is stopped after `tests.timeout` seconds, like a test command; the run then has status `error` and its executions are `blocked` with reason `setup_failed`.

Commands must not require interactive input. Setup must install dependencies locally to the worktree (for example, in a virtual environment), never globally.

## Trust

The setup, test and service commands are written in the project and run with the privileges of the user. RetroAgent runs them only after the user approved their exact content, and asks again when they change (`configuration.md`, Project commands). They never receive the model credentials of the user.

This limits surprises; it is not a sandbox. Approved commands, the tests of the project and the generated tests are code that runs on the machine. A repository that is not trusted should be tested inside a container or a virtual machine.

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
| `retro.lock` | No | Session lock; one session per project at a time. |
| `runs/` | No | Run evidence. |

`retro init` creates `.retro/.gitignore` with:

```
retro.db
retro.db-*
retro.lock
runs/
```
