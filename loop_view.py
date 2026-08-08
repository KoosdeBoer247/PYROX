# -*- coding: utf-8 -*-
"""
Control-loop view — what WBGT and UTCI cannot express
======================================================
WBGT and UTCI describe the DISTURBANCE: how hard the environment is
pushing. They are computed from this hour's weather and nothing else.
PYROX describes whether the REGULATORY LOOP can still reject that
disturbance: how much control authority the group has left, whether the
night returned it, and whether accumulated error is running away.

Two hours with an identical WBGT can therefore sit in completely
different places in the loop. That is not a flaw in WBGT -- it is outside
what an instantaneous environmental index is built to say. This module
surfaces that difference rather than leaving the two views side by side
for the reader to reconcile.

Loop variables, and where they come from (all already produced per day by
PyroxModel.simulate()'s `diagnostics`, they were simply never displayed):

    baseline_heat_load        disturbance entering the loop
    exposure_signal           disturbance after the memory filter
                              (weighted over previous days)
    effective_acclimatization control authority actually available
    net_strain_input          error the controller could not reject
    daily_recovery            overnight leak that discharges the integrator
    cumulative_strain         integrator state
    critical_strain           saturation: above this the loop opens

STATUS. The framing is control-theoretic and the arithmetic is the
model's own, but PYROX's population tier has no event-level validation.
The divergence flag below is a HYPOTHESIS GENERATOR -- "the index and the
loop disagree here, look closer" -- not a validated warning. It is also
only as good as each group's parameters, which for most groups are
extrapolated rather than published.
"""

from __future__ import annotations

__BUILD__ = "2026-08-08f"

import numpy as np
import pandas as pd

from decision_support import classify_hour_race, flag_display_name


# =============================================================================
# 1. Control reserve — the servo-native view
# =============================================================================
def reserve_series(res: dict) -> np.ndarray:
    """Remaining control margin per day, as a fraction of critical strain.

    Plotting reserve rather than strain matches how the quantity actually
    behaves: it is the margin before the actuator saturates and the loop
    opens. 100% = full authority available, 0% = decompensation.
    """
    strain = np.asarray(res["cumulative_strain"][1:], dtype=float)
    return np.clip(1.0 - strain / res["critical_strain"], 0.0, 1.0) * 100.0


def reserve_chart(pyrox_result: dict, label_for: dict):
    import plotly.graph_objects as go

    dates = [pd.Timestamp(d) for d in pyrox_result["dates"]]
    fig = go.Figure()
    for name, res in pyrox_result["groups"].items():
        r = reserve_series(res)
        n = min(len(dates), len(r))
        fig.add_trace(go.Scatter(x=dates[:n], y=r[:n], mode="lines+markers",
                                 name=label_for.get(name, name)))
    fig.add_hrect(y0=0, y1=25, line_width=0, fillcolor="rgba(220,38,38,0.10)",
                  annotation_text="little margin left", annotation_position="bottom left",
                  annotation_font=dict(size=10, color="#7f1d1d"))
    fig.update_layout(
        title=dict(text="Control reserve — margin before the loop opens",
                   x=0, xanchor="left", y=0.98, yanchor="top"),
        yaxis_title="% of control authority remaining", yaxis_range=[0, 105],
        height=430, margin=dict(l=10, r=20, t=70, b=60),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left",
                    x=0, font=dict(size=10)),
        hovermode="x unified",
    )
    return fig


# =============================================================================
# 2. Daily loop balance — load in versus recovery out
# =============================================================================
def loop_balance_frame(res: dict, dates) -> pd.DataFrame:
    """Per-day error input against overnight recovery.

    This is the single clearest thing WBGT cannot express. Two days with
    the same WBGT differ entirely depending on whether the night in
    between discharged the integrator. A warm night that blocks recovery
    turns a survivable sequence into an accumulating one, and no
    instantaneous index sees it.
    """
    rows = []
    for i, d in enumerate(res["diagnostics"]):
        rows.append({
            "date": dates[i] if i < len(dates) else i,
            "strain added": d["net_strain_input"],
            "recovery": -d["daily_recovery"],
            "net": d["net_strain_input"] - d["daily_recovery"],
            "control authority": d["effective_acclimatization"],
            "cumulative strain": d["cumulative_strain"],
        })
    return pd.DataFrame(rows)


def loop_balance_chart(res: dict, dates, title: str):
    import plotly.graph_objects as go

    df = loop_balance_frame(res, dates)
    x = [pd.Timestamp(d) for d in df["date"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=df["strain added"], name="strain added (load not rejected)",
                         marker_color="#dc2626"))
    fig.add_trace(go.Bar(x=x, y=df["recovery"], name="recovery (overnight discharge)",
                         marker_color="#0ea5e9"))
    fig.add_trace(go.Scatter(x=x, y=df["net"], name="net change", mode="lines+markers",
                             line=dict(color="#111827", width=2)))
    fig.add_hline(y=0, line_color="gray")
    fig.update_layout(
        barmode="relative",
        title=dict(text=title, x=0, xanchor="left", y=0.98, yanchor="top"),
        yaxis_title="strain units per day", height=400,
        margin=dict(l=10, r=20, t=70, b=60),
        legend=dict(orientation="h", yanchor="top", y=-0.20, xanchor="left",
                    x=0, font=dict(size=10)),
        hovermode="x unified",
    )
    return fig


