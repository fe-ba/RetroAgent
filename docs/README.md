# RetroAgent documentation

The documentation follows Diataxis (ADR-0013): tutorials to learn, how-to guides to get a task done, reference to look things up, and explanation to understand why. Decision records are in `adr/`. The internal specification that the code was built from is in `../spec/`; when it and these documents disagree, the specification wins.

## Tutorials

| Document | What you do |
|---|---|
| [Getting started](tutorials/getting-started.md) | Install RetroAgent, configure a model and open a first session on the example project. |
| [Your first regression cycle](tutorials/first-regression-cycle.md) | Take the example from `v1.0` to `v1.1` step by step, and read the decision and the report. |

## How-to guides

| Document | Task |
|---|---|
| [Set up a project](how-to/set-up-a-project.md) | Prepare your own project: `retro init`, `RETRO.md`, requirements and test commands. |
| [Configure models](how-to/configure-models.md) | Add a hosted or a local model profile and switch between them. |
| [Compare versions](how-to/compare-versions.md) | Choose the baseline and the candidate, and run single steps instead of the whole cycle. |
| [Generate reports](how-to/generate-reports.md) | Produce the test plan, test cases, status, defects and completion reports, in Markdown or PDF. |
| [Run in CI](how-to/run-in-ci.md) | Run the cycle without a session and use the exit code. |
| [Add MCP servers](how-to/add-mcp-servers.md) | Give the agent the tools of another MCP server. |
| [Add skills and steering](how-to/add-skills-and-steering.md) | Add your own procedures and rules, at user or project level. |

## Reference

| Document | Contents |
|---|---|
| [CLI](reference/cli.md) | Commands, options, slash commands, permission modes and exit codes. |
| [Configuration](reference/configuration.md) | Levels, every key, model profiles, project commands and environment variables. |
| [Project contract](reference/project-contract.md) | What a project provides and what RetroAgent writes in it. |
| [MCP tools](reference/mcp-tools.md) | Every tool of the bundled servers, with its arguments, checks and errors. |
| [Metrics](reference/metrics.md) | Formulas of the metrics, exit criteria and the release decision. |
| [Reports](reference/reports.md) | Report types, templates and sections. |
| [Glossary](reference/glossary.md) | Terms used across the documentation. |

## Explanation

| Document | Topic |
|---|---|
| [Architecture](explanation/architecture.md) | Components, processes, data ownership, a turn and a cycle. |
| [MCP, skills and steering](explanation/mcp-skills-steering.md) | How the three mechanisms divide the work of the agent. |
| [Regression strategy](explanation/regression-strategy.md) | How a change becomes a suite: impact, selection, new tests and triage. |
| [Test states](explanation/test-states.md) | Status of a test case and result of an execution, and why they are separate. |
| [Metrics and exit criteria](explanation/metrics-and-exit-criteria.md) | Why the decision is computed and what each criterion protects. |
| [Project memory](explanation/memory.md) | What is kept between sessions, and who may write it. |
| [Test reports](explanation/test-reports.md) | How a report combines computed data with the agent's text. |
| [Model compatibility](explanation/model-compatibility.md) | What a model needs, and how the evaluated models behaved. |
| [Limitations and risks](explanation/limitations-and-risks.md) | Known limits and how they are handled. |

## Decision records

[`adr/`](adr/README.md) lists the 28 architecture decisions, each with its context, alternatives and consequences.
