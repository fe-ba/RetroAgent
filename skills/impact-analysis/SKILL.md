---
name: impact-analysis
description: Analyze the change between the baseline and the candidate. Computes the change set, maps it to modules and requirements with a risk level, and registers risks. Use for /analyze, or when asked what changed or what a change can break.
---

# Impact analysis

Find what the change between the session versions can break, and record it so that selection, design and reports can use it.

## Procedure

1. **Versions.** If the user named refs that differ from the session versions, call `runtime.set_versions`. If the session versions are `not set` and no refs were given, ask the user for them and stop.
2. **Requirements.** Call `memory.sync_requirements`.
   - `invalid_state`: the project has no requirements configured. Continue; the analysis reaches modules only. Say so and suggest setting `project.requirements`.
   - Files that could not be parsed: name them in the answer.
3. **Change set.** Call `git.analyze_changes`. Keep the analysis ID. If the change set is empty, say so and stop.
4. **Read the changes.** Call `git.get_diff` for each changed file that can affect behavior: source code, configuration, schemas, dependency manifests. Files that cannot affect behavior (documentation, formatting only) can be judged from their path, and must be named as such. When a diff lacks context, read the file with `git.read_file`. When a result is `truncated`, call the tool again with `start_line` set to the `next_line` it returned, until everything that can affect behavior is read. Say which part was not read, if any.
5. **Modules.** Group the changed files into modules, using the modules described in `RETRO.md` or the directory structure (`git.list_files`). Assign each module a risk level:

   | Level | When |
   |---|---|
   | `high` | Changes behavior of core logic (calculations, money, authentication, permissions, stored data), of a public interface, or of a high-priority requirement; or removes or renames something other code uses. |
   | `medium` | Changes behavior of a secondary feature, configuration that alters behavior, or dependency versions. |
   | `low` | No visible change of behavior: refactoring, renaming of internals, comments, formatting, tests only. |

   The reason states what changed in the diff and why it matters, in one or two sentences.
6. **Requirements.** Call `memory.get_requirements`. A requirement is impacted when:
   - a module that implements it changed, judged from its description and the diff;
   - an existing test case traced to it covers a changed module (`memory.get_test_cases` with `requirement_id`);
   - it has a `Changed` or `Removed` entry for the candidate version. Mark the reason as a documented change: failures in that area may be `expected_change` during triage.
7. **Record.** Call `memory.save_impact` with the analysis ID, the modules (files exactly as in the change set) and the impacted requirements with their reasons. An empty list of requirements is valid.
8. **Risks.** Call `memory.add_risk` for each distinct way the change could harm the product, linked to its requirements. Consolidate: one risk per failure scenario, not one per file. Also register a risk when an impacted area has no requirement or no test case.
9. **Answer** with:
   - the analysis ID and the counts of changed files;
   - a table of impacted modules: module, files, risk level, reason;
   - the impacted requirements and their reasons, documented changes first;
   - the registered risks with their IDs;
   - missing information and its effect;
   - next step: `/select`.

## Rules

- Never claim that behavior changed without a line of the diff that shows it.
- A requirement change documented for the candidate is expected, but it still needs tests: the tests that verify the old behavior must be reviewed.
- The analysis judges impact; it does not judge whether the change is correct. That is what the tests are for.
