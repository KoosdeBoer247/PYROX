# PYROX — gebruiksaanwijzing

Deze handleiding is voor mensen die de app **gebruiken**: organisatoren,
hulpverleners, coaches, deelnemers. Voor het beheren van de Streamlit/
GitHub-technische kant is er een aparte handleiding (`HANDLEIDING.md`).

PYROX bestaat uit **vijf apps**, en dit document behandelt ze alle vijf:

| App | Voor wie |
|---|---|
| **PYROX** (algemeen) | Beleid, beroepsgroepen, de brede bevolking |
| **PYROX Participants** | Hardlopers, wandelaars, evenementenorganisatie — volledige methodologie |
| **PYROX Beleid** | Beleidsmakers/organisatoren die snel het eindresultaat voor één specifieke run willen zien, zonder de onderzoeksmatige onderbouwing eromheen |
| **PYROX Persoonlijk** | Eén met naam genoemde deelnemer die zijn eigen assessment wil, volledig lokaal op zijn eigen apparaat (zie §3.9) |
| **PYROX Klimaatprojectie** | Evenementenorganisatoren die willen weten of een vaste jaarlijkse datum/locatie houdbaar blijft naarmate het klimaat opschuift (zie §3.10) |

De derde app, PYROX Beleid, is een sterk vereenvoudigde versie van PYROX
Participants: dezelfde locatie-, tempo- en sessie-invoer, maar alleen de
uitkomst die deze doelgroep nodig heeft — weersomstandigheden, tijd per
vlagcategorie, het EHS-hoofdgetal (§3.6), de T_rect/CO_reserve-scatter en
de piekverdelingen. De ruwe/ongekalibreerde cijfers, de PROVISIONAL-
kanttekeningen, de meerdaagse PYROX-context en het evidence-paneel staan
er bewust niet in — die audience heeft er niet minder recht op, maar wél
minder behoefte aan, en te veel methodologie op het verkeerde moment leidt
juist af van de beslissing die genomen moet worden. Wie de volledige
onderbouwing wil, gebruikt PYROX Participants.

De vierde app, PYROX Persoonlijk, draait dezelfde HESTIA-motor als PYROX
Beleid, maar dan voor precies één persoon in plaats van een gesimuleerde
populatie: eigen lengte, gewicht, leeftijd, tempo en gewoontes, in plaats
van een steekproef. Zie §3.9 voor de privacy-architectuur en het
belangrijke onderscheid tussen "op je eigen apparaat draaien" en "een
gedeelde link openen".

De vijfde app, PYROX Klimaatprojectie, beantwoordt een andere vraag dan de
andere vier: niet "hoe riskant is dit evenement dit jaar", maar "blijft
een vaste jaarlijkse datum/locatie verantwoord naarmate het klimaat
opschuift". Hij vergelijkt de referentieperiode 1996–2025 met door jou
gekozen toekomstige jaren, en toont per jaar zowel de verwachte EHE-uitkomst
als de kans dat een zelf ingestelde grens wordt overschreden. Zie §3.10
voor de volledige uitleg, inclusief de belangrijke kanttekening dat EHE
hier ongekalibreerd blijft.

**Sinds build 2026-08-14a** heeft PYROX Beleid ook een hindcast-modus: in
de zijbalk kun je "Weather source" op "Historical (hindcast)" zetten en
een datumbereik in het verleden kiezen. De app haalt dan waargenomen
historische data op (Open-Meteo-archief) in plaats van een voorspelling,
en draait verder exact dezelfde analyse — inclusief het Word-rapport en
het voorspellingsrecord, die in dat geval zelf duidelijk als "HINDCAST"
gelabeld worden. Dit is bedoeld om de modelvoorspelling tegen een al
bekende, echte gebeurtenis te leggen (bijvoorbeeld een eerder evenement
waarvan je de daadwerkelijke EHS-cijfers al hebt), niet om vooruit te
plannen.

