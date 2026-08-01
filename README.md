# PYROX — heat-risk web app

An interactive web interface on top of the Thermopoulos Data Engine (weather
acquisition + thermal-index processing) and PYROX (population-tier
heat-strain model). All underlying scientific logic is unchanged — this is a
UI layer only.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`.

## Free hosting (Streamlit Community Cloud)

1. Put this folder (`app.py`, `Thermopoulos_Data_Engine.py`,
   `thermopoulos_loader.py`, `pyrox_model.py`, `pyrox_groups.py`,
   `requirements.txt`) in a GitHub repo.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. "New app" → select the repo → entry point `app.py` → Deploy.
4. Done: you get a public URL, free, no credit usage.

## What the app does

- City lookup (Open-Meteo geocoding), with a picker when multiple matches are found
- Terrain type selection (drives the 10m→1.5m wind profile)
- 7–16 day forecast + automatic 14-day hindcast
- Optional custom historical period
- Per dataset: coastal correction (where applicable), UHI, MRT, WBGT, UTCI
- Interactive Plotly charts (T_air, WBGT, UTCI, MRT) with a summary table,
  plus a short explanation of each abbreviation at the top of the page
- **PYROX — population heat-strain risk**: cumulative strain per population
  group (e.g. young adults, older adults 65-85, vulnerable older adults 85+)
  over the combined hindcast+forecast window, with caution/danger/emergency
  crossing days. This is PYROX's deterministic day-by-day strain-accumulation
  model — no Monte Carlo, so it runs in milliseconds, unlike the HESTIA CVR
  simulation
- **Data-quality / UTCI validity flagging** (for research use): pythermalcomfort's
  UTCI implementation is only validated for air temperatures in [-50°C, 50°C]
  and wind speeds in [0.5, 17] m/s. Locations that legitimately exceed these
  bounds (e.g. Death Valley, parts of the Gulf) get UTCI = NaN at those hours
  rather than an extrapolated (unvalidated) number. The app surfaces this as
  a warning banner with the affected hours listed, and includes a **QA_Flags**
  sheet in the Excel export for provenance/reproducibility
- **Local climatological context** (optional, off by default): reports how
  unusual each day is for this specific location, compared with the same
  calendar window over the past 30 years (same ERA5 archive and UHI
  correction as the live data, chosen percentile, default 50th). This is
  presented as **interpretive context alongside** the strain results — it
  does **not** feed into the heat load or the strain computation.

  *Why not fold it into the model?* An earlier version did exactly that,
  replacing the fixed reference temperature with the local climatological
  mean. Testing showed two failure modes serious enough to reverse the
  decision:
  1. **False negatives on absolutely lethal events.** A sustained
     50-52°C apparent-temperature week in Riyadh scored 5% peak strain
     (i.e. "nothing happening") because it isn't anomalous *for Riyadh* —
     but no amount of acclimatization protects against that in absolute
     terms. Physiological limits don't renormalise to local custom.
  2. **It silently invalidated the calibration.** Paris August 2003 —
     the case the heat-load bridge was calibrated on — dropped from 100%
     to 34% or 5% peak strain for the elderly group depending purely on
     which percentile was chosen as "normal". An arbitrary UI setting
     swinging the answer between "disaster correctly predicted" and "no
     risk" is not an acceptable design.

  Climate adaptation belongs on the **capacity** side of the model
  (`recovery_threshold`, `max_acclimatization_capacity`, where the
  Callahan et al. 2025 adaptation limits already apply in PYROX v2.2),
  not on the load side. A parameter scan suggests a `recovery_threshold`
  multiplier around 2.0 separates "routine local summer = safe" from
  "local extreme = dangerous" for a lifelong hot-climate resident — but
  that window is narrow, so any such factor needs literature-based
  justification rather than fitting.
- Download the full dataset as Excel (multiple sheets)

## Caching

API calls (geocoding, forecast, hindcast) are cached for 30 minutes
(`st.cache_data(ttl=1800)`) so repeatedly exploring the same location doesn't
trigger unnecessary Open-Meteo calls. The PYROX computation is cached as well,
keyed on the Excel content and the chosen groups/settings.

## Not included

This app exposes the Thermopoulos and PYROX layers only. The HESTIA
individual-tier cardiovascular Monte Carlo simulation is not integrated —
it's a much heavier workload (minutes per run at N=1000) that needs a
separate architecture (an async job queue, or a precomputed lookup table),
as discussed separately.
