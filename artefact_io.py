"""artefact_io.py — de privé artefact-Gist voor de live bodem-/maai-artefacten.

`docs/data.json` en `docs/mowing_data.json` waren publieke Pages-artefacten met de
gedateerde handmatige-actie-logboeken erin (sproei- en maaibeurten, plus het
irrigatie-logboek integraal). Een meerweeks gat in zo'n logboek is een
afwezigheidssignaal, en de 15-min/uurlijkse commit-historie maakte elke
registratie voorgoed dateerbaar (privacy-deep-dive aug 2026). Beide artefacten
verhuizen daarom naar een eigen **privé Gist** (`ARTEFACT_GIST_ID`, auth = het
bestaande Gist-token `GIST_TOKEN`/`GH_TOKEN`):

- Secret gezet → lezen/schrijven via de Gist-API; er wordt géén lokaal bestand
  meer geschreven, dus de workflow-commit raakt `docs/` niet meer aan.
- Secret afwezig (bootstrap vóór het secret bestaat, tests, lokaal draaien) →
  het oude gedrag: het lokale pad. De migratie activeert zichzelf dus zodra het
  secret bestaat, zonder harde knip — en valt er ook veilig op terug.

Eén schrijver per bestand blijft gelden: `data.json` ← check_and_notify,
`mowing_data.json` ← mowing_advisor. De dashboards lezen de gist client-side
(localStorage `artefact_gist_id` + het bestaande token) en vallen terug op het
lokale bestand zolang dat nog bestaat.
"""

import glob
import json
import os
import re

import gist_io


