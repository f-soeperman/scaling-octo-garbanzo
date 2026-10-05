"""Zindelijkheidstraining — plas-herinnering naar de groep (Project 17).

De browser (`docs/potje.html`) schrijft elke registratie naar `potty_log.json`
in de privé `GIST_ID`-gist. Deze runner draait in een eigen loop elke 5 minuten
(`.github/workflows/potty-reminder.yml`), leest het logboek en stuurt een
Telegram-bericht naar de groep zodra het tijd is om te laten proberen:

- **90 min** na het laatste plasje (wc, potje óf ongelukje);
- **30 min** na een poging die niets opleverde ("geprobeerd");
- **één herhaling** 30 min na een herinnering waar nog niets op volgde.

Komt er ná een herinnering een plasje of poging binnen, dan krijgt dat
bericht achteraf een vinkje (`editMessageText`: "✅" + wie-wat-wanneer eronder)
— zo ziet de rest van de groep dat het al geregeld is, zonder extra bericht.

Alleen tussen `DAY_START_H` (07:00) en `DAY_END_H` (19:00) — daarbuiten slaapt
hij — en alleen op basis van registraties van vandaag: de eerste herinnering
van de ochtend komt dus pas na de eerste registratie. Een herinnering die meer
dan `STALE_MIN` te laat zou komen (loop lag stil, of het moment viel in de
nacht) vervalt stil i.p.v. alsnog uit te gaan.

Privacy (zie de banner in CLAUDE.md): een plas-/poeplogboek met tijdstempels
is gedragsdata van het huishouden. Daarom:
- logboek én herinneringslog leven in de privé Gist, nooit in git of `docs/`;
- de cadans is constant (loop elke 5 min, ook 's nachts) en de stdout is
  vormvast: hij print nooit óf er een herinnering uitging (de
  "[telegram] ✓ verzonden"-regel wordt onderdrukt, het gardena-patroon);
- een schrijffout ná een send-beslissing gaat als privé-alert weg i.p.v. als
  FATAL in het publieke log — anders verraadt de fout dát er iets te melden viel.

`potty_state.json` (schrijver: uitsluitend deze action) houdt de verstuurde
herinneringen bij; het dashboard leest 'm voor de "werkt de herinnering?"-
analyse. `DRY_RUN=1` rekent door, schrijft niets en meldt een eventuele
herinnering met `[dry-run]`-prefix in de privé-chat (niet naar stdout).
"""

import contextlib
import html
import io
import json
import os
from datetime import datetime, timedelta

import gist_io
from notify import edit_telegram, run_guarded, sanitize_error, send_telegram_message
from shared_const import TZ

LOG_FILE = "potty_log.json"
STATE_FILE = "potty_state.json"

# ── Tunables (gespiegeld in docs/js/potje.js — een test bewaakt dat) ─────────
INTERVAL_PEE_MIN = 90      # na een plasje (wc/potje/ongelukje)
INTERVAL_TRY_MIN = 30      # na een poging zonder resultaat
INTERVAL_REPEAT_MIN = 30   # herhaling na een onbeantwoorde herinnering
MAX_REMINDERS_PER_ANCHOR = 2   # eerste herinnering + één herhaling
DAY_START_H = 7            # vanaf 07:00 wakker
DAY_END_H = 19             # vanaf 19:00 slaapt hij — geen herinneringen
STALE_MIN = 60             # te laat → vervalt i.p.v. alsnog sturen
MAX_REMINDER_LOG = 1500    # ~2 jaar aan herinneringen in de state

KINDS = ("plas", "poep")
WHERES = ("wc", "potje", "ongeluk", "geprobeerd")


# ── Logboek ──────────────────────────────────────────────────────────────────

def parse_events(log) -> list[dict]:
    """Geldige events uit `potty_log.json`, met een tz-bewuste `dt` erbij.
    Kapotte of onbekende regels vallen stil weg (de browser is de schrijver;
    één rare regel mag de herinneringen niet stilleggen)."""
    raw = log.get("events") if isinstance(log, dict) else None
    out = []
    for e in raw or []:
        if not isinstance(e, dict):
            continue
        if e.get("kind") not in KINDS or e.get("where") not in WHERES:
            continue
        try:
            dt = datetime.fromisoformat(str(e.get("t")))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        out.append({**e, "dt": dt})
    return out


def anchor_key(event: dict) -> str:
    return str(event.get("id") or event.get("t"))


# ── Beslissing ───────────────────────────────────────────────────────────────

def in_day_window(now: datetime) -> bool:
    return DAY_START_H <= now.astimezone(TZ).hour < DAY_END_H


