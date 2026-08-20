# -*- coding: utf-8 -*-
"""
local_storage.py
=================
Local-only persistence for the personal (individual_engine.py) app.
Everything this module writes stays on the machine it runs on -- there
is no network code anywhere in this file, and nothing here is ever
passed to Thermopoulos_Data_Engine or any other module that makes
outbound calls.

WHAT IS STORED, AND WHERE
--------------------------
Two kinds of local file, both plain JSON, both under one per-user data
directory this module resolves itself (no path is ever asked of, or
sent to, anything outside this machine):

    profiles/<slug>.json   -- a saved PersonalInputs, so someone doesn't
                               have to retype height/weight/age/pace
                               every time. Named by the person (e.g.
                               "koos", "buurman-jan") -- several people
                               can keep separate profiles on one shared
                               machine.
    history/<slug>/<ts>.json
                            -- one saved assessment result: the scenario
                               that was run, the resulting T_rect/
                               CO_reserve bands, conjunction fraction,
                               and EHS interval. Raw per-ensemble-member
                               traces (IndividualAssessment.all_traces)
                               are NOT included by default -- they are
                               large and reconstructible by re-running
                               the same inputs -- unless include_traces
                               is explicitly requested.

Default location:
    Windows  ->  %APPDATA%\\PYROX
    macOS    ->  ~/Library/Application Support/PYROX
    Linux    ->  $XDG_DATA_HOME/PYROX or ~/.local/share/PYROX
Overridable via the PYROX_DATA_DIR environment variable (useful for
tests, or for pointing at a specific folder e.g. on a USB drive).

NOT DONE HERE, AND WHY THAT IS A DELIBERATE OMISSION
------------------------------------------------------
Files are plain JSON, not encrypted at rest. The stated requirement was
that personal data and outcomes stay ON the machine running the app --
that is satisfied by never transmitting the data, which this module
does not do. Encryption-at-rest is a separate, additional guarantee
(protects against another user of the SAME machine, or a stolen disk,
reading the file) that was not asked for and would need a passphrase
UX decision this module should not make unilaterally. If wanted later,
it is a contained addition: encrypt the JSON bytes with a
passphrase-derived key (e.g. via the stdlib's hashlib.pbkdf2_hmac,
no new dependency needed for a basic version) before the two
`path.write_text(...)` calls below, and reverse it in the two
`path.read_text(...)` calls. Flagging it here rather than silently
deciding either way.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from individual_engine import PersonalInputs, EventScenario, IndividualAssessment


# =============================================================================
# Where things live
# =============================================================================
def data_dir() -> Path:
    """Resolve (and create if needed) the local data directory. Never
    reads from or writes to anything network-related."""
    override = os.environ.get("PYROX_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "PYROX"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "PYROX"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "PYROX"
    base.mkdir(parents=True, exist_ok=True)
    (base / "profiles").mkdir(exist_ok=True)
    (base / "history").mkdir(exist_ok=True)
    return base


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Name must contain at least one letter or digit.")
    return slug


# =============================================================================
# Profiles (PersonalInputs)
# =============================================================================
def list_profiles() -> list[str]:
    """Names of saved profiles, most recently modified first."""
    d = data_dir() / "profiles"
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [f.stem for f in files]


def save_profile(name: str, inputs: PersonalInputs) -> Path:
    inputs.validate()
    path = data_dir() / "profiles" / f"{_slugify(name)}.json"
    payload = {"display_name": name, "saved_at": datetime.now().isoformat(timespec="seconds"),
               "inputs": asdict(inputs)}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_profile(name: str) -> PersonalInputs:
    path = data_dir() / "profiles" / f"{_slugify(name)}.json"
    if not path.exists():
        raise FileNotFoundError(f"No saved profile named '{name}'.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PersonalInputs(**payload["inputs"])


def delete_profile(name: str) -> None:
    path = data_dir() / "profiles" / f"{_slugify(name)}.json"
    path.unlink(missing_ok=True)


# =============================================================================
# Assessment history
# =============================================================================
def _assessment_to_jsonable(a: IndividualAssessment, include_traces: bool) -> dict:
    out = {
        "n_ensemble":            a.n_ensemble,
        "minutes":               list(a.minutes),
        "phase":                 list(a.phase),
        "median_stop_minute":    a.median_stop_minute,
        "t_rect_median":         a.t_rect_median.tolist(),
        "t_rect_lo":             a.t_rect_lo.tolist(),
        "t_rect_hi":             a.t_rect_hi.tolist(),
        "co_reserve_median":     a.co_reserve_median.tolist(),
        "co_reserve_lo":         a.co_reserve_lo.tolist(),
        "co_reserve_hi":         a.co_reserve_hi.tolist(),
        "conjunction_fraction":  a.conjunction_fraction,
        "ehs_hits":              a.ehs_hits,
        "ehe_hits":              a.ehe_hits,
        "eac_hits":              a.eac_hits,
        "ehe_fraction":          a.ehe_fraction,
        "ehe_dose_mean":         a.ehe_dose_mean,
        "ehe_dose_among_hits":   a.ehe_dose_among_hits,
        "eac_fraction":          a.eac_fraction,
        "eac_dose_mean":         a.eac_dose_mean,
        "eac_dose_among_hits":   a.eac_dose_among_hits,
        "ehs_interval":          a.ehs_interval,
        "mean_t_air_c":          a.mean_t_air_c,
        "city_name":             a.city_name,
        "meteo": {
            "time": [str(t) for t in a.meteo["time"]],
            "t_air": np.asarray(a.meteo["t_air"]).tolist(),
            "wbgt": np.asarray(a.meteo["wbgt"]).tolist(),
            "utci": np.asarray(a.meteo["utci"]).tolist(),
            "mrt": np.asarray(a.meteo["mrt"]).tolist(),
        },
    }
    if include_traces:
        out["all_traces"] = a.all_traces
    return out


def assessment_from_jsonable(payload: dict) -> IndividualAssessment:
    """Reconstruct an IndividualAssessment from a saved history entry
    (lists back to numpy arrays). all_traces is only present if it was
    saved with include_traces=True; otherwise it comes back empty."""
    meteo = payload.get("meteo", {})
    return IndividualAssessment(
        n_ensemble=payload["n_ensemble"],
        minutes=payload["minutes"],
        phase=payload["phase"],
        median_stop_minute=payload["median_stop_minute"],
        t_rect_median=np.array(payload["t_rect_median"]),
        t_rect_lo=np.array(payload["t_rect_lo"]),
        t_rect_hi=np.array(payload["t_rect_hi"]),
        co_reserve_median=np.array(payload["co_reserve_median"]),
        co_reserve_lo=np.array(payload["co_reserve_lo"]),
        co_reserve_hi=np.array(payload["co_reserve_hi"]),
        conjunction_fraction=payload["conjunction_fraction"],
        ehs_hits=payload.get("ehs_hits", 0),
        ehe_hits=payload.get("ehe_hits", 0),
        eac_hits=payload.get("eac_hits", 0),
        ehe_fraction=payload.get("ehe_fraction", 0.0),
        ehe_dose_mean=payload.get("ehe_dose_mean", 0.0),
        ehe_dose_among_hits=payload.get("ehe_dose_among_hits", 0.0),
        eac_fraction=payload.get("eac_fraction", 0.0),
        eac_dose_mean=payload.get("eac_dose_mean", 0.0),
        eac_dose_among_hits=payload.get("eac_dose_among_hits", 0.0),
        ehs_interval=payload["ehs_interval"],
        mean_t_air_c=payload["mean_t_air_c"],
        city_name=payload["city_name"],
        meteo={
            "time": meteo.get("time", []),
            "t_air": np.array(meteo.get("t_air", [])),
            "wbgt": np.array(meteo.get("wbgt", [])),
            "utci": np.array(meteo.get("utci", [])),
            "mrt": np.array(meteo.get("mrt", [])),
        },
        all_traces=payload.get("all_traces", []),
    )


def save_assessment(profile_name: str, scenario: EventScenario,
                     assessment: IndividualAssessment, *,
                     include_traces: bool = False) -> Path:
    slug = _slugify(profile_name)
    hist_dir = data_dir() / "history" / slug
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = hist_dir / f"{ts}.json"
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "scenario": {
            "location_query": scenario.location_query,
            "start_local": scenario.start_local.isoformat(),
            "duration_minutes": scenario.duration_minutes,
            "use_historical": scenario.use_historical,
            "gpx_path": scenario.gpx_path,
            "clo_value": scenario.clo_value,
            "terrain_key": scenario.terrain_key,
        },
        "assessment": _assessment_to_jsonable(assessment, include_traces),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def list_history(profile_name: str) -> list[dict]:
    """Metadata for each saved run (newest first) -- enough to show in a
    picker without loading every file's full bands."""
    hist_dir = data_dir() / "history" / _slugify(profile_name)
    if not hist_dir.exists():
        return []
    entries = []
    for f in sorted(hist_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entries.append({
            "path": f,
            "saved_at": payload.get("saved_at"),
            "location": payload["scenario"]["location_query"],
            "start_local": payload["scenario"]["start_local"],
            "mean_t_air_c": payload["assessment"]["mean_t_air_c"],
            "conjunction_fraction": payload["assessment"]["conjunction_fraction"],
        })
    return entries


def load_assessment(path: Path) -> tuple[EventScenario, IndividualAssessment]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    s = payload["scenario"]
    scenario = EventScenario(
        location_query=s["location_query"],
        start_local=pd.Timestamp(s["start_local"]),
        duration_minutes=s["duration_minutes"],
        use_historical=s["use_historical"],
        gpx_path=s.get("gpx_path"),
        clo_value=s.get("clo_value", 0.2),
        terrain_key=s.get("terrain_key", "3"),
    )
    return scenario, assessment_from_jsonable(payload["assessment"])
