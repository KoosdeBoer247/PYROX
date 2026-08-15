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

from dataclasses import dataclass, field

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
        days_ahead = max(1, (finish_local.normalize() - pd.Timestamp.now(tz=tz).normalize()).days + 1)
        weather_df, coastal = fetch_hourly_forecast(lat, lon, tz, days_ahead)
        weather_df = validate_weather_data(weather_df, "forecast")

    weather_df = process_weather_data(weather_df, city, lat, lon, tz, coastal_active=coastal)
    return weather_df, city, lat, lon, tz


# =============================================================================
# The assessment itself
# =============================================================================
@dataclass
class IndividualAssessment:
    n_ensemble: int
    t_rect_median: np.ndarray          # one value per timestep
    t_rect_lo: np.ndarray              # 10th percentile band
    t_rect_hi: np.ndarray              # 90th percentile band
    co_reserve_median: np.ndarray
    co_reserve_lo: np.ndarray
    co_reserve_hi: np.ndarray
    time_labels: list
    conjunction_fraction: float        # share of ensemble members meeting
                                        # T_rect>=40.5 AND CO_reserve<=0
                                        # at any point (race or post-finish)
    ehs_interval: dict                 # from uncertainty.ehs_interval(),
                                        # same "sampling + anchor" caveats
    mean_t_air_c: float
    city_name: str
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
) -> IndividualAssessment:
    """Run the personal ensemble and return the aggregated assessment.

    All computation after fetch_scenario_weather() is local: no further
    network access occurs in this function or anything it calls.
    """
    inputs.validate()
    if acclimatization_factor is None:
        acclimatization_factor = 1.0 if inputs.heat_acclimatized else 0.0

    weather_df, city, lat, lon, tz = fetch_scenario_weather(scenario)
    finish_local = scenario.start_local + pd.Timedelta(minutes=scenario.duration_minutes)
    interp_data = build_interp_data(weather_df, scenario.start_local, finish_local)
    mean_t_air = float(np.mean([row["temp"] for row in interp_data]))

    # MET for the liveability check only (see calculate_indices_jos3_adult's
    # docstring: individual MET is derived from vo2max*pct_vo2max, this
    # met_value argument is reference-only).
    vo2max_ref = (inputs.known_vo2max if inputs.known_vo2max is not None
                  else _default_vo2max(inputs.age, inputs.gender))
    met_value_ref = (_daniels_gilbert_vo2_at_pace(inputs.expected_pace_min_per_km)
                      / VO2MAX_TO_MET_FACTOR)

    rng = np.random.default_rng(random_seed)
    all_traces = []
    for _ in range(n_ensemble):
        profile = _build_profile(inputs, rng)
        res = calculate_indices_jos3_adult(
            interp_data, lat, lon, met_value_ref, scenario.clo_value,
            profile, training_factor, acclimatization_factor,
        )
        all_traces.append(res)

    n_steps = min(len(r) for r in all_traces)

    def _band(field_name: str):
        arr = np.array([[r.get(field_name, np.nan) for r in trace[:n_steps]]
                         for trace in all_traces], dtype=float)
        return (np.nanmedian(arr, axis=0),
                np.nanpercentile(arr, 10, axis=0),
                np.nanpercentile(arr, 90, axis=0))

    t_med, t_lo, t_hi = _band("t_rect")
    c_med, c_lo, c_hi = _band("co_reserve")
    time_labels = [r["time"] for r in all_traces[0][:n_steps]]

    # Exact same conjunctive check hestia_bridge.py uses for the
    # population: T_rect>=40.5 AND CO_reserve<=0 at the SAME timestep,
    # during the race or in the post-finish window.
    conj_hits = 0
    doses = []
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
        doses.append(cumulative_deficit_dose(res))

    ehs_ci = _unc.ehs_interval(np.array(doses), mean_t_air, n_boot=2000, random_seed=random_seed)

    return IndividualAssessment(
        n_ensemble=n_ensemble,
        t_rect_median=t_med, t_rect_lo=t_lo, t_rect_hi=t_hi,
        co_reserve_median=c_med, co_reserve_lo=c_lo, co_reserve_hi=c_hi,
        time_labels=time_labels,
        conjunction_fraction=conj_hits / n_ensemble,
        ehs_interval=ehs_ci,
        mean_t_air_c=mean_t_air,
        city_name=f"{city['name']}, {city.get('country', '')}".strip(", "),
        all_traces=all_traces,
    )


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
    return notes
