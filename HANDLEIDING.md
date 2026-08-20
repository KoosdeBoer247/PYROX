# PYROX — handleiding voor GitHub en Streamlit

Deze handleiding beschrijft hoe je dit project beheert zonder opnieuw in de
valkuilen te lopen die we onderweg zijn tegengekomen. Elke waarschuwing hierin
staat er omdat het één keer is misgegaan.

Versie van deze set: **build 2026-08-17a**
Laatst geverifieerd: alle modules compileren, alle acceptatietests slagen
(`test_revised_calibration.py`, `test_cvr_freeze_fix.py`,
`test_uncertainty.py`, `test_individual_engine.py`), alle vier de apps
starten zonder fouten. Let op: `app.py` en `app_athletes.py` staan op
buildstempel 2026-08-12a, `app_beleid.py` en `app_persoonlijk.py` op
2026-08-17a — verschillende bestanden mogen verschillende buildstempels
hebben, zolang elk bestand zijn eigen stempel maar ophoogt bij een wijziging

**Sinds 2026-08-14a, kort:** `app_beleid.py` heeft nu ook een hindcast-
modus (zijbalk: "Weather source" → "Historical (hindcast)"), waarmee je
dezelfde analyse op een datum in het verleden kunt draaien met
waargenomen weerdata in plaats van een voorspelling — voor het toetsen
van een voorspelling tegen een al bekende gebeurtenis. Het Word-rapport en
het voorspellingsrecord (Excel) labelen zichzelf dan automatisch als
"HINDCAST". Zie GEBRUIKSAANWIJZING.md voor de volledige uitleg.
(zie §7).

**Sinds 2026-08-12c, kort:** een derde app is toegevoegd, `app_beleid.py` —
een sterk vereenvoudigde weergave voor beleidsmakers en evenementorganisatoren
die alleen het eindresultaat nodig hebben, zonder de PROVISIONAL-kalibratie-
kanttekeningen en methodologie-uitleg die de onderzoeksapp wél toont. Zie §1.

**Sinds 2026-08-10b, kort:** de dosis-responscurve waarop het HESTIA-
hoofdgetal is gebaseerd, is opnieuw gefit ná de clo-correctie hieronder — de
oorspronkelijke fit was gekalibreerd op simulaties die structureel te heet
liepen. De nieuwe fit is losser (minder deelnemers raken het gevarenkwadrant
ooit), en dat staat expliciet zo in de app en in GEBRUIKSAANWIJZING.md §3.6.

**Sinds 2026-08-09, kort:** een hydratatiebug in `hestia_model.py` is
gefixed — de cardiovasculaire-reservemodule las een aparte, nooit-
gedecrementeerde vochtverliesteller (`cvr_water_loss_kg`) in plaats van de
teller die het model se eigen drink-simulatie al correct bijhield. Gevolg:
cardiovasculaire reserve leek te eroderen ook bij mild, constant weer zonder
enige hitte-escalatie. Zie de code-comment bij `calculate_indices_jos3_adult`
in `hestia_model.py` voor de volledige diagnose.

**Sinds 2026-08-06a, kort:** een verkeerd ingevulde kledingisolatiewaarde
(clo=0,5 -> 0,2) bleek de HESTIA-simulatie structureel te heet te laten
lopen; gecorrigeerd en gecheckt tegen Veltmeijer et al. 2014 en Falmouth/
DeMartini et al. 2014. Het HESTIA-hoofdgetal is sindsdien een dosis-
responsmodel (logistische curve op cumulatief T_rect/CO_reserve-tekort),
niet meer de temperatuur-alleen-Falmouth-schatting. Zie GEBRUIKSAANWIJZING.md
paragraaf 3.6 voor de volledige uitleg.

---

## 1. De opzet in één alinea

Eén GitHub-repository bevat alle bestanden. Streamlit draait daar **vier
apps** uit, die verschillen in welk bestand het startpunt is en welke
modelmotor eronder zit (zie `README.md`: PYROX-tier vs. HESTIA-tier).
Binnen elke tier worden modellen en rekenmodules gedeeld. Een correctie in
bijvoorbeeld `decision_support.py` werkt daardoor meteen door in de drie
apps die het gebruiken (`app.py`, `app_athletes.py`, `app_beleid.py`) —
`app_persoonlijk.py` heeft zijn eigen, kleinere module­set
(`individual_engine.py`, `individual_report.py`, `local_storage.py`,
`uncertainty.py`) en importeert `decision_support.py` niet. Dat is met
opzet zo: meerdere kopieën van dezelfde logica lopen na verloop van tijd
altijd uit elkaar, en niets waarschuwt je daarvoor.

| App | Startbestand | Voor wie |
|---|---|---|
| PYROX (algemeen) | `app.py` | bevolkingsgroepen, beroepsgroepen, beleid — volledige onderzoeksinterface |
| PYROX Participants | `app_athletes.py` | hardlopers en wandelaars, evenementenorganisatie — volledige methodologie zichtbaar |
| PYROX Beleid | `app_beleid.py` | beleidsmakers/organisatoren die alleen het eindresultaat voor één specifieke run nodig hebben — sterk vereenvoudigd, PROVISIONAL-kanttekeningen en ruwe HESTIA-cijfers bewust weggelaten |

