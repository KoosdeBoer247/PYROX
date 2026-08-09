# -*- coding: utf-8 -*-
"""
EXPERIMENTAL — collapse risk and EHS indicators
==================================================
Two indicators, deliberately kept separate because they rest on very
different evidentiary ground, plus a comparison against WBGT/UTCI.

1. COLLAPSE RISK (control-theoretic). Directly derived from PYROX's own
   state (100 - control reserve, see loop_view.py). This is legitimate:
   it is the same arithmetic already in the app, just framed as a risk
   percentage instead of a reserve percentage. It answers "is the
   regulatory loop losing the ability to reject heat load", accumulated
   over the multi-day period -- NOT an acute, single-session estimate.

2. EHS INDICATORS (session-level, exertional heat stroke). This is
   EXPLICITLY NOT the author's own conjunctive criterion (T_rect > 40.5C
   AND CO_reserve <= 0) from the HESTIA individual tier -- that requires
   HESTIA's cardiovascular Monte Carlo simulation, which is a separate,
   heavier model not part of this app. What IS built here, honestly
   scoped to what two published, already-installed pythermalcomfort
   models can support without inventing anything:

   a) Sports Medicine Australia / ISO 7933 PHS-based risk categories,
      via pythermalcomfort's `sports_heat_stress_risk`. General-purpose,
      no age restriction found in the source, but PHS itself (see the
      evidence panel) is validated on a healthy adult population, not
      medically vulnerable individuals.

   b) Predicted rectal temperature (T_re) trajectory, via
      pythermalcomfort's `ridge_regression_predict_t_re_t_sk`. This
      genuinely gives the T_rect half of the author's own criterion --
      but the model's own source code restricts its valid age range to
      60-100 years. It is therefore offered ONLY for the older walker
      groups, and explicitly withheld for younger runners and children
      rather than extrapolated past its fitted range. The cardiovascular
      half of the conjunctive criterion is not computed here at all: no
      proxy is substituted for it, because a substitute would be
      fabricated, not measured or modelled.

STATUS: experimental. Shown separately per indicator, and together
against WBGT/UTCI, so agreement or disagreement between them is visible
rather than papered over.
"""

from __future__ import annotations

__BUILD__ = "2026-08-08a"

import numpy as np
import pandas as pd

from pyrox_bridge import met_from_pace

from pythermalcomfort.models import (
    sports_heat_stress_risk, Sports, ridge_regression_predict_t_re_t_sk,
)

from loop_view import reserve_series

# HESTIA is OPTIONAL: it needs several large sibling files (hestia_model.py,
# the CVR and Control Failure modules) and heavier dependencies (matplotlib,
# seaborn, tqdm, colorama) that the rest of this app does not otherwise
# need. Imported defensively so its absence disables only this one section,
# not the whole app -- same pattern as terrain_lookup.py's rasterio guard.
try:
    from hestia_bridge import render_hestia_section
    HESTIA_AVAILABLE = True
except Exception as _hestia_exc:
    HESTIA_AVAILABLE = False
    _HESTIA_IMPORT_ERROR = str(_hestia_exc)

#: Representative demographics per level, used ONLY for the T_re
#: projection (which needs age/height/weight). These are typical values
#: for the level, not the individual user's own data -- there is no
#: per-person input in this app. Levels not listed are not age-eligible
#: for the T_re model (see RIDGE_VALID_AGE) and are skipped entirely
#: rather than assigned an arbitrary age.
LEVEL_DEMOGRAPHICS = {
    "Walker — middle-aged (45-65)": dict(sex="female", age=58, height=1.68, weight=72),
    "Walker — older adult (65-85)": dict(sex="female", age=74, height=1.65, weight=68),
    "Walker — vulnerable older adult (85+)": dict(sex="female", age=87, height=1.60, weight=62),
}
RIDGE_VALID_AGE = (60, 100)

#: VO2max-pinning gating is now DYNAMIC (see hestia_bridge.render_hestia_
#: section), computed per call from the actual MET used -- not a static
#: list here. That static list only ever covered elite_athletes (99%
#: pinned at its default pace), and testing later found endurance_
#: athletes ALSO severely pinned (72% at its default pace) -- a level the
#: static list never caught, because pace is user-adjustable and a fixed
#: per-group list can't track that. The dynamic check in hestia_bridge.py
#: measures the real pinning fraction for whatever MET is actually in use
#: and gates on that directly, which is correct for any pace a level is
#: configured with, not just the default.


