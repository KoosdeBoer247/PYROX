# -*- coding: utf-8 -*-
"""
HESTIA individual-tier bridge — live-interactive, without blocking the app
=============================================================================
Wraps hestia_model.run_monte_carlo_adult for use inside a Streamlit session
that must stay responsive. Three real bottlenecks were found and fixed (see
hestia_model.py's own patched functions for the detail); this module adds a
fourth layer: a two-tier N so "live and always responds quickly" and
"full-precision Monte Carlo" don't have to be the same request.

PROFILED (network stubbed, 60-minute event, this sandbox's hardware):
    ~133 ms / draw of pure JOS-3 compute, single process.
    n=100  -> ~13 s        n=1000 -> ~130 s (2.2 min)
    n=200  -> ~27 s        n=5000 -> ~660 s (11 min)
Longer events cost proportionally more per draw (JOS-3 steps through every
interpolated timestep). These are lower bounds from one machine; actual
Streamlit Cloud wall-clock is unverified and likely higher, since
multiprocessing.cpu_count() on a shared container often overstates the
cores actually available.

DESIGN: a "quick estimate" (small n, default) runs live inline, capped in
size to keep the wait in the range of seconds rather than minutes, cached
by scenario so repeat views are instant. A "full precision" run is never
triggered automatically -- it requires an explicit button press, shows an
honest time estimate first, and updates a progress bar as results arrive
rather than blocking silently.

TWO FIXES CARRIED BY THIS BRIDGE (not by hestia_model.py's callers):
  1. get_timezone() is monkey-patched to the ALREADY-KNOWN IANA timezone
     from the app's own geocoding step, rather than re-deriving it from
     lat/lon via TimezoneFinder -- more reliable, and sidesteps needing a
     package with no Python 3.12 wheel.
  2. get_air_quality() is monkey-patched to a value fetched ONCE per
     scenario (not per draw, not per worker) -- see hestia_model.py's own
     docstring on this function for why the uncached version was a real
     bottleneck.
"""

from __future__ import annotations

__BUILD__ = "2026-08-11h"

import multiprocessing
import time

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

import hestia_model as h

# =============================================================================
# Sizing
# =============================================================================
#: Default "quick estimate" sample size. ~13s single-process per the
#: profiling above; real deployments should re-measure once on their own
#: hardware (see time_estimate_seconds) rather than trust this blindly.
QUICK_N = 100

#: Ceiling on worker-pool size. Two considerations cap this, not just CPU:
#: 1. multiprocessing.cpu_count() on a shared container can overstate real
#:    availability -- more workers than real cores adds overhead, not speed.
#: 2. MEMORY. Profiled: importing this app's own baseline (streamlit,
#:    plotly, pandas, numpy, pythermalcomfort, rasterio) plus hestia_model
#:    (which pulls in matplotlib/seaborn/scipy) costs ~384MB in a single
#:    process before any simulation runs. fork-based multiprocessing.Pool
#:    (Linux default) shares that baseline across workers via copy-on-write,
#:    but each worker accumulates its own private memory as it actually
#:    simulates (result arrays, mutable state) -- so total memory grows with
#:    worker count during a run, not just at import. Streamlit Community
#:    Cloud's free tier has limited RAM (commonly reported around 1GB,
#:    unverified for this specific deployment). Capped conservatively at 2
#:    rather than a CPU-driven higher number, trading some wall-clock speed
#:    for a materially lower out-of-memory risk. Raise this only after
#:    confirming on the actual deployed container that memory headroom
#:    allows it -- an OOM kill on Streamlit Cloud looks identical to the
#:    "Oh no" crash screen documented in HANDLEIDING.md, with no traceback,
#:    so it is easy to misdiagnose as a code bug rather than a resource limit.
MAX_WORKERS = 2


def _capped_workers() -> int:
    return max(1, min(multiprocessing.cpu_count(), MAX_WORKERS))


def time_estimate_seconds(n_simulations: int, event_minutes: float,
                          per_draw_per_minute_s: float = 133.0 / 60 / 1000) -> float:
    """Rough wall-clock estimate, single-process-equivalent, scaled by
    event duration (JOS-3 cost scales with the number of timesteps).
    Shown to the user BEFORE they commit to a full-precision run -- an
    estimate they can weigh, not a silent multi-minute block."""
    workers = _capped_workers()
    per_draw = per_draw_per_minute_s * max(event_minutes, 1.0)
    return (n_simulations * per_draw) / workers


# =============================================================================
# Weather bridge: build HESTIA's interp_data from the app's own forecast_df
# =============================================================================
def build_interp_data(weather_df: pd.DataFrame, start: pd.Timestamp,
                      finish: pd.Timestamp, interval_minutes: int = 10) -> list:
    """Resample the app's existing hourly weather (with T_globe/MRT already
    computed by Thermopoulos_Data_Engine) onto HESTIA's flat per-timestep
    format, at native minute resolution. Reuses the already-validated
    radiative pipeline rather than reconstructing it a second way."""
    times = pd.date_range(start=start, end=finish, freq=f"{interval_minutes}min")
    if len(times) < 2:
        times = pd.date_range(start=start, periods=2, freq=f"{interval_minutes}min")
    idx_num = weather_df.index.astype("int64").to_numpy()
    q_num = times.astype("int64").to_numpy()

    def interp(col, default=0.0):
        if col not in weather_df.columns:
            return np.full(len(times), default)
        return np.interp(q_num, idx_num, weather_df[col].to_numpy())

    temp = interp("T_air_urban")
    wind = interp("wind_10m", 2.0)
    rh = interp("RH", 50.0)
    clouds = interp("cloud_cover", 30.0)
    pressure = interp("pressure", 1013.0)
    ghi = interp("solar_radiation", 0.0)
    solar_elevation = interp("solar_elevation", 0.0)
    globe_temp = interp("T_globe", temp.mean())
    mrt = interp("MRT", temp.mean())

    return [
        {"time": t, "temp": float(temp[i]), "wind": float(wind[i]),
         "rh": float(rh[i]), "clouds": float(clouds[i]), "pressure": float(pressure[i]),
         "ghi": float(ghi[i]), "solar_elevation": float(solar_elevation[i]),
         "globe_temp": float(globe_temp[i]), "mrt": float(mrt[i])}
        for i, t in enumerate(times)
    ]


