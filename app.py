# -*- coding: utf-8 -*-
"""
PYROX — heat-risk web app
=========================
Streamlit interface on top of the Thermopoulos Data Engine (weather
acquisition + thermal-index processing) and the PYROX population-tier
heat-strain model. Built for an international audience — all user-facing
text is in English.

Note: this app exposes the Thermopoulos + PYROX layers only. The HESTIA
individual-tier cardiovascular Monte Carlo simulation is a separate,
heavier workload (minutes per run) and is not part of this interface.
"""

import io
import tempfile
import time
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from Thermopoulos_Data_Engine import (
    ROUGHNESS_Z0_TERRAIN,
    fetch_historical_data,
    fetch_hourly_forecast,
    geocode_city_candidates,
    process_weather_data,
    validate_weather_data,
)
from thermopoulos_loader import (
    ThermopoulosData,
    apparent_temperature,
    HEAT_LOAD_REFERENCE_TEMP,
    HEAT_LOAD_PER_DEGREE,
)
from pyrox_model import PyroxModel
from pyrox_groups import TARGET_GROUPS, PAPER_PROTOTYPES

# pythermalcomfort's UTCI implementation (ISO/CIE-based) is only validated for
# air temperatures within this range; inputs outside it are silently set to
# NaN rather than extrapolated. Locations with T_air beyond ~50°C (e.g. Death
# Valley, parts of the Gulf, Jacobabad) can legitimately exceed this bound.
UTCI_TDB_MIN, UTCI_TDB_MAX = -50.0, 50.0
# UTCI is also only defined for wind speeds in this range (see UTCI_valid
# column produced by the engine); outside it, UTCI is likewise NaN.
UTCI_WIND_MIN, UTCI_WIND_MAX = 0.5, 17.0


# =============================================================================
# Rate-limit handling for Open-Meteo
# =============================================================================
# Free tier: 10,000 calls/day, 5,000/hour, 600/minute. Note that requests
# spanning more than two weeks for one location count as MORE than one call
# (fractional weighting), so a 21-day window is ~1.5 calls. The climatology
# feature is the expensive one — hence the throttling and reduced defaults.
class RateLimitError(Exception):
    """Raised when Open-Meteo returns 429 after exhausting retries."""


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    if "429" in text or "Too Many Requests" in text:
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 429


