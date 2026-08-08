"""
HESTIA_CVR_Console.py
=====================
Console visualisation of CVR module output for HESTIA.

Matches the visual style of HESTIA_Data_Engine.py:
  - colorama colour coding
  - Fixed-width ASCII panels
  - Horizontal bar charts as inline graphs
  - Colour thresholds consistent with calculate_adult_risk_classification()

Public API
----------
    from HESTIA_CVR_Console import (
        print_cvr_population_summary,   # population-level CVR statistics
        print_cvr_time_series,          # single-runner time series (debug/demo)
        print_cvr_comparison,           # side-by-side edition comparison
        calculate_cvr_risk_score,       # integer risk score 0-4
    )

    # Dutch aliases retained for backward compatibility:
    print_cvr_populatie_samenvatting  -> print_cvr_population_summary
    print_cvr_time_series               -> print_cvr_time_series
    print_cvr_vergelijking            -> print_cvr_comparison

Version history
---------------
v1.0  2026-03  Initial release: HR, CVS index, CO reserve, AVA, dehydration.
v2.0  2026-03  AVA (arteriovenous anastomosis) indicator removed (rev05).
               At exercise intensity in warm conditions AVA blood flow is
               elevated -- the indicator never triggered and had no
               diagnostic value in the DtD scenario domain.
v3.0  2026-03  Collapse risk section added (rev06):
               two-phase logistic model output displayed with per-1000
               expected count and calibration transparency line.
v3.1  2026-03  All text, docstrings, and inline comments translated to
               English. Dutch function names kept as aliases.
               Nested helper functions _coll_color, _per1000_color promoted
               to module level with docstrings.
               Dead _waarde() function removed from print_cvr_comparison.
               Per-row delta thresholds: collapse rows use 0.05 instead of
               0.5 to show meaningful sub-percent differences.
               _pct_bar replaced by direct _bar call with fixed 5% scale
               for collapse display (avoids CVS colour mapping on sub-1%).
               Demo build_stats() extended with collapse risk keys.
               ava_nul parameter removed from demo make_series().

Author  : HESTIA project / Veiligheidsregio Noord-Holland Noord (GHOR NHN)
"""


import numpy as np
from colorama import Fore, Back, Style, init

init(autoreset=True)

# ─────────────────────────────────────────────────────────────────────────────
# FORMATTING CONSTANTS  (consistent with HESTIA_Data_Engine.py)
# ─────────────────────────────────────────────────────────────────────────────

WIDTH = 72          # total console width
BAR_MAX = 36          # maximum width of a horizontal bar

# Colour thresholds -- consistent with calculate_adult_risk_classification()
def _hr_color(hr, hr_max):
    """Return colour for heart rate as fraction of HR_max."""
    pct = hr / hr_max if hr_max > 0 else 0
    if pct < 0.70:  return Fore.GREEN
    if pct < 0.85:  return Fore.YELLOW
    if pct < 0.95:  return Fore.MAGENTA
    return Fore.RED

def _cvs_color(cvs_index):
    """Return colour for cardiovascular stress index (fraction 0-1)."""
    if cvs_index < 0.70:  return Fore.GREEN
    if cvs_index < 0.85:  return Fore.YELLOW
    if cvs_index < 0.95:  return Fore.MAGENTA
    return Fore.RED

def _reserve_color(reserve):
    """Return colour for cardiac output reserve (L/min)."""
    if reserve > 5.0:   return Fore.GREEN
    if reserve > 3.0:   return Fore.YELLOW
    if reserve > 1.0:   return Fore.MAGENTA
    return Fore.RED

def _dehy_color(pct):
    """Return colour for dehydration as percentage of body mass."""
    if pct < 2.0:   return Fore.GREEN
    if pct < 3.0:   return Fore.YELLOW
    if pct < 4.0:   return Fore.MAGENTA
    return Fore.RED


def _coll_color(pct):
    """
    Return colour for collapse risk percentage.

    Thresholds reflect absolute probability scale (not CVS-index scale):
    <  5% -- low (GREEN)
    < 15% -- elevated (YELLOW)
    < 35% -- high (MAGENTA)
    >= 35% -- extreme (RED)

    Added v3.0; promoted to module level in v3.1.
    """
    if pct < 5:   return Fore.GREEN
    if pct < 15:  return Fore.YELLOW
    if pct < 35:  return Fore.MAGENTA
    return Fore.RED