`app_beleid.py` deelt dezelfde zijbalk en tempo/sessie-invoer als
`app_athletes.py`, maar toont in het hoofdscherm alleen: weersomstandigheden,
tijd per WBGT-vlagcategorie, het EHS-hoofdgetal (dosis-responsmodel), de
T_rect/CO_reserve-scatter en de piekverdelingen. Wat bewust ontbreekt (ruwe/
ongekalibreerde HESTIA-cijfers, PROVISIONAL-kalibratiewaarschuwingen,
meerdaagse PYROX-context, GPX-parcoursanalyse, het evidence-paneel) staat in
de docstring bovenin het bestand.

---

## 2. Welk bestand doet wat

### Startbestanden (hier pas je de pagina's aan)

| Bestand | Rol |
|---|---|
| `app.py` | De algemene app: layout, zijbalk, alle schermonderdelen |
| `app_athletes.py` | De deelnemersapp: niveaus, tempo, wedstrijdvlaggen |
| `app_beleid.py` | De beleidsapp: subset van `app_athletes.py`'s invoer, sterk vereenvoudigde uitvoer |

### Applicatiemodules (gedeeld door `app.py` / `app_athletes.py` / `app_beleid.py`)

| Bestand | Rol |
|---|---|
| `pyrox_bridge.py` | Draait het PYROX-model; tempo → MET (ACSM); duurweging |
| `decision_support.py` | Uurlijkse vlaggen (ISO 7243 én atletiek), WBGT↔UTCI-kruiscontrole |
| `loop_view.py` | Regellus: reserve, dagbalans, divergentie index vs. lustoestand |

`app_persoonlijk.py` deelt geen van deze drie — die app heeft zijn eigen
module­set (`individual_engine.py`, `individual_report.py`,
`local_storage.py`, `uncertainty.py`), los van bovenstaande tabel. Wel
gedeeld met `app_beleid.py`: de kernmotor (`hestia_model.py`,
`HESTIA_CVR_Module_v2.py`, `hestia_bridge.py`) — zie `README.md`'s
bestandenlijst voor het volledige overzicht.
| `plain_view.py` | Accu-kaarten en tijdlijn voor niet-ingewijden |
| `evidence.py` | Onderbouwing per claim, inclusief wat *niet* is aangetoond |
| `gpx_route.py` | GPX inlezen, tempo/blootstelling langs de route, kaartje |
| `terrain_lookup.py` | ESA WorldCover terreinclassificatie (optioneel) |
| `hestia_bridge.py` | HESTIA-koppeling: snelle schatting + volledige Monte Carlo, gecacht |
| `hestia_model.py` | **HESTIA individuele-tier model** (JOS-3, CVR, EHS-uitkomsten) |
| `HESTIA_CVR_Module_v2.py` | Cardiovasculaire reserve-module (Lloyd et al. 2022) |
| `HESTIA_CVR_Console.py` | Ondersteunend bestand voor de CVR-module |
| `HESTIA_ControlFailure_Module.py` | Thermoregulatoire regelfalen-metriek (experimenteel) |
| `experimental_risk.py` | Experimentele sectie: collapse risk, EHS-indicatoren, HESTIA-weergave |

### Modelbestanden — **NIET hier bewerken**

| Bestand | Rol |
|---|---|
| `pyrox_model.py` | De PYROX-modelkern |
| `pyrox_groups.py` | De gepubliceerde 23 groepen |
| `pyrox_revised_calibration.py` | Herziene kalibratie + MET-term, met afleiding |
| `Thermopoulos_Data_Engine.py` | Weerdata + thermische indices |
| `thermopoulos_loader.py` | Leest de Excel-uitvoer in voor PYROX |

Deze acht (de vijf hierboven plus `hestia_model.py`, `HESTIA_CVR_Module_v2.py`, `HESTIA_CVR_Console.py` en `HESTIA_ControlFailure_Module.py`) zijn afgeleid van de HESTIA-PYROX-suite. `hestia_model.py` bevat twee kleine, gedocumenteerde afwijkingen van de suite-versie (defensieve `timezonefinder`-import, gecachete `get_air_quality`) — zie de docstrings erin. Pas inhoudelijke wijzigingen aan **in de suite** en draag alleen deze twee fixes handmatig opnieuw over als je de suite-versie kopieert. Doe je het andersom, dan lopen je onderzoek en je app uit elkaar zonder dat iemand het merkt.

### Overig

| Bestand | Rol |
|---|---|
| `requirements.txt` | Python-pakketten |
| `test_revised_calibration.py` | Acceptatietests T1–T8 |
| `README.md` | Wetenschappelijke reikwijdte en validatiestatus |
| `DEPLOY.md` | Korte versie van deze handleiding |

---

## 3. Bestanden naar GitHub zetten

### De regel die je nooit moet vergeten

**Sleep bestanden, plak nooit inhoud.**

Bij het plakken van een lang bestand in de GitHub-editor kan de browser een
regel afbreken. Dat gebeurde met `app.py`: de laatste regel werd
`st.info("... to get start` / `ed.")` en de app startte niet meer met een
`SyntaxError` op regel 1167. Bij slepen gaat het bestand exact over zoals het is.

### Uploaden, stap voor stap

1. Pak de zip lokaal uit in een **verse map** — niet je Downloads-map. Daar
   staan al versies met `(1)` en `(2)` in de naam, en die verwarring heeft
   ons eerder een halve middag gekost.
2. Ga in de map `PYROX` staan. Je hebt de **losse bestanden** nodig, niet
   de map zelf.
3. Op GitHub: **Add file → Upload files**.
4. Selecteer alle bestanden (Ctrl+A) en sleep ze in het uploadvak.
5. Schrijf een commit-omschrijving en klik **Commit changes**.

### Controle achteraf

Kijk op de repo-startpagina of je ziet:

