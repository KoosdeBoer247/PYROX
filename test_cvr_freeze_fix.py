# -*- coding: utf-8 -*-
"""
test_cvr_freeze_fix.py
========================
Permanent regression test for the CO_reserve-goes-NaN-after-DNF bug
found 2026-08-16 while checking a personal-app Word report against its
live run.

ROOT CAUSE: calculate_indices_jos3_adult()'s main loop, once a
participant hits rpe_total>=19.5 (runner_stopped=True), freezes t_rect
by copying the previous row forward ({**results[-1], ...}) but used to
skip appending to jos3_cvr_series (only done in the "fresh computation"
branch, which the frozen path's `continue` never reaches). The post-
loop link_cvr_to_jos3() call therefore produced a CO_reserve series
SHORTER than the race itself -- every frozen row's co_reserve stayed at
its NaN placeholder, even though t_rect was correctly frozen and valid.

IMPACT: cumulative_deficit_dose() and the conjunctive-criterion check
both require non-NaN co_reserve to count a timestep. Any participant
who froze with t_rect>=40.5 (a real possibility -- exhaustion/high RPE
and high core temperature are not mutually exclusive) was silently
EXCLUDED from dose/conjunction accounting for the remainder of the
race, regardless of what their true co_reserve would have been. This
can only cause UNDER-counting of EHS risk, never over-counting -- the
fix can only add previously-invisible conjunction events, never remove
real ones.

This module tests the CORE physiology engine (hestia_model.py), shared
by every PYROX app (population and personal alike) -- not just
individual_engine.py, which is where the bug was first noticed.

Run standalone:  PYTHONPATH=. python3 test_cvr_freeze_fix.py
"""

import numpy as np
import pandas as pd

from hestia_model import (
    calculate_indices_jos3_adult, AdultParticipantProfile,
    _daniels_gilbert_vo2_at_pace, VO2MAX_TO_MET_FACTOR,
)


def _check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return cond


def _hot_long_scenario(n_steps=30):
    """A scenario hot/long enough that some ensemble members reliably
    hit rpe_total>=19.5 (runner_stopped) before the window ends --
    needed to exercise the freeze path at all."""
    times = pd.date_range("2026-07-15 12:00", periods=n_steps, freq="10min")
    return [
        {"time": t, "temp": 31.0, "wind": 1.0, "rh": 65.0, "clouds": 5.0,
         "pressure": 1013.0, "ghi": 850.0, "solar_elevation": 62.0,
         "globe_temp": 46.0, "mrt": 53.0}
        for t in times
    ]


def test_no_nan_co_reserve_after_freeze() -> bool:
    """Across a batch of runs designed to trigger the freeze condition
    for at least some ensemble members, NO frozen row should ever have
    a NaN co_reserve while t_rect is a valid (frozen) number -- that
    combination is exactly the bug's signature."""
    print("No NaN co_reserve after a participant freezes (runner_stopped)")
    interp_data = _hot_long_scenario()
    met_ref = _daniels_gilbert_vo2_at_pace(4.5) / VO2MAX_TO_MET_FACTOR

    rng = np.random.default_rng(7)
    n_frozen_participants = 0
    n_frozen_rows_checked = 0
    bad = []
    for _ in range(60):
        profile = AdultParticipantProfile(
            height=1.75 + rng.normal(0, 0.03), weight=70 + rng.normal(0, 8),
            age=int(np.clip(30 + rng.normal(0, 10), 18, 75)), gender=rng.choice(["male", "female"]),
            body_fat_pct=20.0, vo2max=45.0 + rng.normal(0, 5),
            pct_vo2max=float(np.clip(rng.normal(0.75, 0.1), 0.3, 0.95)),
            temp_variation=0.0, rh_variation=0.0, mf_score=0.5,
            sweat_factor=1.0, thirst_threshold=1.8, kp_pacing=0.1,
            nsaid_gebruik=False, wind_angle_rad=0.0,
        )
        res = calculate_indices_jos3_adult(
            interp_data, 52.0, 5.0, met_ref, 0.2, profile, 0.3, 0.0)
        stopped_rows = [r for r in res if r.get("stopped")]
        if stopped_rows:
            n_frozen_participants += 1
        for r in stopped_rows:
            n_frozen_rows_checked += 1
            t, c = r.get("t_rect"), r.get("co_reserve")
            t_valid = t is not None and not np.isnan(t)
            c_is_nan = c is None or np.isnan(c)
            if t_valid and c_is_nan:
                bad.append((t, c))

    ok = _check(f"{n_frozen_participants}/60 participants triggered the freeze path "
                f"({n_frozen_rows_checked} frozen rows total) -- scenario actually exercises the fix",
                n_frozen_participants > 0)
    ok &= _check("zero frozen rows with valid t_rect but NaN co_reserve",
                 len(bad) == 0, f"{len(bad)} bad rows found: {bad[:3]}")
    return ok


