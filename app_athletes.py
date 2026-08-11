# -*- coding: utf-8 -*-
"""
PYROX Athletes — heat risk for runners, beginner to elite
===========================================================
A single-purpose front-end: heat risk for RUNNERS only. No general
population groups, no occupational work/rest tables, no climatology
layer. Everything here is framed around a race or training session.

Two things distinguish it from the general PYROX app:

1. Metabolic rate comes from the athlete's own PACE (ACSM running
   equation) instead of one fixed number per category. A beginner at
   7:30 min/km and an elite at 3:00 min/km differ enormously in metabolic
   heat production, and that difference drives the heat load.

2. The hourly risk layer uses the ATHLETICS federations' WBGT flag
   categories (ACSM guidance / IIRM flags), not ISO 7243 work:rest
   ratios, which are meaningless advice mid-race.

Model layers are shared with the general app (pyrox_bridge,
decision_support, gpx_route, Thermopoulos_Data_Engine) so a fix in one
place applies to both.
"""

import io
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from Thermopoulos_Data_Engine import (
    ROUGHNESS_Z0_TERRAIN,
    fetch_historical_data,
    fetch_hourly_forecast,
    geocode_city_candidates,
    process_weather_data,
    validate_weather_data,
)
from pyrox_bridge import (
    TARGET_GROUPS, excel_bytes, run_pyrox, met_from_pace, daily_effective_met,
    acsm_range_warning,
)
from pyrox_revised_calibration import K_PER_MET, MET_REFERENCE, onset_temperature
from decision_support import (
    render_hourly_safety_panel, relative_risk_text,
    exposure_by_flag, flag_display_name, flag_colour,
    render_flag_reserve_crosscheck, render_pyrox_hestia_crosscheck,
)
from gpx_route import parse_gpx, route_summary, render_race_profile, route_map
from loop_view import render_loop_view
from evidence import render_evidence_panel
from plain_view import render_plain_view
from experimental_risk import render_experimental_section
from report_generator import generate_report_docx

APP_BUILD = "2026-08-10b (dose-response refit post-clo-fix)"