- Precies de bestanden uit de zip, in de **root** — niet in een submap
- Geen namen met haakjes erin (`app (1).py`)
- Geen map `PYROX/` binnen de repo

Staat er `PYROX/app.py` in plaats van `app.py`, dan heb je de map gesleept
in plaats van de inhoud. Verwijder alles en doe het opnieuw.

---

## 4. Streamlit: de vier apps

### ⚠️ EERST: kies Python 3.12

Dit is de belangrijkste instelling van het hele project, en de enige die je
**niet achteraf kunt wijzigen**.

`pythermalcomfort` eist `numpy<2.3`, en voor die numpy-versies bestaat geen
kant-en-klare wheel voor Python 3.14. Pip moet numpy dan vanuit broncode
compileren — dat duurt tien minuten of meer, en Streamlit herstart de machine
voordat het klaar is. Je ziet dan eindeloos "Your app is in the oven" en een
log die stopt na "Resolved N packages".

Op **Python 3.12** bestaan voor alles wheels en installeert het in enkele
minuten.

Bij het aanmaken van een app: klik op **Advanced settings** en zet
"Python version" op **3.12**. Een `runtime.txt` in de repo werkt hier NIET —
Community Cloud negeert die.

Heb je een app al gedeployed op de verkeerde versie, dan moet je hem
**verwijderen en opnieuw aanmaken**. De Python-versie is achteraf niet
aanpasbaar. Je subdomein komt direct weer vrij, dus je kunt dezelfde URL
opnieuw kiezen.



### De eerste app (bestaat al)

Repository: je PYROX-repo · Branch: `main` · **Main file path: `app.py`**
· Advanced settings → **Python 3.12**

### De tweede app aanmaken

1. share.streamlit.io → **Create app**
2. Repository: **dezelfde repo**
3. Branch: `main`
4. **Main file path: `app_athletes.py`** ← het enige verschil
5. **Advanced settings → Python version: 3.12**
6. Kies een herkenbare URL, bijvoorbeeld `pyrox-events`

### De derde app aanmaken (beleidsweergave)

Zelfde procedure, met **Main file path: `app_beleid.py`**. Ook deze
deployment wijst naar dezelfde repo — één set modules, vier front-ends, dus
een fix in bijvoorbeeld `hestia_bridge.py` bereikt zowel deze als de vierde
app tegelijk. Kies een URL die het onderscheid met de andere apps duidelijk
maakt, bijvoorbeeld `pyrox-beleid`.

### De vierde app aanmaken (persoonlijke weergave)

Zelfde procedure, met **Main file path: `app_persoonlijk.py`**. Deze app
draait op dezelfde HESTIA-motor als `app_beleid.py` (`individual_engine.py`
roept `hestia_model.py`/`HESTIA_CVR_Module_v2.py` rechtstreeks aan), dus een
fix in die motor bereikt beide automatisch — maar de app-laag zelf
(`individual_engine.py`, `individual_report.py`, `local_storage.py`,
`app_persoonlijk.py`) is uniek voor deze deployment en moet net als de
andere apps in zijn geheel worden meegeüpload.

**Privacy-overweging bij het kiezen van een URL:** deel deze URL niet
achteloos. De garantie "blijft op de eigen machine" geldt alleen voor wie
het proces zelf draait — bij een gedeelde Streamlit Cloud-link is dat deze
deployment, niet de bezoeker. Zie `GEBRUIKSAANWIJZING.md` §3.9 en
`README.md`'s privacy-architectuur-paragraaf voor de volledige uitleg
voordat je deze URL doorstuurt.

### Na elke upload

Streamlit herstart meestal vanzelf bij een nieuwe commit. Zo niet:
**Manage app → Reboot app**. Dat wist ook de cache.

---

## 5. Controleren of de juiste versie draait

Dit is de belangrijkste gewoonte uit deze hele handleiding. We hebben uren
verloren aan een bug die allang gerepareerd was, omdat één bestand niet was
meegekomen bij het uploaden.

Onderin de zijbalk staat:

```
Build 2026-08-12a (...)   ← app.py / app_athletes.py
Build 2026-08-17a (...)   ← app_beleid.py / app_persoonlijk.py
```

De vier apps hebben elk hun **eigen** `APP_BUILD`-stempel — dat is normaal,
zolang elke stempel maar hoort bij de laatste wijziging in dát bestand. Het
gaat mis als een stempel *lager* is dan je verwacht op basis van een recente
wijziging: dan is dat specifieke bestand niet meegekomen bij het uploaden.

**Zie je die regel niet**, dan draait de app op oude code — punt uit, geen
verdere discussie nodig.

**Zie je een rode melding** zoals:

> ⚠️ Out-of-date file(s): **gpx_route.py**. These were not updated with the
> rest of the app, so results from them may be wrong.

...dan is precies dát bestand niet meegekomen. Upload alleen dat bestand
opnieuw en reboot. De app controleert alle zeven modules zelf, dus je hoeft
nooit meer uit een foutmelding af te leiden welk bestand achterloopt.

---

## 6. Als er iets misgaat

### De app toont "Oh no. Error running app."

Er is geen traceback, dus de app crashte vóór het renderen. Ga naar
**Manage app** en lees de log. Meestal is het de installatie van pakketten.

### HESTIA — geheugengebruik, een reëel risico

HESTIA importeert matplotlib/seaborn/scipy bovenop wat de app al gebruikt.
Gemeten: **384 MB** in één proces, vóór er ook maar één simulatie draait.
Bij de volledige-precisie-run (n=5000) groeit dat verder doordat elke
worker tijdens het rekenen eigen geheugen opbouwt.

