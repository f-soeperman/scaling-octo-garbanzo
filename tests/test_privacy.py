"""Privacy-invarianten van de publieke repo — afgedwongen in CI, niet per sweep.

**Waarom dit bestand bestaat.** De privatisering ging in vier rondes (aug 2026) en
elke ronde repareerde *gevallen*: dit bestand, dat veld, die pagina. Niets hield de
vólgende tegen, dus elke ronde vond weer iets nieuws — het huismodel-README met een
eigennaam, de bijnaam van een kamer, de weekkalender in `weather_briefing.py`, de
badkamerreeks in de shards. Dat is geen slordigheid maar een ontbrekende controle.

Deze tests zetten de regels uit de PRIVACY-banner van CLAUDE.md om in assertions over
de échte boom, zodat een terugval de build breekt in plaats van te wachten op de
volgende handmatige sweep. Ze draaien op `git ls-files`, dus ze dekken precies wat
gepubliceerd wordt.

Faalt er één? Repareer de inhoud — zet de test niet ruimer. De denylists hieronder
mogen groeien (nieuwe namen), maar de invarianten niet verslappen.
"""
import base64
import json
import os
import re
import subprocess

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Dit bestand ís de denylist en draagt de verboden patronen dus per definitie —
# het moet zichzelf overslaan, anders klaagt het eeuwig over zijn eigen inhoud.
# Bewust één expliciet pad en geen algemene "sla tests/ over": de rest van de
# suite hoort wél gescand te worden (een fixture is net zo publiek als de code).
#
# Deze zelfverwijzing bleef bij het schrijven verborgen doordat het bestand toen
# nog untracked was en `git ls-files` het dus niet teruggaf — de suite werd pas
# eerlijk toen het gecommit was.
_SELF = "tests/test_privacy.py"


def _tracked(*suffixes: str) -> list[str]:
    """Alle door git gevolgde bestanden (optioneel op extensie gefilterd).

    Git is hier de juiste bron en niet `os.walk`: precies de gevolgde bestanden
    worden publiek, en genegeerde lokale terugval-artefacten juist niet."""
    out = subprocess.run(["git", "-C", _ROOT, "ls-files"],
                         capture_output=True, text=True, check=True).stdout.split()
    files = [f for f in out
             if f != _SELF and os.path.exists(os.path.join(_ROOT, f))]
    if suffixes:
        files = [f for f in files if f.endswith(suffixes)]
    return files


def test_de_denylist_slaat_alleen_zichzelf_over():
    """Vangnet op de uitzondering hierboven: precies één bestand mag ontbreken.

    Zonder dit kan een latere 'even dit ook overslaan' de scan stilletjes
    uithollen — dan is de suite groen omdat ze niets meer bekijkt."""
    tracked = subprocess.run(["git", "-C", _ROOT, "ls-files"],
                             capture_output=True, text=True, check=True).stdout.split()
    on_disk = {f for f in tracked if os.path.exists(os.path.join(_ROOT, f))}
    assert on_disk - set(_tracked()) == {_SELF}
    assert len(_tracked()) > 100, "scan lijkt leeg te lopen"


def _read(path: str) -> str:
    with open(os.path.join(_ROOT, path), encoding="utf-8", errors="replace") as f:
        return f.read()


