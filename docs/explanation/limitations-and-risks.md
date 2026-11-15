# Limitations and risks

What RetroAgent does not do, what it cannot guarantee, and the risks accepted in its design. Each item names the decision behind it.

## What the results depend on

- **The model shapes the inputs of the decision.** Code computes metrics, exit criteria and the release decision, and validates the classifications that depend on recorded facts. The suite, the impacted requirements, priorities, defect severities and the classifications `regression`, `environment` and `test_defect` remain judgments of the model. Reports list them for review (ADR-0022).
- **A pass proves only what the test checks.** A generated test with weak assertions passes easily. No tool measures the strength of a test, and code coverage is not measured (ADR-0010, ADR-0017).
- **Flaky detection is a lower bound.** A few reruns find only part of the flakiness (`metrics.md`).
- **Selection is only as good as discovery.** Tests are discovered by running them. In plan mode, and before the first full run, only test cases already known can be selected (ADR-0023).
- **Open defects are counted for the whole project.** A defect of an earlier cycle whose test cases are no longer run stays open and blocks release until the user closes it (ADR-0022).

## What is not supported

- User interface, performance, load and security testing.
- Projects that are not git repositories, or that cannot produce JUnit XML (ADR-0009, ADR-0010).
- Uncommitted changes: only committed versions are tested.
- Requirement identifiers in a form other than `REQ-NNN`, and requirement documents in a format other than the one of `project-contract.md`.
- Tests that need infrastructure beyond one service started by a command: databases, containers, external systems.
- Concurrent sessions on the same project.
- Use of the bundled MCP servers from another MCP client (ADR-0026).

## Technical limits

- **Compiled languages.** The same generated tests run against both versions. Where one file that does not compile stops the whole build, a generated test written for the candidate can block the whole run against the baseline. Only the pytest configuration is verified by the example.
- **Setup runs for every run.** Worktrees are new each time; `{cache_dir}` reduces the cost and does not remove it. Without network, a setup that downloads packages fails unless the cache is filled (ADR-0024).
- **Small models.** A model needs a context window at least twice the size of the steering and tool definitions, and tool calling, or the JSON fallback mode. Small local models may follow the skills poorly; their results are still recorded faithfully, but their analysis and their tests can be weak (ADR-0003, ADR-0027).
- **Name-based selection.** `tests.select` matches test names, so a selection may run more tests than asked; their results are ignored (ADR-0023).
- **Memory does not travel through git.** Generated tests in `.retro/tests/` and reports can be versioned; the database and the run evidence cannot. In a new clone, generated tests are known only as tests of the project until the database is copied (ADR-0008).

## Security

- **RetroAgent is not a sandbox.** Approved project commands, the tests of the project and the generated tests run with the privileges of the user. A repository that is not trusted should be tested inside a container or a virtual machine (ADR-0024).
- **Prompt injection is reduced, not removed.** Content of the project is presented as data, and no tool accepts a result, but a misled model can still write a poor analysis or a harmful test. Interactive sessions show generated code before it is written; in mode `auto` nobody does (ADR-0021, ADR-0024).
- **With a hosted model, project content leaves the machine:** steering, `RETRO.md`, and the files, diffs and logs that tools return (`llm-providers.md`).

## Project risks

- **The runtime is the schedule risk.** RetroAgent has no supported mode without its own runtime (ADR-0026). The core requirements are built first, as a thin path through every component (`spec/requirements.md`).
- **PDF export needs a system library.** Markdown is always produced; the PDF fails with a message that says what to install (ADR-0018).
- **One example project.** Behavior on other languages, frameworks and project sizes is not verified.
