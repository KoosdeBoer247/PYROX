# -*- coding: utf-8 -*-
"""
test_individual_engine.py
===========================
Regression tests for individual_engine.py and local_storage.py.

Deliberately does NOT call fetch_scenario_weather() for real -- there is
no network access in most CI/sandbox environments, and this suite isn't
trying to re-test Open-Meteo's API. What it DOES catch automatically:

  1. Signature drift between individual_engine.fetch_scenario_weather()
     and Thermopoulos_Data_Engine.process_weather_data(). This is
     exactly the bug found 2026-08-15 in production (Streamlit Cloud):
     process_weather_data() gained/kept a required roughness_z0
     argument that fetch_scenario_weather() never supplied. That bug
     could not be caught by py_compile or unit tests that mock the
     weather call -- only by inspecting the real signatures against
     each other. test_no_missing_required_args() below does exactly
     that, generically, so it also catches the NEXT such mismatch
     without needing to be told what changed.

  2. The physiology/ensemble/conjunction/interval pipeline, using
     hand-built synthetic weather data -- i.e. everything downstream of
     the network call.

  3. local_storage.py round-trips, including terrain_key (added in the
     same fix, and itself missed on the first pass through
     local_storage.py -- caught only by writing this round-trip test).

Run standalone:  PYTHONPATH=. python3 test_individual_engine.py
"""

import inspect
import os
import tempfile

import numpy as np
import pandas as pd

os.environ.setdefault("PYROX_DATA_DIR", tempfile.mkdtemp())

from individual_engine import (
    PersonalInputs, EventScenario, IndividualAssessment,
    fetch_scenario_weather, _build_profile, zone_episode,
)
from Thermopoulos_Data_Engine import process_weather_data
from hestia_model import calculate_indices_jos3_adult, VO2MAX_TO_MET_FACTOR, _daniels_gilbert_vo2_at_pace
from hestia_bridge import cumulative_deficit_dose
import uncertainty as unc
import local_storage as store


def _check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return cond


def test_timezone_localization() -> bool:
    """Regression test for the bug found 2026-08-15 on Streamlit Cloud
    (forecast branch, Utrecht scenario): EventScenario.start_local is
    tz-naive by design (the form can't know the event timezone before
    geocoding resolves it), while weather_df's index is tz-aware. Two
    distinct failures came from that mismatch:

      1. A raised exception in the forecast day-count calculation
         ("Cannot subtract tz-naive and tz-aware datetime-like
         objects") -- loud, easy to notice.
      2. A SILENT ~1-2 hour shift of the entire race window in
         build_interp_data(), caught only by manually reconstructing
         the exact interpolation and checking the returned temperature
         against a known-distinct value per hour. This kind of bug
         raises no exception at all -- only this kind of numeric check
         catches it, which is why it is pinned here permanently rather
         than left to be re-discovered by chance.

    Every prior screenshot in this project's history that used live
    weather (Amsterdam Sept 2024, the first Utrecht run) was silently
    affected by failure #2 before this fix.
    """
    print("Timezone localization (silent race-window shift regression)")
    ok = True

    tz = "Europe/Amsterdam"
    naive_hours = pd.date_range("2026-05-31 06:00", periods=12, freq="h")
    weather_index = naive_hours.tz_localize(tz, nonexistent="shift_forward", ambiguous="infer")
    weather_df = pd.DataFrame({"T_air_urban": np.arange(6, 18)}, index=weather_index)

    from individual_engine import _localize_naive
    from hestia_bridge import build_interp_data

    start_local = pd.Timestamp("2026-05-31 10:30")   # naive, exactly what a form gives
    finish_local = start_local + pd.Timedelta(minutes=60)
    start_aware = _localize_naive(start_local, tz)
    finish_aware = _localize_naive(finish_local, tz)
    interp = build_interp_data(weather_df, start_aware, finish_aware, interval_minutes=30)

    ok &= _check("10:30 local resolves to ~10.5\u00b0C, not the 12:30 reading (12.5\u00b0C)",
                 9.9 <= interp[0]["temp"] <= 11.1, f"got {interp[0]['temp']}")

    # Winter (CET, UTC+1) must be handled too -- tz_localize reads the
    # correct offset per-date from the tz database automatically, but
    # worth pinning both seasons since CEST/CET is exactly the kind of
    # thing that can silently regress if _localize_naive is ever
    # bypassed for one call site and not another.
    winter_hours = pd.date_range("2026-01-15 06:00", periods=12, freq="h")
    winter_index = winter_hours.tz_localize(tz, nonexistent="shift_forward", ambiguous="infer")
    winter_df = pd.DataFrame({"T_air_urban": np.arange(0, 12)}, index=winter_index)
    w_start = _localize_naive(pd.Timestamp("2026-01-15 09:00"), tz)
    w_finish = _localize_naive(pd.Timestamp("2026-01-15 09:30"), tz)
    w_interp = build_interp_data(winter_df, w_start, w_finish, interval_minutes=30)
    ok &= _check("winter (CET) 09:00 local resolves to ~3\u00b0C, not a 1h-shifted reading",
                 2.9 <= w_interp[0]["temp"] <= 3.1, f"got {w_interp[0]['temp']}")
    return ok