# =============================================================================
# Monkey-patches: remove per-draw/per-worker network calls entirely when the
# answer is already known from the app's own context.
# =============================================================================
def _patch_timezone(tz_name: str):
    tz_obj = pytz.timezone(tz_name)
    h.get_timezone = lambda lat, lon: tz_obj


def _fetch_aqi_once(lat: float, lon: float) -> int:
    """Single, direct AQI fetch for the scenario -- called once, not per
    draw. Falls back to 1 (best-case) on any failure, matching
    hestia_model's own fallback behaviour."""
    try:
        r = requests.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={"latitude": lat, "longitude": lon, "current": "us_aqi", "timezone": "UTC"},
            timeout=10,
        )
        r.raise_for_status()
        us_aqi = r.json()["current"]["us_aqi"]
        return h._map_us_aqi_to_owm_scale(us_aqi)
    except Exception:
        return 1


def _patch_air_quality(aqi_value: int):
    h.get_air_quality = lambda lat, lon: aqi_value


# =============================================================================
# The run itself
# =============================================================================
def falmouth_ehs_per_1000(mean_t_air_c: float) -> float:
    """Epidemiologically-anchored EHS rate estimate, from real incident
    data -- NOT from HESTIA's own physiological simulation.

    Source: DeMartini JK, Casa DJ, Belval LN, et al. "Environmental
    Conditions and the Occurrence of Exertional Heat Illnesses and
    Exertional Heat Stroke at the Falmouth Road Race." J Athl Train.
    2014;49(4):478-485. 18 years of medical-tent records (12 years with
    finisher counts) at the Falmouth Road Race (7 miles / 11.3 km,
    ~10,000 runners, elite to novice). EHS defined as rectal temp
    >=40degC with CNS dysfunction -- the same clinical definition
    HESTIA's own conjunctive criterion targets.

    Regression (their Fig. 2, fit on n=12 individual race-years):
        EHS per 1000 finishers = 0.004 * exp(0.250 * Tamb_degC)
        R^2 = 0.653, P = .001
    Verified here against their Table 1 (12 individual year values):
    mean absolute deviation ~0.64 per 1000 across the fitted range
    (21.3-27.7 degC) -- a real, moderate-strength epidemiological fit,
    not an exact match to any single year.

    WHY THIS EXISTS: extensive testing this session (see project history)
    found HESTIA's own raw physiological "true EHS criterion" simulation
    over-predicts Falmouth's actual, published EHS incidence by roughly
    20-53x across a comparable temperature range, while the RELATIVE
    temperature-sensitivity (how fast risk grows per degree) was
    reasonably close between the two (suggesting a scale/calibration
    issue more than a broken shape). Pending a full re-derivation of
    HESTIA's own internal calibration (a larger undertaking -- see
    project notes on production-scale intercept re-estimation), this
    formula is used as the PRIMARY, real-data-anchored EHS estimate
    shown to users. HESTIA's raw simulation output remains available
    but is clearly labelled as uncalibrated.

    LIMITATIONS, stated plainly:
      - Fitted on ONE specific race: a 7-mile (~11 km) point-to-point
        event with a broad recreational-to-elite field. Applying it to
        a very different distance, duration, or participant population
        is itself an approximation, not a validated transfer.
      - R^2 = 0.653 means the temperature-fitted curve explains about
        two-thirds of the year-to-year variance in the real data --
        real years scatter meaningfully above and below this line.
      - Uses race-window MEAN ambient temperature, matching the
        original paper's own methodology (their Tamb is a race-window
        average, not a peak).
    """
    return 0.004 * float(np.exp(0.250 * mean_t_air_c))


#: Logistic dose-response parameters, jointly fit against the Falmouth
#: regression across 5 temperature scenarios (22-34C) using REAL individual
#: dose values from n=120 simulated participants per scenario.
#:
#: [refit, 2026-08-10] Re-fit after the clo_value correction (0.5 -> 0.2,
#: see run_quick_estimate() docstring). The ORIGINAL fit (a=-6.933,
#: b=0.1981) was calibrated against simulations that ran systematically
#: too hot; this refit uses the corrected clo=0.2 simulations instead.
#:
#: HONEST LIMITATION: fit quality is WORSE than the original fit (sum-
#: squared log error 0.186 vs 0.015), not because anything is wrong, but
#: because far fewer participants now enter the danger quadrant at all --
#: 0/120 at 22-25C, 1-2/120 at 28-31C, 13/120 at 34C. With this few
#: positive-dose observations, especially at the cooler end, the curve is
#: only loosely constrained. This is a direct, expected consequence of
#: fixing the over-prediction: fewer false positives means less data to
#: fit a dose-response curve from, at this sample size. Predicted/target
#: ratio ranged 0.59-1.79x across the 5 scenarios (vs 0.81-1.14x
#: pre-fix) -- treat this even more cautiously than before; a much
#: larger N (the same production-scale requirement noted throughout this
#: project) would be needed for a well-determined refit.
_DOSE_RESPONSE_A = -6.3837
_DOSE_RESPONSE_B = 0.4486


