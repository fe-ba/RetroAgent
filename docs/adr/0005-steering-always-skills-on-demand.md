# ADR-0005: Steering always loaded, skills on demand

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

Some instructions apply to every task (rules, limits, output format). Others apply only to specific tasks (impact analysis, failure triage). Loading everything always wastes context and dilutes critical rules.

## Decision

Files in `steering/` are always injected into the context, ordered by their numeric prefix. Skills expose only their name and description; the model loads a full `SKILL.md` through a tool when it needs it. Projects and users can add their own steering and skills in `.retro/` and `~/.retro/`.

## Alternatives considered

- **Single system prompt:** wastes context, buries critical rules, cannot be maintained or tested by parts.
- **Load all skills always:** simpler, same context and dilution problems.

## Consequences

- Load order of steering is deterministic and visible in file names.
- `SKILL.md` keeps the common format (frontmatter with `name` and `description`) so skills are portable to other agents.
- This is the practical answer to why a single prompt is not enough.
