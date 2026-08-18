# -*- coding: utf-8 -*-
"""
individual_engine.py
=====================
A single-person, on-demand wrapper around the same JOS-3 + CVR physiology
engine and dose-response calibration that already power PYROX's
population-level apps (app.py, app_beleid.py, app_athletes.py) -- built
for exactly one real person's own biometrics and one real event, instead
of a sampled population of a few thousand virtual participants.

Nothing in the physiology or calibration is reimplemented here.
calculate_indices_jos3_adult(), AdultParticipantProfile,
cumulative_deficit_dose() and dose_response_ehs_probability() are the
exact same functions the population apps call -- this module only
supplies a different SOURCE of participant profiles: one real person,
described once, instead of thousands sampled from a distribution.

PRIVACY ARCHITECTURE
---------------------
Personal data entered here (height, weight, age, pace, ...) and every
outcome derived from it (T_rect trace, CO_reserve trace, EHS estimate)
never leave this process. The only network calls anywhere in this
module's call graph are the two Thermopoulos already uses for the
population apps:
    geocode_city_candidates()          -- place name  -> lat/lon/timezone
    fetch_hourly_forecast() /
    fetch_historical_data()            -- lat/lon/date -> weather
Both were checked directly against Thermopoulos_Data_Engine.py's actual
outgoing request parameters (see PYROX_WINDOWS_PRIVACY.md): they send
latitude, longitude, date(s) and units -- never any field of
PersonalInputs. No analytics, telemetry, or other outbound call exists
in this module or in what it imports.

That guarantee covers this module's code. Two more steps make it hold
for the packaged application as a whole, and are NOT this module's
responsibility -- see PYROX_WINDOWS_PACKAGING.md:
    1. Streamlit's own anonymous usage telemetry (on by default) must be
       disabled via .streamlit/config.toml.
    2. The local server must bind to 127.0.0.1, not 0.0.0.0, so nothing
       else on the network can reach it.

WHY AN ENSEMBLE, NOT ONE DETERMINISTIC RUN
-------------------------------------------
generate_base_population() (hestia_model.py) samples roughly fifteen
fields per virtual participant to represent a whole population. For one
real, named individual most of those fields are directly knowable
(height, weight, age, gender, pace) and are FIXED here to the entered
value -- resampling a known quantity would just add fake noise on top
of a real number.

But a handful of the sampled fields were never standing in for
between-PERSON variability alone; they represent things that are
genuinely unknowable in advance even for one specific person on one
specific day:
    kp_pacing        -- interoceptive / motivational pacing response
    wind_angle_rad    -- course heading vs. wind direction (untracked)
    sweat_factor,
    pct_vo2max noise -- day-to-day physiological variation
    temp/rh offset   -- course microclimate vs. weather-station siting
Collapsing all of these to one point guess would produce a single,
falsely precise trace -- exactly the failure mode this suite's own
population-level EHS figure ran into (see uncertainty.py). Instead this
module runs a small personal ensemble: every entered field held fixed,
only this short list re-drawn per member from the same conditional
distributions generate_base_population() already uses, and reports a
band, not a line.

The EHS probability returned here reuses uncertainty.py's sampling +
anchor interval machinery directly, and inherits the same caveat: it
does not cover the dose-response slope, which is not identified from
the present calibration set. See uncertainty.py's module docstring.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from hestia_model import (
    AdultParticipantProfile,
    VO2MAX_TO_MET_FACTOR,
    K_P_PACING,
    K_P_SIGMA,
    K_P_NSAID_FACTOR,
    _daniels_gilbert_vo2_at_pace,
    calculate_indices_jos3_adult,
)
from Thermopoulos_Data_Engine import (
    ROUGHNESS_Z0_TERRAIN,
    geocode_city_candidates,
    fetch_hourly_forecast,
    fetch_historical_data,
    process_weather_data,
    validate_weather_data,
)
from hestia_bridge import (
    build_interp_data,
    cumulative_deficit_dose,
    dose_response_ehs_probability,
    participant_trace,
    _select_representative_traces,
)
import uncertainty as _unc


# =============================================================================
# What the user is actually asked
# =============================================================================
@dataclass
class PersonalInputs:
    """Everything asked directly of the person. No field here is ever
    guessed or silently defaulted -- the calling form must collect all
    of these (known_vo2max and known_body_fat_pct are the only two
    genuinely optional fields; see their docstrings below).
    """
    height_m: float
    weight_kg: float
    age: int
    gender: str                        # 'male' | 'female'
    expected_pace_min_per_km: float
    nsaid_use: bool                    # takes NSAIDs (e.g. ibuprofen) before/during
    drinks_readily: bool               # True: drinks at ~every station.
                                        # False: waits until clearly thirsty.
    heat_acclimatized: bool            # trained or lived in heat recently (~2+ weeks)

    # Optional overrides -- only if the person genuinely knows these,
    # e.g. from a sports watch's VO2max estimate or a recent BIA/DEXA
    # scan. Left as None, both fall back to an age/gender-conditioned
    # population mean (the same prior generate_base_population() centres
    # its sampling on for an unknown individual) -- a reasonable point
    # default, not a claim about this specific person.
    known_vo2max: float | None = None
    known_body_fat_pct: float | None = None

    def validate(self) -> None:
        if self.gender not in ("male", "female"):
            raise ValueError("gender must be 'male' or 'female'")
        if not (1.30 <= self.height_m <= 2.20):
            raise ValueError("height_m looks out of range (expected 1.30-2.20 m)")
        if not (30.0 <= self.weight_kg <= 200.0):
            raise ValueError("weight_kg looks out of range (expected 30-200 kg)")
        if not (10 <= self.age <= 90):
            raise ValueError("age looks out of range (expected 10-90)")
        if not (2.5 <= self.expected_pace_min_per_km <= 15.0):
            raise ValueError(
                "expected_pace_min_per_km looks out of range (expected 2.5-15 min/km)")


@dataclass
class EventScenario:
    """The event itself. GPX is optional -- terrain refines MRT/albedo
    inputs via the existing GPX/OSM/ESA WorldCover pipeline
    (terrain_lookup.py) but is not required to run an assessment."""
    location_query: str                # free-text place name, geocoded
    start_local: pd.Timestamp          # event start, LOCAL time (naive; the
                                        # geocoded timezone is applied)
    duration_minutes: float
    use_historical: bool = False       # True: ERA5 hindcast for a past date.
                                        # False: forecast (only valid for
                                        # dates within the forecast horizon).
    gpx_path: str | None = None
    clo_value: float = 0.2             # running kit default; see
                                        # run_quick_estimate's clo_value note
                                        # in hestia_bridge.py for why 0.2,
                                        # not the old 0.5 indoor-clothing value.
    terrain_key: str = "3"             # ROUGHNESS_Z0_TERRAIN key (Thermopoulos_
                                        # Data_Engine.py). "3" = open agricultural
                                        # terrain, scattered obstacles -- same
                                        # default app_beleid.py's dropdown starts
                                        # on (index=2). Controls the 10m->1.5m
                                        # wind-profile correction only.


# =============================================================================
# Deriving one ensemble member's physiology profile
# =============================================================================
def _default_vo2max(age: int, gender: str) -> float:
    """Age/gender-conditioned mean VO2max -- same mean formula as Step 3
    of generate_base_population() (hestia_model.py), evaluated as a point
    default for one specific person rather than a distribution to sample.
    Ref: Scharhag-Rosenberger et al. 2010; Tanaka et al. 2001."""
    mu = 52.0 if gender == "male" else 44.0
    return mu - 0.5 * max(0, age - 35)


def _default_body_fat_pct(gender: str) -> float:
    """Population mean only (Nikolaidis et al. 2021), used solely because
    body fat % is not something most people can enter accurately without
    a BIA/DEXA measurement. If the person has one, known_body_fat_pct
    should be used instead."""
    return 17.7 if gender == "male" else 19.6


def _build_profile(inputs: PersonalInputs, rng: np.random.Generator) -> AdultParticipantProfile:
    """One ensemble member: every field the person actually entered is
    fixed exactly as given. Only the handful of genuinely-unknowable
    fields are drawn -- from the same conditional distributions
    generate_base_population() already uses, just conditioned on this
    person's real age/gender/pace instead of also sampling those."""
    vo2max = (inputs.known_vo2max if inputs.known_vo2max is not None
              else _default_vo2max(inputs.age, inputs.gender))
    body_fat_pct = (inputs.known_body_fat_pct if inputs.known_body_fat_pct is not None
                    else _default_body_fat_pct(inputs.gender))

    # pct_vo2max: DERIVED from the entered pace (same relationship
    # generate_base_population() Step 6 uses when met_value is known),
    # not sampled. The sigma=0.04 economy-noise term is retained per
    # draw -- real day-to-day variation in running economy, not a
    # stand-in for not knowing who this person is.
    vo2_at_pace = _daniels_gilbert_vo2_at_pace(inputs.expected_pace_min_per_km)
    pct_vo2max_det = vo2_at_pace / vo2max
    pct_vo2max = float(np.clip(rng.normal(pct_vo2max_det, 0.04), 0.15, 0.95))

    sweat_loc = 0.8 + (0.3 if inputs.heat_acclimatized else 0.0)
    sweat_factor = float(np.clip(rng.normal(sweat_loc, 0.15), 0.4, 1.5))

    # Thirst threshold: mapped from the plain drinking-habit question,
    # onto the same range generate_base_population() Step 8 samples
    # (acclimatization narrows the upper bound there too).
    thirst_hi_cap = 2.5 - (1.0 if inputs.heat_acclimatized else 0.0)
    if inputs.drinks_readily:
        thirst_lo, thirst_hi = 1.0, min(1.6, thirst_hi_cap)
    else:
        thirst_lo, thirst_hi = min(1.6, thirst_hi_cap), max(1.6, thirst_hi_cap)
    thirst_threshold = float(rng.uniform(thirst_lo, max(thirst_lo + 0.05, thirst_hi)))

    kp_base = float(np.clip(rng.normal(K_P_PACING, K_P_SIGMA), 0.0, 0.25))
    kp_pacing = kp_base * (K_P_NSAID_FACTOR if inputs.nsaid_use else 1.0)

    return AdultParticipantProfile(
        height=inputs.height_m,
        weight=inputs.weight_kg,
        age=inputs.age,
        gender=inputs.gender,
        body_fat_pct=body_fat_pct,
        vo2max=vo2max,
        pct_vo2max=pct_vo2max,
        temp_variation=float(rng.normal(0.0, 1.5)),
        rh_variation=float(rng.normal(0.0, 3.0)),
        mf_score=float(rng.uniform(0.0, 1.0)),
        sweat_factor=sweat_factor,
        thirst_threshold=thirst_threshold,
        kp_pacing=kp_pacing,
        nsaid_gebruik=inputs.nsaid_use,
        wind_angle_rad=float(rng.uniform(0.0, 2 * np.pi)),
    )


