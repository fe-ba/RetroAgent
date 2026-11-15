# ADR-0025: Package layout

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

ADR-0001 requires steering, skills and templates to ship inside the installed package, because `retro` runs from any directory. They were kept at the root of the repository, next to a top-level `mcp_servers` folder, outside `src/retroagent/`. How they would reach the installed package was not decided, and a top-level package named `mcp_servers` would be installed under a generic name that another distribution could also use.

## Decision

Everything that ships is inside the package:

| Content | Location |
|---|---|
| Steering, skills, templates and examples | `src/retroagent/resources/` |
| Bundled MCP servers | `src/retroagent/servers/` (`retroagent.servers.<name>`) |
| Default configuration | `src/retroagent/defaults/` |

Code reads resources through the package (`importlib.resources`), never through a path relative to the repository.

## Alternatives considered

- **Keep the folders at the root and include them from `pyproject.toml`:** the root shows at a glance what the course evaluates, but it depends on the build backend, and an editable installation does not contain the files, so the code needs a second way to find them.
- **Move only the servers and keep steering, skills and templates at the root:** fixes the package name, keeps the double lookup.

## Consequences

- An installed package and a development checkout find resources the same way.
- The name `mcp_servers` disappears. The rule of ADR-0004 against a top-level `mcp` package no longer applies, because nothing is top-level.
- The steering and the skills are no longer visible at the root; `README.md` must point to them.
- Paths such as `steering/` or `templates/` in earlier ADRs and in the reference documentation are relative to `src/retroagent/resources/`.
