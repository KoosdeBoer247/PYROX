# -*- coding: utf-8 -*-
"""
app_klimaatprojectie.py
=========================
Klimaathoudbaarheid van een vast jaarlijks evenement (bv. Zwolle Halve
Marathon): geeft per toekomstig jaar een verwachtingswaarde en een
overschrijdingskans voor EHE, vergeleken met de referentieperiode
1996-2025 -- als indicatief hulpmiddel om aan organisaties voor te
leggen, NIET als gevalideerde voorspelling.

METHODE
-------
1. REFERENTIE (1996-2025). Voor elk jaar in die reeks wordt het echte
   ERA5-weer opgehaald voor een venster van datum +/- 3 dagen (tot 30 x 7
   = 210 historische dag-realisaties rond de evenementdatum). Elke dag
   wordt los door de bestaande populatie-ensemble-pijplijn
   (hestia_bridge.run_quick_estimate -- dezelfde functie die app.py en
   app_beleid.py gebruiken) gehaald.
2. PROJECTIE. Voor elk gekozen toekomstig jaar wordt diezelfde set van
   210 historische dagen genomen, maar de RUWE luchttemperatuur
   (T_air_rural, voor UHI/globe/MRT-afleiding) wordt verschoven met de
   Theil-Sen trendhelling (niet-parametrische regressie, scipy.stats.
   theilslopes -- zelfde methode als Klimatos.ClimateShift) x (doeljaar -
   historisch jaar van die specifieke realisatie). De trend wordt
   geschat op het gemiddelde van de RACE-VENSTER-uren (start->finish),
   over de 7 dag-realisaties per jaar -- NIET op het etmaalgemiddelde,
   omdat diurnale opwarming niet uniform is (nachten warmen in veel
   gematigde klimaten sneller op dan middagen; een ochtendstart valt
   anders in die asymmetrie dan een etmaalgemiddelde laat zien). Na de
   verschuiving wordt de VOLLEDIGE fysische keten (UHI, globe-temp, MRT,
   WBGT, UTCI) opnieuw doorgerekend, zodat alle grootheden onderling
   consistent blijven -- alleen de ruwe luchttemperatuur wordt
   aangepast, niets anders los.
3. Elke van de 210 (eventueel verschoven) dag-realisaties levert een
   ensemble-gemiddelde EHE-fractie op (populatie-ensemble van
   n_simulations deelnemers per dag, uit dezelfde generate_base_population
   als de rest van de suite). Het gemiddelde over de 210 realisaties is
   de VERWACHTINGSWAARDE voor dat jaar; het aandeel realisaties dat de
   zelf ingestelde grens overschrijdt is de OVERSCHRIJDINGSKANS.
4. Drie aanvullende plots, analoog aan Klimatos.ClimateShift maar op deze
   pagina's eigen race-venster-gemiddelde T_air-reeks: een trendplot met
   toekomstprojectie (analoog `plot_timeseries_trend`/
   `add_trend_projection`), een verdelingsverschuiving referentie vs.
   doeljaar (analoog `plot_window_normals`) en een return-period-plot met
   zowel Normaal- als GEV-fit (analoog `plot_return_levels`, met dezelfde
   n\u224830-instabiliteitskanttekening bij de GEV-staart).

BEPERKINGEN (bewust zichtbaar, niet verstopt)
-----------------------------------------------
- EHE is NIET gekalibreerd tegen waargenomen incidentie (zie
  individual_engine.py, EHE_T_THRESHOLD-docstring). De "per 1000"-
  weergave hier is een indicatieve, ONGEKALIBREERDE extrapolatie van de
  ensemble-fractie x 10 -- geen geschatte kans op een echte gebeurtenis
  zoals bij het Falmouth-gekalibreerde EHS-cijfer, dat er daarom
  nadrukkelijk naast staat.
- De klimaatprojectie is een statistische Theil-Sen-extrapolatie van de
  waargenomen trend, GEEN fysisch klimaatmodel en geen weersvoorspelling
  voor een specifiek jaar. Trend-stationariteit binnen het venster is
  een aanname, niet getoetst (zelfde caveat als in de Klimatos-
  whitepaper-review).
- Alleen de luchttemperatuur wordt verschoven; RH/wind/bewolking blijven
  op hun historische waarden voor die kalenderdag. Een warmer klimaat
  gaat in werkelijkheid vaak ook gepaard met veranderende vochtigheid --
  dat is hier niet meegenomen.
- Kleine ensemble per dag-realisatie (instelbaar, standaard 30) --
  ruis per losse dag wordt opgevangen doordat 210 dagen worden
  gemiddeld, niet doordat elke dag apart nauwkeurig is.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy import stats as _stats
from scipy.stats import genextreme as _genextreme, norm as _norm

from Thermopoulos_Data_Engine import (
    ROUGHNESS_Z0_TERRAIN,
    fetch_historical_data,
    geocode_city_candidates,
    process_weather_data,
    validate_weather_data,
)
from hestia_bridge import run_quick_estimate
from pyrox_bridge import met_from_pace, acsm_range_warning

st.set_page_config(page_title="Klimaathoudbaarheid evenement", page_icon="\U0001F321\ufe0f",
                   layout="wide")

APP_BUILD = "2026-08-21a (initial release)"
st.sidebar.caption(f"Build {APP_BUILD}")

REFERENCE_START_YEAR = 1996
REFERENCE_END_YEAR = 2025
DAY_WINDOW = 3          # +/- dagen rond de evenementdatum
FETCH_PAUSE_S = 0.3     # vriendelijk voor de Open-Meteo archive-API


# =============================================================================
# Geocoding (cached)
# =============================================================================
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _geocode(location_query: str) -> dict | None:
    candidates = geocode_city_candidates(location_query)
    return candidates[0] if candidates else None


# =============================================================================
# Referentie-weer ophalen: 1 fetch per jaar, venster van (2*DAY_WINDOW+1) dagen
# =============================================================================
@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def _fetch_reference_year_window(lat: float, lon: float, tz: str,
                                 month: int, day: int, year: int,
                                 roughness_z0: float, population: int) -> pd.DataFrame | None:
    """Real ERA5 hourly weather for [date-DAY_WINDOW, date+DAY_WINDOW] in one
    calendar year, fully processed (UHI/globe/MRT/WBGT/UTCI). Returns None if
    the fetch/processing fails for that year (e.g. archive gap) -- the
    calling code skips it rather than aborting the whole reference set."""
    try:
        center = pd.Timestamp(year=year, month=month, day=day)
    except ValueError:
        # 29 Feb in a non-leap reference year: fall back to 28 Feb as the
        # nearest valid calendar date for that year only.
        center = pd.Timestamp(year=year, month=2, day=28)
    start = (center - pd.Timedelta(days=DAY_WINDOW)).strftime("%Y-%m-%d")
    end = (center + pd.Timedelta(days=DAY_WINDOW)).strftime("%Y-%m-%d")
    try:
        raw, coastal_active = fetch_historical_data(lat, lon, tz, start, end)
        raw = validate_weather_data(raw, "historical")
        city = {"population": population}
        proc = process_weather_data(raw, city, lat, lon, tz,
                                    coastal_active=coastal_active,
                                    roughness_z0=roughness_z0)
        time.sleep(FETCH_PAUSE_S)
        return proc
    except Exception:
        return None


def _shift_and_reprocess(raw_df: pd.DataFrame, delta_temp: float, city: dict,
                         lat: float, lon: float, tz: str,
                         coastal_active: bool, roughness_z0: float) -> pd.DataFrame:
    """Shift the RAW rural air temperature by delta_temp (deg C) and
    re-derive the whole physical chain from it, so UHI/globe/MRT/WBGT/UTCI
    stay mutually consistent -- see module docstring, point 2."""
    shifted = raw_df.copy()
    shifted["T_air_rural"] = shifted["T_air_rural"] + delta_temp
    return process_weather_data(shifted, city, lat, lon, tz,
                                coastal_active=coastal_active,
                                roughness_z0=roughness_z0)


# =============================================================================
# Trend: Theil-Sen op de dag-venster-gemiddelde T_air per referentiejaar
# =============================================================================
def _race_window_mean_temp(df: pd.DataFrame, event_date: pd.Timestamp, tz: str,
                           start_time, duration_minutes: float) -> float | None:
    """Mean T_air_rural during the ACTUAL race window (start->finish) on one
    calendar day, not the whole day. Used for trend estimation -- see
    module docstring, point 2a: diurnal warming is not uniform (nights
    often warm faster than afternoons in temperate climates), so a
    whole-day trend can mis-estimate the warming that applies specifically
    to the event's own hours."""
    start_naive = pd.Timestamp.combine(event_date.date(), start_time)
    start_aware = start_naive.tz_localize(tz, nonexistent="shift_forward", ambiguous=True)
    finish_aware = start_aware + pd.Timedelta(minutes=duration_minutes)
    window = df.loc[(df.index >= start_aware) & (df.index <= finish_aware), "T_air_rural"]
    if window.empty:
        return None
    return float(window.mean())


