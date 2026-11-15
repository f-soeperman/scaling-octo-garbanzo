"""Shared read-only GitHub Gist helpers.

Single source of truth for *reading* a file out of a Gist — voorheen vier
keer vrijwel identiek geïmplementeerd (irrigaties, maailog, openings-log,
tado-token). Twee smaken:

- :func:`read_file` — content van één bestand, of ``None`` als het bestand
  niet in de Gist zit. **Raist** bij netwerk-/HTTP-fouten; de caller beslist
  (window_advisor wil hard falen: zonder token-file geen run).
- :func:`read_json` — gracieuze variant: geparsede JSON of ``default`` bij
  élke fout (gelogd, secret-safe via :func:`notify.sanitize_error`). Voor de
  logs waar "leeg" een veilige terugvaloptie is. ``strict=True`` maakt er de
  variant van voor een read-modify-write-basis: een ontbrekend bestand is nog
  steeds ``default``, maar een léésfout raist — "kon niet lezen" mag daar nooit
  als "leeg" doorgaan, want dan schrijft de run een lege basis terug.

Een GET krijgt een korte, begrensde herkansing op transiënte fouten
(timeout/verbindingsfout/502-504, :data:`READ_RETRY_DELAYS`). Bewust zónder
logregel: de privacy-gevoelige loops (gardena, potje) hebben een vormvaste
stdout.

Gist-schrijf*semantiek* (wát er wanneer geschreven wordt) blijft bewust bij de
projecten (CLAUDE.md-grondregel: nooit aan de Gist-schrijflogica komen zonder
expliciete opdracht — risico op stille dataverlies, m.n. de roterende
tado-token). Alleen het *transport* van een PATCH is gedeeld — :func:`write_files`
— omdat de 409-retry voor élke schrijver hetzelfde moet zijn (sept 2026).
"""

import json
import time

import requests

from notify import sanitize_error

GIST_API = "https://api.github.com/gists/{gist_id}"

# De artefact-gist heeft vier schrijvers op eigen cadans (raam-adviseur en
# tweeling elk kwartier, bodem- en maai-run elk uur), en binnen één run gaan
# PATCHes vaak vlak na elkaar. Twee PATCHes die elkaar raken geven een
# 409 Conflict uit Gist's git-backend — geen dataverlies, de tweede mag gewoon
# opnieuw zodra de eerste commit gezet is. Kort en begrensd retryen (de PATCH
# is idempotent); een 409 dat niet wegtrekt faalt daarna alsnog zichtbaar.
WRITE_RETRY_DELAYS = (1, 3, 8)  # s

# Een GET is idempotent, dus een transiënte hapering (timeout, verbroken
# verbinding, gateway-fout) mag kort opnieuw. Zonder dit maakte één blip van
# een graceful reader een "lege" basis (zie read_json).
READ_RETRY_DELAYS = (2, 6)  # s
_TRANSIENT_STATUS = (502, 503, 504)


def _get(url: str, headers: dict, timeout: int):
    """GET met herkansing op transiënte fouten; raist na de laatste poging."""
    last = len(READ_RETRY_DELAYS)
    for attempt, delay in enumerate((0, *READ_RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError):
            if attempt < last:
                continue
            raise
        if r.status_code in _TRANSIENT_STATUS and attempt < last:
            continue
        r.raise_for_status()
        return r


def write_files(gist_id: str, files: dict[str, str], token: str | None = None,
                timeout: int = 20) -> None:
    """Multi-file PATCH naar een Gist, met retry op 409 Conflict. Raist bij
    elke andere HTTP-fout (en bij een 409 dat de retries overleeft)."""
    payload = {"files": {fn: {"content": content} for fn, content in files.items()}}
    for attempt, delay in enumerate((0, *WRITE_RETRY_DELAYS), start=1):
        if delay:
            time.sleep(delay)
        r = requests.patch(GIST_API.format(gist_id=gist_id), headers=_headers(token),
                           json=payload, timeout=timeout)
        if r.status_code == 409 and attempt <= len(WRITE_RETRY_DELAYS):
            print(f"[gist] 409 Conflict op PATCH-poging {attempt}, retry")
            continue
        r.raise_for_status()
        return


def _file_content(f: dict, headers: dict, timeout: int) -> str | None:
    """Content van één Gist-file-record, mét truncation-afhandeling: de Gist-API
    kapt `content` af boven ~1 MB en zet dan `truncated` + een `raw_url`. Dat
    stilzwijgend negeren zou een halve JSON teruggeven die de parser afwijst en
    een graceful reader op zijn default laat terugvallen — stil dataverlies."""
    if f is None:
        return None
    if f.get("truncated") and f.get("raw_url"):
        return _get(f["raw_url"], headers, timeout).text
    return f.get("content")


def _headers(token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def read_file(gist_id: str, filename: str, token: str | None = None,
              timeout: int = 20) -> str | None:
    """Content van één bestand uit een Gist, of ``None`` als het ontbreekt.

    Raist bij netwerk-/HTTP-fouten (caller beslist wat falen betekent).
    """
    headers = _headers(token)
    r = _get(GIST_API.format(gist_id=gist_id), headers, timeout)
    f = r.json().get("files", {}).get(filename)
    return _file_content(f, headers, timeout)


def read_files(gist_id: str, token: str | None = None,
               timeout: int = 20, names=None) -> dict[str, str]:
    """Bestanden uit een Gist als {naam: content} — één API-call i.p.v. één
    per bestand (de Gist-GET levert toch alle files). Raist bij fouten.

    ``names`` beperkt het resultaat tot die bestandsnamen. Dat scheelt meer dan
    het lijkt: voor elk afgekapt (>~1 MB) bestand volgt de reader de ``raw_url``
    met een eigen request, en een aanroeper die twee kleine bestanden wil hoeft
    de grote maand-shards in dezelfde Gist niet mee te downloaden."""
    headers = _headers(token)
    r = _get(GIST_API.format(gist_id=gist_id), headers, timeout)
    wanted = None if names is None else set(names)
    out = {}
    for name, f in (r.json().get("files") or {}).items():
        if wanted is not None and name not in wanted:
            continue
        content = _file_content(f, headers, timeout)
        if content is not None:
            out[name] = content
    return out


def read_json(gist_id: str, filename: str, token: str | None = None,
              timeout: int = 20, default=None, label: str = "gist",
              strict: bool = False):
    """Geparsede JSON uit een Gist-bestand, of ``default`` bij elke fout.

    Fouten worden gelogd met ``label`` als prefix; nooit geraisd — tenzij
    ``strict``: dan raist een léésfout (netwerk/HTTP). Een ontbrekend, leeg of
    onparseerbaar bestand blijft ook dan ``default``: dat is een toestand van
    de Gist, geen hapering, en de schrijver herstelt 'm vanzelf.
    """
    try:
        content = read_file(gist_id, filename, token=token, timeout=timeout)
    except Exception as e:
        if strict:
            raise
        print(f"[{label}] kon niet laden: {sanitize_error(e)}")
        return default
    if not content:
        return default
    try:
        return json.loads(content)
    except ValueError as e:
        print(f"[{label}] kon niet laden: {sanitize_error(e)}")
        return default
