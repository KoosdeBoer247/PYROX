# -*- coding: utf-8 -*-
"""
PYROX — simplified view for policymakers and event organisers
=================================================================
Same location/level sidebar and pace/session inputs as app_athletes.py,
but the main area is deliberately reduced to what this audience actually
needs to assess risk for ONE specific run (given its length, date, and
start time) -- not the full research interface with raw/uncalibrated
figures, PROVISIONAL warnings, and methodology cross-checks.

Shown:
  - Weather conditions (T_air/WBGT/UTCI/MRT) leading into and through
    the race window
  - Time each level spends in each WBGT flag band
  - The headline "EHS estimate (per 1000)" -- the dose-response model,
    the same calibrated figure app_athletes.py treats as primary
  - The T_rect-vs-CO_reserve scatter (the danger quadrant)
  - Peak T_re and CO_reserve distributions
  - How risk builds over time for representative participants

An optional "Historical (hindcast)" weather source (alongside the default
forecast) lets this page re-run a past date using observed weather from
the Open-Meteo archive, rather than an upcoming forecast -- for checking
a prediction against a real, already-known event. Everything downstream
(charts, EHS estimate, Word report, Excel prediction record) is identical
either way; only the weather source and the exported files' own labelling
change.

Deliberately NOT shown: raw/uncalibrated HESTIA figures, the PROVISIONAL
calibration caveats, multi-day PYROX context, GPX course analysis, the
evidence panel, cross-check explanations. Those stay in app_athletes.py
for the audience that needs the full methodology.
"""

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
from pyrox_bridge import met_from_pace
from pyrox_groups import WALKER_LEVELS, LEVELS
from decision_support import exposure_by_flag, flag_display_name, flag_colour
import hestia_bridge as hb
from hestia_model import PF_DUUR_MIN
from report_generator import (
    _t_rect_co_reserve_scatter, _hestia_distribution_chart,
    _co_reserve_distribution_chart, dose_evolution_chart,
    generate_policy_report_docx, dose_positive_count, dose_positive_warning_text,
    generate_policy_prediction_excel_bytes,
)

APP_BUILD = "2026-08-14a (historical/hindcast mode)"


# =============================================================================
# Weather-fetch helpers -- same pattern as app_athletes.py. Duplicated
# rather than imported (importing a sibling Streamlit script would
# re-execute its whole page as a side effect), but kept intentionally
# small and unchanged from the original so it can be diffed against it.
# =============================================================================
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