# =============================================================================
# Weather + geocoding (the ONLY network calls in this module's call graph)
# =============================================================================
def _localize_naive(ts: pd.Timestamp, tz: str) -> pd.Timestamp:
    """Attach the event's timezone to a naive local-wall-clock Timestamp.

    EventScenario.start_local is deliberately naive -- the UI form has no
    way to know the event's timezone until AFTER geocoding resolves it,
    so it can only hand over "what the user typed", not a fully-qualified
    instant. Every place that later compares this timestamp against a
    tz-aware value (weather_df's index, or pd.Timestamp.now(tz=...)) MUST
    localize it first, through this one function, so there is exactly
    one interpretation of "naive local time" in this module -- not two
    independently-written tz_localize() calls that could quietly drift
    apart. See run_individual_assessment()'s own docstring note for the
    bug this fixes: comparing a naive Timestamp against a tz-aware one
    via .astype('int64') does not raise an error, it silently shifts the
    whole race window by the local UTC offset (1-2 hours for the
    Netherlands, CET/CEST) with no error message at all.

    ambiguous=True (not 'infer', which Thermopoulos_Data_Engine.py uses
    but which is only valid on a DatetimeIndex -- inferring a DST fold
    needs multiple consecutive points, a single Timestamp has none) picks
    the DST-active interpretation for the one hour each autumn that
    occurs twice. For a single scheduled event time this is a rare edge
    case either way; documented here rather than silently defaulted.
    """
    return ts.tz_localize(tz, nonexistent="shift_forward", ambiguous=True)