def test_reproducibility_same_seed() -> bool:
    """Regression test for the unseeded-global-RNG bug found 2026-08-16.

    calculate_indices_jos3_adult() draws each drink's volume from the
    GLOBAL numpy RNG (np.random.uniform(120, 180) in its main loop) --
    the only unseeded randomness inside the engine.
    run_individual_assessment() originally seeded only its own
    np.random.default_rng(random_seed) for building ensemble PROFILES,
    leaving that drinking term free-running. Two runs with identical
    inputs AND identical random_seed therefore produced different doses
    and different EHS estimates. Measured before the fix: the dose
    changed for 49 of 60 participants between two runs of the same code.

    generate_base_population() already seeds the global RNG for the
    population apps; run_individual_assessment() now does the same.

    This matters beyond tidiness: a personal report a user downloads
    twice for the same event would otherwise show different numbers,
    with no indication which one to believe."""
    print("Reproducibility: same seed -> identical results")
    ok = True

    tz = "Europe/Amsterdam"
    hours = pd.date_range("2026-05-31 06:00", periods=14, freq="h").tz_localize(tz)
    n = len(hours)
    weather_df = pd.DataFrame({
        "T_air_urban": 26 + 6 * np.sin(np.linspace(0, np.pi, n)),
        "MRT": 30 + 15 * np.sin(np.linspace(0, np.pi, n)),
        "WBGT": 21 + 6 * np.sin(np.linspace(0, np.pi, n)),
        "UTCI": 23 + 7 * np.sin(np.linspace(0, np.pi, n)),
        "wind_10m": np.full(n, 1.5), "RH": np.full(n, 62.0), "cloud_cover": np.full(n, 10.0),
        "pressure": np.full(n, 1013.0), "solar_radiation": np.full(n, 780.0),
        "solar_elevation": np.full(n, 58.0), "T_globe": np.full(n, 34.0),
    }, index=hours)
    fake_city = {"name": "Utrecht", "country": "Netherlands",
                 "latitude": 52.09, "longitude": 5.12, "timezone": tz}

    import individual_engine as ie
    original_fetch = ie.fetch_scenario_weather
    ie.fetch_scenario_weather = lambda scenario: (weather_df, fake_city, 52.09, 5.12, tz)
    try:
        inputs = PersonalInputs(height_m=1.76, weight_kg=80.0, age=48, gender="male",
                                 expected_pace_min_per_km=5.2, nsaid_use=False,
                                 drinks_readily=False, heat_acclimatized=False)
        scenario = EventScenario(location_query="Utrecht",
                                  start_local=pd.Timestamp("2026-05-31 11:00"),
                                  duration_minutes=150.0, use_historical=True)
        a = ie.run_individual_assessment(inputs, scenario, n_ensemble=25, random_seed=1234)
        b = ie.run_individual_assessment(inputs, scenario, n_ensemble=25, random_seed=1234)
        c = ie.run_individual_assessment(inputs, scenario, n_ensemble=25, random_seed=9999)
    finally:
        ie.fetch_scenario_weather = original_fetch

    ok &= _check("same seed -> identical conjunction fraction",
                 a.conjunction_fraction == b.conjunction_fraction,
                 f"{a.conjunction_fraction} vs {b.conjunction_fraction}")
    ok &= _check("same seed -> identical EHS point estimate",
                 a.ehs_interval["point_per_1000"] == b.ehs_interval["point_per_1000"],
                 f"{a.ehs_interval['point_per_1000']} vs {b.ehs_interval['point_per_1000']}")
    ok &= _check("same seed -> identical T_rect median series",
                 np.allclose(a.t_rect_median, b.t_rect_median, rtol=0, atol=0))
    ok &= _check("same seed -> identical CO_reserve median series",
                 np.allclose(a.co_reserve_median, b.co_reserve_median, rtol=0, atol=0))
    # A DIFFERENT seed must still give a different answer -- otherwise the
    # ensemble has stopped varying at all, which would be its own bug.
    ok &= _check("different seed -> genuinely different result (ensemble still varies)",
                 not np.allclose(a.t_rect_median, c.t_rect_median, rtol=0, atol=0))
    return ok


