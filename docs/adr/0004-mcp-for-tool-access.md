# ADR-0004: MCP for tool access

- **Status:** Accepted. Folder layout amended by ADR-0025; use by other MCP clients amended by ADR-0026
- **Date:** 2026-11-14

## Context

The agent must act on real systems: read git history, run tests, store results and generate reports. The project brief requires MCP.

## Decision

Every action on the outside world goes through MCP servers. RetroAgent bundles four: `git`, `test_runner`, `memory` and `reports`. Projects can add their own in `.retro/mcp.json`.

## Alternatives considered

- **Direct function calls from the runtime:** simpler, but does not meet the brief and tools are not reusable by other MCP clients.

## Consequences

- MCP servers are thin layers over logic in `src/retroagent/`; logic is not duplicated.
- The folder is named `mcp_servers`, never `mcp`: a top-level `mcp` package would shadow the official MCP Python SDK.
- Bundled tools can be used by any MCP client, not only RetroAgent.