def cumulative_deficit_dose(res: list) -> float:
    """Cumulative CO_reserve deficit-minutes while T_rect>=40.5 AND
    CO_reserve<=0 (race + post-finish), for one simulated participant.

    Unlike the binary 'true EHS criterion' (in/out of the danger
    quadrant) or a hard duration threshold, this weights BOTH how deep
    into deficit someone goes AND how long they stay there -- analogous
    to cumulative-equivalent-minutes dose models used in hyperthermia
    medicine (e.g. CEM43), rather than treating every quadrant-timestep
    as equally severe regardless of depth.
    """
    dose = 0.0
    for r in res:
        t, c = r.get("t_rect"), r.get("co_reserve")
        if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
            if t >= 40.5 and c <= 0:
                dose += abs(c) * 10.0  # 10-min race timesteps -> L/min-minutes
    pf_t = res[-1].get("t_rect_series_postfinish") or []
    pf_c = res[-1].get("co_reserve_series_postfinish") or []
    for t, c in zip(pf_t, pf_c):
        if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
            if t >= 40.5 and c <= 0:
                dose += abs(c) * 0.5  # ~30s post-finish timesteps
    return dose


def participant_trace(res: list) -> dict:
    """Full per-timestep trace for one simulated participant: T_rect,
    CO_reserve, cumulative deficit dose, and minutes since start (race +
    post-finish). Used for the dose-evolution visualisation -- shows HOW
    a participant's risk builds over time, not just the final tally.
    """
    t_series, c_series, dose_series, minutes = [], [], [], []
    cum_dose = 0.0
    for i, r in enumerate(res):
        t, c = r.get("t_rect"), r.get("co_reserve")
        if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
            if t >= 40.5 and c <= 0:
                cum_dose += abs(c) * 10.0
            t_series.append(float(t)); c_series.append(float(c))
            dose_series.append(cum_dose); minutes.append(i * 10.0)
    pf_t = res[-1].get("t_rect_series_postfinish") or []
    pf_c = res[-1].get("co_reserve_series_postfinish") or []
    last_min = minutes[-1] if minutes else 0.0
    for j, (t, c) in enumerate(zip(pf_t, pf_c)):
        if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
            if t >= 40.5 and c <= 0:
                cum_dose += abs(c) * 0.5
            t_series.append(float(t)); c_series.append(float(c))
            dose_series.append(cum_dose); minutes.append(last_min + j * 0.5)
    return {"t": t_series, "c": c_series, "dose": dose_series, "min": minutes,
           "final_dose": cum_dose, "stopped_at": last_min}


def _population_median_trace(all_results: list) -> dict:
    """Point-by-point population median T_rect/CO_reserve/dose, computed
    across ALL participants at each shared time bucket -- not one
    'representative' individual, but the actual median value at every
    point in time. Always computable, even when every participant's
    final dose is zero (e.g. most walker scenarios), which is exactly
    when a single illustrative trace would have nothing to show.

    Time buckets are keyed by the same minute markers participant_trace()
    already uses (10-min race steps, ~0.5-min post-finish steps), so
    traces of different lengths (some participants' race-phase data ends
    earlier than others -- a known, separately-tracked simulation
    behaviour) still align correctly: each bucket's median only uses
    the participants who actually have a value there.
    """
    from collections import defaultdict
    t_by_min, c_by_min, dose_by_min = defaultdict(list), defaultdict(list), defaultdict(list)
    stop_times = []
    for res in all_results:
        tr = participant_trace(res)
        stop_times.append(tr["stopped_at"])
        for m, t, c, d in zip(tr["min"], tr["t"], tr["c"], tr["dose"]):
            t_by_min[m].append(t)
            c_by_min[m].append(c)
            dose_by_min[m].append(d)
    minutes = sorted(t_by_min)
    return {
        "label": "Population median",
        "min": minutes,
        "stopped_at": float(np.median(stop_times)) if stop_times else 0.0,
        "t": [float(np.median(t_by_min[m])) for m in minutes],
        "c": [float(np.median(c_by_min[m])) for m in minutes],
        "dose": [float(np.median(dose_by_min[m])) for m in minutes],
        "final_dose": float(np.median(dose_by_min[minutes[-1]])) if minutes else 0.0,
    }


