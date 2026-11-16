"""The three charts of the completion report as SVG, drawn with matplotlib (reports.md, Charts; ADR-0018).

The output is deterministic: no date, text kept as text, a fixed salt for the generated identifiers and the font
that ships with matplotlib. The same data gives the same bytes, on any machine.
"""

import io
from collections.abc import Sequence
from fractions import Fraction

import matplotlib
from matplotlib.figure import Figure

from retroagent.metrics import NotEvaluable, Ratio
from retroagent.reports.blocks import AT_LEAST, fmt, percent
from retroagent.reports.render import ReportError

WIDTH = 640  # one SVG unit is one pixel: the figure is WIDTH / 72 inches at 72 dpi
ROW = 34
BAR, INK, GRID, PAPER = "#2a78d6", "#0b0b0b", "#e4e3df", "#fcfcfb"
RC = {
    "svg.fonttype": "none",
    "svg.hashsalt": "retroagent",
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
}
OUTCOMES = ("passed", "failed", "error", "blocked", "skipped")
COMPARISON = ("new_failures", "fixed", "persistent_failures", "stable_passes")


def _figure(height: int, title: str) -> Figure:
    fig = Figure(figsize=(WIDTH / 72, height / 72), dpi=72, facecolor=PAPER)
    fig.text(16 / WIDTH, 1 - 24 / height, title, fontsize=14, fontweight="bold", color=INK, va="baseline")
    return fig


def _save(fig: Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="svg", metadata={"Date": None}, facecolor=PAPER)
    return buffer.getvalue()


class _Panel:
    """Horizontal bars in a band of the figure, one row each, with a label after each bar."""

    def __init__(self, fig: Figure, height: int, top: int, rows: int, left: int, xmax: float, heading=None):
        self.height, self.rows, self.xmax = height, rows, xmax
        self.width_px = WIDTH - left - 16
        band = ROW * rows
        self.ax = fig.add_axes([left / WIDTH, 1 - (top + band) / height, self.width_px / WIDTH, band / height])
        self.ax.set_xlim(0, xmax)
        self.ax.set_ylim(rows, 0)
        for side in ("top", "right", "bottom"):
            self.ax.spines[side].set_visible(False)
        self.ax.spines["left"].set_color(GRID)
        self.ax.set_xticks([])
        self.ax.set_yticks([i + 0.5 for i in range(rows)])
        self.ax.tick_params(axis="y", length=0, labelsize=12, labelcolor=INK)
        self.ax.set_facecolor(PAPER)
        if heading:
            self.ax.set_title(heading, loc="left", fontsize=12, fontweight="bold", color=INK, pad=8)

    def labels(self, names: Sequence[str]) -> None:
        self.ax.set_yticklabels(names)

    def bar(self, row: int, value: float, gid: str) -> None:
        if value > 0:  # a zero is only its label
            self.ax.barh(row + 0.5, value, height=0.4, color=BAR, gid=gid)

    def mark(self, row: int, value: float, gid: str) -> None:
        self.ax.plot([value, value], [row + 0.1, row + 0.9], color=INK, linewidth=2, gid=gid)

    def text(self, row: int, x: float, label: str) -> None:
        pad = 6 / self.width_px * self.xmax
        self.ax.text(x + pad, row + 0.5, label, fontsize=12, color=INK, va="center")


def _bars_chart(title: str, names: Sequence[str], values: Sequence[int]) -> bytes:
    height = 52 + ROW * len(names)
    with matplotlib.rc_context(RC):
        fig = _figure(height, title)
        panel = _Panel(fig, height, 40, len(names), 170, max(max(values), 1) * 1.15)
        panel.labels(names)
        for row, value in enumerate(values):
            panel.bar(row, value, f"bar-{row}")
            panel.text(row, value, str(value))
        return _save(fig)