De worker-pool staat daarom bewust laag ingesteld (`MAX_WORKERS = 2` in
`hestia_bridge.py`) — niet op het aantal CPU-cores, maar met geheugen als
grens. Streamlit Cloud's gratis laag heeft doorgaans rond de 1 GB RAM
(niet geverifieerd voor deze specifieke deployment).

**Een out-of-memory-crash op Streamlit Cloud ziet er identiek uit aan de
gewone "Oh no"-foutpagina**, zonder traceback — makkelijk te verwarren
met een codefout. Zie je die melding specifiek bij het klikken op "Run
full precision", verhoog dan `MAX_WORKERS` niet zomaar, maar verlaag eerst
`QUICK_N` of de standaard n=5000 voor de volledige run.

### rasterio (terreinclassificatie) — status

Sinds de app op Python 3.12 draait, staat `rasterio` weer actief in
`requirements.txt`. Op 3.12 bestaat een kant-en-klare wheel (~38 MB, GDAL
zit erin), dus dit installeert in enkele seconden — geen compilatie meer
nodig, in tegenstelling tot de eerdere situatie op Python 3.14.

Wordt de app ooit teruggezet naar een Python-versie zonder wheel voor
rasterio, dan valt de app niet om: `terrain_lookup.py` detecteert de
afwezigheid zelf (`RASTERIO_AVAILABLE`) en schakelt alleen het
terreinvinkje uit, met een duidelijke melding in de app.

### De app blijft hangen op "Your app is in the oven"

De log stopt na "Resolved N packages" en er komt niets meer bij. Dat betekent
dat pip een pakket vanuit **broncode probeert te compileren** omdat er geen
kant-en-klare wheel is voor de Python-versie die Streamlit gebruikt. Dat kan
eindeloos duren.

Zo spoor je de dader op: kijk op `pypi.org/pypi/<pakketnaam>/json` welke
`cp`-tags de wheels hebben. Staat `cp314` er niet bij terwijl Streamlit op
Python 3.14 draait, dan is dat het pakket.

Dit gebeurde met **`timezonefinder`** (alleen een cp311-wheel). Dat pakket is
daarom uit `requirements.txt` gehaald: het werd in
`Thermopoulos_Data_Engine.py` wel geïmporteerd maar nooit gebruikt — de
tijdzone komt uit de geocoding-API. De import is nu defensief, dus de afwezigheid
is onschadelijk. **Let op:** `hestia_model.py` in de suite gebruikt het wél
echt, dus houd het lokaal geïnstalleerd als je de HESTIA-tier draait.

### De log stopt na "Resolved N packages" (overige gevallen)

De installatie loopt vast of duurt te lang, en Streamlit herstart de machine
(je ziet dan bovenin een nieuwe "Provisioning machine" met een latere tijd).
Twee bekende oorzaken:

- **Een pakket kan niet bouwen.** Dit gebeurde met `pythermalcomfort`: de
  resolver koos versie 3.8.0, die `numba==0.53.1` vastpint, die weer
  `llvmlite==0.36.0` nodig heeft, en dat weigert te bouwen op Python 3.14.
  Daarom staat er nu `pythermalcomfort>=4.4` in `requirements.txt`, met de
  reden erbij. **Verwijder die ondergrens niet.**
- **Te veel apps tegelijk.** De gratis tier deelt resources. Verwijder oude,
  ongebruikte apps via Manage app → Delete app.

### Foutmelding met `KeyError`, `ModuleNotFoundError` of vlakke grafieken

Kijk eerst naar de build-regel in de zijbalk (zie §5). In vrijwel alle
gevallen die we hebben gehad, was het een verouderd of ontbrekend bestand,
niet een echte fout in de code.

### "Open-Meteo rate limit reached (HTTP 429)"

Het gratis quotum is op: 10.000 aanroepen per dag, 5.000 per uur, 600 per
minuut — **geteld per IP-adres**, dus je apps delen dat quotum. Wacht een
paar minuten. De cachetijden staan al ruim ingesteld (geocoding 30 dagen,
forecast 2 uur, historisch 7 dagen), dus een herhaalde run op dezelfde
locatie kost niets.

De klimatologie-optie is veruit de duurste: die doet één aanroep per
historisch jaar. Laat die uit tijdens het testen.

---

## 7. Iets wijzigen

### Kleine tekstwijziging

Voor een losse tekstaanpassing mag je de GitHub-editor gebruiken (potlood-
icoon). Let op de laatste regel van het bestand: die moet compleet blijven.

### Codewijziging

1. Pas het bestand lokaal aan (bijvoorbeeld in Spyder).
2. **Verhoog de buildstempel**: in `app.py` en `app_athletes.py` de
   `APP_BUILD`, en in het gewijzigde bestand de `__BUILD__`. Beide moeten
   dezelfde datumcode krijgen, anders slaat de stale-detectie ten onrechte
   alarm — of, erger, niet.
3. Upload het bestand door het te slepen.
4. Reboot en controleer de build-regel.

### Na een wijziging in de kalibratie

Draai altijd:

```
python test_revised_calibration.py
```

Verwacht: `All acceptance tests passed.` Slaagt een test niet, dan raakt de
wijziging iets fundamentelers dan bedoeld.

---

## 8. Wat je moet weten voordat je deelt

De app is een **screeningsinstrument**, geen gevalideerde medische
voorspelling. Dat staat er ook zo in, en dat moet zo blijven.

Drie dingen die je bij het delen paraat moet hebben:

1. **De populatie-tier van PYROX heeft geen event-validatie.** De r=0,866
   correlatie, de Falmouth-hindcasts en IRONMAN Hoorn horen bij HESTIA's
   *individuele* tier — een ander model, dat niet in deze app draait.
2. **De meeste groepen gebruiken geëxtrapoleerde parameters.** Uitzonderingen
   met gepubliceerde waarden: volwassenen 18-45, ouderen 65-85, kwetsbare
   ouderen 85+.
3. **De regellus-framing is jouw hypothese**, onder review bij het
   International Journal of Biometeorology.

Het paneel "📚 Evidence base" onderin beide apps zet dit al netjes op een rij,
inclusief wat *niet* is aangetoond. Verwijs daar gerust naar in gesprekken —
het is sterker om de beperkingen zelf te benoemen dan ze te laten vinden.

---

## 9. Snelle checklist

Bij elke nieuwe upload:

- [ ] Zip uitgepakt in een verse map
- [ ] Bestanden gesleept, niet geplakt
- [ ] Alles in de root, geen submap, geen namen met haakjes
- [ ] Streamlit gereboot
- [ ] App draait op Python 3.12 (zie de eerste logregels)
- [ ] Build-regel zichtbaar in de zijbalk
- [ ] Geen rode "out-of-date file"-melding
- [ ] Eén stad getest: grafieken vullen zich, geen foutmelding

Bij een codewijziging bovendien:

- [ ] Buildstempels opgehoogd in gewijzigde bestanden én in elke app die
      het bestand gebruikt (zie `README.md`'s bestandenlijst welke apps
      dat zijn — niet alle vier delen alles)
- [ ] `test_revised_calibration.py` geslaagd

---

## Onzekerheid rond de EHS-schatting (toegevoegd 2026-08-14)

Naast het puntgetal toont de app en het Word-rapport nu een interval, bv.
`≈33,5 per 1000 — 95% sampling + anker interval 25,5–41,7 per 1000`.

**Wat het interval dekt**

1. **Monte-Carlo-ruis.** De N gesimuleerde deelnemers zijn een eindige
   trekking. Bootstrap-hersteekproef, aannamevrij.
2. **Ankeronzekerheid van de floor.** De dose=0-floor komt uit de
   gepubliceerde Falmouth-regressie (DeMartini et al. 2014, n=12
   wedstrijdjaren, R²=0,653). Die fit heeft een eigen band, die breder
   wordt naarmate je verder van het zwaartepunt (24,5 °C) af zit.

**Wat het NIET dekt — en dit is de grotere fout**

De helling van de dose-responscurve zelf. `_DOSE_RESPONSE_A/B` is gefit
tegen vijf referentiescenario's waarin dosis en temperatuur verward zijn
(dosis wordt alleen aan de warme kant positief, omdat MET vastgehouden
werd). Met één effectieve ijkconditie is de helling statistisch niet
geïdentificeerd: er bestaat geen steekproefmodel waaronder een
dekkingskans voor die parameter te definiëren valt.

Zodra een noemenswaardig deel van de deelnemers dosis>0 heeft, dragen
juist die deelnemers vrijwel alle kansmassa, en hun kans komt volledig
uit die niet-geïdentificeerde curve. **Het interval is daarom een
ondergrens op de totale onzekerheid, geen betrouwbaarheidsinterval.**
Noem het in rapportage nooit "95%-BI".

Een smal interval rond een verkeerd getal is misleidender dan geen
interval. Daarom staat de disclaimer altijd bovenaan bij de caveats,
ook als het er statistisch gezond uitziet.

**Diagnostiek die het interval meelevert**

- `n_nonzero` — aantal deelnemers met dosis>0
- `top_participant_share` — aandeel van de schatting bij één individu.
  Bij Leiden 10-05-2026 was dit 84%: het puntgetal 1,2 per 1000 zat op
  het rekenkundig maximum van één verzadigde simulant plus de floor.
- `floor_share` — deel van de schatting dat uit de temperatuur-floor
  komt in plaats van uit gesimuleerde dosis
- `extrapolation_degrees` — hoeveel °C buiten Falmouths fitbereik
  (21,3–27,7 °C) deze dag ligt

**Testen**

    python3 test_uncertainty.py

**Aanpassen**

De reconstructie van de Falmouth-spreiding gebruikt één aanname: de
spreiding van de twaalf wedstrijdtemperaturen, afgeleid uit het
gerapporteerde bereik. Die staat geïsoleerd in `_FALM_T_BAR` en
`_FALM_T_SD` bovenaan `uncertainty.py` en kan vervangen worden zodra
Tabel 1 uit het artikel gedigitaliseerd is.

---

## Persoonlijke assessment-pagina (toegevoegd 2026-08-15)

`app_persoonlijk.py` + `individual_engine.py` + `local_storage.py` vormen
samen een derde weergave naast de deelnemers- en beleidsapp: één echte
persoon, eigen gegevens, één specifiek evenement.

**Privacyarchitectuur.** De enige uitgaande aanroepen zijn geocoding
(plaatsnaam \u2192 lat/lon/tijdzone) en weerdata (lat/lon/datum \u2192 weer) \u2014
dezelfde twee die de bestaande apps al gebruiken. Persoonlijke gegevens
en uitkomsten worden alleen weggeschreven naar lokale JSON-bestanden
onder `%APPDATA%\PYROX` (Windows) / `~/Library/Application
Support/PYROX` (macOS) / `~/.local/share/PYROX` (Linux), via
`local_storage.py`. Dat bestand bevat geen netwerkcode.

