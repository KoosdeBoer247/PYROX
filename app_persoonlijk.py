# -*- coding: utf-8 -*-
"""
app_persoonlijk.py
===================
PYROX \u2014 personal assessment page.

One real person's own biometrics, one real event, run through the same
JOS-3 + CVR engine and dose-response calibration as the population apps
(individual_engine.py). See that module's docstring for the privacy
architecture and the ensemble design rationale in full; this file is UI
only -- it collects PersonalInputs/EventScenario, calls
run_individual_assessment(), and renders the result. All persistence
goes through local_storage.py (plain local JSON, never transmitted).

PRIVACY NOTICE SHOWN ON-SCREEN
--------------------------------
The banner below is not decorative -- it is the one sentence a user of
this page most needs before typing in their weight and age. Keep it
accurate if this file is edited: the only outbound calls this page (via
individual_engine.fetch_scenario_weather) makes are geocoding a place
name and fetching weather for lat/lon/date. Nothing else leaves the
machine.
"""

from datetime import date, time as dtime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from individual_engine import (
    PersonalInputs, EventScenario, run_individual_assessment,
    assessment_caveats, dose_scatter_points, representative_trajectories,
    zone_episode,
)
from individual_report import generate_individual_report_docx
from Thermopoulos_Data_Engine import ROUGHNESS_Z0_TERRAIN
import local_storage as store

st.set_page_config(page_title="PYROX \u2014 Personal", page_icon="\U0001F3C3", layout="wide")
st.title("\U0001F3C3 PYROX \u2014 personal heat-risk assessment")
st.info(
    "\U0001F512 **Privacy:** your details and the results below stay on this "
    "computer. The only information sent anywhere is the event's place "
    "name and date/time, to fetch weather \u2014 never your height, weight, "
    "age, pace, or any outcome.",
    icon="\U0001F512",
)

GENDER_OPTIONS = {"Man": "male", "Vrouw": "female"}


# =============================================================================
# Profile: load / fill in / save
# =============================================================================
st.markdown("### \U0001F464 Wie ben je")

saved = store.list_profiles()
col_load, col_new = st.columns([2, 1])
with col_load:
    pick = st.selectbox(
        "Opgeslagen profiel laden (optioneel)",
        options=["\u2014 nieuw profiel \u2014"] + saved,
    )
loaded_inputs = None
if pick != "\u2014 nieuw profiel \u2014":
    try:
        loaded_inputs = store.load_profile(pick)
        st.success(f"Profiel '{pick}' geladen.")
    except FileNotFoundError:
        st.warning("Kon dit profiel niet meer vinden \u2014 mogelijk verwijderd.")

def _default(field, fallback):
    return getattr(loaded_inputs, field) if loaded_inputs is not None else fallback

c1, c2, c3, c4 = st.columns(4)
with c1:
    height_cm = st.number_input("Lengte (cm)", 130, 220,
                                 value=int(round(_default("height_m", 1.78) * 100)))
with c2:
    weight_kg = st.number_input("Gewicht (kg)", 30.0, 200.0,
                                 value=float(_default("weight_kg", 75.0)), step=0.5)
with c3:
    age = st.number_input("Leeftijd", 10, 90, value=int(_default("age", 45)))
with c4:
    gender_label = st.selectbox(
        "Geslacht", list(GENDER_OPTIONS.keys()),
        index=0 if _default("gender", "male") == "male" else 1,
    )

c5, c6 = st.columns(2)
with c5:
    pace_min = st.number_input(
        "Verwacht tempo \u2014 minuten per km", 2.5, 15.0,
        value=float(_default("expected_pace_min_per_km", 6.0)), step=0.1,
        help="Je eigen verwachte tempo voor dit evenement, niet een wedstrijdrecord.",
    )
with c6:
    st.caption(" ")
    st.caption(" ")

st.markdown("##### Gedrag en gebruik")
b1, b2, b3 = st.columns(3)
with b1:
    nsaid_use = st.toggle("Gebruikt NSAID's (bv. ibuprofen) voor/tijdens",
                           value=_default("nsaid_use", False))