# ── 1. Persoonsnamen ────────────────────────────────────────────────────────────
#
# Namen en roepnamen van bewoners horen nergens in de boom — ook niet in een
# comment, een label of een testfixture. Kamers dragen functionele namen; de échte
# tado-zonenaam hoort hooguit in het TADO_ZONE_ALIASES-secret.
#
# De namen staan hier BASE64 en niet als platte tekst. Reden: na de opschoning is
# dit bestand de énige plek in de hele boom waar ze anders nog zouden voorkomen, en
# GitHub indexeert publieke broncode. Een zoekopdracht op de achternaam zou het
# pseudonieme account dan precies weer aan de persoon koppelen — het risico dat de
# hele verhuizing moest wegnemen. De bewaker werd zo zelf de laatste lek.
#
# Dit is nadrukkelijk OBFUSCATIE, geen geheimhouding: wie dit bestand openslaat
# decodeert het in één regel. Dat volstaat, want de dreiging is indexering en
# toevallig grep-en door een voorbijganger, niet een vastberaden lezer — die vindt
# de namen sowieso in de tado-app noch hier. De scan zelf draait onveranderd op
# platte tekst, dus de detectiekracht is exact gelijk gebleven.
#
# Groeit deze lijst? Voeg toe in kleine letters, base64-gecodeerd:
#     python3 -c "import base64;print(base64.b64encode(b'naam'))"
# Vermijd namen die als gewoon woord voorkomen (dan matcht de test overal) — kies
# dan een specifiekere spelling.
FORBIDDEN_NAMES = tuple(base64.b64decode(b).decode() for b in (
    b"bmllbHM=",       # voornaam bewoner
    b"bW9sZW5hYXI=",   # achternaam bewoner
    b"aG90dGllcw==",   # oude bijnaam van de slaapkamer (nu 'bedroom')
))


def test_geen_persoonsnamen_in_de_boom():
    hits = []
    for path in _tracked():
        low = _read(path).lower()
        for name in FORBIDDEN_NAMES:
            if name in low:
                hits.append(f"{path}: {name!r}")
    assert not hits, (
        "Persoonsnaam/bijnaam in een publiek bestand — zie de PRIVACY-banner in "
        "CLAUDE.md:\n  " + "\n  ".join(hits))


# ── 2. Locatie ──────────────────────────────────────────────────────────────────
#
# De coördinaten staan bewust op 2 decimalen (~1 km). 4 decimalen resolven een
# individueel adres (~11 m) — precies wat het WU_STATION_ID-secret moet voorkomen.
_COORD_ASSIGN = re.compile(
    r"\b(?:lat|lon|latitude|longitude|LAT|LON|LATITUDE|LONGITUDE)\b"
    r"\s*[:=]\s*(-?\d+\.(\d+))")
# Tupel-vorm `LAT, LON = 52.09, 5.12`: de oude regex zag alleen de rechter waarde
# (de komma brak de match op de linker) — gedicht bij de privacy-assessment (aug 2026).
_COORD_TUPLE = re.compile(
    r"\b(?:lat|lon|latitude|longitude)\s*,\s*(?:lat|lon|latitude|longitude)\s*=\s*"
    r"(-?\d+\.(\d+))\s*,\s*(-?\d+\.(\d+))", re.IGNORECASE)


def test_coordinaten_blijven_op_twee_decimalen():
    # Sinds de privacy-assessment (aug 2026) ook .md: een coördinaat in een
    # assessment-doc is net zo publiek als een in code.
    hits = []
    for path in _tracked(".py", ".js", ".json", ".html", ".yml", ".md"):
        text = _read(path)
        for m in _COORD_ASSIGN.finditer(text):
            if len(m.group(2)) > 2:
                hits.append(f"{path}: {m.group(0).strip()}")
        for m in _COORD_TUPLE.finditer(text):
            if len(m.group(2)) > 2 or len(m.group(4)) > 2:
                hits.append(f"{path}: {m.group(0).strip()}")
    assert not hits, (
        "Coördinaat met meer dan 2 decimalen — dat pint het adres i.p.v. de buurt:\n  "
        + "\n  ".join(hits))


def test_geen_station_ids_in_de_boom():
    """WU_STATION_ID/WU_NEIGHBOUR_IDS zijn secrets *omdat* een station-id de
    locatie verraadt. Alleen de env-naam mag in de repo staan, nooit een waarde."""
    # WU-station-ids hebben de vorm I<PLAATS><nummer>, bv. IUTRECH123. Sinds de
    # privacy-assessment (aug 2026) volstaat één cijfer — echte ids als IUTREC1
    # ontsnapten aan de oude \d{2,}-eis; testfixtures gebruiken daarom drie
    # letters (IGEH1), buiten deze vorm.
    pattern = re.compile(r"\bI[A-Z]{4,}\d+\b")
    hits = [f"{p}: {m}" for p in _tracked()
            for m in pattern.findall(_read(p))]
    assert not hits, "Mogelijk WU-station-id in de boom:\n  " + "\n  ".join(hits)


