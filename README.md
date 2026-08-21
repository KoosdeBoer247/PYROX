# PYROX — heat-risk web app

An interactive web interface over the Thermopoulos Data Engine (weather
acquisition and thermal-index processing), PYROX (population-tier
heat-strain model), and HESTIA (individual-tier cardiovascular Monte Carlo
model). Five Streamlit front-ends share the same modules — two run on the
PYROX population tier, three on the HESTIA individual tier:

| App | Entry point | Tier | Audience |
|---|---|---|---|
| PYROX | `app.py` | PYROX | General population, occupational groups, policy |
| PYROX Participants | `app_athletes.py` | PYROX | Runners and walkers, event organisers — full methodology |
| PYROX Beleid | `app_beleid.py` | HESTIA | Policymakers/organisers who need one race's headline result, without the research-level caveats |
| PYROX Persoonlijk | `app_persoonlijk.py` | HESTIA | One named individual's own assessment for one event, run entirely on their own machine (see "Privacy architecture" below) |
| PYROX Klimaatprojectie | `app_klimaatprojectie.py` | HESTIA | Event organisers weighing whether a fixed yearly date/location stays viable as the climate shifts — year-over-year EHE/EHS projection against the 1996–2025 reference period (see "Klimaathoudbaarheid projection" below) |

PYROX and HESTIA are deliberately separate model architectures, not one
wrapping the other — `pyrox_model.py`/`pyrox_bridge.py`/`pyrox_groups.py`
never call into `hestia_model.py`/`HESTIA_CVR_Module_v2.py`, or vice versa.
PYROX estimates population-wide heat strain across broad groups; HESTIA
simulates one specific person or a targeted group's individual physiology
(JOS-3 thermoregulation + cardiovascular reserve). A fix to one tier does
not touch the other — see "Recent HESTIA-tier fixes" below for exactly
which apps a given change reaches.

This document covers the **PYROX population-tier scope** in depth (it
predates the HESTIA integration below and the newer apps, and keeps that
narrower focus deliberately — see "Why the calibration was revised"). For
the HESTIA individual tier, the clo/hydration/dose-response fixes, and
day-to-day usage of all five apps, see `GEBRUIKSAANWIJZING.md`. For
GitHub/Streamlit deployment of all five apps, see `HANDLEIDING.md`.

---

## ⚠️ Read this first: the shipped model is not the published one

This app runs a **revised population-tier calibration**, applied
unconditionally with no option to restore the original values.

Two parameters were re-derived on the 11 of 23 population groups that
exhibited a defect (`max_acclimatization_capacity` and
`recovery_threshold`; the other 12 are left bit-identical to the published
values — see "minimal-intervention principle" below), and a metabolic (MET)
load term was added to the heat-load bridge.

**Correction to an earlier version of this README**: it previously stated
that the r = 0.866 Dam tot Damloop correlation, the Falmouth hindcasts, and
the IRONMAN 70.3 Hoorn test needed to be re-run before publishing anything
built on this calibration. That was a citation error — those results belong
to **HESTIA's individual tier** (`hestia_model.py`, `intercept_estimation.py`,
Newton-calibrated `EP1`/`EP2`/`EP3` intercepts against per-person collapse
and hospital-admission rates), not to PYROX. Neither `pyrox_model.py` nor
`pyrox_groups.py` references DtD, Falmouth, or Hoorn anywhere, before or
after this revision.

**The honest status**: PYROX's population tier has no dedicated event-level
validation against real incident data in this suite, before or after this
change. This revision corrects three internal structural defects and is
defensible on those grounds; it is not a substitute for validating PYROX
against real population-level incident data, which does not yet exist for
this tier. The whole-event Dam tot Damloop estimate referenced in project
notes (~57 expected vs. ~50 actual EHS-related cases) should be traced to
its actual source — a genuine PYROX run or a HESTIA aggregation — before
being cited as evidence for either tier.

The full derivation, the defects it corrects, and the reasoning behind every
value are documented in **`pyrox_revised_calibration.py`**. The original
roster remains untouched in `pyrox_groups.py` for comparison.