**Start de pagina** met:

    streamlit run app_persoonlijk.py

Draai eerst `python3 test_uncertainty.py` en test `individual_engine.
fetch_scenario_weather()` handmatig tegen een echte locatie voordat je
vertrouwt op de weeraanroep \u2014 dat pad is in de ontwikkelomgeving niet
end-to-end getest (geen netwerktoegang tot Open-Meteo vanuit die
sandbox), alleen de fysiologie/ensemble/opslag eromheen.

---

## Twee kernfouten gevonden en gerepareerd (2026-08-16)

### 1. CO_reserve werd NaN na uitputting (hestia_model.py)

**Oorzaak.** In `calculate_indices_jos3_adult()` wordt een deelnemer op
`stopped=True` gezet zodra RPE>=19,5. Vanaf dat moment wordt T_rectaal
doorgekopieerd (`{**results[-1], ...}`), maar
`jos3_cvr_series.append(...)` — nodig voor de latere CO_reserve — zat in
de tak die de bevroren iteraties juist overslaan (`continue`). De
post-loop `link_cvr_to_jos3()` kreeg dus een kortere reeks dan de race,
en elke tijdstap na uitputting hield CO_reserve = NaN, terwijl T_rectaal
een geldige bevroren waarde had.

**Impact, empirisch gemeten via A/B (pre-fix vs post-fix codebase, met
globale seeding zodat de vergelijking geldig is):**
- Mild scenario (Utrecht 31-05, 200 runs): conjunctie 0% -> 0%, dosis
  0 -> 0. **Geen verschil.** De twee deelnemers die bevroren boven
  40,5 °C hadden een herstelde CO_reserve van +1,00 en +1,04 — positief,
  dus geen conjunctie. De fout was daar dus latent, niet actief.
- Extreem scenario (35 °C, 400 min, 80 runs): 47 bevroren, waarvan 42
  ín het gevarenkwadrant. Gemiddelde dosis **45,50 -> 137,11 (3x)**.
  42 deelnemers kregen een hogere dosis, **0 een lagere**.

De impact schaalt dus met de ernst van het scenario. Bij milde
omstandigheden verandert er niets; bij ernstige omstandigheden — precies
waar het ertoe doet — werd de belasting fors onderschat. De fout kan
alleen tot **onderschatting** leiden, nooit tot overschatting.

**Correctheid geverifieerd via A/B op identieke invoer:**
- Nooit-bevroren deelnemers: bit-identiek voor/na (49/49).
- Bevroren deelnemers: bit-identiek tot en met de bevriezingsstap.
- Na bevriezing: pre = NaN, post = de bevroren waarde, constant.
- `CVRModel.compute_step()` is aantoonbaar puur (stateless), dus een
  herhaald snapshot geeft een echte bevriezing, geen wegdrijving.

### 2. Persoonlijke app was niet reproduceerbaar (individual_engine.py)

`calculate_indices_jos3_adult()` trekt het drinkvolume per slok uit de
**globale** `np.random` (`np.random.uniform(120, 180)`). Dat is de enige
ongezaaide willekeur in de motor. `run_individual_assessment()` zaaide
alleen zijn eigen `default_rng` voor de profielen, waardoor twee runs met
dezelfde invoer én dezelfde seed verschillende uitkomsten gaven —
gemeten: de dosis veranderde bij **49 van 60 deelnemers**. Een gebruiker
die zijn rapport twee keer downloadt kreeg dus twee verschillende
antwoorden zonder te weten welk klopt.

`generate_base_population()` zaaide de globale RNG al wel voor de
populatie-apps; de persoonlijke route doet dat nu ook.

**Tests:** `test_cvr_freeze_fix.py` (3/3) en
`test_individual_engine.py::test_reproducibility_same_seed`, plus de
volledige bestaande suite blijft groen (7/7, 6/6, 3/3, en
`test_revised_calibration.py`).

---

## Drie endpoints in plaats van één (2026-08-17)

Na toetsing tegen de literatuur zijn de criteria opgesplitst en hernoemd.
Het oude "collaps"-label was onjuist: in de sportgeneeskunde betekent
collaps (EAC) iets anders dan wat er gemodelleerd werd.

| | criterium | venster | anker |
|---|---|---|---|
| **EHS** | T_rect ≥ 40,5 °C én CO_reserve ≤ 0 | race + post-finish | Breslow 2021 (Boston) |
| **EHE** | T_rect > 39,5 °C én CO_reserve < 0 | alleen tijdens inspanning | geen |
| **EAC** | CO_reserve < 0 (géén temperatuureis) | alleen post-finish | 1,53/1000 (Göteborg) — nog niet gefit |

**EHS** — klinisch: CNS-disfunctie plus kerntemperatuur >40,5 °C.
Het model kan geen neurologische status simuleren en vervangt het
CNS-criterium door cardiovasculaire decompensatie. Die substitutie is
conservatief: cerebrale hypoperfusie is gemeten bij 40 °C kerntemperatuur
met intacte cardiac output (Nybo & Nielsen 2001), dus CNS-disfunctie kan
optreden vóórdat CO_reserve nul bereikt. Systematische onderdetectie
wordt opgevangen door de intercept-kalibratie.

