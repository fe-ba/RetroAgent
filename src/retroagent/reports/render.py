"""Templates and markers (ADR-0018, ADR-0019; reports.md, Template resolution).

Markers are resolved in a single pass over the template: what a value or a block inserts is never read again, so
text that comes from memory or from the model cannot act as a marker. An unresolved marker is an error.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import retroagent.resources

TEMPLATES = Path(retroagent.resources.__file__).parent / "templates"

# Whole-line comments take their line with them; an agent marker is a comment that is kept.
_LINE_COMMENT = re.compile(r"^[ \t]*<!--(?!\s*agent:).*?-->[ \t]*\n?", re.DOTALL | re.MULTILINE)
_COMMENT = re.compile(r"<!--(?!\s*agent:).*?-->", re.DOTALL)
_MARKER = re.compile(r"\{\{\s*(.*?)\s*\}\}")
_AGENT = re.compile(r"<!--\s*agent:\s*(.*?)\s*-->")
BLOCK_KINDS = ("table", "list", "items")


class ReportError(Exception):
    """A template cannot be resolved. The message names the marker and the template."""


@dataclass
class Scope:
    """What the markers of a template refer to: values, blocks and, for the top level, the elements of items."""

    values: Mapping[str, str]
    blocks: Mapping[str, Callable[[], str]] = field(default_factory=dict)  # "table:risks" -> text
    items: Mapping[str, list["Scope"]] = field(default_factory=dict)  # "test_case" -> one scope per element


def find_template(name: str, language: str, *, items: bool = False) -> Path:
    """``templates/<language>/`` first, then ``templates/`` (and the same under ``items/``)."""
    folder = Path("items") if items else Path()
    for base in (TEMPLATES / language, TEMPLATES):
        path = base / folder / name
        if path.is_file():
            return path
    raise ReportError(f"template {folder / name} does not exist")


def strip_comments(text: str) -> str:
    return _COMMENT.sub("", _LINE_COMMENT.sub("", text)).strip("\n")


def agent_names(text: str) -> list[str]:
    """The agent sections of a Markdown text, in order."""
    return [m.group(1) for m in _AGENT.finditer(text)]


def chart_references(text: str) -> list[str]:
    """The chart files a template references: ``charts/<name>.svg``."""
    return re.findall(r"\(charts/([\w-]+\.svg)\)", text)


class Renderer:
    """Resolves every marker of a template except the agent ones, which stay in place as comments."""

    def __init__(self, language: str, agent_sections: Mapping[str, str]):
        self.language = language
        self.agent_sections = agent_sections  # name -> purpose: the sections the template may mark

    def render(self, template: str, scope: Scope, *, in_item: bool = False) -> str:
        path = find_template(template, self.language, items=in_item)
        lines = strip_comments(path.read_text(encoding="utf-8")).split("\n")
        return "\n".join(self._line(line, scope, template, in_item) for line in lines)

    def _line(self, line: str, scope: Scope, template: str, in_item: bool) -> str:
        agent = _AGENT.search(line)
        if agent:
            if _AGENT.fullmatch(line.strip()) is None:
                raise ReportError(f"the agent section marker {agent.group(0)!r} in {template} is not alone on its line")
            if agent.group(1) not in self.agent_sections:
                raise ReportError(f"unknown agent section {agent.group(1)!r} in {template}")
            return line.strip()
        alone = _MARKER.fullmatch(line.strip())
        if alone and alone.group(1).partition(":")[0] in BLOCK_KINDS:
            return self._block(alone.group(1), scope, template, in_item)
        return _MARKER.sub(lambda m: self._value(m.group(1), scope, template), line)

    def _value(self, name: str, scope: Scope, template: str) -> str:
        if name.partition(":")[0] in BLOCK_KINDS:
            raise ReportError(f"the marker {{{{ {name} }}}} in {template} is not alone on its line")
        try:
            return scope.values[name]
        except KeyError:
            raise ReportError(f"unknown marker {{{{ {name} }}}} in {template}") from None

    def _block(self, name: str, scope: Scope, template: str, in_item: bool) -> str:
        kind, _, element = name.partition(":")
        if kind == "items":
            if in_item:
                raise ReportError(f"{{{{ {name} }}}} in {template}: an item template cannot contain items")
            if element not in scope.items:
                raise ReportError(f"unknown marker {{{{ {name} }}}} in {template}")
            item_template = element.replace("_", "-") + ".md"
            return "\n\n".join(self.render(item_template, item, in_item=True) for item in scope.items[element])
        if name not in scope.blocks:
            raise ReportError(f"unknown marker {{{{ {name} }}}} in {template}")
        return scope.blocks[name]()


def agent_block(model: str, text: str) -> str:
    """An agent section as it appears in a report (reports.md, Agent sections)."""
    text = text.strip() or "Not provided."
    quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())
    return f"> **Agent analysis** · written by `{model}`, not computed.\n>\n{quoted}"


def add_agent_sections(draft: str, model: str, sections: Mapping[str, str]) -> str:
    """Replace the agent markers of a draft; a section that was not written is ``Not provided.``."""
    return "\n".join(
        agent_block(model, sections.get(m.group(1), "")) if (m := _AGENT.fullmatch(line.strip())) else line
        for line in draft.split("\n")
    )
