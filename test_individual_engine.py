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
    fetch_scenario_weather, _build_profile,
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
        conjunction_fraction=0.0,
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


if __name__ == "__main__":
    results = [
        test_timezone_localization(),
        test_full_pipeline_with_mocked_weather(),
        test_no_missing_required_args(),
        test_storage_roundtrip(),
        test_personal_ensemble_pipeline(),
    ]
    print()
    print(f"{sum(results)}/{len(results)} test groups passed")
    raise SystemExit(0 if all(results) else 1)