---

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py                     # general app
streamlit run app_athletes.py            # runners/walkers, full methodology
streamlit run app_beleid.py              # simplified policy/organiser view
streamlit run app_persoonlijk.py         # one person's own assessment, local-only
streamlit run app_klimaatprojectie.py    # multi-year climate-shift projection for a fixed event date
```

Each opens at `http://localhost:8501` (run one at a time, or on separate
ports with `--server.port`).

Run the acceptance tests:

```bash
python3 test_revised_calibration.py    # PYROX population-tier calibration
python3 test_cvr_freeze_fix.py         # HESTIA CVR fixes (see below)
python3 test_uncertainty.py            # sampling + anchor interval
python3 test_individual_engine.py      # app_persoonlijk.py / individual_engine.py
```

## Free hosting (Streamlit Community Cloud)

1. Put this folder in a GitHub repository.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. "New app" → select the repository → entry point `app.py`, `app_athletes.py`,
   `app_beleid.py`, `app_persoonlijk.py`, or `app_klimaatprojectie.py` →
   Deploy. All five can point at the same repo — one set of modules, five
   front-ends — so a fix reaches all five at once (within the tier it
   belongs to; see above).

See `HANDLEIDING.md` for Python-version pinning and troubleshooting specific
to Streamlit Community Cloud.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface — general population app (PYROX tier) |
| `app_athletes.py` | Streamlit interface — runners/walkers, full methodology (PYROX tier) |
| `app_beleid.py` | Streamlit interface — simplified policy/organiser view (HESTIA tier) |
| `app_persoonlijk.py` | Streamlit interface — one person's own assessment, local-only (HESTIA tier) |
| `app_klimaatprojectie.py` | Streamlit interface — year-over-year EHE/EHS projection vs. 1996–2025 for a fixed yearly event date (HESTIA tier) |
| `Thermopoulos_Data_Engine.py` | Weather acquisition, UHI, MRT, WBGT, UTCI |
| `thermopoulos_loader.py` | Bridge from weather data to daily heat load |
| `pyrox_model.py` | PYROX strain dynamics (paper Sec 2.2) |
| `pyrox_groups.py` | Population group roster, original parameters |
| `pyrox_revised_calibration.py` | Revised parameters, MET term, full rationale |
| `pyrox_bridge.py` | PYROX execution + pace→MET conversion, shared by `app.py`/`app_athletes.py` |
| `hestia_model.py` | HESTIA individual-tier model (JOS-3, CVR, EHS/EHE/EAC outcomes, post-finish module) |
| `hestia_bridge.py` | HESTIA quick-estimate / full-precision entry points, caching, shared by `app_beleid.py`/`app_athletes.py` |
| `HESTIA_CVR_Module_v2.py` | Cardiovascular reserve module (Lloyd et al. 2022) |
| `individual_engine.py` | One-person HESTIA wrapper for `app_persoonlijk.py` — personal ensemble, EHE/EAC criteria, zone-episode classification |
| `individual_report.py` | Word-report generator for `app_persoonlijk.py`, reusing `report_generator.py`'s building blocks |
| `local_storage.py` | Local-only (no network) profile/history persistence for `app_persoonlijk.py` |
| `uncertainty.py` | Sampling + anchor interval around the EHS dose-response estimate; used by both HESTIA-tier apps |
| `decision_support.py` | Hourly activity/rest guidance, WBGT↔UTCI divergence check |
| `gpx_route.py` | GPX parsing, race pace/exposure profiles along a route |
| `terrain_lookup.py` | ESA WorldCover terrain classification (optional) |
| `test_revised_calibration.py` | Acceptance tests for the revised PYROX calibration |
| `test_cvr_freeze_fix.py` | Regression tests: CO_reserve NaN-after-freeze fix, CO_reserve monotonicity fix |
| `test_uncertainty.py` | Regression tests for the sampling + anchor interval |
| `test_individual_engine.py` | Regression tests for `individual_engine.py` / `app_persoonlijk.py` |

---

## What the app does

### Weather and thermal indices (Thermopoulos layer)