def _per1000_color(n):
    """
    Return colour for expected collapses per 1000 participants.

    Calibrated against DtD 2024 observed rate (1.43 / 1000):
    < 0.5  -- low (GREEN)
    < 1.5  -- moderate, near observed DtD 2024 rate (YELLOW)
    < 3.0  -- high (MAGENTA)
    >= 3.0 -- extreme (RED)

    Added v3.0; promoted to module level in v3.1.
    """
    if n < 0.5:   return Fore.GREEN
    if n < 1.5:   return Fore.YELLOW
    if n < 3.0:   return Fore.MAGENTA
    return Fore.RED

# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _line(character='─', width=WIDTH):
    return character * width

def _header_text(text, character='═'):
    padding = max(0, WIDTH - len(text) - 4)
    left = padding // 2
    right = padding - left
    return (Fore.CYAN + character * left + '  ' +
            Style.BRIGHT + text + Style.NORMAL +
            '  ' + character * right + Style.RESET_ALL)

def _bar(value, maximum, width=BAR_MAX, color=Fore.GREEN):
    """Return a horizontal ASCII bar scaled to value/maximum."""
    if maximum <= 0:
        filled = 0
    else:
        # [fix 2026-07] Clamped to [0, width]: co_reserve is no longer
        # hard-clipped upstream (see HESTIA_CVR_Module_v2.py), so very
        # negative values can now reach this function. Without the lower
        # bound, a negative fill count silently overflowed the bar width
        # instead of erroring -- harmless before (input was always >= -4.0)
        # but worth pinning down explicitly now that it isn't bounded.
        filled = int(np.clip(value / maximum, 0.0, 1.0) * width)
    empty = width - filled
    return color + '█' * filled + Fore.WHITE + Style.DIM + '░' * empty + Style.RESET_ALL

def _pct_bar(pct_0_100, width=BAR_MAX):
    """Return a horizontal bar for a percentage in [0, 100]."""
    color = (_cvs_color(pct_0_100 / 100))
    return _bar(pct_0_100, 100, width, color)


# ─────────────────────────────────────────────────────────────────────────────
# 1. POPULATION SUMMARY  (after run_monte_carlo_adult)
# ─────────────────────────────────────────────────────────────────────────────

