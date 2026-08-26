"""Project 16: Gardena bewatering-automaat.

Bestuurt de twee kranen (gras-sproeier + struiken-druppelslang) via de
GARDENA smart system API, op basis van het bestaande FAO-56-bodemmodel
(`docs/data.json`), en meet + registreert kraan-opentijd automatisch in het
irrigatielogboek (`irrigations.json` in de Gist) zodat de waterbalans klopt.

Draait elk uur (orchestrator-dispatch, constante cadans). Beslismomenten:
gras op de eerste run in [05:00, 09:00) lokaal, struiken op de eerste run in
[22:00, 24:00) — zelfde slot-semantiek als het bodemadvies (NOTIFY_AT in
check_and_notify.py), met het dag-geheugen in de Gist-state.

Registratieregels (bewonersbesluit):
  - kraan 2 (druppelslang) bewatert per definitie altijd de struiken → álle
    gemeten opentijd wordt geregistreerd, ook handmatige beurten via de app;
  - kraan 1 (sproeier) wordt ook voor andere dingen gebruikt → opentijd wordt
    alléén geregistreerd zolang de gazon-automaat aan staat; staat hij uit,
    dan logt de bewoner sproeibeurten zelf via de dashboard-modal (automatisch
    meeregistreren zou dan dubbel tellen).

Privacy-grens (bewonersbesluit, zie CLAUDE.md Project 16): de standen in
`garden_automation.json` en alle beslisinformatie zijn privé. Publieke
Actions-logs zijn daarom vormvast — de stdout van dit script codeert nooit
een beslissing, vlagstand, sessie of hoeveelheid; alle inhoud gaat via
Telegram naar de privé-chat en via de Gist naar het (token-gated) dashboard.
Fouten in de GARDENA/Gist-laag eindigen als exit 0 met een privé-alert: een
rode run zou de orchestrator elk kwartier laten herdispatchen (API-budget!)
en zichtbare foutclusters rond de beslismomenten leggen.

Benodigde env (GitHub Secrets): GARDENA_APP_KEY, GARDENA_APP_SECRET,
GIST_ID, GH_TOKEN (gist-scope), TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
Ontbreekt er iets → nette no-op (exit 0), zodat de uurlijkse cadans al
groen draait vóórdat de secrets bestaan.
"""

import contextlib
import functools
import io
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests

import artefact_io
import gardena_api as ga
from notify import run_guarded, sanitize_error, send_telegram
from shared_const import TZ, past_local_time, utc_now_iso
from soil_model import IRRIGATION_RATES as RATES

# ── Afstelbare constanten (domeinbeslissingen) ───────────────────────────────
LAWN_AT = (5, 0)          # beslisvenster gras: eerste run op of ná 05:00 …
LAWN_LATEST_H = 9         # … en vóór 09:00 (daarna is sproeien zonde van de dag)
SHRUBS_AT = (22, 0)       # beslisvenster struiken: [22:00, middernacht)
SHRUBS_END_H = 5          # druppelsessie eindigt uiterlijk 05:00 lokaal —
                          # nooit twee kranen tegelijk met het gras-venster
LAWN_MAX_MIN = 45         # max sproeisessie (één START-commando, < 5400 s)
MIN_SESSION_MIN = 5       # kleinere beurten zijn de kraan niet waard
MAX_CMD_SECONDS = 5400    # Irrigation Control-limiet per START-commando
CHUNK_MARGIN_S = 120      # tolerantie rond gecommandeerde eindtijden
WEEKLY_CAP_MM = {"lawn": 45.0, "shrubs": 40.0}   # noodrem tegen modelfouten
RECENT_KEEP_D = 14
FROST_SKIP_TMIN_C = 1.0   # geen druppelslang/sproeier de vorst in
MAX_DATA_AGE_H = 6.0      # docs/data.json ouder dan dit → geen beslissing
SHRUBS_DISPLAY_MAX_MIN = 7 * 60   # indicatieve cap voor het dashboard-"volgende"
SENSOR_STALE_H = 3
BATTERY_LOW_PCT = 15
ALERT_COOLDOWN_H = {"stuck_open": 6, "zero_delivery": 6, "schedule_active": 6,
                    "rate_limited": 6, "api_error": 6, "weekly_cap": 6,
                    "gateway_offline": 24, "sensor_stale": 24, "battery_low": 24}

# ── Gist-bestanden (één schrijver per bestand, zie CLAUDE.md Project 16) ─────
CONFIG_FILE = "gardena_config.json"        # schrijver: bootstrap (eenmalig)
FLAGS_FILE = "garden_automation.json"      # schrijver: browser (dashboard)
STATE_FILE = "gardena_state.json"          # schrijver: deze action
IRRIGATIONS_FILE = "irrigations.json"      # gedeeld met de dashboard-modal

# Sensor-archief: maand-shards, zelfde patroon als data/station_history.
HISTORY_DIR = os.getenv("GARDENA_HISTORY_DIR", "data/gardena_history")
SHARD_SCHEMA = 1
# Whitelist — alléén sensor- en sensorbatterij-velden komen in het publieke
# archief; nooit kraandata, ids of vlagstanden (test bewaakt dit).
# "light" is bij de privacy-assessment (aug 2026) geschrapt: het veld was in de
# praktijk altijd null, en zou zodra de sensor het wél rapporteert een directe
# buitenactiviteits-proxy in publieke git zetten.
SENSOR_FIELDS = ("soil_hum", "soil_temp", "amb_temp",
                 "battery", "battery_state", "rf")