def fetch_scenario_weather(scenario: EventScenario):
    """Geocode the location and fetch weather for the event window.

    Sends only: place-name text (geocoding) and lat/lon/date(s) (weather).
    No PersonalInputs field is read by this function or passed to either
    Thermopoulos call -- it does not even take a PersonalInputs argument.
    """
    candidates = geocode_city_candidates(scenario.location_query)
    if not candidates:
        raise ValueError(f"No location found for '{scenario.location_query}'.")
    city = candidates[0]
    lat, lon, tz = city["latitude"], city["longitude"], city["timezone"]

    finish_local = scenario.start_local + pd.Timedelta(minutes=scenario.duration_minutes)
    if scenario.use_historical:
        weather_df, coastal = fetch_historical_data(
            lat, lon, tz,
            scenario.start_local.strftime("%Y-%m-%d"),
            finish_local.strftime("%Y-%m-%d"))
        weather_df = validate_weather_data(weather_df, "historical")
    else:
        days_ahead = max(1, (_localize_naive(finish_local, tz).normalize()
                              - pd.Timestamp.now(tz=tz).normalize()).days + 1)
        weather_df, coastal = fetch_hourly_forecast(lat, lon, tz, days_ahead)
        weather_df = validate_weather_data(weather_df, "forecast")

    weather_df = process_weather_data(
        weather_df, city, lat, lon, tz, coastal_active=coastal,
        roughness_z0=ROUGHNESS_Z0_TERRAIN[scenario.terrain_key][1])
    return weather_df, city, lat, lon, tz




def meteo_timeseries(weather_df, start_aware: pd.Timestamp, finish_aware: pd.Timestamp,
                      interval_minutes: int = 10) -> dict:
    """T_air, WBGT, UTCI and MRT over the race window, for DISPLAY only.

    Deliberately separate from hestia_bridge.build_interp_data(), which
    feeds the physiology engine: that function only carries T_air_urban/
    MRT (plus wind/rh/clouds/...) through, because JOS-3 takes those as
    direct inputs and has no use for WBGT/UTCI, which are downstream
    composite indices computed FROM the same underlying weather, not
    additional inputs to it. Rather than modify a shared function used by
    the population apps just to expose two more columns for one page's
    chart, this reuses the identical linear-interpolation approach
    against the same tz-aware weather_df index, so T_air/MRT here match
    interp_data's temp/mrt values exactly (see
    test_individual_engine.py's meteo/physiology consistency check).

    start_aware/finish_aware must already be tz-aware (localized via
    _localize_naive) -- same requirement as build_interp_data, for the
    same reason: comparing naive against weather_df's tz-aware index
    does not raise an error, it silently shifts the whole window (see
    _localize_naive's docstring).
    """
    times = pd.date_range(start=start_aware, end=finish_aware, freq=f"{interval_minutes}min")
    if len(times) < 2:
        times = pd.date_range(start=start_aware, periods=2, freq=f"{interval_minutes}min")
    idx_num = weather_df.index.astype("int64").to_numpy()
    q_num = times.astype("int64").to_numpy()

    def _interp(col):
        if col not in weather_df.columns:
            return np.full(len(times), np.nan)
        return np.interp(q_num, idx_num, weather_df[col].to_numpy())

    return {
        "time": list(times),
        "t_air": _interp("T_air_urban"),
        "wbgt": _interp("WBGT"),
        "utci": _interp("UTCI"),
        "mrt": _interp("MRT"),
    }