def _theil_sen_trend(year_mean_temps: dict[int, float]) -> dict:
    """Same estimator Klimatos.ClimateShift uses (scipy.stats.theilslopes):
    robust non-parametric slope (deg C/year) + 95% CI, on the RACE-WINDOW
    mean air temperature per reference year (see _race_window_mean_temp) --
    NOT the Klimatos annual maxima (wrong statistic here) and NOT a
    whole-day mean (diurnal warming is not uniform, see that function's
    docstring), because what matters is the trend during the event's own
    hours, at this specific time of year."""
    years = np.array(sorted(year_mean_temps))
    vals = np.array([year_mean_temps[y] for y in years])
    if len(years) < 4:
        return {"slope": 0.0, "slope_lo": 0.0, "slope_hi": 0.0, "n": len(years)}
    slope, intercept, slope_lo, slope_hi = _stats.theilslopes(vals, years, alpha=0.95)
    return {"slope": float(slope), "slope_lo": float(slope_lo),
           "slope_hi": float(slope_hi), "intercept": float(intercept),
           "anchor_year": int(years[0]), "n": len(years)}


def _shifted_year_series(year_mean_temps: dict[int, float], trend: dict,
                         target_year: int) -> np.ndarray:
    """The reference years' race-window means, each individually shifted to
    what the trend predicts for `target_year`. Mathematically this is
    equivalent to detrending each historical value (removing the linear
    trend) and re-centring the whole series at the target year's
    trend-predicted level -- so the SPREAD (natural year-to-year weather
    variability) is preserved exactly as observed, only the central
    tendency moves. This is what makes fitting a fresh Normal/GEV to this
    shifted series a coherent trend-adjusted return-period estimate,
    not an ad hoc rescaling."""
    years = np.array(sorted(year_mean_temps))
    vals = np.array([year_mean_temps[y] for y in years])
    return vals + trend["slope"] * (target_year - years)


