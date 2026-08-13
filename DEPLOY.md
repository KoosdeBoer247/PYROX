# PYROX app — file inventory and deployment

Complete, verified set for the PYROX Streamlit apps, as of 12 August 2026.
Everything in this folder goes in the **root** of the GitHub repo
(`KoosdeBoer247/PYROX`) — no subfolders. Verified from a clean directory:
all modules compile, all acceptance tests pass, and all three apps boot
without errors. This is the short version of `HANDLEIDING.md` — see that
file for full troubleshooting detail.

## What each file is

| File | Role | Change this? |
|---|---|---|
| `app.py` | **General population app** — main file for deployment 1 | Yes, entry point 1 |
| `app_athletes.py` | **Athlete app** (beginner→elite) — main file for deployment 2 | Yes, entry point 2 |
| `app_beleid.py` | **Simplified policy/organiser view** — main file for deployment 3 | Yes, entry point 3 |
| `pyrox_bridge.py` | Shared PYROX execution + pace→MET conversion, used by ALL THREE apps | App-layer |
| `hestia_bridge.py` | HESTIA quick-estimate / full-precision entry points, caching | App-layer |
| `requirements.txt` | Python dependencies for Streamlit Cloud | Only when adding a library |
| `decision_support.py` | Risk/strain explainer, hourly activity/rest guide, WBGT↔UTCI divergence check | App-layer, not model |
| `gpx_route.py` | GPX parsing, race pace/exposure profiles, course map | App-layer |
| `terrain_lookup.py` | ESA WorldCover land cover → per-segment roughness → terrain-varying WBGT/MRT | App-layer |
| `pyrox_model.py` | **PYROX model core** (paper Sec 2.2) | No — keep in sync with the suite |
| `pyrox_groups.py` | **Published 23-group roster** | No — keep in sync with the suite |
| `pyrox_revised_calibration.py` | Revised calibration + MET term, with derivation | No — keep in sync with the suite |
| `Thermopoulos_Data_Engine.py` | **Weather acquisition + thermal indices** (WBGT, UTCI, MRT, UHI, coastal) | No — keep in sync with the suite |
| `thermopoulos_loader.py` | Reads the engine's Excel output into PYROX inputs | No — keep in sync with the suite |
| `hestia_model.py` | **HESTIA individual-tier model** (JOS-3, CVR, EHS outcomes, post-finish module) | No — keep in sync with the suite |
| `HESTIA_CVR_Module_v2.py` | Cardiovascular reserve module (Lloyd et al. 2022) | No — keep in sync with the suite |
| `HESTIA_CVR_Console.py` | Supporting file for the CVR module | No — keep in sync with the suite |
| `HESTIA_ControlFailure_Module.py` | Thermoregulatory control-failure metric (experimental) | No — keep in sync with the suite |
| `test_revised_calibration.py` | Acceptance tests (T1–T8) for the revised calibration | Run after any calibration change |
| `README.md` | Scientific scope and validation status | Update when scope changes |

The eight "keep in sync" files are byte-identical to the HESTIA-PYROX
suite, with one exception: `hestia_model.py` carries two small, documented
deviations (a defensive `timezonefinder` import, a cached `get_air_quality`)
— see the docstrings in that file. Do not edit these files here — edit them
in the suite and copy across, so the app can never silently drift from the
research code.

## Deploying

1. Upload every file in this folder to the repo root (GitHub → Add file →
   **Upload files**; drag the files in rather than pasting contents, which
   avoids the line-break corruption that caused an earlier SyntaxError).
2. Streamlit Cloud auto-redeploys on commit. If not: Manage app → Reboot.
3. Main file path: `app.py` for the general app, `app_athletes.py` for the
   athlete app, `app_beleid.py` for the simplified policy view. All three
   deployments can point at this same repo — one set of modules, three
   front-ends, so a fix reaches all three at once.
4. **Advanced settings → Python version: 3.12** for every deployment — this
   cannot be changed after the app is created. See `HANDLEIDING.md` §4 for
   why.

## Running the tests

```
python test_revised_calibration.py
```
Expect: `All acceptance tests passed.`

## API quota note

Open-Meteo's free tier allows 10,000 calls/day, 5,000/hour, 600/minute,
counted **per IP** — so several Streamlit apps on the same host share one
quota. Cache lifetimes in `app.py` are tuned to this (see
`CACHE_TTL_GEOCODE` / `CACHE_TTL_FORECAST` / `CACHE_TTL_HISTORICAL`):
geocoding 30 days, forecasts 2 hours, historical ERA5 7 days, climatology
30 days. Re-running the same location within those windows costs no quota.

The 30-year climatology option is by far the most expensive feature (one
request per year of history) — leave it off while testing.

## Known limitations, deliberately kept visible in the UI

- PYROX's **population tier has no event-level validation** against real
  incident data. The r=0.866 correlation, Falmouth hindcasts and IRONMAN
  Hoorn results belong to HESTIA's individual tier, not PYROX.
- HESTIA's individual-tier EHS estimate is a **PROVISIONAL** dose-response
  fit (n=120 per scenario), re-fit 2026-08-10 after a clothing-insulation
  fix (clo 0.5→0.2) that had been causing systematic over-prediction. See
  `README.md` → "HESTIA individual tier" and `GEBRUIKSAANWIJZING.md` §3.6.
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