def _extended_bands(all_traces: list, lo_pct: float = 2.5, hi_pct: float = 97.5) -> dict:
    """T_rect/CO_reserve median + percentile bands across the ensemble,
    spanning race AND post-finish, correctly time-aligned.

    lo_pct/hi_pct default to 2.5/97.5 (a 95% band) rather than a tighter
    10/90 (80% band): for a heat-risk assessment the outliers ARE the
    point -- a narrower band visually discards exactly the tail draws
    (unlucky pacing response, unfavourable wind direction, ...) that
    matter most for deciding whether to worry. [Changed 2026-08-16 on
    request, after 10/90 was judged too tight for this purpose.]

    Reuses hestia_bridge.participant_trace()'s race/post-finish split
    and the SAME alignment strategy as hestia_bridge._population_median_
    trace(): the race phase is aligned by absolute minutes-since-start
    (valid because every ensemble member starts together), and the
    post-finish phase is aligned by minutes-since-EACH-member's-OWN-
    finish, then the whole post-finish segment is offset by the
    ensemble's MEDIAN stop time. hestia_bridge.py documents exactly why
    the naive alternative -- aligning everything by absolute minutes
    since start throughout -- produces a sawtooth artifact once some
    members are still racing while others have already finished and
    started recovering. Reusing that already-debugged alignment here
    rather than re-deriving (and risking re-introducing) the same bug.

    Unlike hestia_bridge._population_median_trace(), which returns only
    the median, this also returns percentile bands -- matching the rest
    of this module's "band, not a line" treatment of the genuinely
    unknowable day-of factors (see this module's own docstring).
    """
    race_t_by_min, race_c_by_min = defaultdict(list), defaultdict(list)
    pf_t_by_min, pf_c_by_min = defaultdict(list), defaultdict(list)
    stop_times = []
    for res in all_traces:
        tr = participant_trace(res)
        stop_times.append(tr["stopped_at"])
        for m, t, c in zip(tr["race_min"], tr["race_t"], tr["race_c"]):
            race_t_by_min[m].append(t)
            race_c_by_min[m].append(c)
        for m, t, c in zip(tr["pf_min_since_finish"], tr["pf_t"], tr["pf_c"]):
            pf_t_by_min[m].append(t)
            pf_c_by_min[m].append(c)

    median_stop = float(np.median(stop_times)) if stop_times else 0.0
    race_minutes = sorted(race_t_by_min)
    pf_minutes = sorted(pf_t_by_min)
    minutes = list(race_minutes) + [median_stop + m for m in pf_minutes]
    phase = (["race"] * len(race_minutes)) + (["postfinish"] * len(pf_minutes))

    def _stats(by_min: dict, keys: list) -> tuple:
        med = [float(np.median(by_min[m])) for m in keys]
        lo = [float(np.percentile(by_min[m], lo_pct)) for m in keys]
        hi = [float(np.percentile(by_min[m], hi_pct)) for m in keys]
        return med, lo, hi

    t_med_r, t_lo_r, t_hi_r = _stats(race_t_by_min, race_minutes)
    t_med_p, t_lo_p, t_hi_p = _stats(pf_t_by_min, pf_minutes)
    c_med_r, c_lo_r, c_hi_r = _stats(race_c_by_min, race_minutes)
    c_med_p, c_lo_p, c_hi_p = _stats(pf_c_by_min, pf_minutes)

    return {
        "minutes": minutes, "phase": phase, "median_stop_minute": median_stop,
        "t_rect_median": t_med_r + t_med_p, "t_rect_lo": t_lo_r + t_lo_p, "t_rect_hi": t_hi_r + t_hi_p,
        "co_reserve_median": c_med_r + c_med_p, "co_reserve_lo": c_lo_r + c_lo_p, "co_reserve_hi": c_hi_r + c_hi_p,
    }


# =============================================================================
# The assessment itself
# =============================================================================
@dataclass
class IndividualAssessment:
    n_ensemble: int
    minutes: list                      # minutes since event start; spans race + post-finish
    phase: list                        # 'race' | 'postfinish', aligned with `minutes`
    median_stop_minute: float          # ensemble median finish time (minutes since start) --
                                        # where the race/post-finish boundary falls on the chart
    t_rect_median: np.ndarray
    t_rect_lo: np.ndarray               # 10th percentile band
    t_rect_hi: np.ndarray               # 90th percentile band
    co_reserve_median: np.ndarray
    co_reserve_lo: np.ndarray
    co_reserve_hi: np.ndarray
    conjunction_fraction: float        # share of ensemble members meeting
                                        # T_rect>=40.5 AND CO_reserve<=0
                                        # at any point (race or post-finish)
    ehe_fraction: float                # share meeting the EHE
                                        # criterion (T_rect>39.5 AND
                                        # CO_reserve<0, same timestep, during
                                        # exertion).
                                        # Deliberately a FRACTION, never a
                                        # per-1000 rate: no calibration
                                        # anchor exists for this criterion.
    ehe_dose_mean: float               # MEAN EHE dose across the whole ensemble
                                        # (0 for non-qualifying members). Not a
                                        # median: with a minority of members
                                        # qualifying, the median is 0 by
                                        # construction and hides the signal.
    ehe_dose_among_hits: float         # median EHE dose among QUALIFYING members
                                        # only -- "how bad is it when it happens"
    eac_fraction: float                # share meeting EAC (CO_reserve<0
                                        # post-finish, no temperature condition)
    eac_dose_mean: float               # MEAN EAC dose across the whole ensemble
    eac_dose_among_hits: float         # median EAC dose among qualifying members
    ehs_interval: dict                 # from uncertainty.ehs_interval(),
                                        # same "sampling + anchor" caveats
    mean_t_air_c: float
    city_name: str
    meteo: dict                        # from meteo_timeseries(): T_air/WBGT/UTCI/MRT
                                        # over the RACE window (display only -- post-finish
                                        # has no associated weather, see meteo_timeseries())
    all_traces: list                   # raw per-member `res` lists, for
                                        # export/plotting by the caller