st.set_page_config(page_title="PYROX Policy View", page_icon="\U0001F3DB\ufe0f", layout="wide")
st.title("\U0001F3DB\ufe0f PYROX \u2014 simplified view for organisers & policymakers")
st.caption(
    "A reduced view: expected EHS cases per 1000, and the plots most "
    "relevant for assessing risk on a specific run's length, date, and "
    "start time. For the full methodology and raw model outputs, use the "
    "participants view instead."
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


# =============================================================================
# Sidebar -- same structure as app_athletes.py
# =============================================================================
with st.sidebar:
    st.header("Location & levels")
    city_name = st.text_input("City", placeholder="e.g. Zaandam")

    # English labels for this page only -- ROUGHNESS_Z0_TERRAIN itself
    # (Thermopoulos_Data_Engine.py) stays in Dutch since it's shared with
    # app.py/app_athletes.py, which keep their Dutch interface. Same
    # keys, so the underlying roughness values are unaffected.
    TERRAIN_LABELS_EN = {
        "1": "Open water / sea",
        "2": "Open coast, beach, short grass (few obstacles)",
        "3": "Open agricultural land, scattered obstacles",
        "4": "Parkland / scattered buildings, trees",
        "5": "Suburban (low-rise buildings, gardens, trees)",
        "6": "Urban / city centre (tall, dense buildings)",
    }
    terrain_key = st.selectbox(
        "Terrain type (10m \u2192 1.5m wind profile)",
        options=list(ROUGHNESS_Z0_TERRAIN.keys()),
        format_func=lambda k: TERRAIN_LABELS_EN.get(k, ROUGHNESS_Z0_TERRAIN[k][0]),
        index=2,
    )
    roughness_z0 = ROUGHNESS_Z0_TERRAIN[terrain_key][1]

    st.divider()
    data_mode = st.radio(
        "Weather source", options=["Forecast (upcoming)", "Historical (hindcast)"],
        index=0,
        help="Forecast: upcoming weather via Open-Meteo, for planning an "
             "event ahead of time. Historical: observed weather from the "
             "Open-Meteo archive for a past date range, for checking this "
             "model's prediction against a real event that already "
             "happened -- e.g. re-running a past race day and comparing "
             "against the actual outcome logged in a prediction record "
             "(see the download button below).",
    )
    use_historical = data_mode.startswith("Historical")
    forecast_days = 7
    hist_start, hist_end = None, None
    if use_historical:
        default_end = date.today() - timedelta(days=1)
        default_start = default_end - timedelta(days=6)
        hc1, hc2 = st.columns(2)
        with hc1:
            hist_start = st.date_input("Historical start", value=default_start,
                                       max_value=date.today() - timedelta(days=1))
        with hc2:
            hist_end = st.date_input("Historical end", value=default_end,
                                     max_value=date.today() - timedelta(days=1))
        if hist_start > hist_end:
            st.warning("Historical start date must be before the end date.")
    else:
        forecast_days = st.slider("Forecast period (days)", 1, 16, 7)

    st.divider()
    # Runner type is deliberately fixed to "Recreational runner" on this
    # page -- the most relevant group for policymakers -- rather than the
    # full runner-level multiselect app_athletes.py offers. Walker groups
    # keep their full choice, since that variety (age, chronic conditions)
    # is exactly what this audience needs to see.
    include_recreational_runner = st.checkbox(
        "Include recreational runner", value=True,
        help="This page limits the runner category to 'Recreational "
             "runner' -- the group most representative of a typical "
             "event field. For the full range of runner levels "
             "(beginner to elite), use the participants view.",
    )
    selected_runners = ["Recreational runner"] if include_recreational_runner else []
    selected_walkers = st.multiselect(
        "Walker groups", options=list(WALKER_LEVELS), default=[],
    )
    selected_levels = selected_runners + selected_walkers

    st.divider()
    n_simulations = st.number_input(
        "Number of simulations", min_value=20, max_value=1000,
        value=100, step=20,
        help="How many virtual participants the physiological model "
             "simulates per level. More simulations give a more "
             "statistically reliable estimate -- especially important "
             "when the expected number of cases is small, where a low "
             "count can otherwise look more or less serious than it "
             "really is just by chance. Higher values take longer to "
             "compute: a few seconds at 100, roughly a minute or more "
             "as you approach 1000.",
    )

    st.divider()
    run_button = st.button("\U0001F680 Run analysis", type="primary",
                           use_container_width=True)
    st.caption(f"Build {APP_BUILD}")

# =============================================================================
# Pace & session settings -- main area, same iOS-scroll-lock rationale
# as app_athletes.py (see that file for the full explanation).
# =============================================================================
paces, session_km = {}, 10.0
if selected_levels:
    st.markdown("### \u2699\ufe0f Run parameters")
    pace_cols = st.columns(3)
    for i, lvl in enumerate(selected_levels):
        is_walk = LEVELS[lvl]["mode"] == "walk"
        with pace_cols[i % 3]:
            paces[lvl] = st.number_input(
                f"{lvl} (min/km)", min_value=6.0 if is_walk else 2.5,
                max_value=25.0 if is_walk else 12.0,
                value=float(LEVELS[lvl]["pace"]), step=0.25 if is_walk else 0.05,
                key=f"pace_{lvl}",
                help="Pace in minutes per kilometre -- lower is faster. "
                     "This sets how much metabolic heat this level "
                     "produces during the event."
                     + (" 12.0 min/km = 5 km/h." if is_walk else
                       " 6.0 min/km = 10 km/h."),
            )
    session_km = st.number_input(
        "Race distance (km)", min_value=1.0, max_value=100.0,
        value=10.0, step=1.0,
    )
    st.divider()

if "results" not in st.session_state:
    st.session_state.results = None
if "candidates" not in st.session_state:
    st.session_state.candidates = None
if "beleid_hestia_by_level" not in st.session_state:
    # Populated as each level's "Calculate" button is used, so the Word
    # report (built after this loop) can include every level the reader
    # has already looked at without recomputing anything. Cleared on a
    # fresh "Run analysis" (new city/date) below, so a report can never
    # silently mix results from a previous location.
    st.session_state.beleid_hestia_by_level = {}

# =============================================================================
# Geocoding + fetch
# =============================================================================
if run_button:
    if not city_name.strip():
        st.warning("Enter a city first.")
    elif not selected_levels:
        st.warning("Select at least one level.")
    else:
        with st.spinner(f"Looking up '{city_name}'..."):
            try:
                st.session_state.candidates = cached_geocode(city_name.strip())
                st.session_state.beleid_hestia_by_level = {}
            except Exception as e:
                st.error(f"Geocoding failed: {e}")
                st.session_state.candidates = None

if st.session_state.candidates:
    candidates = st.session_state.candidates
    if len(candidates) > 1:
        labels = [
            f"{c['name']}, {c.get('country', 'Unknown')} "
            f"({c.get('admin1', '')})"
            for c in candidates
        ]
        city = candidates[st.selectbox(
            "Multiple locations found — pick one:",
            options=range(len(candidates)), format_func=lambda i: labels[i],
        )]
    else:
        city = candidates[0]

    lat, lon, tz = city["latitude"], city["longitude"], city["timezone"]
    st.success(f"**{city['name']}, {city.get('country', 'Unknown')}**")

    with st.spinner("Fetching weather and computing thermal indices..."):
        try:
            if use_historical:
                if hist_start > hist_end:
                    raise ValueError("Historical start date must be before the end date.")
                weather_df, w_coastal = cached_historical(
                    lat, lon, tz, hist_start.strftime("%Y-%m-%d"),
                    hist_end.strftime("%Y-%m-%d"))
                weather_df = validate_weather_data(weather_df, "historical")
            else:
                weather_df, w_coastal = cached_forecast(lat, lon, tz, forecast_days)
                weather_df = validate_weather_data(weather_df, "forecast")
            weather_df = process_weather_data(
                weather_df, city, lat, lon, tz,
                coastal_active=w_coastal, roughness_z0=roughness_z0)
            st.session_state.results = {"forecast": weather_df, "is_historical": use_historical}
        except RateLimitError:
            st.error("\u23f3 Open-Meteo rate limit reached. Wait a few minutes and try again.")
            st.session_state.results = None
        except Exception as e:
            st.error(f"Could not fetch weather: {e}")
            st.session_state.results = None

if st.session_state.results and selected_levels:
    forecast_df = st.session_state.results["forecast"]
    is_historical = st.session_state.results.get("is_historical", False)

    if is_historical:
        st.info(
            "\U0001F4DC **Hindcast mode** \u2014 this analysis uses observed "
            "historical weather (Open-Meteo archive), not a forecast. Use "
            "this to check the model's prediction against a real event "
            "that already happened."
        )

    st.markdown("### \U0001F4C5 Race date & start time")
    ec1, ec2 = st.columns(2)
    with ec1:
        exp_date = st.date_input(
            "Start date", value=forecast_df.index[0].date(),
            min_value=forecast_df.index[0].date(),
            max_value=forecast_df.index[-1].date(), key="beleid_exp_date")
    with ec2:
        exp_clock = st.time_input("Start time", value=pd.Timestamp("09:00").time(),
                                  key="beleid_exp_clock")

    _tz = forecast_df.index.tz
    exp_start = pd.Timestamp.combine(exp_date, exp_clock)
    exp_start = exp_start.tz_localize(_tz) if _tz is not None else exp_start

    # ---- Weather chart -----------------------------------------------
    st.divider()
    st.plotly_chart(
        thermal_chart(forecast_df, f"Weather conditions \u2014 {city['name']}"),
        use_container_width=True,
    )

    # ---- Time in each flag band, per level ----------------------------
    per_level_exposure, finish_by_level = {}, {}
    for lvl in selected_levels:
        finish = exp_start + pd.Timedelta(minutes=paces[lvl] * session_km)
        finish_by_level[lvl] = finish
        per_level_exposure[lvl] = exposure_by_flag(forecast_df, exp_start, finish)

    order = ["race_green", "race_yellow", "race_red", "race_black"]
    fig_exp = go.Figure()
    for st_key in order:
        fig_exp.add_trace(go.Bar(
            y=selected_levels,
            x=[per_level_exposure[lvl].get(st_key, 0.0) for lvl in selected_levels],
            name=flag_display_name(st_key), orientation="h",
            marker_color=flag_colour(st_key),
        ))
    fig_exp.update_layout(
        barmode="stack", title="Time in each heat-flag band, per level",
        height=120 + 60 * len(selected_levels), xaxis_title="hours",
        margin=dict(l=10, r=20, t=60, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10)),
    )
    st.plotly_chart(fig_exp, use_container_width=True)
    st.caption(
        "\u2139\ufe0f This chart is based on WBGT (Wet Bulb Globe Temperature), "
        "an instantaneous measure of ambient heat stress at each hour -- "
        "it does not account for cumulative physiological strain over "
        "the course of the event, individual differences in fitness or "
        "hydration, or the elevated risk immediately after finishing. "
        "The EHS estimate below, from the full physiological simulation, "
        "can therefore show meaningfully higher risk than the WBGT flag "
        "colours alone would suggest -- treat WBGT as a same-hour "
        "ambient-conditions indicator, not as the full risk picture."
    )

    # ---- HESTIA per level ----------------------------------------------
    st.divider()
    st.markdown("### \U0001F3E5 Expected EHS cases per 1000 participants")
    for lvl in selected_levels:
        met_value = met_from_pace(paces[lvl], mode=LEVELS[lvl]["mode"])
        finish = finish_by_level[lvl]
        st.markdown(f"#### {lvl}")
        req_key = f"beleid_requested_{lvl}"
        if req_key not in st.session_state:
            st.session_state[req_key] = False
        if not st.session_state[req_key]:
            if st.button(f"Calculate for {lvl}", key=f"beleid_btn_{lvl}"):
                st.session_state[req_key] = True
                st.rerun()
            continue

        progress = st.progress(0.0, text=f"Starting simulation for {lvl}...")

        def _progress_cb(done, total):
            progress.progress(done / total, text=f"{lvl}: {done}/{total} simulated participants...")

        with st.spinner(f"Running physiological simulation for {lvl} "
                        f"({n_simulations} simulations)..."):
            result = hb.run_full_precision(
                forecast_df, lat, lon, tz, exp_start, finish, met_value=met_value,
                n_simulations=n_simulations, progress_callback=_progress_cb,
            )
        progress.empty()

        if result is None:
            st.warning("Simulation did not return a usable result for this level.")
            continue

        st.session_state.beleid_hestia_by_level[lvl] = {
            "finish": finish,
            "post_finish_end": finish + pd.Timedelta(minutes=PF_DUUR_MIN),
            "hestia_result": result,
            "met_value": met_value,
            "duration_minutes": paces[lvl] * session_km,
        }

        dose_pct = result.get("pct_dose_response_ehs")
        falmouth_est = result.get("falmouth_ehs_per_1000")
        mean_t = result.get("mean_t_air_race_window")
        broad_screen = result.get("pct_first_aid")
        if dose_pct is not None:
            c1, c2, c3 = st.columns(3)
            c1.metric(
                f"EHS estimate \u2014 {lvl}", f"\u2248{dose_pct*10:.1f} per 1000",
                help="Dose-response model over this level's actual pace, "
                     "duration and simulated physiology, calibrated against "
                     "Falmouth Road Race epidemiology (DeMartini et al. "
                     "2014). EXPLORATORY calibration -- see the participants "
                     "view for full methodology and caveats. This is the "
                     "number to use.")
            if falmouth_est is not None:
                c2.metric(
                    "Alternative estimate (temperature only)",
                    f"\u2248{falmouth_est:.1f} per 1000",
                    help="A second, independent estimate from real "
                         "Falmouth Road Race incident records (DeMartini "
                         "et al. 2014), based ONLY on today's ambient "
                         "temperature"
                         + (f" ({mean_t:.1f}\u00b0C)" if mean_t is not None else "")
                         + " -- unlike the number on the left, it cannot "
                           "see this level's actual pace, distance, or "
                           "group, so it will not move if you change "
                           "those. Shown as a cross-check, not as the "
                           "figure to act on: two independent methods "
                           "landing in the same range is reassuring, but "
                           "a difference between them does not mean "
                           "either one is wrong.")
            if broad_screen is not None:
                c3.metric(
                    "Worth monitoring (broad screen)", f"{broad_screen:.1f}%",
                    help="A deliberately WIDE screening flag: T_rect\u2265"
                         "40.5\u00b0C OR dehydration\u22652% OR RPE\u226517 "
                         "-- any one of the three, not the strict "
                         "conjunctive EHS criterion the estimate on the "
                         "left uses, and NOT gated by that criterion's "
                         "dose-response floor value either. Useful as an "
                         "independent cross-check: if this also reads near "
                         "zero, that supports \u201cnothing detected\u201d; "
                         "if it doesn't, that's worth a closer look even "
                         "when the EHS estimate is only the floor value. "
                         "Not a medical-incident-rate prediction on its "
                         "own -- it is intentionally broad.")

        n_dose_pos, n_dose_total = dose_positive_count(result)
        if n_dose_total > 0:
            st.caption(
                f"\U0001F465 Estimate based on {n_dose_pos} of {n_dose_total} "
                f"simulated participants who ever reached a non-zero dose "
                f"(distinct participants, not timestep-points \u2014 the "
                f"scatter plot below counts every timestep, so one "
                f"participant lingering in the danger quadrant contributes "
                f"several points there)."
            )
        dose_warning = dose_positive_warning_text(
            n_dose_pos, n_dose_total, result.get("pct_first_aid"), mean_t)
        if dose_warning:
            if n_dose_pos == 0:
                st.info(f"\u2139\ufe0f {dose_warning}")
            else:
                st.warning(f"\u26a0\ufe0f {dose_warning}")

        chart_cols = st.columns(2)
        pairs = result.get("t_rect_co_reserve_pairs", [])
        scatter = _t_rect_co_reserve_scatter(pairs, lvl) if pairs else None
        if scatter is not None:
            chart_cols[0].image(scatter.getvalue(),
                               caption="T_rect vs CO_reserve \u2014 every simulated "
                                      "participant, every timestep. Shaded "
                                      "quadrant = the true EHS criterion.")

        # The population median trace is deliberately excluded here --
        # for this non-expert audience it risks reading as "this is what
        # happens", when it's a point-by-point statistical aggregate
        # that no single real participant actually experiences. The
        # individual example lines (or, when every dose is zero, the
        # coolest/median/hottest-by-T_rect fallback) are more directly
        # interpretable on their own.
        traces = [tr for tr in result.get("representative_traces", [])
                 if tr.get("label") != "Population median"]
        dose_chart = dose_evolution_chart(traces, lvl) if traces else None
        if dose_chart is not None:
            chart_cols[1].image(dose_chart.getvalue(),
                               caption="How risk builds over time for "
                                      "representative participants.")

        dist_cols = st.columns(2)
        t_dist = _hestia_distribution_chart(result.get("peak_t_rect_all", []), lvl)
        if t_dist is not None:
            dist_cols[0].image(t_dist.getvalue(),
                              caption="Distribution of peak core temperature.")
        co_dist = _co_reserve_distribution_chart(
            result.get("worst_co_reserve_all", []), lvl)
        if co_dist is not None:
            dist_cols[1].image(co_dist.getvalue(),
                              caption="Distribution of worst cardiovascular reserve.")

        st.divider()

    # -------------------------------------------------------------------
    # Word report -- the chosen day in general, then one zoomed section
    # per level from its own start time through HESTIA's post-finish
    # window. Levels not yet calculated (button not pressed) are still
    # listed in the report, flagged as not calculated, rather than
    # silently omitted -- a reader comparing the report to the screen
    # should never wonder why a selected level is simply missing.
    # -------------------------------------------------------------------
    st.markdown("### \U0001F4C4 Policy report")
    levels_data = {}
    for lvl in selected_levels:
        cached = st.session_state.beleid_hestia_by_level.get(lvl)
        if cached is not None:
            levels_data[lvl] = cached
        else:
            levels_data[lvl] = {
                "finish": finish_by_level[lvl],
                "post_finish_end": finish_by_level[lvl] + pd.Timedelta(minutes=PF_DUUR_MIN),
                "hestia_result": None,
                "met_value": met_from_pace(paces[lvl], mode=LEVELS[lvl]["mode"]),
                "duration_minutes": paces[lvl] * session_km,
            }

    not_calculated = [lvl for lvl, d in levels_data.items() if d["hestia_result"] is None]
    if not_calculated:
        st.caption(
            "\u2139\ufe0f Not yet calculated, so not included with physiological "
            "detail in the report: " + ", ".join(not_calculated) +
            ". Use \u201cCalculate\u201d above first if you want full findings "
            "for these levels."
        )

    st.download_button(
        "\U0001F4C4 Download policy report (Word)",
        data=generate_policy_report_docx(
            city["name"], exp_date, exp_start, forecast_df, levels_data,
            tz, APP_BUILD, is_hindcast=is_historical,
        ),
        file_name=(f"pyrox_beleid_hindcast_{city['name']}_{exp_date}.docx"
                  if is_historical else
                  f"pyrox_beleid_report_{city['name']}_{exp_date}.docx"),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        help="A Word report: the chosen day overall, then a zoomed section "
             "per level from its own start time through the race and "
             "HESTIA's post-finish window. Same scope as this page -- no "
             "raw/uncalibrated figures, no PROVISIONAL caveats, no "
             "multi-day PYROX context. Data and findings only, no "
             "recommended actions.",
    )

    st.download_button(
        "\U0001F4E5 Download prediction record (Excel)",
        data=generate_policy_prediction_excel_bytes(
            city["name"], lat, lon, tz, exp_date, exp_start, forecast_df,
            levels_data, APP_BUILD, is_hindcast=is_historical,
        ),
        file_name=(f"pyrox_beleid_hindcast_record_{city['name']}_{exp_date}.xlsx"
                  if is_historical else
                  f"pyrox_beleid_prediction_{city['name']}_{exp_date}.xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Saves this run's numbers with empty columns for the real "
             "outcome (actual_first_aid_visits, actual_hospitalisations, "
             "actual_ehs_cases), to fill in after the event. Streamlit "
             "Cloud does not persist anything on its own -- download this "
             "if you want to compare this prediction against reality "
             "later. This is also the only way to actually check whether "
             "the dose-response floor value (shown when no participant "
             "reaches a non-zero dose) holds up: comparing predictions "
             "like this one against real outcomes across many events, not "
             "from any single simulation.",
    )
