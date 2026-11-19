# Add MCP servers

How to give the agent the tools of another MCP server, for example one that reads your issue tracker or your documentation. The format is in the [configuration reference](../reference/configuration.md#mcp-servers). Why RetroAgent uses MCP is explained in [MCP, skills and steering](../explanation/mcp-skills-steering.md).

## Declare the server

Servers are declared in a file `mcp.json`, in the format that other agents also use:

```json
{
  "mcpServers": {
    "docs": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/specs"],
      "env": {}
    }
  }
}
```

| Field | Meaning |
|---|---|
| Key (`docs`) | The name of the server. Its tools are shown to the model as `docs__<tool>`. |
| `command`, `args` | How to start the server. It runs as a separate process and talks to RetroAgent over standard input and output. |
| `env` | Extra environment variables for the server. |

The name cannot be `git`, `memory`, `test_runner`, `reports` or `runtime`. A server that uses one of them is not connected, and the conflict is reported.

## Choose the level

| File | Applies to | Approval |
|---|---|---|
| `~/.retro/mcp.json` | Every project you open. | None: it is your own configuration. |
| `<project>/.retro/mcp.json` | That project. Versioned with it, so it reaches everyone who clones it. | Asked once, at the start of the first interactive session, and again whenever the declaration changes. |

A project server is code written by whoever wrote the repository, so it starts only after you have seen and approved its declaration. In non-interactive mode a project server that is not approved is not loaded, and a warning is printed; mode `auto` never approves one.

## Check it

Start a session and run:

```
/mcp
```

It lists every connected server with its tools. A server that does not start, or that is not approved, is not listed, and the session says why at start.

## What the server receives

- RetroAgent removes every model credential from the environment of the server: the variables named in `api_key_env` of your profiles and the usual provider key variables. A server never needs a model key, and never gets one.
- If the server needs a credential of its own, such as a token for your issue tracker, put it in `env`. In a project file, refer to it instead of writing it there.

## Where the model can use its tools

The tools of an additional server are offered in free messages: when you write to the agent in plain language, for example "read the acceptance notes for REQ-004 in the docs server and tell me whether the design of TC-027 covers them".

The steps of `/cycle` and the model commands (`/analyze`, `/select`, `/design`, ...) expose only the tools of their step, which are the bundled ones. This keeps their context small and their behavior predictable. To use an additional server inside a step, run the step and then continue it with a free message that names what to read.

## Write a server of your own

Any MCP server works, in any language. For tools that the agent will rely on, follow the rules of the bundled servers:

- Never call a model from the server. Text that only the model can write arrives as a tool argument.
- Check what can be checked, and refuse with a message that says why and what to do instead.
- Return what was recorded, with its identifiers, so that the model can name it.