DATA_PATH = os.getenv("SOIL_DATA_PATH", "docs/data.json")

ZONES = ("lawn", "shrubs")
OPEN_ACTIVITIES = ("MANUAL_WATERING", "SCHEDULED_WATERING")
ZONE_MSG = {"lawn": ("Gazon-automaat", "sproeier"),
            "shrubs": ("Druppel-automaat", "druppelslang")}

GIST_WRITE_DELAYS = (2, 4, 8, 16, 32)  # s — window_advisor-patroon


# ── Kleine helpers ───────────────────────────────────────────────────────────

def iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_ts(s):
    """ISO-string → aware UTC-datetime, of None bij elke onzin."""
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ceil60(seconds: float) -> int:
    return int(math.ceil(seconds / 60.0)) * 60


def _clamp(dt: datetime, lo: datetime, hi: datetime) -> datetime:
    return min(max(dt, lo), hi)


def minutes_until_local(hour: int, now: datetime) -> int:
    """Minuten (echte, DST-veilige seconden/60) tot de eerstvolgende lokale
    `hour`:00. Op de klokwissel-nachten is 22:00→05:00 dus echt 6 of 8 uur.
    Het verschil wordt bewust in UTC genomen: aware datetimes met hetzélfde
    tzinfo-object trekken elkaar wandklok-gewijs af en zouden de DST-sprong
    wegpoetsen."""
    local = now.astimezone(TZ)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    diff = target.astimezone(timezone.utc) - local.astimezone(timezone.utc)
    return int(diff.total_seconds() // 60)


def fmt_dur(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h}u{m:02d}" if m else f"{h} uur"


def send_private(text: str) -> bool:
    """Telegram naar de privé-chat, met de stdout van notify.py onderdrukt —
    de "[telegram] ✓ verzonden"-regel zou in de publieke Actions-log verraden
    dát er iets te melden viel (de logvorm moet constant blijven)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return send_telegram(text)


def notify(report, text: str) -> None:
    """Bericht versturen, of (DRY_RUN) verzamelen voor het testrapport."""
    if report is not None:
        report.append(text)
    else:
        send_private(text)


# ── Gist-I/O ─────────────────────────────────────────────────────────────────

def _gist_env():
    gist_id = os.environ["GIST_ID"]
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return gist_id, token


def read_gist_files(names) -> dict:
    """Eén GET voor de hele Gist; parse de gevraagde JSON-bestanden.
    Ontbrekend/corrupt bestand → None voor dat bestand. Raist bij netwerk-
    of HTTP-fouten (de aanroeper beslist)."""
    gist_id, token = _gist_env()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"https://api.github.com/gists/{gist_id}",
                     headers=headers, timeout=20)
    r.raise_for_status()
    files = r.json().get("files") or {}
    out = {}
    for name in names:
        content = (files.get(name) or {}).get("content")
        try:
            out[name] = json.loads(content) if content else None
        except json.JSONDecodeError:
            out[name] = None
    return out


def gist_write_files(files: dict) -> None:
    """Multi-file PATCH — atomair aan GitHub-zijde, zodat state + irrigaties
    samen landen of samen niet (voorkomt dubbel registreren na een halve
    schrijf). Zelfde vorm als window_advisor.gist_write_files."""
    gist_id, token = _gist_env()
    payload = {"files": {fn: {"content": content} for fn, content in files.items()}}
    r = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json=payload,
        timeout=20,
    )
    r.raise_for_status()


def persist_files(files: dict) -> bool:
    """PATCH met retry/backoff; bij definitief falen een privé-alert. Een
    verloren registratie zou de waterbalans stil scheeftrekken — de volgende
    run herleidt dezelfde intervallen opnieuw uit de ongewijzigde meter-state,
    dus falen is herstelbaar zolang het maar gemeld wordt."""
    last_err = None
    for delay in (0, *GIST_WRITE_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            gist_write_files(files)
            return True
        except Exception as e:
            last_err = e
    send_private("⚠️ Bewatering-automaat: kon de Gist-state niet opslaan — "
                 f"volgende run probeert opnieuw. Laatste fout: {sanitize_error(last_err)}")
    return False


# ── Bodemmodel-invoer (data.json, read-only) ─────────────────────────────────
# Sinds de privatisering (aug 2026) uit de artefact-gist (ARTEFACT_GIST_ID);
# het lokale pad blijft de test-/bootstrap-terugval. MAX_DATA_AGE_H bewaakt de
# versheid, precies zoals eerst bij de branch-tip-checkout.

def load_soil_data(now: datetime, path: str | None = None):
    """{"age_h", "status": {zone: lawn_status/shrubs_status}, "tmin"} of None."""
    data = artefact_io.read_json("data.json", path or DATA_PATH, default=None)
    if not isinstance(data, dict):
        return None
    gen = parse_ts(data.get("generated_at"))
    age_h = (now - gen).total_seconds() / 3600.0 if gen else None
    status = {"lawn": data.get("lawn_status"), "shrubs": data.get("shrubs_status")}
    tmins = [d.get("Tmin") for d in (data.get("days") or []) if d.get("forecast")][:2]
    tmins = [t for t in tmins if isinstance(t, (int, float))]
    return {"age_h": age_h, "status": status,
            "tmin": min(tmins) if tmins else None}


# ── Opentijd-meter ───────────────────────────────────────────────────────────
# Reconstrueert per kraan de voltooide open-intervallen uit opeenvolgende
# uurlijkse snapshots. De activity-timestamp van de kraan is leidend maar
# wordt altijd geklemd op [vorige check, nu] — blijkt hij onzin, dan degradeert
# de meting naar de vorige check i.p.v. naar garbage. Een kraan die op zowel
# de vorige als de huidige check dicht rapporteert, levert nooit een interval
# op — ook niet als de activity-ts intussen verschoof (zie de toelichting
# onderin `meter_step`): dat bleek in de praktijk een vals-positieve beurt te
# kunnen opleveren voor een kraan die nooit heeft opengestaan.

def meter_step(prev, cur_open: bool, cur_ts, cur_dur, now: datetime):
    """(nieuwe meter-entry, [voltooide (start, eind)-intervallen])."""
    completed = []

    def open_entry(since: datetime):
        return {"open": True, "since": iso(since),
                "cmd_s": int(cur_dur) if isinstance(cur_dur, (int, float)) else None,
                "ts": cur_ts.isoformat() if cur_ts else None, "checked": iso(now)}

    def closed_entry():
        return {"open": False, "since": None, "cmd_s": None,
                "ts": cur_ts.isoformat() if cur_ts else None, "checked": iso(now)}

    if not prev or not prev.get("checked"):
        # Eerste observatie ooit: een al openstaande kraan krijgt zijn eigen
        # activity-ts als start (mits recent), zonder terugwerkend interval.
        if cur_open:
            lo = now - timedelta(hours=24)
            since = cur_ts if (cur_ts and lo <= cur_ts <= now) else now
            return open_entry(since), completed
        return closed_entry(), completed

    prev_checked = parse_ts(prev.get("checked")) or (now - timedelta(hours=1))
    prev_ts = parse_ts(prev.get("ts"))
    changed_ts = cur_ts is not None and prev_ts is not None and cur_ts != prev_ts

    if prev.get("open"):
        p_since = parse_ts(prev.get("since")) or prev_checked
        p_dur = prev.get("cmd_s")
        expected_end = (p_since + timedelta(seconds=p_dur)
                        if isinstance(p_dur, (int, float)) and p_dur else None)
        if cur_open:
            if changed_ts:
                # Dicht én weer open binnen het gat (of een her-override die de
                # timestamp ververste): oude interval sluit op de gecommandeerde
                # eindtijd of het heropen-moment — wat het eerst kwam. Bij een
                # her-override vóór het verlopen sluiten de intervallen naadloos
                # aan (close == heropen-moment), dus de som blijft exact.
                candidates = [t for t in (expected_end, cur_ts) if t is not None]
                close = _clamp(min(candidates), p_since, now)
                completed.append((p_since, close))
                return open_entry(_clamp(cur_ts, prev_checked, now)), completed
            entry = open_entry(p_since)
            if entry["cmd_s"] is None and isinstance(p_dur, (int, float)):
                entry["cmd_s"] = int(p_dur)
            if entry["ts"] is None:
                entry["ts"] = prev.get("ts")
            return entry, completed
        # Dicht: exacte sluittijd als de activity-ts plausibel is; anders de
        # gecommandeerde eindtijd; anders de vorige check (bewuste ondertelling —
        # te weinig tellen laat het model "droger" denken en later bijwateren,
        # te veel tellen riskeert echte droogtestress).
        if cur_ts is not None and p_since <= cur_ts <= now:
            close = cur_ts
        elif expected_end is not None and p_since <= expected_end <= now:
            close = expected_end
        else:
            close = max(p_since, prev_checked)
        completed.append((p_since, close))
        return closed_entry(), completed

    if cur_open:
        since = _clamp(cur_ts, prev_checked, now) if cur_ts else \
            prev_checked + (now - prev_checked) / 2
        return open_entry(since), completed
    # Dicht bij de vorige én de huidige check: nooit een interval verzinnen,
    # ook niet als de activity-ts intussen verschoof. Die verschuiving werd
    # gelezen als bewijs van een volledig binnen het gat geopende-en-gesloten
    # beurt, maar de kraan kan op dezelfde manier dicht blijven terwijl de API
    # de timestamp om een andere reden bijwerkt — en dan verzint dit een
    # opentijd die nooit bestond. Bewuste ondertelling, zelfde afweging als
    # hierboven: een gemiste korte beurt kost een paar mm in de balans, een
    # verzonnen beurt is een registratie die nooit had mogen bestaan.
    return closed_entry(), completed


def register_intervals(zone: str, intervals, auto_lawn: bool):
    """Voltooide intervallen → registratie-entries volgens de bewonersregels.
    Kraan 1 buiten de automaat (speelbadje e.d.) valt hier geruisloos af."""
    entries = []
    for start, end in intervals:
        if zone == "lawn" and not auto_lawn:
            continue
        minutes = round((end - start).total_seconds() / 60)
        if minutes < 1:
            continue
        mm = round(minutes * RATES[zone], 1)
        if mm < 0.1:
            continue
        entries.append({"date": start.astimezone(TZ).date().isoformat(),
                        "min": int(minutes), "mm": mm,
                        "start": iso(start), "end": iso(end)})
    return entries


def merge_irrigation(irrigations: dict, zone: str, entry: dict) -> dict:
    """Additieve merge, byte-compatibel met de dashboard-modal
    (docs/js/index.js saveIrrigation): hele minuten, mm op 0,1 afgerond in
    _meta, en de hoofdsleutel als ongeronde som — automatische en handmatige
    registraties zijn zo niet van elkaar te onderscheiden."""
    key = f"{entry['date']}_{zone}"
    irrigations[key] = (irrigations.get(key) or 0) + entry["mm"]
    meta = irrigations.setdefault("_meta", {})
    prev = meta.get(entry["date"]) or {"minLawn": 0, "mmLawn": 0,
                                       "minShrubs": 0, "mmShrubs": 0}
    suffix = "Lawn" if zone == "lawn" else "Shrubs"
    prev["min" + suffix] = (prev.get("min" + suffix) or 0) + entry["min"]
    prev["mm" + suffix] = round((prev.get("mm" + suffix) or 0) + entry["mm"], 1)
    meta[entry["date"]] = prev
    return irrigations


# ── Beslissingen ─────────────────────────────────────────────────────────────

def slot_open(state: dict, zone: str, now_local: datetime) -> bool:
    """Zelfde semantiek als advice_slot_open in check_and_notify.py: de eerste
    run op of ná het doelmoment die vandaag nog niet besliste."""
    if (state.get("day") or {}).get(zone) == now_local.date().isoformat():
        return False
    if zone == "lawn":
        return (past_local_time(*LAWN_AT, now=now_local)
                and now_local.hour < LAWN_LATEST_H)
    # Struiken: [22:00, middernacht) — ná middernacht is past_local_time
    # vanzelf False, dus een lopende nachtsessie kan nooit opnieuw triggeren.
    return past_local_time(*SHRUBS_AT, now=now_local)


def plan_minutes(zone: str, proposal_min: int, now: datetime) -> int:
    if zone == "lawn":
        return min(proposal_min, LAWN_MAX_MIN)
    return min(proposal_min, minutes_until_local(SHRUBS_END_H, now))


def weekly_mm(recent, today) -> float:
    cutoff = (today - timedelta(days=6)).isoformat()
    return sum(e.get("mm") or 0 for e in (recent or [])
               if (e.get("date") or "") >= cutoff)


def decide_zone(zone: str, now: datetime, state: dict, flags: dict, soil,
                valve, session):
    """→ ("start", planned_min) | ("no", reden) | ("defer", reden) | None.

    "no" is een genomen beslissing en verbruikt het dagslot (een rustige
    05:00 mag niet om 14:00 alsnog een sproeier worden zodra de prioriteit
    omslaat — zelfde argument als het bodemadvies-slot). "defer" is een
    uitvoeringsblokkade (kraan bezet, data oud): slot blijft open zodat de
    volgende run binnen het venster het opnieuw probeert."""
    now_local = now.astimezone(TZ)
    if not slot_open(state, zone, now_local):
        return None
    if flags.get("paused"):
        return ("no", "gepauzeerd")
    if zone == "lawn" and not flags.get("auto_lawn"):
        return ("no", "automaat uit")
    if session is not None:
        return ("defer", "sessie actief")
    if valve is None or valve.get("activity") != "CLOSED":
        # Een openstaande kraan is van de bewoner (speelbadje, handmatige
        # beurt) — nooit kapen; volgende run in het venster probeert opnieuw.
        return ("defer", "kraan niet dicht")
    if soil is None or soil.get("age_h") is None or soil["age_h"] > MAX_DATA_AGE_H:
        return ("defer", "bodemdata veroudert")
    status = (soil.get("status") or {}).get(zone)
    if not status:
        return ("defer", "bodemdata veroudert")
    if status.get("priority") not in ("medium", "high"):
        return ("no", "bodem vochtig genoeg")
    planned = plan_minutes(zone, int(status.get("proposal_min") or 0), now)
    if planned < MIN_SESSION_MIN:
        return ("no", "te weinig nodig")
    tmin = soil.get("tmin")
    if tmin is not None and tmin <= FROST_SKIP_TMIN_C:
        return ("no", "vorstgrens")
    planned_mm = round(planned * RATES[zone], 1)
    if weekly_mm((state.get("recent") or {}).get(zone), now_local.date()) \
            + planned_mm > WEEKLY_CAP_MM[zone]:
        return ("no", "weeklimiet")
    return ("start", planned)


# ── Sessie-machine ───────────────────────────────────────────────────────────

def new_session(zone: str, planned_min: int, now: datetime, forced: bool = False):
    """(sessie-dict, seconden voor het eerste START-commando)."""
    chunk_s = min(planned_min * 60, MAX_CMD_SECONDS)
    return ({"zone": zone, "date": now.astimezone(TZ).date().isoformat(),
             "started_utc": iso(now),
             "target_end_utc": iso(now + timedelta(minutes=planned_min)),
             "chunk_end_utc": iso(now + timedelta(seconds=chunk_s)),
             "planned_min": planned_min,
             "planned_mm": round(planned_min * RATES[zone], 1),
             "chunks": 1, "forced": bool(forced)}, chunk_s)


def advance_session(session: dict, valve_open: bool, scheduled: bool,
                    now: datetime, paused: bool):
    """→ (actie, einde, sessie).

    actie: ("start", seconden) om de lopende sessie te verlengen (chunken —
    her-override vóór het verlopen, dus geen gaten), ("stop",) of None.
    einde: {"reason", "alert"?} zodra de sessie afloopt (sessie wordt None).
    De geregistreerde mm komen NIET hieruit maar uit de meter — dit stuurt
    alleen de kraan en de berichtgeving."""
    target_end = parse_ts(session.get("target_end_utc")) or now
    chunk_end = parse_ts(session.get("chunk_end_utc")) or now
    margin = timedelta(seconds=CHUNK_MARGIN_S)

    if valve_open:
        if scheduled:
            # Een app-schema nam de kraan over: niet tegenvechten, sessie los.
            return None, {"reason": "app-schema nam de kraan over",
                          "alert": "schedule_active"}, None
        if paused:
            return ("stop",), {"reason": "gepauzeerd"}, None
        if now >= target_end + margin:
            return ("stop",), {"reason": "niet vanzelf gesloten",
                               "alert": "stuck_open"}, None
        if chunk_end < target_end and now < target_end:
            seconds = min(ceil60((target_end - now).total_seconds()), MAX_CMD_SECONDS)
            if seconds >= 60:
                session = {**session,
                           "chunk_end_utc": iso(now + timedelta(seconds=seconds)),
                           "chunks": int(session.get("chunks") or 0) + 1}
                return ("start", seconds), None, session
        return None, None, session

    # Kraan dicht.
    if now >= chunk_end - margin:
        if chunk_end >= target_end - margin:
            return None, {"reason": "voltooid"}, None
        # Chunk verlopen vóór de doeltijd: een run is uitgevallen en de kraan
        # sloot zichzelf (de hardware-vangrail). Niet hervatten — het model
        # herbeslist morgen/vanavond gewoon opnieuw.
        return None, {"reason": "eerder afgesloten (run gemist)"}, None
    return None, {"reason": "eerder gestopt (via de app)"}, None


def session_overlaps(state: dict, zone: str, start: datetime, end: datetime) -> bool:
    """Hoort dit gemeten interval bij een (net) door ons gestuurde sessie?
    Dan dekt het sessie-stopbericht de melding en blijft de registratie stil."""
    margin = timedelta(minutes=90)
    windows = []
    session = state.get("session")
    if session and session.get("zone") == zone:
        s = parse_ts(session.get("started_utc"))
        if s:
            windows.append((s, parse_ts(session.get("target_end_utc"))))
    last = (state.get("last") or {}).get(zone) or {}
    s = parse_ts(last.get("started_utc"))
    if s:
        windows.append((s, parse_ts(last.get("ended_utc"))))
    for w_start, w_end in windows:
        w_end = (w_end or w_start) + margin
        if start < w_end and end > w_start - margin:
            return True
    return False


# ── Alerts (gededupliceerd via de Gist-state) ────────────────────────────────

def alert_due(state: dict, key: str, now: datetime) -> bool:
    stamp = parse_ts((state.get("alerts") or {}).get(key))
    if stamp and (now - stamp) < timedelta(hours=ALERT_COOLDOWN_H.get(key, 6)):
        return False
    state.setdefault("alerts", {})[key] = iso(now)
    return True


# ── Dashboard-informatie (privé, via de Gist-state) ──────────────────────────

def compute_next(zone: str, flags: dict, soil) -> dict:
    at = "±05:00" if zone == "lawn" else "22:00"
    out = {"at": at, "eligible": False}
    if flags.get("paused"):
        out["reason"] = "gepauzeerd"
        return out
    if zone == "lawn" and not flags.get("auto_lawn"):
        out["reason"] = "automaat uit"
        return out
    status = ((soil or {}).get("status") or {}).get(zone)
    if not status:
        out["reason"] = "geen bodemdata"
        return out
    if status.get("priority") not in ("medium", "high"):
        out["reason"] = "bodem vochtig genoeg"
        return out
    cap = LAWN_MAX_MIN if zone == "lawn" else SHRUBS_DISPLAY_MAX_MIN
    planned = min(int(status.get("proposal_min") or 0), cap)
    out.update({"eligible": True, "planned_min": planned,
                "planned_mm": round(planned * RATES[zone], 1)})
    return out


def build_health(snap: dict, config: dict, now: datetime) -> dict:
    health = {"checked_utc": iso(now), "valves": {}}
    for zone in ZONES:
        valve = (snap.get("valves") or {}).get((config.get("valves") or {}).get(zone))
        if valve:
            common = (snap.get("common") or {}).get(valve.get("device")) or {}
            health["valves"][zone] = {"state": valve.get("state"),
                                      "rf": common.get("rf"),
                                      "battery": common.get("battery")}
    sensor = (snap.get("sensors") or {}).get(config.get("sensor_id"))
    if sensor:
        common = (snap.get("common") or {}).get(sensor.get("device")) or {}
        health["sensor"] = {"t": sensor.get("soil_hum_ts") or sensor.get("soil_temp_ts"),
                            "soil_hum": sensor.get("soil_hum"),
                            "soil_temp": sensor.get("soil_temp"),
                            "battery": common.get("battery"),
                            "battery_state": common.get("battery_state"),
                            "rf": common.get("rf")}
    return health


# ── Sensor-archief (maand-shards, station_accuracy-patroon) ──────────────────

def sensor_row(snap: dict, config: dict):
    sensor = (snap.get("sensors") or {}).get(config.get("sensor_id"))
    if not sensor:
        return None
    t = parse_ts(sensor.get("soil_hum_ts") or sensor.get("soil_temp_ts"))
    if t is None:
        return None
    common = (snap.get("common") or {}).get(sensor.get("device")) or {}
    return {"t": iso(t),
            "soil_hum": sensor.get("soil_hum"),
            "soil_temp": sensor.get("soil_temp"),
            "amb_temp": sensor.get("amb_temp"),
            "battery": common.get("battery"),
            "battery_state": common.get("battery_state"),
            "rf": common.get("rf")}


def _shard_path(month: str) -> str:
    return os.path.join(HISTORY_DIR, f"{month}.json")


def load_shard(month: str) -> dict:
    try:
        with open(_shard_path(month), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"schema": SHARD_SCHEMA, "month": month,
                "source": "gardena smart sensor", "rows": []}


def append_sensor_rows(rows) -> tuple:
    """Idempotent op de sensor-timestamp `t` (de sensor meldt zich elke
    30–60 min, dus ≤1 verse rij per run); herhaalde observaties werken de
    bestaande rij bij i.p.v. te stapelen. Geeft (nieuw, bijgewerkt) terug."""
    by_month = {}
    fresh = updated = 0
    for r in rows:
        month = r["t"][:7]
        if month not in by_month:
            by_month[month] = load_shard(month)
        shard = by_month[month]
        index = {row["t"]: row for row in shard["rows"]}
        row = {"t": r["t"], **{k: r.get(k) for k in SENSOR_FIELDS}}
        if r["t"] in index:
            if index[r["t"]] != row:
                index[r["t"]].update(row)
                updated += 1
        else:
            shard["rows"].append(row)
            fresh += 1
    os.makedirs(HISTORY_DIR, exist_ok=True)
    for shard in by_month.values():
        shard["rows"].sort(key=lambda row: row["t"])
        with open(_shard_path(shard["month"]), "w", encoding="utf-8") as f:
            json.dump(shard, f, ensure_ascii=False, separators=(",", ":"))
    return fresh, updated


# ── Berichtteksten (privé-chat; neutrale bewoordingen) ───────────────────────

def start_message(zone: str, planned_min: int, planned_mm: float,
                  end_utc: str, forced: bool = False) -> str:
    name, device = ZONE_MSG[zone]
    end_local = parse_ts(end_utc).astimezone(TZ).strftime("%H:%M")
    prefix = "🤖🧪" if forced else "🤖💧"
    label = f"{name} (testsessie)" if forced else name
    return (f"{prefix} {label}: {device} gestart — {fmt_dur(planned_min)} "
            f"(≈{planned_mm} mm), klaar rond {end_local}.")


def stop_message(zone: str, reason: str, minutes: int, mm: float) -> str:
    name, device = ZONE_MSG[zone]
    if reason == "voltooid":
        head = f"🤖✅ {name}: {device} klaar"
    else:
        head = f"🤖⏹ {name}: {reason}"
    if minutes > 0:
        return f"{head} — {fmt_dur(minutes)} gelopen, {mm} mm geregistreerd."
    return f"{head} — registratie volgt zodra de kraan dicht gemeld is."


def registration_message(zone: str, entry: dict) -> str:
    _, device = ZONE_MSG[zone]
    return (f"📒 Geregistreerd: {device} {fmt_dur(entry['min'])} "
            f"(≈{entry['mm']} mm) op {entry['date']}.")


ALERT_TEXT = {
    "stuck_open": "⚠️ Bewatering-automaat: de kraan ({zone}) stond na de geplande "
                  "eindtijd nog open — STOP verstuurd. Controleer de app.",
    "zero_delivery": "⚠️ Bewatering-automaat: de kraan ({zone}) lijkt niet te zijn "
                     "opengegaan — geen water geregistreerd.",
    "schedule_active": "⚠️ Bewatering-automaat: er is een app-schema actief op een "
                       "kraan — zet schema's in de GARDENA-app uit (de automaat "
                       "hoort de enige bestuurder te zijn).",
    "weekly_cap": "⚠️ Bewatering-automaat: weeklimiet bereikt voor {zone} — "
                  "beurt overgeslagen. Controleer het model als dit onverwacht is.",
    "rate_limited": "⚠️ Bewatering-automaat: GARDENA-API-limiet geraakt (429) — "
                    "automaat pauzeert tot de limiet reset (~24u).",
    "api_error": "⚠️ Bewatering-automaat: GARDENA-API niet bereikbaar — "
                 "volgende run probeert opnieuw.",
    "gateway_offline": "⚠️ Bewatering-automaat: gateway/kraan offline (rf-link).",
    "sensor_stale": "⚠️ Bewatering-automaat: de bodemsensor heeft al uren niets "
                    "gemeld — batterij/bereik controleren.",
    "battery_low": "⚠️ Bewatering-automaat: batterij bijna leeg ({detail}).",
}


# ── Hoofdflow ────────────────────────────────────────────────────────────────

def ensure_state(state) -> dict:
    base = {"schema": 1, "session": None, "day": {}, "meter": {}, "last": {},
            "next": {}, "recent": {}, "alerts": {}, "health": {}}
    return {**base, **(state or {})}


def config_valid(config) -> bool:
    return bool(config and config.get("location_id")
                and (config.get("valves") or {}).get("lawn")
                and (config.get("valves") or {}).get("shrubs"))


def _exec_command(report, state, now, fn) -> bool:
    """Kraan-commando uitvoeren (of in DRY_RUN alleen rapporteren)."""
    if report is not None:
        return True
    try:
        fn()
        return True
    except Exception as e:
        if alert_due(state, "api_error", now):
            send_private(ALERT_TEXT["api_error"] + f"\n({sanitize_error(e)})")
        return False


def _run(now: datetime, app_key: str, app_secret: str, report) -> None:
    gist = read_gist_files((CONFIG_FILE, FLAGS_FILE, STATE_FILE))
    config = gist.get(CONFIG_FILE)
    flags = gist.get(FLAGS_FILE) or {}
    state = ensure_state(gist.get(STATE_FILE))
    if not config_valid(config):
        print("[gardena] configuratie onvolledig — geen actie")
        return

    soil = load_soil_data(now)
    today_iso = now.astimezone(TZ).date().isoformat()

    try:
        token = ga.mint_token(app_key, app_secret)
        doc = ga.fetch_location(token, app_key, config["location_id"])
    except Exception as e:
        key = ("rate_limited" if isinstance(e, ga.GardenaApiError)
               and e.status == 429 else "api_error")
        if alert_due(state, key, now):
            notify(report, ALERT_TEXT[key] + f"\n({sanitize_error(e)})")
        if report is None:
            persist_files({STATE_FILE: json.dumps(state, ensure_ascii=False, indent=1)})
        print("[gardena] api niet beschikbaar — volgende run probeert opnieuw")
        return

    snap = ga.parse_snapshot(doc)
    print("[gardena] snapshot verwerkt")

    # 1. Meter: opentijd per kraan bijwerken en voltooide intervallen innen.
    pending = []          # (zone, entry) → irrigations.json-merge aan het eind
    metered_min = {z: 0 for z in ZONES}
    scheduled_seen = False
    valve_state = {}
    for zone in ZONES:
        valve = (snap.get("valves") or {}).get((config.get("valves") or {}).get(zone))
        activity = (valve or {}).get("activity")
        cur_open = activity in OPEN_ACTIVITIES
        scheduled_seen = scheduled_seen or activity == "SCHEDULED_WATERING"
        valve_state[zone] = {"valve": valve, "open": cur_open,
                             "scheduled": activity == "SCHEDULED_WATERING"}
        entry, completed = meter_step(
            (state.get("meter") or {}).get(zone), cur_open,
            parse_ts((valve or {}).get("activity_ts")),
            (valve or {}).get("duration_s"), now)
        state.setdefault("meter", {})[zone] = entry
        for reg in register_intervals(zone, completed, bool(flags.get("auto_lawn"))):
            pending.append((zone, reg))
            metered_min[zone] += reg["min"]
            recent = state.setdefault("recent", {}).setdefault(zone, [])
            recent.append({"date": reg["date"], "mm": reg["mm"]})
            if not session_overlaps(state, zone, parse_ts(reg["start"]),
                                    parse_ts(reg["end"])):
                notify(report, registration_message(zone, reg))
    cutoff = (now.astimezone(TZ).date() - timedelta(days=RECENT_KEEP_D)).isoformat()
    for zone in ZONES:
        recent = (state.get("recent") or {}).get(zone)
        if recent:
            state["recent"][zone] = [e for e in recent if (e.get("date") or "") >= cutoff]

    # 2. Lopende sessie voortzetten/afronden.
    session = state.get("session")
    if session and session.get("zone") in ZONES:
        zone = session["zone"]
        vs = valve_state[zone]
        action, end, session_next = advance_session(
            session, vs["open"], vs["scheduled"], now, bool(flags.get("paused")))
        if action:
            valve_id = config["valves"][zone]
            if action[0] == "start":
                if _exec_command(report, state, now, functools.partial(
                        ga.start_valve, token, app_key, valve_id, action[1])):
                    state["session"] = session_next
                # Mislukt de verlenging, dan sluit de kraan op de lopende chunk —
                # de vangrail; sessie laten staan zodat het einde netjes meldt.
            else:
                _exec_command(report, state, now, functools.partial(
                    ga.stop_valve, token, app_key, valve_id))
        if end:
            started = parse_ts(session.get("started_utc")) or now
            state["last"][zone] = {"date": session.get("date"),
                                   "started_utc": session.get("started_utc"),
                                   "ended_utc": iso(now),
                                   "reason": end["reason"],
                                   "planned_mm": session.get("planned_mm")}
            state["session"] = None
            if end.get("alert") and alert_due(state, end["alert"], now):
                notify(report, ALERT_TEXT[end["alert"]].format(zone=ZONE_MSG[zone][0]))
            ran_min = metered_min[zone]
            ran_mm = round(sum(e["mm"] for z, e in pending if z == zone), 1)
            # Zero-delivery alleen bij een dicht-waargenomen einde: bij een
            # pauze-/stuck-stop staat de kraan nu nog open en int de meter het
            # interval pas volgende run — dat is geen mislukte start.
            closed_end = end["reason"] in ("voltooid", "eerder afgesloten (run gemist)",
                                           "eerder gestopt (via de app)")
            if (ran_min == 0 and closed_end and not end.get("alert")
                    and (now - started) > timedelta(minutes=10)
                    and alert_due(state, "zero_delivery", now)):
                notify(report, ALERT_TEXT["zero_delivery"].format(zone=ZONE_MSG[zone][0]))
            else:
                notify(report, stop_message(zone, end["reason"], ran_min, ran_mm))
        elif action is None and state.get("session") is not None:
            state["session"] = session_next or session

    # 3. Nieuwe beslissingen (gras 05:00-venster, struiken 22:00-venster).
    for zone in ZONES:
        decision = decide_zone(zone, now, state, flags, soil,
                               valve_state[zone]["valve"], state.get("session"))
        if decision is None or decision[0] == "defer":
            continue
        if decision[0] == "no":
            state["day"][zone] = today_iso
            if decision[1] == "weeklimiet" and alert_due(state, "weekly_cap", now):
                notify(report, ALERT_TEXT["weekly_cap"].format(zone=ZONE_MSG[zone][0]))
            continue
        planned_min = decision[1]
        session_new, chunk_s = new_session(zone, planned_min, now)
        if _exec_command(report, state, now, functools.partial(
                ga.start_valve, token, app_key, config["valves"][zone], chunk_s)):
            state["session"] = session_new
            state["day"][zone] = today_iso
            notify(report, start_message(zone, planned_min,
                                         session_new["planned_mm"],
                                         session_new["target_end_utc"]))
        # START mislukt → slot niet verbruiken; volgende run in het venster
        # probeert opnieuw.

    # 3b. Handmatige testsessie via workflow_dispatch (verbruikt geen dagslot).
    force_zone = os.environ.get("FORCE_ZONE") or ""
    if (force_zone in ZONES and state.get("session") is None
            and (valve_state[force_zone]["valve"] or {}).get("activity") == "CLOSED"):
        try:
            force_min = max(1, int(os.environ.get("FORCE_MINUTES") or 2))
        except ValueError:
            force_min = 2
        session_new, chunk_s = new_session(force_zone, force_min, now, forced=True)
        if _exec_command(report, state, now, functools.partial(
                ga.start_valve, token, app_key, config["valves"][force_zone], chunk_s)):
            state["session"] = session_new
            notify(report, start_message(force_zone, force_min,
                                         session_new["planned_mm"],
                                         session_new["target_end_utc"], forced=True))

    # 4. Gezondheid + alerts.
    state["health"] = build_health(snap, config, now)
    if scheduled_seen and alert_due(state, "schedule_active", now):
        notify(report, ALERT_TEXT["schedule_active"])
    sensor = state["health"].get("sensor") or {}
    sensor_t = parse_ts(sensor.get("t"))
    if sensor and sensor_t and (now - sensor_t) > timedelta(hours=SENSOR_STALE_H) \
            and alert_due(state, "sensor_stale", now):
        notify(report, ALERT_TEXT["sensor_stale"])
    lows = [f"sensor {sensor.get('battery')}%"] if isinstance(sensor.get("battery"), (int, float)) \
        and sensor.get("battery") < BATTERY_LOW_PCT else []
    for zone, v in (state["health"].get("valves") or {}).items():
        if isinstance(v.get("battery"), (int, float)) and v["battery"] < BATTERY_LOW_PCT:
            lows.append(f"{ZONE_MSG[zone][1]} {v['battery']}%")
        if v.get("rf") == "OFFLINE" and alert_due(state, "gateway_offline", now):
            notify(report, ALERT_TEXT["gateway_offline"])
    if lows and alert_due(state, "battery_low", now):
        notify(report, ALERT_TEXT["battery_low"].format(detail=", ".join(lows)))

    # 5. Sensor-archief (publieke shards — alleen de gewhiteliste sensorvelden).
    row = sensor_row(snap, config)
    if row and report is None:
        append_sensor_rows([row])
    print("[gardena] archief bijgewerkt")

    # 6. Dashboard-info + één atomaire Gist-PATCH (state + evt. registraties).
    state["next"] = {zone: compute_next(zone, flags, soil) for zone in ZONES}
    state["last_updated"] = utc_now_iso()
    if report is None:
        files = {STATE_FILE: json.dumps(state, ensure_ascii=False, indent=1)}
        if pending:
            # Verse read vlak vóór de merge: de modal kan intussen handmatige
            # beurten hebben toegevoegd en de merge is additief.
            irr = read_gist_files((IRRIGATIONS_FILE,)).get(IRRIGATIONS_FILE) or {}
            for zone, entry in pending:
                merge_irrigation(irr, zone, entry)
            files[IRRIGATIONS_FILE] = json.dumps(irr, indent=2)
        persist_files(files)
    print("[gardena] state opgeslagen")


def main():
    print("[gardena] run gestart")
    now = datetime.now(timezone.utc)
    report = [] if os.environ.get("DRY_RUN") == "1" else None

    app_key = os.environ.get("GARDENA_APP_KEY")
    app_secret = os.environ.get("GARDENA_APP_SECRET")
    if not (app_key and app_secret and os.environ.get("GIST_ID")
            and (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))):
        print("[gardena] configuratie onvolledig — geen actie")
        return

    try:
        _run(now, app_key, app_secret, report)
    except Exception as e:
        # Exit 0, met privé-alert: een rode run zou de orchestrator elk
        # kwartier laten herdispatchen (API-budget) en foutclusters in de
        # publieke run-historie leggen. De volgende uurlijkse run herstelt.
        send_private("⚠️ Bewatering-automaat: run niet afgerond — "
                     f"{sanitize_error(e)}")
        print("[gardena] run niet afgerond — volgende run probeert opnieuw")
        return

    if report is not None:
        send_private("🧪 Testrun bewatering-automaat:\n"
                     + ("\n".join(report) if report else "geen acties"))
    print("[gardena] klaar")


if __name__ == "__main__":
    run_guarded(main, "Gardena besturing")