def print_cvr_population_summary(
    stats: dict,
    start_group_label: str = "",
    n_participants: int = 0,
    edition: str = "",
):
    """
    Print a structured population-level CVR summary after a Monte Carlo run.

    Renders five sections: heart rate, cardiovascular stress index,
    cardiac output reserve, dehydration, and collapse risk (only shown
    when p_collapse_mean is present in the stats dict).

    Expected keys in stats (all produced by run_monte_carlo_adult):
      hr_peak_p50/p95          peak HR percentiles (beats/min)
      hr_max_population         mean age-predicted HR_max
      cvs_peak_p50/p95         CVS index percentiles (fraction 0-1)
      pct_cvs_above_90         % participants with CVS > 0.90
      pct_decompensation        % participants with CO_reserve < 2 L/min
      co_reserve_min_p50/p05   CO reserve percentiles (L/min)
      dehy_pct_p50/p95         end-dehydration percentiles (%)
      p_collapse_mean     mean individual collapse probability (%)
      p_collapse_p95           P95 collapse probability (%)
      pct_high_collapse_risk   % participants with P(collapse) > 50%
      expected_collapses_per_1000  expected collapses per 1000 participants
      collapse_intercept_kal   calibrated logistic intercept
      collapse_p_obs_pct       observed calibration incidence (%)

    Parameters
    ----------
    stats : dict
        Statistics dict returned by run_monte_carlo_adult().
    start_group_label : str
        Start group label shown in the panel header.
    n_participants : int
        Number of simulated participants (shown in header).
    edition : str
        Event edition label (e.g. "DtD 2024").

    Changes vs previous version
    ---------------------------
    v2.0: AVA section removed (pct_ava_closed / ava_open no longer exists).
    v3.0: Collapse risk section added.
    v3.1: Renamed print_cvr_population_summary. Parameters renamed.
          _coll_color and _per1000_color moved to module level.
          Collapse bar uses _bar with fixed 5% scale instead of _pct_bar.
    """
    print()
    print(_header_text(f"CVR ANALYSIS  {edition}  {start_group_label}"))
    if n_participants:
        print(f"  {Fore.WHITE}Population: {Style.BRIGHT}{n_participants}{Style.RESET_ALL} simulated participants")
    print(_line())

    # ── Heart rate ──────────────────────────────────────────────────────────────
    print(f"\n  {Style.BRIGHT}HEART RATE (estimated){Style.RESET_ALL}  "
          f"{Fore.WHITE + Style.DIM}HR = CO_jos3 / SV  [Lloyd 2022 Eq. 2]{Style.RESET_ALL}")

    hr_p50  = stats.get('hr_peak_p50',  0)
    hr_p95  = stats.get('hr_peak_p95',  0)
    hr_max  = stats.get('hr_max_population', 185)

    color50 = _hr_color(hr_p50, hr_max)
    color95 = _hr_color(hr_p95, hr_max)

    print(f"  {'Median peak HR':<28} {color50}{hr_p50:>5.0f} bpm{Style.RESET_ALL}  "
          f"{_bar(hr_p50, hr_max, 20, color50)}  "
          f"{color50}{hr_p50/hr_max*100:>4.0f}% HR_max{Style.RESET_ALL}")
    print(f"  {'P95 peak HR':<28} {color95}{hr_p95:>5.0f} bpm{Style.RESET_ALL}  "
          f"{_bar(hr_p95, hr_max, 20, color95)}  "
          f"{color95}{hr_p95/hr_max*100:>4.0f}% HR_max{Style.RESET_ALL}")

    # ── CVS-index ─────────────────────────────────────────────────────────────
    print(f"\n  {Style.BRIGHT}CARDIOVASCULAR STRESS  (CVS index = CO / CO_max){Style.RESET_ALL}")

    cvs_p50 = stats.get('cvs_peak_p50', 0) * 100
    cvs_p95 = stats.get('cvs_peak_p95', 0) * 100
    pct_90  = stats.get('pct_cvs_above_90', 0)

    print(f"  {'Median peak CVS index':<28} {_cvs_color(cvs_p50/100)}{cvs_p50:>5.1f}%{Style.RESET_ALL}  "
          f"{_pct_bar(cvs_p50)}")
    print(f"  {'P95 peak CVS index':<28} {_cvs_color(cvs_p95/100)}{cvs_p95:>5.1f}%{Style.RESET_ALL}  "
          f"{_pct_bar(cvs_p95)}")
    print(f"  {'% with CVS index > 90%':<28} "
          f"{_cvs_color(pct_90/100)}{pct_90:>5.1f}%{Style.RESET_ALL}  "
          f"{_pct_bar(pct_90)}")

    # ── CO reserve ───────────────────────────────────────────────────────────
    print(f"\n  {Style.BRIGHT}CARDIAC OUTPUT RESERVE{Style.RESET_ALL}  "
          f"{Fore.WHITE + Style.DIM}< 2.0 L/min = decompensation risk{Style.RESET_ALL}")

    res_p50 = stats.get('co_reserve_min_p50', 0)
    res_p05 = stats.get('co_reserve_min_p05', 0)
    pct_dec = stats.get('pct_decompensation', 0)

    print(f"  {'Median min CO reserve':<28} "
          f"{_reserve_color(res_p50)}{res_p50:>5.1f} L/min{Style.RESET_ALL}  "
          f"{_bar(res_p50, 10, 20, _reserve_color(res_p50))}")
    print(f"  {'P05 min CO reserve':<28} "
          f"{_reserve_color(res_p05)}{res_p05:>5.1f} L/min{Style.RESET_ALL}  "
          f"{_bar(res_p05, 10, 20, _reserve_color(res_p05))}")
    print(f"  {'% with decompensation risk':<28} "
          f"{_cvs_color(pct_dec/100)}{pct_dec:>5.1f}%{Style.RESET_ALL}  "
          f"{_pct_bar(pct_dec)}")

    # ── Dehydration ────────────────────────────────────────────────────────────
    print(f"\n  {Style.BRIGHT}DEHYDRATION{Style.RESET_ALL}")

    dhy_p50 = stats.get('dehy_pct_p50', 0)
    dhy_p95 = stats.get('dehy_pct_p95', 0)

    print(f"  {'Median end dehydration':<28} "
          f"{_dehy_color(dhy_p50)}{dhy_p50:>5.1f}%{Style.RESET_ALL}  "
          f"{_bar(dhy_p50, 6, 20, _dehy_color(dhy_p50))}")
    print(f"  {'P95 end dehydration':<28} "
          f"{_dehy_color(dhy_p95)}{dhy_p95:>5.1f}%{Style.RESET_ALL}  "
          f"{_bar(dhy_p95, 6, 20, _dehy_color(dhy_p95))}")

    # ── Collapse risk ─────────────────────────────────────────────────────────
    p_gem   = stats.get('p_collapse_mean',        float('nan'))
    p95_coll= stats.get('p_collapse_p95',              float('nan'))
    pct_hoog= stats.get('pct_high_collapse_risk',      float('nan'))
    per1000 = stats.get('expected_collapses_per_1000', float('nan'))
    intercept_kal = stats.get('collapse_intercept_kal', float('nan'))
    p_obs_pct     = stats.get('collapse_p_obs_pct',     float('nan'))
    # [fix] Was a hardcoded, stale string ("DtD 2024 admissions: 50/35,000")
    # left over from a superseded calibration (rev11 moved the primary
    # calibration source to Boston Marathon pooled data, but this print
    # statement was never updated). Use the endpoint's own label field
    # (already present in stats, just unused here) so this stays correct
    # automatically if the active calibration ever changes again.
    endpoint_label = stats.get('active_endpoint_label', 'unknown source')

    if not np.isnan(p_gem):
        print(f"\n  {Style.BRIGHT}COLLAPSE RISK{Style.RESET_ALL}  "
              f"{Fore.WHITE + Style.DIM}two-phase logistic model  "
              f"(T_rect >=39.5/40.5degC + CO_reserve + dehydration){Style.RESET_ALL}")

        print(f"  {'Mean collapse risk':<28} "
              f"{_coll_color(p_gem)}{p_gem:>5.2f}%{Style.RESET_ALL}  "
              f"{_bar(min(p_gem, 5.0), 5.0, BAR_MAX, _coll_color(p_gem))}")
        print(f"  {'P95 collapse risk':<28} "
              f"{_coll_color(p95_coll)}{p95_coll:>5.2f}%{Style.RESET_ALL}  "
              f"{_bar(min(p95_coll, 5.0), 5.0, BAR_MAX, _coll_color(p95_coll))}")
        print(f"  {'% participants risk > 50%':<28} "
              f"{_coll_color(pct_hoog)}{pct_hoog:>5.1f}%{Style.RESET_ALL}  "
              f"{_pct_bar(pct_hoog)}")
        print(f"  {'Expected per 1000 participants':<28} "
              f"{_per1000_color(per1000)}{per1000:>5.2f}{Style.RESET_ALL}  "
              f"{Fore.WHITE + Style.DIM}based on mean collapse probability{Style.RESET_ALL}")
        if not np.isnan(intercept_kal):
            print(f"  {Fore.WHITE + Style.DIM}"
                  f"Calibration: intercept={intercept_kal:+.3f}  "
                  f"target={p_obs_pct:.4f}% ({endpoint_label})"
                  f"{Style.RESET_ALL}")

    print()
    print(_line())


