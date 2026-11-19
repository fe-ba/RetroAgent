# Add skills and steering

How to add your own rules and procedures to the agent, for every project or for one project. What steering and skills are, and why they are separate, is explained in [MCP, skills and steering](../explanation/mcp-skills-steering.md).

## Steering or skill?

| Add | When the text is | Example |
|---|---|---|
| Steering | A rule that holds in every step | "Requirements of the payments module are always high priority." |
| A skill | A procedure for one kind of task | How to design tests for an API endpoint in your team's style. |

Steering is sent with every model call, so every line of it costs context in every call. Keep it short, and put procedures in skills.

## Add steering

Create a Markdown file named `NN-<name>.md`:

| Level | Folder | Loaded |
|---|---|---|
| User | `~/.retro/steering/` | In every project. |
| Project | `.retro/steering/` | In that project, after you approve it. |

```markdown
## Team rules

- Requirements of `src/payments/` are always `high` priority.
- Name generated test files after the requirement, for example `test_req_012_refunds.py`.
```

- Start the file with a level-2 heading (`##`): steering is placed under a level-1 heading.
- No frontmatter.
- Files load in ascending order of `NN` within each level: bundled first, then user, then project.
- Added steering never replaces the bundled steering. A file with the same name as a bundled one is added, not substituted, and the bundled rules state that additional rules never override them.
- Write tool names as the model sees them: `memory__save_triage`, not `memory.save_triage`.

## Add a skill

A skill is a folder with a `SKILL.md`:

```
~/.retro/skills/api-test-design/SKILL.md
```

```markdown
---
name: api-test-design
description: "Design tests for HTTP endpoints: status codes, error bodies and one test per documented field. Use when designing tests for anything under src/api/."
---

# API test design

1. Read the endpoint with `git__read_file` at the candidate version.
2. ...
```

| Field | Rule |
|---|---|
| `name` | Required. Equal to the folder name; lowercase letters, digits and hyphens. |
| `description` | Required, at most 300 characters. Say what the skill does and when to use it: this line is all the model sees until it loads the skill. Quote it when it contains a colon followed by a space. |

The body is the procedure. Number the steps, name the tools to call, and say what to record and when to stop. The bundled skills in `src/retroagent/resources/skills/` are examples to follow.

| Level | Folder | Rule |
|---|---|---|
| User | `~/.retro/skills/<name>/` | May replace a bundled skill with the same name. |
| Project | `.retro/skills/<name>/` | Loaded after you approve it. Cannot replace a bundled or user skill: a skill with the same name is skipped with a warning. |

A skill with an invalid header is skipped, and `/skills` shows why.

## Check it

```
/skills
```

lists every skill with its level and which one is loaded. A project's steering and skills are asked for approval at the start of the first interactive session, and again when they change. In non-interactive mode, items that are not approved are not loaded.

## How new skills are used

- **In free messages**, the model sees your skill in the index and loads it when its description matches the task. A clear description is what makes it load at the right time.
- **In `/cycle` and the model commands**, each step loads its bundled skill by name: `impact-analysis`, `test-selection`, `test-design`, `failure-triage` or `test-reporting`. A new skill with another name is not used there. To change how a step works, add a user skill with the same name as the bundled one: it replaces it in every step that loads it.

When you replace a bundled skill, copy it first and change it, rather than start from nothing: the bundled procedures contain what the tools of each step expect, and a step whose outcome is missing is retried once and then stops the cycle.
