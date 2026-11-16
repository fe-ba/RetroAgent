"""Measure the texts of a chart SVG against its canvas."""

import html
import re

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from retroagent.reports import charts

CANVAS = charts.WIDTH


def overflowing(svg: bytes) -> list[str]:
    """The texts of the SVG whose extent leaves the canvas, measured with the font the chart is drawn with."""
    figure = Figure(dpi=72)
    renderer = FigureCanvasAgg(figure).get_renderer()
    bad = []
    for attributes, text in re.findall(r"<text([^>]*)>([^<]*)</text>", svg.decode()):
        text = html.unescape(text)
        size = float(re.search(r"font-size: ([\d.]+)px", attributes).group(1))
        bold = "font-weight: 700" in attributes or "font-weight: bold" in attributes
        x = float(re.search(r' x="([-\d.]+)"', attributes).group(1))
        probe = figure.text(0, 0, text, fontsize=size, fontweight="bold" if bold else "normal")
        width = probe.get_window_extent(renderer).width
        probe.remove()
        anchor = re.search(r"text-anchor: (\w+)", attributes).group(1)
        left, right = {"start": (x, x + width), "end": (x - width, x), "middle": (x - width / 2, x + width / 2)}[anchor]
        if left < 0 or right > CANVAS:
            bad.append(f"{text!r} spans {left:.0f} to {right:.0f} of {CANVAS}")
    return bad