def _return_period_normal(data: np.ndarray, threshold: float) -> float:
    """Return period [years] via a Normal fit -- same construction as
    Klimatos.ClimateShift's _return_period(), just inlined here since this
    module fits its own (smaller, race-window-specific) series rather than
    importing the Klimatos script directly."""
    if len(data) < 4:
        return float("inf")
    mu, sigma = float(np.mean(data)), float(np.std(data, ddof=1))
    if sigma <= 0:
        return float("inf")
    prob = float(_norm.sf(threshold, loc=mu, scale=sigma))
    return 1.0 / prob if prob > 0 else float("inf")


def _return_period_gev(data: np.ndarray, threshold: float) -> float:
    """Return period [years] via a GEV fit. Same caveat as Klimatos'
    plot_return_levels(): a 3-parameter GEV fit on ~30 points is
    genuinely unstable -- shown alongside the Normal fit as a second
    reference point, not as the more trustworthy of the two."""
    if len(data) < 8:
        return float("inf")
    try:
        c, loc, scale = _genextreme.fit(data)
        prob = float(_genextreme.sf(threshold, c, loc=loc, scale=scale))
        return 1.0 / prob if prob > 0 else float("inf")
    except Exception:
        return float("inf")


def _build_trend_plot(year_mean_temps: dict[int, float], trend: dict,
                      target_years: list[int]) -> go.Figure:
    """Race-window mean T_air per reference year, with the Theil-Sen fit
    and a projection fan (central + 95% CI) extended to the last chosen
    target year -- direct analogue of Klimatos.ClimateShift's
    plot_timeseries_trend()/add_trend_projection()."""
    years = np.array(sorted(year_mean_temps))
    vals = np.array([year_mean_temps[y] for y in years])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=vals, mode="markers",
                             name="Race-venster-gemiddelde T_air per jaar",
                             marker=dict(size=7)))
    fit_line = trend["intercept"] + trend["slope"] * years
    fig.add_trace(go.Scatter(x=years, y=fit_line, mode="lines",
                             name="Theil-Sen fit", line=dict(color="firebrick")))
    if target_years:
        last_year = max(target_years)
        future_years = np.arange(years[-1], last_year + 1)
        y_last = trend["intercept"] + trend["slope"] * years[-1]
        t = future_years - years[-1]
        central = y_last + trend["slope"] * t
        lo = y_last + trend["slope_lo"] * t
        hi = y_last + trend["slope_hi"] * t
        fig.add_trace(go.Scatter(x=future_years, y=central, mode="lines",
                                 line=dict(color="firebrick", dash="dash"),
                                 name=f"Projectie naar {last_year}"))
        fig.add_trace(go.Scatter(
            x=list(future_years) + list(future_years[::-1]),
            y=list(np.maximum(lo, hi)) + list(np.minimum(lo, hi)[::-1]),
            fill="toself", fillcolor="rgba(178,34,34,0.12)",
            line=dict(width=0), name="Sen's slope 95%-CI (geprojecteerd)",
            showlegend=True,
        ))
    fig.update_layout(
        title="Trend: race-venster-gemiddelde T_air, met toekomstprojectie",
        xaxis_title="Jaar", yaxis_title="T_air tijdens race-venster (\u00b0C)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=420,
    )
    return fig