# ─────────────────────────────────────────────────────────────────────────────
# 2. SINGLE-RUNNER TIME SERIES  (optional -- debug / illustration)
# ─────────────────────────────────────────────────────────────────────────────

def print_cvr_time_series(cvr_time_series, runner_label: str = "", hr_max: float = 185):
    """
    Print a compact time series of CVRState objects for a single runner.

    Each row = one time step, showing HR, HR%, CVS index, CO demand,
    CO reserve, dehydration, core temperature, and central blood temperature,
    with colour-coded risk levels. Sub-sampled to max 20 rows.

    Parameters
    ----------
    cvr_time_series : CVRTimeSeries
        Time series returned by link_cvr_to_jos3().
    runner_label : str
        Descriptive label shown in the panel header.
    hr_max : float
        Age-predicted maximal HR for this runner (beats/min).

    Changes vs previous version
    ---------------------------
    v2.0: AVA column removed from table header and rows.
    v3.1: Renamed print_cvr_time_series. Parameters renamed.
    """
    states = cvr_time_series.states
    if not states:
        print(Fore.YELLOW + "  No CVR data available." + Style.RESET_ALL)
        return

    print()
    print(_header_text(f"CVR TIME SERIES  {runner_label}"))
    print(f"  {'Min':>4}  {'HR':>5}  {'HR%':>4}  {'CVS':>5}  "
          f"{'CO_req':>6}  {'CO_res':>6}  {'Dehy':>5}  T_core  T_cb")
    print(_line('─'))

    step = max(1, len(states) // 20)   # maximum 20 rows in console

    for s in states[::step]:
        hr_pct = s.HR / hr_max * 100 if hr_max > 0 else 0
        khr    = _hr_color(s.HR, hr_max)
        kcvs   = _cvs_color(s.CVS_index)
        kres   = _reserve_color(s.CO_reserve)
        kdhy   = _dehy_color(s.dehydration_pct)
        dec_s  = f" {Fore.RED}DECOMP{Style.RESET_ALL}" if s.decompensating else ""

        print(
            f"  {s.t_min:>4.0f}  "
            f"{khr}{s.HR:>5.0f}{Style.RESET_ALL}  "
            f"{khr}{hr_pct:>3.0f}%{Style.RESET_ALL}  "
            f"{kcvs}{s.CVS_index*100:>4.0f}%{Style.RESET_ALL}  "
            f"{s.CO_demand:>5.1f}L  "
            f"{kres}{s.CO_reserve:>5.1f}L{Style.RESET_ALL}  "
            f"{kdhy}{s.dehydration_pct:>4.1f}%{Style.RESET_ALL}  "
            f"{s.t_core:>5.2f}°  "
            f"{s.t_cb:>5.2f}°"
            f"{dec_s}"
        )

    print(_line('─'))
    print(f"  Peak HR: {_hr_color(cvr_time_series.max_HR(), hr_max)}"
          f"{cvr_time_series.max_HR():.0f} bpm{Style.RESET_ALL}  |  "
          f"Max CVS: {_cvs_color(cvr_time_series.max_CVS_index())}"
          f"{cvr_time_series.max_CVS_index()*100:.0f}%{Style.RESET_ALL}  |  "
          f"Min reserve: {_reserve_color(cvr_time_series.min_CO_reserve())}"
          f"{cvr_time_series.min_CO_reserve():.1f} L/min{Style.RESET_ALL}")

    decomp_t = cvr_time_series.decompensation_time()
    if decomp_t is not None:
        print(f"  {Fore.RED}▲ Decompensation risk from t={decomp_t:.0f} min{Style.RESET_ALL}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 3. COMPARISON OF TWO EDITIONS  (core output for DtD 2024 vs 2025)
# ─────────────────────────────────────────────────────────────────────────────

def print_cvr_comparison(
    stats_a: dict, label_a: str,
    stats_b: dict, label_b: str,
    n_a: int = 0, n_b: int = 0,
):
    """
    Print a side-by-side comparison of CVR statistics for two editions,
    with a delta column (Δ = A − B) and per-row colour coding.

    Delta thresholds per metric category:
      Standard physiological metrics : 0.5 (absolute)
      Collapse risk percentages      : 0.05 (sub-percent scale)
      Expected collapses per 1000    : 0.05

    Parameters
    ----------
    stats_a / stats_b : dict
        Statistics dicts from run_monte_carlo_adult() for each edition.
    label_a / label_b : str
        Edition labels (e.g. 'DtD 2024' / 'DtD 2025').
    n_a / n_b : int
        Number of simulated participants shown in column headers.

    Changes vs previous version
    ---------------------------
    v2.0: AVA row (pct_ava_closed) removed.
    v3.0: Collapse risk rows added.
    v3.1: Renamed print_cvr_comparison. Dead _value() helper removed.
          Per-row delta thresholds introduced (collapse rows use 0.05).
    """

    def _delta_color(delta, higher_is_worse=True, threshold=0.5):
        if abs(delta) < threshold:
            return Fore.WHITE
        if higher_is_worse:
            return Fore.RED if delta > 0 else Fore.GREEN
        else:
            return Fore.GREEN if delta > 0 else Fore.RED

    print()
    print(_header_text(f"CVR COMPARISON  {label_a}  vs  {label_b}"))
    lbl_a = f"{label_a}" + (f" (n={n_a})" if n_a else "")
    lbl_b = f"{label_b}" + (f" (n={n_b})" if n_b else "")
    print(f"  {'Metric':<35}  {lbl_a:>14}  {lbl_b:>14}  {'Delta':>8}")
    print(_line('─'))

    rows = [
        # (label, key_a, key_b, factor, fmt, higher_is_worse, delta_threshold)
        ('Median peak HR (bpm)',          'hr_peak_p50',              'hr_peak_p50',              1,   '.0f', True,  0.5),
        ('P95 peak HR (bpm)',             'hr_peak_p95',              'hr_peak_p95',              1,   '.0f', True,  0.5),
        ('Median peak CVS index (%)',     'cvs_peak_p50',             'cvs_peak_p50',             100, '.1f', True,  0.5),
        ('P95 peak CVS index (%)',        'cvs_peak_p95',             'cvs_peak_p95',             100, '.1f', True,  0.5),
        ('% CVS index > 90%',             'pct_cvs_above_90',         'pct_cvs_above_90',         1,   '.1f', True,  0.5),
        ('% with decompensation risk',    'pct_decompensation',        'pct_decompensation',        1,   '.1f', True,  0.5),
        ('Median min CO reserve (L)',     'co_reserve_min_p50',       'co_reserve_min_p50',       1,   '.1f', False, 0.5),
        ('P05 min CO reserve (L)',        'co_reserve_min_p05',       'co_reserve_min_p05',       1,   '.1f', False, 0.5),
        ('Mean collapse risk (%)',        'p_collapse_mean',     'p_collapse_mean',     1,   '.2f', True,  0.05),
        ('P95 collapse risk (%)',         'p_collapse_p95',           'p_collapse_p95',           1,   '.2f', True,  0.05),
        ('Expected per 1000',             'expected_collapses_per_1000', 'expected_collapses_per_1000', 1, '.2f', True, 0.05),
        ('% high collapse risk (>50%)',   'pct_high_collapse_risk',   'pct_high_collapse_risk',   1,   '.1f', True,  0.5),
        ('Median end dehydration (%)',    'dehy_pct_p50',             'dehy_pct_p50',             1,   '.1f', True,  0.5),
        ('P95 end dehydration (%)',       'dehy_pct_p95',             'dehy_pct_p95',             1,   '.1f', True,  0.5),
    ]

    for label, key_a, key_b, factor, fmt, higher_is_worse, d_thresh in rows:
        va = stats_a.get(key_a, float('nan')) * factor
        vb = stats_b.get(key_b, float('nan')) * factor

        if np.isnan(va) or np.isnan(vb):
            delta_str = '   —'
            d_color    = Fore.WHITE
        else:
            delta = va - vb
            d_color = _delta_color(delta, higher_is_worse, threshold=d_thresh)
            delta_str = f"{delta:+.2f}"

        va_str = f"{va:{fmt}}" if not np.isnan(va) else '—'
        vb_str = f"{vb:{fmt}}" if not np.isnan(vb) else '—'

        # Colour values based on which side is higher/worse
        if not np.isnan(va) and not np.isnan(vb):
            if higher_is_worse:
                kl_a = Fore.RED   if va > vb else Fore.GREEN
                kl_b = Fore.GREEN if va > vb else Fore.RED
            else:
                kl_a = Fore.GREEN if va > vb else Fore.RED
                kl_b = Fore.RED   if va > vb else Fore.GREEN
            if abs(va - vb) < d_thresh:
                kl_a = kl_b = Fore.WHITE
        else:
            kl_a = kl_b = Fore.WHITE

        print(f"  {label:<35}  "
              f"{kl_a}{va_str:>14}{Style.RESET_ALL}  "
              f"{kl_b}{vb_str:>14}{Style.RESET_ALL}  "
              f"{d_color}{delta_str:>8}{Style.RESET_ALL}")

    print(_line())
    print(f"  {Fore.WHITE + Style.DIM}Green = better  |  Red = worse  |  "
          f"delta = {label_a} - {label_b}{Style.RESET_ALL}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 4. CVR RISK SCORE  (extension of the existing HESTIA risk classification)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_cvr_risk_score(cvs_index: float, co_reserve: float,
                              hr_pct_max: float) -> int:
    """
    Return a composite CVR risk level 0-4.

    Consistent with calculate_adult_risk_classification() in the Data Engine.
    Final score = maximum across CVS, CO reserve, and HR sub-scores.

    Score  CVS index   CO reserve   %HR_max   Label
    -----  ----------  -----------  --------  -------
      0    < 70%       > 5.0 L/min  < 70%     No risk
      1    < 80%       > 3.0 L/min  < 80%     Low risk
      2    < 90%       > 2.0 L/min  < 90%     Moderate risk
      3    < 95%       > 1.0 L/min  < 95%     High risk
      4    >= 95%      <= 1.0 L/min >= 95%    Extreme risk

    Parameters
    ----------
    cvs_index : float
        Cardiovascular stress index = CO_demanded / CO_max (fraction 0-1).
    co_reserve : float
        Minimum cardiac output reserve (L/min).
    hr_pct_max : float
        Heart rate as percentage of HR_max (0-100).

    Returns
    -------
    int
        Risk score 0-4.
    """
    scores = {
        'cvs':     (0 if cvs_index < 0.70 else 1 if cvs_index < 0.80
                    else 2 if cvs_index < 0.90 else 3 if cvs_index < 0.95 else 4),
        'reserve': (0 if co_reserve > 5.0 else 1 if co_reserve > 3.0
                    else 2 if co_reserve > 2.0 else 3 if co_reserve > 1.0 else 4),
        'hr_pct':  (0 if hr_pct_max < 70 else 1 if hr_pct_max < 80
                    else 2 if hr_pct_max < 90 else 3 if hr_pct_max < 95 else 4),
    }
    return max(scores.values())


# ─────────────────────────────────────────────────────────────────────────────
# DEMO  (run as a standalone script)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/home/claude')
    sys.path.insert(0, '/mnt/user-data/outputs')

    from HESTIA_CVR_Module_v2 import (
        RunnerProfile, JOS3Outputs, CVRModel,
        link_cvr_to_jos3, CVRTimeSeries
    )

    print()
    print(Fore.CYAN + Style.BRIGHT +
          "  HESTIA CVR Console -- Demo: DtD 2024 vs 2025" +
          Style.RESET_ALL)
    print()

    # ── Simulated JOS-3 time series (as in the previous module) ───────────────
    def make_series(co_start, co_end, tc_start, tc_end,
                   tcb_start, tcb_end, sweat_kgh,
                   bfsk_start, bfsk_end, n=100):
        series = []
        for i in range(n):
            f    = (i / n) ** 0.5
            co   = co_start   + f * (co_end   - co_start)
            tc   = tc_start   + f * (tc_end   - tc_start)
            tcb  = tcb_start  + f * (tcb_end  - tcb_start)
            bfsk = bfsk_start + f * (bfsk_end - bfsk_start)
            gv   = sweat_kgh * (i / 60)
            series.append(JOS3Outputs(
                t_min=i, cardiac_output=co, t_core_mean=tc, t_cb=tcb,
                weight_loss_g_s=gv, bf_skin_total=bfsk,
                bf_ava_hand=1.2, bf_ava_foot=1.2,  # open state (exercise in heat)
            ))
        return series

    runners = [
        RunnerProfile(mass=70, height=175, age=35, sex='male',   vo2max=50),
        RunnerProfile(mass=65, height=168, age=52, sex='male',   vo2max=38),
        RunnerProfile(mass=58, height=163, age=38, sex='female', vo2max=42),
    ]

    series_2024 = make_series(800,1480, 37.0,40.4, 36.8,39.8, 1.5, 80,480)
    series_2025 = make_series(780,1220, 37.0,39.5, 36.8,39.1, 1.1, 80,340)

    # ── Build simulated population statistics for the demo ───────────────────
    def build_stats(series_per_runner):
        hr_peaks, cvs_peaks, reserves, dehys = [], [], [], []
        hr_maxes = []
        for runner, series in series_per_runner:
            ts = link_cvr_to_jos3(runner, series)
            hr_peaks.append(ts.max_HR())
            cvs_peaks.append(ts.max_CVS_index())
            reserves.append(ts.min_CO_reserve())
            dehys.append(ts.final_state().dehydration_pct)
            hr_maxes.append(CVRModel(runner).HR_max)

        hr_a = np.array(hr_peaks)
        cv_a = np.array(cvs_peaks)
        re_a = np.array(reserves)
        dh_a = np.array(dehys)
        hm_a = np.array(hr_maxes)

        # Two-phase collapse risk (mirrors run_monte_carlo_adult logic)
        t_core_arr = np.array([link_cvr_to_jos3(l, r).final_state().t_core
                               for l, r in series_per_runner])
        W_T1, W_T2, W_C, W_D = 1.0, 4.0, 0.8, 0.5
        P_OBS_D = 50 / 35_000
        z0 = (W_T1 * np.clip(t_core_arr - 39.5, 0, None)
              + W_T2 * np.clip(t_core_arr - 40.5, 0, None)
              + W_C  * np.clip(2.0 - re_a, 0, None)
              + W_D  * np.clip(dh_a - 3.0, 0, None))
        intc = float(np.log(P_OBS_D/(1-P_OBS_D))) - float(np.nanmean(z0))
        for _ in range(5):
            pp = 1/(1+np.exp(-(intc+z0)))
            g  = float(np.nanmean(pp*(1-pp)))
            if g < 1e-12: break
            intc += (P_OBS_D - float(np.nanmean(pp))) / g
        p_coll = 1/(1+np.exp(-(intc+z0)))
        return {
            'hr_peak_p50':               np.percentile(hr_a, 50),
            'hr_peak_p95':               np.percentile(hr_a, 95),
            'cvs_peak_p50':              np.percentile(cv_a, 50),
            'cvs_peak_p95':              np.percentile(cv_a, 95),
            'pct_cvs_above_90':          np.mean(cv_a > 0.90) * 100,
            'pct_decompensation':         np.mean(re_a < 2.0)  * 100,
            'co_reserve_min_p50':        np.percentile(re_a, 50),
            'co_reserve_min_p05':        np.percentile(re_a,  5),
            'dehy_pct_p50':              np.percentile(dh_a, 50),
            'dehy_pct_p95':              np.percentile(dh_a, 95),
            'hr_max_population':          np.mean(hm_a),
            'p_collapse_mean':      float(np.nanmean(p_coll)) * 100,
            'p_collapse_p95':            float(np.nanpercentile(p_coll, 95)) * 100,
            'pct_high_collapse_risk':    float(np.nanmean(p_coll > 0.50)) * 100,
            'expected_collapses_per_1000': float(np.nanmean(p_coll)) * 1000,
            'collapse_intercept_kal':    float(intc),
            'collapse_p_obs_pct':        P_OBS_D * 100,
            'p_collapse_per_sim':        p_coll,
        }

    pairs_2024 = [(l, series_2024) for l in runners]
    pairs_2025 = [(l, series_2025) for l in runners]
    stats_2024 = build_stats(pairs_2024)
    stats_2025 = build_stats(pairs_2025)

    # ── 1. Population summary per edition ─────────────────────────────────────
    print_cvr_population_summary(stats_2024, "Business Run 5", 3, "DtD 2024")
    print_cvr_population_summary(stats_2025, "Business Run 5", 3, "DtD 2025")

    # ── 2. Time series for one runner ──────────────────────────────────────────
    ts_2024 = link_cvr_to_jos3(runners[1], series_2024)  # male 52y
    print_cvr_time_series(ts_2024, "Male 52y VO2max=38 -- DtD 2024",
                          hr_max=CVRModel(runners[1]).HR_max)

    # ── 3. Comparison, 2024 vs 2025 ────────────────────────────────────────────
    print_cvr_comparison(
        stats_2024, "DtD 2024", stats_2025, "DtD 2025",
        n_a=3, n_b=3
    )

# =============================================================================
# BACKWARD-COMPATIBLE DUTCH ALIASES  (v3.1)
# Existing code using Dutch function names continues to work unchanged.
# New code should use the English names.
# =============================================================================
print_cvr_populatie_samenvatting = print_cvr_population_summary
print_cvr_time_series              = print_cvr_time_series
print_cvr_vergelijking           = print_cvr_comparison
