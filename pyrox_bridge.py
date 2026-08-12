# -*- coding: utf-8 -*-
"""
Shared PYROX execution bridge
==============================
Both Streamlit front-ends (the general population app and the athlete app)
run the PYROX population tier through THIS module, rather than each
keeping its own copy of the Excel round-trip and simulation loop. Two
copies of that logic would drift apart silently -- one app would get a fix
and the other would not, and nothing would flag it.

Also holds the pace -> metabolic rate conversion used by the athlete app.
"""

from __future__ import annotations

__BUILD__ = "2026-08-11h"

import io
import tempfile

import pandas as pd
import streamlit as st

from thermopoulos_loader import (
    ThermopoulosData,
    apparent_temperature,
    HEAT_LOAD_REFERENCE_TEMP,
    HEAT_LOAD_PER_DEGREE,
)
from pyrox_model import PyroxModel
from pyrox_revised_calibration import (
    apply_revised_calibration,
    met_adjusted_apparent_temperature,
    MET_REFERENCE,
)
from pyrox_groups import TARGET_GROUPS as _ORIGINAL_GROUPS

TARGET_GROUPS = apply_revised_calibration(_ORIGINAL_GROUPS)


# =============================================================================
# Pace -> metabolic rate
# =============================================================================
def met_from_pace(pace_min_per_km: float, grade: float = 0.0,
                  mode: str = "run") -> float:
    """Metabolic rate (MET) for running or walking at a given pace, via the
    ACSM metabolic equations:

        running: VO2 = 0.2 * S + 0.9 * S * G + 3.5      (S in m/min)
        walking: VO2 = 0.1 * S + 1.8 * S * G + 3.5
        MET = VO2 / 3.5

    This is a genuine improvement over a fixed MET per category: a beginner
    at 7:30 min/km and an elite at 3:00 min/km differ enormously in
    metabolic heat production, and that difference drives the heat load.

    CAUTION, WHICH DIFFERS SHARPLY BY MODE. The heat-load bridge multiplies
    MET by K_PER_MET (2.29 degC/MET), derived from ISO 7243 reference
    values tabulated over roughly 1.2-8 MET.
      - WALKING produces about 2.5-5 MET, comfortably INSIDE that range, so
        the coefficient is being used as intended.
      - RUNNING produces 9-19 MET, well OUTSIDE it, so running loads are an
        extrapolation and are ordinally useful rather than calibrated.
    The app states this distinction rather than treating both alike.
    """
    if pace_min_per_km <= 0:
        return MET_REFERENCE
    speed_m_per_min = 1000.0 / pace_min_per_km
    if mode == "walk":
        vo2 = 0.1 * speed_m_per_min + 1.8 * speed_m_per_min * grade + 3.5
    else:
        vo2 = 0.2 * speed_m_per_min + 0.9 * speed_m_per_min * grade + 3.5
    return max(MET_REFERENCE, vo2 / 3.5)


#: Speed ranges (km/h) over which each ACSM equation is considered valid.
#: Walking: 3.0-6.0 km/h (50-100 m/min). Running: from ~8 km/h upward.
#: Between 6 and 8 km/h neither fits well -- that is race-walking or a very
#: slow jog, where the equations diverge and neither was fitted.
ACSM_VALID_SPEED_KMH = {"walk": (3.0, 6.0), "run": (8.0, 25.0)}


def acsm_range_warning(pace_min_per_km: float, mode: str) -> str | None:
    """Return a human-readable note if the pace falls outside the ACSM
    equation's fitted range, or None if it is fine."""
    if pace_min_per_km <= 0:
        return None
    speed = 60.0 / pace_min_per_km
    lo, hi = ACSM_VALID_SPEED_KMH.get(mode, (0.0, 1e9))
    if speed < lo:
        return (f"{speed:.1f} km/h is below the ACSM {mode}ing equation's "
                f"fitted range ({lo:.0f}-{hi:.0f} km/h); the metabolic rate "
                "is an extrapolation.")
    if speed > hi:
        return (f"{speed:.1f} km/h is above the ACSM {mode}ing equation's "
                f"fitted range ({lo:.0f}-{hi:.0f} km/h); the metabolic rate "
                "is an extrapolation.")
    return None


def pace_from_speed(speed_kmh: float) -> float:
    """Convenience: km/h -> min/km."""
    return 60.0 / speed_kmh if speed_kmh > 0 else 0.0


#: The occupational shift length the MET correction's framing assumes.
#: pyrox_revised_calibration weights MET to the shift rather than the
#: 24-hour day, on the reasoning that the shift coincides with the daily
#: thermal peak. That holds for an 8-hour working day.
REFERENCE_SHIFT_HOURS = 8.0