def _build_distribution_plot(year_mean_temps: dict[int, float], trend: dict,
                             target_year: int) -> go.Figure:
    """Reference vs. target-year Normal fit of the race-window mean T_air --
    analogue of Klimatos.ClimateShift's plot_window_normals()/
    plot_standardized_anomaly(), shown here for two periods instead of a
    sliding-window series."""
    ref_vals = np.array(list(year_mean_temps.values()))
    tgt_vals = _shifted_year_series(year_mean_temps, trend, target_year)
    lo = min(ref_vals.min(), tgt_vals.min()) - 2
    hi = max(ref_vals.max(), tgt_vals.max()) + 2
    x = np.linspace(lo, hi, 300)
    fig = go.Figure()
    for label, vals, color in [
        (f"Referentie {REFERENCE_START_YEAR}-{REFERENCE_END_YEAR}", ref_vals, "steelblue"),
        (f"Geprojecteerd {target_year}", tgt_vals, "firebrick"),
    ]:
        mu, sigma = float(np.mean(vals)), float(np.std(vals, ddof=1))
        pdf = _norm.pdf(x, loc=mu, scale=sigma) if sigma > 0 else np.zeros_like(x)
        fig.add_trace(go.Scatter(x=x, y=pdf, mode="lines", name=label,
                                 line=dict(color=color)))
        fig.add_trace(go.Scatter(x=vals, y=[0] * len(vals), mode="markers",
                                 marker=dict(color=color, size=6, symbol="line-ns-open"),
                                 showlegend=False))
    fig.update_layout(
        title=f"Verdelingsverschuiving: referentie vs. {target_year} (Normaalfit)",
        xaxis_title="T_air tijdens race-venster (\u00b0C)", yaxis_title="Dichtheid",
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=420,
    )
    return fig


def _build_return_period_plot(year_mean_temps: dict[int, float], trend: dict,
                              target_year: int, threshold_temp: float) -> go.Figure:
    """Return period vs. threshold temperature, reference vs. target year,
    Normal fit (solid, robust at n=30) and GEV fit (dashed, same caveat as
    Klimatos.ClimateShift's plot_return_levels() -- shown as a second
    reference point, not the more trustworthy of the two)."""
    ref_vals = np.array(list(year_mean_temps.values()))
    tgt_vals = _shifted_year_series(year_mean_temps, trend, target_year)
    lo = min(ref_vals.min(), tgt_vals.min())
    hi = max(ref_vals.max(), tgt_vals.max()) + 3
    thresholds = np.linspace(lo, hi, 60)
    fig = go.Figure()
    for label, vals, color in [
        (f"Referentie {REFERENCE_START_YEAR}-{REFERENCE_END_YEAR}", ref_vals, "steelblue"),
        (f"Geprojecteerd {target_year}", tgt_vals, "firebrick"),
    ]:
        rp_normal = [_return_period_normal(vals, t) for t in thresholds]
        rp_gev = [_return_period_gev(vals, t) for t in thresholds]
        fig.add_trace(go.Scatter(x=thresholds, y=rp_normal, mode="lines",
                                 name=f"{label} (Normaal)", line=dict(color=color)))
        fig.add_trace(go.Scatter(x=thresholds, y=rp_gev, mode="lines",
                                 name=f"{label} (GEV)",
                                 line=dict(color=color, dash="dot")))
    fig.add_vline(x=threshold_temp, line_dash="dash", line_color="grey",
                 annotation_text="Gekozen drempel")
    fig.update_layout(
        title="Return period vs. drempeltemperatuur, referentie vs. doeljaar",
        xaxis_title="Drempeltemperatuur (\u00b0C, race-venster-gemiddelde)",
        yaxis_title="Terugkeertijd (jaar)", yaxis_type="log",
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=420,
    )
    return fig



