"""artefact_io.py — de privé artefact-Gist voor de gegenereerde artefacten.

De dashboard-artefacten (`data.json`, `mowing_data.json`, `window_data.json`, de
drie vent-artefacten) en `mowing_state.json` waren publieke bestanden in de repo
met gedateerde handmatige-actie-logboeken, raamstanden en kamerreeksen erin. Een
meerweeks gat in zo'n logboek is een afwezigheidssignaal, en de
15-min/uurlijkse commit-historie maakte elke registratie voorgoed dateerbaar
(privacy-deep-dive aug 2026). Ze leven daarom in een eigen **privé Gist**
(`ARTEFACT_GIST_ID`, auth = het bestaande Gist-token `GIST_TOKEN`/`GH_TOKEN`):

- Secret gezet → lezen/schrijven via de Gist-API; er wordt géén lokaal bestand
  meer geschreven, dus de workflow-commit raakt `docs/` niet meer aan.
- Secret afwezig (bootstrap vóór het secret bestaat, tests, lokaal draaien) →
  het oude gedrag: het lokale pad. De migratie activeert zichzelf dus zodra het
  secret bestaat, zonder harde knip — en valt er ook veilig op terug.

Eén schrijver per bestand blijft gelden: `data.json` ← check_and_notify,
`mowing_data.json` + `mowing_state.json` ← mowing_advisor, `window_data.json` ←
window_advisor, de vent-artefacten ← vent_twin. De dashboards lezen de gist
client-side (localStorage `artefact_gist_id` + het bestaande token).
"""

import json
import os

import gist_io
from notify import sanitize_error


def _creds() -> tuple[str | None, str | None]:
    return (os.getenv("ARTEFACT_GIST_ID"),
            os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN"))


def gist_active() -> bool:
    gid, token = _creds()
    return bool(gid and token)


def read_json(filename: str, local_path: str, default=None, strict: bool = False):
    """Het artefact als geparsede JSON: uit de artefact-gist wanneer die
    geconfigureerd is, anders het lokale pad. Graceful → ``default``.

    ``strict=True`` is voor wie het resultaat als basis voor een schrijf
    gebruikt (state, rollende historie, koude opslag): een léésfout op de gist
    raist dan i.p.v. als "leeg" door te gaan — anders overschrijft één
    netwerk-blip de opgebouwde historie met een lege basis. Een ontbrekend
    bestand is ook dan gewoon ``default``."""
    if gist_active():
        gid, token = _creds()
        return gist_io.read_json(gid, filename, token=token, default=default,
                                 label="artefact", strict=strict)
    return _read_local(local_path, default)


def read_many(files: dict[str, str], strict: bool = False) -> dict:
    """Meerdere artefacten in één keer: ``{bestandsnaam: lokaal pad}`` →
    ``{bestandsnaam: geparsede JSON of None}``. In gist-modus is dat één
    API-call i.p.v. één volledige Gist-download per bestand. ``strict`` als bij
    :func:`read_json`."""
    if not gist_active():
        return {fn: _read_local(path, None) for fn, path in files.items()}
    gid, token = _creds()
    try:
        raw = gist_io.read_files(gid, token=token, names=files)
    except Exception as e:
        if strict:
            raise
        print(f"[artefact] kon niet laden: {sanitize_error(e)}")
        return dict.fromkeys(files)
    out = {}
    for fn in files:
        try:
            out[fn] = json.loads(raw[fn]) if raw.get(fn) else None
        except ValueError:
            out[fn] = None
    return out


def _read_local(local_path: str, default):
    try:
        with open(local_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json_str(filename: str, local_path: str, payload: str) -> str:
    """Schrijf het artefact (gist-PATCH of lokaal bestand). Geeft een korte
    bestemmingsnaam voor de logregel. Gist-fouten raisen — het artefact is de
    kern-deliverable van de run, dus stil half-falen is erger dan een rode run
    (de workflows hebben een in-job herkansing)."""
    if gist_active():
        gid, token = _creds()
        gist_io.write_files(gid, {filename: payload}, token=token, timeout=30)
        return filename
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(payload)
    return local_path