def is_t_re_eligible(level_label: str) -> bool:
    demo = LEVEL_DEMOGRAPHICS.get(level_label)
    if demo is None:
        return False
    lo, hi = RIDGE_VALID_AGE
    return lo <= demo["age"] <= hi


def sport_for_level(mode: str):
    return Sports.RUNNING if mode == "run" else Sports.WALKING


# =============================================================================
# 1. Collapse risk (from PYROX's own state)
# =============================================================================
def collapse_risk_series(res: dict) -> np.ndarray:
    """100 - control reserve. See loop_view.reserve_series for the
    underlying quantity; this is a relabelling, not a new computation."""
    return 100.0 - reserve_series(res)


def collapse_risk_chart(pyrox_result: dict, label_for: dict):
    import plotly.graph_objects as go

    dates = [pd.Timestamp(d) for d in pyrox_result["dates"]]
    fig = go.Figure()
    for name, res in pyrox_result["groups"].items():
        y = collapse_risk_series(res)
        n = min(len(dates), len(y))
        fig.add_trace(go.Scatter(x=dates[:n], y=y[:n], mode="lines+markers",
                                 name=label_for.get(name, name)))
    fig.add_hrect(y0=75, y1=100, line_width=0, fillcolor="rgba(220,38,38,0.10)",
                  annotation_text="little margin left", annotation_position="top left",
                  annotation_font=dict(size=10, color="#7f1d1d"))
    fig.update_layout(
        title=dict(text="Collapse risk \u2014 control-theoretic (multi-day, from PYROX)",
                   x=0, xanchor="left", y=0.98, yanchor="top"),
        yaxis_title="% (100 = loop open)", yaxis_range=[0, 105],
        height=380, margin=dict(l=10, r=20, t=60, b=50),
        legend=dict(orientation="h", yanchor="top", y=-0.20, xanchor="left",
                    x=0, font=dict(size=10)),
        hovermode="x unified",
    )
    return fig


# =============================================================================
# 2a. Sports Medicine Australia / PHS risk category
# =============================================================================
def sports_risk_for_window(weather_df: pd.DataFrame, start, finish, mode: str) -> dict | None:
    """Peak-conditions PHS-based sports heat-stress risk over a session
    window. Uses the worst (highest T_air) hour in the window as the
    representative condition, consistent with how the app already reports
    "peak" conditions elsewhere."""
    win = weather_df[(weather_df.index >= pd.Timestamp(start))
                     & (weather_df.index <= pd.Timestamp(finish))]
    if win.empty or "T_air_urban" not in win.columns:
        return None
    i = win["T_air_urban"].idxmax()
    row = win.loc[i]
    wind = float(row.get("wind_10m", 2.0)) or 2.0
    try:
        r = sports_heat_stress_risk(
            tdb=float(row["T_air_urban"]), tr=float(row.get("MRT", row["T_air_urban"])),
            rh=float(row.get("RH", 50.0)), vr=wind, sport=sport_for_level(mode),
        )
    except Exception as e:
        return {"error": str(e)}
    return {
        "time": i, "t_air": float(row["T_air_urban"]),
        "risk_level": r.risk_level_interpolated,
        "t_medium": r.t_medium, "t_high": r.t_high, "t_extreme": r.t_extreme,
        "recommendation": r.recommendation,
    }


def render_sports_risk_card(st, result: dict, level_label: str) -> None:
    if result is None:
        st.info(f"No data to assess {level_label} against.")
        return
    if "error" in result:
        st.warning(f"Could not compute sports heat-stress risk for {level_label}: {result['error']}")
        return
    level_val = result["risk_level"]
    band = "Low" if level_val < 1 else "Medium" if level_val < 2 else "High" if level_val < 3 else "Extreme"
    colour = {"Low": "#16a34a", "Medium": "#eab308", "High": "#f97316", "Extreme": "#dc2626"}[band]
    st.markdown(
        f"""<div style="border-left:8px solid {colour};background:#fff;border:1px solid #e2e8f0;
        border-left:8px solid {colour};border-radius:10px;padding:12px 14px;margin-bottom:10px">
        <div style="font-weight:700;color:#0f172a">{level_label}</div>
        <div style="color:{colour};font-weight:700">{band} risk</div>
        <div style="color:#475569;font-size:0.88rem;margin-top:4px">
        Peak T_air {result['t_air']:.1f}\u00b0C at {pd.Timestamp(result['time']).strftime('%H:%M')} \u00b7
        thresholds: medium {result['t_medium']:.1f}\u00b0C, high {result['t_high']:.1f}\u00b0C,
        extreme {result['t_extreme']:.1f}\u00b0C</div>
        <div style="margin-top:6px;color:#1e293b">{result['recommendation']}</div>
        </div>""",
        unsafe_allow_html=True,
    )


