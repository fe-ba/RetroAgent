# Project memory

What RetroAgent keeps between sessions, why it is a database rather than the conversation, and who may write each part of it ([ADR-0008](../adr/0008-project-local-sqlite-memory.md)). The tables and columns are specified in `spec/data-model.md`.

## Why a database

A conversation with a model is short-lived and unreliable as a record. It is cleared between the steps of a cycle, old parts are dropped when the context fills up, and the model can misremember what it read. A regression cycle needs the opposite: facts that stay exact across steps, sessions and releases, and that a report can cite.

So every fact lives in project memory: one SQLite file per project, `.retro/retro.db`. The model reads it and writes to it only through the tools of the `memory`, `test_runner` and `reports` servers. When the conversation is cleared, nothing is lost: the next step reads what it needs again.

## What it holds

| Area | Records |
|---|---|
| Sessions and audit | Each session with its versions and model, and every tool call with its arguments, outcome and duration. |
| Requirements | Requirements parsed from the documents of the project, with their documented changes. |
| Impact analysis | The change set of each pair of versions, the impacted modules and requirements with their reasons, the requirements judged not impacted with theirs, and the risks. |
| Test design and selection | Test cases, their links to requirements, suites, and the test cases left out of each suite with a reason. |
| Execution | Runs, one execution per test case per run, and every attempt with its result and evidence. |
| Interpretation | Triage of each failed execution, defects and their links to executions. |
| Reporting | Evaluations of the exit criteria, and reports. |

## Who writes what

The rules that keep the memory trustworthy:

- **One writer per fact.** Each table has one component allowed to write it. The model reaches the data only through tools, and no tool lets it write what code owns. A test result, for example, is written only by the test runner, from JUnit XML.
- **Code assigns identifiers.** `REQ-`, `TC-`, `RUN-`, `DEF-`, `RSK-` and `RPT-` identifiers are assigned in sequence and never reused. The model never invents an identifier for a new record.
- **Code reads requirements.** Requirements are parsed by code from the requirement documents, not summarized by the model.
- **Model input is marked.** Columns whose content was written by the model, such as a reason, a justification or a design, are marked as such in the specification, and records store which model wrote them.
- **History is kept.** Nothing is deleted. Runs, executions, evaluations and reports are immutable once complete. A second triage of an execution does not erase the first: both are kept, and reports list executions triaged more than once.

## Memory across cycles

Because memory belongs to the project, a new pair of versions builds on the previous one. Test cases, including generated ones, are kept. A defect stays open until a run on a candidate in which all its tests pass, or until the user closes it. The comparison of a test across releases is possible because its history is there.

The audit table also supports the line shown after every turn: what the model actually recorded, computed from the tool calls, whatever its answer says.

## One session at a time

A session takes a lock on `.retro/retro.lock` for its whole duration. A second session on the same project is refused, and the message names the process that holds the lock. This keeps one writer at a time, and lets a session read "everything since I started" as its own work, for example the decision of its latest evaluation. A lock left by a session that crashed is taken over; runs that the crash left half done are marked `interrupted`.

## What is not in git

The database and the run evidence (`.retro/runs/`) are excluded from version control by `.retro/.gitignore`. They are machine records, large and changing. Generated tests (`.retro/tests/`) and reports (`.retro/reports/`) can be versioned and reviewed like any other file. A new clone therefore starts with an empty memory. Copy `.retro/retro.db` to keep the history of a project on another machine.