- City lookup via Open-Meteo geocoding, with a picker when several places match
- Terrain type selection, driving the 10 m → 1.5 m wind profile
- 7–16 day forecast plus an automatic 14-day hindcast, and an optional custom
  historical period
- Per dataset: coastal correction where applicable, urban heat island, mean
  radiant temperature, WBGT and UTCI
- Interactive charts with a plain-language explanation of each abbreviation
- Excel export with all datasets on separate sheets

### Population heat-strain risk (PYROX layer)

Two complementary outputs are shown, because they answer different questions.

**Continuous risk level** (`final_risk`, model Step 5) varies smoothly and
monotonically with heat load. This is the signal to use for ranking days,
ranking groups, and making graded operational decisions.

**Cumulative strain** describes whether the regulatory loop has opened and
decompensation is running away. It is bistable *by design* — the
control-theoretic premise is that the loop escapes once its gain exceeds
unity — so it tends to sit near baseline or near the ceiling. Earlier
versions of this app showed only cumulative strain, which made every group
look either fine or catastrophic.

Also reported: caution / danger / emergency crossing days, each group's
metabolic rate and onset temperature, and optionally the local 30-year
climatological anomaly.

### Metabolic load (MET)

Each selected group has an editable metabolic rate. Metabolic heat is added
to the environmental heat load at **2.29 °C apparent-temperature equivalent
per MET**, derived from ISO 7243's own reference limit values. Enter the rate
**during the shift or event**, not a daily average: the working period
overlaps the daily thermal peak, and averaging across the cool night dilutes
the effect until it vanishes.

This is what makes occupational risk visible. An outdoor worker in a severe
Dutch heatwave is not at risk standing still, but is at risk working:

| Condition | MET | Peak strain |
|---|---|---|
| at rest | 1.2 | 5.0% |
| light work | 2.7 | 7.0% |
| construction | 4.0 | 16.0% |
| heavy labour | 5.5 | 63.1% |

**Scope limit.** This models cumulative multi-day strain in a working
population. It does not model acute exertional heat stroke during a single
shift or race, which needs hour-scale core-temperature dynamics and belongs
to HESTIA's individual tier.

### Data-quality flagging (for research use)

The `pythermalcomfort` UTCI implementation is only validated for air
temperatures in [−50 °C, +50 °C] and wind speeds in [0.5, 17] m/s. Locations
that legitimately exceed those bounds (Death Valley, parts of the Gulf) get
UTCI = NaN at those hours rather than an extrapolated, unvalidated number.
The app raises a warning banner listing the affected hours, and the Excel
export includes a **QA_Flags** sheet, so gaps in a UTCI series are documented
rather than silently absent.

### Local climatological context

Optionally reports how unusual each day is for this specific location against
a 30-year ERA5 baseline (same archive and UHI correction as the live data).

**This is context only — it does not feed the model.** An earlier version
replaced the fixed heat-load reference with the local climatological mean.
Testing showed two failure modes serious enough to reverse the decision:

1. *False negatives on lethal events.* A sustained 50–52 °C apparent-
   temperature week in Riyadh scored 5% peak strain — "nothing happening" —
   because it is not anomalous *for Riyadh*. No amount of acclimatization
   protects against that in absolute terms. Physiological limits do not
   renormalise to local custom.
2. *Silent invalidation of the calibration.* Paris August 2003 dropped from
   100% to 34% or 5% peak strain for the elderly group depending purely on
   which percentile was chosen as "normal" — an arbitrary UI setting swinging
   the answer between "disaster correctly predicted" and "no risk".

Climate adaptation belongs on the capacity side of the model, which is where
the revised calibration addresses it.

---

## Why the calibration was revised

Three independent defects were found in the original roster, each
reproducible from the shipped code. Summarised here; derived in full in
`pyrox_revised_calibration.py`.

**1. Resilience was counted twice, multiplicatively.** `net_strain_input`
evaluates the recovery threshold *after* the acclimatization reduction, so
the load at which a group starts accumulating strain is
`recovery_threshold / (1 − max_acclimatization_capacity)`, not the threshold
itself. Groups given both a high threshold and a high capacity had the two
compound. Outdoor workers: threshold 1.70, capacity 0.80, effective
tolerance 8.5.

