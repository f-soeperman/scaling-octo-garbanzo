# Bodemsensor vs. FAO-56-model (Project 16 → Project 1) — eerste analyse, augustus 2026

_Datum: 2026-08-15. Aanleiding: de GARDENA smart Sensor (19040-20) is aangesloten en
`data/gardena_history/` draagt zijn eerste rijen. Dit is de eerste keer dat er iets bestaat om de
waterbalans van Project 1 tegen te leggen; tot nu toe was `docs/data.json` een volledig ongetoetst
model. Reproduceren: `python tools/gardena_sensor_eval.py`._

**Oordeel in één alinea.** Er is nog **geen** uitspraak over modelprestatie mogelijk, en dat is
geen voorzichtigheid maar rekenkunde: het record is **11,9 uur lang, uitsluitend nacht, en bevat
na de inregel-rijen precies één vochtwaarde** (70 %) op een resolutie van vermoedelijk 5
procentpunt. Eén getal tegen één modelgetal is geen validatie, hoe goed het ook uitkomt. Wat deze
eerste rijen wél doen is drie dingen vastleggen die er straks toe doen. (1) **De sensor rapporteert
géén θ** — 70 % ligt boven de porositeit van zand, dus er is een onbekende mapping nodig en de
verleiding om "70 % vocht" naast "θ = 0,17" te leggen en te concluderen dat het model 4× te droog
staat, is een rekenfout, niet een bevinding. (2) Van de vier plausibele mappings landt
"% plantbeschikbaar water in de wortelzone" als enige in de buurt: het model zegt op de
installatiedag **73,5 % (struiken)** en **63,2 % (gras)** tegen de sensor **70 %**. Dat is een
hypothese om te toetsen, geen bevestiging. (3) De **bodemtemperatuur** is wél direct vergelijkbaar,
en daar staat meteen een vlag: de sensor mat 's nachts 20,2 °C terwijl de Open-Meteo-overlay
`Tsoil_shallow` voor die dag een etmaalgemiddelde van 24,6 °C op 6 cm geeft. Dat is nog geen
tegenspraak (we hebben geen daguren), maar het is het eerste getal dat de overlay ooit tegenover
een meting heeft gehad. De belangrijkste opbrengst van deze ronde is daarom §4: de **regenbui van
18–19 augustus** is een scherp onderscheidend experiment — niet op grootte maar op *timing*, omdat
de oppervlaktelaag na ~2 mm vol zit en de wortelzone pas na ~20 mm — en de voorspelling ervan
staat hieronder vastgelegd vóórdat de data binnen zijn. De droge dagen ervóór beslissen niets: in
de struikenzone (waar de prikker blijkt te zitten) liggen de twee hypotheses daar maar één
sensorstap uit elkaar.

---

## 1. Wat er staat

| | |
|---|---|
| record | 2026-08-14 21:18 → 2026-08-15 09:10 lokaal (11,9 u, 12 rijen) |
| waarvan inregel | 2 rijen (venster 2 u na de eerste observatie) |
| `soil_hum` waargenomen | 65 en 70 → stap ≈ **5 procentpunt** |
| `soil_temp` waargenomen | 26, 21, 20 → stap 1 °C |
| dekking | uitsluitend 21:18–09:10, **geen enkel daguur** |

De eerste rij (21:18, `hum` 65, `temp` 26) is als inregel-rij behandeld. De grond daarvoor is
thermisch: de waarde zakt binnen twee uur 5 °C en beweegt daarna over tien uur nog maar 1 °C.
Dat is de exponentiële settle van een lichaam dat met een nieuwe omgeving in evenwicht komt, niet
het dagritme van een bodem — die kan niet eerst tien keer zo snel dalen als daarna. Het
alternatief (de prikker mat op 21:18 echt 26 °C, vlak na een dag met Tmax 39 °C) is niet
uitgesloten en de filter gooit de rij daarom niet weg maar markeert 'm; `--settle-h 0` zet 'm uit.

**Twee meetkundige beperkingen die de rest van dit document sturen:**

- **Resolutie 5 pp.** Zolang de sensor in stappen van 5 rapporteert, is elke modeldrift kleiner
  dan dat principieel onmeetbaar, en betekent "de sensor stond stil" *niets*. In de 11 uur die we
  hebben voorspelt het model een verandering van ~0,3 pp. De vlakke reeks bevestigt dus niets —
  een kapotte sensor die op 70 blijft hangen ziet er exact zo uit. (De 5 pp is zelf nog een
  schatting uit twee waarden; het is het eerste dat de groeiende reeks bevestigt of weerlegt.)
- **Cadans.** De shard bemonstert op het uurritme van de runner, niet van het apparaat, en pakt
  elke sensorwaarde ~1 uur later op. Nu de sensor uurlijks meldt levert dat 1 rij/uur zonder
  verlies. Zou het apparaat op 30 minuten overgaan, dan belandt de helft nooit in het archief —
  iets om aan te denken bij een firmware-wissel, geen actie nu.