# =============================================================================
# 2b. T_re (rectal temperature) projection -- age-restricted
# =============================================================================
def t_re_projection(level_label: str, tdb: float, rh: float, duration_min: int):
    """Rectal-temperature trajectory for the session, or None if this
    level's representative age falls outside the model's valid range."""
    if not is_t_re_eligible(level_label):
        return None
    demo = LEVEL_DEMOGRAPHICS[level_label]
    duration_min = max(1, min(int(duration_min), 300))  # cap: model's own practical range
    r = ridge_regression_predict_t_re_t_sk(
        sex=demo["sex"], age=demo["age"], height=demo["height"], weight=demo["weight"],
        tdb=tdb, rh=rh, duration=duration_min,
    )
    return np.asarray(r.t_re, dtype=float)


#: Rectal-temperature threshold associated with exertional heat stroke in
#: the sports-medicine literature, and the same threshold used in the
#: author's own (unvalidated, HESTIA-tier) conjunctive EHS criterion.
T_RE_EHS_THRESHOLD = 40.5


def t_re_chart(level_label: str, t_re: np.ndarray, start_time: pd.Timestamp):
    import plotly.graph_objects as go

    minutes = np.arange(len(t_re))
    times = [start_time + pd.Timedelta(minutes=int(m)) for m in minutes]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times, y=t_re, mode="lines", name="predicted T_re",
                             line=dict(color="#dc2626", width=2.5)))
    fig.add_hline(y=T_RE_EHS_THRESHOLD, line_dash="dot", line_color="#7f1d1d",
                  annotation_text=f"EHS reference ({T_RE_EHS_THRESHOLD}\u00b0C)",
                  annotation_position="top left",
                  annotation_font=dict(size=10, color="#7f1d1d"))
    fig.update_layout(
        title=dict(text=f"Predicted rectal temperature \u2014 {level_label}",
                   x=0, xanchor="left", y=0.95, yanchor="top"),
        yaxis_title="\u00b0C", height=300, margin=dict(l=10, r=20, t=50, b=10),
        showlegend=False, hovermode="x unified",
    )
    return fig