def test_zone_episode_classification() -> bool:
    """zone_episode()'s three real patterns, plus the near-miss case
    found while building the Word report (2026-08-16): T_rect and
    CO_reserve can EACH cross their own threshold at some point in a
    trace without ever doing so AT THE SAME timestep -- two separate
    line panels both crossing their threshold looks, at a glance, like
    the conjunctive zone was reached, but it wasn't. This is exactly
    the distinction the conjunctive criterion exists to enforce (see
    Veltmeijer's finding that T_rect alone is too loose a criterion),
    so a regression here would silently reintroduce that looseness."""
    print("zone_episode() classification, including the near-miss case")
    ok = True

    self_recovered = {"t": [38, 40.6, 40.6, 39.5, 39.0], "c": [3, -0.5, -0.3, 1.0, 2.0],
                       "min": [0, 20, 30, 40, 50], "stopped_at": 50}
    r = zone_episode(self_recovered)
    ok &= _check("self-recovered during race",
                 r is not None and r["exited_during_race"] and not r["in_zone_at_finish"])

    still_in_at_finish = {"t": [38, 40.6, 40.7, 40.8, 41.0, 41.0], "c": [3, -0.2, -0.5, -0.9, 4.0, 4.5],
                          "min": [0, 20, 40, 50, 60, 70], "stopped_at": 50}
    r = zone_episode(still_in_at_finish)
    ok &= _check("still in zone at finish", r is not None and r["in_zone_at_finish"])

    postfinish_only = {"t": [38, 39, 39.5, 41.2, 41.5], "c": [3, 2.5, 2.0, -0.3, -0.8],
                       "min": [0, 25, 50, 60, 70], "stopped_at": 50}
    r = zone_episode(postfinish_only)
    ok &= _check("entered only post-finish",
                 r is not None and r["entered_only_postfinish"] and not r["entered_during_race"])

    never_enters = {"t": [38, 39, 39.5], "c": [3, 2.5, 2.0], "min": [0, 25, 50], "stopped_at": 50}
    ok &= _check("never enters zone -> None", zone_episode(never_enters) is None)

    # THE NEAR-MISS CASE: T_rect peaks at 40.8 (index 1), CO_reserve
    # dips to -0.6 (index 3) -- both individually cross their threshold,
    # but never on the same index. Must classify as "never entered".
    near_miss = {"t": [38.0, 40.8, 39.0, 38.5], "c": [3.0, 1.0, 0.5, -0.6],
                "min": [0, 20, 40, 60], "stopped_at": 60}
    r = zone_episode(near_miss)
    ok &= _check("independent (non-simultaneous) extremes do NOT count as entering the zone",
                 r is None, f"got {r}")
    return ok