Ook is er sinds build 2026-08-13f-2026-08-13c een deelnemersteller onder
het EHS-hoofdgetal ("👥 Estimate based on X of Y simulated participants
who ever reached a non-zero dose"), met een waarschuwing bij een klein
aantal en een aparte uitleg wanneer dat aantal 0 is (dan toont het cijfer
Falmouths eigen temperatuurgebonden achtergrondincidentie, niet iets dat
de simulatie zelf heeft gedetecteerd — zie de ℹ️-melding in de app zelf
voor de volledige uitleg). Daarnaast staat er een "Worth monitoring
(broad screen)"-kruiscontrole naast het hoofdgetal, en twee downloadknoppen
onderaan: een Word-rapport en een Excel-voorspellingsrecord met lege
`actual_*`-kolommen om na afloop van een evenement in te vullen.

Als dit je eerste keer is: lees eerst **§1 Snelstart**, en kom pas terug
naar de rest als je specifieke vragen hebt. Je hoeft niet alles te
begrijpen om de app zinnig te gebruiken.

---

## 1. Snelstart

**Stap 1.** Vul een plaatsnaam in.
**Stap 2.** Kies je niveaus (hardloop- en/of wandelgroepen) of blijf bij
de standaardgroepen in de algemene app.
**Stap 3.** Klik **Run analysis**.
**Stap 4.** Lees de kaarten onder **"How much reserve is left"** — een
groene accu betekent "in orde", rood betekent "alert".

Dat is voor de meeste vragen genoeg. De rest van dit document legt uit
wat er allemaal ónder die kaarten zit, en — belangrijker — **wat je moet
doen als twee delen van de app elkaar lijken tegen te spreken**, want dat
gebeurt, en dat is met opzet zo gebouwd.

---

## 2. Waarom voelt dit complex?

Omdat de app expres **meerdere, verschillende vragen apart beantwoordt**
in plaats van ze tot één simpel getal samen te persen. Dat is een bewuste
keuze: één samengevoegd "risicocijfer" zou makkelijker ogen, maar zou
verbergen dat een wedstrijddag-vraag ("is het nú te heet om te starten?")
en een trainingsblok-vraag ("bouwt deze groep over meerdere dagen
warmtebelasting op?") gewoon **niet hetzelfde antwoord hebben**.

Onthoud dit ene principe, en de rest van de app wordt logisch:

> **Elke indicator beantwoordt een eigen vraag, op een eigen tijdschaal.
> Als twee indicatoren het oneens lijken, is dat meestal geen fout — het
> zijn twee juiste antwoorden op twee verschillende vragen.**

---

## 3. De onderdelen, op volgorde van de app

### 3.1 Locatie & instellingen (zijbalk)
Stad, terreintype (beïnvloedt windprofiel), en — in de deelnemersapp —
je niveaus. Tempo's staan in het hoofdscherm, niet in de zijbalk (dat is
zo gebouwd omdat een lange lijst tempo-invoervelden op een tablet/iPad
lastig te bedienen bleek).

### 3.2 Race-day heat flags (WBGT-vlaggen)
**Vraag die dit beantwoordt: "Hoe heet is het NU, ter plekke?"**

Groen/geel/rood/zwart, gebaseerd op de WBGT-index — de industriestandaard
voor sportevenementen. Kijkt alleen naar het huidige uur, kent geen
geheiden van eerdere dagen. Een zwarte vlag met een dun zwart randje
betekent: WBGT zegt "veilig", maar UTCI (die ook straling meeweegt)
zegt "zware hittestress" — die twee zijn het dan oneens, en de rand
maakt dat zichtbaar.

**Gebruik dit voor:** starttijd- en tempobeslissingen, dezelfde dag.

### 3.3 Time in the heat, per group
Hoeveel tijd elk niveau daadwerkelijk in elke vlagcategorie doorbrengt,
gegeven hun eigen tempo. Een langzamere deelnemer kan nog op de weg zijn
als de vlag al naar rood is gesprongen, terwijl de winnaar allang binnen
is.

### 3.4 How much reserve is left
**Vraag die dit beantwoordt: "Hoe zwaar valt de warmtebelasting van de
afgelopen en komende dagen bij elkaar op, voor een gemiddeld iemand in
deze groep?"**

Dit is **PYROX**, het meerdaagse model. De accu-kaart toont de reserve op
de datum die je bij §3.3 hebt ingesteld — niet per se de slechtste dag
uit het hele venster.

**Belangrijke beperking, met opzet zo:** een wedstrijd van 1-2 uur wordt
door dit model bijna weggedeeld, omdat het rekent alsof iemand een hele
werkdag (8 uur) bezig is. **Voor de vraag "is deze race zelf gevaarlijk"
is dit dus niet het juiste onderdeel** — daarvoor is §3.6 (HESTIA) bedoeld.
Gebruik dit onderdeel voor **trainingsopbouw naar de wedstrijddag toe**,
niet voor de wedstrijd zelf.

### 3.5 EXPERIMENTAL — collapse risk & EHS indicators
Drie aparte, elk anders onderbouwde signalen:

- **Collapse risk** — hetzelfde PYROX-cijfer als §3.4, omgekeerd
  weergegeven. Zelfde beperking: meerdaags, niet racespecifiek.
- **Sports Medicine Australia / PHS** — een gepubliceerde,
  sportspecifieke risicoclassificatie (Laag/Gemiddeld/Hoog/Extreem), met
  concreet advies.
- **T_re-projectie** — voorspelde lichaamskerntemperatuur, **alleen
  getoond voor wandelaars van 60-100 jaar** (het onderliggende model is
  niet voor andere leeftijden gevalideerd — vandaar dat het bij jongere
  groepen bewust ontbreekt in plaats van een onbetrouwbaar getal te
  tonen).

### 3.6 HESTIA individual-tier Monte Carlo
**Vraag die dit beantwoordt: "Wat gebeurt er fysiologisch, minuut voor
minuut, tijdens en vlak na déze specifieke race?"**

Dit is het meest gedetailleerde onderdeel: een simulatie van honderden
virtuele deelnemers, met echte cardiovasculaire fysiologie.

**Het hoofdgetal: "EHS estimate (primary: dose-response model)".** Dit
komt uit een logistische curve over elke gesimuleerde deelnemer's
cumulatieve T_rect/CO_reserve-tekort (diepte × tijd in het gevarenkwadrant),
gefit tegen de gepubliceerde Falmouth Road Race-epidemiologie (DeMartini
et al. 2014). Dit cijfer reflecteert het **eigen tempo, duur en niveau**
van dit scenario — in tegenstelling tot de temperatuur-alleen-schatting
hieronder, die dat niet kan zien.

**Als vergelijking, direct eronder:** de epidemiologisch gekalibreerde
schatting (Falmouth, alleen op temperatuur gebaseerd) en het ruwe,
ongekalibreerde HESTIA-percentage. Beide zijn nuttig om te zien hoe de
verschillende methoden zich tot elkaar verhouden, maar het hoofdgetal is
leidend.

**Belangrijke correctie, 2026-08-10:** een verkeerd ingevulde kledingisolatiewaarde
(clo=0,5, alsof deelnemers lichte binnenkleding droegen) liet de ruwe
simulatie structureel te heet lopen — tot 93% van een gesimuleerde groep
boven de klinische EHS-drempel, tegen een handvol procent in
werkelijkheid (Veltmeijer et al. 2014, Zevenheuvelenloop). Gecorrigeerd
naar clo=0,2 (realistische hardloopkleding), gecheckt tegen zowel
Veltmeijer als Falmouth. De ruwe simulatie is sindsdien veel
geloofwaardiger, al blijft hij ongekalibreerd getoond.

**Kleinere correctie, 2026-08-09:** de cardiovasculaire reserve leek in een
eerdere versie ook bij mild, constant weer zonder hitte-escalatie
langzaam te eroderen. Oorzaak was een technische bug (een vochtverlies-
teller die het drinkgedrag van de gesimuleerde deelnemer niet meenam),
niet een probleem met het dehydratiemodel zelf. Gecorrigeerd; de
cardiovasculaire cijfers in dit onderdeel zijn sindsdien betrouwbaarder
bij lange, milde scenario's.

**De ruwe simulatiecijfers** staan nog steeds beschikbaar, in een
uitklapbare sectie "Raw physiological simulation (uncalibrated)":

| Metriek | Betekenis |
|---|---|
| Peak T_re, mean | Gemiddelde piek-lichaamskerntemperatuur |
| True EHS criterion met | % dat **tegelijkertijd** T_rect≥40,5°C ÉN cardiovasculaire reserve≤0 bereikt — ruwe, ongekalibreerde simulatie-uitkomst |
| Worth monitoring (broad screen) | Brede signaleringsvlag (uitdroging óf hoge inspanning óf hoge temperatuur) — bewust ruim, geen medisch incidentcijfer |
| Avg. cardiovascular capacity remaining | Hoeveel cardiovasculaire reserve een gemiddelde deelnemer overhoudt tijdens + 10 min na de finish |
| Reached zero/negative capacity | % dat op enig moment tijdens/vlak na de race op nul of negatieve capaciteit komt |

**Waarom de dosis vaak pas ná de finish begint te lopen.** De grafiek
"How risk builds over time" laat voor veel deelnemers een cumulatieve
dosis zien die tijdens de race op nul blijft en pas rond het eigen finish-
moment (de stippellijn) omhoogschiet. Dat is geen fout, maar het model dat
een goed gedocumenteerd klinisch patroon reproduceert: **30-40% van alle
EHS-gevallen bij grote hardloopevenementen gebeurt in de finishzone, niet
tijdens de race zelf** (Roberts 1998; Rae et al. 2008). Twee dingen
gebeuren namelijk zodra iemand stopt: de kerntemperatuur blijft nog even
doorstijgen (restwarmte die vanuit de spieren naar de kern diffundeert,
terwijl actieve koeling wegvalt), en de cardiovasculaire reserve stort
acuut in doordat de spierpomp stopt en de veneuze terugvoer terugvalt
("venous pooling", Rowell 1974). Omdat de dosis pas telt wanneer T_rect≥
40,5°C ÉN CO_reserve≤0 **tegelijk** gelden, vallen die twee voorwaarden bij
veel deelnemers precies rond het finish-moment samen.

Bij een pittiger tempo (hogere MET) kan de dosis al **tijdens** de race
beginnen te lopen, niet pas erna — dan is de deelnemer al vóór de finish
tegelijk boven de temperatuurdrempel én cardiovasculair door de reserve
heen. Dat onderscheidt twee reële faalmodi die het model allebei laat
zien: te-langzaam-en-te-lang (risico concentreert zich rond de finish) en
te-hard-gaan (risico loopt al tijdens de race op).

**Belangrijke beperkingen van het hoofdgetal:**
- De Falmouth-regressie waarop het dosis-responsmodel is gekalibreerd, is
  gefit op één specifieke 11 km-race met een brede recreatieve-tot-elite
  deelnemersgroep (R²=0,65). Toepassen op een andere afstand, duur of
  deelnemersgroep is zelf ook een benadering.
- Het dosis-responsmodel is gefit op een kleine steekproef (n=120 per
  scenario) — en sinds de clo-fix zijn er per scenario nog minder
  deelnemers die het gevarenkwadrant ooit raken, wat de fit losser maakt
  (voorspelling/doel-verhouding nu 0,6-1,8×, breder dan voorheen). Dit is
  een bekend, gedocumenteerd voorbehoud — geen instelling om zelf aan te
  passen.
- Als het gekozen tempo (MET) of de duur sterk afwijkt van waarop de
  curve is gefit (MET≈10,5, ≈96 min), verschijnt een expliciete
  waarschuwing in de app.

**Twee waarschuwingen die je serieus moet nemen, en die de app ook zelf
toont:**

1. **PROVISIONAL kalibratie.** De vertaling van simulatie naar
   percentages is door de auteur zelf als "voorlopig" gemarkeerd — kleine
   steekproef, nog niet op productieschaal herbevestigd. Behandel de
   getallen als richtinggevend, niet als vaststaand.
2. **Sommige niveaus worden automatisch niet getoond.** Bij een te
   pittig tempo (hoge MET) raakt de onderliggende populatie "tegen het
   plafond" gesimuleerd — dan toont de app een uitleg in plaats van een
   getal, in plaats van een onbetrouwbaar cijfer te presenteren.

Niets hier draait automatisch. Per niveau staat een knop **"Calculate
race-day physiology"** — pas na die klik draait de snelle schatting
(enkele seconden). Dit is bewust een aparte stap: het is een zware
berekening, en niet elke gebruiker heeft deze race-specifieke laag nodig
naast de rest van de app. Een **volledige berekening** (nauwkeuriger, kan
enkele minuten duren) is daarna nog een aparte, verdere keuze.

### 3.7 Regulatory loop — beyond WBGT and UTCI
Meerdaagse controletheoretische weergave: hoeveel "regelruimte" een groep
nog heeft, en of warme nachten herstel blokkeren. Hetzelfde meerdaagse
tijdschaal-voorbehoud als §3.4 geldt hier ook.

### 3.8 Course analysis (GPX)
Upload een GPX-track voor een parcoursgebonden analyse: tempo, water­
posten, en weersomstandigheden langs de route zelf.

### 3.9 PYROX Persoonlijk — één deelnemer, eigen apparaat

Zelfde HESTIA-motor als §3.6, maar met jouw eigen lengte, gewicht,
leeftijd, tempo en gewoontes in plaats van een gesimuleerde populatie.
De vergelijking "1000 gesimuleerde deelnemers" is dan niet meer zinvol —
alle "deelnemers" ben jij, met alleen de dag-onzekerheden (windrichting,
pacing-respons, zweetvariatie) herhaald getrokken. De app toont daarom
een percentage van je eigen ensemble-runs, geen aantal per 1000, en een
"2,5–97,5e percentiel"-band in plaats van een enkele lijn.

**Privacy: leg dit eerst uit, niet achteraf.** De enige gegevens die de
app naar buiten stuurt zijn de plaatsnaam en datum van het evenement, om
het weer op te halen — nooit lengte, gewicht, leeftijd of een uitkomst.
Dat geldt echter alleen voor **wie het proces daadwerkelijk draait**.
Start jij `streamlit run app_persoonlijk.py` op je eigen pc, dan ben jij
dat, en klopt de garantie volledig. Geef je iemand anders een gedeelde
URL (inclusief een Streamlit Cloud-link), dan draait het proces nog
steeds bij jou — zijn invoer komt bij jouw machine of bij de
cloud-server terecht, niet bij hem. Er bestaat geen manier om een
gemakkelijk te delen link te combineren met een gegarandeerd privé
resultaat voor de bezoeker; dat is een grens van client-server-software
zelf, geen tekortkoming van deze app. Wil je de app voor meerdere mensen
beschikbaar maken met behoud van die garantie, dan moet ieder zijn eigen
exemplaar starten (`git clone` + zelf `streamlit run`, of een
Windows-installatie).

Drie endpoints, niet één (zie de woordenlijst, §8, voor de volledige
definities): **EHS** (gekalibreerd, per 1000, race + herstel), **EHE**
(ongekalibreerd, percentage, alleen tijdens de inspanning), **EAC**
(ongekalibreerd, percentage, alleen na de finish). Een Word-rapport met
alle drie en een verklarende sectie is met één knop te downloaden onder
de resultaten.

### 3.10 PYROX Klimaatprojectie — houdbaarheid van een vaste jaardatum

Deze app beantwoordt een andere vraag dan de vier hiervoor: niet "hoe
riskant is dit evenement dit jaar", maar "blijft een vaste jaarlijkse
datum/locatie verantwoord naarmate het klimaat opschuift".

**Wat je invult:** locatie, de kalenderdatum (het jaartal zelf doet er
niet toe — alleen dag en maand), starttijd, duur, tempo van de mediane
deelnemer, terreintype, een zelf ingestelde EHE-grens (%), en een reeks
toekomstige jaren om te vergelijken (bijvoorbeeld 2030 t/m 2050, in
stappen van 5 jaar).

**Wat de app doet, in het kort** (de volledige methode staat in de
docstring bovenin `app_klimaatprojectie.py` en in `README.md`):

1. Haalt het echte, waargenomen weer op voor elk jaar 1996–2025, in een
   venster van jouw datum ±3 dagen — tot 210 historische dagen.
2. Schat de opwarmingstrend op díe specifieke periode van het jaar (niet
   de jaarpiek), met dezelfde Theil-Sen-methode als Klimatos.ClimateShift.
3. Verschuift voor elk gekozen toekomstig jaar diezelfde 210 dagen met die
   trend, en rekent daarna de volledige fysische keten (stad-warmte-eiland,
   globe-temperatuur, WBGT/UTCI) opnieuw door — niet los van elkaar.
4. Laat elke dag door dezelfde HESTIA-populatie-ensemble lopen als
   PYROX/PYROX Beleid, en middelt het resultaat over de 210 dagen.

**Wat je terugkrijgt, per jaar naast de referentieperiode:**
- de verwachte EHE-uitkomst (als percentage **én** als "per 1000")
- de kans dat je ingestelde grens dat jaar wordt overschreden
- het Falmouth-gekalibreerde EHS/1000 ter vergelijking

**Belangrijke kanttekening, die de app zelf ook op elke pagina toont:**
EHE is, net als in de andere apps, **niet gekalibreerd** tegen
waargenomen incidentie. Anders dan in de rest van de suite toont deze
app EHE tóch als "per 1000" — dat is een bewuste keuze voor dit ene
instrument, nadrukkelijk gelabeld als indicatief/ongekalibreerd, zodat
het naast het wél gekalibreerde EHS/1000 herkenbaar blijft wat wel en
niet op echte incidentie is getoetst. De toekomstprojectie zelf is een
statistische trendextrapolatie, geen klimaatmodel en geen weersvoorspelling
voor een specifiek jaar — een individueel jaar kan altijd sterk afwijken.

Bedoeld voor een indicatief gesprek met een organisatie ("moeten we deze
datum over tien jaar heroverwegen"), niet als eindoordeel op zichzelf.

---

## 4. Waarom zeggen twee onderdelen soms iets anders?

Dit gebeurt, en de app signaleert het zelf met een waarschuwing zodra het
optreedt. Twee vaste patronen:

### 4.1 "De vlag zegt hoog risico, maar de reserve zegt 100%"
De vlag (§3.2) kijkt naar het huidige uur. De reserve (§3.4) is
meerdaags en verdunt een korte race bijna tot niets. **Vertrouw de vlag
voor dezelfde-dag-beslissingen, de reserve alleen voor meerdaagse
opbouw.**

### 4.2 "PYROX zegt 100% reserve, maar HESTIA vindt veel deelnemers met nul/negatieve capaciteit"
Zelfde oorzaak. PYROX is niet gebouwd om een race van 1-2 uur te
beoordelen. HESTIA wél. **Vertrouw voor de race zelf HESTIA, niet de
PYROX-reservekaart.**

Bij allebei toont de app automatisch een gele waarschuwing met uitleg
zodra dit patroon zich voordoet — je hoeft het dus niet zelf te
herkennen.

---

## 5. Welk onderdeel voor welke beslissing?

| Beslissing | Gebruik |
|---|---|
| Starttijd of tempo-advies, vandaag | §3.2 Race-day heat flags |
| Wie loopt risico tijdens déze race zelf | §3.6 HESTIA (met het PROVISIONAL-voorbehoud in gedachten) |
| Trainingsopbouw richting een hittegolf of wedstrijddag | §3.4 / §3.7 (PYROX) |
| Sportspecifiek advies op basis van omgevingscondities | §3.5 Sports Medicine Australia/PHS |
| Globaal, snel overzicht voor een niet-ingewijde | De groene/gele/rode accu-kaarten in §3.4, in de "Simple"-weergave |
| Blijft een vaste jaardatum houdbaar over 10-20 jaar | §3.10 PYROX Klimaatprojectie (indicatief, ongekalibreerd) |

---

## 6. Wat de app NIET is

- **Geen medische diagnose.** Alle uitkomsten zijn groepsgemiddelden uit
  een model, geen voorspelling voor een individu.
- **Geen bewezen incidentvoorspeller.** Met uitzondering van HESTIA's
  eigen, voorlopige vergelijking met echte DtD-gegevens, is geen enkel
  onderdeel getoetst aan echte medische registraties. Zie het
  **"📚 Evidence base"**-paneel onderaan de algemene app voor het volledige
  overzicht van wat wel en niet is onderbouwd.
- **Geen vervanging voor plaatselijke medische expertise.** De app geeft
  input voor een gesprek met een arts/EHBO-coördinator, niet het laatste
  woord.

---

## 7. Veelgestelde vragen

**"Waarom is de accu op 100% terwijl het buiten snikheet is?"**
Check welke datum er bij "Time in the heat" staat ingesteld — de kaart
toont de reserve óp die datum, niet per se de slechtste dag in de hele
periode. Check ook of je naar §3.4 (meerdaags, verdunt korte races) of
§3.6 (racespecifiek) kijkt.

**"Waarom staat er geen T_re-grafiek bij deze groep?"**
Het onderliggende model is alleen gevalideerd voor wandelaars van 60-100
jaar. Bij andere groepen laat de app het bewust weg in plaats van een
cijfer te tonen dat buiten het gevalideerde bereik ligt.

**"Waarom mist HESTIA voor Elite/Trained-endurance-lopers?"**
Bij een te snel tempo raakt de gesimuleerde populatie "tegen het
plafond" — de app herkent dit automatisch (bij >50% van de virtuele
deelnemers) en toont dan een uitleg in plaats van een onbetrouwbaar getal.

**"Wat betekent 'Worth monitoring: 80%' — moeten 80% van de deelnemers
naar de EHBO?"**
Nee. Dit is een bewust ruime signaleringsvlag (uitdroging óf hoge
inspanning óf hoge temperatuur), geen voorspelling van daadwerkelijke
EHBO-bezoeken. Kijk voor de zwaardere, preciezere uitspraak naar "True
EHS criterion met" ernaast.

**"Kan ik deze cijfers gebruiken om ambulances/EHBO-capaciteit te plannen?"**
Nog niet zonder voorbehoud. De onderliggende kalibratie is door de auteur
zelf als voorlopig gemarkeerd. Bruikbaar om **groepen en dagen onderling
te vergelijken**; nog niet als vaststaande absolute planningscijfers.

---

## 7b. Voorspellingen bewaren voor latere vergelijking

Onderaan de deelnemersapp staat **"📥 Download prediction record
(Excel)"**. Dit legt de complete stand van zaken vast op het moment dat
je hem downloadt: alle vlaggen, PYROX-reserve, HESTIA-cijfers (inclusief
de PROVISIONAL-status), en welke waarschuwingen er zijn afgegaan — met
lege kolommen erbij (`actual_first_aid_visits`,
`actual_hospitalisations`, `actual_ehs_cases`) om na afloop van het
evenement zelf in te vullen.

**Waarom dit belangrijk is:** Streamlit Cloud bewaart niets vanzelf —
een herstart wist alles. Als je de app parallel meedraait met echte
evenementen of hittegolven, is dit exportbestand de enige manier om een
voorspelling te bewaren tot je hem tegen de werkelijkheid kunt afzetten.

## 8. Korte woordenlijst

| Term | Betekenis |
|---|---|
| **WBGT** | Wet Bulb Globe Temperature — de gangbare hittestress-index voor sport |
| **UTCI** | Universal Thermal Climate Index — fysiologisch "voelt als"-getal |
| **MRT** | Stralingstemperatuur van de omgeving (zon, hete oppervlakken) |
| **MET** | Metabolic Equivalent — maat voor inspanningsintensiteit |
| **RPE** | Rate of Perceived Exertion. Let op: dit model gebruikt de klassieke **Borg-schaal (6–20)**, niet de vaker gebruikte Borg CR10-schaal (0–10). Op de 6-20-schaal betekent 17 "very hard", geen middenwaarde. |
| **T_rect / T_re** | Lichaamskerntemperatuur (rectaal gemeten/voorspeld) |
| **CO_reserve** | Cardiovasculaire reserve — hoeveel "extra" hartminuutvolume er nog is boven wat inspanning en warmteregulatie samen al opeisen. Nul betekent: geen verdere toename van koelcapaciteit meer beschikbaar. |
| **Dosis** | Het tekort geïntegreerd over tijd (L/min × minuten) zolang een criterium geldt — weegt zowel hoe diep als hoe lang, in plaats van elk moment even zwaar te tellen. |
| **Conjunctief / gelijktijdig** | Alle drie de criteria hieronder vereisen beide voorwaarden op **hetzelfde tijdstip**. Een temperatuurpiek om 11:00 en een reservedal om 13:00 tellen niet mee — dit is het onderscheid met optelbare indices zoals WBGT. |
| **EHS** | Exertional Heat Stroke. Klinisch: CNS-disfunctie plus kerntemperatuur >40,5 °C. Dit model kan geen neurologische status simuleren en vervangt dat door cardiovasculaire decompensatie (T_rect≥40,5 °C én CO_reserve≤0) — een conservatieve vervanging. Enige gekalibreerde endpoint (tegen Falmouth-incidentie), vandaar het enige dat als "per 1000" wordt getoond. |
| **EHE** | Exertional Heat Exhaustion. Klinisch: uitputting, kerntemperatuur doorgaans 38,5–40 °C, zónder de CNS-disfunctie die EHS definieert. Gemodelleerd als T_rect>39,5 °C én CO_reserve<0, alleen tijdens de inspanning. Markeert verloren regelmarge, niet een aanstaande hittebevanging. Ongekalibreerd — getoond als percentage, niet per 1000. |
| **EAC** | Exercise-Associated Collapse. Klinisch: een bij bewustzijn zijnde sporter die na de finish niet zelfstandig kan staan of lopen, door bloeddrukval wanneer de spierpomp wegvalt. Cardiovasculair, niet thermisch — daarom geen temperatuurdrempel. Vereist een aanhoudend tekort, geen enkele korte dip. Ongekalibreerd in dit model (referentie-incidentie 1,53 per 1000, Göteborg, nog niet gefit) — getoond als percentage. |
| **Reserve / collapse risk** | PYROX's meerdaagse maat voor resterende regelcapaciteit |

---

*Voor technisch beheer (GitHub, Streamlit-deployment, troubleshooting)
zie `HANDLEIDING.md`. Voor de volledige wetenschappelijke onderbouwing
zie het evidence-paneel in de app zelf.*
