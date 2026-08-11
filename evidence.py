# -*- coding: utf-8 -*-
"""
Evidence base — what is supported, by what, and what is not
=============================================================
A references panel that is useful in an argument has to do two things:
name the support, and be candid about its limits. A list that implies
everything is covered invites exactly the challenge it was meant to
answer, because the first informed reader will find the gap.

So each claim below carries its sources AND the scope limit: what that
literature does not establish. The unsupported items are stated as
plainly as the supported ones.
"""

from __future__ import annotations

__BUILD__ = "2026-08-11a"


# Each entry: the claim the app makes, the sources, and the honest limit.
EVIDENCE = [
    {
        "claim": "Recovery from heat strain takes days to weeks, not hours",
        "why_it_matters":
            "This is what sets the model's recovery rate, and therefore "
            "everything the multi-day view says. PYROX discharges "
            "accumulated strain over roughly 7 days (healthy adults) to 17 "
            "days (vulnerable 85+).",
        "sources": [
            ("Return to Duty Following Exertional Heat Stroke: A Review",
             "Military Medicine (2024), doi:10.1093/milmed/usad388",
             "Reports that biochemical recovery after exertional heat stroke "
             "follows a 16-day time course; US Army/Air Force practice places "
             "patients on a strict no-heat-stress profile for at least two "
             "weeks, with restrictions up to three months."),
            ("Return to duty/play after exertional heat injury: two case studies",
             "Disaster and Military Medicine (2015), doi:10.1186/s40696-015-0010-3",
             "Israeli Defence Forces test heat tolerance 6-8 weeks after the "
             "event; thermoregulatory recovery can take several months in "
             "some individuals."),
        ],
        "limit":
            "These describe recovery after exertional heat STROKE in young, "
            "fit military personnel — a severe acute injury in a population "
            "unlike most of the groups modelled here. That the time course "
            "matches is meaningful corroboration, not calibration. The model's "
            "per-group recovery rates remain reasoned estimates.",
        "status": "supported",
    },
    {
        "claim": "Health effects of heat persist after the weather improves",
        "why_it_matters":
            "This is the premise of the whole loop view: an index computed "
            "from today's weather cannot see what came before.",
        "sources": [
            ("Gronlund et al., Heat, heat waves, and hospital admissions among "
             "the elderly in the United States, 1992-2006",
             "Environ Health Perspect 122:1187-1192 (2014), doi:10.1289/ehp.1206132",
             "Extreme heat raised all-cause admissions by about 3% across the "
             "following 8 days in over-65s, with renal admissions up 15% and "
             "respiratory up 4%."),
            ("Impact of heat waves on morbidity and hospital admissions, "
             "western Mediterranean",
             "(2024), PMC11416421",
             "Uses a 7-day lag window as standard in the heat-wave definition; "
             "found raised admissions for acute kidney injury and heat stroke."),
        ],
        "limit":
            "Lag structure differs by outcome. Heat-related MORTALITY peaks "
            "within the first days and falls off quickly; morbidity and "
            "physiological recovery run longer. The model describes "
            "physiological reserve, so the morbidity and recovery literature "
            "is the relevant comparison — but that also means the model does "
            "not predict mortality timing and should not be read as doing so.",
        "status": "supported",
    },
    {
        "claim": "WBGT alone does not capture heat risk well",
        "why_it_matters":
            "Justifies the UTCI cross-check and the reason a physiological "
            "layer sits on top of the index at all.",
        "sources": [
            ("Systematic review and meta-analysis of 43 studies on WBGT risk "
             "categories and self-paced running",
             "reported 2026",
             "Runners' core temperature and heart rate did not separate "
             "between ACSM heat-risk bands as cleanly as the categories "
             "assume."),
            ("Roberts WO, Determining a 'do not start' temperature for a "
             "marathon on the basis of adverse outcomes",
             "Med Sci Sports Exerc",
             "Notes that the ACSM WBGT cascade derives from the heat "
             "tolerance of young military recruits, acclimated military "
             "personnel and laboratory subjects — not from unacclimatised, "
             "non-elite marathon runners."),
            ("WBGT formula weighting",
             "ISO 7243",
             "WBGT weights wet-bulb (humidity) at 0.7 and globe (radiant "
             "load) at 0.2, so it responds far more to humidity than to "
             "direct solar load."),
        ],
        "limit":
            "Showing that WBGT is imperfect does not establish that this "
            "model is better. It establishes that a gap exists.",
        "status": "supported",
    },
    {
        "claim": "The model's physiological components are established science",
        "why_it_matters":
            "The building blocks are not novel and do not need to be "
            "defended as such.",
        "sources": [
            ("JOS-3 thermoregulation model", "Takahashi et al., Waseda",
             "Peer-reviewed multi-node thermophysiological model."),
            ("Cardiovascular reserve equations", "Lloyd et al. (2022)",
             "Underpin the cardiac-output reserve used in the HESTIA tier."),
            ("UTCI", "Brode/Blazejczyk et al., ISO/CIE lineage",
             "Peer-reviewed physiological equivalent index."),
            ("ACSM metabolic equations", "ACSM Guidelines",
             "Walking and running VO2 from speed and grade; used here to turn "
             "pace into metabolic rate."),
            ("Minetti et al. (2002)", "J Appl Physiol 93:1039-1046",
             "Energy cost of running on gradients."),
            ("Callahan et al. (2025)", "adaptation limits",
             "Informs the acclimatisation ceiling in PYROX v2.2."),
        ],
        "limit":
            "Correct use of validated components does not make the "
            "combination validated.",
        "status": "supported",
    },
    {
        "claim": "The app's EHS estimate is anchored to real incident data",
        "why_it_matters":
            "The single most operationally relevant number this app "
            "produces -- 'how many per 1000 participants might experience "
            "EHS' -- needed a real-world anchor, not just a physiological "
            "simulation.",
        "sources": [
            ("DeMartini JK, Casa DJ, Belval LN, et al., Environmental "
             "Conditions and the Occurrence of Exertional Heat Illnesses "
             "and Exertional Heat Stroke at the Falmouth Road Race",
             "J Athl Train 49(4):478-485 (2014)",
             "18 years of Falmouth Road Race medical-tent records (12 "
             "years with finisher counts). EHS per 1000 finishers = "
             "0.004*exp(0.250*Tamb), R\u00b2=0.65, P=.001, fitted on n=12 "
             "individual race-years. Verified in this app against the "
             "paper's own Table 1 (mean absolute deviation ~0.64 per 1000 "
             "across the fitted 21-27\u00b0C range)."),
        ],
        "limit":
            "Extensive testing found HESTIA's own raw physiological "
            "simulation over-predicts this same real-world benchmark by "
            "roughly 20-50x across a comparable temperature range -- the "
            "app therefore shows the Falmouth-based estimate as the "
            "primary EHS figure, with HESTIA's raw simulation kept "
            "visible but clearly marked as uncalibrated. This is a "
            "genuine, published, peer-reviewed regression -- but it was "
            "fitted on ONE specific 7-mile race with a broad "
            "recreational-to-elite field. Applying it to a different "
            "distance, duration, or participant population is an "
            "approximation, not a validated transfer. R\u00b2=0.65 also "
            "means real years scatter meaningfully around this line -- it "
            "explains about two-thirds of year-to-year variance, not all "
            "of it.",
        "status": "supported",
    },
    {
        "claim": "PYROX's population tier predicts real incidents",
        "why_it_matters":
            "This is the claim an operational user will most want, and it is "
            "the one that cannot currently be made.",
        "sources": [],
        "limit":
            "NOT ESTABLISHED. The population tier has no event-level "
            "validation against incident or hospital records. The r=0.866 "
            "correlation with Dam tot Damloop incidents, the Falmouth "
            "hindcasts and the IRONMAN Hoorn work belong to HESTIA's "
            "INDIVIDUAL tier, which is a different model and is not what runs "
            "in this app. Most groups here also use extrapolated rather than "
            "published parameters. Use the outputs to rank groups, days and "
            "hours — not as probabilities of harm.",
        "status": "not_established",
    },
    {
        "claim": "The control-loop framing is the author's own hypothesis",
        "why_it_matters":
            "Attribution matters, in both directions: credit where it is due, "
            "and no borrowed authority.",
        "sources": [
            ("Conjunctive EHS criterion (T_rect > 40.5 C AND CO_reserve <= 0)",
             "author's own hypothesis, from control engineering",
             "The 40.5 C threshold is Roberts'; the cardiac-output reserve "
             "condition draws on Rowell and Gonzalez-Alonso. The CONJUNCTION "
             "of the two as a joint failure criterion is the author's, not "
             "taken from Veltmeijer or any other published source."),
        ],
        "limit":
            "A coherent, testable hypothesis under peer review — not settled "
            "science. A PYROX preprint is under review at the International "
            "Journal of Biometeorology (doi:10.21203/rs.3.rs-6826369/v1).",
        "status": "hypothesis",
    },
]

