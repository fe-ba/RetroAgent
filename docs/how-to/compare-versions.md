# Compare versions

How to choose the two versions a cycle compares, change them, run single steps instead of the whole cycle, and continue a cycle that stopped. The commands are in the [CLI reference](../reference/cli.md).

## Set the versions

A cycle compares a **baseline**, the version known to work, with a **candidate**, the version to release. Each can be a tag, a branch or a commit.

| Where | How | Scope |
|---|---|---|
| Project configuration | `versions.base` and `versions.candidate` in `.retro/config.yaml` | Default for every session. `retro init` proposes the two most recent tags. |
| Command line | `retro --base v1.0 --candidate v1.1` | One session. Overrides the configuration. |
| Inside a session | `/analyze v1.0 v1.1` or `/cycle v1.0 v1.1` | From that command on. |
| In plain language | "Compare v1.1 with v1.2" | The agent sets them with `runtime__set_versions`. |

Each ref is resolved to its commit when it is set, and the commit is what every tool uses. A branch that moves during the session does not change what is compared. A ref that does not resolve stops the session at start with exit code `2`, or makes the command fail inside a session.

Only committed versions are compared. To test a change that is not committed yet, commit it on a branch and use the branch as the candidate.

`/status` shows the session versions with their commits.

## Run the whole cycle or single steps

`/cycle` runs every step in order and checks each outcome before the next. Run steps one by one when you want to review or correct each result before going on:

| Step | Command | Check before going on |
|---|---|---|
| Impact analysis | `/analyze` | The impacted requirements and modules, and the reasons for those left out. |
| Discovery, the first time | `/run all --on base`, then `/run all --on candidate` when the change touches test files | `/history`: the runs completed. |
| Selection | `/select` | The suite, the reasons, and the gaps it reports. |
| Design | `/design`, or `/design REQ-002` for one requirement | The test cases: concrete data and an expected result. |
| Implementation | `/implement`, or `/implement TC-027` | The generated code in `.retro/tests/`. |
| Execution | `/run --on both` | `/status`: executions by status and result. |
| Triage | `/triage` | Each classification and its justification; `/defects`. |
| Report | `/report completion` | The decision and its reasons. |

Between steps you can talk to the agent in plain language, for example to ask why a requirement was left out, or to add a test case to the suite. Its tools check what it records in the same way as during the cycle.

### Plan without running anything

`retro --mode plan`, or `/mode plan` in a session, analyzes and designs but cannot run tests or write test code. `/cycle` in plan mode runs the analysis, the selection and the design, and stops before the implementation. Use it to review what the agent would test before anything runs.

## Continue a cycle that stopped

A cycle stops when a step does not reach its outcome after one retry, when a tool call is refused, when a run ends in error, when the agent asks you a question, or when the model's quota runs out. Everything done so far is in project memory. Fix the cause or answer the question, then run `/cycle` again in the same session: steps whose outcome is already in project memory for the session versions are not repeated.

## Compare the next pair of versions

A new pair of versions is a new cycle on the same project memory:

```
retro --base v1.1 --candidate v1.2
```

```
/cycle
```

What earlier cycles left is used:

- Test cases are kept, including generated ones. A full run for discovery is skipped when one already exists on the same commit, and on the candidate it runs only when the change touches test files.
- A test that failed before and now passes is counted as `fixed`.
- An open defect is closed by a completed run on the candidate in which every test case linked to it passes. Otherwise it stays open and counts against the release, even if its tests are no longer selected; close it yourself with `/defects close DEF-001 <reason>` when it no longer applies.

## Compare against an older baseline

The baseline does not have to be the previous release. Comparing `v1.0` with `v1.2` shows the change of two releases at once: more requirements are impacted, and every test that changed verdict across both releases counts. Requirement changes apply when their version lies between the two commits, so a `Changed: v1.1` entry applies to a `v1.0` to `v1.2` comparison too.
