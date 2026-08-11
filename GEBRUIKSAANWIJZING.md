# PYROX — gebruiksaanwijzing

Deze handleiding is voor mensen die de app **gebruiken**: organisatoren,
hulpverleners, coaches, deelnemers. Voor het beheren van de Streamlit/
GitHub-technische kant is er een aparte handleiding (`HANDLEIDING.md`).

PYROX bestaat uit **twee apps**, en dit document behandelt beide:

| App | Voor wie |
|---|---|
| **PYROX** (algemeen) | Beleid, beroepsgroepen, de brede bevolking |
| **PYROX Participants** | Hardlopers, wandelaars, evenementenorganisatie |

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

**De ruwe simulatiecijfers** staan nog steeds beschikbaar, in een
uitklapbare sectie "Raw physiological simulation (uncalibrated)":

| Metriek | Betekenis |
|---|---|
| Peak T_re, mean | Gemiddelde piek-lichaamskerntemperatuur |
| True EHS criterion met | % dat **tegelijkertijd** T_rect≥40,5°C ÉN cardiovasculaire reserve≤0 bereikt — ruwe, ongekalibreerde simulatie-uitkomst |
| Worth monitoring (broad screen) | Brede signaleringsvlag (uitdroging óf hoge inspanning óf hoge temperatuur) — bewust ruim, geen medisch incidentcijfer |
| Avg. cardiovascular capacity remaining | Hoeveel cardiovasculaire reserve een gemiddelde deelnemer overhoudt tijdens + 10 min na de finish |
| Reached zero/negative capacity | % dat op enig moment tijdens/vlak na de race op nul of negatieve capaciteit komt |

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
| **T_rect / T_re** | Lichaamskerntemperatuur (rectaal gemeten/voorspeld) |
| **CO_reserve** | Cardiovasculaire reserve — hoeveel "extra" hartminuutvolume er nog is |
| **EHS** | Exertional Heat Stroke — inspanningsgebonden hitteberoerte |
| **Reserve / collapse risk** | PYROX's meerdaagse maat voor resterende regelcapaciteit |

---

*Voor technisch beheer (GitHub, Streamlit-deployment, troubleshooting)
zie `HANDLEIDING.md`. Voor de volledige wetenschappelijke onderbouwing
zie het evidence-paneel in de app zelf.*