def _run_one_day(weather_df: pd.DataFrame, lat: float, lon: float, tz: str,
                 event_date: pd.Timestamp, start_time, duration_minutes: float,
                 met_value: float, clo_value: float, n_simulations: int,
                 random_seed: int) -> dict | None:
    start_naive = pd.Timestamp.combine(event_date.date(), start_time)
    start_aware = start_naive.tz_localize(tz, nonexistent="shift_forward", ambiguous=True)
    finish_aware = start_aware + pd.Timedelta(minutes=duration_minutes)
    if start_aware < weather_df.index.min() or finish_aware > weather_df.index.max():
        return None
    result = run_quick_estimate(
        weather_df, lat, lon, tz, start_aware, finish_aware,
        met_value=met_value, clo_value=clo_value,
        n_simulations=n_simulations, random_seed=random_seed,
    )
    return result


@dataclass
class YearOutcome:
    year: int | None          # None = referentieperiode (samengevoegd)
    n_realisations: int
    ehe_fraction_mean: float          # gemiddelde ensemble-EHE-fractie over alle dag-realisaties
    ehe_per_1000_mean: float          # zelfde x 10, ongekalibreerd
    p_exceeds_threshold: float        # aandeel dag-realisaties boven de ingestelde grens
    ehs_per_1000_falmouth_mean: float  # ter vergelijking: het WEL gekalibreerde EHS-cijfer


def _aggregate(realisation_results: list[dict], threshold_pct: float) -> YearOutcome | None:
    valid = [r for r in realisation_results if r is not None]
    if not valid:
        return None
    ehe_pcts = np.array([r["pct_true_ehe_criterion"] for r in valid])
    ehs_1000 = np.array([r.get("falmouth_ehs_per_1000", np.nan) for r in valid])
    return YearOutcome(
        year=None,
        n_realisations=len(valid),
        ehe_fraction_mean=float(np.mean(ehe_pcts)) / 100.0,
        ehe_per_1000_mean=float(np.mean(ehe_pcts)) * 10.0,
        p_exceeds_threshold=float(np.mean(ehe_pcts > threshold_pct)),
        ehs_per_1000_falmouth_mean=float(np.nanmean(ehs_1000)),
    )


# =============================================================================
# UI
# =============================================================================
st.title("\U0001F321\ufe0f Klimaathoudbaarheid van een jaarlijks evenement")
st.caption(
    "Indicatief hulpmiddel voor gesprekken met evenementenorganisaties. "
    "EHE is NIET gekalibreerd tegen waargenomen incidentie -- zie de "
    "toelichting onderaan voordat je dit deelt."
)

with st.form("event_config"):
    c1, c2 = st.columns(2)
    with c1:
        location_query = st.text_input("Locatie", value="Zwolle")
        event_date_input = st.date_input(
            "Datum in het jaar (het jaartal zelf wordt genegeerd)",
            value=pd.Timestamp("2026-04-19"),
        )
        start_time = st.time_input("Starttijd", value=pd.Timestamp("2026-01-01 10:00").time())
        duration_minutes = st.number_input("Duur (minuten, mediane deelnemer)",
                                           min_value=10, max_value=600, value=110)
    with c2:
        pace = st.number_input("Tempo mediane deelnemer (min/km)", min_value=2.5,
                               max_value=15.0, value=5.5, step=0.1)
        mode = st.selectbox("Modus", options=["run", "walk"], index=0,
                            format_func=lambda m: "Hardlopen" if m == "run" else "Wandelen")
        terrain_key = st.selectbox(
            "Terreintype", options=list(ROUGHNESS_Z0_TERRAIN.keys()),
            index=2, format_func=lambda k: ROUGHNESS_Z0_TERRAIN[k][0],
        )
        threshold_pct = st.number_input(
            "Ingestelde grens: EHE (% van het ensemble)", min_value=0.1,
            max_value=100.0, value=5.0, step=0.5,
        )

    c3, c4, c5 = st.columns(3)
    with c3:
        target_year_start = st.number_input("Vanaf doeljaar", min_value=REFERENCE_END_YEAR + 1,
                                            max_value=2100, value=2030)
    with c4:
        target_year_end = st.number_input("Tot en met doeljaar", min_value=REFERENCE_END_YEAR + 1,
                                          max_value=2100, value=2050)
    with c5:
        target_year_step = st.number_input("Stap (jaren)", min_value=1, max_value=25, value=5)

    n_simulations = st.slider(
        "Ensemble per dag-realisatie (n deelnemers)", min_value=10, max_value=100,
        value=30, step=10,
        help="Lager = sneller maar ruisiger per dag; de 210 dagen samen "
             "middelen dat grotendeels uit. Hoger alleen zinvol als je de "
             "berekening kunt laten doorlopen.",
    )
    submitted = st.form_submit_button("Bereken klimaathoudbaarheid", type="primary")