# De buurtnaam die de privacy-assessment (aug 2026) uit een broncommentaar viste:
# een benoemde buurt verkleint "Utrecht Oost" (~1 km-cel) tot een paar straten.
# Base64 om precies dezelfde reden als FORBIDDEN_NAMES hierboven — dit bestand
# mag niet zelf de laatste plek zijn waar de naam leesbaar staat. Groeit deze
# lijst? Kleine letters, base64 (zie het recept bij FORBIDDEN_NAMES).
FORBIDDEN_PLACES = tuple(base64.b64decode(b).decode() for b in (
    b"c2NoaWxkZXJzYnV1cnQ=",   # buurtnaam, scherper dan het gesanctioneerde "Utrecht Oost"
))


def test_geen_buurtnaam_in_de_boom():
    hits = []
    for path in _tracked():
        low = _read(path).lower()
        for name in FORBIDDEN_PLACES:
            if name in low:
                hits.append(f"{path}: {name!r}")
    assert not hits, (
        "Buurt-/straatnaam in een publiek bestand — scherper dan het gesanctioneerde "
        "gebiedsniveau (zie de PRIVACY-banner):\n  " + "\n  ".join(hits))


def test_geen_fijnmazige_afstanden():
    """Een afstand met een decimaal naar een vast, publiek bekend punt (bv. een
    KNMI-station) is een afstandsmeting van ±50 m — die maakt de bewuste
    2-decimalen-vergroving grotendeels ongedaan (een ring ∩ de coördinaat-cel).
    "ruim 4 km" zegt niets meer dan de publieke coördinaten zelf al impliceren;
    een waarde als "3,7 km" wél (bewust een verzonnen voorbeeld — de échte
    verwijderde waarde hier herhalen zou het lek reconstrueren). De
    (?![\\w/])-staart laat snelheden (km/h) met rust."""
    pattern = re.compile(r"\b\d+,\d+\s*km(?![\w/])")
    hits = []
    for path in _tracked(".py", ".js", ".html", ".yml", ".md"):
        for m in pattern.findall(_read(path)):
            hits.append(f"{path}: {m!r}")
    assert not hits, (
        "Afstand met één-decimaal-precisie in een publiek bestand:\n  " + "\n  ".join(hits))


# ── 3. Gedragsdata onder docs/ (Pages = publiek, ongeauthenticeerd) ─────────────

