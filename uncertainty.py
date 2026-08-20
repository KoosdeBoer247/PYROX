"""Uncertainty quantification for the headline EHS estimate.

WHAT THIS COVERS -- and, more importantly, what it does NOT.

The headline figure is 1000 * mean(p_i), where p_i is a per-participant
EHS probability: the fitted logistic of that participant's cumulative
deficit dose when dose>0, and Falmouth's temperature-only regression
value when dose==0 (see _dose_response_pct_patched in hestia_bridge).

Three separable uncertainties sit under that number:

  (1) MONTE-CARLO SAMPLING NOISE. The N simulated participants are a
      finite draw from the population distribution. Quantified here by
      bootstrap resampling of the participant-level probabilities.
      Assumption-free and correct.

  (2) ANCHOR UNCERTAINTY IN THE FLOOR. The dose==0 floor comes from
      DeMartini et al. 2014's published regression, fit on n=12 race-
      years with R^2=0.653. That fit has its own confidence band, which
      widens away from its calibration centroid. Reconstructed and
      propagated here (see falmouth_log_se).

  (3) SLOPE UNCERTAINTY IN THE DOSE-RESPONSE CURVE ITSELF. NOT COVERED,
      AND NOT COVERABLE. _DOSE_RESPONSE_A/B were fit jointly against
      five reference scenarios in which dose and ambient temperature are
      confounded (hestia_bridge documents this directly: dose only turns
      non-zero at the hot end because MET was held fixed). With one
      effective anchoring condition, the slope is not statistically
      identified -- there is no sampling model under which a coverage
      probability could be defined for it.

(3) is expected to DOMINATE (1) and (2) whenever a meaningful fraction
of participants have dose>0, because those participants carry almost all
of the probability mass and their probabilities come entirely from the
unidentified curve. The interval this module returns is therefore a
LOWER BOUND on total uncertainty, and must be labelled as such wherever
it is displayed. An interval that looks reassuringly tight around a
number that is wrong by an order of magnitude is worse than no interval
at all.

Report it as "sampling + anchor interval", never as "95% CI on the EHS
rate".
"""

from __future__ import annotations

import numpy as np

# =============================================================================
# Falmouth regression -- reconstructed uncertainty
# =============================================================================
#: DeMartini JK, Casa DJ, Belval LN, et al. J Athl Train. 2014;49(4):478-485.
#: Published fit: EHS per 1000 finishers = 0.004 * exp(0.250 * Tamb_C),
#: R^2 = 0.653, P = .001, n = 12 race-years, fitted range 21.3-27.7 C.
_FALM_A = 0.004
_FALM_B = 0.250
_FALM_R2 = 0.653
_FALM_N = 12
_FALM_T_MIN = 21.3
_FALM_T_MAX = 27.7

#: The paper reports R^2 and n but not the coefficient standard errors, so
#: the residual scatter is reconstructed. Centroid of the fitted
#: temperatures is taken as the midpoint of the reported range, and their
#: spread from the range via the expected range/SD ratio for n=12 normal
#: draws (~3.3). This is an assumption, isolated here so it can be
#: replaced if the underlying Table 1 values are ever digitised.
_FALM_T_BAR = 0.5 * (_FALM_T_MIN + _FALM_T_MAX)
_FALM_T_SD = (_FALM_T_MAX - _FALM_T_MIN) / 3.3

#: Cross-check on the reconstruction: the slope t-statistic implied by
#: R^2 and n is sqrt(R^2*(n-2)/(1-R^2)) = 4.34, giving P ~ .0015 --
#: consistent with the paper's reported P = .001. If that consistency
#: ever fails after editing the constants above, the reconstruction is
#: wrong and this module should not be trusted.


def _falmouth_residual_sd() -> float:
    """Residual SD of ln(EHS per 1000) about the fitted line."""
    t_stat = np.sqrt(_FALM_R2 * (_FALM_N - 2) / (1.0 - _FALM_R2))
    se_b = _FALM_B / t_stat
    return se_b * _FALM_T_SD * np.sqrt(_FALM_N - 1)