def _creds() -> tuple[str | None, str | None]:
    return (os.getenv("ARTEFACT_GIST_ID"),
            os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN"))


def gist_active() -> bool:
    gid, token = _creds()
    return bool(gid and token)


def read_json(filename: str, local_path: str, default=None):
    """Het artefact als geparsede JSON: uit de artefact-gist wanneer die
    geconfigureerd is, anders het lokale pad. Graceful → ``default``."""
    if gist_active():
        gid, token = _creds()
        return gist_io.read_json(gid, filename, token=token, default=default,
                                 label="artefact")
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


# ── Zelf-uitvoerende migratie van gecommitte bestanden (security-scan nov 2026) ──
#
# Voor state en archieven die tot nov 2026 gecommit werden (soil_state.json,
# shade_state.json, het nachtvoorspellingslog, het stations-archief): de eerste
# run in gist-modus leest de gecommitte kopie nog als startpunt, schrijft naar
# de gist en verwijdert daarna het lokale bestand; de workflow commit die
# verwijdering. Geen harde knip, geen verloren dag-geheugen.

def read_json_migrating(filename: str, local_path: str, default=None):
    """Als :func:`read_json`, maar valt in gist-modus terug op het (nog
    gecommitte) lokale bestand zolang de gist het niet kent."""
    if gist_active():
        stored = read_json(filename, local_path, default=None)
        if stored is not None:
            return stored
    try:
        with open(local_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def retire_local(local_path: str) -> bool:
    """Verwijder de lokale kopie zodra de gist de bron is. Alleen aanroepen ná
    een geslaagde gist-schrijf."""
    if gist_active() and os.path.isfile(local_path):
        os.remove(local_path)
        return True
    return False


def read_text(filename: str) -> str | None:
    """Ruwe content uit de artefact-gist, ``None`` als het bestand ontbreekt.
    Raist bij netwerk-/API-fouten — bedoeld als basis voor read-modify-write,
    waar een stille lege basis dataverlies zou zijn."""
    gid, token = _creds()
    return gist_io.read_file(gid, filename, token=token)


def read_all_text() -> dict[str, str]:
    """Alle bestanden uit de artefact-gist als {naam: content}. Raist bij fouten."""
    gid, token = _creds()
    return gist_io.read_files(gid, token=token)


def write_many(files: dict[str, str]) -> None:
    """Eén multi-file-PATCH naar de artefact-gist. Raist bij fouten."""
    gid, token = _creds()
    gist_io.write_files(gid, files, token=token, timeout=30)


# ── Maand-shards in de artefact-gist (`<prefix>_<YYYY-MM>.json`) ─────────────────
#
# Eén schrijver per prefix. In gist-modus is de gist de bron; de lokale map is
# dan alleen nog het startpunt van de migratie (en het test-/bootstrap-pad
# zolang het secret ontbreekt).


def shard_name(prefix: str, month: str) -> str:
    return f"{prefix}_{month}.json"


def _local_shards(local_dir: str) -> dict[str, tuple[str, dict]]:
    """{maand: (pad, shard)} voor elk leesbaar lokaal maandbestand."""
    out = {}
    for path in sorted(glob.glob(os.path.join(local_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue   # onleesbaar → niet migreren én niet verwijderen
        if isinstance(shard, dict):
            out[shard.get("month") or os.path.basename(path)[:-len(".json")]] = (path, shard)
    return out


def load_shard(prefix: str, local_dir: str, month: str) -> dict | None:
    """Eén maand-shard, of ``None`` als hij nog niet bestaat. In gist-modus
    raist een netwerkfout (nooit een lege basis voor een read-modify-write)."""
    if gist_active():
        text = read_text(shard_name(prefix, month))
        return json.loads(text) if text else None
    try:
        with open(os.path.join(local_dir, f"{month}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_shards(prefix: str, local_dir: str, shards: dict[str, dict]) -> None:
    """Schrijf {maand: shard} — één PATCH in gist-modus, anders lokale bestanden."""
    if not shards:
        return
    body = {m: json.dumps(s, ensure_ascii=False, separators=(",", ":"))
            for m, s in shards.items()}
    if gist_active():
        write_many({shard_name(prefix, m): b for m, b in body.items()})
        return
    os.makedirs(local_dir, exist_ok=True)
    for month, payload in body.items():
        with open(os.path.join(local_dir, f"{month}.json"), "w", encoding="utf-8") as f:
            f.write(payload)


def load_all_shards(prefix: str, local_dir: str) -> list[dict]:
    """Alle maand-shards, op maand gesorteerd: de gist (indien actief) plus
    lokale maanden die de gist nog niet kent."""
    found: dict[str, dict] = {}
    if gist_active():
        pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{4}}-\d{{2}})\.json$")
        for name, text in read_all_text().items():
            m = pattern.match(name)
            if not m:
                continue
            try:
                found[m.group(1)] = json.loads(text)
            except json.JSONDecodeError:
                continue
    for month, (_path, shard) in _local_shards(local_dir).items():
        found.setdefault(month, shard)
    return [found[m] for m in sorted(found)]


def migrate_shards(prefix: str, local_dir: str, rows_key: str, id_key: str) -> int:
    """Eenmalige, zelf-uitvoerende migratie van gecommitte maand-shards naar de
    artefact-gist: unie per ``id_key`` (de gist wint bij overlap) → schrijven →
    read-back die bevestigt dat élke lokale rij in de gist staat → lokale
    bestanden weg (de workflow commit die verwijdering). Idempotent; elke
    faalroute raist en laat de lokale bestanden staan. Zelfde opzet als
    vent_io.migrate_history_shards. Geeft het aantal gemigreerde bestanden."""
    if not gist_active():
        return 0
    local = _local_shards(local_dir)
    if not local:
        return 0
    to_write = {}
    for month, (_path, shard) in local.items():
        merged = load_shard(prefix, local_dir, month) or {
            k: v for k, v in shard.items() if k != rows_key}
        rows = merged.setdefault(rows_key, [])
        have = {r.get(id_key) for r in rows}
        rows.extend(r for r in shard.get(rows_key) or []
                    if r.get(id_key) and r[id_key] not in have)
        rows.sort(key=lambda r: r.get(id_key) or "")
        to_write[month] = merged
    save_shards(prefix, local_dir, to_write)
    for month, (_path, shard) in local.items():
        after = load_shard(prefix, local_dir, month) or {}
        have = {r.get(id_key) for r in after.get(rows_key) or []}
        want = {r[id_key] for r in shard.get(rows_key) or [] if r.get(id_key)}
        if not want <= have:
            raise RuntimeError("read-back mist rijen — lokale shards blijven staan")
    for _month, (path, _shard) in local.items():
        os.remove(path)
    return len(local)


def write_state(filename: str, local_path: str, payload: str,
                attempts: int = 3, delay_s: float = 5.0) -> None:
    """Schrijf een meld-state en ruim de gemigreerde lokale kopie op. Een state
    wordt ná het versturen van het bericht geschreven; een schrijf die op een
    korte Gist-hapering strandt zou de in-job herkansing hetzelfde bericht nog
    eens laten sturen. Daarom een paar pogingen vóór de fout doorgaat."""
    import time
    for attempt in range(1, attempts + 1):
        try:
            write_json_str(filename, local_path, payload)
            break
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(delay_s)
    retire_local(local_path)
