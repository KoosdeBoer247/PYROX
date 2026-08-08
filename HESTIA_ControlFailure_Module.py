# -*- coding: utf-8 -*-
"""
HESTIA_ControlFailure_Module.py
===============================
Thermoregulatory Control Failure (TCF) module for HESTIA.

Purpose
-------
This module does NOT diagnose clinical exertional heat stroke (EHS).
It quantifies a mechanistic risk state: loss of thermoregulatory control
reserve during or shortly after exercise.

The central metric is the Thermal-CVR Deficit Dose:

    integral max(0, T_rect - T_CRIT) * max(0, CO_RESERVE_LIMIT - CO_reserve) dt

Default:
    T_CRIT = 40.5 deg C
    CO_RESERVE_LIMIT = 0.0 L/min

Units:
    deg C * L/min * min = deg C * L

Interpretation
--------------
The metric integrates three conditions:
  1. critical core temperature excess,
  2. cardiovascular demand-capacity deficit,
  3. duration of that combined state.

It is intended as a hypothesis-driven, physiologically informed marker for
"thermoregulatory control failure", not as a validated EHS incidence model.
Clinical EHS probability should be calibrated separately against event-level
medical data.

Scientific rationale
--------------------
* EHS diagnosis requires high core temperature plus central nervous system
  dysfunction; temperature alone is not sufficient.
* Heat storage is time-dependent; degree-minute concepts are common in heat
  strain interpretation.
* During exercise in heat, cardiac output is shared between exercising muscle,
  skin blood flow, and blood pressure maintenance. A negative CO reserve in
  HESTIA is interpreted as demand exceeding estimated circulatory capacity.
* After finishing, loss of the muscle pump can reduce venous return and
  cardiac output while heat continues to move from active muscle to the core.

Key sources to cite in documentation:
  - Casa DJ et al. National Athletic Trainers' Association position statement:
    Exertional heat illnesses. J Athl Train. 2015.
  - Roberts WO. Determining a "do not start" temperature for a marathon on the
    basis of adverse outcomes. Med Sci Sports Exerc. 2010.
  - Rowell LB. Human cardiovascular adjustments to exercise and thermal stress.
    Physiol Rev. 1974.
  - Gonzalez-Alonso J et al. Haemodynamics and the human cardiovascular
    response to heat stress. J Physiol. 2008.
  - Lloyd A et al. A mathematical model for predicting cardiovascular responses
    at rest and during exercise in demanding environmental conditions.
    J Appl Physiol. 2022.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class ControlFailureConfig:
    """Configuration for the Thermoregulatory Control Failure metric."""

    t_rect_crit: float = 40.5
    co_reserve_limit: float = 0.0
    default_step_min: float = 10.0
    relevant_dose: float = 5.0
    severe_dose: float = 20.0
    extreme_dose: float = 60.0


DEFAULT_CONFIG = ControlFailureConfig()


def thermal_excess(t_rect: float, config: ControlFailureConfig = DEFAULT_CONFIG) -> float:
    """Return T_rect excess above the critical threshold [deg C]."""
    return max(0.0, float(t_rect) - config.t_rect_crit)


def co_deficit(co_reserve: float, config: ControlFailureConfig = DEFAULT_CONFIG) -> float:
    """Return cardiovascular demand-capacity deficit [L/min]."""
    if co_reserve is None:
        return 0.0
    try:
        val = float(co_reserve)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(val):
        return 0.0
    return max(0.0, config.co_reserve_limit - val)


def control_failure_increment(
    t_rect: float,
    co_reserve: float,
    dt_min: float,
    config: ControlFailureConfig = DEFAULT_CONFIG,
) -> float:
    """
    Return one time-step Thermal-CVR Deficit Dose increment [deg C * L].

    Formula:
        max(0, T_rect - T_crit) * max(0, CO_limit - CO_reserve) * dt_min
    """
    return thermal_excess(t_rect, config) * co_deficit(co_reserve, config) * max(0.0, dt_min)


def classify_dose(dose: float, config: ControlFailureConfig = DEFAULT_CONFIG) -> str:
    """Classify total control-failure dose into provisional severity bands."""
    if dose <= 0:
        return "none"
    if dose < config.relevant_dose:
        return "brief"
    if dose < config.severe_dose:
        return "relevant"
    if dose < config.extreme_dose:
        return "severe"
    return "extreme"


def _parse_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M")
        except ValueError:
            return None


def _dt_minutes(records: Sequence[Mapping[str, Any]], idx: int, config: ControlFailureConfig) -> float:
    if idx <= 0:
        return 0.0
    t_now = _parse_time(records[idx].get("time"))
    t_prev = _parse_time(records[idx - 1].get("time"))
    if t_now is None or t_prev is None:
        return config.default_step_min
    dt = (t_now - t_prev).total_seconds() / 60.0
    if dt <= 0 or not np.isfinite(dt):
        return config.default_step_min
    return dt


def analyse_participant(
    records: Sequence[Mapping[str, Any]],
    config: ControlFailureConfig = DEFAULT_CONFIG,
) -> Dict[str, Any]:
    """
    Analyse one participant time series.

    The race dose is calculated from every HESTIA time step. Post-finish dose
    is taken from exact post-finish fields when the host script provides them.
    """
    race_dose = 0.0
    race_time_failure = 0.0
    race_time_heat = 0.0
    race_time_cvr_deficit = 0.0
    first_failure_time = None

    peak_t_rect = float("-inf")
    min_co_reserve = float("inf")

    for idx, rec in enumerate(records):
        t_rect = float(rec.get("t_rect", np.nan))
        co_res = rec.get("co_reserve", np.nan)
        dt_min = _dt_minutes(records, idx, config)

        if np.isfinite(t_rect):
            peak_t_rect = max(peak_t_rect, t_rect)
        try:
            co_val = float(co_res)
            if np.isfinite(co_val):
                min_co_reserve = min(min_co_reserve, co_val)
        except (TypeError, ValueError):
            co_val = np.nan

        excess = thermal_excess(t_rect, config) if np.isfinite(t_rect) else 0.0
        deficit = co_deficit(co_val, config)
        race_dose += excess * deficit * dt_min

        if excess > 0:
            race_time_heat += dt_min
        if deficit > 0:
            race_time_cvr_deficit += dt_min
        if excess > 0 and deficit > 0:
            race_time_failure += dt_min
            if first_failure_time is None:
                first_failure_time = rec.get("time")

    last = records[-1] if records else {}
    post_dose = float(last.get("control_failure_dose_postfinish", 0.0) or 0.0)
    post_time = float(last.get("control_failure_time_postfinish_min", 0.0) or 0.0)

    total_dose = race_dose + post_dose
    total_time = race_time_failure + post_time

    if peak_t_rect == float("-inf"):
        peak_t_rect = float("nan")
    if min_co_reserve == float("inf"):
        min_co_reserve = float("nan")

    return {
        "control_failure_dose_race": round(race_dose, 4),
        "control_failure_dose_postfinish": round(post_dose, 4),
        "control_failure_dose_total": round(total_dose, 4),
        "control_failure_time_race_min": round(race_time_failure, 3),
        "control_failure_time_postfinish_min": round(post_time, 3),
        "control_failure_time_total_min": round(total_time, 3),
        "control_failure_any": bool(total_dose > 0),
        "control_failure_relevant": bool(total_dose >= config.relevant_dose),
        "control_failure_severe": bool(total_dose >= config.severe_dose),
        "control_failure_extreme": bool(total_dose >= config.extreme_dose),
        "control_failure_class": classify_dose(total_dose, config),
        "first_control_failure_time": first_failure_time,
        "thermal_excess_time_min": round(race_time_heat, 3),
        "cvr_deficit_time_min": round(race_time_cvr_deficit, 3),
        "peak_t_rect": round(peak_t_rect, 4),
        "min_co_reserve": round(min_co_reserve, 4),
    }


def analyse_population(
    all_results: Sequence[Sequence[Mapping[str, Any]]],
    config: ControlFailureConfig = DEFAULT_CONFIG,
) -> Dict[str, Any]:
    """Analyse a HESTIA Monte Carlo result set and return population summary."""
    per_participant = [analyse_participant(records, config) for records in all_results]
    if not per_participant:
        return {"per_participant": [], "summary": {}}

    dose_total = np.array([p["control_failure_dose_total"] for p in per_participant], dtype=float)
    dose_race = np.array([p["control_failure_dose_race"] for p in per_participant], dtype=float)
    dose_pf = np.array([p["control_failure_dose_postfinish"] for p in per_participant], dtype=float)
    time_total = np.array([p["control_failure_time_total_min"] for p in per_participant], dtype=float)
    time_cvr = np.array([p["cvr_deficit_time_min"] for p in per_participant], dtype=float)
    time_heat = np.array([p["thermal_excess_time_min"] for p in per_participant], dtype=float)

    n = len(per_participant)
    summary = {
        "control_failure_n": n,
        "control_failure_t_rect_crit": config.t_rect_crit,
        "control_failure_co_reserve_limit": config.co_reserve_limit,
        "control_failure_units": "degC*L",
        "control_failure_dose_p50": float(np.nanpercentile(dose_total, 50)),
        "control_failure_dose_p95": float(np.nanpercentile(dose_total, 95)),
        "control_failure_dose_p99": float(np.nanpercentile(dose_total, 99)),
        "control_failure_dose_p999": float(np.nanpercentile(dose_total, 99.9)),
        "control_failure_dose_max": float(np.nanmax(dose_total)),
    
        "control_failure_dose_race_p95": float(np.nanpercentile(dose_race, 95)),
        "control_failure_dose_postfinish_p95": float(np.nanpercentile(dose_pf, 95)),
        "control_failure_time_p50": float(np.nanpercentile(time_total, 50)),
        "control_failure_time_p95": float(np.nanpercentile(time_total, 95)),
        "pct_control_failure_any": float(np.mean(dose_total > 0) * 100),
        "pct_control_failure_relevant": float(np.mean(dose_total >= config.relevant_dose) * 100),
        "pct_control_failure_severe": float(np.mean(dose_total >= config.severe_dose) * 100),
        "pct_control_failure_extreme": float(np.mean(dose_total >= config.extreme_dose) * 100),
        "pct_cvr_deficit_any": float(np.mean(time_cvr > 0) * 100),
        "pct_thermal_excess_any": float(np.mean(time_heat > 0) * 100),
        "control_failure_relevant_threshold": config.relevant_dose,
        "control_failure_severe_threshold": config.severe_dose,
        "control_failure_extreme_threshold": config.extreme_dose,
    }
    return {"per_participant": per_participant, "summary": summary}


def format_population_summary(summary: Mapping[str, Any]) -> List[str]:
    """Return concise human-readable lines for console output."""
    if not summary:
        return ["Thermoregulatory Control Failure: no data available."]
    return [
        "THERMOREGULATORY CONTROL FAILURE (experimental mechanistic metric)",
        (
            "  Definition : integral max(0, T_rect - "
            f"{summary['control_failure_t_rect_crit']:.1f}) * "
            "max(0, -CO_reserve) dt"
        ),
        f"  Units      : {summary['control_failure_units']}  (deg C * L/min * min)",
        
        
        
        
        
        
        
        f"  Dose P50/P95/P99/P99.9/MAX : {summary['control_failure_dose_p50']:.2f} / "
        f"{summary['control_failure_dose_p95']:.2f} / "
        f"{summary['control_failure_dose_p99']:.2f} / "
        f"{summary['control_failure_dose_p999']:.2f} / "
        f"{summary['control_failure_dose_max']:.2f}",
        f"  Time P50/P95     : {summary['control_failure_time_p50']:.1f} / "
        f"{summary['control_failure_time_p95']:.1f} min",
        f"  Any/relevant/severe/extreme : {summary['pct_control_failure_any']:.1f}% / "
        f"{summary['pct_control_failure_relevant']:.1f}% / "
        f"{summary['pct_control_failure_severe']:.1f}% / "
        f"{summary['pct_control_failure_extreme']:.1f}%",
        (
            "  Note       : not a clinical EHS diagnosis; calibrate against "
            "event medical data before converting to EHS probability."
        ),
    ]