# =============================================================================
# 3. Divergence: environmental flag versus loop state
# =============================================================================
#: Reserve below this counts as "the loop is under real pressure", chosen to
#: line up with the app's existing caution threshold (50% of critical strain).
RESERVE_CONCERN = 50.0


def daily_flag_from_hourly(weather_df: pd.DataFrame, dates) -> dict:
    """Worst athletics WBGT flag reached on each calendar day."""
    if "WBGT" not in weather_df.columns:
        return {}
    order = ["race_green", "race_yellow", "race_red", "race_black"]
    rank = {s: i for i, s in enumerate(order)}
    worst = {}
    for ts, wbgt in weather_df["WBGT"].items():
        day = ts.date()
        status = classify_hour_race(wbgt)["status"]
        if status not in rank:
            continue
        if day not in worst or rank[status] > rank[worst[day]]:
            worst[day] = status
    return worst


def divergence_table(pyrox_result: dict, weather_df: pd.DataFrame,
                     label_for: dict) -> pd.DataFrame:
    """Days where the environmental flag and the loop state disagree.

    The interesting case is a benign flag over a group with little reserve
    left: the weather today is unremarkable, but this group has not
    recovered from the days before it, so the same conditions land on a
    system that is already close to saturation. An hourly index cannot
    produce that statement, because it has no memory.
    """
    day_flag = daily_flag_from_hourly(weather_df, pyrox_result["dates"])
    dates = pyrox_result["dates"]
    rows = []
    for name, res in pyrox_result["groups"].items():
        reserve = reserve_series(res)
        for i, d in enumerate(dates):
            if i >= len(reserve):
                break
            flag = day_flag.get(pd.Timestamp(d).date())
            if flag is None:
                continue
            if flag in ("race_green", "race_yellow") and reserve[i] < RESERVE_CONCERN:
                rows.append({
                    "Date": pd.Timestamp(d).date(),
                    "Group": label_for.get(name, name),
                    "WBGT flag": flag_display_name(flag),
                    "Control reserve": f"{reserve[i]:.0f}%",
                    "Why it diverges":
                        "Conditions look benign, but this group is carrying "
                        "unrecovered strain from earlier days.",
                })
    return pd.DataFrame(rows)


# =============================================================================
# 4. Rendering
# =============================================================================
def render_loop_view(st, pyrox_result: dict, weather_df: pd.DataFrame,
                     label_for: dict) -> None:
    """Render the whole control-loop layer."""
    st.header("\U0001F501 Regulatory loop — beyond WBGT and UTCI")
    st.caption(
        "WBGT and UTCI describe **the disturbance**: how hard the "
        "environment is pushing, computed from this hour's weather and "
        "nothing else. The view below describes **whether the body's "
        "regulatory loop can still reject it** — how much control "
        "authority is left, whether the night returned it, and whether "
        "unrejected load is accumulating. Two hours with the same WBGT can "
        "sit in very different places in that loop."
    )

    st.plotly_chart(reserve_chart(pyrox_result, label_for),
                    use_container_width=True, key="loop_reserve")
    st.caption(
        "Reserve is the margin before the actuator saturates. It falls when "
        "load exceeds what acclimatisation can reject and rises when "
        "recovery outpaces load. Zero means the loop has opened — "
        "decompensation runs away from there."
    )

    div = divergence_table(pyrox_result, weather_df, label_for)
    if len(div):
        st.warning(
            f"\u26a0\ufe0f **{len(div)} day/group combination(s) where the WBGT flag "
            "and the loop state disagree.** On these days the weather reads "
            "benign, but the group is already low on reserve from earlier "
            "days. This is the multi-day blind spot of any instantaneous "
            "index — it has no memory of what came before."
        )
        st.dataframe(div, use_container_width=True, hide_index=True)
    else:
        st.success(
            "\u2705 No divergence in this period: wherever reserve is low, the "
            "WBGT flag already indicates elevated risk, so the index and the "
            "loop agree."
        )

    with st.expander("Daily loop balance — load in versus recovery out"):
        st.caption(
            "The clearest thing an instantaneous index cannot express. Two "
            "days with identical WBGT differ entirely depending on whether "
            "the night in between discharged the accumulated strain. Warm "
            "nights block that discharge, and nothing in WBGT sees it."
        )
        for name, res in pyrox_result["groups"].items():
            st.plotly_chart(
                loop_balance_chart(res, pyrox_result["dates"],
                                   label_for.get(name, name)),
                use_container_width=True, key=f"loop_balance_{name}")

    st.caption(
        "\u2139\ufe0f Control-theoretic framing of PYROX's own arithmetic. The "
        "population tier has no event-level validation, and most groups use "
        "extrapolated rather than published parameters, so treat the "
        "divergence flag as a prompt to look closer — not as a validated "
        "warning."
    )
