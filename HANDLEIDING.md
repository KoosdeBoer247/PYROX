# PYROX — handleiding voor GitHub en Streamlit

Deze handleiding beschrijft hoe je dit project beheert zonder opnieuw in de
valkuilen te lopen die we onderweg zijn tegengekomen. Elke waarschuwing hierin
staat er omdat het één keer is misgegaan.

Versie van deze set: **build 2026-08-10b**
Laatst geverifieerd: alle modules compileren, alle acceptatietests slagen,
beide apps starten zonder fouten.

**Sinds 2026-08-06a, kort:** een verkeerd ingevulde kledingisolatiewaarde
(clo=0,5 -> 0,2) bleek de HESTIA-simulatie structureel te heet te laten
lopen; gecorrigeerd en gecheckt tegen Veltmeijer et al. 2014 en Falmouth/
DeMartini et al. 2014. Het HESTIA-hoofdgetal is sindsdien een dosis-
responsmodel (logistische curve op cumulatief T_rect/CO_reserve-tekort),
niet meer de temperatuur-alleen-Falmouth-schatting. Zie GEBRUIKSAANWIJZING.md
paragraaf 3.6 voor de volledige uitleg.

---

## 1. De opzet in één alinea

Eén GitHub-repository bevat alle bestanden. Streamlit draait daar **twee
apps** uit, die verschillen in één ding: welk bestand het startpunt is.
Alle modellen en rekenmodules worden gedeeld. Een correctie in bijvoorbeeld
`decision_support.py` werkt daardoor meteen in beide apps door. Dat is met
opzet zo: twee kopieën van dezelfde logica lopen na verloop van tijd altijd
uit elkaar, en niets waarschuwt je daarvoor.

| App | Startbestand | Voor wie |
|---|---|---|
| PYROX (algemeen) | `app.py` | bevolkingsgroepen, beroepsgroepen, beleid |
| PYROX Participants | `app_athletes.py` | hardlopers en wandelaars, evenementen |

---

## 2. Welk bestand doet wat

### Startbestanden (hier pas je de pagina's aan)

| Bestand | Rol |
|---|---|
| `app.py` | De algemene app: layout, zijbalk, alle schermonderdelen |
| `app_athletes.py` | De deelnemersapp: niveaus, tempo, wedstrijdvlaggen |

### Applicatiemodules (gedeeld door beide apps)

| Bestand | Rol |
|---|---|
| `pyrox_bridge.py` | Draait het PYROX-model; tempo → MET (ACSM); duurweging |
| `decision_support.py` | Uurlijkse vlaggen (ISO 7243 én atletiek), WBGT↔UTCI-kruiscontrole |
| `loop_view.py` | Regellus: reserve, dagbalans, divergentie index vs. lustoestand |
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

## 4. Streamlit: de twee apps

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
Build 2026-08-10b (...)
```

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

- [ ] Buildstempels opgehoogd in gewijzigde bestanden én in beide apps
- [ ] `test_revised_calibration.py` geslaagd