def falmouth_log_se(t_air_c: float) -> float:
    """Standard error, in log space, of the fitted Falmouth mean rate at
    ambient temperature `t_air_c`.

    Standard regression prediction-of-the-mean SE, widening with distance
    from the fit centroid. Note this quantifies only the uncertainty of
    the fitted line; it says nothing about whether extrapolating a
    7-mile road race's epidemiology to a marathon is valid at all, nor
    about extrapolation bias outside 21.3-27.7 C. Both remain
    unquantified assumptions.
    """
    s = _falmouth_residual_sd()
    sxx = (_FALM_N - 1) * _FALM_T_SD ** 2
    return float(s * np.sqrt(1.0 / _FALM_N + (t_air_c - _FALM_T_BAR) ** 2 / sxx))


def falmouth_extrapolation_factor(t_air_c: float) -> float:
    """How far outside the fitted range this temperature sits, in degrees.
    Zero inside the range. Purely informational -- used to decide whether
    to print a warning, not to widen the interval (extrapolation bias is
    not a variance and must not be smuggled in as one).
    """
    if t_air_c < _FALM_T_MIN:
        return float(_FALM_T_MIN - t_air_c)
    if t_air_c > _FALM_T_MAX:
        return float(t_air_c - _FALM_T_MAX)
    return 0.0


# =============================================================================
# The dose-response curve, without importing the app
# =============================================================================
def _dose_response_constants() -> tuple[float, float]:
    """(_DOSE_RESPONSE_A, _DOSE_RESPONSE_B) as currently defined in
    hestia_bridge.py.

    hestia_bridge imports streamlit at module level, so importing it
    outside a running app fails -- which would make this module
    untestable standalone, exactly when independent testing is most
    useful. Rather than keeping a second copy of the constants here
    (which would silently go stale the next time the curve is refit),
    the values are read out of the source file itself. If hestia_bridge
    is already imported (the normal in-app case) that module is used
    directly, so there is only ever one definition in play.
    """
    import sys
    mod = sys.modules.get("hestia_bridge")
    if mod is not None:
        return float(mod._DOSE_RESPONSE_A), float(mod._DOSE_RESPONSE_B)

    import ast
    import pathlib
    src = pathlib.Path(__file__).with_name("hestia_bridge.py")
    found: dict[str, float] = {}
    for node in ast.parse(src.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Name)
                        and tgt.id in ("_DOSE_RESPONSE_A", "_DOSE_RESPONSE_B")):
                    found[tgt.id] = float(ast.literal_eval(node.value))
    if len(found) != 2:
        raise RuntimeError(
            "Could not read _DOSE_RESPONSE_A/_DOSE_RESPONSE_B from "
            "hestia_bridge.py. Refusing to guess: pass dose_response_fn "
            "explicitly instead."
        )
    return found["_DOSE_RESPONSE_A"], found["_DOSE_RESPONSE_B"]


def _dose_response_curve():
    """The same logistic as hestia_bridge.dose_response_ehs_probability,
    built from that module's own constants."""
    a, b = _dose_response_constants()
    return lambda d: 1.0 / (1.0 + np.exp(-(a + b * np.asarray(d, dtype=float))))


