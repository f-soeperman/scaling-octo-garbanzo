"""
Daily check & notify script.

Runs in GitHub Actions every morning. Doet:
  1. Haalt WU + Open-Meteo data
  2. Haalt irrigatie-log uit GitHub Gist
  3. Rekent soil water balance uit voor lawn + shrubs
  4. Als water geven nodig → stuurt Telegram
  5. Schrijft verse data.json terug (voor de GitHub Pages dashboard)

Benodigde env vars (in GitHub Secrets):
  WU_STATION_ID, WU_API_KEY
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID      (optioneel)
  GIST_ID, GITHUB_TOKEN                     (voor irrigatie-log)
"""

import json
import os
from datetime import date, timedelta

import artefact_io
from gist_io import read_json as gist_read_json
from notify import run_guarded, sanitize_error, send_telegram
from shared_const import (format_date_nl, local_today, past_local_time,
                          utc_now_iso)
from soil_model import (SOIL_FC, SOIL_WP, apply_et0_and_balance, assess_status,
                        build_full_dataset, build_monthly_totals_from_days,
                        fetch_open_meteo_archive)

# =============================================================================
# Meldmoment — de run draait vaker dan hij meldt.
#
# Sinds aug 2026 vuurt de orchestrator deze workflow ELK UUR af, zodat het
# dashboard meebeweegt met de dag: de regen die vanochtend viel, de ET0 die
# tot nu toe verdampte (`partial_factor`), een verse forecast en een zojuist
# gelogde beurt water. Het dagelijkse advies-bericht hoort daar niet in mee
# te schalen — dat zou 24 Telegrams per dag zijn.
#
# Het advies wordt daarom één keer per dag bepaald: op de eerste run op of ná
# NOTIFY_AT, en daarna niet meer die dag — ook niet als de prioriteit later op
# de dag alsnog omslaat (dan is het bericht van morgenochtend vroeg genoeg;
# het dashboard toont de omslag meteen). Dat is bewust "op of ná" en niet "om
# precies 06:00": valt de run van 06:00 uit, dan stuurt die van 07:00 het
# bericht alsnog i.p.v. de dag over te slaan. Zelfde semantiek als het dagplan
# van de raam-adviseur (`PLAN_HOUR`).
NOTIFY_AT = (6, 0)  # 06:00 Europe/Amsterdam
STATE_FILE = os.getenv("SOIL_STATE_FILE", "soil_state.json")

# =============================================================================

def load_existing_monthly_totals() -> dict:
    """Laad bestaande maandtotalen uit data.json (koude opslag) — sinds de
    privatisering (aug 2026) uit de artefact-gist, met het lokale pad als
    bootstrap-/test-terugval. Dit pad missen zou élke uurlijkse run de
    13-maands archief-bootstrap laten draaien."""
    prev = artefact_io.read_json("data.json", "docs/data.json", default={}) or {}
    return prev.get("monthly_totals", {})


def load_previous_theta() -> dict:
    """Laad de laatst-geregistreerde θ per zone uit docs/data.json zodat de
    volgende run niet vanaf de generieke 30%-uitputting hoeft te starten.

    Geeft een dict zoals {"lawn": 0.14, "shrubs": 0.16} terug, of {} als
    er geen vorige run is. We accepteren elke datum: de vorige run heeft
    35 dagen warmup verteerd, dus de "as_of" hoeft niet aan te sluiten
    op de eerste dag van de nieuwe run — het is een betere prior dan de
    statische 30%-uitputting.
    """
    prev = artefact_io.read_json("data.json", "docs/data.json", default=None)
    if not isinstance(prev, dict):
        return {}
    te = prev.get("theta_end") or {}
    seed = {k: te[k] for k in ("lawn", "shrubs") if te.get(k) is not None}
    # Een corrupte/handmatig bewerkte data.json mag de waterbalans niet met
    # een onmogelijke θ seeden — clamp naar het fysieke bereik [WP, FC].
    for k, v in seed.items():
        if not isinstance(v, (int, float)) or not (SOIL_WP <= v <= SOIL_FC):
            clamped = min(SOIL_FC, max(SOIL_WP, v)) if isinstance(v, (int, float)) else None
            print(f"[seed] ongeldige θ voor {k}: {v!r} → {clamped if clamped is not None else 'genegeerd'}")
            seed[k] = clamped
    seed = {k: v for k, v in seed.items() if v is not None}
    if seed:
        print(f"[seed] vorige θ geladen (as of {te.get('as_of')})")
    return seed


