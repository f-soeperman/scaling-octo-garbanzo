"""Wekelijks verwarmingsexperiment: welk nachtsetpoint draait deze week.

De vraag (bewonersbesluit okt 2026): **wat kost het om het huis 's nachts warm
te houden, vergeleken met het laten afkoelen?** Twee armen, wekelijks
alternerend: `afkoelen` (nachtsetpoint 16 °C — het huis komt daar in de
praktijk niet onder, dus het koelt vrij af) en `warm` (nachtsetpoint 19 °C).

**Waarom dit wél gemeten wordt.** Het experiment dat hier tot okt 2026 liep
(`morning_recovery`, early start vs. harde start om 06:00) was gekozen op basis
van een rekensom van buiten de repo: UA 163 W/K, "lager dan 16 °C bindt nooit",
~€32 per graad warmer per seizoen (150 nachten × 8 u, 92% ketelrendement,
€1,45/m³). Daaruit volgde "warm houden is per definitie duurder, dus niet het
meten waard". De *richting* klopt fysisch vrijwel zeker, maar de *prijs* — en
dáár gaat de afweging tegen comfort over — is nooit gemeten. Die rekensom is
dus een hypothese die dit experiment toetst, geen uitkomst.

**Early start staat in béíde armen aan.** Zo meet het verschil precies
"afkoelen + weer opwarmen" tegen "warm houden", inclusief het (mogelijk minder
zuinige) opwarmen in de ochtend — en verder niets. Als early start per arm zou
verschillen, valt niet meer te zeggen waar een verschil vandaan komt.

**Waarom wekelijks en niet in blokken van twee maanden.** Twee maandblokken
verschillen per *seizoen*, niet per instelling: januari is kouder dan
november, dus de arm die in januari valt ziet er slechter uit om de verkeerde
reden. Bij wekelijks alterneren zien beide armen hetzelfde weerbereik.

**Waarom de eerste dag afvalt.** Met τ ≈ 23 u draagt het huis zijn toestand
mee over de omschakeling heen: één dag settelt ~65%, twee dagen ~92%. De
omschakeling gebeurt maandagavond, dus dinsdagochtend valt af en woensdag is
de eerste schone ochtend.

De armkeuze is **puur uit de datum afgeleid** (pariteit van het maandag-
ordinaal), niet uit de state. Een gemiste maandag, een handmatige dispatch of
de zomerstop kan de alternatie dus niet uit de pas laten lopen; de state is
enkel het logboek voor de latere analyse (armen koppelen aan het gasverbruik
uit tado Energy IQ + graaddagen gebeurt buiten dit script).
"""

import json
import os
from datetime import date, timedelta

from notify import run_guarded, sanitize_error, send_telegram
from shared_const import format_date_nl, local_today, utc_now_iso

EXPERIMENT = "night_setpoint"

# Het experiment dat tot deze maandag liep. Zijn weekregels blijven in het
# logboek staan (getagd), zodat de historie niet verloren gaat.
PREVIOUS_EXPERIMENT = "morning_recovery"

# Eerste maandag van dit experiment. Weken daarvóór hoorden bij
# `morning_recovery`; een dispatch in zo'n week schrijft niets, anders
# overschrijft hij de bestaande weekregel van het vorige experiment.
EXPERIMENT_START = date(2026, 11, 2)

ARMS = {
    "afkoelen": {
        "label": "laten afkoelen",
        "setpoint": 16.0,
        "detail": "zet het nachtblok in het tado-schema op 16 °C — het huis "
        "komt daar in de praktijk niet onder, dus het koelt vrij af.",
    },
    "warm": {
        "label": "warm houden",
        "setpoint": 19.0,
        "detail": "zet het nachtblok in het tado-schema op 19 °C — het huis "
        "wordt 's nachts op temperatuur gehouden.",
    },
}