def run_individual_assessment(
    inputs: PersonalInputs,
    scenario: EventScenario,
    *,
    n_ensemble: int = 200,
    training_factor: float = 0.5,
    acclimatization_factor: float | None = None,
    random_seed: int = 42,
    progress_callback: Callable[[float, str], None] | None = None,
    band_lo_pct: float = 2.5,
    band_hi_pct: float = 97.5,
) -> IndividualAssessment:
    """Run the personal ensemble and return the aggregated assessment.

    All computation after fetch_scenario_weather() is local: no further
    network access occurs in this function or anything it calls.

    progress_callback, if given, is called with (fraction_done in
    [0, 1], status_text) at meaningful points: once for the weather/
    geocoding fetch, then once per ensemble member. This module has no
    Streamlit dependency of its own -- the callback is how the UI layer
    (app_persoonlijk.py) wires a progress bar to a run that can take
    a minute or more at n_ensemble=200, without this engine module
    needing to know Streamlit exists.

    band_lo_pct/band_hi_pct control the T_rect/CO_reserve percentile
    band width (default 2.5/97.5, a 95% band -- see _extended_bands()'s
    docstring for why that default was chosen over a tighter 10/90).
    """
    inputs.validate()
    if acclimatization_factor is None:
        acclimatization_factor = 1.0 if inputs.heat_acclimatized else 0.0

    def _progress(frac: float, text: str) -> None:
        if progress_callback is not None:
            progress_callback(frac, text)

    _progress(0.0, "Locatie en weer ophalen\u2026")
    weather_df, city, lat, lon, tz = fetch_scenario_weather(scenario)
    finish_local = scenario.start_local + pd.Timedelta(minutes=scenario.duration_minutes)
    # CRITICAL: weather_df's index is tz-aware (localized to the event's
    # own timezone by Thermopoulos_Data_Engine.py). scenario.start_local/
    # finish_local are tz-naive by construction (see EventScenario's
    # docstring). Comparing a naive and an aware timestamp via
    # build_interp_data's internal .astype('int64') does NOT raise an
    # error -- it silently shifts the whole race window by the local UTC
    # offset (1-2 hours for CET/CEST), with no warning anywhere. Confirmed
    # directly: at 10:30 local, the unlocalized version fed the simulation
    # the 12:30 local reading instead. Must localize before calling
    # build_interp_data, every time, via the same helper used above.
    start_aware = _localize_naive(scenario.start_local, tz)
    finish_aware = _localize_naive(finish_local, tz)
    interp_data = build_interp_data(weather_df, start_aware, finish_aware)
    mean_t_air = float(np.mean([row["temp"] for row in interp_data]))
    meteo = meteo_timeseries(weather_df, start_aware, finish_aware)

    # MET for the liveability check only (see calculate_indices_jos3_adult's
    # docstring: individual MET is derived from vo2max*pct_vo2max, this
    # met_value argument is reference-only).
    vo2max_ref = (inputs.known_vo2max if inputs.known_vo2max is not None
                  else _default_vo2max(inputs.age, inputs.gender))
    met_value_ref = (_daniels_gilbert_vo2_at_pace(inputs.expected_pace_min_per_km)
                      / VO2MAX_TO_MET_FACTOR)

    _progress(0.05, f"Simulatie starten (0/{n_ensemble})\u2026")
    # [fix, 2026-08-16] Seed the GLOBAL numpy RNG as well, not just this
    # module's own default_rng. calculate_indices_jos3_adult() draws the
    # per-drink volume from the global np.random (np.random.uniform(120,
    # 180) in its main loop) -- the only unseeded randomness inside the
    # engine. Without this line, `random_seed` controlled only the
    # ensemble PROFILES while the drinking term still varied freely, so
    # two runs with identical inputs and identical seed produced
    # different doses and different EHS estimates. Verified directly:
    # before this line, running the same 60-participant batch twice
    # changed the dose for 49 of 60 participants.
    # generate_base_population() (hestia_model.py) already does exactly
    # this for the population apps -- this brings the personal path in
    # line with it rather than inventing a different convention.
    np.random.seed(random_seed)
    rng = np.random.default_rng(random_seed)
    all_traces = []
    for i in range(n_ensemble):
        profile = _build_profile(inputs, rng)
        res = calculate_indices_jos3_adult(
            interp_data, lat, lon, met_value_ref, scenario.clo_value,
            profile, training_factor, acclimatization_factor,
        )
        all_traces.append(res)
        # Weather/geocoding gets the first 5%, the ensemble loop (by far
        # the slow part -- ~0.4s/member, so ~80s at the default 200) gets
        # up to 98%, leaving room for the two steps after the loop so the
        # bar never ticks backward.
        _progress(0.05 + 0.93 * (i + 1) / n_ensemble,
                  f"Ensemble-run {i + 1}/{n_ensemble}\u2026")

    bands = _extended_bands(all_traces, lo_pct=band_lo_pct, hi_pct=band_hi_pct)

    # Exact same conjunctive check hestia_bridge.py uses for the
    # population: T_rect>=40.5 AND CO_reserve<=0 at the SAME timestep,
    # during the race or in the post-finish window.
    conj_hits = 0
    ehe_hits = 0
    eac_hits = 0
    doses = []
    ehe_doses = []
    eac_doses = []
    for res in all_traces:
        during_race = any(
            (r.get("t_rect") is not None and r.get("co_reserve") is not None
             and not np.isnan(r.get("t_rect")) and not np.isnan(r.get("co_reserve"))
             and r["t_rect"] >= 40.5 and r["co_reserve"] <= 0)
            for r in res
        )
        post_finish = bool(res[-1].get("ehs_postfinish", False))
        if during_race or post_finish:
            conj_hits += 1
        if conjunctive_hit(res, EHE_T_THRESHOLD, EHE_CO_THRESHOLD,
                           strict=True, window="race"):
            ehe_hits += 1
        if eac_hit(res):
            eac_hits += 1
        doses.append(cumulative_deficit_dose(res))
        ehe_doses.append(ehe_dose(res))
        eac_doses.append(eac_dose(res))

    _progress(0.99, "Resultaten samenvatten\u2026")
    ehs_ci = _unc.ehs_interval(np.array(doses), mean_t_air, n_boot=2000, random_seed=random_seed)

    result = IndividualAssessment(
        n_ensemble=n_ensemble,
        minutes=bands["minutes"], phase=bands["phase"],
        median_stop_minute=bands["median_stop_minute"],
        t_rect_median=np.array(bands["t_rect_median"]), t_rect_lo=np.array(bands["t_rect_lo"]),
        t_rect_hi=np.array(bands["t_rect_hi"]),
        co_reserve_median=np.array(bands["co_reserve_median"]), co_reserve_lo=np.array(bands["co_reserve_lo"]),
        co_reserve_hi=np.array(bands["co_reserve_hi"]),
        conjunction_fraction=conj_hits / n_ensemble,
        ehe_fraction=ehe_hits / n_ensemble,
        ehe_dose_mean=float(np.mean(ehe_doses)) if ehe_doses else 0.0,
        ehe_dose_among_hits=(float(np.median([d for d in ehe_doses if d > 0]))
                              if any(d > 0 for d in ehe_doses) else 0.0),
        eac_fraction=eac_hits / n_ensemble,
        eac_dose_mean=float(np.mean(eac_doses)) if eac_doses else 0.0,
        eac_dose_among_hits=(float(np.median([d for d in eac_doses if d > 0]))
                              if any(d > 0 for d in eac_doses) else 0.0),
        ehs_interval=ehs_ci,
        mean_t_air_c=mean_t_air,
        city_name=f"{city['name']}, {city.get('country', '')}".strip(", "),
        meteo=meteo,
        all_traces=all_traces,
    )
    _progress(1.0, "Klaar.")
    return result


