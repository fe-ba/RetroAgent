# ADR-0020: MCP servers never call the model

- **Status:** Accepted. Channel of the session context defined by ADR-0026
- **Date:** 2026-11-15

## Context

Some operations need text that only the model can write: the agent sections of a report, a triage justification, a test case design. The MCP servers that store or render that text could obtain it in two ways: by asking the model themselves, or by receiving it from the model as tool arguments. MCP allows the first through sampling, where a server asks the client to run a completion.

At the same time, the guarantees of ADR-0006 depend on servers being deterministic: the same stored data must always produce the same metrics, decision and report data.

## Decision

- MCP servers never call a model, directly or through sampling. Text written by the model reaches a server only as a tool argument.
- Report generation takes two steps: `reports.prepare_report` computes everything and lists the agent sections to write; the model writes them; `reports.render_report` produces the files.
- The session context (project, session, versions, model name) is passed to the servers by the runtime with every call, never by the model.

## Alternatives considered

- **Sampling:** a single report call, but servers would depend on model behavior, become hard to test, and not every MCP client supports sampling.
- **Servers with their own model access:** duplicates provider configuration in every server and breaks ADR-0002.
- **Model provides the session context:** simpler tool signatures, but the model could record actions under another model or version.

## Consequences

- Every server can be tested without a model.
- A report needs two tool calls and one model turn in between; a report whose agent sections are never written stays `draft`.
- Records such as `designed_by` and `triaged_by` always name the model that actually acted.