**EHE** — exertional heat exhaustion. Empirisch getoetst tegen de eigen
modeluitvoer: de toestand gaat *niet* over in 40,5 °C. Van 40 gewaarschuwde
lopers bij 31 °C bereikte er één alsnog die drempel, en die zat er al
boven. T_rect bereikt een echt thermisch evenwicht terwijl CO_reserve
blijft dalen door dehydratie — bij vrijwel onveranderde MET (11,04 → 11,00
over vijf stappen), dus pacing is níet de stabilisator. Het criterium
markeert daarom **verloren regelmarge**, geen aanstaande hittebevanging.
De dosis draagt dat signaal; de ja/nee-vlag niet.

**EAC** — exercise-associated collapse. Posturale hypotensie na de finish
wanneer de spierpomp wegvalt. Cardiovasculair, niet thermisch: de
temperatuurdrempel ontbreekt bewust. Dit is het enige criterium met een
extern anker en daarmee de eerste kandidaat sinds Falmouth voor een
absolute-incidentiekalibratie.

Tests: `test_individual_engine.py::test_ehe_eac_criteria` en
`::test_eac_window_scoping` (9/9 groen).

---

## CO_reserve tekenomkering bij extreme hittebelasting (2026-08-17)

**Gevonden bij onderzoek naar waarom de conjunctieve criteria zelden vuren.**

CO_reserve = (CO_max_heat − CO_rest_heat) × (1 − f). Hittebelasting duwt
CO_max omlaag (−8,3%/CHSI) en CO_rest omhoog (+31,3%/CHSI), dus voorbij
een bepaalde CHSI kruisen die twee en wordt de eerste factor negatief. In
datzelfde bereik is f afgekapt boven 1,0 (op 1,15), dus (1 − f) is óók
negatief — en twee negatieven vermenigvuldigd geven een **positieve**
reserve. Precies in de toestand waarin de loper zelfs de rustbehoefte niet
meer kan leveren, rapporteerde het model dus een gezonde reserve, waardoor
elk criterium dat CO_reserve < 0 vereist stilzwijgend stopte met vuren.

Gemeten vóór de fix (66 jaar, 94 kg, MET 7,5):

| CHSI | 5 | 6 | 7 | 8 |
|---|---|---|---|---|
| CO_reserve | +0,08 | **−0,08** | **+0,16** | **+0,49** |

Na de fix: −0,08 → −1,04 → −3,27 → −7,73, monotoon dalend.

**Fix:** `co_demand` wordt afgekapt op `co_rest_heat` — de metabole vraag
kan niet onder de rustbehoefte zakken. Dit verandert niets zolang
CO_max_heat > CO_rest_heat, dus over het hele fysiologisch normale bereik;
de coëfficiënten van Lloyd et al. (2022) blijven onaangeroerd. Het
verwijdert alleen een artefact van het lineair doorextrapoleren voorbij
het punt waar de twee lijnen elkaar kruisen.

**Wat NIET het probleem bleek.** Twee hypothesen zijn onderzocht en
verworpen: (a) onbeperkt drinken — de gesimuleerde netto dehydratie is
3,16% (spreiding 1,75–4,25%) bij een marathon van 3,5 uur op 30 °C,
precies binnen de 2–4% uit de literatuur; (b) de dehydratie-fix van
9 augustus 2026 — die corrigeerde een echte fout (CVR kreeg een
nooit-verminderde accumulator gevoed, alsof de loper nooit dronk) en de
uitkomst is aantoonbaar realistisch.

Test: `test_cvr_freeze_fix.py::test_co_reserve_monotone_in_heat_strain`.

---

## Beleidsapp: drie criteria per 1000 (2026-08-17)

`app_beleid.py` en het beleids-Word-rapport tonen nu alle drie de
endpoints als aantal per 1000, met definities.

**Waarom per 1000 hier wél mag en in de persoonlijke app niet.** In de
beleidsapp is het ensemble een *gesimuleerde populatie* (uit
`generate_base_population`), dus fractie x 1000 is een echte incidentie
per 1000 deelnemers. In `app_persoonlijk.py` is het ensemble één persoon
herhaald onder verschillende dag-aannames; daar zou dezelfde omrekening
betekenisloos zijn en blijft het een percentage van je eigen runs.

**Twee soorten "per 1000" op dezelfde pagina.** De EHS-schatting bovenaan
komt uit een dosis-responsmodel dat tegen waargenomen Falmouth-incidentie
is gekalibreerd. De drie criteriumtellingen eronder zijn ongekalibreerd:
hoeveel gesimuleerde lopers per 1000 het criterium haalden, zonder fit
tegen enige waarneming. Onderling en tussen scenario's vergelijkbaar,
maar niet te lezen als verwachte aantallen. Dit staat expliciet in zowel
het scherm (uitklapbaar blok) als het rapport.

Implementatie: `hestia_bridge.py` berekent `pct_true_ehe_criterion` en
`pct_true_eac_criterion` naast de bestaande `pct_true_ehs_criterion`,
via dezelfde `conjunctive_hit()`/`eac_hit()` uit `individual_engine.py`
(lazy import wegens circulaire afhankelijkheid) — één implementatie
gedeeld door de populatie- en persoonlijke route, geen tweede kopie.

---

## EAC: drempel op de dosis, en terug naar percentages (2026-08-17)

**Waarom de EAC-getallen te hoog waren.** Het criterium telde elke
nuldoorgang van CO_reserve in het post-finish-venster. Gemeten op een
zwaar scenario (30 °C, 3 uur, 5:00/km): 40% van de populatie had minstens
één negatieve stap — maar de hélft daarvan had er precies één van 30
seconden, waarna herstel volgde. `simulate_post_finish()` documenteert die
korte dip zelf als gevalideerde, normale fysiologie bij het stoppen. Wie
werkelijk in elkaar zakt, ligt daar minuten.