def _select_representative_traces(all_results: list, doses: np.ndarray) -> list:
    """Population median (always present) plus up to 3 illustrative
    individual participants -- lowest (usually 0), median non-zero, and
    highest dose -- for the dose-evolution chart. The median alone still
    renders something informative (e.g. 'everyone stayed safe') even
    when no individual ever crosses the danger threshold, which used to
    make this return [] and suppress the chart entirely -- a real gap
    for low-MET scenarios (walkers) where that is the common case.
    """
    picks = [_population_median_trace(all_results)]
    order = np.argsort(doses)
    nonzero = [i for i in order if doses[i] > 0]
    if not nonzero:
        return picks
    idx_high = order[-1]
    idx_mid = nonzero[len(nonzero) // 2]
    idx_zero = next((i for i in order if doses[i] == 0), None)
    for idx, label in ([(idx_zero, "Lowest risk (dose=0)")] if idx_zero is not None else []) + [
        (idx_mid, "Median non-zero dose"), (idx_high, "Highest dose"),
    ]:
        picks.append({"label": label, **participant_trace(all_results[idx])})
    return picks


def dose_response_ehs_probability(dose: float) -> float:
    """Maps a cumulative deficit dose to an estimated EHS probability via
    the jointly-fit logistic curve. See _DOSE_RESPONSE_A/B docstring for
    fit provenance and honest limitations."""
    return 1.0 / (1.0 + np.exp(-(_DOSE_RESPONSE_A + _DOSE_RESPONSE_B * dose)))


def _summarize_results(all_results: list) -> dict:
    """Population statistics from a list of per-draw simulation results.
    Shared by _cached_quick_run and run_full_precision so the two paths
    can never compute these differently by accident.
    """
    t_rect_sims = np.array([[r["t_rect"] for r in res] for res in all_results])
    peak_t_rect = np.nanmax(t_rect_sims, axis=1)

    # "first_aid_visit" (per hestia_model.py, line ~3178) is a broad,
    # deliberately over-inclusive OR-based screening trigger --
    # (t_rect>=40.5) OR (water_loss_pct>=2.0) OR (rpe_total>=17) -- NOT a
    # calibrated probability of an actual medical incident. 2% dehydration
    # or RPE>=17 are common in a hard effort, which is why this legitimately
    # fires for a large fraction of a simulated field; it answers "worth
    # keeping an eye on", not "will need first aid". The real, calibrated
    # DtD 2024 first-aid rate (150/35,000 = 0.43%) is a completely
    # different, much narrower quantity -- see the caption where this is
    # displayed for that contrast, so the gap between the two doesn't read
    # as a broken model.
    first_aid = np.array([res[-1].get("first_aid_visit", False) for res in all_results])

    # T_rect >= 40.5 ALONE is deliberately NOT reported as an EHS estimate.
    # Veltmeijer's own findings, and the author's own conjunctive
    # hypothesis, are that T_rect elevation alone is not sufficient --
    # EHS requires T_rect>40.5 AND CO_reserve<=0 SIMULTANEOUSLY. The
    # model's own simulate_post_finish() already implements exactly this
    # conjunction, but ONLY for the 10-minute post-finish window
    # (hestia_model.py's own ehs_postfinish flag) -- it was never checked
    # DURING the race itself. Built here: the true conjunction, checked at
    # every timestep during the race (using the already-available per-step
    # t_rect/co_reserve arrays) and combined with the existing post-finish
    # flag, so a runner who meets both conditions simultaneously at any
    # point -- mid-race or shortly after -- is counted, and one who merely
    # has a high T_rect with intact cardiovascular reserve is not.
    true_ehs = []
    t_rect_co_reserve_pairs = []
    doses = []
    for res in all_results:
        during_race = any(
            (r.get("t_rect") is not None and r.get("co_reserve") is not None
             and not np.isnan(r.get("t_rect")) and not np.isnan(r.get("co_reserve"))
             and r["t_rect"] >= 40.5 and r["co_reserve"] <= 0)
            for r in res
        )
        post_finish = bool(res[-1].get("ehs_postfinish", False))
        true_ehs.append(during_race or post_finish)
        doses.append(cumulative_deficit_dose(res))

        # Same source data as the check above, kept for the scatter plot:
        # every point where both t_rect and co_reserve are known simultaneously.
        for r in res:
            t, c = r.get("t_rect"), r.get("co_reserve")
            if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
                t_rect_co_reserve_pairs.append((float(t), float(c)))
        t_pf = res[-1].get("t_rect_series_postfinish") or []
        c_pf = res[-1].get("co_reserve_series_postfinish") or []
        for t, c in zip(t_pf, c_pf):
            if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
                t_rect_co_reserve_pairs.append((float(t), float(c)))
    true_ehs = np.array(true_ehs)
    doses = np.array(doses)
    dose_response_pct = float(100.0 * np.mean(dose_response_ehs_probability(doses)))
    representative_traces = _select_representative_traces(all_results, doses)

    # CO_reserve: "how much capacity is lost during and shortly after the
    # race", and "% reaching zero/negative capacity". Baseline = first
    # valid (non-NaN) co_reserve observed during the race for that draw
    # (co_reserve is NaN at t=0 by construction). Worst point = the
    # minimum across BOTH the race trajectory AND the full post-finish
    # series (co_reserve_series_postfinish), not just the single
    # 10-minute post-finish endpoint -- the post-finish module documents
    # a validated acute dip that can occur and recover within that
    # window, which an endpoint-only read would miss entirely.
    baseline_co, worst_co = [], []
    for res in all_results:
        race_vals = [r.get("co_reserve") for r in res
                    if r.get("co_reserve") is not None and not np.isnan(r.get("co_reserve"))]
        pf_series = res[-1].get("co_reserve_series_postfinish") or []
        pf_vals = [v for v in pf_series if v is not None and not np.isnan(v)]
        baseline_co.append(race_vals[0] if race_vals else np.nan)
        combined = race_vals + pf_vals
        worst_co.append(min(combined) if combined else np.nan)
    baseline_co = np.array(baseline_co, dtype=float)
    worst_co = np.array(worst_co, dtype=float)

    valid = ~np.isnan(baseline_co) & ~np.isnan(worst_co) & (baseline_co > 0)
    pct_reserve_remaining = np.full(len(baseline_co), np.nan)
    pct_reserve_remaining[valid] = 100.0 * np.clip(worst_co[valid] / baseline_co[valid], 0.0, 1.0)
    pct_zero_or_negative = float(100 * np.mean(worst_co[~np.isnan(worst_co)] <= 0)) \
        if np.any(~np.isnan(worst_co)) else float("nan")

    return {
        "peak_t_rect_mean": float(np.nanmean(peak_t_rect)),
        "peak_t_rect_p95": float(np.nanpercentile(peak_t_rect, 95)),
        "peak_t_rect_max": float(np.nanmax(peak_t_rect)),
        "pct_true_ehs_criterion": float(100 * np.mean(true_ehs)),
        "pct_first_aid": float(100 * np.mean(first_aid)),
        "pct_ehs_postfinish": float(100 * np.mean(
            [bool(res[-1].get("ehs_postfinish", False)) for res in all_results])),
        "peak_t_rect_all": peak_t_rect.tolist(),
        "pct_reserve_remaining_mean": float(np.nanmean(pct_reserve_remaining)),
        "pct_reserve_remaining_median": float(np.nanmedian(pct_reserve_remaining)),
        "pct_zero_or_negative_capacity": pct_zero_or_negative,
        "n_with_valid_co_reserve": int(np.sum(valid)),
        "pct_dose_response_ehs": dose_response_pct,
        "cumulative_doses_all": doses.tolist(),
        "representative_traces": representative_traces,
        "worst_co_reserve_all": worst_co.tolist(),
        "t_rect_co_reserve_pairs": t_rect_co_reserve_pairs,
    }


@st.cache_data(ttl=60 * 60 * 2, show_spinner=False)
def _cached_quick_run(interp_data_key: tuple, lat: float, lon: float, tz_name: str,
                      met_value: float, clo_value: float, training_factor: float,
                      acclimatization_factor: float, n_simulations: int,
                      random_seed: int):
    """The actual cached computation. interp_data is passed as a hashable
    tuple-of-tuples key; reconstructed inside since st.cache_data needs
    hashable arguments."""
    interp_data = [
        {
            "time": pd.Timestamp(row[0]), "temp": row[1], "wind": row[2],
            "rh": row[3], "clouds": row[4], "pressure": row[5],
            "ghi": row[6], "solar_elevation": row[7], "globe_temp": row[8],
            "mrt": row[9],
        }
        for row in interp_data_key
    ]

    _patch_timezone(tz_name)
    aqi = _fetch_aqi_once(lat, lon)
    _patch_air_quality(aqi)

    workers = _capped_workers()
    t0 = time.time()
    pop = h.generate_base_population(
        n_simulations=n_simulations, training_factor=training_factor,
        acclimatization_factor=acclimatization_factor, random_seed=random_seed,
        met_value=met_value,
    )
    pct_pinned = float(100 * np.mean([p.pct_vo2max >= 0.9499 for p in pop])) if pop else float("nan")
    all_results, stats, results_df = h.run_monte_carlo_adult(
        interp_data, lat, lon, met_value, clo_value,
        n_simulations=n_simulations, age_configuration="standard",
        training_factor=training_factor, acclimatization_factor=acclimatization_factor,
        use_parallel=workers > 1, random_seed=random_seed, base_population=pop,
    )
    elapsed = time.time() - t0

    if stats is None:
        return None

    summary = _summarize_results(all_results)
    summary["pct_vo2max_pinned"] = pct_pinned
    return {
        "n": len(all_results),
        "workers": workers,
        "elapsed_s": elapsed,
        "aqi_used": aqi,
        **summary,
    }


def run_quick_estimate(weather_df: pd.DataFrame, lat: float, lon: float, tz_name: str,
                       start: pd.Timestamp, finish: pd.Timestamp,
                       met_value: float, clo_value: float = 0.2,
                       training_factor: float = 0.5, acclimatization_factor: float = 0.5,
                       n_simulations: int = QUICK_N, random_seed: int = 42) -> dict | None:
    """The quick-estimate entry point: small N, capped workers, cached by
    scenario. This is the one safe to call on every page render.

    [fix, 2026-08-10] clo_value default changed from 0.5 to 0.2. 0.5 (light
    indoor clothing per ISO 9920) was being applied to every scenario
    regardless of conditions, including hot-weather running kit (shorts +
    t-shirt + socks + shoes), which standard clo tables put at ~0.2-0.3, not
    0.5. Tested directly: at ~32degC/MET 10.5/96min, clo=0.5 gave a median
    peak race-phase T_rect of 41.4degC with 93% of the simulated population
    exceeding the clinical EHS threshold (40.5degC) -- clo=0.2 brought that
    to 40.0degC median and 8%, much closer to real measured data (Veltmeijer
    et al. 2014, JSAMS: 15% >=40degC in a 15km race, albeit in COOLER
    WBGT=11degC conditions -- so some elevation above 15% would still be
    expected at 32degC; 8% may itself run slightly low, worth revisiting
    once production-scale validation is done). This was the single largest
    contributor found in that investigation to HESTIA's T_rect
    over-prediction -- larger than any single factor found in the earlier
    CO_reserve/CHSI work.
    """
    interp_data = build_interp_data(weather_df, start, finish)
    # Hashable cache key: round timestamps/floats to avoid float-noise cache
    # misses between visually-identical reruns.
    key = tuple(
        (row["time"].isoformat(), round(row["temp"], 2), round(row["wind"], 2),
         round(row["rh"], 1), round(row["clouds"], 1), round(row["pressure"], 1),
         round(row["ghi"], 1), round(row["solar_elevation"], 2),
         round(row["globe_temp"], 2), round(row["mrt"], 2))
        for row in interp_data
    )
    result = _cached_quick_run(
        key, lat, lon, tz_name, met_value, clo_value,
        training_factor, acclimatization_factor, n_simulations, random_seed,
    )
    if result is not None:
        mean_t_air = float(np.mean([row["temp"] for row in interp_data]))
        result = dict(result)  # cached dict is shared -- don't mutate it in place
        result["mean_t_air_race_window"] = mean_t_air
        result["falmouth_ehs_per_1000"] = falmouth_ehs_per_1000(mean_t_air)
    return result


def run_full_precision(weather_df, lat, lon, tz_name, start, finish, met_value,
                       clo_value=0.2, training_factor=0.5, acclimatization_factor=0.5,
                       n_simulations=5000, random_seed=42,
                       progress_callback=None) -> dict | None:
    """Full-precision run. NOT cached at this level -- the quick-estimate
    cache already covers the common case; a 5000-draw run is expected to
    be requested rarely and deliberately. progress_callback(done, total),
    if given, is called after each chunk so a Streamlit progress bar can
    move and the session stays visibly alive during a multi-minute wait.
    """
    interp_data = build_interp_data(weather_df, start, finish)
    _patch_timezone(tz_name)
    aqi = _fetch_aqi_once(lat, lon)
    _patch_air_quality(aqi)

    pop = h.generate_base_population(
        n_simulations=n_simulations, training_factor=training_factor,
        acclimatization_factor=acclimatization_factor, random_seed=random_seed,
        met_value=met_value,
    )
    if not pop:
        return None

    workers = _capped_workers()
    worker_args = [(interp_data, lat, lon, met_value, clo_value, p,
                    training_factor, acclimatization_factor) for p in pop]

    all_results = []
    chunk = max(10, len(worker_args) // 40)  # ~40 progress updates
    t0 = time.time()
    if workers > 1:
        with multiprocessing.Pool(workers) as pool:
            for i, res in enumerate(pool.imap(h.worker_monte_carlo_adult, worker_args)):
                all_results.append(res)
                if progress_callback and (i + 1) % chunk == 0:
                    progress_callback(i + 1, len(worker_args))
    else:
        for i, args in enumerate(worker_args):
            all_results.append(h.worker_monte_carlo_adult(args))
            if progress_callback and (i + 1) % chunk == 0:
                progress_callback(i + 1, len(worker_args))
    elapsed = time.time() - t0
    if progress_callback:
        progress_callback(len(worker_args), len(worker_args))

    pct_pinned = float(100 * np.mean([p.pct_vo2max >= 0.9499 for p in pop])) if pop else float("nan")
    summary = _summarize_results(all_results)
    summary["pct_vo2max_pinned"] = pct_pinned
    mean_t_air = float(np.mean([row["temp"] for row in interp_data]))
    summary["mean_t_air_race_window"] = mean_t_air
    summary["falmouth_ehs_per_1000"] = falmouth_ehs_per_1000(mean_t_air)
    return {
        "n": len(all_results), "workers": workers, "elapsed_s": elapsed,
        "aqi_used": aqi,
        **summary,
    }


# =============================================================================
# Rendering
# =============================================================================
def render_hestia_section(st_module, weather_df: pd.DataFrame, lat: float, lon: float,
                          tz_name: str, level_label: str, met_value: float,
                          start: pd.Timestamp, finish: pd.Timestamp) -> dict | None:
    """One level's HESTIA panel. NOT auto-run: the quick estimate itself
    is now gated behind an explicit per-level button (persisted in
    st.session_state so it stays open across unrelated reruns), and full
    precision remains behind its own separate button as before.

    This used to run automatically for every eligible level on every
    page render -- meaning the heavy HESTIA import (~384MB) and a Monte
    Carlo run were paid unconditionally by anyone who used this app at
    all, whether or not they cared about this section. Gating it behind
    an explicit click means that cost, and the wall of experimental
    numbers, only appears for someone who actually asked for it.

    Returns the quick-estimate result dict (or None if not yet requested,
    or on failure), so callers can cross-reference it against other
    layers of the app.
    """
    event_minutes = max(1.0, (finish - start).total_seconds() / 60)
    st_module.markdown(f"**{level_label}**")

    requested_key = f"hestia_requested_{level_label}"
    already_requested = st_module.session_state.get(requested_key, False)
    if not already_requested:
        clicked = st_module.button(
            f"\U0001F52C Calculate race-day physiology \u2014 {level_label}",
            key=f"hestia_btn_{level_label}",
        )
        if clicked:
            st_module.session_state[requested_key] = True
        else:
            st_module.caption(
                "Not yet calculated for this level. This runs a real "
                f"physiological Monte Carlo (~{QUICK_N} simulated "
                "participants, a few seconds) \u2014 click above if you want "
                "the race-day capacity/EHS numbers for this level."
            )
            return None

    with st_module.spinner(f"Quick estimate (n={QUICK_N})..."):
        quick = run_quick_estimate(
            weather_df, lat, lon, tz_name, start, finish, met_value,
            n_simulations=QUICK_N,
        )
    if quick is None:
        st_module.warning("Could not generate a population for this scenario.")
        return None

    pct_pinned = quick.get("pct_vo2max_pinned")
    if pct_pinned is not None and not np.isnan(pct_pinned) and pct_pinned > 50:
        st_module.warning(
            f"\u26a0\ufe0f **Results withheld for {level_label}.** At this "
            f"pace (MET {met_value:.1f}), {pct_pinned:.0f}% of the simulated "
            "population is pinned at its physiological ceiling (95% "
            "VO2max) \u2014 the underlying fitness distribution wasn't built "
            "for this effort level, so individual variation collapses and "
            "the resulting statistics would not be trustworthy. Try a "
            "slower pace for this level, or interpret any number shown "
            "elsewhere for it with that in mind."
        )
        return None
    elif pct_pinned is not None and not np.isnan(pct_pinned) and pct_pinned > 20:
        st_module.caption(
            f"\u26a0\ufe0f {pct_pinned:.0f}% of the simulated population is "
            "pinned at its physiological ceiling for this pace \u2014 "
            "individual variation is somewhat compressed. Treat these "
            "numbers with extra caution."
        )

    falmouth_est = quick.get("falmouth_ehs_per_1000")
    mean_t = quick.get("mean_t_air_race_window")
    dose_pct = quick.get("pct_dose_response_ehs")

    if dose_pct is not None:
        race_minutes = (finish - start).total_seconds() / 60.0
        # The dose-response curve (_DOSE_RESPONSE_A/B) was jointly fit on
        # scenarios at MET~10.5, ~96 min. It has NOT been validated to
        # generalise to very different effort levels or durations -- flag
        # this explicitly rather than silently applying it everywhere,
        # since a walker at MET~3 or a 4-hour event is well outside what
        # was actually tested.
        met_off = abs(met_value - 10.5) > 3.0
        dur_off = abs(race_minutes - 96) > 60
        st_module.metric(
            "EHS estimate (primary: dose-response model)",
            f"\u2248{dose_pct*10:.1f} per 1000",
            help="A logistic curve over each simulated participant's "
                 "cumulative T_rect/CO_reserve deficit (depth \u00d7 "
                 "duration in the danger zone), fit jointly against "
                 "Falmouth Road Race epidemiology (DeMartini et al. 2014) "
                 "across 5 temperature scenarios. Refit 2026-08-10 after "
                 "a clo_value correction (0.5->0.2) that fixed a major "
                 "T_rect over-prediction; predicted/target ratio is now "
                 "0.6-1.8x -- wider than the pre-fix 0.8-1.1x, because far "
                 "fewer participants now enter the danger quadrant at all "
                 "(as few as 0/120 at cooler temperatures), leaving less "
                 "data to constrain the curve. Reflects THIS scenario's "
                 "actual pace, duration and group -- unlike the "
                 "temperature-only Falmouth estimate below, which cannot "
                 "see any of that. EXPLORATORY: fit at n=120/scenario, "
                 "well below the ~4,000-30,000 a production-scale fit "
                 "would need -- treat with real caution.")
        if met_off or dur_off:
            st_module.warning(
                "\u26a0\ufe0f This scenario (MET "
                f"{met_value:.1f}, {race_minutes:.0f} min) falls outside "
                "the range the dose-response curve was actually fit on "
                "(MET\u224810.5, \u224896 min). It has NOT been validated to "
                "generalise this far -- treat this number with extra "
                "caution here, more so than usual."
            )
        note_parts = []
        if falmouth_est is not None:
            note_parts.append(
                f"epidemiologically-calibrated estimate (Falmouth, "
                f"temperature-only): \u2248{falmouth_est:.1f} per 1000"
                + (f" at {mean_t:.1f}\u00b0C" if mean_t is not None else "")
            )
        raw_pct = quick.get("pct_true_ehs_criterion")
        if raw_pct is not None:
            note_parts.append(
                f"raw HESTIA simulation (uncalibrated): "
                f"{raw_pct:.1f}% (\u2248{raw_pct*10:.0f} per 1000)"
            )
        if note_parts:
            st_module.caption("\u2139\ufe0f For comparison \u2014 " + "; ".join(note_parts) + ".")

    with st_module.expander("Raw physiological simulation (HESTIA, currently uncalibrated)"):
        st_module.warning(
            "\u26a0\ufe0f The figures in this section come directly from "
            "HESTIA's own physiological simulation, with NO correction "
            "applied. Testing found they over-predict real Falmouth Road "
            "Race EHS incidence by roughly 20-50x across a comparable "
            "temperature range -- shown here for transparency and for "
            "tracking how future recalibration changes them, not as a "
            "number to use directly."
        )
        c1, c2, c3 = st_module.columns(3)
        c1.metric("Peak T_re, mean", f"{quick['peak_t_rect_mean']:.1f}\u00b0C")
        c2.metric("True EHS criterion met", f"{quick['pct_true_ehs_criterion']:.1f}%",
                 help="T_rect >= 40.5\u00b0C AND CO_reserve <= 0, SIMULTANEOUSLY, "
                      "at any point during the race or in the 10-min post-finish "
                      "window \u2014 the author's own conjunctive hypothesis. "
                      "T_rect alone is deliberately NOT reported as an EHS risk: "
                      "Veltmeijer's own findings, and this hypothesis itself, "
                      "hold that elevated T_rect without cardiovascular "
                      "decompensation is not sufficient for harm.")
        c3.metric("Worth monitoring (broad screen)", f"{quick['pct_first_aid']:.1f}%",
                 help="T_rect>=40.5 OR dehydration>=2% OR RPE>=17, at any point "
                      "\u2014 a deliberately broad, over-inclusive screening flag "
                      "(hestia_model.py), NOT a calibrated medical-incident rate. "
                      "For contrast: DtD 2024's own observed first-aid rate was "
                      "150/35,000 = 0.43%, a much narrower real-world quantity.")

        d1, d2 = st_module.columns(2)
        reserve_left = quick.get("pct_reserve_remaining_mean")
        zero_or_neg = quick.get("pct_zero_or_negative_capacity")
        if reserve_left is not None and not np.isnan(reserve_left):
            d1.metric("Avg. cardiovascular capacity remaining",
                      f"{reserve_left:.0f}%",
                      delta=f"-{100 - reserve_left:.0f}pp lost", delta_color="inverse")
        if zero_or_neg is not None and not np.isnan(zero_or_neg):
            d2.metric("Reached zero/negative capacity",
                      f"{zero_or_neg:.1f}%",
                      help="Share of the simulated group whose cardiac-output "
                           "reserve reached zero or below, at any point during "
                           "the race or in the 10 minutes after finishing.")
        st_module.caption(
            "\u2139\ufe0f **PROVISIONAL calibration** \u2014 the intercepts behind "
            "HESTIA's incident-rate translation are self-labelled 'PROVISIONAL' "
            "in the model's own source (reduced N=200 feasibility fit, not "
            "production-scale; recalibrated after a July 2026 cardiovascular-"
            "module rebuild). Treat these numbers as directional, not as "
            "settled probabilities, until re-run at production scale."
        )
        st_module.caption(
            "\u2139\ufe0f The middle two figures answer 'how much capacity does "
            "an average runner lose during and shortly after the race' and "
            "'what share reach zero or negative capacity' \u2014 using HESTIA's "
            "own cardiac-output-reserve (Lloyd et al. 2022), evaluated at the "
            "actual race timescale (minute-by-minute through the race plus "
            "the 10-minute post-finish window), not PYROX's multi-day model. "
            f"Based on {quick.get('n_with_valid_co_reserve', '?')} of "
            f"{quick['n']} simulated participants with a usable CO_reserve "
            "trajectory."
        )

    st_module.caption(
        f"Quick estimate, n={quick['n']} (of the app's own simulated population, "
        f"not real participants), {quick['elapsed_s']:.1f}s on {quick['workers']} "
        f"worker(s). Wider uncertainty than a full run \u2014 treat as indicative."
    )

    est_full = time_estimate_seconds(5000, event_minutes)
    if st_module.button(f"Run full precision (n=5000, est. ~{est_full/60:.1f} min)",
                        key=f"hestia_full_{level_label}"):
        progress = st_module.progress(0.0, text="Starting full Monte Carlo...")

        def _cb(done, total):
            progress.progress(done / total, text=f"{done}/{total} simulated participants...")

        with st_module.spinner("Running full-precision HESTIA Monte Carlo..."):
            full = run_full_precision(
                weather_df, lat, lon, tz_name, start, finish, met_value,
                n_simulations=5000, progress_callback=_cb,
            )
        progress.empty()
        if full is None:
            st_module.warning("Full-precision run failed to generate a population.")
        else:
            full_falmouth = full.get("falmouth_ehs_per_1000")
            quick_falmouth = quick.get("falmouth_ehs_per_1000")
            if full_falmouth is not None:
                st_module.metric(
                    "EHS estimate (epidemiologically calibrated) \u2014 full precision",
                    f"\u2248{full_falmouth:.1f} per 1000",
                    delta=(f"{full_falmouth - quick_falmouth:+.1f} vs quick"
                          if quick_falmouth is not None else None),
                    help="Same Falmouth-based calibration as the quick estimate "
                         "above (DeMartini et al. 2014) \u2014 shown again here "
                         "because it depends only on ambient temperature, not "
                         "on sample size, so it should barely move between "
                         "quick and full precision. A large difference would "
                         "itself be worth investigating.",
                )
                st_module.caption(
                    "\u2139\ufe0f The figures below are HESTIA's own raw, "
                    "uncalibrated physiological simulation (full precision), "
                    "shown for comparison against the quick estimate \u2014 "
                    "not the calibrated figure above."
                )

            f1, f2, f3 = st_module.columns(3)
            f1.metric("Peak T_re, mean", f"{full['peak_t_rect_mean']:.1f}\u00b0C",
                      delta=f"{full['peak_t_rect_mean']-quick['peak_t_rect_mean']:+.1f} vs quick")
            f2.metric("True EHS criterion met (raw, uncalibrated)", f"{full['pct_true_ehs_criterion']:.1f}%",
                      delta=f"{full['pct_true_ehs_criterion']-quick['pct_true_ehs_criterion']:+.1f}pp vs quick",
                      help="T_rect>=40.5\u00b0C AND CO_reserve<=0, simultaneously. "
                           "Raw simulation output -- NOT the calibrated estimate above.")
            f3.metric("Worth monitoring (broad screen)", f"{full['pct_first_aid']:.1f}%",
                      delta=f"{full['pct_first_aid']-quick['pct_first_aid']:+.1f}pp vs quick",
                      help="Broad OR-based screen, not a calibrated incident rate.")

            g1, g2 = st_module.columns(2)
            full_reserve = full.get("pct_reserve_remaining_mean")
            quick_reserve = quick.get("pct_reserve_remaining_mean")
            full_zeroneg = full.get("pct_zero_or_negative_capacity")
            quick_zeroneg = quick.get("pct_zero_or_negative_capacity")
            if full_reserve is not None and not np.isnan(full_reserve):
                delta_r = (f"{full_reserve - quick_reserve:+.0f}pp vs quick"
                          if quick_reserve is not None and not np.isnan(quick_reserve) else None)
                g1.metric("Avg. cardiovascular capacity remaining",
                         f"{full_reserve:.0f}%", delta=delta_r, delta_color="inverse")
            if full_zeroneg is not None and not np.isnan(full_zeroneg):
                delta_z = (f"{full_zeroneg - quick_zeroneg:+.1f}pp vs quick"
                          if quick_zeroneg is not None and not np.isnan(quick_zeroneg) else None)
                g2.metric("Reached zero/negative capacity",
                         f"{full_zeroneg:.1f}%", delta=delta_z)

            st_module.caption(
                f"Full precision, n={full['n']}, {full['elapsed_s']:.1f}s on "
                f"{full['workers']} worker(s)."
            )

    return quick