**2. The parameters sat on the wrong scale.** The heat-load unit is
`(apparent °C − 22) × 0.10`, so real weather spans 0–3.0 (severe Dutch
heatwave 1.60; the global lethal extreme about 3.00). Four groups had a
threshold that alone exceeded a severe heatwave: endurance athletes 2.50,
elite athletes 2.00, recreational athletes 1.80, outdoor workers 1.70.

**3. One capacity value implied immunity.** Since
`experienced_load = load × (1 − capacity)`, the endurance athletes' 1.00
meant they experienced exactly zero heat load under all conditions. Heat
acclimation bounds strain; it does not abolish load. The suite's own PYROX
v2.2 work had already applied a Callahan et al. (2025) adaptation limit
elsewhere without bringing this roster into line.

**Measured consequences before the fix.** Zero of 667 tested (group, load)
combinations settled at a stable intermediate strain level. The outcome was
predicted in 96.8% of 1357 cases by the single comparison
`experienced_load > recovery_threshold`, meaning the memory kernel,
suppression gate and homeostatic drive had no influence on the answer. Eight
of 23 groups — every exertional group — reported baseline in every scenario
worldwide.

**What was deliberately not changed.** The model equations are untouched.
Raising `HOMEOSTATIC_DRIVE_COEFFICIENT` does produce a graded region but
destroys the calibration case (elderly Paris 2003 falls from 100% to 54% at
3.0, and 28% at 6.0). Bang-bang behaviour is the model's thesis, not a
defect. Once the thresholds sit on the correct scale, graded behaviour
emerges anyway along the metabolic axis.

### Known limitation of the revision

The onset temperatures from which the thresholds are solved are **reasoned
assumptions, not values taken from threshold epidemiology**. They are
internally consistent and pass the acceptance tests, but each should be
substantiated against published heat-mortality threshold literature before
the revised calibration is treated as authoritative.

---

## Caching and API limits

Open-Meteo's free tier allows 10,000 calls/day, 5,000/hour and 600/minute,
and requests spanning more than two weeks for one location count as more than
one call.

- Geocoding, forecast and hindcast results are cached for 30 minutes
- The 30-year climatology is cached for 30 days per location/date/settings
  combination, and is the most expensive feature — one request per year of
  history, throttled, with exponential backoff on HTTP 429
- If the quota is exhausted mid-climatology, the app returns a partial
  baseline with a warning rather than failing; the strain results do not
  depend on it

## HESTIA individual tier (correction to an earlier version of this README)

An earlier version of this README stated the HESTIA individual-tier
cardiovascular Monte Carlo simulation was not part of this app, because at
N = 1000 it takes minutes per run. That has since been addressed with a
two-speed architecture in `hestia_bridge.py`:

- **Quick estimate** (`run_quick_estimate`): a small, capped-worker,
  scenario-cached run, safe to call on every page render — this is what
  drives the headline "EHS estimate" shown in `app_athletes.py` and
  `app_beleid.py`.