def prediction_record_excel_bytes(
    city_name: str, lat: float, lon: float, tz_name: str,
    exp_start, per_level_exposure: dict, pyrox_result: dict, label_for: dict,
    hestia_results: dict, session_hours: dict, daily_met: dict,
    forecast_df: pd.DataFrame, flag_warnings: list, hestia_warnings: list,
) -> bytes:
    """A single-file record of a prediction, made BEFORE an event or
    heatwave, in a form built for LATER comparison against what actually
    happened -- not a status export.

    Why this exists: Koos is running this app in parallel with real
    events and expected heatwaves. Without something that survives the
    session, every prediction is lost the moment the tab closes or
    Streamlit Cloud reboots (its filesystem is ephemeral -- nothing
    written server-side persists across a redeploy). This is also the
    concrete path from PROVISIONAL calibration to something stronger:
    each parallel run is a comparison point against real GHOR incident
    data, the same kind of evidence the original DtD calibration used,
    just gathered forward instead of retrospectively.

    Deliberately includes empty columns for the real outcome, so the
    SAME file can be completed after the event rather than needing a
    second document to be created and manually matched up later.
    """
    buf = io.BytesIO()

    def _strip_tz(df):
        df = df.copy()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    from loop_view import reserve_series
    from decision_support import worst_flag, flag_display_name

    made_at = pd.Timestamp.now(tz=tz_name)
    exp_date = pd.Timestamp(exp_start).date()

    meta = {
        "prediction_made_at": made_at.strftime("%Y-%m-%d %H:%M %Z"),
        "app_build": APP_BUILD,
        "city": city_name, "lat": lat, "lon": lon, "timezone": tz_name,
        "race_date": str(exp_date), "race_start_time": pd.Timestamp(exp_start).strftime("%H:%M"),
        "note": ("This is a PRE-EVENT prediction. Fill in the 'actual_*' "
                "columns in the Per_Level sheet once real outcomes are "
                "known, to build a comparison record over time."),
    }

    rows = []
    for name, res in pyrox_result["groups"].items():
        level_label = label_for.get(name, name)
        exposure = per_level_exposure.get(level_label, {})
        flag = worst_flag(exposure) if exposure else None
        dates = pyrox_result["dates"]
        matches = [i for i, d in enumerate(dates) if pd.Timestamp(d).date() == exp_date]
        reserve_val = reserve_series(res)[matches[0]] if matches else float("nan")
        hestia = hestia_results.get(level_label)

        rows.append({
            "level": level_label,
            "session_hours": session_hours.get(level_label),
            "daily_weighted_met": daily_met.get(level_label),
            "worst_wbgt_flag": flag_display_name(flag) if flag else "no data",
            "pyrox_reserve_pct_on_race_date": round(reserve_val, 1) if not pd.isna(reserve_val) else None,
            "hestia_computed": hestia is not None,
            "hestia_peak_t_re_mean_c": round(hestia["peak_t_rect_mean"], 2) if hestia else None,
            "hestia_true_ehs_criterion_pct": round(hestia["pct_true_ehs_criterion"], 1) if hestia else None,
            "hestia_broad_screen_pct": round(hestia["pct_first_aid"], 1) if hestia else None,
            "hestia_avg_capacity_remaining_pct": round(hestia["pct_reserve_remaining_mean"], 1) if hestia else None,
            "hestia_zero_or_negative_capacity_pct": round(hestia["pct_zero_or_negative_capacity"], 1) if hestia else None,
            "hestia_vo2max_pinned_pct": round(hestia.get("pct_vo2max_pinned", float("nan")), 1) if hestia else None,
            "hestia_calibration_status": "PROVISIONAL (N=200, not production-scale)" if hestia else "",
            # Deliberately empty -- fill in once the real outcome is known.
            "actual_first_aid_visits": None,
            "actual_hospitalisations": None,
            "actual_ehs_cases": None,
            "actual_participant_count": None,
            "notes": None,
        })
    per_level_df = pd.DataFrame(rows)

    warnings_rows = (
        [{"type": "flag_vs_pyrox_reserve", "text": w} for w in flag_warnings]
        + [{"type": "pyrox_vs_hestia_capacity", "text": w} for w in hestia_warnings]
    )
    warnings_df = pd.DataFrame(warnings_rows) if warnings_rows else pd.DataFrame(
        [{"type": "none", "text": "No divergence warnings fired for this run."}])

    weather_window = forecast_df[
        (forecast_df.index >= pd.Timestamp(exp_start) - pd.Timedelta(hours=6))
        & (forecast_df.index <= pd.Timestamp(exp_start) + pd.Timedelta(hours=6))
    ]

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        pd.DataFrame([meta]).to_excel(writer, sheet_name="Metadata", index=False)
        per_level_df.to_excel(writer, sheet_name="Per_Level", index=False)
        warnings_df.to_excel(writer, sheet_name="Divergence_Warnings", index=False)
        _strip_tz(weather_window).to_excel(writer, sheet_name="Weather_Used")

    return buf.getvalue()


# -----------------------------------------------------------------------------
# Athlete levels. Each maps to an existing PYROX group -- no new calibration is
# invented here. "Beginner" uses the untrained young-adult group, which is the
# only one of the four carrying the PUBLISHED parameterisation (the three
# athlete groups are extrapolated); that is stated in the UI rather than hidden.
# Default paces are typical race paces for each level over ~10-21 km.
# -----------------------------------------------------------------------------
RUNNER_LEVELS = {
    "Beginner runner (untrained)": dict(
        group="adults_18_45", pace=7.5, mode="run",
        note="Untrained or newly active. No heat acclimatisation assumed.",
    ),
    "Recreational runner": dict(
        group="recreational_athletes", pace=6.0, mode="run",
        note="Runs regularly, a few times a week.",
    ),
    "Trained / endurance runner": dict(
        group="endurance_athletes", pace=4.5, mode="run",
        note="Structured training, competes at club level.",
    ),
    "Elite runner": dict(
        group="elite_athletes", pace=3.25, mode="run",
        note="High training volume and well-developed heat acclimatisation.",
    ),
}