# =============================================================================
# The interval
# =============================================================================
def ehs_interval(
    doses,
    mean_t_air_c: float,
    *,
    dose_response_fn=None,
    n_boot: int = 4000,
    alpha: float = 0.05,
    random_seed: int = 42,
    include_anchor: bool = True,
) -> dict:
    """Sampling + anchor interval around the headline EHS estimate.

    Parameters
    ----------
    doses
        Per-participant cumulative deficit doses -- i.e. the
        `cumulative_doses_all` array already present in the summary dict
        returned by run_quick_estimate / run_full_precision.
    mean_t_air_c
        Race-window mean air temperature -- `mean_t_air_race_window` from
        the same dict. Drives the dose==0 floor.
    dose_response_fn
        Defaults to hestia_bridge.dose_response_ehs_probability. Injectable
        so this module can be tested without importing the full bridge.
    include_anchor
        If False, returns the sampling-only interval. Useful for showing
        which of the two components dominates in a given scenario.

    Returns
    -------
    dict with per-1000 point estimate, interval bounds, the two
    components separately, and the diagnostics needed to judge whether
    the point estimate is a population feature or an artefact of a
    handful of individuals.

    Method
    ------
    Each bootstrap iteration resamples participants with replacement AND
    draws one shared multiplicative perturbation of the floor. The floor
    perturbation is applied per-iteration rather than per-participant
    because the regression uncertainty is a property of the fitted line,
    shared by every participant in a run -- treating it as independent
    per-participant noise would average it away and understate the
    interval.
    """
    if dose_response_fn is None:
        dose_response_fn = _dose_response_curve()

    doses = np.asarray(doses, dtype=float)
    n = doses.size
    if n == 0:
        return {"error": "no participants"}

    nonzero = doses > 0
    n_nonzero = int(nonzero.sum())

    floor_point = _FALM_A * np.exp(_FALM_B * mean_t_air_c) / 1000.0
    p_dose = np.where(nonzero, dose_response_fn(doses), 0.0)

    point = 1000.0 * float(np.mean(np.where(nonzero, p_dose, floor_point)))

    log_se = falmouth_log_se(mean_t_air_c) if include_anchor else 0.0
    rng = np.random.default_rng(random_seed)

    def _run(with_anchor: bool, with_sampling: bool) -> np.ndarray:
        out = np.empty(n_boot)
        for b in range(n_boot):
            idx = rng.integers(0, n, n) if with_sampling else np.arange(n)
            f = floor_point * np.exp(rng.normal(0.0, log_se)) if with_anchor else floor_point
            probs = np.where(nonzero[idx], p_dose[idx], f)
            out[b] = 1000.0 * probs.mean()
        return out

    lo_q, hi_q = 100 * alpha / 2, 100 * (1 - alpha / 2)
    combined = _run(include_anchor, True)
    sampling = _run(False, True)
    anchor = _run(include_anchor, False)

    # How much of the point estimate rests on the single most influential
    # participant. At the extreme (one saturated individual in an
    # otherwise floor-only field) this approaches 1.0, and the headline
    # figure is then a statement about that individual, not the field.
    contrib = np.where(nonzero, p_dose, floor_point)
    top_share = float(contrib.max() / contrib.sum()) if contrib.sum() > 0 else float("nan")

    return {
        "point_per_1000": point,
        "lo_per_1000": float(np.percentile(combined, lo_q)),
        "hi_per_1000": float(np.percentile(combined, hi_q)),
        "sampling_lo": float(np.percentile(sampling, lo_q)),
        "sampling_hi": float(np.percentile(sampling, hi_q)),
        "anchor_lo": float(np.percentile(anchor, lo_q)),
        "anchor_hi": float(np.percentile(anchor, hi_q)),
        "n": n,
        "n_nonzero": n_nonzero,
        "floor_per_1000": floor_point * 1000.0,
        "floor_share": float((n - n_nonzero) * floor_point / contrib.sum())
        if contrib.sum() > 0 else float("nan"),
        "top_participant_share": top_share,
        "extrapolation_degrees": falmouth_extrapolation_factor(mean_t_air_c),
        "alpha": alpha,
        "n_boot": n_boot,
    }


def format_interval(res: dict) -> str:
    """One-line report string. Deliberately says 'sampling + anchor',
    never 'confidence interval'."""
    if "error" in res:
        return res["error"]
    pct = int(round((1 - res["alpha"]) * 100))
    return (
        f"\u2248{res['point_per_1000']:.1f} per 1000 "
        f"({pct}% sampling + anchor interval: "
        f"{res['lo_per_1000']:.2f}\u2013{res['hi_per_1000']:.2f})"
    )


def interval_caveats(res: dict) -> list[str]:
    """Caveats that must accompany the interval. Returned as a list so
    the caller can render them as footnotes, italics, or Word comments
    without this module knowing about presentation."""
    if "error" in res:
        return []
    notes = [
        "This interval covers Monte-Carlo sampling noise and the "
        "uncertainty of the Falmouth floor regression ONLY. It does NOT "
        "cover uncertainty in the dose-response slope, which is not "
        "statistically identified from the present calibration set and "
        "is expected to be the larger error. Treat the interval as a "
        "lower bound on total uncertainty."
    ]
    if res["n_nonzero"] == 0:
        notes.append(
            "No simulated participant reached a non-zero dose: the point "
            "estimate is the temperature floor alone, and the dose-"
            "response model contributes nothing to it."
        )
    elif res["n_nonzero"] <= 5:
        notes.append(
            f"Only {res['n_nonzero']} of {res['n']} simulated participants "
            f"reached a non-zero dose, and the single most influential one "
            f"accounts for {res['top_participant_share']:.0%} of the "
            f"estimate. At this count the figure describes a few "
            f"individuals rather than the field."
        )
    if res["floor_share"] > 0.5 and res["n_nonzero"] > 0:
        notes.append(
            f"{res['floor_share']:.0%} of the estimate comes from the "
            f"temperature floor rather than from simulated dose, so it "
            f"largely restates Falmouth's epidemiology."
        )
    if res["extrapolation_degrees"] > 0:
        notes.append(
            f"The race-window mean temperature lies "
            f"{res['extrapolation_degrees']:.1f}\u00b0C outside the range "
            f"the Falmouth regression was fitted over (21.3\u201327.7\u00b0C). "
            f"The interval widens for this, but extrapolation BIAS is not "
            f"a variance and is not included in it."
        )
    return notes


