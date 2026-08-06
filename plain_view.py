# -*- coding: utf-8 -*-
"""
Plain view — visuals a non-specialist reads in seconds
========================================================
The rest of the app is built for someone who wants the model. This module
is for the race director, the duty officer, the alderman: people who need
the answer in one glance and will not read a caption about dimensionless
indices.

DESIGN CHOICES, AND WHY

1. A BATTERY, not a line chart. Control reserve genuinely behaves like a
   charge: it drains under load, recharges overnight, and at zero the
   system fails. The metaphor is apt rather than decorative, so it
   simplifies without distorting. Everyone reads a battery at 7% instantly;
   almost nobody reads "cumulative strain 1.86 of 2.0" instantly.

2. ONE CARD PER GROUP, not eight overlaid lines. Overlaid series force the
   reader to find their group in a legend before learning anything. Cards
   put the group's name and its verdict in the same place.

3. THE VERDICT IN WORDS, in the card. A colour alone tells someone that
   something is wrong, not what to do about it.

4. NO NEW NUMBERS. Everything here is a restatement of what the model
   already produced. The plain wording does not soften the uncertainty:
   the cards say "modelled", and the caveat travels with them rather than
   living only in the technical view a lay reader will never open.
"""

from __future__ import annotations

__BUILD__ = "2026-08-06a"

import numpy as np
import pandas as pd

from loop_view import reserve_series

# Reserve bands, aligned with the app's existing caution/danger/emergency
# thresholds (50% / 25% / 10% reserve = 50% / 75% / 90% strain).
_BANDS = [
    (75.0, "#16a34a", "Plenty in reserve",
     "This group is coping. Normal precautions."),
    (50.0, "#84cc16", "Reserve dipping",
     "Still coping, but the margin is narrowing. Keep an eye on it."),
    (25.0, "#eab308", "Running low",
     "Half the reserve is gone. Add rest, shade and fluids; check on people "
     "who are on their own."),
    (10.0, "#f97316", "Nearly empty",
     "Little margin left. Actively reduce exposure and check on this group."),
    (0.0, "#dc2626", "Empty",
     "The model puts this group past the point where its cooling system "
     "keeps up. Treat as urgent."),
]


def band_for(reserve_pct: float):
    for threshold, colour, title, advice in _BANDS:
        if reserve_pct >= threshold:
            return colour, title, advice
    return _BANDS[-1][1], _BANDS[-1][2], _BANDS[-1][3]


def _battery_svg(pct: float, colour: str, width: int = 220, height: int = 46) -> str:
    """A horizontal battery drawn as inline SVG, so it renders identically
    everywhere without a plotting round-trip."""
    pct = float(np.clip(pct, 0.0, 100.0))
    body_w = width - 14
    fill_w = max(2.0, (body_w - 8) * pct / 100.0)
    return f"""
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="1" y="6" rx="6" ry="6" width="{body_w}" height="{height-12}"
        fill="#f8fafc" stroke="#94a3b8" stroke-width="2"/>
  <rect x="{body_w+3}" y="{height/2-7}" width="9" height="14" rx="2" fill="#94a3b8"/>
  <rect x="5" y="10" rx="3" ry="3" width="{fill_w}" height="{height-20}" fill="{colour}"/>
  <text x="{body_w/2}" y="{height/2+6}" text-anchor="middle"
        font-family="system-ui, sans-serif" font-size="17" font-weight="700"
        fill="#0f172a">{pct:.0f}%</text>
</svg>"""


def status_card_html(group_label: str, reserve_pct: float, subtitle: str = "") -> str:
    colour, title, advice = band_for(reserve_pct)
    sub = f"<div style='color:#475569;font-size:0.85rem;margin-top:2px'>{subtitle}</div>" if subtitle else ""
    return f"""
<div style="border-left:10px solid {colour};background:#ffffff;
            border:1px solid #e2e8f0;border-left:10px solid {colour};
            border-radius:10px;padding:14px 16px;margin-bottom:12px">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
    <div style="min-width:230px">
      <div style="font-size:1.05rem;font-weight:700;color:#0f172a">{group_label}</div>
      <div style="color:{colour};font-weight:700;font-size:0.95rem">{title}</div>
      {sub}
    </div>
    <div>{_battery_svg(reserve_pct, colour)}</div>
  </div>
  <div style="margin-top:10px;color:#1e293b;font-size:0.92rem">{advice}</div>
</div>"""


