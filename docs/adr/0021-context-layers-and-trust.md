# ADR-0021: Context layers and trust

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

The context of the model combines sources with different authors. Bundled steering and skills come with RetroAgent; user steering and skills come from the user. `RETRO.md`, project steering and skills, and the content of files, diffs and logs come from the target project, which may not be trustworthy (ADR-0014). Any of them can contain text that tries to change the behavior of the model, for example an instruction to mark every test as passed: a prompt injection.

## Decision

| Source | Treated as | Rule |
|---|---|---|
| Bundled steering and skills | Instructions | Always loaded; never replaced or disabled. |
| User steering and skills | Instructions | Steering is added after the bundled steering. A user skill may replace a bundled skill with the same name. |
| Project steering and skills | Instructions, after approval | Loaded only after the user approves them; approvals are stored with MCP approvals in `~/.retro/approvals.json`. They never replace bundled or user steering and skills. |
| `RETRO.md` | Information | Presented as a description of the project, not as rules. |
| Tool results | Data | Files, diffs, logs and evidence never change the rules. |

The bundled steering states that additional rules and project content never override it.

## Alternatives considered

- **Treat every source equally:** simplest, but any repository could instruct the agent.
- **Forbid project steering and skills:** safest, but removes per-project customization (FR-31).
- **Rely only on the model to resist injection:** models can be misled, and some are easily misled.

## Consequences

- Project-level customization requires one approval per project.
- Prompt injection is reduced but not eliminated: a misled model can still design poor tests or write a misleading analysis.
- It cannot falsify results: no tool accepts an execution status or result (ADR-0006, INV-03), and metrics and the release decision are computed by code. This is the main protection.
