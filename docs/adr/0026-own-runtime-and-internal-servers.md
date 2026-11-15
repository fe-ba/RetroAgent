# ADR-0026: Own runtime and internal servers

- **Status:** Accepted
- **Supersedes:** ADR-0002
- **Date:** 2026-11-15

## Context

ADR-0002 decided that RetroAgent implements its own runtime. The decision stands, but a review found its reasons weak:

- It stated that existing agent hosts only run the models of their vendor. That is not a safe premise: hosts change, some accept other providers, and open-source terminal agents work with many models.
- It stated that the test-state guarantees depend on control of the loop. By the design itself they do not: they are enforced by the data layer and by the tool contracts (ADR-0006, ADR-0016), and would hold under any MCP client.
- ADR-0004 stated that the bundled servers can be used by any MCP client, while ADR-0020 required a session context that only the runtime provides, without saying through which channel.

## Decision

RetroAgent implements its own runtime in Python, for these reasons:

1. **The course asks what MCP, skills and steering contribute.** Building the part that loads and combines them makes each contribution explicit, deterministic and testable byte for byte (`context-loading.md`). Inside another host, that part is a black box.
2. **Enforcement belongs to code this project controls.** Modes and permissions, the approval of project commands, the audit trail of every tool call, the context budget and the order of the cycle are guarantees of RetroAgent. A host that RetroAgent does not control could not be made to keep them.
3. **Local and hosted models must be a matter of configuration.** Which models a host accepts, and how well it serves local ones, is decided by the host.

What does not depend on the runtime is stated as such: no tool accepts a result, and metrics and the release decision are computed from stored evidence, whoever calls the tools.

The bundled MCP servers are internal components:

- Each server is started by the runtime for one project and one session.
- The session context (versions, model) is the `session` record of project memory, which only the runtime writes. Servers read it there. Nothing is passed through protocol extensions or by the model.
- Using the bundled servers from another MCP client is not supported: there would be no session, no permission check and no approval.

Bundled steering and skills name tools exactly as they are exposed to the model.

## Alternatives considered

- **Run inside an existing terminal agent:** far less code. Rejected because permissions, approvals, audit and context assembly would belong to the host, and extension formats differ between hosts.
- **Build on an agent framework or SDK:** provides the loop and the provider abstraction. Rejected because the loop is small (`runtime.md` specifies it in a page), LiteLLM already normalizes providers, and the parts that matter here would still have to be written on top of a large dependency.
- **Pass the session context with every tool call, as protocol metadata:** keeps servers stateless, but depends on how each SDK version exposes request metadata. A database record that the runtime writes is simpler to implement and to test.
- **Support other MCP clients:** would require the servers to enforce permissions and approvals themselves, which duplicates the runtime.

## Consequences

- The runtime is code this project must write and test. It must stay small: one loop, one permission table, one cycle.
- If the runtime is not finished, there is no supported degraded mode. This is the main schedule risk of the project and is listed in `limitations-and-risks.md`.
- Behavior can be compared across models with everything else fixed, which the acceptance scenarios use.
- The claim of ADR-0004 that any MCP client can use the bundled tools is withdrawn. MCP remains the only way the model acts on the outside world.
- Servers can be tested without a model and without the runtime, by creating a `session` record.