def next_reminder(events: list[dict], state: dict, now: datetime) -> dict | None:
    """Het eerstvolgende herinneringsmoment, of None.

    Anker = de laatste plas-registratie van vandaag (lokale datum) die niet in
    de toekomst ligt — een echt plasje of een poging. Per anker hooguit
    `MAX_REMINDERS_PER_ANCHOR` herinneringen. Geeft `{due, kind, anchor}`."""
    local_now = now.astimezone(TZ)
    today = local_now.date()
    pees = [e for e in events
            if e["kind"] == "plas" and e["dt"] <= now
            and e["dt"].astimezone(TZ).date() == today]
    if not pees:
        return None
    # max() geeft bij gelijke tijd de eerste — de láátst ingevoerde wint.
    anchor = max(reversed(pees), key=lambda e: e["dt"])
    key = anchor_key(anchor)
    sent = [r for r in (state.get("reminders") or [])
            if isinstance(r, dict) and r.get("anchor") == key]
    if len(sent) >= MAX_REMINDERS_PER_ANCHOR:
        return None
    if sent:
        try:
            last = datetime.fromisoformat(str(sent[-1].get("t")))
        except ValueError:
            return None
        return {"due": last + timedelta(minutes=INTERVAL_REPEAT_MIN),
                "kind": "herhaal", "anchor": anchor}
    if anchor["where"] == "geprobeerd":
        return {"due": anchor["dt"] + timedelta(minutes=INTERVAL_TRY_MIN),
                "kind": "poging", "anchor": anchor}
    return {"due": anchor["dt"] + timedelta(minutes=INTERVAL_PEE_MIN),
            "kind": "plas", "anchor": anchor}


def should_send(nxt: dict | None, now: datetime) -> bool:
    if nxt is None or not in_day_window(now):
        return False
    late = now - nxt["due"]
    return timedelta(0) <= late <= timedelta(minutes=STALE_MIN)


def decide(events: list[dict], state: dict, now: datetime) -> dict | None:
    nxt = next_reminder(events, state, now)
    return nxt if should_send(nxt, now) else None