_STATUS_BADGE = {
    "supported": ("\u2705", "Supported by published literature"),
    "not_established": ("\u274c", "NOT established — stated plainly"),
    "hypothesis": ("\U0001F9EA", "Author's hypothesis, under peer review"),
}


def render_evidence_panel(st, expanded: bool = False) -> None:
    """Render the evidence base. Intended to sit near the bottom of the app,
    where someone challenging its applicability will look."""
    with st.expander("\U0001F4DA Evidence base — what supports this, and what does not",
                     expanded=expanded):
        st.markdown(
            "Grouped by the specific claim each source supports. The scope "
            "limits are part of the answer, not a disclaimer bolted on: the "
            "quickest way to lose an argument about applicability is to have "
            "claimed more than the sources carry."
        )
        for item in EVIDENCE:
            icon, badge = _STATUS_BADGE[item["status"]]
            st.markdown(f"### {icon} {item['claim']}")
            st.caption(f"*{badge}* \u2014 {item['why_it_matters']}")
            if item["sources"]:
                for title, ref, finding in item["sources"]:
                    st.markdown(f"- **{title}** \u2014 {ref}  \n  {finding}")
            if item["status"] == "not_established":
                st.error(item["limit"])
            else:
                st.info(f"**Scope limit:** {item['limit']}")
        st.caption(
            "Suite documentation: `pyrox_revised_calibration.py` carries the "
            "full derivation of the revised parameters and the three defects "
            "they correct; `loop_view.py` documents the control-loop mapping; "
            "`decision_support.py` documents the WBGT/UTCI divergence check."
        )