## 2. Waarom sensor en model niet hetzelfde meten (en wat dat voor de vergelijking betekent)

Drie verschillen tegelijk, die alle drie de *verkeerde* manier van vergelijken aantrekkelijk maken:

**Andere eenheid.** GARDENA documenteert de schaal van "soil humidity" niet. 70 % kan geen
volumetrisch vochtgehalte zijn (dat ligt voor dit zand rond 0,10–0,20, en boven ~0,43 zit je boven
de porositeit). `tools/gardena_sensor_eval.py` kiest daarom bewust geen mapping maar rekent alle
vier de plausibele kandidaten door, zodat de reeks zelf mag uitwijzen welke standhoudt:

| mapping | gras | struiken | sensor |
|---|---|---|---|
| θ × 100 | 16,0 | 17,1 | 70 |
| **% plantbeschikbaar water (wortelzone)** | **63,2** | **73,5** | **70** |
| % van verzadiging | 37,1 | 39,7 | 70 |
| % vulling oppervlaktelaag (0–10 cm) | 96,2 | 92,2 | 70 |

De sensorwaarde valt netjes tússen de twee zones van de beschikbaar-water-mapping in. Dat is
opvallend genoeg om als leidende hypothese te noteren en te zwak om iets mee te doen: met vier
kandidaten en één meetpunt is "eentje past" de verwachting, niet het bewijs.

**Andere diepte — en dit is het interessantste punt.** De prikker zit op ~5–10 cm. Het model heeft
daar géén toestandsvariabele voor. Het draagt een *oppervlaktelaag* (`De`, Ze = 0,10 m) die alleen
door **verdamping** leegloopt, en een *wortelzone* (`theta`, Zr = 0,20 m gras / 0,50 m struiken)
die door **transpiratie** leegloopt. De prikker zit fysiek in de eerste, maar meet mee met de
tweede: wortels onttrekken juist bovenin het meest.

Dat is geen theoretische subtiliteit, want de twee lopen in dit seizoen ver uiteen. Onder de dichte
beplanting is `few` klein (0,05 gras / 0,10 struiken), dus E is maar 0,24–0,48 mm/dag en de
oppervlaktelaag blijft **92–96 % vol** terwijl de wortelzone al **26–37 % uitgeput** is. De twee
hypotheses voorspellen dus totaal verschillende dingen voor de komende droge dagen — precies wat
§4 uitbuit. Merk op dat de *dieptematig juiste* vergelijking (oppervlaktelaag) het slechtst bij de
meting past; dat is geen modelfout maar de FAO-56-tweebakkenstructuur die doet wat ze hoort te
doen, alleen niet op de as die de sensor bemonstert.

**Ander punt in de ruimte.** Eén prikker in één bed tegen een zone-gemiddelde over de hele tuin.
Ruimtelijke variatie in bodemvocht is groot; een systematisch niveauverschil is daarom **geen**
modelfout en mag ook nooit als kalibratiedoel gebruikt worden.

**Gevolg voor de maat.** Een RMSE tussen sensor en model zou een precisie suggereren die deze drie
punten uitsluiten — met een onbekende mapping is elke RMSE vooral een keuze van de mapping. De
maat die er wél toe doet is de **dynamiek**: een onbekende schaalfactor en een ruimtelijke offset
overleven een dag-op-dag-differentie niet, een kloppende waterbalans wel. Zakt de meting terwijl
het model zakt en springt hij op de dag dat het model naar veldcapaciteit gaat, dan klopt de
balans — ongeacht het niveau. Die maat staat in de tool en zegt nu terecht "nog geen uitspraak,
0 van de 3 benodigde volledige dagen".

## 3. Bodemtemperatuur — het enige kanaal met nú al signaal

Hier is °C gewoon °C, dus deze vergelijking heeft geen mapping nodig.

| | sensor | lucht (zelfde uren) | `Tsoil_shallow` (OM 6 cm, etmaal) | `Tsoil_root` (OM 18 cm, etmaal) |
|---|---|---|---|---|
| 2026-08-15 (9 u dekking, nacht) | 20,2 gem. / amplitude 1,0 | 21,7 gem. / amplitude 3,7 | 24,64 | 25,37 |

Twee waarnemingen:

- **De demping klopt kwalitatief.** Van de luchtswing bereikt 0,27 de sensordiepte. Sterke demping
  op ~5–10 cm is precies wat je verwacht, en het is de sanity-check dat de prikker echt in de
  bodem zit en niet half bloot ligt. Let op: dit is de demping over een **nachtvenster**, niet over
  een etmaal — de echte diurnale verhouding kan er fors naast zitten en volgt uit de eerste
  volledige dag.