# =============================================================================
# 3. Rendering
# =============================================================================
def render_experimental_section(st, pyrox_result: dict, label_for: dict,
                                weather_df: pd.DataFrame, level_modes: dict,
                                exp_start, session_km: float, paces: dict,
                                hestia_ctx: dict = None) -> dict:
    """Returns {level_label: hestia_quick_result} for every level HESTIA
    actually ran on (empty dict if HESTIA is unavailable/not requested) --
    so callers can cross-reference HESTIA's acute, race-timescale finding
    against other layers of the app (e.g. PYROX's multi-day reserve),
    which otherwise have no way of knowing about each other.
    """
    st.header("\U0001F9EA EXPERIMENTAL \u2014 collapse risk & EHS indicators")
    st.warning(
        "\u26a0\ufe0f **Experimental.** Two different indicators, kept deliberately "
        "separate because they rest on different evidence:\n\n"
        "- **Collapse risk** is the app's own PYROX state (relabelled from "
        "control reserve) \u2014 multi-day, no new physiology.\n"
        "- **EHS indicators** use two published pythermalcomfort models "
        "(Sports Medicine Australia / ISO 7933 PHS, and a ridge-regression "
        "rectal-temperature predictor). **This is NOT the author's own "
        "conjunctive EHS criterion** (T_rect > 40.5\u00b0C AND cardiac-output "
        "reserve \u2264 0) from HESTIA's individual tier \u2014 that needs a "
        "cardiovascular Monte Carlo simulation not part of this app. Only "
        "the T_rect half is estimated here; no cardiovascular component is "
        "computed or substituted."
    )

    st.plotly_chart(collapse_risk_chart(pyrox_result, label_for),
                    use_container_width=True, key="exp_collapse_risk")

    st.markdown("### EHS indicators, per level")
    for name, res in pyrox_result["groups"].items():
        level_label = label_for.get(name, name)
        mode = level_modes.get(level_label, "run")
        pace = paces.get(level_label)
        if pace is None:
            continue
        finish = pd.Timestamp(exp_start) + pd.Timedelta(minutes=pace * session_km)

        st.markdown(f"**{level_label}**")
        c1, c2 = st.columns(2)
        with c1:
            sr = sports_risk_for_window(weather_df, exp_start, finish, mode)
            render_sports_risk_card(st, sr, "Sports Medicine Australia / PHS")
        with c2:
            if is_t_re_eligible(level_label):
                win = weather_df[(weather_df.index >= pd.Timestamp(exp_start))
                                 & (weather_df.index <= finish)]
                if not win.empty:
                    tdb = float(win["T_air_urban"].mean())
                    rh = float(win.get("RH", pd.Series([50.0])).mean())
                    duration_min = int((finish - pd.Timestamp(exp_start)).total_seconds() / 60)
                    t_re = t_re_projection(level_label, tdb, rh, duration_min)
                    if t_re is not None and not np.all(np.isnan(t_re)):
                        peak = float(np.nanmax(t_re))
                        crossed = peak >= T_RE_EHS_THRESHOLD
                        st.plotly_chart(
                            t_re_chart(level_label, t_re, pd.Timestamp(exp_start)),
                            use_container_width=True, key=f"exp_tre_{level_label}")
                        if crossed:
                            st.error(
                                f"\u26a0\ufe0f Predicted T_re reaches {peak:.1f}\u00b0C \u2014 "
                                f"at or above the {T_RE_EHS_THRESHOLD}\u00b0C EHS reference."
                            )
                        else:
                            st.caption(f"Predicted peak T_re: {peak:.1f}\u00b0C")
            else:
                st.caption(
                    "T_re projection not shown for this level \u2014 the model is "
                    f"only validated for ages {RIDGE_VALID_AGE[0]}\u2013"
                    f"{RIDGE_VALID_AGE[1]}."
                )
        st.divider()

    if hestia_ctx is not None and HESTIA_AVAILABLE:
        st.markdown("### \U0001F52C HESTIA individual-tier Monte Carlo (real population simulation)")
        st.info(
            "Unlike the two indicators above (which use published but "
            "general-purpose models), this runs the author's own HESTIA "
            "individual tier \u2014 the model with a history of event-hindcast "
            "comparison (Falmouth, Dam tot Damloop, IRONMAN Hoorn; see the "
            "evidence panel). \u26a0\ufe0f **The current calibration is "
            "self-labelled PROVISIONAL in the model's own source code**: "
            "re-fit at a reduced N=200 (not production scale) after a "
            "July 2026 rebuild of the cardiovascular module, pending "
            "production-scale reconfirmation. Treat outputs as directional "
            "research estimates, not settled probabilities. Nothing here "
            "runs automatically: click the button under each level below "
            "for a quick estimate (a few seconds); full precision (n=5000, "
            "several minutes) is a separate, further opt-in after that."
        )
        lat, lon, tz_name = hestia_ctx["lat"], hestia_ctx["lon"], hestia_ctx["tz_name"]
        hestia_results = {}
        for name, res in pyrox_result["groups"].items():
            level_label = label_for.get(name, name)
            pace = paces.get(level_label)
            if pace is None:
                continue
            finish = pd.Timestamp(exp_start) + pd.Timedelta(minutes=pace * session_km)
            met_value = met_from_pace(pace, mode=level_modes.get(level_label, "run"))
            quick = render_hestia_section(
                st, weather_df, lat, lon, tz_name, level_label, met_value,
                pd.Timestamp(exp_start), finish,
            )
            if quick is not None:
                hestia_results[level_label] = quick
        return hestia_results
    elif hestia_ctx is not None and not HESTIA_AVAILABLE:
        st.caption(
            "\u2139\ufe0f HESTIA individual-tier Monte Carlo is unavailable in this "
            f"deployment ({_HESTIA_IMPORT_ERROR}). The two indicators above "
            "are unaffected."
        )
    return {}