def test_full_pipeline_with_mocked_weather() -> bool:
    """End-to-end run_individual_assessment(), with fetch_scenario_weather
    monkeypatched to a synthetic-but-realistic weather_df (tz-aware index,
    T_air_urban/MRT/WBGT/UTCI + the other columns build_interp_data needs)
    instead of hitting the network. This is the closest this suite can get
    to a real run without network access, and is the only test that
    exercises the progress callback, meteo_timeseries, and
    _extended_bands all wired together as the UI actually calls them.

    Regression coverage: the progress-callback budget bug found while
    building this test (the post-loop "summarising" step reported 0.99
    right after the last ensemble member had already reported 1.0 --
    a visible backward tick in the Streamlit progress bar) is pinned by
    the monotonicity assertion below.
    """
    print("Full pipeline, mocked weather (progress + meteo + extended bands + storage)")
    ok = True

    tz = "Europe/Amsterdam"
    hours = pd.date_range("2026-05-31 06:00", periods=14, freq="h").tz_localize(tz)
    n = len(hours)
    weather_df = pd.DataFrame({
        "T_air_urban": 18 + 6 * np.sin(np.linspace(0, np.pi, n)),
        "MRT": 20 + 10 * np.sin(np.linspace(0, np.pi, n)),
        "WBGT": 16 + 5 * np.sin(np.linspace(0, np.pi, n)),
        "UTCI": 17 + 6 * np.sin(np.linspace(0, np.pi, n)),
        "wind_10m": np.full(n, 3.0), "RH": np.full(n, 55.0), "cloud_cover": np.full(n, 20.0),
        "pressure": np.full(n, 1013.0), "solar_radiation": np.full(n, 500.0),
        "solar_elevation": np.full(n, 45.0), "T_globe": np.full(n, 25.0),
    }, index=hours)
    fake_city = {"name": "Utrecht", "country": "Netherlands",
                 "latitude": 52.09, "longitude": 5.12, "timezone": tz}

    import individual_engine as ie
    original_fetch = ie.fetch_scenario_weather
    ie.fetch_scenario_weather = lambda scenario: (weather_df, fake_city, 52.09, 5.12, tz)
    try:
        inputs = PersonalInputs(height_m=1.78, weight_kg=78.0, age=52, gender="male",
                                 expected_pace_min_per_km=5.5, nsaid_use=False,
                                 drinks_readily=True, heat_acclimatized=False)
        scenario = EventScenario(location_query="Utrecht",
                                  start_local=pd.Timestamp("2026-05-31 10:30"),
                                  duration_minutes=100.0, use_historical=False)
        calls = []
        result = ie.run_individual_assessment(
            inputs, scenario, n_ensemble=15,
            progress_callback=lambda frac, text: calls.append((frac, text)),
            random_seed=3,
        )
    finally:
        ie.fetch_scenario_weather = original_fetch

    fracs = [c[0] for c in calls]
    ok &= _check("progress reaches 0 at start and 1.0 at end",
                 fracs[0] <= 0.06 and fracs[-1] == 1.0, f"{fracs[0]}..{fracs[-1]}")
    ok &= _check("progress never ticks backward (regression: post-loop step "
                 "used to report less than the last ensemble step)",
                 all(fracs[i] <= fracs[i + 1] for i in range(len(fracs) - 1)))

    ok &= _check("meteo arrays present and equal length",
                 len(result.meteo["t_air"]) == len(result.meteo["wbgt"])
                 == len(result.meteo["utci"]) == len(result.meteo["mrt"]) > 0)

    race_minutes = [m for m, p in zip(result.minutes, result.phase) if p == "race"]
    pf_minutes = [m for m, p in zip(result.minutes, result.phase) if p == "postfinish"]
    ok &= _check("both race and post-finish phases present", bool(race_minutes) and bool(pf_minutes))
    ok &= _check("post-finish minutes start at/after median_stop_minute",
                 min(pf_minutes) >= result.median_stop_minute)
    ok &= _check("minutes axis is monotonically non-decreasing",
                 all(result.minutes[i] <= result.minutes[i + 1]
                     for i in range(len(result.minutes) - 1)))

    path = store.save_assessment("__test_pipeline__", scenario, result, include_traces=False)
    s2, a2 = store.load_assessment(path)
    ok &= _check("full round-trip preserves minutes/phase/meteo",
                 a2.minutes == result.minutes and a2.phase == result.phase
                 and np.allclose(a2.meteo["t_air"], result.meteo["t_air"]))
    path.unlink(missing_ok=True)
    return ok