# =============================================================================
# Conjunctive criteria
# =============================================================================
#: The author's own conjunctive EHS criterion: T_rect >= 40.5 C AND
#: CO_reserve <= 0 AT THE SAME TIMESTEP. 40.5 C after Roberts (2010).
EHS_T_THRESHOLD  = 40.5
EHS_CO_THRESHOLD = 0.0

#: --- EHE: Exertional Heat Exhaustion -------------------------------------
#: T_rect > 39.5 C AND CO_reserve < 0 at the SAME timestep, DURING exertion.
#:
#: Formerly labelled "collapse" in this module; renamed 2026-08-17 after
#: checking the definitions against the literature. The clinical entity
#: this matches is exertional heat exhaustion (ACSM Expert Consensus
#: Statement on Exertional Heat Illness, 2023): core temperature
#: typically 38.5-40 C, inability to continue, WITHOUT the CNS
#: dysfunction that defines EHS. 39.5 C sits inside that band.
#: "Collapse" was the wrong word: in the sports-medicine literature
#: that term denotes EAC (see below), a different entity with the
#: opposite pathophysiology.
#:
#: WHAT THIS CRITERION ACTUALLY MEANS -- checked empirically against
#: this model's own output (2026-08-17), not assumed:
#: Following ensemble members from the moment they first meet it, T_rect
#: does NOT then climb to the 40.5 C EHS threshold. It plateaus: of 40
#: warned members at 31 C, exactly one later reached 40.5 C, and that
#: one was already above it when warned. The state is stable in
#: temperature, not a slope toward heat stroke.
#: But CO_reserve keeps falling at that plateau (e.g. -0.10 -> -0.46
#: over five 10-min steps at a constant 40.14 C). MET stays essentially
#: flat over the same span (11.04 -> 11.00, i.e. 0.4%), so pacing is NOT
#: what stabilises the temperature -- a genuine thermal steady state is,
#: while dehydration erodes CO_max underneath it.
#: So the criterion marks LOST CONTROL MARGIN, not impending
#: hyperthermia: temperature is being held only because heat production
#: and loss happen to balance, while the capacity to answer any further
#: disturbance (a climb, a sheltered windless stretch, a finishing
#: sprint) is disappearing. In control terms: the regulated variable
#: looks fine while the actuator reserve runs out.
#: This is why EHE_dose (the integral of the deficit over time) is the
#: more informative output than the yes/no flag -- erosion is the
#: phenomenon, not threshold-crossing.
#:
#: Independent confirmation (2026-08-19): Kong et al., "Exceeding human
#: heat tolerance in a warming, ageing world" (Lancet Planet Health,
#: 2026) cites chamber-experiment evidence from the same PSU HEAT
#: Project lineage (Cottle et al. 2024, J Appl Physiol) that
#: "cardiovascular strain, indicated by a sustained increase in heart
#: rate, occurs before core temperature begins to rise continuously."
#: That is the same temporal ordering this criterion targets -- found
#: independently, in a different age group (middle-aged, 40-59) and a
#: different exposure type (resting/ADL heat exposure, not exercise),
#: which is exactly the kind of independent replication a single-anchor,
#: uncalibrated criterion like this one benefits from. It does not
#: calibrate EHE (their thresholds are for near-resting metabolic rate,
#: an order of magnitude below marathon MET, so the exposure regime does
#: not transfer directly) -- but it corroborates the mechanism.
#:
#: NOT the same construct as hestia_model.py's existing `p_collapse`
#: two-phase logistic. That model reads t_rect_max_per_sim (maximum over
#: the whole trace) and res_min (minimum over the whole trace)
#: INDEPENDENTLY, so a T_rect peak at 11:00 and a CO_reserve trough at
#: 13:00 both contribute even though they never co-occurred. This
#: criterion is strictly simultaneous.
#:
#: NOT calibrated against observed EHE incidence -- no anchor dataset
#: exists for it, so this module reports it as a FRACTION OF THE
#: ENSEMBLE and never converts it to a rate per 1000.
EHE_T_THRESHOLD  = 39.5
EHE_CO_THRESHOLD = 0.0

#: --- EAC: Exercise-Associated Collapse ------------------------------------
#: CO_reserve < 0 in the POST-FINISH window only. No temperature
#: requirement -- deliberately.
#:
#: EAC (Asplund & O'Connor 2011; Roberts 2007; StatPearls) is collapse in
#: a CONSCIOUS athlete who cannot stand or walk unaided, occurring after
#: an endurance event. Its mechanism is postural hypotension: the muscle
#: pump stops at the finish line, cutaneous vasodilation persists, venous
#: return falls, and cerebral perfusion follows. It is cardiovascular,
#: not thermal -- which is why imposing a temperature threshold here
#: would be wrong, not merely conservative. Asplund's own guidance is
#: that collapse DURING a race points to some other, more serious cause.
#:
#: This is the one criterion in this module with a real external anchor:
#: the Gothenburg Half Marathon reports 1.53 EAC cases per 1000 runners,
#: and EAC accounts for 59-85% of finish-line medical-tent visits. That
#: makes it the first candidate since Falmouth for calibrating an
#: absolute rate rather than a relative signal. Not attempted here --
#: reported as an ensemble fraction like the others, pending a proper
#: dose-response fit against that anchor.
EAC_CO_THRESHOLD = 0.0

