# ADR-0027: Context budget and cycle command

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

The runtime kept the whole conversation until the user cleared it, and stopped when a call would exceed the context window. Three problems followed:

- A full regression cycle asked in one prompt is one turn: dozens of diffs, designs and triage calls within one iteration limit and one context. In non-interactive mode there is no `/clear`, so the cycle could not finish on a large change.
- Local models have small context windows, and a local server may apply a smaller default than the model allows and drop the beginning of the context without an error. The beginning is the steering.
- Every tool was always defined, which is a large fixed cost for a small model.

The project is to be presented with local models when they perform well enough, so these are not edge cases.

## Decision

1. **The context window is always known.** It comes from the model profile or from the provider; local profiles must state it, and the runtime sends it to servers that accept a context size. A model whose window cannot hold twice the fixed part of the context is refused at start.
2. **The runtime frees context by replacing old tool results with a note.** Steering, user messages, model answers and loaded skills are never replaced. Project memory keeps the facts, so the model can read them again. The conversation is never summarized by a model.
3. **`/cycle` runs the regression cycle one step at a time.** The runtime decides the order. Each model step is a turn with an empty conversation, the tools of that step only, and its own iteration limit. After each step, code checks its outcome in project memory, retries the step once when the outcome is missing, and stops the cycle otherwise.
4. **Model commands expose only the tools of their skill.**

## Alternatives considered

- **Summarize the conversation with the model when it grows:** common in terminal agents, but a summary can state a result that no tool returned, which is what ADR-0006 exists to prevent.
- **One long turn with a higher iteration limit:** no new command, but the context still grows without bound and a failure in step eight repeats the first seven.
- **A fixed pipeline without the model between steps:** the steps that need judgment (impact, selection, design, triage, report sections) are the purpose of the agent.
- **Let the model choose its tools from all of them, always:** simplest, and adequate for large hosted models, but it spends a large share of a small context window.

## Consequences

- A cycle can finish with a small context window, and can resume after a failure from the step that failed.
- The order of the cycle is in code; the steering describes it to the model but no longer has to enforce it.
- Each step must find everything it needs in project memory. A step that relies on something said in an earlier step is a defect of its skill.
- Free conversation still works as before, with every tool and the context budget.
- The step outcomes checked by code are minimal on purpose: they prove that the step left its records, not that its judgment was good.
