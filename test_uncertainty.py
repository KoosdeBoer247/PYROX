"""Acceptance tests for uncertainty.py.

Run standalone (no streamlit needed):  python3 test_uncertainty.py
"""

import numpy as np

import uncertainty as u


def _t_sf_two_sided(t: float, df: int) -> float:
    """Two-sided tail probability of Student's t, exact for integer df,
    using the continued-fraction incomplete beta. Kept local to the test
    file so the project picks up no new runtime dependency."""
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b), Lentz continued fraction."""
    from math import lgamma, exp
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = lgamma(a) + lgamma(b) - lgamma(a + b)
    front = exp(a * np.log(x) + b * np.log(1 - x) - lbeta) / a
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betainc(b, a, 1 - x)
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 300):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + num / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-12:
            break
    return front * (f - 1.0)


def _check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return cond


def test_falmouth_reconstruction() -> bool:
    """The reconstructed residual scatter must reproduce the paper's own
    reported significance. If this fails, the SE reconstruction is wrong
    and every interval built on it is wrong too."""
    print("Falmouth regression reconstruction")
    ok = True
    t_stat = np.sqrt(u._FALM_R2 * (u._FALM_N - 2) / (1 - u._FALM_R2))
    ok &= _check("implied t-statistic ~4.34", abs(t_stat - 4.34) < 0.05, f"{t_stat:.3f}")
    # Paper reports P = .001. Exact two-sided p for Student's t on n-2
    # df, via the regularised incomplete beta -- no scipy (not a declared
    # dependency of this project) and no normal approximation, which is
    # not adequate at 10 df.
    ok &= _check("implied P consistent with published .001",
                 0.0005 < _t_sf_two_sided(t_stat, u._FALM_N - 2) < 0.005,
                 f"P={_t_sf_two_sided(t_stat, u._FALM_N - 2):.5f}")
    # SE must widen away from the fit centroid, never shrink.
    se_centre = u.falmouth_log_se(u._FALM_T_BAR)
    se_edge = u.falmouth_log_se(u._FALM_T_MAX)
    se_far = u.falmouth_log_se(15.0)
    ok &= _check("SE minimal at centroid", se_centre < se_edge < se_far,
                 f"{se_centre:.3f} < {se_edge:.3f} < {se_far:.3f}")
    ok &= _check("extrapolation flagged below fitted range",
                 u.falmouth_extrapolation_factor(15.4) > 5.0)
    ok &= _check("no extrapolation flagged inside range",
                 u.falmouth_extrapolation_factor(24.0) == 0.0)
    return ok


def test_point_estimate_matches_app() -> bool:
    """The interval's point estimate must equal what the app already
    reports, or the interval is around a different number than the one
    on screen."""
    print("Point estimate agrees with _dose_response_pct_patched")
    a, b = u._dose_response_constants()
    doses = np.r_[np.linspace(0.5, 25, 40), np.zeros(160)]
    t = 23.2
    floor = u._FALM_A * np.exp(u._FALM_B * t) / 1000.0
    probs = np.where(doses > 0, 1 / (1 + np.exp(-(a + b * doses))), floor)
    expected = 1000.0 * probs.mean()
    got = u.ehs_interval(doses, t, n_boot=200)["point_per_1000"]
    return _check("matches to 1e-9", abs(expected - got) < 1e-9,
                  f"{expected:.6f} vs {got:.6f}")


def test_interval_properties() -> bool:
    """Structural properties the interval must always have."""
    print("Interval structure")
    ok = True
    doses = np.r_[np.random.default_rng(0).normal(13, 3, 70).clip(0.5), np.zeros(930)]
    r = u.ehs_interval(doses, 23.2, n_boot=3000)
    ok &= _check("point inside interval",
                 r["lo_per_1000"] <= r["point_per_1000"] <= r["hi_per_1000"])
    ok &= _check("combined at least as wide as sampling alone",
                 (r["hi_per_1000"] - r["lo_per_1000"])
                 >= 0.98 * (r["sampling_hi"] - r["sampling_lo"]))
    ok &= _check("anchor-only interval is narrow when dose dominates",
                 (r["anchor_hi"] - r["anchor_lo"])
                 < (r["sampling_hi"] - r["sampling_lo"]))
    ok &= _check("bounds non-negative", r["lo_per_1000"] >= 0)
    tight = u.ehs_interval(doses, 23.2, n_boot=3000, alpha=0.50)
    ok &= _check("50% interval narrower than 95%",
                 (tight["hi_per_1000"] - tight["lo_per_1000"])
                 < (r["hi_per_1000"] - r["lo_per_1000"]))
    return ok


def test_degenerate_cases() -> bool:
    """The two regimes that actually occur in practice and are most
    likely to mislead a reader."""
    print("Degenerate cases")
    ok = True

    # All doses zero: the estimate IS the floor, exactly.
    r0 = u.ehs_interval(np.zeros(500), 14.0, n_boot=1000)
    ok &= _check("zero-dose point equals floor",
                 abs(r0["point_per_1000"] - r0["floor_per_1000"]) < 1e-9)
    ok &= _check("zero-dose flags 'no participant reached dose'",
                 any("non-zero dose" in c for c in u.interval_caveats(r0)))
    ok &= _check("zero-dose interval is anchor-driven",
                 abs((r0["hi_per_1000"] - r0["lo_per_1000"])
                     - (r0["anchor_hi"] - r0["anchor_lo"])) < 0.05,
                 "sampling adds nothing when every participant is identical")

    # One saturated participant: the Leiden 2026 case.
    r1 = u.ehs_interval(np.r_[40.0, np.zeros(999)], 15.4, n_boot=3000)
    ok &= _check("single participant dominates the estimate",
                 r1["top_participant_share"] > 0.8,
                 f"{r1['top_participant_share']:.0%}")
    ok &= _check("interval spans more than an order of magnitude",
                 r1["hi_per_1000"] / max(r1["lo_per_1000"], 1e-9) > 10,
                 f"{r1['lo_per_1000']:.2f}-{r1['hi_per_1000']:.2f}")
    ok &= _check("small-sample caveat raised",
                 any("individuals rather than the field" in c
                     for c in u.interval_caveats(r1)))
    return ok


def test_caveats_always_lead_with_the_limitation() -> bool:
    """The slope-uncertainty disclaimer is the whole point. It must be
    present in every case, including the ones that look statistically
    healthy -- a tight interval around a wrong number is the failure
    mode this module exists to prevent."""
    print("Mandatory caveat")
    ok = True
    for label, doses, t in [
        ("many-dose", np.r_[np.random.default_rng(2).normal(13, 3, 200).clip(0.5),
                            np.zeros(800)], 25.0),
        ("zero-dose", np.zeros(300), 12.0),
        ("few-dose", np.r_[30.0, 28.0, np.zeros(998)], 20.0),
    ]:
        c = u.interval_caveats(u.ehs_interval(doses, t, n_boot=500))
        ok &= _check(f"{label}: lower-bound disclaimer present and first",
                     bool(c) and "lower bound on total uncertainty" in c[0])
    return ok


def test_reproducibility() -> bool:
    print("Reproducibility")
    d = np.r_[np.random.default_rng(3).normal(13, 3, 50).clip(0.5), np.zeros(950)]
    a = u.ehs_interval(d, 23.0, n_boot=1000, random_seed=7)
    b = u.ehs_interval(d, 23.0, n_boot=1000, random_seed=7)
    return _check("same seed gives identical bounds",
                  a["lo_per_1000"] == b["lo_per_1000"]
                  and a["hi_per_1000"] == b["hi_per_1000"])


if __name__ == "__main__":
    results = [
        test_falmouth_reconstruction(),
        test_point_estimate_matches_app(),
        test_interval_properties(),
        test_degenerate_cases(),
        test_caveats_always_lead_with_the_limitation(),
        test_reproducibility(),
    ]
    print()
    print(f"{sum(results)}/{len(results)} test groups passed")
    raise SystemExit(0 if all(results) else 1)