#: Minimum accumulated post-finish deficit (L/min x minutes) before EAC
#: is counted. Requiring merely ONE crossing of zero produced obvious
#: false positives: measured on a severe scenario (30 C, 3 h, 5:00/km),
#: 40% of the population had at least one negative post-finish step, but
#: HALF of those had exactly one 30-second step before recovering. A
#: single half-minute dip is not a collapse -- it is the ordinary
#: blood-pressure drop on stopping, which simulate_post_finish() itself
#: documents as a validated acute dip that occurs and recovers inside
#: this window. Someone who actually collapses stays down for minutes.
#:
#: The empirical distribution has a clear knee: raising the threshold
#: from 0 to 0.5 drops the count from 40% to 15%, after which it is
#: nearly flat (15% at 1.0, 12.5% at 2.0). 0.5 therefore sits at the
#: elbow -- it removes the single-step transients without cutting into
#: the sustained cases.
#:
#: This does NOT make the count a clinical incidence. Meeting a
#: mechanistic precondition is not the same as the syndrome: real EAC
#: additionally requires cerebral hypoperfusion, an upright posture and
#: a moment. The count therefore still sits orders of magnitude above
#: observed incidence (1.53 per 1000, Gothenburg Half Marathon), exactly
#: as the EHS criterion count does against Falmouth. Calibrating against
#: the Gothenburg anchor -- the way pct_dose_response_ehs is calibrated
#: against Falmouth -- remains the outstanding work that would turn this
#: into a genuine rate.
EAC_DOSE_THRESHOLD = 0.5


def conjunctive_hit(res: list, t_threshold: float, co_threshold: float,
                     strict: bool = False, window: str = "both") -> bool:
    """True if T_rect and CO_reserve BOTH cross their thresholds at the
    SAME timestep, within the requested window.

    window: 'race' (during exertion only), 'postfinish' (the recovery
    window only), or 'both'. This matters because the three criteria in
    this module are deliberately scoped differently:
        EHS  -> both      (can occur during or just after)
        EHE  -> race      (exhaustion is a during-exertion entity)
        EAC  -> postfinish (Asplund: collapse DURING a race points to a
                            different, more serious cause)
    Scoping them identically would quietly merge three distinct clinical
    entities into one number.

    `strict` selects > / < rather than >= / <=. EHS uses non-strict
    (>=40.5, <=0) to match how it is stated in the literature; EHE uses
    strict (>39.5, <0). Kept as an explicit argument so the asymmetry is
    visible at every call site rather than hidden per-criterion.
    """
    def _hit(t, c) -> bool:
        if t is None or c is None or np.isnan(t) or np.isnan(c):
            return False
        return ((t > t_threshold) if strict else (t >= t_threshold)) and \
               ((c < co_threshold) if strict else (c <= co_threshold))

    if window in ("race", "both"):
        for r in res:
            if _hit(r.get("t_rect"), r.get("co_reserve")):
                return True
    if window in ("postfinish", "both"):
        pf_t = res[-1].get("t_rect_series_postfinish") or []
        pf_c = res[-1].get("co_reserve_series_postfinish") or []
        if any(_hit(t, c) for t, c in zip(pf_t, pf_c)):
            return True
    return False


def eac_hit(res: list) -> bool:
    """EAC: a SUSTAINED post-finish cardiac-output deficit, with no
    temperature condition. See EAC_CO_THRESHOLD for why imposing one
    would be wrong rather than merely conservative, and
    EAC_DOSE_THRESHOLD for why a single zero-crossing is not enough."""
    return eac_dose(res) > EAC_DOSE_THRESHOLD


def ehe_dose(res: list) -> float:
    """Cumulative CO_reserve deficit-minutes while the EHE conjunction
    holds DURING exertion -- same construction as
    hestia_bridge.cumulative_deficit_dose(), at the milder temperature
    threshold and restricted to the race window.

    This, rather than the yes/no flag, is the output that matches what
    the criterion actually describes: the empirical check documented at
    EHE_T_THRESHOLD found the warned state to be stable in temperature
    while the reserve deficit keeps deepening, so the integral of that
    deficit carries the signal and a threshold crossing does not."""
    dose = 0.0
    for r in res:
        t, c = r.get("t_rect"), r.get("co_reserve")
        if t is not None and c is not None and not np.isnan(t) and not np.isnan(c):
            if t > EHE_T_THRESHOLD and c < EHE_CO_THRESHOLD:
                dose += abs(c) * 10.0          # 10-min race timesteps
    return dose


def eac_dose(res: list) -> float:
    """Cumulative CO_reserve deficit-minutes in the post-finish window
    (no temperature condition), i.e. the EAC analogue of ehe_dose()."""
    dose = 0.0
    pf_c = res[-1].get("co_reserve_series_postfinish") or []
    for c in pf_c:
        if c is not None and not np.isnan(c) and c < EAC_CO_THRESHOLD:
            dose += abs(c) * 0.5               # ~30s post-finish timesteps
    return dose