# Walking events draw a very different field from running events: older
# participants, children, and people with chronic conditions who would never
# enter a race. Those are exactly the groups PYROX was built around, and
# three of them (adults_18_45, elderly_65_85, very_elderly_85plus) carry the
# PUBLISHED parameterisation rather than the extrapolated one the athlete
# groups use. Walking is also a better fit for the model itself: 2.5-4 MET
# sits inside the range the heat-load coefficient was fitted on, and a
# multi-hour walking day matches the shift length its weighting assumes.
# Default speed 5 km/h (12.0 min/km) except where a slower pace is typical.
WALKER_LEVELS = {
    "Walker — adult (18-45)": dict(
        group="adults_18_45", pace=12.0, mode="walk",
        note="Healthy adult walker.",
    ),
    "Walker — middle-aged (45-65)": dict(
        group="middle_aged_45_65", pace=12.5, mode="walk",
        note="Healthy middle-aged walker.",
    ),
    "Walker — older adult (65-85)": dict(
        group="elderly_65_85", pace=13.5, mode="walk",
        note="Healthy older walker. Published PYROX parameters.",
    ),
    "Walker — vulnerable older adult (85+)": dict(
        group="very_elderly_85plus", pace=15.0, mode="walk",
        note="Frail older walker. Published PYROX parameters. Markedly "
             "reduced thermoregulatory reserve.",
    ),
    "Walker — youth (10-18)": dict(
        group="youth_10_18", pace=12.0, mode="walk",
        note="Typical of school walking events.",
    ),
    "Walker — child (6-10)": dict(
        group="children_6_10", pace=14.0, mode="walk",
        note="Higher surface-area-to-mass ratio and less mature sweating "
             "response than adults.",
    ),
    "Walker — cardiovascular disease": dict(
        group="cardiovascular_disease", pace=14.0, mode="walk",
        note="Reduced cardiac reserve limits the skin blood flow available "
             "for heat loss.",
    ),
    "Walker — obesity": dict(
        group="obesity", pace=14.0, mode="walk",
        note="Greater metabolic heat production per distance and a lower "
             "surface-area-to-mass ratio for dissipating it.",
    ),
}

LEVELS = {**RUNNER_LEVELS, **WALKER_LEVELS}


class RateLimitError(Exception):
    """Open-Meteo returned 429 after exhausting retries."""


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    if "429" in text or "Too Many Requests" in text:
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 429


def with_retry(fn, *args, max_attempts: int = 4, base_delay: float = 2.0, **kwargs):
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not is_rate_limit_error(exc):
                raise
            if attempt < max_attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise RateLimitError(
        "Open-Meteo rate limit reached (HTTP 429) after several retries."
    ) from last_exc


st.set_page_config(page_title="PYROX Participants", page_icon="\U0001F3C3", layout="wide")

st.title("\U0001F3C3 PYROX \u2014 event participants")

# Defensive fix for a known iOS Safari bug: Streamlit's sidebar scroll
# container can "lock up" -- touch-scroll gestures stop registering --
# especially once its content height changes dynamically, which happens
# here whenever the level multiselects change. Scoped to touch devices only
# via (hover: none) and (pointer: coarse), which is never true for a
# mouse/trackpad -- so this never applies on Windows/Chrome or any other
# desktop browser, avoiding any risk of interacting with Streamlit's own
# desktop layout in ways not visually verifiable in this environment.
st.markdown(
    """<style>
    @media (hover: none) and (pointer: coarse) {
        [data-testid="stSidebar"] > div:first-child {
            overflow-y: auto !important;
            -webkit-overflow-scrolling: touch !important;
            height: 100vh !important;
        }
    }
    </style>""",
    unsafe_allow_html=True,
)
st.caption(
    "Heat risk for event participants — runners from beginner to elite, and "
    "walker groups including older adults and children. Race-day flags, "
    "per-group comparison, and optional course analysis from a GPX file."
)

CACHE_TTL_GEOCODE = 60 * 60 * 24 * 30
CACHE_TTL_FORECAST = 60 * 60 * 2
CACHE_TTL_HISTORICAL = 60 * 60 * 24 * 7


@st.cache_data(ttl=CACHE_TTL_GEOCODE, show_spinner=False)
def cached_geocode(city_name: str):
    return with_retry(geocode_city_candidates, city_name)


@st.cache_data(ttl=CACHE_TTL_FORECAST, show_spinner=False)
def cached_forecast(lat: float, lon: float, tz: str, days: int):
    return with_retry(fetch_hourly_forecast, lat, lon, tz, days=days)


@st.cache_data(ttl=CACHE_TTL_HISTORICAL, show_spinner=False)
def cached_historical(lat: float, lon: float, tz: str, start: str, end: str):
    return with_retry(fetch_historical_data, lat, lon, tz, start, end)


def thermal_chart(df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    for col, name, colour, dash in [
        ("T_air_urban", "T_air (urban)", "#f97316", None),
        ("WBGT", "WBGT", "#dc2626", None),
        ("UTCI", "UTCI", "#7c3aed", None),
        ("MRT", "MRT", "#0ea5e9", "dot"),
    ]:
        if col not in df.columns:
            continue
        line = dict(color=colour)
        if dash:
            line["dash"] = dash
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=name, line=line))

    # Athletics flag bands, so the chart is read against the criteria the
    # sport actually uses rather than as bare temperature curves.
    for y0, y1, colour, label in [
        (23.0, 28.0, "rgba(220,38,38,0.07)", "red flag zone (23-28)"),
        (28.0, 45.0, "rgba(127,29,29,0.10)", "black flag zone (>28)"),
    ]:
        fig.add_hrect(y0=y0, y1=y1, line_width=0, fillcolor=colour,
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(size=9, color="#7f1d1d"))

    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", y=0.97, yanchor="top"),
        height=430, margin=dict(l=10, r=20, t=80, b=10),
        legend=dict(orientation="h", yanchor="top", y=1.08, xanchor="left", x=0,
                    font=dict(size=11)),
        hovermode="x unified", yaxis_title="\u00b0C",
    )
    return fig