- **Er staat een vlag bij de overlay.** De sensor zat de hele nacht op 20 °C; Open-Meteo's
  etmaalgemiddelde op 6 cm is 24,6 °C. Om die twee te verzoenen zou de bodem overdag naar ~29–30
  °C moeten pieken, terwijl de nacht een amplitude van 1 °C liet zien. Dat is niet onmogelijk (de
  luchtdag ervoor haalde Tmax 39 °C) maar het is spanning, en het is de eerste keer dat de
  `Tsoil_*`-velden ooit tegenover een meting staan. **Dit is expliciet nog geen bevinding:** een
  nachtmiddel tegen een etmaalmiddel leggen meet het etmaal, niet de modelfout. Het rapport
  markeert zulke dagen daarom met `full_day = NEE`. Eén volledige dag lost dit op.

**Wat dit nog niet kan zeggen, en wanneer wel.** `temp_factor` is de enige plek waar
bodemtemperatuur het bodemmodel binnenkomt, en die draait op een 5-daags loopgemiddelde van de
*lucht*-Tmean — de "nooit-gemeten aanname" uit CLAUDE.md. Toetsen kan nu niet: het loopgemiddelde
staat op 21,8 °C, ver boven de 8 °C waarboven `temp_factor` op 1,0 vastligt. Sensor én proxy geven
1,0, dus het verschil verandert nul beslissingen. Deze reeks is voor de **schouderseizoenen**
(ruwweg okt–apr) en wordt nu gebankt, niet nu beantwoord. Dat is ook waarom `soil_temp_proxy.py`
tot die tijd ongemoeid blijft: hij vergelijkt de proxy met ERA5, en de sensor wordt daar pas een
betere referentie voor als er een winter in zit.

## 4. Vooraf vastgelegd: het onderscheidende experiment van deze week

**De prikker zit in de struiken** (bewonersopgave, 15 aug 2026). Dat is nu de leidende modelkolom
(`SENSOR_ZONE` in de tool); gras blijft als referentie in het rapport staan, met een `*`. De
forecast in `docs/data.json` (gegenereerd 2026-08-15T08:00Z) bevat twee droge dagen gevolgd door
~50 mm regen:

| datum | regen | ET0 | struiken: wortelzone | struiken: oppervlak | vol na: opp. | vol na: wortelzone |
|---|---|---|---|---|---|---|
| 08-15 (nu) | 0,2 | 0,35 | 73,5 | 92,2 | 1,4 mm | 14,6 mm |
| 08-16 | 0,0 | 3,18 | 68,7 | 90,1 | 1,8 mm | 17,2 mm |
| 08-17 | 0,5 | 2,98 | **64,5** | 88,6 | **2,1 mm** | **19,5 mm** |
| 08-18 | 12,5 | 1,66 | 82,1 | 98,9 | 0,2 mm | 9,9 mm |
| 08-19 | 25,8 | 2,03 | **100,0** | 98,7 | 0,2 mm | 0,0 mm |

### 4a. De droge etappe is in de struiken géén bruikbare toets

Dat is de eerste consequentie van de zonebevestiging, en het is een verzwakking. Over
08-15 → 08-17 voorspelt de wortelzone −9,0 pp (≈ 1,8 sensorstappen) en de oppervlaktelaag
−3,6 pp (≈ 0,7 stap). De twee hypotheses liggen dus ~1 stap uit elkaar — precies op de
resolutievloer. In het gras zou dit onderscheid ~4 stappen zijn geweest; in de struiken is het
ruis. **Wat de sensor de komende twee dagen ook doet, het beslist niets over de diepte.**

### 4b. De regen doet het wél — en op timing, niet op grootte

Dit is het punt dat door het zonebesluit scherper werd in plaats van vager, en het volgt uit hoe
FAO-56 §7.4.5 de twee bakken bijhoudt. Regen en irrigatie worden van **beide** boekhoudingen
tegelijk afgetrokken (het zijn twee rekeningen over hetzelfde fysieke water), dus ze reageren op
dezelfde invoer en het onderscheid zit *niet* in óf ze stijgen. Het zit in **hoe snel ze vol
zitten**:

- de **oppervlaktelaag** loopt over bij TEW = 18 mm en staat onder de dichte beplanting al bijna
  vol → op 08-17 is hij verzadigd na **2,1 mm**;
- de **wortelzone** moet het hele tekort t.o.v. veldcapaciteit goedmaken → **19,5 mm**, bijna een
  factor tien meer (AWC struiken = 55 mm).

Twee scherp verschillende voorspellingen op uurresolutie, en de sensor meet uurlijks:

- **Zit hij in de oppervlaktelaag:** hij schiet binnen de eerste paar millimeter van de bui op
  08-18 naar zijn plafond en blijft daar de rest van de regenperiode vlak liggen.
