# PYROX app — file inventory and deployment

Complete, verified set for the PYROX Streamlit apps, as of 21 August 2026.
Everything in this folder goes in the **root** of the GitHub repo
(`KoosdeBoer247/PYROX`) — no subfolders. Verified from a clean directory:
all modules compile, all acceptance tests pass, and all five apps boot
without errors. This is the short version of `HANDLEIDING.md` — see that
file for full troubleshooting detail.

## What each file is

| File | Role | Change this? |
|---|---|---|
| `app.py` | **General population app** (PYROX tier) — main file for deployment 1 | Yes, entry point 1 |
| `app_athletes.py` | **Athlete app** (PYROX tier, beginner→elite) — main file for deployment 2 | Yes, entry point 2 |
| `app_beleid.py` | **Simplified policy/organiser view** (HESTIA tier) — main file for deployment 3 | Yes, entry point 3 |
| `app_persoonlijk.py` | **One person's own assessment, local-only** (HESTIA tier) — main file for deployment 4 | Yes, entry point 4 |
| `app_klimaatprojectie.py` | **Klimaathoudbaarheid van een jaarlijks evenement** (year-over-year EHE/EHS projection vs. 1996–2025) — main file for deployment 5 | Yes, entry point 5 |
| `pyrox_bridge.py` | Shared PYROX execution + pace→MET conversion, used by `app.py`/`app_athletes.py`/`app_klimaatprojectie.py` | App-layer |
| `hestia_bridge.py` | HESTIA quick-estimate / full-precision entry points, caching, used by `app_beleid.py`/`app_athletes.py`/`app_klimaatprojectie.py` | App-layer |
| `individual_engine.py` | One-person HESTIA wrapper for `app_persoonlijk.py` — personal ensemble, EHE/EAC criteria | App-layer |
| `individual_report.py` | Word-report generator for `app_persoonlijk.py` | App-layer |
| `local_storage.py` | Local-only (no network) persistence for `app_persoonlijk.py` | App-layer |
| `uncertainty.py` | Sampling + anchor interval for the EHS estimate, used by `app_beleid.py`/`app_persoonlijk.py` | App-layer |
| `requirements.txt` | Python dependencies for Streamlit Cloud | Only when adding a library |
| `decision_support.py` | Risk/strain explainer, hourly activity/rest guide, WBGT↔UTCI divergence check | App-layer, not model |
| `gpx_route.py` | GPX parsing, race pace/exposure profiles, course map | App-layer |
| `terrain_lookup.py` | ESA WorldCover land cover → per-segment roughness → terrain-varying WBGT/MRT | App-layer |
| `pyrox_model.py` | **PYROX model core** (paper Sec 2.2) | No — keep in sync with the suite |
| `pyrox_groups.py` | **Published 23-group roster** | No — keep in sync with the suite |
| `pyrox_revised_calibration.py` | Revised calibration + MET term, with derivation | No — keep in sync with the suite |
| `Thermopoulos_Data_Engine.py` | **Weather acquisition + thermal indices** (WBGT, UTCI, MRT, UHI, coastal) | No — keep in sync with the suite |
| `thermopoulos_loader.py` | Reads the engine's Excel output into PYROX inputs | No — keep in sync with the suite |
| `hestia_model.py` | **HESTIA individual-tier model** (JOS-3, CVR, EHS/EHE/EAC outcomes, post-finish module) | No — keep in sync with the suite |
| `HESTIA_CVR_Module_v2.py` | Cardiovascular reserve module (Lloyd et al. 2022) | No — keep in sync with the suite |
| `HESTIA_CVR_Console.py` | Supporting file for the CVR module | No — keep in sync with the suite |
| `HESTIA_ControlFailure_Module.py` | Thermoregulatory control-failure metric (experimental) | No — keep in sync with the suite |
| `test_revised_calibration.py` | Acceptance tests (T1–T8) for the revised PYROX calibration | Run after any PYROX-tier change |
| `test_cvr_freeze_fix.py` | Regression tests: CO_reserve NaN-after-freeze fix, CO_reserve monotonicity fix | Run after any HESTIA/CVR change |
| `test_uncertainty.py` | Regression tests for the sampling + anchor interval | Run after any change to `uncertainty.py` |
| `test_individual_engine.py` | Regression tests for `individual_engine.py` / `app_persoonlijk.py` | Run after any change touching the personal app |
| `README.md` | Scientific scope and validation status | Update when scope changes |

`app_klimaatprojectie.py` adds no new core-model file — it reuses
`hestia_bridge.run_quick_estimate()` and `Thermopoulos_Data_Engine.py`
exactly as `app.py`/`app_beleid.py` do, plus a self-contained Theil-Sen
trend estimator (`scipy.stats.theilslopes`, added to `requirements.txt`).

The nine "keep in sync" files are byte-identical to the HESTIA-PYROX
suite, with one exception: `hestia_model.py` carries two small, documented
deviations (a defensive `timezonefinder` import, a cached `get_air_quality`)
— see the docstrings in that file. Do not edit these files here — edit them
in the suite and copy across, so the app can never silently drift from the
research code.

## Deploying