def strain_chart(pyrox_result: dict, label_for: dict) -> go.Figure:
    dates = [pd.Timestamp(d) for d in pyrox_result["dates"]]
    fig = go.Figure()
    for name, res in pyrox_result["groups"].items():
        pct = 100 * res["cumulative_strain"][1:] / res["critical_strain"]
        fig.add_trace(go.Scatter(x=dates, y=pct, mode="lines+markers",
                                 name=label_for.get(name, name)))
    for level, label, colour in [(50, "caution (50%)", "#f59e0b"),
                                 (75, "danger (75%)", "#f97316"),
                                 (90, "emergency (90%)", "#dc2626")]:
        fig.add_hline(y=level, line_dash="dot", line_color=colour,
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(size=10, color=colour))
    fstart = pyrox_result["forecast_start_idx"]
    if 0 < fstart < len(dates):
        fig.add_shape(type="line", x0=dates[fstart], x1=dates[fstart], y0=0, y1=1,
                      xref="x", yref="paper", line=dict(color="gray", dash="dash"))
        fig.add_annotation(x=dates[fstart], y=1.01, xref="x", yref="paper",
                           text="forecast start", showarrow=False,
                           yanchor="bottom", font=dict(color="gray", size=11))
    fig.update_layout(
        title=dict(text="Accumulated heat strain per level (% of critical threshold)",
                   x=0, xanchor="left", y=0.98, yanchor="top"),
        yaxis_title="% of critical threshold", height=460,
        margin=dict(l=10, r=20, t=70, b=60),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0,
                    font=dict(size=10)),
        hovermode="x unified",
    )
    return fig


# =============================================================================
# Sidebar
# =============================================================================
with st.sidebar:
    st.header("Location & athlete levels")
    city_name = st.text_input("City", placeholder="e.g. Zaandam")

    terrain_options = {k: v[0] for k, v in ROUGHNESS_Z0_TERRAIN.items()}
    terrain_key = st.selectbox(
        "Terrain type (10m \u2192 1.5m wind profile)",
        options=list(terrain_options.keys()),
        format_func=lambda k: terrain_options[k], index=2,
    )
    roughness_z0 = ROUGHNESS_Z0_TERRAIN[terrain_key][1]

    forecast_days = st.slider("Forecast period (days)", 1, 16, 7)

    st.divider()
    selected_runners = st.multiselect(
        "Runner levels", options=list(RUNNER_LEVELS),
        default=list(RUNNER_LEVELS),
    )
    selected_walkers = st.multiselect(
        "Walker groups", options=list(WALKER_LEVELS), default=[],
        help="Walking events draw older participants, children and people "
             "with chronic conditions — groups a race field rarely contains.",
    )
    selected_levels = selected_runners + selected_walkers

    st.divider()
    run_button = st.button("\U0001F680 Run analysis", type="primary",
                           use_container_width=True)
    st.caption(f"Build {APP_BUILD}")

# =============================================================================
# Pace & session settings — MAIN AREA, not sidebar.
# =============================================================================
# Deliberately not in the sidebar: with up to 12 levels selected, this is
# 12+ number_input widgets stacked together, each with its own +/- stepper
# buttons. On iOS Safari that combination is a known trigger for the
# sidebar's scroll container "locking up" -- the stepper buttons' touch
# handlers can swallow the scroll gesture, especially once the sidebar's
# content height changes dynamically (which it does here, as levels are
# added/removed). Moving these widgets to the main area, which scrolls
# with the page rather than in a nested container, sidesteps the bug
# entirely and is also just easier to use with a finger on a tablet.
paces, session_km, use_nocturnal = {}, 10.0, False
if selected_levels:
    st.markdown("### \u2699\ufe0f Pace & session settings")
    pace_cols = st.columns(3)
    for i, lvl in enumerate(selected_levels):
        is_walk = LEVELS[lvl]["mode"] == "walk"
        with pace_cols[i % 3]:
            paces[lvl] = st.number_input(
                lvl, min_value=6.0 if is_walk else 2.5,
                max_value=25.0 if is_walk else 12.0,
                value=float(LEVELS[lvl]["pace"]), step=0.25 if is_walk else 0.05,
                key=f"pace_{lvl}",
                help=LEVELS[lvl]["note"] + " Pace sets the metabolic rate."
                     + (" 12.0 min/km = 5 km/h." if is_walk else ""),
            )

    sc1, sc2 = st.columns([2, 1])
    with sc1:
        session_km = st.number_input(
            "Session / race distance (km)", min_value=1.0, max_value=100.0,
            value=10.0, step=1.0,
            help="Sets how long each level is out on the course, and the "
                 "daily metabolic load for the multi-day view.",
        )
    with sc2:
        use_nocturnal = st.checkbox(
            "Nocturnal recovery", value=False,
            help="Warm nights reduce overnight recovery between sessions.",
        )
    st.divider()