def dose_scatter_points(all_traces: list) -> dict:
    """T_rect / CO_reserve / cumulative-dose triples across every
    (ensemble member, timestep) combination -- data only, no plotting.

    Reuses hestia_bridge.participant_trace() rather than re-deriving
    dose accumulation here, so there is exactly one implementation of
    "how dose builds over time", shared with the population apps'
    dose-evolution chart.

    IMPORTANT for interpretation: each point's dose is the CUMULATIVE
    dose up to that timestep along that ensemble member's own
    trajectory -- not a fixed per-point severity, and not that member's
    single final total. A given member's points sweep from dose=0
    toward their own final_dose as their simulated race progresses;
    colour them accordingly rather than reading each point as an
    independent "total".

    Also returns a `phase` array ('race' | 'postfinish') per point.
    This matters because the race and post-finish windows can look
    like two visually separate clusters: cardiac output reserve tends
    to rebound quickly once someone stops (recovering demand), while
    T_rect lags and stays elevated a little longer -- a real
    "afterdrop"-style physiological pattern, not a plotting artefact.
    Without a phase label, that split is easy to misread as a bug the
    first time someone sees it.
    """
    t_all, c_all, d_all, phase_all = [], [], [], []
    for res in all_traces:
        tr = participant_trace(res)
        n_race = len(tr["race_t"])
        t_all.extend(tr["t"])
        c_all.extend(tr["c"])
        d_all.extend(tr["dose"])
        phase_all.extend(["race"] * n_race + ["postfinish"] * (len(tr["t"]) - n_race))
    return {
        "t_rect": np.array(t_all),
        "co_reserve": np.array(c_all),
        "dose": np.array(d_all),
        "phase": np.array(phase_all),
    }


def representative_trajectories(all_traces: list) -> list:
    """A small number of representative ensemble members' full T_rect/
    CO_reserve paths over time (race + post-finish) -- a legible
    complement to plotting every ensemble member as a raw point cloud
    (see dose_scatter_points()): connected paths show HOW a member's
    state moved through T_rect/CO_reserve space, which a cloud of
    disconnected points cannot.

    Reuses hestia_bridge._select_representative_traces() -- the exact
    selection rule the population apps' own dose-evolution chart
    already uses (ensemble median, plus lowest/median-nonzero/highest
    dose members, or coolest/median/hottest-peak members if every dose
    is zero) -- rather than inventing a second selection rule here.

    Each returned dict has: 'label' (English, from hestia_bridge -- this
    module stays English throughout; translate at the UI layer, same as
    everywhere else in this codebase), 'min' (minutes since start),
    't' (T_rect), 'c' (CO_reserve), 'dose', 'stopped_at' (that specific
    trace's own finish time in minutes).
    """
    doses = np.array([cumulative_deficit_dose(res) for res in all_traces])
    return _select_representative_traces(all_traces, doses)


def zone_episode(tr: dict) -> dict | None:
    """For one representative trajectory (from representative_trajectories()),
    determine whether and how it entered the conjunctive danger zone
    (T_rect>=40.5 AND CO_reserve<=0) -- and, crucially, whether any exit
    from that zone happened WHILE STILL EXERTING or only AFTER the
    finish. A static chart does not make this distinction visible by
    itself; this function computes it directly from the trace.

    These two exits are not equivalent. Exiting post-finish is largely
    a consequence of simulate_post_finish() feeding the CVR model
    resting metabolic rate (PF_MET_RUST) instead of race-pace MET:
    cardiac output demand collapses once running stops, which can pull
    CO_reserve back above zero even while T_rect is still elevated (see
    the note on this in this module's docstring history). That is a
    mechanical consequence of stopping, not evidence the thermal danger
    resolved. Exiting the zone DURING the race means the danger
    genuinely eased while the person was still under load -- a
    meaningfully more reassuring pattern, and worth telling apart in
    plain language for a non-expert reader.

    Returns None if the trace never entered the zone at all. Otherwise:
        'entered_during_race'    -- zone reached at some point while m <= stopped_at
        'in_zone_at_finish'      -- still in the zone at that member's own finish moment
        'entered_only_postfinish'-- zone reached ONLY after finishing, never during the race
        'exited_during_race'     -- left the zone before finishing, while still exerting
    """
    in_zone = [(t >= 40.5 and c <= 0) for t, c in zip(tr["t"], tr["c"])]
    if not any(in_zone):
        return None
    stopped_at = tr["stopped_at"]
    during_race = [z for z, m in zip(in_zone, tr["min"]) if m <= stopped_at]
    after_finish = [z for z, m in zip(in_zone, tr["min"]) if m > stopped_at]
    finish_idx = min(range(len(tr["min"])), key=lambda i: abs(tr["min"][i] - stopped_at))
    return {
        "entered_during_race": any(during_race),
        "in_zone_at_finish": in_zone[finish_idx],
        "entered_only_postfinish": (not any(during_race)) and any(after_finish),
        "exited_during_race": any(during_race) and not in_zone[finish_idx],
    }


def assessment_caveats(a: IndividualAssessment) -> list[str]:
    """Caveats to show alongside the assessment. Mirrors
    uncertainty.interval_caveats() but reworded for a personal-ensemble
    context rather than a population-sampling one."""
    notes = list(_unc.interval_caveats(a.ehs_interval))
    notes.append(
        f"The T_rect and CO_reserve bands reflect {a.n_ensemble} runs with "
        f"your entered details held fixed and only the genuinely unknowable "
        f"day-of factors (pacing response, wind direction, sweat-rate "
        f"variation) re-drawn. They are NOT a population percentile band -- "
        f"every run in this ensemble is you, on slightly different "
        f"assumptions about factors nobody can know in advance."
    )
    if a.ehe_fraction > 0 or a.eac_fraction > 0:
        notes.append(
            f"EHE ({a.ehe_fraction:.0%}) and EAC ({a.eac_fraction:.0%}) are shares "
            f"of YOUR OWN ensemble runs \u2014 not rates per 1000, and not calibrated "
            f"against observed incidence for either criterion. Read them as "
            f"relative severity signals for comparing scenarios. For EHE the "
            f"dose (mean {a.ehe_dose_mean:.2f}, median among those affected "
            f"{a.ehe_dose_among_hits:.2f}) is the more informative "
            f"figure: the criterion marks lost control margin that keeps "
            f"deepening at a stable temperature, not an imminent threshold "
            f"crossing."
        )
    return notes