if not submitted:
    st.info("Vul de eventgegevens in en klik op **Bereken klimaathoudbaarheid**.")
    st.stop()

warn = acsm_range_warning(pace, mode)
if warn:
    st.warning(warn)

city = _geocode(location_query)
if city is None:
    st.error(f"Locatie '{location_query}' niet gevonden.")
    st.stop()

lat, lon, tz = city["latitude"], city["longitude"], city["timezone"]
population = city.get("population", 0) or 0
roughness_z0 = ROUGHNESS_Z0_TERRAIN[terrain_key][1]
met_value = met_from_pace(pace, mode=mode)
target_years = list(range(int(target_year_start), int(target_year_end) + 1, int(target_year_step)))

st.markdown(
    f"**{city['name']}, {city.get('country', '')}** &middot; "
    f"referentieperiode **{REFERENCE_START_YEAR}-{REFERENCE_END_YEAR}** &middot; "
    f"venster {event_date_input.strftime('%d-%m')} &plusmn;{DAY_WINDOW} dagen &middot; "
    f"MET \u2248 {met_value:.1f}"
)

# --- 1. Referentie-weer ophalen (1 fetch per jaar) --------------------------
progress = st.progress(0.0, text="Referentieperiode: weer ophalen\u2026")
ref_years = list(range(REFERENCE_START_YEAR, REFERENCE_END_YEAR + 1))
raw_weather_by_year: dict[int, pd.DataFrame] = {}
for i, y in enumerate(ref_years):
    df = _fetch_reference_year_window(lat, lon, tz, event_date_input.month,
                                      event_date_input.day, y, roughness_z0, population)
    if df is not None:
        raw_weather_by_year[y] = df
    progress.progress((i + 1) / len(ref_years),
                      text=f"Referentieperiode: weer ophalen ({i + 1}/{len(ref_years)})\u2026")

if len(raw_weather_by_year) < 10:
    st.error("Te weinig referentiejaren met bruikbare data opgehaald -- probeer het later opnieuw.")
    st.stop()

# --- 2. Trend schatten op het RACE-VENSTER (niet het etmaal) ---------------
# Per referentiejaar: gemiddelde T_air_rural tijdens start->finish, over de
# 7 dag-realisaties in dat jaar -- niet het etmaalgemiddelde over het hele
# +/-3-dagen-venster. Diurnale opwarming is niet uniform (zie
# _race_window_mean_temp's docstring), dus de trend moet specifiek over de
# uren van het evenement zelf worden geschat.
year_mean_temp: dict[int, float] = {}
for y, df in raw_weather_by_year.items():
    day_means = []
    for off in range(-DAY_WINDOW, DAY_WINDOW + 1):
        try:
            d = pd.Timestamp(year=y, month=event_date_input.month,
                             day=event_date_input.day) + pd.Timedelta(days=off)
        except ValueError:
            continue
        m = _race_window_mean_temp(df, d, tz, start_time, duration_minutes)
        if m is not None:
            day_means.append(m)
    if day_means:
        year_mean_temp[y] = float(np.mean(day_means))
trend = _theil_sen_trend(year_mean_temp)
st.caption(
    f"Theil-Sen trend (specifiek over start\u2192finish, niet het etmaal): "
    f"{trend['slope']:+.3f} \u00b0C/jaar (95%-CI {trend['slope_lo']:+.3f} tot "
    f"{trend['slope_hi']:+.3f}), n={trend['n']} referentiejaren."
)

# --- 3. Voor elke referentiedag: door de bestaande ensemble-pijplijn --------
progress = st.progress(0.0, text="Referentieperiode: fysiologische simulatie\u2026")
offsets = list(range(-DAY_WINDOW, DAY_WINDOW + 1))
ref_results = []
total_steps = len(raw_weather_by_year) * len(offsets)
step = 0
for y, df in raw_weather_by_year.items():
    for off in offsets:
        try:
            event_date = pd.Timestamp(year=y, month=event_date_input.month,
                                      day=event_date_input.day) + pd.Timedelta(days=off)
        except ValueError:
            step += 1
            continue
        res = _run_one_day(df, lat, lon, tz, event_date, start_time, duration_minutes,
                           met_value, clo_value=0.2, n_simulations=n_simulations,
                           random_seed=42 + off)
        ref_results.append(res)
        step += 1
        if step % 10 == 0 or step == total_steps:
            progress.progress(step / total_steps,
                              text=f"Referentieperiode: fysiologische simulatie ({step}/{total_steps})\u2026")