def test_frozen_co_reserve_matches_freeze_moment() -> bool:
    """When co_reserve IS frozen, it should equal the value at the exact
    moment freezing began (mirroring t_rect's own freeze semantics) --
    not some other fallback number. Uses a single deterministic profile
    likely to freeze given the hot/long scenario."""
    print("Frozen co_reserve equals the value at the freeze moment (like t_rect)")
    interp_data = _hot_long_scenario()
    met_ref = _daniels_gilbert_vo2_at_pace(4.5) / VO2MAX_TO_MET_FACTOR
    rng = np.random.default_rng(7)  # same seed as test_no_nan_co_reserve_after_freeze
    res = None
    for _ in range(60):
        profile = AdultParticipantProfile(
            height=1.75 + rng.normal(0, 0.03), weight=70 + rng.normal(0, 8),
            age=int(np.clip(30 + rng.normal(0, 10), 18, 75)), gender=rng.choice(["male", "female"]),
            body_fat_pct=20.0, vo2max=45.0 + rng.normal(0, 5),
            pct_vo2max=float(np.clip(rng.normal(0.75, 0.1), 0.3, 0.95)),
            temp_variation=0.0, rh_variation=0.0, mf_score=0.5,
            sweat_factor=1.0, thirst_threshold=1.8, kp_pacing=0.1,
            nsaid_gebruik=False, wind_angle_rad=0.0,
        )
        candidate = calculate_indices_jos3_adult(
            interp_data, 52.0, 5.0, met_ref, 0.2, profile, 0.3, 0.0)
        if any(r.get("stopped") for r in candidate):
            res = candidate
            break
    stopped_idx = [i for i, r in enumerate(res)] if res is None else [i for i, r in enumerate(res) if r.get("stopped")]
    if res is None or len(stopped_idx) < 2:
        print("  [SKIP] this run did not produce enough frozen rows -- inconclusive, not a failure")
        return True
    # stopped_idx[0] is the LAST FRESH computation (the step where RPE
    # first crossed 19.5 -- runner_stopped is set mid-iteration, so that
    # step's own physiology is still a genuine calculation, not a copy).
    # The frozen COPIES begin at stopped_idx[1] onward -- those are what
    # must match stopped_idx[0]'s values, not the row before it.
    freeze_t = res[stopped_idx[0]]["t_rect"]
    freeze_c = res[stopped_idx[0]]["co_reserve"]
    ok = True
    for i in stopped_idx[1:]:
        row_t, row_c = res[i]["t_rect"], res[i]["co_reserve"]
        if row_t != freeze_t:
            ok = False
        if row_c is None or np.isnan(row_c) or abs(row_c - freeze_c) > 1e-9:
            ok = False
    ok = _check(f"all {len(stopped_idx) - 1} frozen-copy rows carry "
                f"t_rect={freeze_t:.2f}, co_reserve={freeze_c:.3f} unchanged from the freeze moment",
                ok)
    return ok


def test_unaffected_participants_are_unchanged() -> bool:
    """The fix only adds code inside the `runner_stopped and i > 0`
    branch. A participant who never freezes takes a code path that
    branch cannot reach, so their trace must be identical to what it
    was before this fix -- checked here via simple determinism (same
    inputs -> same outputs), which is the property the fix must not
    disturb for the unaffected majority."""
    print("Never-frozen participants: deterministic, unaffected by the fix")
    interp_data = [
        {"time": t, "temp": 18.0, "wind": 3.0, "rh": 55.0, "clouds": 30.0,
         "pressure": 1013.0, "ghi": 300.0, "solar_elevation": 30.0,
         "globe_temp": 21.0, "mrt": 22.0}
        for t in pd.date_range("2026-05-01 10:00", periods=11, freq="10min")
    ]
    met_ref = _daniels_gilbert_vo2_at_pace(6.0) / VO2MAX_TO_MET_FACTOR
    profile = AdultParticipantProfile(
        height=1.75, weight=70.0, age=35, gender="male", body_fat_pct=18.0,
        vo2max=50.0, pct_vo2max=0.5, temp_variation=0.0, rh_variation=0.0,
        mf_score=0.5, sweat_factor=1.0, thirst_threshold=1.8, kp_pacing=0.1,
        nsaid_gebruik=False, wind_angle_rad=0.0,
    )
    res_a = calculate_indices_jos3_adult(interp_data, 52.0, 5.0, met_ref, 0.5, profile, 0.5, 0.0)
    res_b = calculate_indices_jos3_adult(interp_data, 52.0, 5.0, met_ref, 0.5, profile, 0.5, 0.0)
    ok = _check("no participant froze in this mild scenario (sanity)",
               not any(r.get("stopped") for r in res_a))
    ok &= _check("identical inputs -> bit-identical t_rect/co_reserve series",
                all(a["t_rect"] == b["t_rect"] and
                    (a["co_reserve"] == b["co_reserve"]
                     or (np.isnan(a["co_reserve"]) and np.isnan(b["co_reserve"])))
                    for a, b in zip(res_a, res_b)))
    return ok


if __name__ == "__main__":
    results = [
        test_no_nan_co_reserve_after_freeze(),
        test_frozen_co_reserve_matches_freeze_moment(),
        test_unaffected_participants_are_unchanged(),
    ]
    print()
    print(f"{sum(results)}/{len(results)} test groups passed")
    raise SystemExit(0 if all(results) else 1)