if "results" not in st.session_state:
    st.session_state.results = None
if "candidates" not in st.session_state:
    st.session_state.candidates = None

# =============================================================================
# Metabolic rates from pace
# =============================================================================
if selected_levels:
    met_by_level = {lvl: met_from_pace(paces[lvl], mode=LEVELS[lvl]["mode"])
                    for lvl in selected_levels}
    session_hours = {lvl: paces[lvl] * session_km / 60.0 for lvl in selected_levels}
    daily_met = {lvl: daily_effective_met(met_by_level[lvl], session_hours[lvl])
                 for lvl in selected_levels}
    with st.expander("\u2699\ufe0f How pace becomes heat load", expanded=False):
        st.markdown(
            "Metabolic rate is computed from pace with the ACSM running "
            "equation, then converted to an equivalent apparent-temperature "
            f"penalty at {K_PER_MET:.2f}\u00b0C per MET above "
            f"{MET_REFERENCE:.1f} MET. Metabolic and environmental heat are "
            "physically additive: both leave the body through the same "
            "route, so a faster runner carries a larger total load in the "
            "same weather."
        )
        st.dataframe(
            pd.DataFrame([
                {
                    "Level": lvl,
                    "Mode": LEVELS[lvl]["mode"],
                    "Pace (min/km)": round(paces[lvl], 2),
                    "Speed (km/h)": round(60 / paces[lvl], 1),
                    "Session MET": round(met_by_level[lvl], 1),
                    "Time on course (h)": round(session_hours[lvl], 2),
                    "Daily-weighted MET": round(daily_met[lvl], 2),
                    "Equivalent extra heat (\u00b0C)":
                        round(K_PER_MET * (daily_met[lvl] - MET_REFERENCE), 1),
                }
                for lvl in selected_levels
            ]),
            use_container_width=True, hide_index=True,
        )
        st.info(
            "Notice the daily-weighted values barely differ between levels. "
            "That is not a rounding artefact: the energy cost of running is "
            "close to 1 kcal/kg/km almost regardless of pace, so over the "
            "same distance every level produces broadly similar total heat "
            "\u2014 the beginner slowly over a long time, the elite quickly over "
            "a short one. What separates them on race day is **how long they "
            "stand in the heat**, which is the comparison below."
        )
        st.caption(
            "The 2.29\u00b0C/MET coefficient comes from ISO 7243, whose reference "
            "values are tabulated over roughly 1.2\u20138 MET. **Walking "
            "(2.5\u20134 MET) sits inside that range**, so those loads use the "
            "coefficient as intended. **Running (9\u201319 MET) sits outside it**, "
            "so running loads extrapolate beyond the fitted range \u2014 compare "
            "levels and hours with them, rather than reading them as "
            "calibrated absolute values."
        )
        _warnings = [
            (lvl, acsm_range_warning(paces[lvl], LEVELS[lvl]["mode"]))
            for lvl in selected_levels
        ]
        for lvl, warn in _warnings:
            if warn:
                st.caption(f"\u26a0\ufe0f **{lvl}**: {warn}")

# =============================================================================
# Geocoding + fetch
# =============================================================================
if run_button:
    if not city_name.strip():
        st.warning("Enter a city first.")
    elif not selected_levels:
        st.warning("Select at least one runner level or walker group.")
    else:
        with st.spinner(f"Looking up '{city_name}'..."):
            try:
                st.session_state.candidates = cached_geocode(city_name.strip())
            except Exception as e:
                st.error(f"Geocoding failed: {e}")
                st.session_state.candidates = None