def load_state() -> dict:
    """Meld-bookkeeping (spiegelt sandbox_state.json / mowing_state.json)."""
    defaults = {"last_advice_date": None, "last_advice_priority": None}
    try:
        with open(STATE_FILE) as f:
            return {**defaults, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return defaults


def save_state(state: dict) -> None:
    state["last_updated"] = utc_now_iso()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print("[state] opgeslagen.")


def advice_slot_open(state: dict, today: date, now=None) -> bool:
    """Is dit de dagelijkse advies-run?

    True op de eerste run op of ná NOTIFY_AT die vandaag nog geen advies
    heeft afgehandeld. De uurlijkse verversingsruns daarvoor én daarna
    geven False — die schrijven alleen data.json.
    """
    if state.get("last_advice_date") == today.isoformat():
        return False
    return past_local_time(*NOTIFY_AT, now=now)


def bootstrap_monthly_totals(irrigations_raw: dict) -> dict:
    """Eenmalige bootstrap: haal ~13 maanden historische data op en bevries voltooide maanden."""
    today = local_today()
    first_of_month = today.replace(day=1)
    # Einddatum = laatste dag van vorige maand (archive API heeft lag, voltooide maanden zijn veilig)
    end_date = (first_of_month - timedelta(days=1)).isoformat()
    # Startdatum = 1e dag van de maand 13 maanden geleden
    start = first_of_month
    for _ in range(13):
        start = (start - timedelta(days=1)).replace(day=1)
    start_date = start.isoformat()

    print(f"[bootstrap] Ophalen historische data: {start_date} → {end_date}")
    try:
        series = fetch_open_meteo_archive(start_date, end_date)
    except Exception as e:
        print(f"[bootstrap] archive fetch mislukt: {sanitize_error(e)}")
        return {}

    apply_et0_and_balance(series, irrigations_raw)
    totals = build_monthly_totals_from_days(series)
    print(f"[bootstrap] {len(totals)} maanden bevroren: {sorted(totals.keys())}")
    return totals


def load_irrigations_from_gist() -> dict:
    """Haalt irrigatie-log uit GitHub Gist. Format: {"YYYY-MM-DD": mm}."""
    gist_id = os.getenv("GIST_ID")
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not gist_id:
        print("[irrigations] geen GIST_ID, overslaan")
        return {}
    data = gist_read_json(gist_id, "irrigations.json", token=token,
                          default={}, label="irrigations")
    # Bewust geen event-telling in het publieke log: het verschil tussen twee uurlijkse
    # runs zou elke handmatige registratie op de minuut dateren.
    print("[irrigations] logboek geladen")
    return data


def format_telegram(status_lawn: dict, status_shrubs: dict,
                    generated_at: str) -> str:
    icons = {"high": "🚨", "medium": "💧", "low": "⏳", "none": "✓"}

    def zone_line(label: str, status: dict) -> list[str]:
        icon = icons[status["priority"]]
        available_pct = 100 - status["depletion_pct"]
        lines = [
            f"{icon} <b>{label}</b>: {status['recommendation']}",
            f"   Beschikbaar water: <code>{available_pct:.0f}%</code>",
        ]
        if status["proposal_min"] > 0:
            lines.append(
                f"   💧 Advies: <b>{status['proposal_min']} min</b>"
                f" (= {status['proposal_mm']:.1f} mm)"
            )
        return lines

    lawn_lines = zone_line("Gras (sproeier)", status_lawn)
    shrub_lines = zone_line("Struiken (druppelslang)", status_shrubs)

    # Samengevat irrigatie-advies als beide water nodig hebben
    both_need = status_lawn["proposal_min"] > 0 and status_shrubs["proposal_min"] > 0
    one_needs = status_lawn["proposal_min"] > 0 or status_shrubs["proposal_min"] > 0

    today = local_today()
    lines = [
        "<b>Pineapple Under The Sea · dagcheck</b>",
        f"<i>{format_date_nl(today)} {today.year}</i>",
        "",
        *lawn_lines,
        "",
        *shrub_lines,
        "",
        f"🌧️ Regen komende 7d: <b>{status_lawn['rain7_mm']:.1f} mm</b>",
    ]

    # Effectief netto (na probability + canopy-interceptie) — toon alleen
    # als het wezenlijk afwijkt van de ruwe regen, anders is het ruis.
    raw7 = status_lawn["rain7_mm"]
    eff7_lawn = status_lawn.get("eff_rain_7d_mm", raw7)
    eff7_shr = status_shrubs.get("eff_rain_7d_mm", raw7)
    if raw7 >= 1 and (raw7 - eff7_lawn) >= 1.0:
        lines.append(
            f"   <i>Effectief (3d): gras {status_lawn.get('eff_rain_3d_mm', 0):.1f} mm · "
            f"struiken {status_shrubs.get('eff_rain_3d_mm', 0):.1f} mm</i>"
        )
        lines.append(
            f"   <i>Effectief (7d): gras {eff7_lawn:.1f} mm · "
            f"struiken {eff7_shr:.1f} mm</i>"
        )

    if one_needs:
        lines += [""]
        if both_need:
            lines.append(
                f"⏱ Gras: <b>{status_lawn['proposal_min']} min</b> · "
                f"Struiken: <b>{status_shrubs['proposal_min']} min</b>"
            )
        elif status_lawn["proposal_min"] > 0:
            lines.append(f"⏱ Gras: <b>{status_lawn['proposal_min']} min</b>")
        else:
            lines.append(f"⏱ Struiken: <b>{status_shrubs['proposal_min']} min</b>")

    dash = os.getenv("DASHBOARD_URL")
    if dash:
        lines += ["", f'<a href="{dash}">→ Open dashboard</a>']
    return "\n".join(lines)


def main():
    station = os.getenv("WU_STATION_ID", "")
    key = os.getenv("WU_API_KEY", "")
    if not station or not key:
        print("⚠ WU_STATION_ID of WU_API_KEY niet gezet!")
        # Ga toch door met Open-Meteo only
    force = os.getenv("FORCE_NOTIFY", "").lower() in ("1", "true", "yes")

    print("→ Irrigaties laden uit Gist...")
    irrigations_raw = load_irrigations_from_gist()

    # Bootstrap maandtotalen als er nog geen koude opslag is
    existing_monthly = load_existing_monthly_totals()
    if not existing_monthly:
        print("→ Geen maandtotalen gevonden — eenmalige bootstrap...")
        existing_monthly = bootstrap_monthly_totals(irrigations_raw)

    seed_theta = load_previous_theta()
    print(f"→ Data bouwen (WU={bool(station)}, Open-Meteo forecast, 35 warme dagen)...")
    data = build_full_dataset(station, key, irrigations=irrigations_raw,
                              days_past=35, seed_theta=seed_theta or None)
    data["irrigations"] = irrigations_raw

    # Bevries voltooide maanden uit het warme venster en merge met koude opslag
    new_frozen = build_monthly_totals_from_days(data["days"])
    merged_monthly = {**existing_monthly, **new_frozen}  # nieuwe data wint bij overlap
    data["monthly_totals"] = merged_monthly
    print(f"→ Maandtotalen: {len(merged_monthly)} maanden ({', '.join(sorted(merged_monthly.keys()))})")

    status_lawn = assess_status(data, "lawn")
    status_shrubs = assess_status(data, "shrubs")
    # Alleen de prioriteit in het publieke log; de aanbevelingstekst (hoeveelheden,
    # beurt-timing) blijft Telegram-only.
    print(f"   Gras: {status_lawn['priority']} · Struiken: {status_shrubs['priority']}")

    # Publish a trimmed status per zone so the dashboard reads the same facts
    # the Telegram message does, instead of re-deriving thresholds in JS.
    # `recommendation` stays Telegram-only (long-form); the dashboard renders
    # its own short tile text from these facts.
    _DASHBOARD_FIELDS = ("state", "priority", "depletion_pct", "deficit_mm",
                         "days_to_stress", "rain7_mm",
                         "eff_rain_3d_mm", "eff_rain_7d_mm",
                         "eff_rain_intercepted_7d_mm",
                         "proposal_mm", "proposal_min")
    data["lawn_status"]   = {k: status_lawn[k]   for k in _DASHBOARD_FIELDS}
    data["shrubs_status"] = {k: status_shrubs[k] for k in _DASHBOARD_FIELDS}

    # data.json wegschrijven voor het dashboard: naar de privé artefact-gist zodra
    # ARTEFACT_GIST_ID bestaat (privatisering aug 2026 — het bevat o.a. het volledige
    # irrigatie-logboek), anders het oude lokale pad.
    payload = json.dumps(data, separators=(",", ":"))
    dest = artefact_io.write_json_str("data.json", "docs/data.json", payload)
    print(f"→ {dest} geschreven ({len(payload)} bytes)")

    # --- Meldmoment + notificatie-logica ---
    # De uurlijkse runs verversen alleen data.json; alleen de advies-run van
    # 06:00 mag melden (zie NOTIFY_AT). `force` (handmatige dispatch) stuurt
    # altijd en verbruikt het dagslot bewust NIET: een testbericht mag het
    # ochtendadvies niet stilleggen.
    today = local_today()
    state = load_state()
    slot = advice_slot_open(state, today)

    priorities = {status_lawn["priority"], status_shrubs["priority"]}
    needs_advice = ("high" in priorities) or ("medium" in priorities)

    if not (slot or force):
        print(f"→ Geen advies-slot (data ververst; bericht valt om "
              f"{NOTIFY_AT[0]:02d}:{NOTIFY_AT[1]:02d})")
    elif needs_advice or force:
        print("→ Notificatie nodig, versturen...")
        tg_text = format_telegram(status_lawn, status_shrubs, data["generated_at"])
        send_telegram(tg_text, muted_in_quiet=True)
    else:
        print("→ Geen notificatie nodig (alles rustig)")

    if slot:
        # Slot verbruikt, ook als er niets te melden viel — anders zou een
        # rustige ochtend de rest van de dag alsnog een bericht kunnen
        # afvuren zodra de prioriteit omslaat.
        state["last_advice_date"] = today.isoformat()
        state["last_advice_priority"] = (
            "high" if "high" in priorities else
            "medium" if "medium" in priorities else "low")
        save_state(state)

    print("✓ klaar")


if __name__ == "__main__":
    # fail_threshold=2: de workflow doet bij falen één herkansing na 10 min
    # (zelfde job, dus zelfde RUNNER_TEMP-teller) — alleen als die óók faalt
    # is de dag echt verloren en komt er één alert.
    run_guarded(main, "Pineapple Under The Sea check", fail_threshold=2)