- **Volgt hij de wortelzone:** hij klimt getrapt door — na de 12,5 mm van 08-18 zit hij ruwweg
  halverwege (het model zegt 82 %), en pas ergens in de 25,8 mm van 08-19 raakt hij zijn plafond.

**Dit is de beste toets die deze dataset gaat opleveren**, en wel omdat hij op de *vorm* draait:
hij werkt ook als de sensorschaal niet-lineair is. De niveauvergelijking uit §2 heeft die
eigenschap niet.

### 4c. De tweede, onafhankelijke vraag: is de schaal lineair?

Klimt de sensor van 70 naar ~95–100 terwijl het model naar veldcapaciteit gaat, dan houdt de
beschikbaar-water-mapping stand. Blijft hij rond 75–80 steken, dan is de schaal niet-lineair of
zit de sensor tegen zijn eigen plafond — en dan blijft 4b bruikbaar (vorm) maar is de
niveauvergelijking uit §2 waardeloos. Deze vraag staat bewust los van 4b genoteerd: in één
samengevoegde waarneming ("de sensor stijgt minder dan verwacht") zijn een dieptefout en een
schaalfout niet te scheiden.

### 4d. Wat er daarna nodig is

De struikenzone beweegt traag (~4,8 pp/dag droog, ≈ 1 sensorstap), dus de dynamiek-maat heeft hier
méér nodig dan de drie dagen die de tool minimaal eist — die drempel gaat over datasufficiëntie,
niet over onderscheidend vermogen. Voor een correlatie die iets betekent zijn een paar volledige
nat-droog-cycli nodig, dus weken.

Eén gunstige omstandigheid: de struiken worden door Project 16 zélf druppelbewaterd, en elke
geregistreerde beurt is een **bekende stapinvoer op een bekend tijdstip** — schoner dan regen
(geen interceptie-onzekerheid, geen ruimtelijke variatie in de bui). Omdat de oppervlaktelaag toch
al bijna vol staat, gaat vrijwel al het druppelwater rechtstreeks naar de wortelzone; de
responsvorm op zo'n beurt is dus een tweede, herhaalbare versie van de toets uit 4b. Dat maakt het
irrigatielogboek op termijn de waardevolste kolom in deze analyse — geen actie nu, wel de reden om
de beurten netjes geregistreerd te houden.

## 5. Wat ik bewust níet heb gedaan

- **Geen parameter aangeraakt.** FC, WP, Zr, TEW/REW en de FAO-56-formules staan onaangeroerd. Eén
  meetpunt met een onbekende mapping is het tegenovergestelde van een kalibratiegrond, en CLAUDE.md
  merkt die waarden bovendien als domeinbeslissingen aan.
- **Geen mapping in het model ingebakken.** Zolang de dynamiek geen kandidaat heeft gekozen, zou
  elke vertaling in productie een gok zijn die zichzelf daarna bevestigt.
- **Geen dashboard/Telegram.** Er is niets te melden dat een bericht rechtvaardigt, en een
  vochtgrafiek met één punt suggereert kennis die er niet is.
- **De sensorreeks niet in `docs/` gepubliceerd.** De shards zijn al publiek en dat is genoeg;
  Project 16 meldt verder uitsluitend privé.

## 6. Wanneer dit opnieuw draaien

`python tools/gardena_sensor_eval.py` (optioneel `--json <pad>`, `--zone lawn` voor de
referentiekolom). De dynamiek-sectie schakelt zichzelf in zodra er **3 dagen met ≥ 18 uur dekking**
staan — bij ongestoorde cadans 2026-08-18. De eerstvolgende zinnige momenten:

1. **~08-18** — eerste dynamiek-uitspraak, maar over de droge etappe, en die is in de struiken te
   traag om iets te beslissen (§4a). Vooral een controle dat de pijplijn en de dekking kloppen
   vóór de bui — mislopen we die, dan is er weken niets vergelijkbaars.
2. **~08-20, op uurresolutie** — **het echte moment**: de vorm van de sensorrespons op de regen
   van 08-18/19 beantwoordt de dieptevraag (§4b), en de eindstand beantwoordt de
   lineariteitsvraag (§4c). Hier is het dagmiddel níet de juiste blik; kijk naar de rijen zelf in
   `data/gardena_history/`.
3. **~08-21** — eerste volledige dagen voor de bodemtemperatuur-vergelijking (`full_day = ja`),
   waarmee de vlag uit §3 over de Open-Meteo-overlay beslisbaar wordt.
4. **schouderseizoen (okt–nov)** — pas dan wordt de `temp_factor`-proxy toetsbaar, en dat is de
   vraag met de grootste modelimpact (groeiseizoensgrenzen, en daarmee Project 5).