def render_status_cards(st, pyrox_result: dict, label_for: dict,
                        day_index: int = None) -> None:
    """One card per group: how much cooling reserve the model leaves it, and
    what to do. `day_index` defaults to the worst day in the period."""
    dates = pyrox_result["dates"]
    st.markdown("### \U0001F50B How much reserve is left")
    st.caption(
        "Think of each group as having a battery of cooling capacity. Heat "
        "drains it; cool nights recharge it. At zero, the body can no longer "
        "hold its temperature steady. These are **modelled** values for a "
        "group, not measurements of any individual."
    )

    for name, res in pyrox_result["groups"].items():
        reserve = reserve_series(res)
        if len(reserve) == 0:
            continue
        idx = int(np.argmin(reserve)) if day_index is None else min(day_index, len(reserve) - 1)
        when = pd.Timestamp(dates[idx]).strftime("%a %d %b") if idx < len(dates) else ""
        st.markdown(
            status_card_html(label_for.get(name, name), reserve[idx],
                             subtitle=f"lowest point in this period \u2014 {when}"),
            unsafe_allow_html=True,
        )


def battery_timeline_chart(pyrox_result: dict, label_for: dict):
    """Reserve over time as a filled area with coloured comfort zones —
    small multiples, one row per group, so nobody has to decode a legend."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    groups = list(pyrox_result["groups"].items())
    dates = [pd.Timestamp(d) for d in pyrox_result["dates"]]
    fig = make_subplots(
        rows=len(groups), cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=[label_for.get(n, n) for n, _ in groups],
    )
    for r, (name, res) in enumerate(groups, start=1):
        y = reserve_series(res)
        n = min(len(dates), len(y))
        fig.add_trace(go.Scatter(
            x=dates[:n], y=y[:n], mode="lines", fill="tozeroy",
            line=dict(color="#0f172a", width=2), fillcolor="rgba(59,130,246,0.25)",
            name=label_for.get(name, name), showlegend=False,
            hovertemplate="%{x|%a %d %b}<br>reserve %{y:.0f}%<extra></extra>",
        ), row=r, col=1)
        for y0, y1, colour in [(0, 25, "rgba(220,38,38,0.13)"),
                               (25, 50, "rgba(234,179,8,0.13)")]:
            fig.add_hrect(y0=y0, y1=y1, line_width=0, fillcolor=colour,
                          row=r, col=1)
        fig.update_yaxes(range=[0, 105], title_text="% left", row=r, col=1,
                         title_font=dict(size=10))

    fig.update_layout(
        height=150 * len(groups) + 60,
        margin=dict(l=10, r=20, t=50, b=30),
        title=dict(text="Cooling reserve over the period",
                   x=0, xanchor="left", y=0.99, yanchor="top"),
        hovermode="x unified",
    )
    for ann in fig.layout.annotations:
        ann.font.size = 12
    return fig


def render_plain_view(st, pyrox_result: dict, label_for: dict) -> None:
    """The whole lay-reader layer."""
    render_status_cards(st, pyrox_result, label_for)

    with st.expander("Show how the reserve changes day by day"):
        st.plotly_chart(battery_timeline_chart(pyrox_result, label_for),
                        use_container_width=True, key="plain_battery_timeline")
        st.caption(
            "Each band is one group. The line falls when heat outpaces what "
            "the body can shed and rises when there is time to recover. "
            "Yellow and red mark where the margin is getting thin."
        )

    st.caption(
        "\u2139\ufe0f These are modelled group averages for planning and comparison. "
        "They are not a diagnosis and not a prediction for any individual, "
        "and the model has not yet been checked against real incident "
        "records \u2014 see the evidence panel below."
    )