def daily_effective_met(session_met: float, session_hours: float,
                        reference_shift_hours: float = REFERENCE_SHIFT_HOURS) -> float:
    """Scale a session metabolic rate to the daily-load equivalent PYROX
    expects.

    WHY THIS IS NECESSARY. PYROX resolves days, and its MET term is
    shift-weighted: the assumption is that the exertion window is a
    substantial fraction of the day and coincides with the thermal peak.
    An 8-hour construction shift fits that. A one-hour run does not.
    Feeding a race MET in unweighted implies running at race pace all day:
    at 18.6 MET the correction alone adds ~40 degC of apparent temperature,
    which saturates every athlete level at 100% strain and destroys the
    comparison the app exists to make.

    Weighting the excess above resting by the exertion window relative to a
    reference shift restores a meaningful spread, and has a side effect
    that is physiologically right rather than accidental: a slower runner
    is exposed for longer, so a beginner taking two hours can accumulate a
    daily load comparable to an elite runner finishing in under one.

    THIS IS AN EXTENSION, NOT PART OF THE PUBLISHED CALIBRATION. It is a
    linear duration weighting, not a validated dose-response relationship;
    real thermal strain does not accumulate strictly linearly with exposure
    time. Acute within-session risk is a different question entirely and
    belongs to HESTIA's individual tier, not here -- this module only makes
    PYROX's MULTI-DAY load comparison usable for athletes.
    """
    if session_hours <= 0:
        return MET_REFERENCE
    excess = max(0.0, session_met - MET_REFERENCE)
    return MET_REFERENCE + excess * (session_hours / reference_shift_hours)


# =============================================================================
# Excel round-trip (ThermopoulosData needs a real file path)
# =============================================================================
def excel_bytes(forecast_df, hindcast_df, historical_df, meta) -> bytes:
    """Build the multi-sheet Excel export in-memory."""
    buf = io.BytesIO()

    def _strip_tz(df):
        df = df.copy()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        _strip_tz(forecast_df).to_excel(writer, sheet_name="Forecast_7d")
        _strip_tz(hindcast_df).to_excel(writer, sheet_name="Hindcast_14d")
        if historical_df is not None:
            _strip_tz(historical_df).to_excel(writer, sheet_name="Historical_Custom")
        pd.DataFrame([meta]).to_excel(writer, sheet_name="Metadata", index=False)

    return buf.getvalue()


@st.cache_data(ttl=60 * 60 * 2, show_spinner=False)
def run_pyrox(excel_blob: bytes, group_names: tuple, forecast_days_used: int,
              hindcast_days_used: int, use_nocturnal_recovery: bool,
              met_by_group: tuple = None):
    """Run PYROX (population tier) on the combined hindcast+forecast window.

    Heat load is always absolute (HEAT_LOAD_REFERENCE_TEMP), never
    renormalised to local climatology -- see the general app's README for
    the Riyadh false-negative case that settled that question.

    Metabolic load, by contrast, does belong on the load side: metabolic
    and environmental heat are shed through the same actuator, so they are
    physically additive. Each group therefore gets its own heat-load series
    from its MET.
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

    heat_loads = combined["baseline_heat_load"].tolist()
    apparent = [
        apparent_temperature(row.t_air_max, row.rh_mean, row.wind_mean)
        for row in combined.itertuples()
    ]

    # Defensive NaN guard. Not tied to a confirmed root cause -- isolated
    # testing could not reproduce NaN reaching this point through the
    # normal path -- but if a weather fetch ever leaves a gap here,
    # Python's max(0.0, nan) == 0.0 would silently turn a missing value
    # into a false "perfectly calm day" rather than surfacing it. Linear
    # interpolation (falling back to a neighbour, then to the series mean
    # if a whole run is somehow NaN) keeps a bad day from silently
    # vanishing into a 0-load reading.
    def _fill_nan(seq):
        s = pd.Series(seq, dtype=float)
        if s.isna().any():
            s = s.interpolate(limit_direction="both")
            if s.isna().any():  # entire series was NaN
                s = s.fillna(HEAT_LOAD_REFERENCE_TEMP)
        return s.tolist()

    heat_loads = _fill_nan(heat_loads)
    apparent = _fill_nan(apparent)

    def loads_for_met(met: float):
        if met is None or abs(met - MET_REFERENCE) < 1e-9:
            return heat_loads
        return [
            max(0.0,
                (met_adjusted_apparent_temperature(t, met) - HEAT_LOAD_REFERENCE_TEMP)
                * HEAT_LOAD_PER_DEGREE)
            for t in apparent
        ]

    sleep_quality_series = None
    if use_nocturnal_recovery:
        sleep_quality_series = data.sleep_quality_series(combined)

    met_lookup = dict(met_by_group) if met_by_group else {}

    groups, group_loads, group_mets = {}, {}, {}
    for name in group_names:
        met = met_lookup.get(name, MET_REFERENCE)
        loads = loads_for_met(met)
        model = PyroxModel(TARGET_GROUPS[name])
        groups[name] = model.simulate(loads, sleep_quality_series=sleep_quality_series)
        group_loads[name] = loads
        group_mets[name] = met

    return {
        "dates": dates,
        "forecast_start_idx": forecast_start_idx,
        "groups": groups,
        "combined": combined,
        "heat_loads": heat_loads,
        "group_loads": group_loads,
        "group_mets": group_mets,
        "apparent": apparent,
        "reference_used": HEAT_LOAD_REFERENCE_TEMP,
    }
