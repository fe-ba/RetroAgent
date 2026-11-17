---
name: impact-analysis
description: Analyze the change between the baseline and the candidate. Computes the change set, maps it to modules and requirements with a risk level, and registers risks. Use for /analyze, or when asked what changed or what a change can break.
---

# Impact analysis

Find what the change between the session versions can break, and record it so that selection, design and reports can use it.

## Procedure

1. **Versions.** If the user named refs that differ from the session versions, call `runtime__set_versions`. If the session versions are `not set` and no refs were given, ask the user for them and stop.
2. **Requirements.** Call `memory__sync_requirements`.
   - `invalid_state`: the project has no requirements configured. Continue; the analysis reaches modules only. Say so and suggest setting `project.requirements`.
   - Files that could not be parsed: name them in the answer.
3. **Change set.** Call `git__analyze_changes`. Keep the analysis ID. If the change set is empty, say so and stop.
4. **Read the changes.** Work one file at a time: read its diff, then write in one or two lines what changed and which behavior it can affect, before reading the next file. Old results can be removed from the context; what you wrote stays. Call `git__get_diff` for every changed file that can affect behavior: source code, configuration, schemas, dependency manifests. Do not skip a source file because its name looks unrelated to the purpose of the change. Files that cannot affect behavior (documentation, formatting only) can be judged from their path, and must be named as such. When a diff lacks context, read the file with `git__read_file`. When a result is `truncated`, call the tool again with `start_line` set to the `next_line` it returned, until everything that can affect behavior is read. Say which part was not read, if any.
5. **Modules.** Group the changed files into modules, using the modules described in `RETRO.md` or the directory structure (`git__list_files`). Assign each module a risk level:

   | Level | When |
   |---|---|
   | `high` | Changes behavior of core logic (calculations, money, authentication, permissions, stored data), of a public interface, or of a high-priority requirement; or removes or renames something other code uses. |
   | `medium` | Changes behavior of a secondary feature, configuration that alters behavior, or dependency versions. |
   | `low` | No visible change of behavior: refactoring, renaming of internals, comments, formatting, tests only. |

   The reason states what changed in the diff and why it matters, in one or two sentences.
6. **Requirements.** Call `memory__get_requirements`. Then go through the requirements one by one, all of them, and decide each: impacted or not, and why. A requirement is impacted when:
   - a file that takes part in its behavior changed, even when the change was made for another requirement. A file that computes several things impacts every requirement about those things: a change made for one feature that breaks another is what a regression is;
   - it has a `Changed` or `Removed` entry for the candidate version. Mark the reason as a documented change: failures in that area may be `expected_change` during triage;
   - it is new in the candidate version. Say so in the reason.

   When in doubt, mark it impacted: a requirement left out is not tested, and one too many only adds tests. Leave out only the requirements whose behavior no changed file takes part in, and name them in the answer with that reason.
7. **Record.** Call `memory__save_impact` with the analysis ID, the modules (files exactly as in the change set) and the impacted requirements with their reasons. An empty list of requirements is valid.
8. **Risks.** Call `memory__add_risk` for each distinct way the change could harm the product, linked to its requirements. Consolidate: one risk per failure scenario, not one per file. Also register a risk when an impacted area has no requirement or no test case.
9. **Answer** with:
   - the analysis ID and the counts of changed files;
   - a table of impacted modules: module, files, risk level, reason;
   - the impacted requirements and their reasons, documented changes first, then the requirements judged not impacted;
   - the changed files that were not read, and why;
   - the registered risks with their IDs;
   - missing information and its effect;
   - next step: `/select`.

## Rules

- Never claim that behavior changed without a line of the diff that shows it.
- A requirement change documented for the candidate is expected, but it still needs tests: the tests that verify the old behavior must be reviewed.
- The analysis judges impact; it does not judge whether the change is correct. That is what the tests are for.
