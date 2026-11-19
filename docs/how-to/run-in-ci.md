# Run in CI

How to run RetroAgent without a session, in a script or a CI pipeline, and use its exit code to gate a release. The options are in the [CLI reference](../reference/cli.md).

## The non-interactive command

```
retro -p --mode auto --trust-commands --base v1.0 --candidate v1.1 "/cycle"
```

| Option | Why |
|---|---|
| `-p` | Runs the prompt and exits. A slash command as the prompt runs that command; `/cycle` runs every step, each as its own turn. |
| `--mode auto` | Performs the actions the configuration allows without asking. In mode `default` there is nobody to answer, so every action that needs permission is refused and the command exits with `4`. |
| `--trust-commands` | Approves the setup, test and service commands of the project for this run only, without storing anything. Without it, and without an approval stored on that machine, running tests is refused. Use it only for a repository of your own. |
| `--base`, `--candidate` | The versions to compare. They override `versions.*` of the project. |

Add `--output-format json` to get one JSON object instead of the answer text, with the decision, the runs, the reports, what was recorded and the exit code:

```
retro -p --mode auto --trust-commands --output-format json "/cycle" > retro-result.json
```

## The exit code

| Code | Meaning | In a pipeline |
|---|---|---|
| `0` | Completed. If a decision was produced, it is `release` or `release_with_conditions`. | Pass. |
| `3` | Completed, with decision `do_not_release`. | Fail the release gate. |
| `4` | An action needed a permission or an approval that was not granted. | Fix the configuration or the options. |
| `2` | Invalid usage or configuration, a missing credential, or a ref that does not resolve. | Fix the job. |
| `1` | Runtime error: the model, a tool, or an unexpected failure. | Retry or investigate. |

When several apply, `1` wins over `4`, `4` over `3`, and `3` over `0`. A cycle that stopped in the middle has its work in `.retro/retro.db`; keep it with the artifacts if you want to inspect or continue it.

## Choose what the pipeline may do

`/cycle` designs and implements new tests, and in mode `auto` nobody reviews that code before it runs. Two ways to handle it:

**Review generated tests before CI runs them (recommended).** Run the cycle in an interactive session on your machine and review the tests the agent writes in `.retro/tests/`. Move the ones you keep into the project's own test folder, keeping the requirement in their names, and commit them: from then on they are tests of the project. Generated tests left in `.retro/tests/` are run only by the project memory that created them, and a fresh CI checkout has no project memory. In CI, forbid new test code and run the steps that do not write it:

```yaml
# .retro/config.yaml of the project, or the user configuration of the CI machine
permissions:
  write_tests: deny
```

```
retro -p --mode auto --trust-commands "/analyze"
retro -p --mode auto --trust-commands "/run all --on both"
retro -p --mode auto --trust-commands "/select"
retro -p --mode auto --trust-commands "/run --on both"
retro -p --mode auto --trust-commands "/triage"
retro -p --mode auto --trust-commands "/report completion"
```

Each command is a session of its own; project memory in `.retro/retro.db` carries the state from one to the next, so run them in the same job and the same checkout. The versions come from `versions.*` of the project; to compare others, add the same `--base` and `--candidate` to every command. The exit code of the last one carries the decision.

**Let the agent write tests in CI.** Run `/cycle` as above, on a repository of your own, in an isolated runner, and keep `.retro/tests/` as an artifact to review afterwards. A refused write stops the cycle with exit code `4`, so do not combine this with `write_tests: deny`.

## The model in CI

- **Hosted model:** store the key as a secret of the CI service, expose it as the variable that the profile names in `api_key_env`, and never print it. Set `requests_per_minute` if the plan has a low limit. A day of many pipelines can exhaust a daily quota; the run then fails with exit code `1` and a message that names the limit.
- **Local model:** the CI machine needs Ollama and the model, and a small model on a CPU takes about an hour per cycle. Use it on a self-hosted runner with a GPU, or not at all in CI.

The model profile must be in the user configuration of the CI machine, `~/.retro/config.yaml`, or in a directory given by `RETRO_HOME`. A project cannot define it. Select the profile with `-m` or `RETRO_MODEL`.

## Example: GitHub Actions

```yaml
name: regression
on:
  push:
    tags: ["v*"]

jobs:
  retro:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0              # every tag and commit, for the two versions
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install RetroAgent
        run: pip install git+https://github.com/fe-ba/RetroAgent.git
      - name: Model profile
        run: |
          mkdir -p ~/.retro
          cat > ~/.retro/config.yaml <<'EOF'
          model: gemini
          models:
            gemini:
              provider: google
              name: gemini-3.1-flash-lite
              api_key_env: GEMINI_API_KEY
              requests_per_minute: 12
          EOF
      - name: Regression cycle
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          BASE=$(git describe --tags --abbrev=0 HEAD^)
          retro -p --mode auto --trust-commands --base "$BASE" --candidate "$GITHUB_REF_NAME" "/cycle"
      - name: Keep the evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: retro
          path: |
            .retro/reports/
            .retro/runs/
            .retro/tests/
            .retro/retro.db
```

`fetch-depth: 0` matters: with the default shallow checkout, the base version is not in the repository and the command exits with `2`. For PDF reports, also install Pango (`sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0`); without it, reports are Markdown.