- **Full precision** (`run_full_precision`): the full N=5000 run, not
  cached at this level, invoked only on explicit user request ("Run full
  precision").

Three defects found and fixed in this tier since the population-tier
revision below (all documented in code comments at their fix sites, and in
`GEBRUIKSAANWIJZING.md` §3.6 for a user-facing explanation):

1. **Clothing insulation (2026-08-09/10).** `clo_value` defaulted to 0.5
   (light indoor clothing, ISO 9920) regardless of conditions, including
   hot-weather running kit (~0.2-0.3). This was the single largest
   contributor to T_rect over-prediction found in that investigation —
   larger than any factor in the earlier CO_reserve/CHSI work. Fixed to
   0.2; the dose-response curve was re-fit against the corrected
   simulations (fit quality is honestly *worse* post-fix, since fewer
   participants now enter the danger quadrant at all — see the docstring
   above `_DOSE_RESPONSE_A`/`_DOSE_RESPONSE_B` in `hestia_bridge.py`).
2. **Hydration accounting (2026-08-09).** The cardiovascular-reserve module
   read a separate, never-decremented fluid-loss accumulator instead of the
   value the model's own drinking simulation already tracked correctly,
   causing reserve to appear to erode even in mild, constant conditions
   with no heat escalation at all.
3. **Post-finish module (rev14).** 30-40% of EHS cases at mass running
   events occur in the finish zone, not during the race (Roberts 1998; Rae
   et al. 2008). `simulate_post_finish()` in `hestia_model.py` propagates
   T_rect (metabolic after-glow) and CO_reserve (acute venous pooling,
   Rowell 1974) for 10 minutes after the race ends, without pacing control.

Four further defects found and fixed while building `app_persoonlijk.py`
(2026-08-16/17), all in code shared by `app_beleid.py` too — see
`test_cvr_freeze_fix.py` for regression coverage of the first two:

4. **CO_reserve silently went NaN after a participant froze
   (2026-08-16).** Once `runner_stopped=True` (RPE≥19.5), T_rect was
   correctly carried forward, but the CVR input series stopped growing,
   leaving CO_reserve at its NaN placeholder for the rest of that
   participant's trace. Any participant who froze with T_rect≥40.5°C
   was therefore invisible to the conjunctive criterion regardless of
   their true CO_reserve. Measured impact: mean dose in an extreme test
   scenario rose from 45.5 to 137.1 (3×) after the fix; effect scales
   with scenario severity and was negligible in the mild scenarios
   checked (Utrecht 31 May: unchanged).
5. **CO_reserve was non-monotonic — and could turn positive — at
   extreme heat strain (2026-08-17).** `co_reserve = (co_max_heat -
   co_rest_heat) × (1 - f)`; past a certain CHSI, `co_rest_heat` exceeds
   `co_max_heat` (first factor negative) while `f` is clipped above 1.0
   (second factor also negative), so the product flipped positive —
   reporting a healthy-looking reserve exactly where a participant could
   not meet even resting demand. Fixed by flooring cardiac-output demand
   at resting demand; unaffected wherever `co_max_heat > co_rest_heat`,
   i.e. the entire physiologically normal range, so Lloyd et al. (2022)'s
   coefficients are untouched.
6. **The global RNG was unseeded (2026-08-17).** The main loop draws
   drink volume from `np.random.uniform(120, 180)` — the only unseeded
   randomness in the engine. `generate_base_population()` already seeds
   the global RNG for the PYROX-tier population apps;
   `run_individual_assessment()` (in `individual_engine.py`) now does the
   same. Before this fix, the same inputs and the same `random_seed`
   produced different results on every run (measured: dose changed for
   49 of 60 participants between two runs of identical code).
7. **The race window could silently shift 1-2 hours (2026-08-16).**
   Comparing a naive local timestamp against `weather_df`'s tz-aware
   index does not raise an error — it silently offsets the whole race
   window by the local UTC offset (CET/CEST). Fixed via one shared
   localisation helper (`individual_engine._localize_naive`), covered by
   `test_timezone_localization` for both seasons.

**Three heat-illness endpoints, not one (2026-08-17).** Checked against
the literature after a definitional review: "collapse" as originally
implemented conflated two distinct clinical entities. `hestia_model.py`
and `individual_engine.py` now expose three, each with its own window and
literature basis (see `EHS_T_THRESHOLD`/`EHE_T_THRESHOLD`/
`EAC_CO_THRESHOLD` and their docstrings for the full derivation):

| Endpoint | Criterion | Window | Anchor |
|---|---|---|---|
| **EHS** — Exertional Heat Stroke | T_rect≥40.5°C AND CO_reserve≤0 | race + post-finish | Falmouth (dose-response fit) |
| **EHE** — Exertional Heat Exhaustion | T_rect>39.5°C AND CO_reserve<0 | race only | none (uncalibrated) |
| **EAC** — Exercise-Associated Collapse | sustained CO_reserve<0 (no temperature condition) | post-finish only | Gothenburg Half Marathon, 1.53/1000 (not yet fitted) |

EHE and EAC are reported as **percentages of the simulated population**,
not rates per 1000: meeting a mechanistic criterion is not the same as
the clinical syndrome (real EAC additionally requires cerebral
hypoperfusion, an upright posture and a moment), so neither has the kind
of observed-incidence fit that would make a per-1000 rate defensible.
EAC's Gothenburg anchor is the strongest candidate for a second
calibration point alongside Falmouth — not yet attempted.

**Klimaathoudbaarheid projection (`app_klimaatprojectie.py`, 2026-08-21).**
Answers a different question from the other four apps: not "what is the
risk this year", but "does a fixed yearly event date/location stay
defensible as the climate shifts" — built for indicative conversations
with event organisers about whether to move a date, not as a validated
forecast.

Method, entirely on top of existing modules (no new physiology, no new
weather source):

1. **Reference period (1996-2025).** For each reference year, one real
   ERA5 fetch covers the event date ±3 days (`Thermopoulos_Data_Engine.
   fetch_historical_data` — the same call `app.py`/`app_beleid.py` use),
   giving up to 210 real historical day-realisations around the date.
2. **Trend.** A Theil-Sen slope (`scipy.stats.theilslopes`, the same
   estimator `Klimatos.ClimateShift` uses for its annual maxima) is fit
   on the mean air temperature **during the actual race window
   (start→finish)**, averaged over the 7 day-realisations per reference
   year — not the whole-day mean and not the yearly maximum. Diurnal
   warming is not uniform (nights often warm faster than afternoons in
   temperate climates), so a whole-day trend can mis-estimate the
   warming that applies specifically to the event's own hours.
3. **Projection.** For each target year, every one of the 210 historical
   days has its raw rural air temperature shifted by
   `slope × (target_year − that day's own historical year)`, then the
   **full** physical chain (UHI → globe temperature → MRT → WBGT/UTCI)
   is re-derived from the shifted value via `process_weather_data()`, so
   nothing is shifted in isolation from the rest of the pipeline.
4. Every (possibly shifted) day-realisation is run through
   `hestia_bridge.run_quick_estimate()` — the identical population
   ensemble function `app.py`/`app_beleid.py` call, nothing reimplemented.
   The mean EHE outcome across the 210 realisations for a given year is
   its expectation; the fraction of the 210 realisations exceeding a
   user-set threshold is its exceedance probability. Both are reported
   for the reference period and for every target year, side by side.

**Deliberate deviation from the EHE/EAC convention above.** The rest of
this suite reports EHE only as a percentage of the ensemble, never a
rate per 1000, because it is uncalibrated. This app additionally shows
an **"EHE per 1000"** figure (the same percentage × 10) at the author's
explicit request, labelled uncalibrated/indicative everywhere it
appears, alongside the properly Falmouth-calibrated EHS/1000 from the
same run for contrast. This is a UI choice for this one app, not a
change to what EHE means or how it is computed.

Explicit, undisguised limitations (also in the app's own expander,
every run): the projection is a statistical extrapolation of an
observed trend estimated specifically over the race-window hours, not
a physical climate model or a forecast for any one year; only air
temperature is shifted, humidity/wind/cloud cover are left at their
historical values for that calendar day; trend stationarity within the
reference window is an assumption, not tested.

**Privacy architecture (`app_persoonlijk.py`, 2026-08-15/16).** Built for
one named individual's own biometrics and one event, run entirely on
whatever machine executes `streamlit run app_persoonlijk.py`. The only
network calls anywhere in `individual_engine.py`'s call graph are
geocoding the event location and fetching weather for it — audited
directly against `Thermopoulos_Data_Engine.py`'s outgoing request
parameters (lat/lon/date/units only, never a personal field). Local
persistence (`local_storage.py`) writes outside the project folder
(`%APPDATA%\PYROX` on Windows) specifically so a `git add .` in this repo
cannot pick up personal data. **This guarantee holds only for whoever
actually runs the process** — a Streamlit Cloud deployment or a shared
URL moves that "local machine" to the server or host account, not the
visitor's device; see `GEBRUIKSAANWIJZING.md` §3.9 for the deployment
choice this implies.

**Scope limit, unchanged from the original text:** this remains a
screening-level simulation, not a validated clinical predictor for any
named individual.