if st.session_state.candidates:
    candidates = st.session_state.candidates
    if len(candidates) > 1:
        labels = [
            f"{c['name']}, {c.get('country', 'Unknown')} "
            f"({c.get('admin1', '')}) \u2014 pop. {c.get('population', 'unknown')}"
            for c in candidates
        ]
        city = candidates[st.selectbox(
            "Multiple locations found — pick one:",
            options=range(len(candidates)), format_func=lambda i: labels[i],
        )]
    else:
        city = candidates[0]

    lat, lon, tz = city["latitude"], city["longitude"], city["timezone"]
    st.success(
        f"**{city['name']}, {city.get('country', 'Unknown')}** \u2014 "
        f"{lat:.4f}\u00b0, {lon:.4f}\u00b0 \u00b7 {tz}"
    )

    with st.spinner("Fetching weather and computing thermal indices..."):
        try:
            forecast_df, f_coastal = cached_forecast(lat, lon, tz, forecast_days)
            forecast_df = validate_weather_data(forecast_df, "forecast")

            f_start = forecast_df.index[0].date()
            h_end = f_start - timedelta(days=1)
            h_start = h_end - timedelta(days=13)
            hindcast_df, h_coastal = cached_historical(
                lat, lon, tz, h_start.strftime("%Y-%m-%d"), h_end.strftime("%Y-%m-%d"))
            hindcast_df = validate_weather_data(hindcast_df, "hindcast")

            forecast_df = process_weather_data(
                forecast_df, city, lat, lon, tz,
                coastal_active=f_coastal, roughness_z0=roughness_z0)
            hindcast_df = process_weather_data(
                hindcast_df, city, lat, lon, tz,
                coastal_active=h_coastal, roughness_z0=roughness_z0)

            meta = {
                "city": city["name"], "country": city.get("country", "Unknown"),
                "latitude": lat, "longitude": lon, "timezone": tz,
                "population": city.get("population", 0),
                "roughness_z0": roughness_z0,
                "terrain_type": terrain_options[terrain_key],
                "model_version": "Thermopoulos v3.1",
            }
            st.session_state.results = {
                "forecast": forecast_df, "hindcast": hindcast_df, "meta": meta,
            }
        except RateLimitError:
            st.error(
                "\u23f3 **Open-Meteo rate limit reached (HTTP 429).** Wait a few "
                "minutes and try again — cached results cost no quota."
            )
            st.session_state.results = None
        except Exception as e:
            st.error(f"Processing failed: {e}")
            st.session_state.results = None

