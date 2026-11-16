"""Errors of the bundled servers, with the codes of docs/reference/mcp-tools.md (Errors)."""


class ToolError(Exception):
    """A tool call failed: ``code`` is ``invalid_argument``, ``not_found``, ``invalid_state``, ``denied``,
    ``execution_failed`` or ``unavailable``."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")