def _hhmm(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%H:%M")


def build_message(decision: dict, state: dict, now: datetime) -> str:
    anchor = decision["anchor"]
    if decision["kind"] == "herhaal":
        sent = [r for r in state.get("reminders") or []
                if r.get("anchor") == anchor_key(anchor)]
        when = _hhmm(datetime.fromisoformat(sent[-1]["t"])) if sent else "eerder"
        return ("🚽 <b>Nog even proberen?</b>\n"
                f"Sinds de herinnering van {when} is er niets geregistreerd — "
                "tijd om te laten plassen.")
    if decision["kind"] == "poging":
        return ("🚽 <b>Nieuwe poging?</b>\n"
                f"De poging van {_hhmm(anchor['dt'])} leverde niets op — "
                "probeer het nu nog een keer.")
    mins = int((now - anchor["dt"]).total_seconds() // 60)
    where = {"wc": "op de wc", "potje": "op het potje",
             "ongeluk": "een ongelukje"}.get(anchor["where"], "")
    return ("🚽 <b>Tijd om te plassen!</b>\n"
            f"Het laatste plasje was om {_hhmm(anchor['dt'])} ({where}, "
            f"{mins} min geleden) — even laten proberen.")


def record_reminder(state: dict, decision: dict, now: datetime) -> dict:
    """Nieuwe state met de herinnering erbij (niet-muterend). De berichttekst
    van eerdere dagen valt weg — die is alleen nodig om vandaag af te vinken."""
    today = now.astimezone(TZ).date()
    reminders = [r if _is_today(r, today) else {k: v for k, v in r.items() if k != "text"}
                 for r in state.get("reminders") or [] if isinstance(r, dict)]
    reminders.append({"t": now.astimezone(TZ).isoformat(timespec="seconds"),
                      "anchor": anchor_key(decision["anchor"]),
                      "kind": decision["kind"]})
    return {**state, "reminders": reminders[-MAX_REMINDER_LOG:]}


def attach_message(state: dict, message_id: int, text: str) -> dict:
    """Koppel het verstuurde bericht aan de laatste herinnering (niet-muterend),
    zodat `pending_acks` het later kan afvinken."""
    reminders = [dict(r) for r in state.get("reminders") or [] if isinstance(r, dict)]
    if reminders:
        reminders[-1].update({"msg_id": message_id, "text": text})
    return {**state, "reminders": reminders}


# ── Afvinken ─────────────────────────────────────────────────────────────────

ACK_WHERE = {"wc": "op de wc", "potje": "op het potje",
             "ongeluk": "ongelukje", "geprobeerd": "poging"}


def _is_today(reminder: dict, today) -> bool:
    try:
        return datetime.fromisoformat(str(reminder.get("t"))).astimezone(TZ).date() == today
    except ValueError:
        return False


def pending_acks(events: list[dict], state: dict, now: datetime) -> list[tuple[int, dict]]:
    """(index in `reminders`, plas-event) voor elk nog niet afgevinkt bericht van
    vandaag waarná een plasje of poging is geregistreerd. Een herhaling en de
    herinnering ervóór vinken dus samen af op dezelfde registratie."""
    today = now.astimezone(TZ).date()
    pees = sorted((e for e in events if e["kind"] == "plas" and e["dt"] <= now),
                  key=lambda e: e["dt"])
    out = []
    for i, r in enumerate(state.get("reminders") or []):
        if (not isinstance(r, dict) or r.get("acked") or not r.get("msg_id")
                or not r.get("text") or not _is_today(r, today)):
            continue
        sent_at = datetime.fromisoformat(str(r["t"]))
        hit = next((e for e in pees if e["dt"] > sent_at), None)
        if hit is not None:
            out.append((i, hit))
    return out


def ack_text(text: str, event: dict) -> str:
    return (f"✅ {text}\n<i>Geregistreerd om {_hhmm(event['dt'])} "
            f"({ACK_WHERE.get(event['where'], event['where'])}).</i>")


def mark_acked(state: dict, done: list[tuple[int, dict]]) -> dict:
    """Niet-muterend: afgevinkte herinneringen krijgen `acked` (tijd van de
    registratie) en verliezen hun `text`."""
    reminders = [dict(r) if isinstance(r, dict) else r for r in state.get("reminders") or []]
    for i, e in done:
        reminders[i].pop("text", None)
        reminders[i]["acked"] = e["dt"].astimezone(TZ).isoformat(timespec="seconds")
    return {**state, "reminders": reminders}


# ── I/O ──────────────────────────────────────────────────────────────────────

def _quiet_send(text: str, chat_id: str | None, muted: bool) -> int | bool:
    """Telegram met onderdrukte stdout — de verzonden-regel zou in het publieke
    log verraden dát er een herinnering uitging (vormvaste log, gardena-patroon).
    Geeft de message_id terug bij een echte verzending (zie notify)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return send_telegram_message(text, chat_id=chat_id, muted_in_quiet=muted)


def _loads(content: str | None) -> dict:
    if not content:
        return {}
    try:
        val = json.loads(content)
    except ValueError:
        return {}
    return val if isinstance(val, dict) else {}


def run(now: datetime | None = None) -> None:
    gist_id = os.getenv("GIST_ID")
    token = os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN")
    dry = os.getenv("DRY_RUN") == "1"
    now = now or datetime.now(TZ)
    if gist_id:
        files = gist_io.read_files(gist_id, token=token)
        events = parse_events(_loads(files.get(LOG_FILE)))
        state = _loads(files.get(STATE_FILE))
        if not dry:
            state = _ack(gist_id, token, events, state, now)
        decision = decide(events, state, now)
        if decision is not None:
            text = build_message(decision, state, now)
            if dry:
                _quiet_send("[dry-run] " + text, None, muted=False)
            else:
                _act(gist_id, token, state, decision, text, now)
    print("potje: controle klaar")


def _act(gist_id, token, state, decision, text, now) -> None:
    """Eerst de state, dan het bericht: een kapotte Gist-schrijf mag niet elke
    5 minuten hetzelfde bericht opleveren. Fouten → privé-alert, niet raisen
    (een FATAL alleen op send-iteraties is zelf een publiek signaal)."""
    try:
        new_state = record_reminder(state, decision, now)
        gist_io.write_files(gist_id, {STATE_FILE: _dump(new_state)}, token=token)
    except Exception as e:
        _quiet_send(f"⚠ <b>Potje-herinnering</b>: state niet opgeslagen, "
                    f"herinnering overgeslagen.\n<code>{html.escape(sanitize_error(e))}</code>",
                    None, muted=False)
        return
    group = os.getenv("TELEGRAM_CHAT_GROUP_ID")
    if not group:   # geen stille terugval naar de privé-chat (zelfde keuze als het dagplan)
        return
    mid = _quiet_send(text, group, muted=True)
    if type(mid) is int:   # bool is ook een int: alleen een échte message_id
        # Mislukt dit, dan krijgt alleen dit bericht later geen vinkje.
        with contextlib.suppress(Exception):
            gist_io.write_files(gist_id, {STATE_FILE: _dump(attach_message(new_state, mid, text))},
                                token=token)


def _ack(gist_id, token, events, state, now) -> dict:
    """Vink herinneringen af waar inmiddels een registratie op volgde. Raist
    nooit en print niets: een fout hier zou in het publieke log dateren dát er
    vandaag geregistreerd is. Een mislukte edit (netwerk) probeert de volgende
    iteratie opnieuw; een bericht dat niet meer te bewerken is telt als klaar."""
    group = os.getenv("TELEGRAM_CHAT_GROUP_ID")
    try:
        todo = pending_acks(events, state, now)
        if not group or not todo:
            return state
        done = []
        for i, e in todo:
            r = state["reminders"][i]
            with contextlib.redirect_stdout(io.StringIO()):
                status = edit_telegram(group, r["msg_id"], ack_text(r["text"], e))
            if status != "retry":
                done.append((i, e))
        if not done:
            return state
        new_state = mark_acked(state, done)
        gist_io.write_files(gist_id, {STATE_FILE: _dump(new_state)}, token=token)
        return new_state
    except Exception:
        return state


def _dump(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, indent=1)


def main():
    run()


if __name__ == "__main__":
    # fail_threshold=6: de loop draait elke 5 min, een Gist-hikje mag niet pagen.
    run_guarded(main, "Potje-herinnering", fail_threshold=6)