reference_outcome = _aggregate(ref_results, threshold_pct)
if reference_outcome is None:
    st.error("Geen enkele referentiedag leverde een geldige simulatie op.")
    st.stop()

# --- 4. Voor elk doeljaar: dezelfde dagen, klimaat-verschoven ---------------
progress = st.progress(0.0, text="Toekomstprojectie\u2026")
year_outcomes: dict[int, YearOutcome] = {}
total_steps = len(target_years) * len(raw_weather_by_year) * len(offsets)
step = 0
for target_year in target_years:
    proj_results = []
    for y, raw_df in raw_weather_by_year.items():
        delta_temp = trend["slope"] * (target_year - y)
        # Re-fetch coastal_active is not stored on the processed df; recompute
        # a fresh raw fetch would be wasteful, so shift is applied directly on
        # the ALREADY-PROCESSED df's rural column, which still carries
        # T_air_rural untouched by process_weather_data (rural = pre-UHI).
        shifted = raw_df.copy()
        shifted["T_air_rural"] = shifted["T_air_rural"] + delta_temp
        city_dict = {"population": population}
        proc = process_weather_data(shifted, city_dict, lat, lon, tz,
                                    coastal_active=False, roughness_z0=roughness_z0)
        for off in offsets:
            try:
                event_date = pd.Timestamp(year=y, month=event_date_input.month,
                                          day=event_date_input.day) + pd.Timedelta(days=off)
            except ValueError:
                step += 1
                continue
            res = _run_one_day(proc, lat, lon, tz, event_date, start_time, duration_minutes,
                               met_value, clo_value=0.2, n_simulations=n_simulations,
                               random_seed=42 + off)
            proj_results.append(res)
            step += 1
        if step % 20 == 0 or step == total_steps:
            progress.progress(min(step / total_steps, 1.0),
                              text=f"Toekomstprojectie: {target_year} ({step}/{total_steps})\u2026")
    outcome = _aggregate(proj_results, threshold_pct)
    if outcome is not None:
        outcome.year = target_year
        year_outcomes[target_year] = outcome

progress.empty()

# =============================================================================
# Resultaten
# =============================================================================
st.divider()
st.markdown("## Resultaten")

st.markdown(
    f"### Referentieperiode {REFERENCE_START_YEAR}-{REFERENCE_END_YEAR}\n"
    f"- Verwachte EHE-fractie: **{reference_outcome.ehe_fraction_mean * 100:.1f}%** "
    f"van het ensemble (ongekalibreerd, indicatief: **{reference_outcome.ehe_per_1000_mean:.0f} per 1000**)\n"
    f"- Kans dat EHE de ingestelde grens van {threshold_pct:.1f}% overschrijdt: "
    f"**{reference_outcome.p_exceeds_threshold * 100:.0f}%** van de {reference_outcome.n_realisations} "
    f"historische dag-realisaties\n"
    f"- Ter vergelijking, het WEL Falmouth-gekalibreerde EHS: "
    f"**{reference_outcome.ehs_per_1000_falmouth_mean:.2f} per 1000**"
)