def _room_series_keys(obj, depth: int = 0) -> bool:
    """True als de JSON ergens een per-kamer meetreeks draagt.

    Signatuur: een dict-waarde met zowel een tijdreeks-achtige sleutel als een
    meetwaarde (`temp`/`hum`/`humidity`). Dat is de vorm die het dagritme van het
    huishouden tekent — zie window_data.json/twin2_history."""
    if depth > 6:
        return False
    if isinstance(obj, dict):
        keys = set(obj)
        if {"ts", "temp"} <= keys or {"history"} <= keys or {"hum", "temp"} <= keys:
            return True
        return any(_room_series_keys(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return any(_room_series_keys(v, depth + 1) for v in obj[:3])
    return False


def test_geen_kamer_meetreeksen_onder_docs():
    """Kamer-temperatuur/-vocht op kwartierresolutie is gedragsdata (een douche
    is een vochtpiek; een dag zonder pieken leest als afwezigheid) en hoort in
    de privé gist — zie de PRIVACY-banner. Sinds de privacy-assessment (aug
    2026) scant dit de HELE boom en niet alleen `docs/`: de twin2-shards onder
    `data/` waren precies zo'n reeks in gewone git-historie, terwijl de
    docstring van deze test ze al als schoolvoorbeeld noemde.

    Tijdelijke uitzondering: de nog gecommitte `data/twin2_history/`-maanden,
    tot de zelf-uitvoerende migratie (vent_io.migrate_history_shards, draait in
    de eerstvolgende kwartierrun mét secrets) ze naar de privé Gist verhuisd en
    verwijderd heeft — daarna deze carve-out weghalen (TODO)."""
    hits = []
    for path in _tracked(".json"):
        if path.startswith("data/twin2_history/"):
            continue
        try:
            data = json.loads(_read(path))
        except json.JSONDecodeError:
            continue
        if _room_series_keys(data):
            hits.append(path)
    assert not hits, (
        "Publiek artefact met een per-kamer meetreeks:\n  " + "\n  ".join(hits))


def test_twin2_shards_zijn_gitignored():
    """De preventieve helft van de shard-privatisering: nieuwe lokale terugval-
    shards mogen nooit terug in git (zelfde patroon als de artefact-tests)."""
    ignored = subprocess.run(["git", "-C", _ROOT, "check-ignore", "-q",
                              "data/twin2_history/2099-01.json"]).returncode == 0
    assert ignored, "data/twin2_history/*.json ontbreekt in .gitignore"


_PRIVATE_ARTEFACTS = (
    "docs/data.json", "docs/mowing_data.json", "docs/window_data.json",
    "docs/vent_data.json", "docs/vent_forecast.json", "docs/vent_learned.json",
    "mowing_state.json",
    # Privacy-assessment aug 2026: per-nacht kinderkamerscores tegen gemeten
    # temperaturen — naar de artefact-gist, nooit onder docs/.
    "docs/night_verify.json",
)


def test_geprivatiseerde_artefacten_zijn_niet_gecommit():
    """Deze bestanden leven in de artefact-gist. De lokale terugval mag bestaan
    (bootstrap/tests) maar nooit gevolgd worden — anders zet één `git add -A` ze
    terug in de publieke historie."""
    private = set(_PRIVATE_ARTEFACTS)
    tracked = set(_tracked())
    assert not (private & tracked), (
        "Privé artefact staat in git:\n  " + "\n  ".join(sorted(private & tracked)))


@pytest.mark.parametrize("path", _PRIVATE_ARTEFACTS)
def test_geprivatiseerde_artefacten_zijn_gitignored(path):
    """De preventieve helft van de test hierboven: de regel in `.gitignore`.

    Zonder die regel is de test hierboven pas ná de commit een signaal, en de
    commits die het zouden veroorzaken dragen `[skip ci]` — dan draait de suite
    er niet eens op. Genegeerd is `git add <pad>` een no-op (waarschuwing,
    exit 0), dus dit kost geen enkele werkende run."""
    ignored = subprocess.run(["git", "-C", _ROOT, "check-ignore", "-q", path]).returncode == 0
    assert ignored, f"{path} ontbreekt in .gitignore"


# ── 4. Gedateerde handmatige handelingen in gecommitte state ────────────────────

def test_geen_gedateerde_handmatige_actie_in_gecommitte_state():
    """Een veld dat de datum van een menselijke handeling draagt (maaien, sproeien)
    dateert die handeling twee keer: via de waarde én via de commit die 'm wijzigt.
    Een hash lost dat niet op — zulke state hoort in de privé-gist."""
    # `last_notification` hoort erbij sinds de privacy-assessment (aug 2026): het
    # dateerde in sandbox_state.json elk verstuurd bericht — geen handmatige
    # handeling, maar wél een gedateerd meldspoor in een publiek gecommit bestand.
    forbidden = ("last_seen_mow_date", "last_mow", "last_irrigation", "last_watering",
                 "last_notification")
    hits = []
    for path in _tracked(".json"):
        if path.startswith(("tests/", "data/", "docs/js/", "tools/golden/")):
            continue
        text = _read(path)
        hits += [f"{path}: {k}" for k in forbidden if f'"{k}"' in text]
    assert not hits, (
        "Gedateerde handmatige actie in gecommitte state:\n  " + "\n  ".join(hits))


# ── 5. Het huishoudritme ────────────────────────────────────────────────────────

def test_geen_weekrooster_in_de_broncode():
    """De tijdblokken van de weerbriefing zijn een 'wanneer is het huis leeg'-
    kalender en horen in het BRIEFING_BLOCKS-secret. De publieke boom mag alleen
    de generieke dagdelen dragen."""
    import weather_briefing as wb

    generic = {"ochtend", "middag", "avond", "nacht"}
    labels = {b[0].lower() for b in wb.DEFAULT_BLOCKS}
    assert labels <= generic, f"DEFAULT_BLOCKS draagt niet-generieke labels: {labels - generic}"

    # Woorden die een concrete bezigheid/afspraak benoemen i.p.v. een dagdeel.
    routine_words = ("kdv", "crèche", "creche", "kinderopvang", "opvang",
                     "kantoor", "office day", "sport", "fietstocht", "dutje",
                     "school", "werk ", "oppas")
    hits = [f"{p}: {w!r}" for p in ("weather_briefing.py",)
            for w in routine_words if w in _read(p).lower()]
    assert not hits, (
        "Concreet huishoudritme in de broncode — hoort in BRIEFING_BLOCKS:\n  "
        + "\n  ".join(hits))


def test_briefing_valt_terug_op_generieke_dagdelen(monkeypatch):
    """Zonder (of met een kapot) secret moet de briefing blijven werken én
    niets specifieks tonen — fail open, maar generiek."""
    import weather_briefing as wb

    monkeypatch.delenv("BRIEFING_BLOCKS", raising=False)
    week, weekend, days = wb.load_blocks()
    assert week == wb.DEFAULT_BLOCKS and weekend == wb.DEFAULT_BLOCKS
    assert days == wb.DEFAULT_WEEKEND_DAYS

    monkeypatch.setenv("BRIEFING_BLOCKS", "{niet eens json")
    assert wb.load_blocks()[0] == wb.DEFAULT_BLOCKS


def test_briefing_leest_het_secret_wel_als_het_klopt(monkeypatch):
    import weather_briefing as wb

    monkeypatch.setenv("BRIEFING_BLOCKS", json.dumps({
        "weekday": [["A", 6, 0, 7, 0, [1, 3], "x"]],
        "weekend": [["B", 9, 0, 11, 0, None, "y"]],
        "weekend_days": [5, 6],
    }))
    week, weekend, days = wb.load_blocks()
    assert week == [("A", 6, 0, 7, 0, {1, 3}, "x")]
    assert weekend == [("B", 9, 0, 11, 0, None, "y")]
    assert days == {5, 6}


# ── 6. Publieke sporen van een interactie ───────────────────────────────────────

def _strip_js_comments(text: str) -> str:
    """`//`- en `/* */`-commentaar eruit, zodat een regel die uitlegt waaróm iets
    weg is niet als de praktijk zelf wordt gelezen (de dashboards dragen precies
    zulke comments)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(^|\s)//[^\n]*", " ", text)


def test_dashboards_dispatchen_geen_workflows():
    """Een browser-getriggerde run is publiek zichtbaar in de Actions-lijst (actor
    + minuut) en dateert daarmee elke huiselijke interactie. De dashboards schrijven
    naar de Gist; de volgende geplande run pikt het vanzelf op."""
    hits = [p for p in _tracked(".js", ".html")
            if re.search(r"/actions/workflows/[^\"']*/dispatches|\bworkflow_dispatch\b",
                         _strip_js_comments(_read(p)))]
    assert not hits, (
        "Frontend dispatcht een workflow — dat dateert de interactie publiek:\n  "
        + "\n  ".join(hits))


def _all_workflows() -> list[str]:
    wf_dir = os.path.join(_ROOT, ".github", "workflows")
    return sorted(f for f in os.listdir(wf_dir) if f.endswith((".yml", ".yaml")))


@pytest.mark.parametrize("workflow", _all_workflows())
def test_workflows_echoën_geen_state(workflow):
    """Actions-logs zijn publiek en worden niet mee-herschreven door een history-
    rewrite. Geen `cat`/`echo` van een state- of artefactbestand in een run-step.

    Sinds de privacy-assessment (aug 2026) over álle workflows i.p.v. een
    handgeschreven viertal — dezelfde 'een lijst die moet groeien, groeit niet'-
    les als de zelf-skip-meta-test bovenaan dit bestand."""
    text = _read(os.path.join(".github", "workflows", workflow))
    bad = re.findall(r"^\s*(?:cat|echo)\s+[^|&\n]*\.json", text, re.MULTILINE)
    assert not bad, f"{workflow} dumpt een JSON-bestand naar het publieke log: {bad}"