# =============================================================================
# Criterion-fraction sampling precision (phase 1, 2026-08-19)
# =============================================================================
#: The EHE/EAC/conjunction figures elsewhere in this suite are counts of
#: how many ensemble members met a criterion, divided by ensemble size.
#: With a thin tail that ratio is a NOISY estimator, and nothing in the
#: reported number showed how noisy.
#:
#: Measured directly (2026-08-19): the same scenario, the same n=100
#: ensemble, five different seeds, gave 1%, 5%, 4%, 4%, 1% -- a fivefold
#: spread from sampling alone. That is the source of the jumps seen
#: across this project's reports (a fraction moving 0% -> 45% between
#: adjacent scenarios, or the DtD female curve kinking from 8% to 4%
#: between 50 and 55 years).
#:
#: These helpers make that precision visible instead of leaving it to be
#: guessed at, or to be caught by hand in prose each time.
#:
#: NOT included here: effective sample size. For unweighted Monte Carlo
#: ESS equals n by construction and carries no information; it only
#: becomes a diagnostic once importance sampling exists (planned phase
#: 2), where it detects weight degeneracy. Adding a column that always
#: reads "100/100" would suggest a check is happening when none is.


def fraction_interval(k: int, n: int, alpha: float = 0.05) -> dict:
    """Exact (Clopper-Pearson) interval for a criterion fraction k/n.

    Exact rather than normal-approximation on purpose: the normal
    approximation is unreliable precisely in the regime this suite
    operates in (small k, small p), and degenerates completely at k=0,
    where it returns a zero-width interval implying certainty.

    Covers ONE source of error: the finite number of ensemble members.
    It says nothing about whether the physiology, the thresholds, or the
    weather reconstruction are right.
    """
    if n <= 0:
        return {"error": "empty ensemble"}
    k = int(k); n = int(n)
    if k < 0 or k > n:
        return {"error": f"invalid count {k} of {n}"}
    from scipy.stats import beta as _beta
    lo = 0.0 if k == 0 else float(_beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(_beta.ppf(1 - alpha / 2, k + 1, n - k))
    return {"k": k, "n": n, "point": k / n, "lo": lo, "hi": hi, "alpha": alpha}


def format_fraction_interval(res: dict) -> str:
    """One-line rendering, e.g. '8% (3 of 40; 95% interval 2-21%)'.

    The raw count is shown deliberately: '8%' and '3 of 40' carry the
    same number but not the same warning.
    """
    if "error" in res:
        return res["error"]
    pct = int(round((1 - res["alpha"]) * 100))
    return (f"{res['point']:.0%} ({res['k']} van {res['n']}; "
            f"{pct}%-interval {res['lo']:.0%}\u2013{res['hi']:.0%})")


def fraction_caveats(res: dict, label: str = "criterium") -> list[str]:
    """Warnings triggered by the count itself, so a reader is told when a
    number is too thin to lean on without someone remembering to say so."""
    if "error" in res:
        return []
    notes = []
    k, n, lo, hi = res["k"], res["n"], res["lo"], res["hi"]
    if k == 0:
        notes.append(
            f"Geen enkele run haalde het {label}. Dat betekent niet dat de "
            f"kans nul is: bij {n} runs is alles tot {hi:.0%} verenigbaar "
            f"met deze uitkomst.")
    elif k < 5:
        notes.append(
            f"Dit percentage berust op {k} van de {n} runs. Het "
            f"{int(round((1-res['alpha'])*100))}%-interval loopt van "
            f"{lo:.0%} tot {hi:.0%} \u2014 breed genoeg om het cijfer alleen "
            f"als richtingaanwijzer te lezen, niet als schatting.")
    if k > 0 and hi > 3 * res["point"]:
        notes.append(
            f"De bovengrens ({hi:.0%}) is meer dan drie keer de "
            f"puntschatting ({res['point']:.0%}): verschillen met andere "
            f"scenario's van deze orde zijn niet te onderscheiden van "
            f"steekproefruis.")
    return notes