def test_no_missing_required_args() -> bool:
    """Generic signature-compatibility check: every required keyword of
    process_weather_data() must appear in fetch_scenario_weather()'s
    source. Re-run this any time Thermopoulos_Data_Engine.py's function
    signatures change -- it will fail loudly instead of only failing at
    runtime in front of a user."""
    print("Signature compatibility: fetch_scenario_weather vs process_weather_data")
    sig = inspect.signature(process_weather_data)
    required = [p.name for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty and p.name != "df"]
    src = inspect.getsource(fetch_scenario_weather)
    missing = [p for p in required if p not in src]
    return _check("all required kwargs referenced in fetch_scenario_weather",
                  not missing, f"required={required}, missing={missing}")


def test_storage_roundtrip() -> bool:
    print("local_storage round-trips (profile + assessment incl. terrain_key)")
    ok = True

    inp = PersonalInputs(height_m=1.78, weight_kg=75.0, age=54, gender="male",
                          expected_pace_min_per_km=5.8, nsaid_use=False,
                          drinks_readily=True, heat_acclimatized=False,
                          known_vo2max=48.5)
    store.save_profile("__test_koos__", inp)
    loaded = store.load_profile("__test_koos__")
    ok &= _check("profile fields survive round-trip", loaded == inp)

    scenario = EventScenario(location_query="Amsterdam",
                              start_local=pd.Timestamp("2024-09-22 10:30"),
                              duration_minutes=100.0, use_historical=True,
                              terrain_key="6")
    fake = IndividualAssessment(
        n_ensemble=1,
        minutes=[0.0, 10.0, 100.0, 110.0], phase=["race", "race", "postfinish", "postfinish"],
        median_stop_minute=100.0,
        t_rect_median=np.array([37.0, 38.0, 38.5, 38.2]), t_rect_lo=np.array([36.5, 37.5, 38.0, 37.8]),
        t_rect_hi=np.array([37.5, 38.5, 39.0, 38.6]),
        co_reserve_median=np.array([3.0, 2.5, 4.0, 4.5]), co_reserve_lo=np.array([2.5, 2.0, 3.5, 4.0]),
        co_reserve_hi=np.array([3.5, 3.0, 4.5, 5.0]),
        conjunction_fraction=0.0, ehe_fraction=0.0, ehe_dose_mean=0.0, ehe_dose_among_hits=0.0,
        eac_fraction=0.0, eac_dose_mean=0.0, eac_dose_among_hits=0.0,
        ehs_interval={"point_per_1000": 1.0, "lo_per_1000": 0.5, "hi_per_1000": 1.5, "alpha": 0.05},
        mean_t_air_c=20.0, city_name="Amsterdam",
        meteo={"time": [pd.Timestamp("2024-09-22 10:30")], "t_air": np.array([20.0]),
               "wbgt": np.array([17.0]), "utci": np.array([18.0]), "mrt": np.array([22.0])},
        all_traces=[],
    )
    path = store.save_assessment("__test_koos__", scenario, fake)
    s2, a2 = store.load_assessment(path)
    ok &= _check("terrain_key survives round-trip", s2.terrain_key == "6", s2.terrain_key)
    ok &= _check("assessment arrays survive round-trip",
                 np.allclose(a2.t_rect_median, fake.t_rect_median))

    store.delete_profile("__test_koos__")
    path.unlink(missing_ok=True)
    return ok


