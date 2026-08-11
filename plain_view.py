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

__BUILD__ = "2026-08-10b"

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
    if reserve_pct is None or (isinstance(reserve_pct, float) and np.isnan(reserve_pct)):
        return "#9ca3af", "No data", "This day/group could not be computed from the available data."
    for threshold, colour, title, advice in _BANDS:
        if reserve_pct >= threshold:
            return colour, title, advice
    return _BANDS[-1][1], _BANDS[-1][2], _BANDS[-1][3]


def _battery_svg(pct: float, colour: str, width: int = 220, height: int = 46) -> str:
    """A horizontal battery drawn as inline SVG, so it renders identically
    everywhere without a plotting round-trip."""
    is_valid = pct is not None and not (isinstance(pct, float) and np.isnan(pct))
    pct_clamped = float(np.clip(pct, 0.0, 100.0)) if is_valid else 0.0
    body_w = width - 14
    fill_w = max(2.0, (body_w - 8) * pct_clamped / 100.0) if is_valid else 2.0
    label = f"{pct_clamped:.0f}%" if is_valid else "N/A"
    return f"""
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="1" y="6" rx="6" ry="6" width="{body_w}" height="{height-12}"
        fill="#f8fafc" stroke="#94a3b8" stroke-width="2"/>
  <rect x="{body_w+3}" y="{height/2-7}" width="9" height="14" rx="2" fill="#94a3b8"/>
  <rect x="5" y="10" rx="3" ry="3" width="{fill_w}" height="{height-20}" fill="{colour}"/>
  <text x="{body_w/2}" y="{height/2+6}" text-anchor="middle"
        font-family="system-ui, sans-serif" font-size="17" font-weight="700"
        fill="#0f172a">{label}</text>
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
        if day_index is not None:
            idx = min(day_index, len(reserve) - 1)
        elif np.all(np.isnan(reserve)):
            # Every day is NaN for this group -- nanargmin would raise.
            # Show it honestly as "no data" rather than picking an
            # arbitrary index and rendering something plausible-looking.
            st.markdown(
                status_card_html(label_for.get(name, name), float("nan"),
                                 subtitle="no valid data in this period"),
                unsafe_allow_html=True,
            )
            continue
        else:
            # np.argmin on an array containing NaN returns the NaN's own
            # index, not the true minimum among valid values (NaN
            # comparisons are always False, so it "wins" the internal
            # scan). That silently turned one bad data point into every
            # group showing "nan% / Empty / urgent". np.nanargmin skips
            # NaN correctly.
            idx = int(np.nanargmin(reserve))
        when = pd.Timestamp(dates[idx]).strftime("%a %d %b") if idx < len(dates) else ""
        if day_index is not None:
            subtitle = f"on your chosen date \u2014 {when}"
        else:
            subtitle = f"lowest point in this period \u2014 {when}"
        st.markdown(
            status_card_html(label_for.get(name, name), reserve[idx],
                             subtitle=subtitle),
            unsafe_allow_html=True,
        )


def battery_timeline_chart(pyrox_result: dict, label_for: dict, target_date=None):
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
    any_missing_data = False
    for r, (name, res) in enumerate(groups, start=1):
        y = reserve_series(res)
        n = min(len(dates), len(y))
        x_vals, y_vals = dates[:n], y[:n]
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="lines", fill="tozeroy",
            line=dict(color="#0f172a", width=2), fillcolor="rgba(59,130,246,0.25)",
            name=label_for.get(name, name), showlegend=False,
            hovertemplate="%{x|%a %d %b}<br>reserve %{y:.0f}%<extra></extra>",
            connectgaps=False,  # NaN must show as a real gap, never bridged silently
        ), row=r, col=1)

        # A gap (NaN anywhere in this group's series) is made visible rather
        # than left as an unexplained blank area -- the earlier "nan% /
        # Empty / urgent" battery-card bug happened precisely because a gap
        # like this was invisible until it got misread downstream.
        is_nan = pd.isna(y_vals) if isinstance(y_vals, np.ndarray) else np.isnan(y_vals)
        if np.any(is_nan):
            any_missing_data = True
            first_gap = x_vals[int(np.argmax(is_nan))]
            fig.add_vrect(x0=first_gap, x1=x_vals[-1], line_width=0,
                         fillcolor="rgba(148,163,184,0.35)", row=r, col=1)
            fig.add_annotation(
                x=first_gap, y=50, row=r, col=1, text="no data",
                showarrow=False, font=dict(size=10, color="#475569"),
                bgcolor="rgba(255,255,255,0.8)",
            )

        for y0, y1, colour in [(0, 25, "rgba(220,38,38,0.13)"),
                               (25, 50, "rgba(234,179,8,0.13)")]:
            fig.add_hrect(y0=y0, y1=y1, line_width=0, fillcolor=colour,
                          row=r, col=1)
        if target_date is not None:
            fig.add_vline(x=pd.Timestamp(target_date), line_dash="dash",
                          line_color="#111827", row=r, col=1)
        fig.update_yaxes(range=[0, 105], title_text="% left", row=r, col=1,
                         title_font=dict(size=10))

    fig.update_layout(
        height=150 * len(groups) + 60,
        margin=dict(l=10, r=20, t=50, b=30),
        title=dict(text="Cooling reserve over the period",
                   x=0, xanchor="left", y=0.99, yanchor="top"),
        hovermode="x unified",
    )
    fig._pyrox_any_missing_data = any_missing_data
    for ann in fig.layout.annotations:
        ann.font.size = 12
    return fig


def render_plain_view(st, pyrox_result: dict, label_for: dict,
                      target_date=None) -> None:
    """The whole lay-reader layer.

    `target_date`, if given (e.g. the race/session date chosen elsewhere
    in the app), scopes the reserve cards to THAT specific day instead of
    the worst day anywhere across the whole multi-week hindcast+forecast
    window. Without it, "lowest point in this period" can land on a date
    the user never asked about (e.g. the very first day of a 24-day
    combined window) rather than the day they actually chose.
    """
    day_index = None
    if target_date is not None:
        dates = pyrox_result["dates"]
        target = pd.Timestamp(target_date).date()
        matches = [i for i, d in enumerate(dates) if pd.Timestamp(d).date() == target]
        if matches:
            day_index = matches[0]
        # If the chosen date falls outside the computed window entirely,
        # fall back to the worst-day view (day_index stays None) rather
        # than silently showing the wrong day.

    render_status_cards(st, pyrox_result, label_for, day_index=day_index)

    with st.expander("Show how the reserve changes day by day"):
        fig = battery_timeline_chart(pyrox_result, label_for, target_date=target_date)
        st.plotly_chart(fig, use_container_width=True, key="plain_battery_timeline")
        if getattr(fig, "_pyrox_any_missing_data", False):
            st.warning(
                "\u26a0\ufe0f The grey band(s) above mark days with no usable "
                "data for that group \u2014 most likely a gap in the underlying "
                "weather fetch. Treat those days as unknown, not as zero "
                "risk, and try re-running the analysis."
            )
        st.caption(
            "Each band is one group. The line falls when heat outpaces what "
            "the body can shed and rises when there is time to recover. "
            "Yellow and red mark where the margin is getting thin."
            + (" The dashed line marks your chosen date." if target_date is not None else "")
        )

    st.caption(
        "\u2139\ufe0f These are modelled group averages for planning and comparison. "
        "They are not a diagnosis and not a prediction for any individual, "
        "and the model has not yet been checked against real incident "
        "records \u2014 see the evidence panel below."
    )
