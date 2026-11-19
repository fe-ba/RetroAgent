# MCP, skills and steering

RetroAgent is a language model plus three things around it: **steering**, which tells the model who it is and which rules always hold; **skills**, which tell it how to do one step of the work; and **MCP servers**, which are the only way it can act on the project. This document explains what each one holds, why the work is split this way, and how the three meet in one step of a regression cycle.

The short version:

| Mechanism | Answers | Loaded | Written in | Example |
|---|---|---|---|---|
| Steering | Who am I, and what must I never do? | Always, in every model call | Markdown | "Never claim an action that was not done through a tool." |
| Skill | How do I do this step? | On demand, one at a time | Markdown with a short YAML header | The procedure to triage a failure. |
| MCP server | What can I do, and what is refused? | Its tools are listed in every call | Python, deterministic code | `memory.save_triage`, which refuses a triage that the evidence does not support. |

## Steering: the rules that always hold

Steering is a set of six Markdown files in `src/retroagent/resources/steering/`, placed at the start of the context of every model call:

| File | Content |
|---|---|
| `01-identity.md` | What RetroAgent is, its purpose, and how to treat each source of information: instructions, project description, data. |
| `02-workflow.md` | The steps of a regression cycle, the command and the skill of each one, and how to respect a refusal. |
| `03-test-states.md` | The difference between designed, implemented, executed and passed, and the evidence each one needs. |
| `04-quality.md` | Evidence: base every statement on a tool result or a record, name it, separate facts from hypotheses. |
| `05-safety.md` | Never modify the user's working copy, write tests only in `.retro/tests/`, never claim an action that was not done. |
| `06-output.md` | Language, form, and copying figures exactly as the tools return them. |

Steering holds what must be true in every turn, whatever the step. Because it is always present, it is kept short: every word is paid for in every call, and a small local model has little room.

The user can add steering in `~/.retro/steering/`, and a project in `.retro/steering/`. Added steering comes after the bundled files and never replaces them. Project steering is loaded only after the user approves it, because it comes from the repository being tested, and a repository can be written by anyone ([ADR-0021](../adr/0021-context-layers-and-trust.md)).

## Skills: one procedure per step

A skill is a folder with a `SKILL.md` file: a YAML header with a name and a one-paragraph description, and a body with the procedure. RetroAgent ships five:

| Skill | Step | What the procedure covers |
|---|---|---|
| `impact-analysis` | Analyze | Set the versions, read the requirements, compute the change set, read the diffs, decide every requirement, record risks. |
| `test-selection` | Select | Choose and prioritize the suite, justify every test case, leave out with reasons, report the gaps, ask for a full run when the change adds tests. |
| `test-design` | Design and implement | Write test case specifications with concrete data, then their code, following the conventions of the project. |
| `failure-triage` | Triage | Read the evidence of each failure, classify it, and register or link a defect for each product fault. |
| `test-reporting` | Report | Prepare a report, write its narrative sections from the computed data, render it. |

Only the names and descriptions of the skills are always in the context, as an index. The body of a skill enters the context when the model calls `runtime.load_skill`, and only one body is loaded at a time ([ADR-0005](../adr/0005-steering-always-skills-on-demand.md)). During triage, the model does not need the procedure of test design, so it does not pay for it.

This is the main difference with steering. Steering is what the agent is; a skill is what it is doing now. A rule that applies only to triage, such as "register a defect right after the regression it explains", belongs in the triage skill, not in the steering.

A user can add skills in `~/.retro/skills/`, and may replace a bundled skill with one of the same name. A project can add skills in `.retro/skills/` after approval, but cannot replace a bundled or user skill. A team can thus adapt a procedure to its own way of working without forking RetroAgent.

## MCP servers: the only way to act