def test_personal_ensemble_pipeline() -> bool:
    """Everything downstream of the network call: profile-building,
    JOS-3/CVR simulation, conjunction check, dose + interval -- run on
    hand-built weather data so it needs no network access."""
    print("Personal ensemble pipeline (synthetic weather, no network)")
    ok = True

    n_steps = 11
    times = pd.date_range("2026-05-31 10:30", periods=n_steps, freq="10min")
    interp_data = [{"time": t, "temp": 21.0 + 4 * np.sin(np.pi * i / (n_steps - 1)),
                     "wind": 3.0, "rh": 55.0, "clouds": 30.0, "pressure": 1013.0,
                     "ghi": 500.0, "solar_elevation": 45.0,
                     "globe_temp": 28.0, "mrt": 30.0}
                    for i, t in enumerate(times)]
    mean_t_air = float(np.mean([r["temp"] for r in interp_data]))

    inputs = PersonalInputs(height_m=1.78, weight_kg=75.0, age=54, gender="male",
                             expected_pace_min_per_km=5.8, nsaid_use=False,
                             drinks_readily=True, heat_acclimatized=False)
    inputs.validate()
    met_ref = _daniels_gilbert_vo2_at_pace(5.8) / VO2MAX_TO_MET_FACTOR

    rng = np.random.default_rng(3)
    traces = []
    for _ in range(20):
        profile = _build_profile(inputs, rng)
        res = calculate_indices_jos3_adult(interp_data, 52.0, 5.0, met_ref, 0.2, profile, 0.5, 0.0)
        traces.append(res)
    ok &= _check("all ensemble members produced a full trace",
                 all(len(t) == n_steps for t in traces))

    doses = [cumulative_deficit_dose(t) for t in traces]
    ok &= _check("doses are non-negative", all(d >= 0 for d in doses))

    r = unc.ehs_interval(np.array(doses), mean_t_air, n_boot=500)
    ok &= _check("interval brackets the point estimate",
                 r["lo_per_1000"] <= r["point_per_1000"] <= r["hi_per_1000"])
    return ok


def test_ehe_eac_criteria() -> bool:
    """The conjunctive collapse criterion (T_rect>39.5 AND CO_reserve<0,
    same timestep) must be strictly more sensitive than the EHS
    criterion (>=40.5 / <=0), and must enforce simultaneity -- the
    property that distinguishes it from hestia_model.py's existing
    p_collapse logistic, which reads max(T_rect) and min(CO_reserve)
    independently across the whole trace."""
    print("EHE / EAC criteria")
    from individual_engine import (conjunctive_hit, ehe_dose, eac_hit,
                                    EHE_T_THRESHOLD, EHE_CO_THRESHOLD,
                                    EHS_T_THRESHOLD, EHS_CO_THRESHOLD)
    ok = True

    def mk(ts, cs):
        rows = [{"t_rect": t, "co_reserve": c} for t, c in zip(ts, cs)]
        rows[-1]["t_rect_series_postfinish"] = []
        rows[-1]["co_reserve_series_postfinish"] = []
        return rows

    # Simultaneous mild conjunction: collapse yes, EHS no
    mild = mk([38.0, 39.8, 39.9], [3.0, -0.2, -0.1])
    ok &= _check("mild simultaneous hit -> collapse YES",
                 conjunctive_hit(mild, EHE_T_THRESHOLD, EHE_CO_THRESHOLD, strict=True))
    ok &= _check("mild simultaneous hit -> EHS NO",
                 not conjunctive_hit(mild, EHS_T_THRESHOLD, EHS_CO_THRESHOLD, strict=False))

    # NON-simultaneous extremes: neither criterion may fire. This is the
    # exact case hestia_model.py's p_collapse WOULD count (max T=40.9,
    # min CO=-0.5) even though they never co-occur.
    apart = mk([38.0, 40.9, 39.0, 38.2], [4.0, 2.5, 1.0, -0.5])
    ok &= _check("non-simultaneous extremes -> collapse NO (simultaneity enforced)",
                 not conjunctive_hit(apart, EHE_T_THRESHOLD, EHE_CO_THRESHOLD, strict=True))
    ok &= _check("non-simultaneous extremes -> EHS NO",
                 not conjunctive_hit(apart, EHS_T_THRESHOLD, EHS_CO_THRESHOLD, strict=False))

    # Strictness: exactly at the threshold must NOT fire (strict >/<)
    edge = mk([39.5, 39.5], [0.0, 0.0])
    ok &= _check("exactly at 39.5/0.0 -> collapse NO (strict inequalities)",
                 not conjunctive_hit(edge, EHE_T_THRESHOLD, EHE_CO_THRESHOLD, strict=True))

    # Any EHS hit must also be a collapse hit (nesting), since 40.5>39.5
    # and <=0 overlaps <0 except exactly at 0.
    ehs_case = mk([40.6], [-0.3])
    ok &= _check("an EHS hit is also a collapse hit (criteria nest)",
                 conjunctive_hit(ehs_case, EHS_T_THRESHOLD, EHS_CO_THRESHOLD, strict=False)
                 and conjunctive_hit(ehs_case, EHE_T_THRESHOLD, EHE_CO_THRESHOLD, strict=True))

    ok &= _check("collapse dose is 0 when criterion never met", ehe_dose(apart) == 0.0)
    ok &= _check("collapse dose > 0 when criterion met", ehe_dose(mild) > 0.0)
    return ok