def message_chart(title: str, reason: str) -> bytes:
    """A chart whose data is not evaluable: the message takes the place of the bars."""
    with matplotlib.rc_context(RC):
        fig = _figure(88, title)
        fig.text(16 / WIDTH, 1 - 58 / 88, f"Not evaluable: {reason}", fontsize=12, color=INK, va="center")
        return _save(fig)


def outcomes_chart(counts: dict[str, int]) -> bytes:
    """Execution outcomes: bars for ``passed``, ``failed``, ``error``, ``blocked`` and ``skipped``."""
    executed = counts["passed"] + counts["failed"] + counts["error"]
    return _bars_chart(f"Execution outcomes ({executed} executed)", OUTCOMES, [counts[name] for name in OUTCOMES])


def comparison_chart(counts: dict[str, int]) -> bytes:
    """Comparison with the baseline: ``new_failures``, ``fixed``, ``persistent_failures`` and ``stable_passes``."""
    values = [counts[name] for name in COMPARISON]
    title = f"Comparison with the baseline ({sum(values)} test cases executed in both runs)"
    return _bars_chart(title, [name.replace("_", " ") for name in COMPARISON], values)


def criteria_chart(rates: list[dict], counts: list[dict]) -> bytes:
    """One horizontal bar per criterion with a threshold: its value, with the threshold marked.

    Each row is ``{"label", "value", "threshold", "text"}``: ``value`` is a number or None when the criterion
    is not evaluable and ``text`` is the label printed after the bar.
    ``rates`` use a scale of 0 to 1 and ``counts`` the scale of their largest number.
    """
    title = "Exit criteria: value (bar) and threshold (mark)"
    if not any(row["value"] is not None for row in rates + counts):
        return message_chart(title, "no criterion with a threshold has a value")
    groups = [(heading, rows) for heading, rows in (("Rates", rates), ("Counts", counts)) if rows]
    height = 40 + sum(26 + ROW * len(rows) + 18 for _, rows in groups)
    with matplotlib.rc_context(RC):
        fig = _figure(height, title)
        top, index = 40, 0
        for heading, rows in groups:
            numbers = [x for row in rows for x in (row["value"], row["threshold"]) if x is not None]
            xmax = 1.35 if heading == "Rates" else max(max(numbers), 1) * 1.35
            panel = _Panel(fig, height, top + 26, len(rows), 230, xmax, heading)
            panel.labels([row["label"] for row in rows])
            for i, row in enumerate(rows):
                if row["value"] is not None:
                    panel.bar(i, row["value"], f"bar-{index}")
                panel.mark(i, row["threshold"], f"mark-{index}")
                panel.text(i, max(row["value"] or 0, row["threshold"]), row["text"])
                index += 1
            top += 26 + ROW * len(rows) + 18
        return _save(fig)


def draw(name: str, evaluation) -> bytes:
    """The chart ``charts/<name>`` of the completion report, from the evaluation of its run."""
    metrics = evaluation.metrics
    if name == "outcomes.svg":
        return outcomes_chart({key: metrics[key] for key in OUTCOMES})
    if name == "comparison.svg":
        counts = {key: metrics[key] for key in COMPARISON}
        missing = next((v for v in counts.values() if isinstance(v, NotEvaluable)), None)
        if missing is not None:
            return message_chart("Comparison with the baseline", missing.reason)
        return comparison_chart(counts)
    if name == "criteria.svg":
        rates, counts = [], []
        for c in evaluation.criteria:
            if c.threshold is None:
                continue
            value = c.value.value if isinstance(c.value, Ratio) else c.value
            is_rate = isinstance(c.threshold, float)
            threshold = percent(Fraction(str(c.threshold))) if is_rate else str(c.threshold)
            bound = "min" if c.id in AT_LEAST else "max"
            row = {
                "label": f"{c.id} {c.name}",
                "value": None if value is None else float(value),
                "threshold": float(c.threshold),
                "text": f"{fmt(c.value)}  ({bound} {threshold})",
            }
            (rates if is_rate else counts).append(row)
        return criteria_chart(rates, counts)
    raise ReportError(f"unknown chart charts/{name}")