if year_outcomes:
    rows = []
    for ty in target_years:
        if ty not in year_outcomes:
            continue
        o = year_outcomes[ty]
        rows.append({
            "Jaar": ty,
            "Verwachte EHE-fractie (%)": round(o.ehe_fraction_mean * 100, 1),
            "EHE per 1000 (ongekalibreerd)": round(o.ehe_per_1000_mean, 0),
            f"Kans op overschrijding grens ({threshold_pct:.1f}%)": round(o.p_exceeds_threshold * 100, 0),
            "EHS per 1000 (Falmouth-gekalibreerd)": round(o.ehs_per_1000_falmouth_mean, 2),
        })
    df_out = pd.DataFrame(rows).set_index("Jaar")
    st.dataframe(df_out, use_container_width=True)

    fig = go.Figure()
    years_plot = [REFERENCE_START_YEAR + (REFERENCE_END_YEAR - REFERENCE_START_YEAR) // 2] + target_years
    ehe_vals = [reference_outcome.ehe_fraction_mean * 100] + [
        year_outcomes[y].ehe_fraction_mean * 100 for y in target_years if y in year_outcomes]
    p_exceed_vals = [reference_outcome.p_exceeds_threshold * 100] + [
        year_outcomes[y].p_exceeds_threshold * 100 for y in target_years if y in year_outcomes]

    fig.add_trace(go.Scatter(x=years_plot, y=ehe_vals, mode="lines+markers",
                             name="Verwachte EHE-fractie (%)"))
    fig.add_trace(go.Scatter(x=years_plot, y=p_exceed_vals, mode="lines+markers",
                             name=f"Kans op overschrijding grens ({threshold_pct:.1f}%)",
                             yaxis="y2"))
    fig.add_hline(y=reference_outcome.ehe_fraction_mean * 100, line_dash="dot",
                 annotation_text="Referentieperiode (verwachtingswaarde)", line_color="grey")
    fig.update_layout(
        title="EHE-projectie t.o.v. referentieperiode (indicatief, ongekalibreerd)",
        xaxis_title="Jaar (referentiepunt = midden van 1996-2025)",
        yaxis=dict(title="Verwachte EHE-fractie (%)"),
        yaxis2=dict(title="Overschrijdingskans (%)", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=450,
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Klimatos-stijl plots: trend, verdelingsverschuiving, return period ---
    st.divider()
    st.markdown("### Klimaatplots (analoog aan Klimatos.ClimateShift)")
    st.plotly_chart(_build_trend_plot(year_mean_temp, trend, target_years),
                    use_container_width=True)

    plot_year = st.selectbox(
        "Doeljaar voor de verdelings- en return-period-plot hieronder",
        options=target_years, index=len(target_years) - 1,
    )
    c_dist, c_rp = st.columns(2)
    with c_dist:
        st.plotly_chart(_build_distribution_plot(year_mean_temp, trend, plot_year),
                        use_container_width=True)
    with c_rp:
        default_threshold = float(np.mean(list(year_mean_temp.values()))
                                  + 2 * np.std(list(year_mean_temp.values()), ddof=1))
        threshold_temp = st.number_input(
            "Drempeltemperatuur voor de return-period-plot (\u00b0C, race-venster-gemiddelde)",
            value=round(default_threshold, 1), step=0.5,
        )
        st.plotly_chart(
            _build_return_period_plot(year_mean_temp, trend, plot_year, threshold_temp),
            use_container_width=True)
    st.caption(
        "De GEV-fit (stippellijn) is bij n\u224830 referentiejaren instabiel in de staart -- "
        "zelfde kanttekening als in de Klimatos-whitepaper. De Normaalfit (getrokken lijn) "
        "is hier de robuustere van de twee."
    )
else:
    st.warning("Geen enkel doeljaar leverde geldige resultaten op.")

st.divider()
with st.expander("\u2139\ufe0f Belangrijke beperkingen -- lees dit voordat je dit deelt"):
    st.markdown(
        "- **EHE is niet gekalibreerd** tegen waargenomen incidentie (in tegenstelling "
        "tot het Falmouth-gekalibreerde EHS-cijfer hiernaast). De EHE-per-1000-waarde "
        "hier is een indicatieve extrapolatie van de ensemble-fractie, geen geschatte "
        "kans op een echte gebeurtenis.\n"
        "- De toekomstprojectie is een **statistische Theil-Sen-extrapolatie** van de "
        "waargenomen trend, geschat specifiek over de uren van start tot finish "
        "(niet het etmaalgemiddelde, want opwarming verloopt 's nachts en overdag "
        "vaak verschillend) -- geen fysisch klimaatmodel en geen weersvoorspelling "
        "voor een specifiek jaar. Een individueel jaar kan altijd sterk afwijken van "
        "deze verwachtingswaarde.\n"
        "- Alleen de **luchttemperatuur** is verschoven; luchtvochtigheid, wind en "
        "bewolking zijn ongewijzigd gelaten op hun historische waarden voor die "
        "kalenderdag.\n"
        "- Trend-stationariteit binnen de referentieperiode is een aanname, niet getoetst.\n"
        "- Elke dag-realisatie draait een ensemble van "
        f"{n_simulations} deelnemers (i.p.v. de standaard {100}); de 210 dagen samen "
        "middelen ruis per losse dag grotendeels uit, maar dit blijft een indicatief "
        "instrument, geen validatiestudie."
    )