def test_eac_window_scoping() -> bool:
    """EAC must fire ONLY on post-finish CO_reserve<0, with no
    temperature condition, and EHE must fire ONLY during the race.
    Scoping them identically would merge three distinct clinical
    entities into one number (Asplund: collapse DURING a race points to
    a different, more serious cause)."""
    print("EHE/EAC window scoping")
    from individual_engine import (eac_hit, eac_dose, conjunctive_hit,
                                    EHE_T_THRESHOLD, EHE_CO_THRESHOLD)
    ok = True

    # Cool runner, but CO_reserve goes negative AFTER finishing.
    cool_pf = [{"t_rect": 38.5, "co_reserve": 2.0},
               {"t_rect": 38.4, "co_reserve": 1.8}]
    cool_pf[-1]["t_rect_series_postfinish"] = [38.2, 38.0]
    cool_pf[-1]["co_reserve_series_postfinish"] = [-0.4, -0.6]
    ok &= _check("EAC fires post-finish with no temperature condition",
                 eac_hit(cool_pf))
    ok &= _check("EAC dose > 0 in that case", eac_dose(cool_pf) > 0)
    ok &= _check("EHE does NOT fire (race window is clean)",
                 not conjunctive_hit(cool_pf, EHE_T_THRESHOLD, EHE_CO_THRESHOLD,
                                      strict=True, window="race"))

    # Hot runner in trouble DURING the race, fine afterwards.
    hot_race = [{"t_rect": 39.9, "co_reserve": -0.5},
                {"t_rect": 39.8, "co_reserve": -0.3}]
    hot_race[-1]["t_rect_series_postfinish"] = [39.5, 39.2]
    hot_race[-1]["co_reserve_series_postfinish"] = [5.0, 6.0]
    ok &= _check("EHE fires during the race",
                 conjunctive_hit(hot_race, EHE_T_THRESHOLD, EHE_CO_THRESHOLD,
                                  strict=True, window="race"))
    ok &= _check("EAC does NOT fire (post-finish reserve is healthy)",
                 not eac_hit(hot_race))
    return ok


if __name__ == "__main__":
    results = [
        test_timezone_localization(),
        test_reproducibility_same_seed(),
        test_zone_episode_classification(),
        test_ehe_eac_criteria(),
        test_eac_window_scoping(),
        test_full_pipeline_with_mocked_weather(),
        test_no_missing_required_args(),
        test_storage_roundtrip(),
        test_personal_ensemble_pipeline(),
    ]
    print()
    print(f"{sum(results)}/{len(results)} test groups passed")
    raise SystemExit(0 if all(results) else 1)