with b2:
    drinks_readily = st.toggle("Drinkt bij vrijwel elke post",
                                value=_default("drinks_readily", True),
                                help="Uit: wacht tot echt dorstig.")
with b3:
    heat_acclimatized = st.toggle("Recent (2+ weken) getraind/gewoond in hitte",
                                   value=_default("heat_acclimatized", False))

with st.expander("Optioneel \u2014 als je deze echt weet (bv. van een sporthorloge of meting)"):
    o1, o2 = st.columns(2)
    with o1:
        known_vo2max_input = st.number_input(
            "VO2max (mL/kg/min) \u2014 laat op 0 voor schatting o.b.v. leeftijd/geslacht",
            0.0, 90.0, value=float(_default("known_vo2max", 0.0) or 0.0), step=0.5)
    with o2:
        known_bodyfat_input = st.number_input(
            "Vetpercentage (%) \u2014 laat op 0 voor schatting",
            0.0, 50.0, value=float(_default("known_body_fat_pct", 0.0) or 0.0), step=0.5)

inputs = PersonalInputs(
    height_m=height_cm / 100.0,
    weight_kg=weight_kg,
    age=int(age),
    gender=GENDER_OPTIONS[gender_label],
    expected_pace_min_per_km=pace_min,
    nsaid_use=nsaid_use,
    drinks_readily=drinks_readily,
    heat_acclimatized=heat_acclimatized,
    known_vo2max=known_vo2max_input or None,
    known_body_fat_pct=known_bodyfat_input or None,
)

save_col1, save_col2 = st.columns([3, 1])
with save_col1:
    profile_name = st.text_input("Naam om profiel onder op te slaan", value=pick if pick != "\u2014 nieuw profiel \u2014" else "")
