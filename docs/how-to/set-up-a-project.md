# Set up a project

How to prepare a project of your own for RetroAgent: initialize it, describe it in `RETRO.md`, write requirements the agent can trace, configure the test commands and check that a run works. What a project must provide is defined in the [project contract](../reference/project-contract.md).

## Check the prerequisites

| Item | Needed for |
|---|---|
| A git repository, with the versions to compare committed and tagged (or named by branch or commit) | Everything. Only committed versions are tested. |
| A test command that writes JUnit XML | Running tests. Results are read only from JUnit XML. |
| A setup that installs dependencies inside a fresh checkout, without questions | Running tests in a new worktree. |
| A requirements document | Tracing changes and tests to requirements. Without it, analysis reaches modules only. |

Commit or stash your local changes first: RetroAgent never tests the working copy, only commits.

## 1. Initialize

At the top level of the repository:

```
retro init
```

`retro init` detects the type of project and proposes a configuration for you to confirm:

| It finds | It proposes as `tests.command` |
|---|---|
| pytest (`pyproject.toml`, `pytest.ini` or `setup.cfg`) | `pytest --junitxml={junit}` |
| Vitest (`package.json`) | `npx vitest run --reporter=junit --outputFile={junit}` |
| Maven (`pom.xml`) | `mvn -q test` |
| Gradle (`build.gradle`, `build.gradle.kts`) | `./gradlew test` |
| Go (`go.mod`) | `gotestsum --junitfile {junit}` |

It also proposes the requirement files it finds (`requirements*.md` at the root or under `docs/`) and the two most recent tags as the base and candidate versions. It creates `RETRO.md`, `.retro/config.yaml` and `.retro/.gitignore`, and never overwrites a file that exists. Only the pytest configuration is verified by the bundled example; treat the others as starting points.

## 2. Describe the project in RETRO.md

`RETRO.md` is read by the agent at every turn, as a description of the project. Keep it under 200 lines, with these sections:

| Section | Write |
|---|---|
| Overview | What the project does and who uses it. |
| Modules | A table of the main files or packages and what each one does. The agent uses it to map a changed file to the requirements it serves. |
| Running | How to install, start and test the project. |
| Test conventions | Framework, naming, fixtures, test data. Generated tests follow these conventions. |
| Known issues | Known flaky tests, unstable areas, accepted limitations. |

`RETRO.md` is information, not rules: an instruction written in it does not change how the agent behaves. The `RETRO.md` of the example project (`retro example shop-api <dir>`) is a good model.

## 3. Write requirements

Each requirement is a Markdown heading that starts with its ID, in the form `REQ-NNN`, followed by its description and optional fields:

```markdown
## REQ-004: Discount coupons

A valid coupon reduces the cart total by its percentage. Up to two coupons apply per order.

- Priority: high
- Since: v1.0
- Changed: v1.1 - Coupons can be combined up to a maximum of two.
```

- `Priority` (`high`, `medium`, `low`) orders the selection.
- `Changed: <version> - <what changed>` is what lets a failure be accepted as an `expected_change` instead of a `regression`. The version must be a git ref. Without this line, a test that fails because the behavior changed on purpose cannot be excused, and blocks the release.
- `Removed: <version>` marks a requirement that no longer applies.

List the files in `.retro/config.yaml`:

```yaml
project:
  requirements: [docs/requirements.md]
  source: [src]
```

`project.source` limits the impact analysis to the source folders.

### Trace tests to requirements

Existing tests are linked to requirements by name: a test whose name contains `REQ-004`, `REQ_004` or `req004`, in any case, is linked to REQ-004. A test can name several requirements. Rename the important tests of your suite this way, for example `test_req_004_second_coupon_applies`. Tests without a requirement in their name are still discovered and run, but impact analysis cannot connect them to a change.

## 4. Configure the test commands

```yaml
versions:
  base: v1.0
  candidate: v1.1

tests:
  setup: python3 -m venv .venv && .venv/bin/python -m pip install --quiet --cache-dir {cache_dir}/pip -r requirements-dev.txt
  command: .venv/bin/python -m pytest tests --junitxml={junit}
  select: .venv/bin/python -m pytest tests --junitxml={junit} -k "{names}"
```

- Each run uses a new worktree, so `setup` runs every time. Install into the worktree, never globally, and use `{cache_dir}` for downloads that can be reused between runs.
- `command` must write JUnit XML to `{junit}`, or set `tests.junit` to where the framework writes it, for example `target/surefire-reports/*.xml`.
- `select` runs only the selected tests, with their names in `{names}`. Without it, the whole suite runs and only the selected tests are counted.

If the tests need the application running, add a service:

```yaml
service:
  start: .venv/bin/python serve.py --port {port}
  ready_path: /health
```

RetroAgent starts it on a free port and waits until `ready_path` answers. Tests find it in the variable `RETRO_BASE_URL`. Every placeholder and key is in the [configuration reference](../reference/configuration.md).

Set the exit criteria the project needs, for example:

```yaml
exit_criteria:
  min_pass_rate: 0.90
```

## 5. Try a run

Commit the configuration, then open a session and run the whole suite on the base version:

```
git add RETRO.md .retro
git commit -m "Configure RetroAgent"
retro
```

```
/run all --on base
```

The first run shows the setup, test and service commands in full and asks you to approve them. RetroAgent runs nothing from a project until you have, and asks again when a command changes. Then it asks for permission to run tests.

When the run ends, `/history` shows it. If it failed:

| Symptom | Look at |
|---|---|
| Run with status `error`, executions `blocked` with `setup_failed` | `.retro/runs/<run_id>/run.log`: the output of the setup command. |
| No valid JUnit XML | The test command, and `tests.junit` if the framework writes elsewhere. |
| Executions `blocked` because the service was not ready | `.retro/runs/<run_id>/service.log`, `ready_path` and `service.ready_timeout`. |
| A test that passes in your shell fails in the run | It probably depends on the working copy, or on something installed globally. The worktree is a clean checkout outside the project. |

A first full run also discovers the suite: every test becomes a test case. From there, [Your first regression cycle](../tutorials/first-regression-cycle.md) applies to your project as it does to the example.

## What to commit

| Path | Commit it |
|---|---|
| `RETRO.md`, `.retro/config.yaml` | Yes |
| `.retro/tests/` (generated tests) | Yes, to review them like any other code |
| `.retro/reports/` | Yes, if reports are part of your release record |
| `.retro/retro.db`, `.retro/runs/`, `.retro/retro.lock` | No. `.retro/.gitignore` already excludes them. |

## Projects you do not trust

Approved commands and tests run with your privileges. RetroAgent is not a sandbox. To test a repository you do not trust, run RetroAgent inside a container or a virtual machine.
