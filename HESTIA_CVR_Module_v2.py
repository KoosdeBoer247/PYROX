"""
HESTIA_CVR_Module_v2.py
=======================
Cardiovascular Response module for HESTIA — version 2.

Revised architecture based on the full set of JOS-3 output variables:
  - cardiac_output [L/h] from JOS-3 as a direct CO demand (no longer estimated)
  - bf_skin, bf_ava_hand/foot, t_cb as additional JOS-3 inputs
  - HR computed via Lloyd et al. (2022) Eq. 2: CO = SV x HR

Sources:
  Lloyd A, Fiala D, Heyde C, Havenith G (2022).
    "A mathematical model for predicting cardiovascular responses at rest
    and during exercise in demanding environmental conditions."
    J Appl Physiol 133(2):247-261. doi:10.1152/japplphysiol.00619.2021
    PMC9342140 -- CC-BY 4.0

  Takahashi Y et al. (2021). Thermoregulation Model JOS-3 with New Open
    Source Code. Energy & Buildings. doi:10.1016/j.enbuild.2020.110575

  Tanaka H et al. (2001). Age-predicted maximal heart rate revisited.
    J Am Coll Cardiol 37:153-156.  [HR_max = 208 - 0.7 x age]

  Rowell LB (1986). Human Circulation: Regulation During Physical Stress.
    Oxford University Press. [CO_max during exercise in heat]

  Gonzalez-Alonso J et al. (2008). Haemodynamics and the human
    cardiovascular response to heat and exercise.
    J Physiol 586:45-49.  [SV decline under heat stress]

Author  : HESTIA project / Veiligheidsregio NHN
Version : 2.0 -- March 2026

Line 264 commented out; related to the correction for females.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RunnerProfile:
    """
    Anthropometric and physiological characteristics of one runner.
    vo2max in mL/kg/min -- to be added to HESTIA's Monte Carlo sampling.

    Recommended Monte Carlo distribution for vo2max in a DtD population:
        Normal(mu=45, sigma=10) mL/kg/min, bounded to [20, 80]
        Source: Scharhag-Rosenberger et al. (2010) for recreational runners
    """
    mass:        float                 # kg
    height:      float                 # cm
    age:         float                 # years
    sex:         str                   # 'male' | 'female'
    vo2max:      float                 # mL/kg/min


@dataclass
class JOS3Outputs:
    """
    Relevant JOS-3 outputs at one point in time.
    Units exactly as published in the pythermalcomfort documentation.
    """
    t_min:               float          # time in minutes (computed by HESTIA)
    cardiac_output:      float          # L/h  -- sum of all blood flows
    t_core_mean:         float          # degC -- mean core temperature (t_core.mean())
    t_cb:                float          # degC -- central blood temperature
    weight_loss_g_s:     float          # g/s  -- cumulative sweat+respiratory weight loss
    bf_skin_total:       float          # L/h  -- sum of bf_skin over all 17 segments
    bf_ava_hand:         float          # L/h  -- AVA blood flow, hand
    bf_ava_foot:         float          # L/h  -- AVA blood flow, foot
    t_skin_mean:         Optional[float] = None  # [2026-07] mean skin temp
                                         # (jos3_model.t_skin_mean); needed for
                                         # the Lloyd 2022 mean-body-temperature
                                         # term (Tbody = 0.2*Tskin + 0.8*Tcore)
                                         # that drives the Cardiac Heat Strain
                                         # Index. None falls back to an
                                         # approximation (t_core_mean - 4.0)
                                         # for backward compatibility with
                                         # code that doesn't supply it.
    current_met:         Optional[float] = None  # [2026-07] the actual MET
                                         # driving JOS-3 at this time step
                                         # (jos3_model.par in hestia_model.py;
                                         # reflects real-time pacing slowdown,
                                         # not just the initial target MET).
                                         # Used for a direct VO2 calculation
                                         # in CVRModel.compute_step() instead
                                         # of back-calculating VO2 from
                                         # cardiac_output. None falls back to
                                         # the old back-calculation for
                                         # backward compatibility (e.g. the
                                         # demos in this file and in
                                         # HESTIA_CVR_Console.py, which
                                         # synthesize cardiac_output curves
                                         # directly and have no MET signal).


@dataclass
class CVRState:
    """Cardiovascular state at one point in time -- output of the CVR module."""
    t_min:              float = 0.0
    # Heart-rate estimate (primary new output)
    HR:                 float = 0.0    # beats/min -- estimated
    HR_max:             float = 0.0    # beats/min -- age-dependent maximum
    HR_reserve_pct:     float = 0.0    # % of HR reserve used (Karvonen)
    # Cardiac output
    CO_demand:          float = 0.0    # L/min -- from JOS-3 (cardiac_output / 60)
    CO_max:             float = 0.0    # L/min -- maximum under current conditions
    CO_reserve:         float = 0.0    # L/min -- available reserve
    SV:                 float = 0.0    # mL/beat -- stroke volume
    # Cardiovascular load
    CVS_index:          float = 0.0    # CO_demand / CO_max  (0-1, or above 1 if demand exceeds capacity)
    decompensating:     bool  = False  # CO_reserve < threshold
    # AVA status (thermoregulatory signal)
    ava_open:           bool  = True   # False = AVA closed -> limit reached
    # Dehydration
    dehydration_pct:    float = 0.0    # % body-weight loss
    # Passed-through JOS-3 values
    t_core:             float = 0.0
    t_cb:               float = 0.0
    bf_skin_total_lh:   float = 0.0   # L/h, for logging


@dataclass
class CVRTimeSeries:
    """Time series of CVRState objects for one runner."""
    states: List[CVRState] = field(default_factory=list)

    def append(self, s: CVRState):
        self.states.append(s)

    def max_CVS_index(self) -> float:
        return max(s.CVS_index for s in self.states) if self.states else 0.0

    def max_HR(self) -> float:
        return max(s.HR for s in self.states) if self.states else 0.0

    def min_CO_reserve(self) -> float:
        return min(s.CO_reserve for s in self.states) if self.states else 0.0

    def decompensation_time(self) -> Optional[float]:
        for s in self.states:
            if s.decompensating:
                return s.t_min
        return None

    def ava_closure_time(self) -> Optional[float]:
        """First time at which the AVA closes -- the earliest detectable signal."""
        for s in self.states:
            if not s.ava_open:
                return s.t_min
        return None

    def final_state(self) -> Optional[CVRState]:
        return self.states[-1] if self.states else None


# ─────────────────────────────────────────────────────────────────────────────
# CVR MODEL
# ─────────────────────────────────────────────────────────────────────────────

# [INVESTIGATION NOTE, 2026-08-09, superseded -- see hestia_model.py's
# calculate_indices_jos3_adult() near "cvr_water_loss_kg" for the real fix]
#
# An initial hypothesis here proposed capping dehydration_pct's
# contribution to CHSI at a fixed ceiling, to stop a duration-driven
# CO_reserve decline that persisted even at a mild, constant 22degC (no
# heat escalation at all) and even after T_core had plateaued. That
# hypothesis was WRONG: the dehydration_pct values themselves were modest
# and realistic (1.64% after 2h, well within normal sweat-loss ranges) --
# capping them would have masked the real problem rather than fixed it.
#
# The actual root cause: this module's dehydration input
# (weight_loss_g_s, fed from hestia_model.py's `cvr_water_loss_kg`) is a
# PURE ACCUMULATOR with no drinking/rehydration subtracted from it, ever
# -- as if the simulated runner drinks nothing for the entire event. A
# SEPARATE, parallel variable in the same function (`cumulative_water_loss`)
# already correctly simulates ad-libitum drinking (thirst_threshold,
# random 120-180g intake per drink) and is used for RPE and the
# first_aid_visit screening flag -- but that correctly-hydrating value was
# never connected to the CVR module. CHSI, and therefore CO_max and
# CO_reserve, was being computed as if the runner never drinks, while the
# rest of the simulation assumed realistic drinking behaviour.
#
# Proposed fix (not yet applied here -- needs hestia_model.py's loop
# reordered so cumulative_water_loss is current for the same timestep
# before the CVR snapshot is built, then pass that instead of
# cvr_water_loss_kg): see the detailed note at that call site.


class CVRModel:
    """
    CVR Model v2 -- rebuilt 2026-07 to implement Lloyd et al. (2022)'s
    full workload-response and heat-strain equations (Eq. 12-31), instead
    of reading JOS-3's own `cardiac_output` (which is a thermal-model sum
    of tissue blood flows, not an independently validated cardiovascular
    demand -- see compute_step()'s docstring for the full story and the
    literature that led to this rebuild).

    HR/CO/SV are computed entirely from: workload (current MET relative
    to this person's own VO2rest/VO2max), and a Cardiac Heat Strain Index
    driven by mean body temperature and dehydration. jos3.cardiac_output
    is only used as a legacy fallback when no MET signal is available.
    """

    # Thresholds
    DECOMPENSATION_RESERVE = 2.0    # L/min
    AVA_CLOSURE_THRESHOLD  = 0.10   # L/h -- AVA essentially closed
    RER                    = 0.7    # respiratory exchange ratio (Lloyd 2022, Eq. 4.1/4.2)

    def __init__(self, runner: RunnerProfile):
        self.runner = runner
        self._vo2max_abs = (runner.vo2max * runner.mass) / 1000.0  # L/min
        self._compute_base_parameters()
        self._vo2_rest = self._compute_vo2_rest()

    # ── Base parameters (Lloyd 2022, Tanaka 2001) ─────────────────────────────

    def _compute_base_parameters(self):
        """
        One-off computation of age- and fitness-dependent limits.

        SV_max  (Eq. 6 Lloyd 2022): SVmax = 40.59 + 24.81 x VO2max_abs
        SV_rest (Eq. 7 Lloyd 2022): 85.1 mL/beat population average
        HR_max  (Eq. 8, Tanaka 2001): 208 - 0.7 x age
        HR_rest (Eq. 9 Lloyd 2022):   90.93 - 0.64 x VO2max_rel
        CO_max  (Eq. 10):             SV_max x HR_max / 1000
        CO_rest (Eq. 11):             SV_rest x HR_rest / 1000
        """
        v = self._vo2max_abs

        self.SV_max  = 40.59 + 24.81 * v         # mL/beat
        self.SV_rest = 85.1                        # mL/beat
        self.HR_max  = 208 - 0.7 * self.runner.age
        self.HR_rest = max(40.0, 90.93 - 0.64 * self.runner.vo2max)
        self.CO_max  = (self.SV_max  / 1000) * self.HR_max
        self.CO_rest = (self.SV_rest / 1000) * self.HR_rest

    # ── Environmental corrections ──────────────────────────────────────────────

    def _compute_vo2_rest(self) -> float:
        """
        Resting oxygen consumption via Mifflin-St Jeor + Weir rearrangement
        (Lloyd 2022, Eq. 4.1/4.2).

        BMR (kcal/day), standard Mifflin-St Jeor:
            male:   10*mass + 6.25*height - 5*age + 5
            female: 10*mass + 6.25*height - 5*age - 161
        Converted to VO2rest (L/min) assuming RER=0.7, per Lloyd 2022's
        stated rearrangement of the Weir formula: divide by (1440*5.05*RER).
        """
        m = self.runner
        if str(m.sex).lower().startswith('m'):
            bmr_kcal_day = 10 * m.mass + 6.25 * m.height - 5 * m.age + 5
        else:
            bmr_kcal_day = 10 * m.mass + 6.25 * m.height - 5 * m.age - 161
        vo2_rest = bmr_kcal_day / (1440 * 5.05 * self.RER)
        return max(0.15, vo2_rest)  # floor: avoid degenerate near-zero BMR inputs

    def _chsi(self, t_core: float, t_skin: float, dehydration_pct: float) -> float:
        """
        Cardiac Heat Strain Index -- additive form (Lloyd 2022, Eq. 22.2).

        CHSI = 0.5*%Dehyd + 0.5*deltaTbody
        where deltaTbody = 0.2*Tskin + 0.8*Tcore - 36.54 (reference point).

        The synergistic form (Eq. 22.1) was derived from young endurance-
        trained male runners only (Gonzalez-Alonso 2008); the additive form
        is used here as the more general default across a mixed-age,
        mixed-fitness population, consistent with how Lloyd et al. (2022)
        themselves tested both forms for validation.
        """
        delta_t_body = max(0.0, 0.2 * t_skin + 0.8 * t_core - 36.54)
        dehyd = max(0.0, dehydration_pct)
        return 0.5 * dehyd + 0.5 * delta_t_body

    # ── Single time step ───────────────────────────────────────────────────────

    def compute_step(
        self,
        jos3: JOS3Outputs,
        decompensation_threshold: float = DECOMPENSATION_RESERVE,
    ) -> CVRState:
        """
        Compute cardiovascular state from JOS-3 output.

        [2026-07, REBUILT] Two same-day attempts to fix implausibly high
        collapse-risk rates were tried and reverted (see git history /
        INTEGRATION_CHANGELOG.md): an intensity-dependent a-vO2diff, and a
        direct MET-based VO2 calculation that bypassed jos3.cardiac_output
        entirely. The second one "looked" like it fixed the problem
        (Falmouth 2015: 92.7 -> 4.8 expected collapses/1000) but was a
        misdiagnosis: verified directly that JOS-3's own cardiac_output
        (the sum of all tissue blood flows) rises ~80% between tdb=20degC
        and tdb=38degC at a FIXED MET -- a large, genuine heat-driven
        cardiovascular signal that a MET-only calculation cannot see, and
        that got silently deleted along with whatever was actually wrong.

        Root cause, per Lloyd A, Fiala D, Heyde C, Havenith G (2022,
        J Appl Physiol 133:247-261 -- the SAME paper this module already
        cites for Eq. 6-11): thermophysiological models like JOS-3 derive
        "cardiac output" from tissue oxygen needs and skin blood flow
        requirements, but do NOT "account for cardiac strains imposed by
        the heat-induced competitive redistribution of blood flow" (their
        words). That paper's own measured exercise data shows CO changes
        only -3% to +15% during EXERCISE in heat (their Fig. 2D) -- nothing
        like JOS-3's +80% at fixed effort. The paper's entire point is that
        thermal models' own cardiac_output should NOT be used as the
        cardiovascular demand signal; their CVR Model computes CO/SV/HR
        independently from workload + environmental strain, validated
        against real heart-rate data from 101 individuals (R2=0.82-0.97).

        This rebuild implements that intended architecture (Eq. 12-13,
        22-31) instead of reading jos3.cardiac_output at all:
          1. Workload fraction FVO2max(reserve) from current MET vs. this
             person's own VO2rest/VO2max (Eq. 5, adapted from current_met).
          2. Cardiac Heat Strain Index (CHSI) from mean body temperature
             and dehydration (Eq. 22.2).
          3. Heat/dehydration-modulated CO_max, CO_rest, SV_max, SV_rest
             (Eq. 23-27) -- CO_max DECREASES with heat (-8.3%/degC CHSI),
             CO_rest INCREASES (+31.3%/degC CHSI); these are independently
             fitted, not mirror images of each other.
          4. Final HR/CO/SV via linear interpolation between heat-adjusted
             rest and max, driven by workload fraction (Eq. 29-31).
        No altitude term (not relevant here) -- Eq. 15/28/32 simplified
        accordingly (see comments below).
        """
        # --- Dehydration and mean body temperature ---
        dehydration_pct = (jos3.weight_loss_g_s / self.runner.mass) * 100
        t_skin = jos3.t_skin_mean if jos3.t_skin_mean is not None else jos3.t_core_mean - 4.0
        chsi = self._chsi(jos3.t_core_mean, t_skin, dehydration_pct)

        # --- Heat/dehydration-modulated basic parameters (Eq. 23-26) ---
        sv_max_heat  = (1 + chsi * -0.083) * self.SV_max
        co_max_heat  = (1 + chsi * -0.083) * self.CO_max
        sv_rest_heat = (1 + chsi *  0.025) * self.SV_rest
        co_rest_heat = (1 + chsi *  0.313) * self.CO_rest
        hr_rest_heat = (co_rest_heat * 1000.0) / max(1.0, sv_rest_heat)  # Eq. 27

        # --- Workload fraction (Eq. 5, adapted; Eq. 32 without altitude) ---
        if jos3.current_met is not None:
            vo2_current = (jos3.current_met * 3.5 * self.runner.mass) / 1000.0
        else:
            # Legacy fallback for callers with no MET signal (e.g. the
            # standalone demos in this file / HESTIA_CVR_Console.py, which
            # synthesize cardiac_output curves directly): approximate VO2
            # from JOS-3's own CO. Not used in the production pipeline.
            vo2_current = (jos3.cardiac_output / 60) * 0.155

        avo2diffmax = self._vo2max_abs / max(0.1, self.CO_max)   # Eq. 15, no altitude
        vo2max_heat = avo2diffmax * co_max_heat                    # Eq. 32, no altitude
        denom = max(0.05, vo2max_heat - self._vo2_rest)
        f_vo2max_reserve = float(np.clip(
            (vo2_current - self._vo2_rest) / denom, 0.0, 1.15
        ))

        # --- Final HR, CO, SV (Eq. 29-31) ---
        hr = (self.HR_max - hr_rest_heat) * f_vo2max_reserve + hr_rest_heat
        hr = np.clip(hr, hr_rest_heat * 0.95, self.HR_max * 1.05)
        co_demand = (co_max_heat - co_rest_heat) * f_vo2max_reserve + co_rest_heat
        sv = (co_demand / max(0.01, hr)) * 1000.0

        # --- Reserve and load, measured against the heat-adjusted ceiling ---
        # [2026-07] co_reserve is intentionally unbounded (see prior fix
        # history above/in INTEGRATION_CHANGELOG.md): it expresses distance
        # from safe, not a value ever directly observed at some clipped
        # limit. cvs_index likewise unbounded above 1.0.
        co_reserve = co_max_heat - co_demand
        cvs_index  = (co_demand / co_max_heat) if co_max_heat > 0 else 1.0

        # --- Karvonen HR-reserve percentage ---
        hr_reserve_pct = np.clip(
            (hr - hr_rest_heat) / max(1.0, self.HR_max - hr_rest_heat) * 100,
            0.0, 100.0
        )

        # --- AVA status ---
        ava_totaal = jos3.bf_ava_hand + jos3.bf_ava_foot
        ava_open   = ava_totaal > self.AVA_CLOSURE_THRESHOLD

        # --- Decompensation ---
        decompensating = co_reserve < decompensation_threshold

        return CVRState(
            t_min            = jos3.t_min,
            HR               = round(hr, 1),
            HR_max           = round(self.HR_max, 1),
            HR_reserve_pct   = round(hr_reserve_pct, 1),
            CO_demand        = round(co_demand, 2),
            CO_max           = round(co_max_heat, 2),
            CO_reserve       = round(co_reserve, 2),
            SV               = round(sv, 1),
            CVS_index        = round(cvs_index, 3),
            decompensating   = decompensating,
            ava_open         = ava_open,
            dehydration_pct  = round(dehydration_pct, 2),
            t_core           = round(jos3.t_core_mean, 2),
            t_cb             = round(jos3.t_cb, 2),
            bf_skin_total_lh = round(jos3.bf_skin_total, 1),
        )


# ─────────────────────────────────────────────────────────────────────────────
# HESTIA COUPLING INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def link_cvr_to_jos3(
    runner:           RunnerProfile,
    jos3_output_list: List[JOS3Outputs],
    decompensation_threshold: float = 2.0,
) -> CVRTimeSeries:
    """
    Process a list of JOS3Outputs into a CVRTimeSeries.

    Usage in HESTIA_Data_Engine.py:

        from HESTIA_CVR_Module_v2 import (
            RunnerProfile, JOS3Outputs, link_cvr_to_jos3
        )

        # After the existing JOS-3 simulation loop:
        jos3_outputs = []
        weight_loss_kg = 0.0
        for step_idx, sim_step in enumerate(simulation_time_steps):
            jos3_model.simulate(times=1, dtime=60)
            r = jos3_model.dict_results()

            # Build up cumulative weight loss
            weight_loss_kg += r['weight_loss_by_evap_and_res'][-1] * 60 / 1000

            jos3_outputs.append(JOS3Outputs(
                t_min            = step_idx,
                cardiac_output   = r['cardiac_output'][-1],       # L/h
                t_core_mean      = r['t_core'][-1].mean(),         # degC
                t_cb             = r['t_cb'][-1],                  # degC
                weight_loss_g_s  = weight_loss_kg,                 # cumulative kg
                bf_skin_total    = r['bf_skin'][-1].sum(),          # L/h
                bf_ava_hand      = r['bf_ava_hand'][-1],           # L/h
                bf_ava_foot      = r['bf_ava_foot'][-1],           # L/h
            ))

        cvr_profile = RunnerProfile(
            mass=runner_weight, height=runner_height * 100,
            age=runner_age, sex=gender, vo2max=vo2max_sample
        )
        cvr_ts = link_cvr_to_jos3(cvr_profile, jos3_outputs)

        # Outcome measures for HESTIA aggregation:
        hr_max_run          = cvr_ts.max_HR()
        cvs_index_max       = cvr_ts.max_CVS_index()
        decompensation_t    = cvr_ts.decompensation_time()
        ava_closure_t       = cvr_ts.ava_closure_time()
    """
    model = CVRModel(runner)
    time_series = CVRTimeSeries()
    for jos3_step in jos3_output_list:
        state = model.compute_step(jos3_step, decompensation_threshold)
        time_series.append(state)
    return time_series


# ─────────────────────────────────────────────────────────────────────────────
# DEMO: DtD 2024 vs 2025 with simulated JOS-3 time series
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print("=" * 72)
    print("HESTIA CVR Module v2 -- Demo: DtD 2024 vs 2025")
    print("Coupled via JOS-3 cardiac_output (L/h) as direct CO input")
    print("=" * 72)

    # ── Three representative runners ──────────────────────────────────────────
    runners = [
        RunnerProfile(mass=70, height=175, age=35, sex='male',   vo2max=50),
        RunnerProfile(mass=65, height=168, age=52, sex='male',   vo2max=38),
        RunnerProfile(mass=58, height=163, age=38, sex='female', vo2max=42),
    ]
    runner_labels = [
        'Man   35y VO2=50',
        'Man   52y VO2=38',
        'Woman 38y VO2=42',
    ]

    # ── Simulated JOS-3 time series (100 min, 1-min steps) ────────────────────
    # cardiac_output: at MET 10, CO rises from ~600 to ~1200-1500 L/h
    # Derived from Gonzalez-Alonso (2008): CO ~20-25 L/min = 1200-1500 L/h
    # 2024: higher MRT -> higher BFsk -> higher CO demand and higher T_core

    def make_jos3_time_series(
        co_start, co_end,             # L/h
        t_core_start, t_core_end,     # degC
        t_cb_start,   t_cb_end,       # degC
        sweat_kg_h,                   # kg/h sweat rate
        bf_skin_start, bf_skin_end,   # L/h total
        ava_zero_at_min=None,         # AVA-closure time (None = stays open)
        n=100
    ):
        series = []
        for i in range(n):
            f = (i / n) ** 0.5   # mild square-root rise -- physiologically plausible
            co   = co_start   + f * (co_end   - co_start)
            tc   = t_core_start + f * (t_core_end - t_core_start)
            tcb  = t_cb_start   + f * (t_cb_end   - t_cb_start)
            bfsk = bf_skin_start + f * (bf_skin_end - bf_skin_start)
            weight_loss_kg = sweat_kg_h * (i / 60)
            ava_h = 0.05 if (ava_zero_at_min and i >= ava_zero_at_min) else 1.2
            series.append(JOS3Outputs(
                t_min            = i,
                cardiac_output   = co,
                t_core_mean      = tc,
                t_cb             = tcb,
                weight_loss_g_s  = weight_loss_kg,  # cumulative kg here
                bf_skin_total    = bfsk,
                bf_ava_hand      = ava_h / 2,
                bf_ava_foot      = ava_h / 2,
            ))
        return series

    # DtD 2024: high MRT (42 degC), high CO demand, AVA closes at ~70 min
    # DtD 2025: low MRT (34 degC), lower CO demand, AVA stays open
    scenario = {
        '2024': {
            'co':        (800, 1480),
            't_core':    (37.0, 40.4),
            't_cb':      (36.8, 39.8),
            'sweat_kgh': 1.5,
            'bf_skin':   (80, 480),
            'ava_close': 70,
        },
        '2025': {
            'co':        (780, 1220),
            't_core':    (37.0, 39.5),
            't_cb':      (36.8, 39.1),
            'sweat_kgh': 1.1,
            'bf_skin':   (80, 340),
            'ava_close': None,
        },
    }

    # ── Output ─────────────────────────────────────────────────────────────────
    for edition, p in scenario.items():
        print(f"\n{'─' * 72}")
        print(f"  DtD {edition}  |  MRT {'~42degC' if edition=='2024' else '~34degC'}  |  "
              f"T_air {'~24degC' if edition=='2024' else '~16degC'}")
        print(f"{'─' * 72}")

        hdr = (f"{'Runner':<18} | {'HR_max':>6} | {'HR_peak':>7} | {'HR%res':>6} | "
               f"{'CVS_max':>7} | {'CO_res_min':>10} | {'Decomp':>8} | "
               f"{'AVA_cl':>7} | {'Dehy%':>6}")
        print(hdr)
        print('-' * len(hdr))

        for runner, label in zip(runners, runner_labels):
            series = make_jos3_time_series(
                co_start=p['co'][0], co_end=p['co'][1],
                t_core_start=p['t_core'][0], t_core_end=p['t_core'][1],
                t_cb_start=p['t_cb'][0], t_cb_end=p['t_cb'][1],
                sweat_kg_h=p['sweat_kgh'],
                bf_skin_start=p['bf_skin'][0], bf_skin_end=p['bf_skin'][1],
                ava_zero_at_min=p['ava_close'],
            )

            cvr = link_cvr_to_jos3(runner, series)
            m = CVRModel(runner)

            decomp_t = cvr.decompensation_time()
            ava_t    = cvr.ava_closure_time()
            final    = cvr.final_state()

            decomp_str = f"{decomp_t:.0f}min" if decomp_t is not None else "--"
            ava_str    = f"{ava_t:.0f}min"    if ava_t    is not None else "--"

            print(
                f"{label:<18} | {m.HR_max:>6.0f} | {cvr.max_HR():>7.1f} | "
                f"{final.HR_reserve_pct:>5.1f}% | {cvr.max_CVS_index():>6.1%} | "
                f"{cvr.min_CO_reserve():>9.1f}L | {decomp_str:>8} | "
                f"{ava_str:>7} | {final.dehydration_pct:>5.1f}%"
            )

    print(f"\n{'─' * 72}")
    print("COLUMNS:")
    print("  HR_max    : age-dependent maximum heart rate (Tanaka 2001)")
    print("  HR_peak   : estimated peak HR during the run (Lloyd 2022 Eq.2: HR=CO/SV)")
    print("  HR%res    : % Karvonen HR reserve used at the final time step")
    print("  CVS_max   : max cardiovascular load (CO_demand/CO_max)")
    print("  CO_res_min: minimum CO reserve (L/min) over the whole run")
    print("  Decomp    : time of first CO_reserve < 2.0 L/min")
    print("  AVA_cl    : time of AVA closure (earliest detectable signal)")
    print("  Dehy%     : final dehydration (% body-weight loss)")
    print()
    print("HEART-RATE ESTIMATION SOURCES:")
    print("  SV_max  = 40.59 + 24.81 x VO2max_abs  (Lloyd 2022, Eq.6)")
    print("  HR_max  = 208 - 0.7 x age              (Tanaka 2001)")
    print("  HR      = CO_demand / SV               (Lloyd 2022, Eq.2)")
    print("  SV corr = -3 mL/degC above T_core 38degC (Gonzalez-Alonso 2008)")
    print()
    print("INTEGRATION IN HESTIA_Data_Engine.py: see link_cvr_to_jos3()'s docstring")
    print(f"{'=' * 72}")