`EAC_DOSE_THRESHOLD = 0.5` vereist nu een opgebouwd tekort. De empirische
verdeling heeft daar een duidelijke knik: 40% bij drempel 0, 15% bij 0,5,
en daarna vlak (15% bij 1,0, 12,5% bij 2,0). De dosis weegt zowel diepte
als duur, dus één diepe dip telt ook mee. Voor EHE is géén drempel
toegevoegd: daar is één tijdstap 10 minuten, dus per definitie geen
transiënt.

**Presentatie in de beleidsapp aangepast.** EHS blijft per 1000 — dat is
het enige gekalibreerde getal (dosis-respons tegen Falmouth). EHE en EAC
staan nu als **percentage van gesimuleerde deelnemers**, niet per 1000.
Reden: een criteriumtelling ligt per definitie ordes van grootte boven de
klinische incidentie, omdat het voldoen aan een mechanistische voorwaarde
niet hetzelfde is als het syndroom (echte EAC vereist daarnaast cerebrale
hypoperfusie, een rechtopstaande houding en een moment). "EAC 450 per
1000" naast een waargenomen 1,53 per 1000 nodigt uit tot de conclusie dat
het model onzin is; een percentage voorkomt die valse vergelijkbaarheid.

**Openstaand werk:** EAC kalibreren tegen het Göteborg-anker (1,53 per
1000), zoals EHS tegen Falmouth is gekalibreerd. Dat is het enige
endpoint waarvoor die data bestaat, en daarna mag het wél per 1000.

Test: `test_individual_engine.py::test_eac_requires_sustained_deficit`.

---

## Fase 1: steekproefprecisie zichtbaar gemaakt (2026-08-19)

**Het gemeten probleem.** Dezelfde scenario-opzet, dezelfde ensemblegrootte
(n=100), alleen een andere seed, vijf keer gedraaid:

| seed | 11 | 22 | 33 | 44 | 55 |
|---|---|---|---|---|---|
| EHE-schatting | 1% | 5% | 4% | 4% | 1% |

Een vijfvoudig verschil, puur door toeval. Dit verklaart de sprongen
verspreid over de rapporten van dit project (een fractie die van 0% naar
45% gaat tussen naburige scenario's; de DtD-vrouwencurve die van 8% naar
4% knikt tussen 50 en 55 jaar). Niets in het gerapporteerde percentage
liet zien hoe onnauwkeurig het was.

**Wat is toegevoegd.** `uncertainty.fraction_interval()` geeft een exact
Clopper-Pearson-interval bij een criteriumtelling k/n, plus
`format_fraction_interval()` (die de RUWE TELLING toont, niet alleen het
percentage) en `fraction_caveats()` (die automatisch waarschuwt bij k=0,
k<5, of een bovengrens boven 3x de puntschatting).

Exact, niet normaal-benaderd: de normale benadering is juist onbetrouwbaar
bij kleine k en kleine p, en klapt bij k=0 dicht tot een interval van
nul breedte — wat zekerheid suggereert waar die niet is.

**Effect, op het DtD-scenario dat de aanleiding was:**
- was: `EHE 8%`
- nu: `EHE 8% (6 van 80; 95%-interval 3%-16%)`
- en bij een nulwaarde verschijnt nu automatisch: *"Geen enkele run haalde
  het EAC-criterium. Dat betekent niet dat de kans nul is: bij 80 runs is
  alles tot 5% verenigbaar met deze uitkomst."*

Doorgevoerd in `app_persoonlijk.py`, `app_beleid.py`, `individual_report.py`
en `report_generator.py`. De ruwe tellingen worden nu bewaard op
`IndividualAssessment` (`ehs_hits`/`ehe_hits`/`eac_hits`) en in de
populatieroute (`n_true_*_hits`, `n_simulations_used`).

**Bewust NIET toegevoegd: effectieve steekproefgrootte (ESS).** Bij
ongewogen Monte Carlo is ESS per definitie gelijk aan n en draagt geen
informatie. ESS wordt pas een diagnose zodra importance sampling bestaat
(fase 2), waar het gewichtsdegeneratie detecteert. Een kolom die altijd
"100/100" toont zou suggereren dat er iets gecontroleerd wordt.

**Wat dit NIET oplost.** Dit maakt de precisie van de schatting binnen het
eigen model zichtbaar. Het zegt niets over de dosis-responscurve, die op
vijf Falmouth-ijkpunten rust en waarvan de helling niet geïdentificeerd
is. Nauwkeuriger meten van een onzekere curve verplaatst dat probleem
niet.

**Onderzocht en vooralsnog niet doorgevoerd (fase 2/3):**
- *Naïeve importance sampling* verslechterde de zaak: schattingen 3,9 /
  3,0 / 6,1 / **13,4** / 3,5%, met ESS 8-19 van 100 — gewichtsdegeneratie.
- *Defensieve mengverdeling* (helft natuurlijk, helft verschoven, gewicht
  begrensd op 1/alpha=2) werkte wel: 2,6 / 2,2 / 3,1 / 2,0 / 4,0%,
  ESS ~69. Standaarddeviatie van 1,87% naar 0,79% — factor 2,4 minder
  ruis, equivalent aan ~6x minder simulaties voor dezelfde precisie.
- *GPD-staartfit* op 500 gepoolde runs reproduceerde de telling (3,02% /
  2,98% / 2,75% bij drie drempels tegen 3,00% geteld) maar met 51-99
  informatieve punten in plaats van 15.

Test: `test_uncertainty.py::test_fraction_interval` (7/7 groepen).