[MCP](https://modelcontextprotocol.io) (Model Context Protocol) is an open protocol for giving a model tools. A server publishes tools, each with a name, a description and a JSON schema for its arguments. A client lists them, shows them to the model, and forwards the calls the model makes. RetroAgent's runtime is the client. It starts four bundled servers, each a separate process that talks to the runtime over standard input and output:

| Server | Tools | What it does |
|---|---|---|
| `git` | 5 | Reads the repository: resolves refs, computes the change set, shows diffs, reads and lists files at a version. It never modifies the working copy. |
| `memory` | 20 | Keeps project memory: requirements, impact, risks, suites, test cases, runs, executions, triage and defects. |
| `test_runner` | 3 | Writes generated tests and runs suites in temporary worktrees, then reads results from the JUnit XML. |
| `reports` | 4 | Evaluates the exit criteria, prepares a report with all its computed data, and renders it. |

The runtime adds two tools of its own, `runtime.load_skill` and `runtime.set_versions`. The model sees each tool as `<server>__<tool>`, for example `memory__save_triage`. The full list, with every argument, check and error, is in the [MCP tools reference](../reference/mcp-tools.md).

### Tools that check

A tool is not only a way to write. It is also where a claim of the model meets the evidence. The servers refuse records that the evidence does not support. Some examples:

| Tool | Refuses |
|---|---|
| `memory.save_impact` | An impact that does not decide every requirement in effect. |
| `memory.save_suite` | A suite that leaves out a test that passed on the baseline and failed on the candidate. |
| `memory.save_triage` | `expected_change` for a requirement without a documented change in this version; `flaky` for a test that never passed in a rerun; `pre_existing` for a test that did not fail on the baseline; `regression` for a test that also failed on the baseline. |
| `memory.register_defect` | A defect for an execution that was not triaged as a product fault. |

Some checks are hard: no argument can override them. Others are soft: they refuse a likely mistake and show the evidence, and the model may confirm the record with `confirm: true` when it has a reason. The confirmation is stored with the record, so a reviewer can see it.

There is no tool that sets a test result, a metric or the release decision. Results come only from the JUnit XML written by the test run, and metrics and the decision are computed from stored records ([ADR-0006](../adr/0006-deterministic-statuses-metrics-and-release.md)). This is the main protection of RetroAgent: a model can be wrong, or be misled by text planted in the project, but it cannot falsify a result.

### Servers never call the model

MCP allows a server to ask the client for a model completion, which is called sampling. RetroAgent's servers never do it ([ADR-0020](../adr/0020-mcp-servers-never-call-the-model.md)). Text that only the model can write, such as a triage justification or the narrative of a report, reaches a server only as a tool argument. The servers are therefore deterministic: the same records always give the same metrics, the same decision and the same report data. They are tested without any model.

### More servers

A user or a project can declare more MCP servers, for example one that reads an issue tracker. Their tools are offered to the model next to the bundled ones, after the user approves them. They cannot use the name of a bundled server. See [Add MCP servers](../how-to/add-mcp-servers.md).

## How the three meet in one step

Take the triage step of `/cycle`.

1. **The runtime prepares the call.** The conversation starts empty. The model receives the steering, `RETRO.md` as the project description, the index of skills, the tools of this step only, and a state message that names the step and summarizes project memory.
2. **The model loads the skill.** It calls `runtime__load_skill` with `failure-triage`, and the procedure enters the context.
3. **The model reads through tools.** `memory__get_executions` lists the failed executions of the candidate run. `test_runner__get_evidence` returns the JUnit entry and the log of each one. `memory__get_test_case_history` tells whether the test passed on the baseline.
4. **The model judges, and the server checks.** For the shipping test, the model calls `memory__save_triage` with `regression` and a justification. The server checks that the test did not fail on the baseline, and stores it. Then `memory__register_defect` registers the defect, and the server checks that the execution was triaged as a product fault.
5. **The model answers, and the runtime shows what was recorded.** Below the answer, a line computed from the tool calls lists the writes that succeeded: two triages, one defect, and so on. If the answer claims more than that, the line shows it.
6. **Code checks the step.** Before the report step starts, the runtime checks that no failed execution of the candidate run is left without triage. If one is, the step runs once more with a message that says what is missing.

Each part does what it is good at. The steering keeps the model honest in every step. The skill gives it a procedure for this step and nothing else. The tools give it facts, and refuse what the facts do not support. The runtime decides the order of the steps and checks the outcome of each one.

## Why not one long prompt

The simplest agent is one long prompt with every rule and procedure in it, and tools that store whatever the model sends. RetroAgent splits the work for three reasons.

- **Context is limited.** A small local model has a window of about 32,000 tokens. The fixed part of a step, with steering, the project description, one skill and the tools of the step, uses about a third of it. With every procedure and every tool always loaded, a small model would have no room left to read a diff.
- **Instructions are not guarantees.** "Never classify a failure as an expected change without a documented change" can be written in a prompt, and models still do it. It was observed during development with both a hosted and a local model. A check in a tool cannot be talked around.
- **Each part can change alone.** A team can change a procedure without touching code, add a tool without changing a prompt, and change a model without changing either. RetroAgent does not depend on any model vendor ([ADR-0002](../adr/0002-model-agnostic-runtime.md)).

Since development started, several failures of real models were fixed by adding a check in code, in a tool or in the runtime, not by adding a sentence to a skill: an invented trace between a test and a requirement, defects registered for tests that did not fail, a regression claimed for a test that also failed on the baseline, and a model that called the same read tool dozens of times. The rule followed was simple: if a mistake can be detected from the records, code detects it.