with save_col2:
    st.write("")
    st.write("")
    if st.button("\U0001F4BE Profiel opslaan", use_container_width=True):
        if not profile_name.strip():
            st.warning("Geef eerst een naam op.")
        else:
            try:
                inputs.validate()
                store.save_profile(profile_name.strip(), inputs)
                st.success(f"Opgeslagen als '{profile_name.strip()}' \u2014 alleen op deze computer.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

# =============================================================================
# Event
# =============================================================================
st.markdown("### \U0001F4CD Evenement")
e1, e2 = st.columns([2, 1])
with e1:
    location_query = st.text_input("Plaats / evenement locatie", value="Utrecht, Nederland")
with e2:
    use_historical = st.toggle("Historisch (al gebeurd)", value=False,
                                help="Aan: gebruik echt gemeten weer voor een datum in het verleden. "
                                     "Uit: gebruik de weersverwachting voor een komende datum.")

e3, e4, e5 = st.columns(3)
with e3:
    event_date = st.date_input("Datum", value=date.today())
with e4:
    event_time = st.time_input("Starttijd", value=dtime(10, 30))
with e5:
    duration_minutes = st.number_input("Duur (minuten)", 10, 600, value=100)

terrain_key = st.selectbox(
    "Terreintype (10m \u2192 1,5m windprofiel)",
    options=list(ROUGHNESS_Z0_TERRAIN.keys()),
    format_func=lambda k: ROUGHNESS_Z0_TERRAIN[k][0],
    index=2,
    help="Zelfde terreincategorie\u00ebn als de beleidsweergave; be\u00efnvloedt alleen "
         "de windcorrectie tussen de 10m-meethoogte en loophoogte.",
)

scenario = EventScenario(
    location_query=location_query,
    start_local=pd.Timestamp.combine(event_date, event_time),
    duration_minutes=float(duration_minutes),
    use_historical=use_historical,
    terrain_key=terrain_key,
)

with st.expander("Geavanceerd"):
    n_ensemble = st.slider(
        "Aantal ensemble-runs", 50, 400, 200, step=50,
        help="Hoger = stabielere band, maar langzamer. ~200 duurt ongeveer 60\u201390 seconden.")
    training_factor = st.slider("Trainingsfactor (0=ongetraind, 1=zeer getraind)", 0.0, 1.0, 0.5)

run = st.button("\U0001F3C3 Bereken", type="primary", use_container_width=True)

# =============================================================================
# Run + display
# =============================================================================
if run:
    try:
        inputs.validate()
    except ValueError as e:
        st.error(f"Controleer je gegevens: {e}")
        st.stop()
    if not location_query.strip():
        st.error("Vul een locatie in.")
        st.stop()

    progress = st.progress(0, text="Starten\u2026")

    def _on_progress(frac: float, text: str) -> None:
        progress.progress(min(int(frac * 100), 100), text=text)

    try:
        result = run_individual_assessment(
            inputs, scenario, n_ensemble=int(n_ensemble),
            training_factor=float(training_factor),
            progress_callback=_on_progress,
        )
    except Exception as e:
        progress.empty()
        st.error(f"Berekening mislukt: {e}")
        st.stop()
    progress.empty()
    st.session_state["laatste_resultaat"] = result
    st.session_state["laatste_scenario"] = scenario

result = st.session_state.get("laatste_resultaat")
scenario_shown = st.session_state.get("laatste_scenario")

if result is not None:
    st.markdown(f"### \U0001F4CA Resultaat \u2014 {result.city_name}")
    st.caption(f"Gemiddelde luchttemperatuur in het raceraam: {result.mean_t_air_c:.1f}\u00b0C "
               f"\u2014 gebaseerd op {result.n_ensemble} persoonlijke ensemble-runs.")

    m1, m2, m3 = st.columns(3)
    m1.metric("Conjunctie (T_rect\u226540.5\u00b0C \u00e9n CO_reserve\u22640)",
              f"{result.conjunction_fraction:.0%}",
              help="Aandeel van je ensemble-runs waarin beide voorwaarden gelijktijdig optraden, "
                   "tijdens de inspanning of in de 10 minuten erna.")
    ehs = result.ehs_interval
    if "error" not in ehs:
        # Shown as a percentage, not "per 1000": this run describes one
        # person, and "per 1000" invites the reasonable-but-wrong
        # question "1000 of what?" when there is no population here.
        # The label deliberately does NOT say "kans op EHS" outright --
        # this number is Falmouth Road Race population epidemiology
        # (DeMartini et al.) applied to this person's simulated dose,
        # not a probability independently validated for this individual.
        # Overstating it as "the chance" would quietly undo the same
        # epistemic caution uncertainty.py's caveats exist to keep.
        pct = ehs["point_per_1000"] / 10.0
        pct_lo = ehs["lo_per_1000"] / 10.0
        pct_hi = ehs["hi_per_1000"] / 10.0
        m2.metric(
            "Geschatte EHS-kans (o.b.v. vergelijkbare gevallen)",
            f"\u2248{pct:.2f}%",
            delta=f"{pct_lo:.2f}\u2013{pct_hi:.2f}% sampling+anker",
            delta_color="off",
            help="Gebaseerd op epidemiologie van vergelijkbare hardlopers (Falmouth Road Race-"
                 "data), toegepast op jouw gesimuleerde dosis \u2014 geen kans die specifiek voor "
                 "jou is gevalideerd.",
        )
    m3.metric("T_rect piek (mediaan)", f"{np.nanmax(result.t_rect_median):.2f}\u00b0C")

    from uncertainty import fraction_interval, format_fraction_interval, fraction_caveats
    _ehe_ci = fraction_interval(result.ehe_hits, result.n_ensemble)
    _eac_ci = fraction_interval(result.eac_hits, result.n_ensemble)
    e1, e2 = st.columns(2)
    e1.metric(
        "EHE \u2014 uitputting door hitte (T_rect>39,5\u00b0C \u00e9n CO_reserve<0)",
        format_fraction_interval(_ehe_ci),
        delta=f"dosis: gem. {result.ehe_dose_mean:.2f} | {result.ehe_dose_among_hits:.2f} bij getroffenen",
        delta_color="off",
        help="Exertional Heat Exhaustion: uitputting door hitte tijdens de inspanning. "
             "Markeert het moment waarop je temperatuur alleen nog stabiel blijft omdat "
             "warmteproductie en -verlies toevallig in balans zijn, terwijl je "
             "cardiovasculaire reserve verder wegzakt. De dosis zegt meer dan het "
             "percentage \u2014 het gaat om hoe lang en hoe diep, niet om het passeren "
             "van een grens.",
    )
    e2.metric(
        "EAC \u2014 collaps na de finish (CO_reserve<0, geen temperatuureis)",
        format_fraction_interval(_eac_ci),
        delta=f"dosis: gem. {result.eac_dose_mean:.2f} | {result.eac_dose_among_hits:.2f} bij getroffenen",
        delta_color="off",
        help="Exercise-Associated Collapse: het niet zelfstandig kunnen staan of lopen "
             "n\u00e1 de finish, door bloeddrukval wanneer de spierpomp wegvalt. "
             "Cardiovasculair, niet thermisch \u2014 daarom bewust z\u00f3nder "
             "temperatuurdrempel.",
    )
    _fc = (fraction_caveats(_ehe_ci, "EHE-criterium")
           + fraction_caveats(_eac_ci, "EAC-criterium"))
    if _fc:
        with st.expander("\u26a0\ufe0f Hoe nauwkeurig zijn deze percentages?"):
            for _c in _fc:
                st.markdown("- " + _c)
            st.caption(
                "Dit gaat uitsluitend over het aantal simulaties, niet over de "
                "vraag of de fysiologie of de drempels kloppen.")
    if "error" not in ehs:
        def _freq_phrase(lo1000: float, hi1000: float) -> str:
            lo_r, hi_r = round(lo1000), round(hi1000)
            if hi_r < 1:
                return "minder dan 1 op de 1000"
            if lo_r == hi_r:
                return f"ongeveer {lo_r} op de 1000"
            return f"ongeveer {lo_r} tot {hi_r} op de 1000"

        st.caption(
            f"Ter vergelijking: {_freq_phrase(ehs['lo_per_1000'], ehs['hi_per_1000'])} in "
            f"soortgelijke omstandigheden. Dit is een populatiegemiddelde toegepast op jouw "
            f"situatie \u2014 geen unieke, voor jou gevalideerde kans."
        )

    x_finish = result.median_stop_minute
    x_max_chart = max(result.minutes) if result.minutes else x_finish

    meteo = result.meteo
    fig_m = go.Figure()
    for key, label, color in [
        ("t_air", "T_air", "#f59e0b"),
        ("wbgt", "WBGT", "#dc2626"),
        ("utci", "UTCI", "#7c3aed"),
        ("mrt", "MRT", "#0891b2"),
    ]:
        fig_m.add_trace(go.Scatter(x=meteo["time"], y=meteo[key], mode="lines",
                                    line=dict(color=color, width=2), name=label))
    fig_m.update_layout(
        title="Weersomstandigheden tijdens de inspanning",
        yaxis_title="\u00b0C", height=320, margin=dict(t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.10, x=0.0),
    )
    st.plotly_chart(fig_m, use_container_width=True)
    st.caption(
        "T_air = luchttemperatuur, WBGT = Wet Bulb Globe Temperature, UTCI = Universal "
        "Thermal Climate Index, MRT = gemiddelde stralingstemperatuur. Alle vier in \u00b0C, "
        "over het raceraam \u2014 dit venster heeft geen equivalent na de finish."
    )

    fig_t = go.Figure()
    fig_t.add_vrect(x0=x_finish, x1=x_max_chart, fillcolor="rgba(148,163,184,0.10)",
                     line_width=0, layer="below")
    fig_t.add_trace(go.Scatter(x=result.minutes, y=result.t_rect_hi, line=dict(width=0),
                                showlegend=False, hoverinfo="skip"))
    fig_t.add_trace(go.Scatter(x=result.minutes, y=result.t_rect_lo, line=dict(width=0),
                                fill="tonexty", fillcolor="rgba(220,80,50,0.18)",
                                name="2,5\u201397,5e percentiel", hoverinfo="skip"))
    fig_t.add_trace(go.Scatter(x=result.minutes, y=result.t_rect_median,
                                line=dict(color="rgb(190,40,20)", width=2), name="Mediaan"))
    fig_t.add_hline(y=40.5, line_dash="dot", line_color="darkred",
                     annotation_text="40.5\u00b0C (EHS-drempel)")
    fig_t.add_vline(x=x_finish, line_dash="dash", line_color="#64748b",
                     annotation_text="Finish (mediaan)", annotation_position="top")
    fig_t.update_layout(title="T_rectaal over tijd \u2014 inspanning + 10 min herstel",
                         xaxis_title="Minuten sinds start", yaxis_title="\u00b0C", height=350,
                         margin=dict(t=40, b=20))
    st.plotly_chart(fig_t, use_container_width=True)
    st.caption(
        "De band (2,5\u201397,5e percentiel) toont de spreiding binnen je eigen ensemble \u2014 "
        "onzekerheden zoals pacing-respons, windrichting en zweetvariatie. Ze dekt **niet** de "
        "hellingsonzekerheid van het onderliggende dosis-responsmodel, de grootste, nog niet "
        "gekwantificeerde foutbron in dit project (zie de kanttekeningen bij de EHS-schatting "
        "hierboven). Een bredere band betekent dus niet dat het volledige worst-case-scenario "
        "hier al in zit."
    )

    fig_c = go.Figure()
    fig_c.add_vrect(x0=x_finish, x1=x_max_chart, fillcolor="rgba(148,163,184,0.10)",
                     line_width=0, layer="below")
    fig_c.add_trace(go.Scatter(x=result.minutes, y=result.co_reserve_hi, line=dict(width=0),
                                showlegend=False, hoverinfo="skip"))
    fig_c.add_trace(go.Scatter(x=result.minutes, y=result.co_reserve_lo, line=dict(width=0),
                                fill="tonexty", fillcolor="rgba(30,90,180,0.15)",
                                name="2,5\u201397,5e percentiel", hoverinfo="skip"))
    fig_c.add_trace(go.Scatter(x=result.minutes, y=result.co_reserve_median,
                                line=dict(color="rgb(20,70,160)", width=2), name="Mediaan"))
    fig_c.add_hline(y=0, line_dash="dot", line_color="darkblue",
                     annotation_text="CO_reserve = 0")
    fig_c.add_vline(x=x_finish, line_dash="dash", line_color="#64748b",
                     annotation_text="Finish (mediaan)", annotation_position="top")
    fig_c.update_layout(title="Cardiale reservecapaciteit (CO_reserve) over tijd \u2014 inspanning + 10 min herstel",
                         xaxis_title="Minuten sinds start", yaxis_title="L/min", height=350,
                         margin=dict(t=40, b=20))
    st.plotly_chart(fig_c, use_container_width=True)
    st.caption(
        "Grijs gearceerd = het herstelvenster na de finish. Cardiale reserve herstelt daar "
        "doorgaans sneller dan T_rectaal daalt, omdat de metabole vraag na het stoppen direct "
        "wegvalt terwijl de warmte-uitwisseling langzamer verloopt \u2014 een verwacht na-ijl-effect."
    )

    scatter_data = dose_scatter_points(result.all_traces)
    if len(scatter_data["t_rect"]) > 0:
        t_vals, c_vals, d_vals, phase_vals = (
            scatter_data["t_rect"], scatter_data["co_reserve"],
            scatter_data["dose"], scatter_data["phase"])
        x_min, x_max = min(37.0, float(t_vals.min()) - 0.2), max(41.5, float(t_vals.max()) + 0.2)
        y_min, y_max = min(-1.0, float(c_vals.min()) - 0.3), max(3.0, float(c_vals.max()) + 0.3)
        max_dose = float(d_vals.max()) if len(d_vals) else 0.0
        has_dose = max_dose > 0

        fig_s = go.Figure()
        fig_s.add_shape(type="rect", x0=40.5, x1=x_max, y0=y_min, y1=0,
                         fillcolor="rgba(127,0,0,0.12)", line_width=0, layer="below")
        fig_s.add_hline(y=0, line_dash="dot", line_color="#94a3b8")
        fig_s.add_vline(x=40.5, line_dash="dot", line_color="#94a3b8")

        # Race and post-finish plotted as separate traces (different
        # marker symbol) -- these can otherwise look like two unrelated
        # clusters (CO_reserve rebounding while T_rect lags behind, a
        # real recovery-phase pattern) with no visual explanation.
        # Custom colorscale: OrRd's low end is near-white, which made
        # every dose\u22480 point (the vast majority, in a normally mild
        # scenario) nearly invisible against the white chart background.
        # This scale starts at a visible pale blue instead of white, so
        # "no dose yet" still reads as a clear dot, not a gap.
        _dose_colorscale = [
            [0.0, "#bfdbfe"], [0.15, "#93c5fd"], [0.4, "#fde68a"],
            [0.7, "#f97316"], [1.0, "#7f1d1d"],
        ]
        for phase, symbol, label in [("race", "circle", "Tijdens de inspanning"),
                                      ("postfinish", "diamond", "Herstel (10 min na finish)")]:
            mask = phase_vals == phase
            if not mask.any():
                continue
            marker = dict(size=6, symbol=symbol,
                          line=dict(width=0.6, color="rgba(51,65,85,0.35)"))
            if has_dose:
                marker.update(color=d_vals[mask], colorscale=_dose_colorscale, cmin=0, cmax=max_dose,
                               showscale=(phase == "race"),
                               colorbar=dict(title="Cumulatieve<br>dosis") if phase == "race" else None)
            else:
                marker["color"] = "#3b82f6" if phase == "race" else "#7c3aed"
            fig_s.add_trace(go.Scatter(
                x=t_vals[mask], y=c_vals[mask], mode="markers", marker=marker,
                name=label,
                hovertemplate=(f"{label}<br>T_rect=%{{x:.2f}}\u00b0C<br>"
                                "CO_reserve=%{y:.2f} L/min<br>"
                                + ("dosis tot dan=%{marker.color:.1f}<extra></extra>"
                                   if has_dose else "<extra></extra>")),
            ))

        fig_s.update_layout(
            title="T_rectaal vs CO_reserve \u2014 elk punt is (ensemblelid, tijdstip)",
            xaxis_title="T_rect (\u00b0C)", yaxis_title="CO_reserve (L/min)",
            xaxis_range=[x_min, x_max], yaxis_range=[y_min, y_max],
            height=460, margin=dict(t=90, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.10, x=0.0),
        )
        st.plotly_chart(fig_s, use_container_width=True)

        has_postfinish_only_spread = (
            (phase_vals == "postfinish").any()
            and float(c_vals[phase_vals == "postfinish"].max())
                > float(c_vals[phase_vals == "race"].max() if (phase_vals == "race").any() else -1e9) + 1.0
        )
        base_caption = (
            "Rood gearceerd = de conjunctiezone (T_rect\u226540,5\u00b0C \u00e9n CO_reserve\u22640), "
            "dezelfde zone die de conjunctie-metriek hierboven telt. De bovenste bandgrafiek "
            "toont alleen het raceraam; deze scatter bevat ook de 10 minuten herstel na de "
            "finish (ruit-vormige punten) \u2014 vandaar het bredere CO_reserve-bereik hier."
        )
        if has_dose:
            st.caption(
                base_caption + " Kleur = cumulatieve dosis **tot dat tijdstip** binnen de "
                "conjunctiezone, per ensemblelid \u2014 niet de einddosis van dat lid."
            )
        else:
            st.caption(
                base_caption + " Geen enkel ensemblelid kwam in de conjunctiezone terecht \u2014 "
                "de dosis bleef in alle runs op 0."
            )
        if has_postfinish_only_spread:
            st.caption(
                "\u2139\ufe0f De ruit-vormige (herstel-)punten liggen hoger in CO_reserve dan alle "
                "race-punten: cardiale reserve veert na het stoppen sneller terug dan T_rectaal "
                "daalt \u2014 een verwacht na-ijl-effect, geen fout in de simulatie."
            )
    else:
        st.caption("Geen bruikbare T_rect/CO_reserve-punten in deze run om te tonen.")

    # --- Complementary view: a few representative PATHS instead of a
    # cloud of disconnected points. Reuses the same selection rule the
    # population apps' Word-report dose-evolution chart already uses.
    reps = representative_trajectories(result.all_traces)
    if reps:
        _label_nl = {
            "Population median": "Ensemblemediaan",
            "Lowest risk (dose=0)": "Laagste risico (dosis=0)",
            "Median non-zero dose": "Mediane niet-nul dosis",
            "Highest dose": "Hoogste dosis",
            "Coolest participant": "Koelste run",
            "Median participant": "Mediane run",
            "Hottest participant": "Heetste run",
        }
        _individual_palette = ["#2a9d8f", "#e9a942", "#c1121f"]

        fig_r = go.Figure()
        cloud = dose_scatter_points(result.all_traces)
        if len(cloud["t_rect"]):
            fig_r.add_trace(go.Scatter(
                x=cloud["t_rect"], y=cloud["co_reserve"], mode="markers",
                marker=dict(size=3, color="rgba(148,163,184,0.28)"),
                name="Volledig ensemble (context)", hoverinfo="skip",
            ))
        fig_r.add_shape(type="rect", x0=40.5, x1=42.5, y0=-2, y1=0,
                         fillcolor="rgba(127,0,0,0.10)", line_width=0, layer="below")
        fig_r.add_hline(y=0, line_dash="dot", line_color="#94a3b8")
        fig_r.add_vline(x=40.5, line_dash="dot", line_color="#94a3b8")

        individual_i = 0
        for tr in reps:
            label_nl = _label_nl.get(tr["label"], tr["label"])
            if tr["label"] == "Population median":
                color = "#1e293b"
                line_style = dict(color=color, width=2.5, dash="dash")
            else:
                color = _individual_palette[individual_i % len(_individual_palette)]
                individual_i += 1
                line_style = dict(color=color, width=2)
            fig_r.add_trace(go.Scatter(
                x=tr["t"], y=tr["c"], mode="lines", line=line_style, name=label_nl,
                hovertemplate=(f"{label_nl}<br>T_rect=%{{x:.2f}}\u00b0C<br>"
                                "CO_reserve=%{y:.2f} L/min<extra></extra>"),
            ))
            if tr.get("stopped_at") is not None and tr["min"]:
                finish_idx = min(range(len(tr["min"])),
                                  key=lambda i: abs(tr["min"][i] - tr["stopped_at"]))
                fig_r.add_trace(go.Scatter(
                    x=[tr["t"][finish_idx]], y=[tr["c"][finish_idx]], mode="markers",
                    marker=dict(size=11, symbol="star", color=color,
                                line=dict(width=1, color="white")),
                    showlegend=False,
                    hovertemplate=f"{label_nl} \u2014 finish<extra></extra>",
                ))

        all_t = list(cloud["t_rect"]) + [v for tr in reps for v in tr["t"]]
        all_c = list(cloud["co_reserve"]) + [v for tr in reps for v in tr["c"]]
        if all_t and all_c:
            fig_r.update_layout(
                xaxis_range=[min(37.0, min(all_t) - 0.2), max(41.5, max(all_t) + 0.2)],
                yaxis_range=[min(-1.0, min(all_c) - 0.3), max(3.0, max(all_c) + 0.3)],
            )
        fig_r.update_layout(
            title="T_rectaal vs CO_reserve \u2014 representatieve paden door de tijd",
            xaxis_title="T_rect (\u00b0C)", yaxis_title="CO_reserve (L/min)",
            height=440, margin=dict(t=90, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.10, x=0.0),
        )
        st.plotly_chart(fig_r, use_container_width=True)
        st.caption(
            "Elke gekleurde lijn is \u00e9\u00e9n representatief ensemblelid, gevolgd door de tijd "
            "heen \u2014 dus een pad, geen losse punten. \u2605 = het moment waarop dat lid zelf "
            "finishte. De lichte puntenwolk op de achtergrond toont het volledige ensemble ter "
            "context, dezelfde data als de scatter hierboven."
        )

        # Automatic, per-line explanation of WHEN a member entered/left
        # the danger zone -- a static chart doesn't make this timing
        # visible by itself, and "recovered" means something different
        # depending on whether it happened during exertion or only
        # after stopping (see zone_episode()'s docstring).
        zone_lines = []
        individual_i = 0
        for tr in reps:
            label_nl = _label_nl.get(tr["label"], tr["label"])
            ep = zone_episode(tr)
            if ep is None:
                continue
            if ep["entered_only_postfinish"]:
                zone_lines.append(
                    f"**{label_nl}**: kwam de conjunctiezone pas **na de finish** binnen \u2014 "
                    f"nooit tijdens de race zelf. T_rectaal liep na het stoppen nog door tot de "
                    f"drempel geraakt werd (het na-ijl-effect); stoppen bleek hier niet meteen "
                    f"voldoende bescherming."
                )
            elif ep["exited_during_race"]:
                zone_lines.append(
                    f"**{label_nl}**: kwam de conjunctiezone in \u00e9n er weer uit, **terwijl nog "
                    f"gelopen werd**. Het lichaam trok zichzelf hier terug onder belasting \u2014 "
                    f"het meest geruststellende van de drie patronen."
                )
            elif ep["in_zone_at_finish"]:
                zone_lines.append(
                    f"**{label_nl}**: zat nog in de conjunctiezone **op het moment van finishen**. "
                    f"Als de lijn daarna herstelt, komt dat vrijwel zeker doordat de inspanning "
                    f"stopte (de hartslagvraag valt dan snel weg), niet doordat de warmtedreiging "
                    f"al was opgelost."
                )
        if zone_lines:
            st.markdown("**Wanneer kwam elk pad de conjunctiezone in of uit?**")
            for line in zone_lines:
                st.markdown(f"- {line}")


    with st.expander("\u26a0\ufe0f Wat dit wel en niet betekent", expanded=True):
        for c in assessment_caveats(result):
            st.markdown(f"- {c}")

    if profile_name.strip():
        if st.button("\U0001F4BE Deze uitkomst opslaan bij dit profiel (lokaal, incl. scatterdata)"):
            path = store.save_assessment(profile_name.strip(), scenario_shown, result,
                                          include_traces=True)
            st.success(f"Opgeslagen: {path.name} \u2014 alleen op deze computer. "
                       f"Inclusief de ruwe data voor de scatterplot hierboven "
                       f"(bij deze ensemblegrootte is dat een paar honderd KB, "
                       f"geen probleem \u2014 anders dan bij een volledige populatierun).")

    st.download_button(
        "\U0001F4C4 Download persoonlijk rapport (Word)",
        data=generate_individual_report_docx(inputs, scenario_shown, result),
        file_name=(f"pyrox_persoonlijk_{result.city_name.split(',')[0]}_"
                   f"{scenario_shown.start_local.date()}.docx"),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        help="Een Word-rapport met je profiel, het evenement, de weersomstandigheden, "
             "de EHS-schatting met kanttekeningen, en de T_rect/CO_reserve-grafieken \u2014 "
             "gegenereerd volledig lokaal, uit de al-berekende uitkomst hierboven "
             "(geen nieuwe simulatie, geen netwerkverkeer). In het Engels, net als de "
             "andere PYROX-rapporten in deze suite.",
    )

    hist = store.list_history(profile_name.strip()) if profile_name.strip() else []
    if hist:
        with st.expander(f"\U0001F4C1 Eerdere opgeslagen resultaten voor '{profile_name.strip()}' ({len(hist)})"):
            for h in hist:
                st.write(f"{h['saved_at']} \u2014 {h['location']} ({h['mean_t_air_c']:.1f}\u00b0C, "
                         f"conjunctie {h['conjunction_fraction']:.0%})")