# Buiten het stookseizoen valt er niets op te stoken, dus ook niets te meten.
# De alternatie is datum-afgeleid, dus de zomerstop verschuift hem niet.
SEASON_MONTHS = {10, 11, 12, 1, 2, 3, 4}

# Ruim twee winters aan weken; het logboek is klein maar hoeft niet oneindig.
MAX_WEEKS = 200

DEFAULT_STATE_FILE = "heating_experiment_state.json"


# ---------------------------------------------------------------- armkeuze


def monday_of(d: date) -> date:
    """De maandag van de week waar `d` in valt."""
    return d - timedelta(days=d.weekday())


def arm_for_week(d: date) -> str:
    """De arm voor de week van `d` — strikt alternerend, puur uit de datum.

    Pariteit op het *ordinaal van de maandag* (niet op het ISO-weeknummer):
    opeenvolgende maandagen liggen exact 7 dagen uit elkaar, dus `// 7` telt
    gegarandeerd met 1 op. Op het ISO-weeknummer zou een jaar met 53 weken
    twee gelijke armen achter elkaar geven op de jaargrens.
    """
    # Fase zo gekozen dat de eerste week (`EXPERIMENT_START`) `afkoelen` is —
    # dat is de stand van vóór het experiment, dus die week begint zonder
    # omschakeling.
    return "warm" if (monday_of(d).toordinal() // 7) % 2 == 0 else "afkoelen"


def week_label(monday: date) -> str:
    """ISO-weeklabel, bv. `2026-W45`."""
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def analysis_window(monday: date) -> tuple[date, date]:
    """(eerste, laatste) dag die voor deze arm meetelt.

    De omschakeling gebeurt maandagavond; de settle-periode van 24 u loopt dan
    tot dinsdagavond, dus dinsdag valt af en woensdag is de eerste schone dag.
    De arm loopt door tot het bericht van de vólgende maandag, dus die
    maandag telt nog mee.
    """
    return monday + timedelta(days=2), monday + timedelta(days=7)


def week_entry(monday: date, arm: str) -> dict:
    """Het logboekrecord voor deze week — volledig uit de datum afgeleid."""
    start, end = analysis_window(monday)
    return {
        "week": week_label(monday),
        "experiment": EXPERIMENT,
        "arm": arm,
        "night_setpoint": ARMS[arm]["setpoint"],
        "switched_at": monday.isoformat(),
        "analyse_from": start.isoformat(),
        "analyse_through": end.isoformat(),
    }


# ---------------------------------------------------------------- logboek


def state_path() -> str:
    return os.environ.get("HEATING_STATE_FILE", DEFAULT_STATE_FILE)


def load_state() -> dict:
    path = state_path()
    defaults = {"experiment": EXPERIMENT, "weeks": []}
    if not os.path.exists(path):
        return defaults
    # Onleesbaar logboek → verder met een leeg logboek i.p.v. elke maandag
    # crashen tot iemand het bestand met de hand repareert. Dat kan hier
    # veilig: de armkeuze is puur datum-afgeleid (de state is logboek, geen
    # besturing) en eerdere goede versies staan in de git-historie.
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[state] {path} onleesbaar ({sanitize_error(e)}), verder met leeg logboek")
        return defaults
    # Weekregels van vóór de per-regel-tag horen bij het experiment dat toen
    # bovenaan het bestand stond. Taggen vóórdat `record_week` die kop
    # overschrijft — anders lezen de oude regels daarna als het nieuwe
    # experiment.
    owner = state.get("experiment", PREVIOUS_EXPERIMENT)
    for w in state.setdefault("weeks", []):
        w.setdefault("experiment", owner)
    state.setdefault("experiment", EXPERIMENT)
    return state


def previous_arm(state: dict, monday: date) -> str | None:
    """De arm die vorige week draaide volgens het logboek, of `None`.

    Bewust uit het logboek en niet uit de pariteit: bij een koude start (of na
    de zomerstop) is er géén vorige week, en dan is "vorige week draaide …" een
    verzonnen bewering over een week die het experiment niet gedraaid heeft.
    Alleen regels van dít experiment tellen: de laatste `morning_recovery`-week
    is geen vorige arm van het nachtsetpoint-experiment.
    """
    label = week_label(monday - timedelta(days=7))
    for w in state.get("weeks", []):
        if w.get("week") == label and w.get("experiment") == EXPERIMENT:
            return w.get("arm")
    return None


def record_week(state: dict, entry: dict) -> dict:
    """Voeg `entry` toe of werk de bestaande week bij (pure functie).

    Upsert op weeklabel, zodat een herhaalde dispatch in dezelfde week geen
    dubbele regel oplevert — de orchestrator en de fallback-cron kunnen elkaar
    overlappen, en de armkeuze is toch datum-afgeleid.
    """
    weeks = [w for w in state.get("weeks", []) if w.get("week") != entry["week"]]
    weeks.append(entry)
    weeks.sort(key=lambda w: w["switched_at"])
    return {**state, "experiment": EXPERIMENT, "weeks": weeks[-MAX_WEEKS:]}


def save_state(state: dict) -> None:
    state = {**state, "last_updated": utc_now_iso()}
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------- bericht


def build_message(monday: date, arm: str, prev_arm: str | None) -> str:
    start, end = analysis_window(monday)
    drop = monday + timedelta(days=1)
    this = ARMS[arm]
    vorige = (
        f"Vorige week: {ARMS[prev_arm]['label']} ({ARMS[prev_arm]['setpoint']:.0f} °C)."
        if prev_arm
        else "Eerste week van het experiment — vanaf nu wisselt het elke maandag."
    )

    return "\n".join(
        [
            f"🔥 *Verwarmingsexperiment — week {week_label(monday)}*",
            "",
            f"Deze week: *{this['label']}* (nacht {this['setpoint']:.0f} °C)",
            f"→ {this['detail']}",
            "",
            vorige,
            f"Meetdagen: {format_date_nl(start)} t/m {format_date_nl(end)} — "
            f"{format_date_nl(drop)} valt af (het huis draagt na de omschakeling "
            "nog ~24 u zijn oude toestand mee).",
            "",
            "Early start (voorverwarmen) blijft in béíde weken aan — alleen het "
            "nachtsetpoint wisselt.",
            "Tip: een gasmeterstand in tado (Energy IQ) op deze avond maakt de "
            "week echt gemeten i.p.v. door tado verdeeld.",
        ]
    )


def main():
    today = local_today()
    monday = monday_of(today)
    arm = arm_for_week(today)

    if monday < EXPERIMENT_START:
        print(f"Experiment start op {EXPERIMENT_START.isoformat()} — geen bericht, geen weekregistratie.")
        return

    if today.month not in SEASON_MONTHS and os.environ.get("FORCE_SEND") != "1":
        print(f"Buiten het stookseizoen (maand {today.month}) — geen bericht, geen weekregistratie.")
        return

    state = load_state()
    message = build_message(monday, arm, previous_arm(state, monday))

    if os.environ.get("DRY_RUN") == "1":
        # Alleen een handmatige DRY_RUN-dispatch mag de berichttekst tonen —
        # de scheduled run-log is publiek (zie de privacy-grondregel), en dit
        # was tot aug 2026 de enige melder die zijn body onvoorwaardelijk
        # printte. Een testdispatch mag bovendien het experimentlogboek niet
        # vervuilen; de armkeuze is datum-afgeleid, dus er valt hier niets te
        # bewaren.
        print(message)
        print("DRY_RUN=1, niet verzonden en state niet weggeschreven.")
        return

    save_state(record_week(state, week_entry(monday, arm)))
    print(f"Week {week_label(monday)} geregistreerd in {state_path()} (arm: {arm}).")

    send_telegram(message, parse_mode="Markdown", muted_in_quiet=True)
    print("Verzonden naar Telegram.")


if __name__ == "__main__":
    run_guarded(main, "verwarming")