def with_retry(fn, *args, max_attempts: int = 4, base_delay: float = 2.0, **kwargs):
    """Call fn with exponential backoff on transient rate-limit errors.

    Waits 2s, 4s, 8s between attempts. Raises RateLimitError if all attempts
    are rate-limited, so callers can degrade gracefully rather than crash.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - need to inspect any exception type
            last_exc = exc
            if not is_rate_limit_error(exc):
                raise
            if attempt < max_attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise RateLimitError(
        "Open-Meteo rate limit reached (HTTP 429) after several retries."
    ) from last_exc

# =============================================================================
# Page setup
# =============================================================================
st.set_page_config(
    page_title="PYROX",
    page_icon="\U0001F321\uFE0F",
    layout="wide",
)

st.title("\U0001F321\uFE0F PYROX")
st.caption(
    "Weather acquisition, thermal-index processing, and population-level "
    "heat-strain risk — forecast, hindcast, and custom historical periods."
)

# =============================================================================
# Legend: explanation of the thermal-index abbreviations used throughout
# =============================================================================
METRIC_INFO = {
    "T_air": (
        "Air temperature (dry-bulb) at 2m height, corrected for the urban "
        "heat-island effect (UHI). The 'ordinary' temperature a thermometer "
        "reads in the shade."
    ),
    "MRT": (
        "Mean Radiant Temperature — the average radiant temperature of the "
        "surroundings (sun plus heat re-emitted by surfaces) as the body "
        "experiences it. Can run well above T_air in direct sun."
    ),
    "WBGT": (
        "Wet Bulb Globe Temperature — a combined heat-stress index (wet-bulb, "
        "globe, and air temperature) that also accounts for humidity and "
        "radiant heat. Widely used in occupational and sports heat guidelines."
    ),
    "UTCI": (
        "Universal Thermal Climate Index — an index of how an average person "
        "physiologically experiences the environment, combining temperature, "
        "humidity, wind, and radiation. Serves a similar purpose to 'feels-like'."
    ),
}

with st.expander("\u2139\uFE0F What do T_air, MRT, WBGT, and UTCI mean?"):
    for name, desc in METRIC_INFO.items():
        st.markdown(f"**{name}** — {desc}")

# =============================================================================
# Cached wrappers around the engine's I/O functions
# (cache_data keyed on the actual arguments; TTL keeps forecasts from going stale)
# =============================================================================

@st.cache_data(ttl=1800, show_spinner=False)
def cached_geocode(city_name: str):
    return with_retry(geocode_city_candidates, city_name)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_forecast(lat: float, lon: float, tz: str, days: int):
    return with_retry(fetch_hourly_forecast, lat, lon, tz, days=days)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_historical(lat: float, lon: float, tz: str, start: str, end: str):
    return with_retry(fetch_historical_data, lat, lon, tz, start, end)


def excel_bytes(forecast_df, hindcast_df, historical_df, meta) -> bytes:
    """Build the multi-sheet Excel export in-memory (no temp files on disk).
    Includes a QA_Flags sheet listing any UTCI validity-envelope violations,
    for provenance/reproducibility in research use.
    """
    buf = io.BytesIO()

    def _strip_tz(df):
        df = df.copy()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    qa_parts = []
    for dataset_name, df in [("Forecast_7d", forecast_df), ("Hindcast_14d", hindcast_df),
                              ("Historical_Custom", historical_df)]:
        if df is None:
            continue
        report = utci_quality_report(df)
        if report["flagged_rows"] is not None:
            part = report["flagged_rows"].copy()
            part.insert(0, "dataset", dataset_name)
            qa_parts.append(part)

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        _strip_tz(forecast_df).to_excel(writer, sheet_name="Forecast_7d")
        _strip_tz(hindcast_df).to_excel(writer, sheet_name="Hindcast_14d")
        if historical_df is not None:
            _strip_tz(historical_df).to_excel(writer, sheet_name="Historical_Custom")
        pd.DataFrame([meta]).to_excel(writer, sheet_name="Metadata", index=False)

        if qa_parts:
            qa_df = pd.concat(qa_parts)
            _strip_tz(qa_df).to_excel(writer, sheet_name="QA_Flags")
        else:
            pd.DataFrame([{"note": "No UTCI validity-envelope violations detected in this run."}]).to_excel(
                writer, sheet_name="QA_Flags", index=False
            )

    return buf.getvalue()


def thermal_chart(df: pd.DataFrame, title: str) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=df.index, y=df["T_air_urban"], name="T_air (urban)", line=dict(color="#f97316")))
    fig.add_trace(go.Scatter(x=df.index, y=df["WBGT"], name="WBGT", line=dict(color="#dc2626")))
    fig.add_trace(go.Scatter(x=df.index, y=df["UTCI"], name="UTCI", line=dict(color="#7c3aed")))
    fig.add_trace(go.Scatter(x=df.index, y=df["MRT"], name="MRT", line=dict(color="#0ea5e9", dash="dot")))
    fig.update_layout(
        title=title,
        height=420,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="\u00b0C")
    return fig


def legend_caption() -> str:
    return (
        "T_air = air temperature (2m, UHI-corrected) \u00b7 "
        "MRT = radiant temperature of the surroundings \u00b7 "
        "WBGT = heat-stress index (temp + humidity + radiation) \u00b7 "
        "UTCI = physiological 'feels-like' temperature"
    )


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["T_air_urban", "MRT", "WBGT", "UTCI"] if c in df.columns]
    return df[cols].describe().loc[["mean", "min", "max"]].round(1)


# =============================================================================
# Data-quality diagnostics: UTCI validity envelope
# =============================================================================
def utci_quality_report(df: pd.DataFrame) -> dict:
    """Flag hours where UTCI is NaN or outside its model-validated envelope,
    and identify the likely cause (temperature range vs. wind range), for
    transparency in research use.
    """
    n_total = len(df)
    utci_nan_mask = df["UTCI"].isna() if "UTCI" in df.columns else pd.Series(False, index=df.index)
    temp_out_of_range = (df["T_air_urban"] < UTCI_TDB_MIN) | (df["T_air_urban"] > UTCI_TDB_MAX)
    wind_out_of_range = ~df.get("UTCI_valid", pd.Series(True, index=df.index)).astype(bool)

    flagged = df.loc[utci_nan_mask | temp_out_of_range].copy()
    flagged["reason"] = ""
    flagged.loc[temp_out_of_range.reindex(flagged.index, fill_value=False), "reason"] += "T_air outside [-50, 50]\u00b0C; "
    flagged.loc[wind_out_of_range.reindex(flagged.index, fill_value=False), "reason"] += "wind outside [0.5, 17] m/s; "
    flagged.loc[flagged["reason"] == "", "reason"] = "UTCI is NaN (cause not attributable to temp/wind bounds)"

    return {
        "n_total": n_total,
        "n_utci_nan": int(utci_nan_mask.sum()),
        "n_temp_out_of_range": int(temp_out_of_range.sum()),
        "n_wind_out_of_range": int(wind_out_of_range.sum()),
        "max_t_air": float(df["T_air_urban"].max()) if n_total else float("nan"),
        "min_t_air": float(df["T_air_urban"].min()) if n_total else float("nan"),
        "flagged_rows": flagged[["T_air_urban", "wind_10m", "UTCI", "reason"]] if len(flagged) else None,
    }


def show_utci_quality_banner(df: pd.DataFrame, label: str) -> None:
    """Render a warning banner + detail expander if any UTCI validity issues
    are found in this dataset. Silent (no banner) if the data is clean.
    """
    report = utci_quality_report(df)
    if report["n_utci_nan"] == 0:
        return

    pct = 100 * report["n_utci_nan"] / report["n_total"] if report["n_total"] else 0
    st.warning(
        f"\u26a0\ufe0f **UTCI validity issue in {label}**: {report['n_utci_nan']} of "
        f"{report['n_total']} hours ({pct:.1f}%) have UTCI = NaN. "
        f"Peak air temperature reached {report['max_t_air']:.1f}\u00b0C. "
        "pythermalcomfort's UTCI model is only validated for air temperatures "
        "in [-50\u00b0C, 50\u00b0C] and wind speeds in [0.5, 17] m/s \u2014 values "
        "outside this envelope are set to NaN rather than extrapolated, since "
        "extrapolating a fitted regression model outside its calibration range "
        "would silently produce numbers with no validated basis. This matters "
        "for research use: gaps in a UTCI time series at the most extreme "
        "hours are a genuine model limitation, not missing data."
    )
    if report["flagged_rows"] is not None:
        with st.expander(f"Show flagged hours \u2014 {label} ({len(report['flagged_rows'])} rows)"):
            st.dataframe(report["flagged_rows"], use_container_width=True)


@st.cache_data(ttl=60 * 60 * 24 * 30, show_spinner=False)  # 30 days: climatology barely moves day to day
def fetch_climatology_baseline(lat: float, lon: float, tz: str, population: int,
                                target_month: int, target_day: int,
                                window_days: int = 10, years_back: int = 30,
                                percentile: float = 50.0) -> dict:
    """A genuine multi-year climatological baseline for the heat-load reference.

    For each of the past `years_back` years, fetches a `window_days`-wide
    calendar window centred on (target_month, target_day) from the SAME ERA5
    archive (era5_seamless) that Thermopoulos already uses for hindcasts —
    this approximates a Klimatos-style 30-year baseline using the existing
    data pipeline, without requiring the separate Klimatos codebase. Applies
    the same population-based UHI correction as the live data, so the
    baseline and "today's" reading are urban-vs-urban, not urban-vs-rural.

    Returns the chosen percentile (default: 50th, i.e. the local seasonal
    median) of pooled daily-max apparent temperature across all years, plus
    provenance (years actually retrieved, days pooled) for research use.

    Known simplification: does NOT re-apply the per-year coastal correction
    (unlike the live forecast/hindcast fetches) — each year's fetch is
    checked independently but the correction is not layered in here, to
    keep the number of API calls manageable. Flagged in the UI.
    """
    from Thermopoulos_Data_Engine import fetch_historical_data, calculate_uhi_oke
    import numpy as np

    current_year = pd.Timestamp.now(tz=tz).year
    daily_maxes = []
    years_used, years_failed = [], []
    rate_limited = False

    for offset in range(1, years_back + 1):
        year = current_year - offset
        day = min(target_day, 28) if (target_month == 2 and target_day > 28) else target_day
        try:
            center = pd.Timestamp(year=year, month=target_month, day=day)
        except ValueError:
            continue
        start = (center - pd.Timedelta(days=window_days)).strftime("%Y-%m-%d")
        end = (center + pd.Timedelta(days=window_days)).strftime("%Y-%m-%d")
        try:
            hourly, _coastal = with_retry(fetch_historical_data, lat, lon, tz, start, end)
        except RateLimitError:
            # Quota exhausted: stop hammering the API and return whatever we
            # have, flagged as partial, rather than failing the whole run.
            rate_limited = True
            break
        except Exception:
            years_failed.append(year)
            continue

        if population and population > 0:
            uhi_delta = calculate_uhi_oke(population, hourly.index)
            hourly = hourly.assign(T_air_urban=hourly["T_air_rural"] + uhi_delta)
        else:
            hourly = hourly.assign(T_air_urban=hourly["T_air_rural"])

        grouped = hourly.groupby(hourly.index.date).agg(
            t_max=("T_air_urban", "max"),
            rh_mean=("RH", "mean"),
            wind_mean=("wind_10m", "mean"),
        )
        for row in grouped.itertuples():
            daily_maxes.append(apparent_temperature(row.t_max, row.rh_mean, row.wind_mean))
        years_used.append(year)

        # Throttle: stay well clear of the 600/min burst limit, and be a
        # considerate client of a free, non-profit service.
        time.sleep(0.3)

    if not daily_maxes:
        return {
            "baseline": None, "n_years_used": 0, "n_years_failed": len(years_failed),
            "n_days_pooled": 0, "percentile": percentile, "window_days": window_days,
            "rate_limited": rate_limited,
        }

    return {
        "baseline": float(np.percentile(daily_maxes, percentile)),
        "n_years_used": len(years_used),
        "n_years_failed": len(years_failed),
        "n_days_pooled": len(daily_maxes),
        "percentile": percentile,
        "window_days": window_days,
        "rate_limited": rate_limited,
    }


def climatological_anomaly(combined: pd.DataFrame, climatology_baseline: float) -> pd.Series:
    """How unusual is each day for THIS location, in °C above the local
    climatological reference?

    This is deliberately a CONTEXT INDICATOR, not an input to the strain
    model. Testing showed that folding local climatology into the heat-load
    reference produces catastrophic false negatives: a sustained 50-52°C
    apparent-temperature week in Riyadh (absolutely lethal, beyond any
    acclimatization) scored the same 5% baseline strain as a routine local
    summer day, because relative to Riyadh's own climatology it isn't
    anomalous. Physiological limits are absolute; anomaly is context for
    interpreting them, not a substitute.
    """
    return pd.Series(
        [
            apparent_temperature(row.t_air_max, row.rh_mean, row.wind_mean) - climatology_baseline
            for row in combined.itertuples()
        ],
        index=range(len(combined)),
    )


@st.cache_data(ttl=1800, show_spinner=False)
def run_pyrox(excel_blob: bytes, group_names: tuple, forecast_days_used: int,
              hindcast_days_used: int, use_nocturnal_recovery: bool,
              climatology_baseline: float = None):
    """Run PYROX (population tier) on the combined hindcast+forecast window.

    Unlike HESTIA's CVR Monte Carlo, PYROX is a deterministic day-by-day
    strain-accumulation model (paper Sec 2.2) — no sampling, so this runs in
    well under a second even for many groups. ThermopoulosData needs a real
    file path, so the in-memory Excel is written to a throwaway temp file.

    HEAT LOAD IS ALWAYS ABSOLUTE (the original HEAT_LOAD_REFERENCE_TEMP,
    calibrated on Paris 2003). An earlier version of this app offered a
    "climate-relative" reference that replaced the fixed constant with the
    local 14-day or 30-year climatological mean. That was removed after
    testing showed two failure modes:

      1. False negatives on absolutely lethal events. A 50-52°C apparent
         week in Riyadh scored 5% (baseline, "nothing happening") because
         it is not anomalous for that location — but no amount of
         acclimatization protects against that in absolute terms.
      2. It silently invalidated the existing calibration. Paris 2003
         (the calibration case) dropped from 100% to 34% or 5% peak strain
         for the elderly group depending purely on which percentile was
         chosen as "normal" — an arbitrary UI setting swinging the answer
         between "disaster correctly predicted" and "no risk".

    Climate adaptation belongs on the CAPACITY side (recovery_threshold and
    max_acclimatization_capacity, where Callahan et al. 2025 adaptation
    limits already apply in PYROX v2.2), not on the load side. If supplied,
    climatology_baseline is used only to report a per-day anomaly alongside
    the strain results, as interpretive context.
    """
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(excel_blob)
        tmp_path = tmp.name

    data = ThermopoulosData(tmp_path)
    combined = data.get_combined_window(
        hindcast_days=hindcast_days_used, forecast_days=forecast_days_used
    )
    forecast_start_idx = data.forecast_start_index(combined)
    dates = combined["date"].tolist()

    # Always absolute: physiology does not renormalise to local custom.
    heat_loads = combined["baseline_heat_load"].tolist()

    anomaly = None
    if climatology_baseline is not None:
        anomaly = climatological_anomaly(combined, climatology_baseline).tolist()

    sleep_quality_series = None
    if use_nocturnal_recovery:
        sleep_quality_series = data.sleep_quality_series(combined)

    groups = {}
    for name in group_names:
        model = PyroxModel(TARGET_GROUPS[name])
        groups[name] = model.simulate(heat_loads, sleep_quality_series=sleep_quality_series)

    return {
        "dates": dates,
        "forecast_start_idx": forecast_start_idx,
        "groups": groups,
        "combined": combined,
        "heat_loads": heat_loads,
        "reference_used": HEAT_LOAD_REFERENCE_TEMP,
        "climatology_baseline": climatology_baseline,
        "anomaly": anomaly,
    }


def pyrox_chart(pyrox_result: dict) -> go.Figure:
    dates = pyrox_result["dates"]
    fig = go.Figure()
    for name, res in pyrox_result["groups"].items():
        pct = 100 * res["cumulative_strain"][1:] / res["critical_strain"]
        fig.add_trace(go.Scatter(
            x=dates, y=pct, mode="lines+markers",
            name=TARGET_GROUPS[name].display_name,
        ))

    for level, label, color in [(50, "caution (50%)", "#f59e0b"),
                                  (75, "danger (75%)", "#f97316"),
                                  (90, "emergency (90%)", "#dc2626")]:
        fig.add_hline(y=level, line_dash="dot", line_color=color,
                      annotation_text=label, annotation_position="right")

    fstart = pyrox_result["forecast_start_idx"]
    if 0 < fstart < len(dates):
        fig.add_vline(x=dates[fstart], line_dash="dash", line_color="gray",
                      annotation_text="forecast start", annotation_position="top")

    fig.update_layout(
        title="PYROX \u2014 cumulative strain per group (% of critical threshold)",
        yaxis_title="% of critical_strain",
        height=440,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )
    return fig


def pyrox_summary_table(pyrox_result: dict) -> pd.DataFrame:
    dates = pyrox_result["dates"]
    rows = []
    for name, res in pyrox_result["groups"].items():
        def _date_or_dash(day_idx):
            return dates[day_idx] if day_idx is not None and day_idx < len(dates) else "\u2014"

        rows.append({
            "Group": TARGET_GROUPS[name].display_name,
            "Peak strain (%)": round(100 * res["peak_strain"] / res["critical_strain"], 1),
            "Caution day (50%)": _date_or_dash(res["caution_day"]),
            "Danger day (75%)": _date_or_dash(res["danger_day"]),
            "Emergency day (90%)": _date_or_dash(res["emergency_day"]),
        })
    return pd.DataFrame(rows)


# =============================================================================
# Sidebar — inputs
# =============================================================================
with st.sidebar:
    st.header("Location & settings")

    city_name = st.text_input("City", placeholder="e.g. Falmouth, MA")

    terrain_options = {k: v[0] for k, v in ROUGHNESS_Z0_TERRAIN.items()}
    terrain_key = st.selectbox(
        "Terrain type (10m \u2192 1.5m wind profile)",
        options=list(terrain_options.keys()),
        format_func=lambda k: terrain_options[k],
        index=2,
    )
    roughness_z0 = ROUGHNESS_Z0_TERRAIN[terrain_key][1]

    forecast_days = st.slider("Forecast period (days)", min_value=1, max_value=16, value=7)

    st.divider()
    use_custom = st.checkbox("Add a custom historical period")
    custom_start, custom_end = None, None
    if use_custom:
        default_start = date.today() - timedelta(days=30)
        default_end = date.today() - timedelta(days=23)
        custom_start = st.date_input("Start date", value=default_start, max_value=date.today())
        custom_end = st.date_input("End date", value=default_end, max_value=date.today())

    st.divider()
    run_button = st.button("\U0001F680 Run analysis", type="primary", use_container_width=True)

# =============================================================================
# Session state
# =============================================================================
if "results" not in st.session_state:
    st.session_state.results = None
if "candidates" not in st.session_state:
    st.session_state.candidates = None

# =============================================================================
# Geocoding step (handles multiple matches)
# =============================================================================
if run_button:
    if not city_name.strip():
        st.warning("Please enter a city name first.")
    else:
        with st.spinner(f"Looking up location for '{city_name}'..."):
            try:
                candidates = cached_geocode(city_name.strip())
                st.session_state.candidates = candidates
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
        chosen_idx = st.selectbox(
            "Multiple locations found — pick one:",
            options=range(len(candidates)),
            format_func=lambda i: labels[i],
        )
        city = candidates[chosen_idx]
    else:
        city = candidates[0]

    lat, lon, tz = city["latitude"], city["longitude"], city["timezone"]

    st.success(
        f"**{city['name']}, {city.get('country', 'Unknown')}** \u2014 "
        f"{lat:.4f}\u00b0, {lon:.4f}\u00b0 \u00b7 timezone {tz} \u00b7 "
        f"population {city.get('population', 'unknown')}"
    )

    with st.spinner("Fetching weather data and computing thermal indices..."):
        try:
            forecast_df, forecast_coastal = cached_forecast(lat, lon, tz, forecast_days)
            forecast_df = validate_weather_data(forecast_df, "forecast")

            forecast_start = forecast_df.index[0].date()
            hindcast_end = forecast_start - timedelta(days=1)
            hindcast_start = hindcast_end - timedelta(days=13)
            hindcast_df, hindcast_coastal = cached_historical(
                lat, lon, tz,
                hindcast_start.strftime("%Y-%m-%d"),
                hindcast_end.strftime("%Y-%m-%d"),
            )
            hindcast_df = validate_weather_data(hindcast_df, "hindcast")

            historical_df, historical_coastal = None, False
            if use_custom and custom_start and custom_end and custom_start <= custom_end:
                historical_df, historical_coastal = cached_historical(
                    lat, lon, tz,
                    custom_start.strftime("%Y-%m-%d"),
                    custom_end.strftime("%Y-%m-%d"),
                )
                historical_df = validate_weather_data(historical_df, "custom historical")

            forecast_df = process_weather_data(
                forecast_df, city, lat, lon, tz,
                coastal_active=forecast_coastal, roughness_z0=roughness_z0,
            )
            hindcast_df = process_weather_data(
                hindcast_df, city, lat, lon, tz,
                coastal_active=hindcast_coastal, roughness_z0=roughness_z0,
            )
            if historical_df is not None:
                historical_df = process_weather_data(
                    historical_df, city, lat, lon, tz,
                    coastal_active=historical_coastal, roughness_z0=roughness_z0,
                )

            meta = {
                "city": city["name"],
                "country": city.get("country", "Unknown"),
                "latitude": lat,
                "longitude": lon,
                "timezone": tz,
                "population": city.get("population", 0),
                "roughness_z0": roughness_z0,
                "terrain_type": terrain_options[terrain_key],
                "model_version": "Thermopoulos v3.1",
            }

            st.session_state.results = {
                "forecast": forecast_df,
                "hindcast": hindcast_df,
                "historical": historical_df,
                "meta": meta,
                "coastal": {
                    "forecast": forecast_coastal,
                    "hindcast": hindcast_coastal,
                    "historical": historical_coastal,
                },
            }
        except RateLimitError:
            st.error(
                "\u23f3 **Open-Meteo rate limit reached (HTTP 429).**\n\n"
                "The free tier allows 10,000 calls/day, 5,000/hour and "
                "600/minute, and requests spanning more than two weeks count "
                "as more than one call. The 30-year climatology option is by "
                "far the most expensive feature \u2014 it makes one request per "
                "year of history.\n\n"
                "What to do:\n"
                "- Wait a few minutes and try again (the per-minute limit "
                "resets quickly; the hourly one takes longer)\n"
                "- Leave the climatological context option switched off, or "
                "reduce the years of history, while you work\n"
                "- Results are cached, so re-running the same location and "
                "settings will not spend more quota"
            )
            st.session_state.results = None
        except Exception as e:
            st.error(f"Processing failed: {e}")
            st.session_state.results = None

# =============================================================================
# Results display
# =============================================================================
if st.session_state.results:
    r = st.session_state.results
    forecast_df, hindcast_df, historical_df = r["forecast"], r["hindcast"], r["historical"]
    meta, coastal = r["meta"], r["coastal"]

    tab_names = ["\U0001F4C5 Forecast", "\U0001F55B Hindcast (14d)"]
    if historical_df is not None:
        tab_names.append("\U0001F4C6 Historical period")
    tabs = st.tabs(tab_names)

    with tabs[0]:
        if coastal["forecast"]:
            st.info("Coastal correction applied (grid cell falls outside this model's resolution threshold).")
        st.plotly_chart(thermal_chart(forecast_df, f"{meta['city']} \u2014 Forecast"), use_container_width=True)
        st.caption(legend_caption())
        st.dataframe(summary_table(forecast_df), use_container_width=True)
        show_utci_quality_banner(forecast_df, "Forecast")

    with tabs[1]:
        if coastal["hindcast"]:
            st.info("Coastal correction applied (grid cell falls outside this model's resolution threshold).")
        st.plotly_chart(thermal_chart(hindcast_df, f"{meta['city']} \u2014 Hindcast (14 days)"), use_container_width=True)
        st.caption(legend_caption())
        st.dataframe(summary_table(hindcast_df), use_container_width=True)
        show_utci_quality_banner(hindcast_df, "Hindcast")

    if historical_df is not None:
        with tabs[2]:
            if coastal["historical"]:
                st.info("Coastal correction applied (grid cell falls outside this model's resolution threshold).")
            st.plotly_chart(
                thermal_chart(historical_df, f"{meta['city']} \u2014 Historical period"),
                use_container_width=True,
            )
            st.caption(legend_caption())
            st.dataframe(summary_table(historical_df), use_container_width=True)
            show_utci_quality_banner(historical_df, "Historical period")

    st.divider()
    excel_data = excel_bytes(forecast_df, hindcast_df, historical_df, meta)

    # -------------------------------------------------------------------
    # PYROX — population-tier heat-strain risk (fast, deterministic;
    # NOT the HESTIA CVR Monte Carlo, so no multi-minute wait here)
    # -------------------------------------------------------------------
    st.header("\U0001F9EC PYROX \u2014 population heat-strain risk")
    st.caption(
        "Cumulative strain per population group over the hindcast+forecast "
        "period, based on daily heat load (paper Sec 2.2). Deterministic "
        "model, no Monte Carlo \u2014 runs in milliseconds."
    )

    all_group_names = sorted(TARGET_GROUPS, key=lambda k: TARGET_GROUPS[k].display_name)
    default_selection = [g for g in PAPER_PROTOTYPES if g in TARGET_GROUPS]

    col_a, col_b = st.columns([2, 1])
    with col_a:
        selected_groups = st.multiselect(
            "Population groups",
            options=all_group_names,
            default=default_selection,
            format_func=lambda k: TARGET_GROUPS[k].display_name,
        )
    with col_b:
        use_nocturnal = st.checkbox(
            "Include nocturnal recovery",
            value=False,
            help="Warm nights (low t_air_min) reduce recovery during sleep.",
        )

    show_climatology = st.checkbox(
        "Add local climatological context (30-year ERA5 anomaly)",
        value=False,
        help=(
            "Reports how unusual each day is for THIS location, compared with "
            "the same calendar window over the past 30 years. This is shown "
            "alongside the strain results as interpretive context \u2014 it does "
            "NOT change the heat load or the strain computation, which stay "
            "absolute. Fetching 30 years of ERA5 data can take up to a minute "
            "the first time (cached for 30 days afterward)."
        ),
    )

    climatology_baseline = None
    climatology = None
    if show_climatology:
        with st.expander("Climatology settings"):
            window_days = st.slider("Calendar window (\u00b1 days around the forecast date)", 5, 20, 7)
            years_back = st.slider(
                "Years of history", 5, 30, 15,
                help="Each year is a separate API request. Open-Meteo's free "
                     "tier allows 10,000 calls/day and 5,000/hour, and windows "
                     "longer than two weeks count as more than one call. Lower "
                     "values are kinder to the quota; 15 years already gives a "
                     "reasonably stable percentile.",
            )
            percentile = st.slider(
                "Percentile of pooled daily-max apparent temperature", 10, 95, 50,
                help="50 = local seasonal median ('a typical day here'). "
                     "Only affects the anomaly reported as context, not the "
                     "strain computation.",
            )
            est_calls = years_back * (1.5 if window_days > 7 else 1.0)
            st.caption(
                f"Estimated API cost: ~{est_calls:.0f} weighted calls "
                f"({years_back} requests). Cached for 30 days per "
                "location/date/settings combination."
            )
        target_date = forecast_df.index[0]
        with st.spinner(
            f"Fetching {years_back} years of ERA5 historical data for the "
            f"{2 * window_days}-day calendar window around "
            f"{target_date.strftime('%d %b')}..."
        ):
            climatology = fetch_climatology_baseline(
                lat, lon, tz, meta["population"],
                target_date.month, target_date.day,
                window_days, years_back, percentile,
            )
        if climatology["baseline"] is None:
            if climatology.get("rate_limited"):
                st.error(
                    "\u23f3 Open-Meteo rate limit reached while fetching "
                    "climatology (HTTP 429). Continuing without climatological "
                    "context \u2014 the strain results below are unaffected, since "
                    "they don't depend on it. Try again in a few minutes, or "
                    "reduce the years of history."
                )
            else:
                st.error(
                    "Could not retrieve any historical years for this location "
                    "(all requests failed). Continuing without climatological context."
                )
        else:
            climatology_baseline = climatology["baseline"]
            fail_note = (
                f", {climatology['n_years_failed']} year(s) failed to fetch"
                if climatology["n_years_failed"] else ""
            )
            if climatology.get("rate_limited"):
                st.warning(
                    f"\u23f3 Rate limit reached partway through: the baseline "
                    f"below is based on {climatology['n_years_used']} of the "
                    f"{years_back} requested years. Still usable, but less "
                    "stable than a full sample \u2014 re-run in a few minutes "
                    "for the complete set."
                )
            st.info(
                f"\U0001F30D **Local climatological reference: {climatology_baseline:.1f}\u00b0C** "
                f"apparent temperature \u2014 the {percentile:.0f}th percentile of "
                f"{climatology['n_days_pooled']} pooled days from "
                f"{climatology['n_years_used']} years{fail_note}, within \u00b1"
                f"{window_days} days of {target_date.strftime('%d %b')}. "
                "Uses the same ERA5 archive and UHI correction as the live data. "
                "Does not re-apply the per-year coastal correction (a documented "
                "simplification)."
            )

    if not selected_groups:
        st.warning("Select at least one population group.")
    else:
        hindcast_days_used = min(14, len(hindcast_df.index.normalize().unique()))
        forecast_days_used = min(7, forecast_days)  # PYROX caps forecast skill at ~1 week
        pyrox_result = run_pyrox(
            excel_data, tuple(selected_groups),
            forecast_days_used, hindcast_days_used, use_nocturnal,
            climatology_baseline,
        )

        st.caption(
            f"Heat load is computed against the absolute reference of "
            f"{HEAT_LOAD_REFERENCE_TEMP:.0f}\u00b0C apparent temperature "
            "(Paris 2003 calibration). Physiological limits are absolute, so "
            "local climatology is reported as context below rather than "
            "folded into the load \u2014 see the README for why."
        )

        st.plotly_chart(pyrox_chart(pyrox_result), use_container_width=True)
        st.dataframe(pyrox_summary_table(pyrox_result), use_container_width=True)
        st.caption(
            "Caution/danger/emergency = the day cumulative strain first "
            "reaches 50% / 75% / 90% of that group's critical threshold. "
            "'\u2014' means the threshold was not reached within this period."
        )

        # ---------------------------------------------------------------
        # Climatological context (separate from, not folded into, the model)
        # ---------------------------------------------------------------
        if pyrox_result["anomaly"] is not None:
            st.subheader("\U0001F30D Local climatological context")
            st.caption(
                "How unusual each day is for this location, relative to the "
                "30-year baseline above. Shown as context for interpreting the "
                "strain results \u2014 a locally unremarkable day can still be "
                "physiologically dangerous in absolute terms, and a locally "
                "extreme anomaly in a cool climate can hit an unacclimatized "
                "population hard."
            )
            anomaly_df = pd.DataFrame({
                "date": pyrox_result["dates"],
                "anomaly (\u00b0C vs local normal)": [round(a, 1) for a in pyrox_result["anomaly"]],
                "absolute heat load": [round(h, 2) for h in pyrox_result["heat_loads"]],
            })
            fig_anom = go.Figure()
            fig_anom.add_trace(go.Bar(
                x=anomaly_df["date"],
                y=anomaly_df["anomaly (\u00b0C vs local normal)"],
                name="anomaly vs local normal",
                marker_color=[
                    "#dc2626" if a > 0 else "#0ea5e9"
                    for a in pyrox_result["anomaly"]
                ],
            ))
            fig_anom.add_hline(y=0, line_color="gray")
            fig_anom.update_layout(
                title="Departure from local 30-year normal",
                yaxis_title="\u00b0C above/below local normal",
                height=300,
                margin=dict(l=10, r=10, t=40, b=10),
                hovermode="x unified",
            )
            st.plotly_chart(fig_anom, use_container_width=True)
            st.dataframe(anomaly_df, use_container_width=True)

    st.divider()
    st.download_button(
        "\U0001F4E5 Download full dataset (Excel, multiple sheets)",
        data=excel_data,
        file_name=f"PYROX_{meta['city'].replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.caption(
        "Includes a **QA_Flags** sheet listing any UTCI validity-envelope "
        "violations (temperature/wind outside the model's calibrated range), "
        "for provenance in research use."
    )
else:
    st.info("Enter a city on the left and click **Run analysis** to get started.")
