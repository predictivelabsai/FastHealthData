"""Render synthetic-cohort aggregates as Plotly charts (server-emitted spec).

Client-side Plotly (loaded from CDN in layout.py) draws from a JSON spec, so the
server needs no plotting dependency — same pattern as FastInsights.
"""
from __future__ import annotations

import json

from fasthtml.common import Div, Script, NotStr, P

PALETTE = ["#4f46e5", "#0694a2", "#0e9f6e", "#c27803", "#e02424", "#7c3aed", "#db2777"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def bar(div_id, labels, values, height=280, horizontal=False, color=None):
    if not labels:
        return Div(P("No data.", style="color:var(--text-mute);"), cls="plot")
    if horizontal:
        trace = {"type": "bar", "orientation": "h", "y": labels, "x": [_num(v) for v in values],
                 "marker": {"color": color or PALETTE[0]}}
    else:
        trace = {"type": "bar", "x": labels, "y": [_num(v) for v in values],
                 "marker": {"color": [color or PALETTE[i % len(PALETTE)] for i in range(len(labels))]}}
    return _fig(div_id, [trace], height)


def line(div_id, labels, values, height=280):
    if not labels:
        return Div(P("No data.", style="color:var(--text-mute);"), cls="plot")
    trace = {"type": "scatter", "mode": "lines+markers", "x": labels, "y": [_num(v) for v in values],
             "line": {"color": PALETTE[0], "width": 2}, "marker": {"size": 6}}
    return _fig(div_id, [trace], height)


def donut(div_id, labels, values, height=280):
    if not labels:
        return Div(P("No data.", style="color:var(--text-mute);"), cls="plot")
    trace = {"type": "pie", "labels": labels, "values": [_num(v) for v in values], "hole": 0.5,
             "marker": {"colors": PALETTE}}
    return _fig(div_id, [trace], height, legend=True)


def grouped_bar(div_id, categories, series: dict, height=300):
    """series: {series_name: [values aligned to categories]}."""
    if not categories or not series:
        return Div(P("No data.", style="color:var(--text-mute);"), cls="plot")
    traces = [{"type": "bar", "name": name, "x": categories, "y": [_num(v) for v in vals],
               "marker": {"color": PALETTE[i % len(PALETTE)]}}
              for i, (name, vals) in enumerate(series.items())]
    return _fig(div_id, traces, height, legend=True, barmode="stack")


def _fig(div_id, traces, height, legend=False, barmode=None):
    layout = {"margin": {"t": 12, "r": 12, "b": 54, "l": 56}, "height": height,
              "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
              "font": {"size": 11, "color": "#4a5270"},
              "xaxis": {"automargin": True}, "yaxis": {"automargin": True},
              "showlegend": legend, "legend": {"orientation": "h", "y": -0.2}}
    if barmode:
        layout["barmode"] = barmode
    spec = json.dumps({"data": traces, "layout": layout})
    return Div(
        Div(id=div_id, cls="plot"),
        Script(NotStr(
            f"(function(){{var s={spec};"
            f"Plotly.newPlot('{div_id}',s.data,s.layout,{{displayModeBar:false,responsive:true}});}})();")))
