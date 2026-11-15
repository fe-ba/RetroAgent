# ADR-0024: Execution safety

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

ADR-0014 treats the configuration of a target project as untrusted: it cannot define model endpoints, loosen permissions or start MCP servers without approval. A review found that the protection stopped short of the place where a project runs code:

- `tests.setup`, `tests.command`, `tests.select`, `service.start` and `tests.env` are written in the project. The permission prompt showed the arguments of the tool (version and scope), not the commands, so a cloned repository could run any command after one generic approval, or with none in mode `auto`.
- Test processes inherited the environment of `retro`, including the API keys of the user.
- Generated test code was written and run without the user seeing it.
- Worktrees were created under `.retro/worktrees/`, inside the project. Tools that search parent directories for configuration or dependencies could find those of the working copy while testing another version.
- The session lock was a file. A session that crashed left it behind and blocked the next one.

## Decision

1. **Project commands need an approval of their content.** The setup, test, selection and service commands and `tests.env` run only after the user saw and approved them. The approval is stored at user level as a hash and is asked again when any of them changes. Non-interactive mode never approves; `--trust-commands` approves for one session. Every approval of project content (commands, MCP servers, steering, skills) covers the exact content approved.
2. **Subprocesses never receive model credentials.** Setup, test and service commands and every MCP server start without the variables that hold API keys.
3. **Permission prompts show what will run.** The prompt for writing a test shows the code, or the difference in a rewrite. The prompt for a run shows the commands.
4. **Worktrees live outside the project,** under `~/.retro/worktrees/<project-id>/`. This amends the location chosen in ADR-0009; the decision to use worktrees stands. A directory kept between runs, `{cache_dir}`, is offered to setup commands, because worktrees are new for every run.
5. **The session lock is an operating-system file lock.** It is released when the process ends, however it ends.
6. **Commands run in their own process group,** which is terminated as a whole on timeout, interruption or end of session.
7. **RetroAgent does not claim to be a sandbox.** The documentation says so and recommends a container or a virtual machine for repositories that are not trusted.

## Alternatives considered

- **Show the commands in the permission prompt of every run:** no stored approval is needed, but the user sees the same text at every run and stops reading it, and mode `auto` skips the prompt.
- **Run tests inside a container:** real isolation, but it requires a container runtime on every machine, breaks offline use and is a project of its own.
- **Static checks on generated test code:** easy to bypass and give false confidence.
- **Keep worktrees in `.retro/` and tell projects to set a root marker:** depends on every tool of every language honoring it.
- **A lock file with a process identifier, checked at start:** works on one machine, but identifiers are reused and the check differs per platform; the operating system already solves it.
- **Reuse one worktree per commit across runs:** avoids repeating the setup, but lets one run leave files that change the next one.

## Consequences

- A repository cloned from elsewhere cannot run a command, start a server or load an instruction without the user having seen it.
- CI needs `--trust-commands`, or an approval stored for the CI user. In mode `auto` nobody reviews generated test code; CI should run tests that were written and reviewed before, with `permissions.write_tests` set to `deny`.
- Tests that need a credential of their own must receive it through `tests.env` or the environment, under a name that is not a model credential.
- Setup runs for every run. `{cache_dir}` reduces the cost; it does not remove it.
- `retro init` no longer lists `worktrees/` in `.retro/.gitignore`.
- Residual risk, accepted and documented: approved commands, project tests and generated tests run with the privileges of the user.