# =============================================================================
# Results
# =============================================================================
if st.session_state.results and selected_levels:
    r = st.session_state.results
    forecast_df, hindcast_df, meta = r["forecast"], r["hindcast"], r["meta"]

    st.plotly_chart(
        thermal_chart(forecast_df, f"{meta['city']} \u2014 conditions"),
        use_container_width=True)
    st.caption(
        "Shaded bands are the athletics-federation WBGT flag zones "
        "(red 23\u201328\u00b0C, black above 28\u00b0C). T_air = air temperature "
        "(UHI-corrected) \u00b7 WBGT = heat-stress index \u00b7 UTCI = physiological "
        "'feels-like' \u00b7 MRT = radiant temperature of the surroundings."
    )

    st.divider()
    st.header("\U0001F6A9 Race-day heat flags")
    st.caption(
        "Hour-by-hour, using the flag categories the athletics governing "
        "bodies apply to road races (ACSM guidance / IIRM flags): green "
        "below 18\u00b0C, yellow 18\u201323\u00b0C, red 23\u201328\u00b0C, black above 28\u00b0C "
        "WBGT. These are the same for every runner by design \u2014 the "
        "per-level comparison below is what adds the pace and fitness "
        "difference the flags leave out."
    )
    render_hourly_safety_panel(
        st, forecast_df, "all runners", met=12.0, scheme="race")

    # -------------------------------------------------------------------
    # Exposure by level -- the comparison that actually separates athlete
    # levels on a single race day (see exposure_by_flag's docstring).
    # -------------------------------------------------------------------
    st.divider()
    st.header("\u23F1\ufe0f Time in the heat, per group")
    st.caption(
        "Over a fixed distance every level produces broadly similar total "
        "metabolic heat, so what separates them on race day is exposure "
        "time: a slower finisher can still be out there when conditions "
        "have moved into the red band that the winner left before."
    )

    ec1, ec2 = st.columns(2)
    with ec1:
        exp_date = st.date_input(
            "Start date", value=forecast_df.index[0].date(),
            min_value=forecast_df.index[0].date(),
            max_value=forecast_df.index[-1].date(), key="exp_date")
    with ec2:
        exp_clock = st.time_input("Start time", value=pd.Timestamp("09:00").time(),
                                  key="exp_clock")

    _tz = forecast_df.index.tz
    exp_start = pd.Timestamp.combine(exp_date, exp_clock)
    exp_start = exp_start.tz_localize(_tz) if _tz is not None else exp_start

    exp_rows, fig_exp = [], go.Figure()
    order = ["race_green", "race_yellow", "race_red", "race_black"]
    per_level_exposure = {}
    for lvl in selected_levels:
        finish = exp_start + pd.Timedelta(minutes=paces[lvl] * session_km)
        exp = exposure_by_flag(forecast_df, exp_start, finish)
        per_level_exposure[lvl] = exp
        row = {"Level": lvl, "Finish": finish.strftime("%H:%M"),
               "On course (h)": round(sum(exp.values()), 2)}
        for st_key in order:
            row[flag_display_name(st_key)] = round(exp.get(st_key, 0.0), 2)
        exp_rows.append(row)

    for st_key in order:
        fig_exp.add_trace(go.Bar(
            y=selected_levels,
            x=[per_level_exposure[l].get(st_key, 0.0) for l in selected_levels],
            name=flag_display_name(st_key), orientation="h",
            marker_color=flag_colour(st_key),
        ))
    fig_exp.update_layout(
        barmode="stack", height=90 + 55 * len(selected_levels),
        xaxis_title="Hours on course", margin=dict(l=10, r=20, t=30, b=10),
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="left", x=0,
                    font=dict(size=10)),
    )
    st.plotly_chart(fig_exp, use_container_width=True)
    st.dataframe(pd.DataFrame(exp_rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Based on a {session_km:.0f} km course at each level's own pace, "
        "against the hourly forecast. Hours are fractional."
    )

    st.divider()
    st.header("\U0001F4C8 Per-group comparison")
    st.warning(
        "\u26a0\ufe0f **Screening tool, not a validated medical prediction.** "
        "PYROX's population tier has not been checked against real incident "
        "or hospital records for these groups. The three athlete groups "
        "(recreational, endurance, elite) use extrapolated rather than "
        "published parameters; several walker groups (adults 18-45, older "
        "adults 65-85, vulnerable older adults 85+) use the published ones. "
        "Use this to compare groups and days \u2014 not as a probability of "
        "harm for any individual participant."
    )

    group_for = {lvl: LEVELS[lvl]["group"] for lvl in selected_levels}
    label_for = {v: k for k, v in group_for.items()}
    met_by_group = {group_for[lvl]: daily_met[lvl] for lvl in selected_levels}

    excel_data = excel_bytes(forecast_df, hindcast_df, None, meta)
    hindcast_days_used = min(14, len(hindcast_df.index.normalize().unique()))
    forecast_days_used = min(7, forecast_days)

    pyrox_result = run_pyrox(
        excel_data, tuple(group_for[lvl] for lvl in selected_levels),
        forecast_days_used, hindcast_days_used, use_nocturnal,
        tuple(sorted(met_by_group.items())),
    )

    render_plain_view(st, pyrox_result, label_for, target_date=exp_date)
    flag_warnings = render_flag_reserve_crosscheck(
        st, per_level_exposure, pyrox_result, label_for, exp_date,
        session_hours, daily_met,
    )

    st.divider()
    level_modes = {lvl: LEVELS[lvl]["mode"] for lvl in selected_levels}
    hestia_results = render_experimental_section(
        st, pyrox_result, label_for, forecast_df, level_modes,
        exp_start, session_km, paces,
        hestia_ctx={"lat": lat, "lon": lon, "tz_name": tz},
    )

    with st.expander("Technical view — accumulated strain against thresholds"):
        st.plotly_chart(strain_chart(pyrox_result, label_for),
                        use_container_width=True)

    rows = []
    dates = pyrox_result["dates"]
    for lvl in selected_levels:
        g = group_for[lvl]
        res = pyrox_result["groups"][g]

        def _d(idx):
            return dates[idx] if idx is not None and idx < len(dates) else "\u2014"

        peak = float(max(res["final_risk"]))
        mild, paris = relative_risk_text(peak, g, pyrox_result["group_mets"][g])
        rows.append({
            "Level": lvl,
            "Pace": f"{paces[lvl]:.2f} min/km",
            "MET": round(met_by_level[lvl], 1),
            "vs. mild summer": f"{mild:.1f}\u00d7" if mild else "\u2014",
            "vs. Paris 2003": f"{paris:.0f}%" if paris else "\u2014",
            "Peak strain (%)": round(100 * res["peak_strain"] / res["critical_strain"], 1),
            "Caution day": _d(res["caution_day"]),
            "Danger day": _d(res["danger_day"]),
            "Emergency day": _d(res["emergency_day"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "'vs. mild summer' and 'vs. Paris 2003' put each level's peak load "
        "against two reference weeks for that same level \u2014 comparisons to "
        "known scenarios, not calibrated probabilities. Caution/danger/"
        "emergency = the day accumulated strain first crosses 50% / 75% / "
        "90% of that level's critical threshold; '\u2014' means it was not "
        "reached in this period."
    )

    st.divider()
    render_loop_view(st, pyrox_result, forecast_df, label_for)
    hestia_warnings = render_pyrox_hestia_crosscheck(
        st, hestia_results, pyrox_result, label_for, exp_date)

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "\U0001F4E5 Download prediction record (Excel)",
            data=prediction_record_excel_bytes(
                city["name"], lat, lon, tz, exp_start, per_level_exposure,
                pyrox_result, label_for, hestia_results, session_hours, daily_met,
                forecast_df, flag_warnings, hestia_warnings,
            ),
            file_name=f"pyrox_prediction_{city['name']}_{exp_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Saves this run's numbers (across all layers) with empty "
                 "columns for the real outcome, for later comparison. "
                 "Streamlit Cloud does not persist anything on its own -- "
                 "download this if you want to keep the prediction.",
        )
    with col_b:
        slowest_pace = max(paces.values()) if paces else 12.0
        latest_finish = pd.Timestamp(exp_start) + pd.Timedelta(minutes=slowest_pace * session_km)
        st.download_button(
            "\U0001F4C4 Download findings report (Word)",
            data=generate_report_docx(
                city["name"], exp_start, forecast_df, per_level_exposure,
                pyrox_result, label_for, hestia_results, latest_finish,
                flag_warnings, hestia_warnings, tz, APP_BUILD,
                met_by_level_label={label_for.get(lvl, lvl): met_by_level[lvl]
                                    for lvl in met_by_level},
                duration_by_level_label={label_for.get(lvl, lvl): paces[lvl] * session_km
                                         for lvl in paces},
            ),
            file_name=f"pyrox_report_{city['name']}_{exp_date}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            help="A readable Word report of the same findings, for sharing "
                 "with GHOR or event organisers. Data and findings only -- "
                 "deliberately does not recommend any operational measures.",
        )

    render_evidence_panel(st)

    # -------------------------------------------------------------------
    # Optional course analysis
    # -------------------------------------------------------------------
    st.divider()
    st.header("\U0001F3C1 Course analysis (GPX)")
    st.caption(
        "Upload a route to see what each level actually runs through, at "
        "their own pace, and the flags for their real start-to-finish window."
    )
    gpx_file = st.file_uploader("Race route (.gpx)", type=["gpx"])

    if gpx_file is not None:
        try:
            parsed = parse_gpx(gpx_file)
        except Exception as e:
            st.error(f"Could not parse this GPX file: {e}")
            parsed = None

        if parsed is not None and not parsed["route"].empty:
            route_df, waypoints = parsed["route"], parsed["waypoints"]
            summary = route_summary(route_df)
            st.success(
                f"**{summary['total_km']:.2f} km** course, "
                f"{len(waypoints)} water post(s)"
                + (f", {summary['elevation_gain_m']:.0f} m climb"
                   if summary["has_elevation"] else " (flat)")
            )

            c1, c2 = st.columns(2)
            with c1:
                race_date = st.date_input(
                    "Race date", value=forecast_df.index[0].date(),
                    min_value=forecast_df.index[0].date(),
                    max_value=forecast_df.index[-1].date())
            with c2:
                race_clock = st.time_input("Start time",
                                           value=pd.Timestamp("09:00").time())

            tzinfo = forecast_df.index.tz
            start_time = pd.Timestamp.combine(race_date, race_clock)
            start_time = start_time.tz_localize(tzinfo) if tzinfo is not None else start_time

            st.plotly_chart(
                route_map(route_df, waypoints,
                          f"Course \u2014 {summary['total_km']:.1f} km"),
                use_container_width=True)
            st.caption("Map \u00a9 OpenStreetMap contributors.")

            for lvl in selected_levels:
                st.divider()
                render_race_profile(
                    st, route_df, waypoints, forecast_df, lvl,
                    met_by_level[lvl], start_time, paces[lvl],
                    render_hourly_safety_panel,
                )

elif not st.session_state.results:
    st.info(
        "Enter a city on the left, pick the runner levels and/or walker "
        "groups you want to compare, and click **Run analysis**."
    )
