"""Shared read-only GitHub Gist helpers.

Single source of truth for *reading* a file out of a Gist — voorheen vier
keer vrijwel identiek geïmplementeerd (irrigaties, maailog, openings-log,
tado-token). Twee smaken:

- :func:`read_file` — content van één bestand, of ``None`` als het bestand
  niet in de Gist zit. **Raist** bij netwerk-/HTTP-fouten; de caller beslist
  (window_advisor wil hard falen: zonder token-file geen run).
- :func:`read_json` — gracieuze variant: geparsede JSON of ``default`` bij
  élke fout (gelogd, secret-safe via :func:`notify.sanitize_error`). Voor de
  logs waar "leeg" een veilige terugvaloptie is.

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
        r = requests.get(f["raw_url"], headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
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
    r = requests.get(GIST_API.format(gist_id=gist_id), headers=headers,
                     timeout=timeout)
    r.raise_for_status()
    f = r.json().get("files", {}).get(filename)
    return _file_content(f, headers, timeout)


def read_files(gist_id: str, token: str | None = None,
               timeout: int = 20) -> dict[str, str]:
    """Alle bestanden uit een Gist als {naam: content} — één API-call i.p.v. één
    per bestand (de Gist-GET levert toch alle files). Raist bij fouten."""
    headers = _headers(token)
    r = requests.get(GIST_API.format(gist_id=gist_id), headers=headers,
                     timeout=timeout)
    r.raise_for_status()
    out = {}
    for name, f in (r.json().get("files") or {}).items():
        content = _file_content(f, headers, timeout)
        if content is not None:
            out[name] = content
    return out


def read_json(gist_id: str, filename: str, token: str | None = None,
              timeout: int = 20, default=None, label: str = "gist"):
    """Geparsede JSON uit een Gist-bestand, of ``default`` bij elke fout.

    Fouten worden gelogd met ``label`` als prefix; nooit geraisd.
    """
    try:
        content = read_file(gist_id, filename, token=token, timeout=timeout)
        if not content:
            return default
        return json.loads(content)
    except Exception as e:
        print(f"[{label}] kon niet laden: {sanitize_error(e)}")
        return default
