# ADR-0014: Untrusted project configuration

- **Status:** Accepted. Extended by ADR-0024
- **Date:** 2026-11-14

## Context

The project configuration (`.retro/config.yaml`, `.retro/mcp.json`) is stored inside the target project and travels with it. A cloned repository is not necessarily trustworthy. If its configuration could define model endpoints, it could send the user's API keys to a third party. If it could loosen permissions or start MCP servers, it could run arbitrary code without the user noticing.

## Decision

- Model profiles (`models`) are defined only at user level. A project can only select a profile by name.
- At project level, permissions can only be made stricter, never looser.
- MCP servers declared by a project require user approval the first time they are used. Approvals are stored in `~/.retro/approvals.json`.
- The permission mode cannot be set in any configuration file; only with `--mode` or `/mode`.

## Alternatives considered

- **Trust project configuration fully:** simplest, but exposes API keys and allows silent code execution.
- **Ignore project configuration entirely:** safe, but every user would have to configure every project by hand.

## Consequences

- A shared project configuration is safe to version and to clone.
- Some settings must be repeated at user level on each machine.
- Validation must know the allowed level of every key and reject violations with exit code `2`.