1. Upload every file in this folder to the repo root (GitHub → Add file →
   **Upload files**; drag the files in rather than pasting contents, which
   avoids the line-break corruption that caused an earlier SyntaxError).
   Upload the complete set in one go rather than a partial update — a
   deployment reads whatever the repo's current state is, so an app-layer
   file (e.g. `individual_engine.py`) and a core-model file
   (`hestia_model.py`) that were never tested together locally can end up
   paired for the first time on the live app.
2. Streamlit Cloud auto-redeploys on commit. If not: Manage app → Reboot.
3. Main file path: `app.py` for the general app, `app_athletes.py` for the
   athlete app, `app_beleid.py` for the simplified policy view,
   `app_persoonlijk.py` for the one-person local assessment,
   `app_klimaatprojectie.py` for the multi-year climate-shift projection.
   All five deployments can point at this same repo — one set of
   modules, five front-ends, so a fix reaches all five at once (within
   the tier it belongs to — see `README.md`'s PYROX/HESTIA split).
4. **Advanced settings → Python version: 3.12** for every deployment — this
   cannot be changed after the app is created. See `HANDLEIDING.md` §4 for
   why.

## Running the tests

```
python test_revised_calibration.py   # PYROX population-tier calibration
python test_cvr_freeze_fix.py        # HESTIA CVR fixes (co_reserve NaN, monotonicity)
python test_uncertainty.py           # sampling + anchor interval
python test_individual_engine.py     # app_persoonlijk.py / individual_engine.py
```
Expect: all four report every test group passed.

## API quota note

Open-Meteo's free tier allows 10,000 calls/day, 5,000/hour, 600/minute,
counted **per IP** — so several Streamlit apps on the same host share one
quota. Cache lifetimes in `app.py` are tuned to this (see
`CACHE_TTL_GEOCODE` / `CACHE_TTL_FORECAST` / `CACHE_TTL_HISTORICAL`):
geocoding 30 days, forecasts 2 hours, historical ERA5 7 days, climatology
30 days. Re-running the same location within those windows costs no quota.

The 30-year climatology option is by far the most expensive feature (one
request per year of history) — leave it off while testing.

`app_klimaatprojectie.py` is the heaviest single run in the whole suite:
one historical fetch per reference year (1996–2025, ~30 calls), cached
6 hours per (location, date, terrain) combination via `st.cache_data`.
Re-running the same event configuration within that window costs no
extra quota; changing the location or date starts a fresh 30-call fetch.

## Known limitations, deliberately kept visible in the UI

- PYROX's **population tier has no event-level validation** against real
  incident data. The r=0.866 correlation, Falmouth hindcasts and IRONMAN
  Hoorn results belong to HESTIA's individual tier, not PYROX.
- HESTIA's individual-tier EHS estimate is a **PROVISIONAL** dose-response
  fit (n=120 per scenario), re-fit 2026-08-10 after a clothing-insulation
  fix (clo 0.5→0.2) that had been causing systematic over-prediction. See
  `README.md` → "HESTIA individual tier" and `GEBRUIKSAANWIJZING.md` §3.6.
- **EHE and EAC (added 2026-08-17) are UNCALIBRATED.** Both are shown as
  a percentage of the simulated population, never a rate per 1000 —
  meeting the mechanistic criterion is not the same as the clinical
  syndrome, and neither has an observed-incidence fit. EAC has a
  candidate anchor (1.53/1000, Gothenburg Half Marathon) not yet used to
  calibrate anything. See `README.md` → "Three heat-illness endpoints".
- **`app_persoonlijk.py`'s local-only privacy guarantee applies only to
  whoever runs the process.** A shared URL (including a Streamlit Cloud
  deployment) moves "local machine" to the server or host account, not
  the visitor's device — there is no configuration of this app that
  gives a shared link the same guarantee as running it yourself. See
  `GEBRUIKSAANWIJZING.md` §3.9.
- `final_risk` is **dimensionless** — meaningful only relative to the
  mild-summer and Paris 2003 reference scenarios shown beside it, not as a
  probability.
- WBGT under-weights radiant load (0.7 wet-bulb / 0.2 globe / 0.1 dry-bulb).
  The activity/rest guide flags hours where WBGT reads "safe" but UTCI is
  ≥32°C, rather than letting them pass silently.
- **ESA WorldCover fetching has not been exercised against the live AWS
  bucket** — the development sandbox had no S3 access. Tile naming follows
  ESA's documented convention and the downstream pipeline is tested, but
  the first real Streamlit Cloud run is the actual test. Any failure falls
  back to the sidebar terrain selector with a visible message.
- UTCI is **not** terrain-adjusted (it is defined at a fixed 10m reference
  wind); only WBGT and MRT vary by land cover.
- GPX timestamps are ignored; pace comes from the values entered in the UI.
- **`app_klimaatprojectie.py`'s future-year EHE/1000 figures are doubly
  indicative**: EHE itself is uncalibrated (see above), and the
  climate-shift projection is a Theil-Sen statistical extrapolation of
  the observed 1996–2025 trend, not a physical climate model or a
  weather forecast for a specific year. It shifts air temperature only —
  humidity, wind and cloud cover are left at their historical values for
  that calendar day. Built for indicative conversations with event
  organisers, not as a validated forecast; the in-app expander states
  this every time it is run.
