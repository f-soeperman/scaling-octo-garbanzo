"""Shared Telegram notification helper.

Single source of truth for sending Telegram messages across all pipelines.
Credentials default to the environment (`TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID`); callers override the chat target (e.g. the
weather-briefing group via `TELEGRAM_CHAT_GROUP_ID`) or the parse mode as
needed.

Missing credentials or a send error are a graceful no-op that returns
``False`` instead of raising — a single unset secret or a transient Telegram
hiccup can't fail an otherwise-healthy Action run whose real work (compute +
commit) already succeeded by the time it notifies. Transient failures
(connection errors, timeouts, 429, 5xx) are retried twice with a short
backoff before giving up; permanent 4xx errors (bad chat id, malformed
message) are not retried. Zero third-party deps beyond ``requests``.

Also provides :func:`sanitize_error` — secret-safe rendering of exceptions.
WU- en Telegram-URLs dragen hun credential als query-param (`apiKey=...`,
`/bot<token>/`); een requests-exceptie bevat de volledige URL, dus rauwe
``str(e)`` in een log of Telegram-bericht zou het geheim lekken. GitHub
Actions maskeert secrets in de eigen logs, maar niet in een doorgestuurd
Telegram-bericht — daarom altijd via deze helper printen/doorsturen.
"""

import html
import os
import re
import sys
import tempfile
import time

import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

RETRY_DELAYS = (2, 4)  # seconds between attempts on transient failures

# ── Stille modus (quiet) ─────────────────────────────────────────────────────
#
# notify_prefs.json in de GIST_ID-gist — geschreven door uitsluitend de browser
# (vent.html-modal, token-gated): {"quiet": bool, "since": ISO, "cleared_at": ISO}.
# Adviesberichten die `muted_in_quiet=True` meegeven worden bij een actieve
# stille modus niet verstuurd, maar gedragen zich voor de aanroeper én in de
# stdout exact als een geslaagde verzending (zelfde print, return True). Dat is
# de kern van het ontwerp: elke committed state-file, elk artefact en elk
# publiek Actions-log blijft byte-voor-byte gelijk aan een gewone dag — de
# activatie mag nergens publiek af te lezen zijn.
#
# Fail-open: geen creds, geen bestand, of een leesfout → niet stil (liever een
# overbodig bericht dan een stilgevallen pijplijn die niemand opmerkt).
# Operationele meldingen (crash-alerts via run_guarded, token-persist,
# Gardena) geven de vlag bewust niet mee en blijven altijd doorkomen.

NOTIFY_PREFS_FILE = "notify_prefs.json"

_prefs_cache: dict | None = None


def read_notify_prefs() -> dict:
    """De stille-modus-prefs, één keer per proces gelezen (gecachet). ``{}`` bij
    ontbrekende creds/bestand of een leesfout — fail-open, nooit raisen."""
    global _prefs_cache
    if _prefs_cache is None:
        _prefs_cache = _fetch_notify_prefs()
    return _prefs_cache


def _fetch_notify_prefs() -> dict:
    gist_id = os.getenv("GIST_ID")
    # Drie workflows exporteren het Gist-token als GH_TOKEN i.p.v. GIST_TOKEN
    # (daily-check, mowing-notify, gardena-control) — beide namen accepteren.
    token = os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN")
    if not gist_id:
        return {}
    try:
        # Lazy import: gist_io importeert notify (sanitize_error) — een import
        # bovenaan zou een kringimport zijn.
        import gist_io
        prefs = gist_io.read_json(gist_id, NOTIFY_PREFS_FILE, token=token,
                                  default={}, label="prefs")
        return prefs if isinstance(prefs, dict) else {}
    except Exception:
        return {}


def _reset_prefs_cache() -> None:
    """Test-seam: cache legen zodat een test met eigen env/gist opnieuw leest."""
    global _prefs_cache
    _prefs_cache = None


def _quiet_active() -> bool:
    return bool(read_notify_prefs().get("quiet"))

_SECRET_PATTERNS = (
    # query-param credentials (WU apiKey + stationId — beide secrets, zie
    # Project 7 — en generieke token/key params)
    (re.compile(r"(apiKey=)[^&\s\"']+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(stationId=)[^&\s\"']+", re.IGNORECASE), r"\1***"),
    (re.compile(r"((?:api_key|token|key|access_token)=)[^&\s\"']+", re.IGNORECASE), r"\1***"),
    # Telegram bot token in the URL path: /bot<id>:<secret>/
    (re.compile(r"(/bot)[0-9]+:[A-Za-z0-9_-]+"), r"\1***"),
    # Gist-ID in API-URLs: GIST_ID/TADO_GIST_ID zijn secrets en een requests-
    # exceptie op een Gist-call bevat de volledige URL.
    (re.compile(r"(gists/)[0-9a-f]{16,}", re.IGNORECASE), r"\1***"),
)


def sanitize_error(e: BaseException) -> str:
    """Render an exception as ``Type: message`` with credentials scrubbed."""
    msg = str(e)
    for pattern, repl in _SECRET_PATTERNS:
        msg = pattern.sub(repl, msg)
    return f"{type(e).__name__}: {msg}"


def send_telegram(
    text: str,
    *,
    token: str | None = None,
    chat_id: str | None = None,
    parse_mode: str = "HTML",
    disable_preview: bool = True,
    timeout: int = 20,
    muted_in_quiet: bool = False,
) -> bool:
    """Send a Telegram message.

    Returns ``True`` on success, ``False`` on missing credentials or any send
    error. Never raises.

    ``muted_in_quiet=True`` (opt-in per call site — alleen adviesberichten):
    bij een actieve stille modus wordt niets verstuurd, maar het gedrag is voor
    de aanroeper en in stdout identiek aan een geslaagde verzending. Zo stempelt
    elke aanroeper zijn meld-state alsof er verstuurd is en verandert er niets
    aan de publieke sporen. De poort staat ná de creds-check zodat het
    geen-creds-pad in beide standen exact hetzelfde blijft.
    """
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] geen creds, overslaan")
        return False
    if muted_in_quiet and _quiet_active():
        print("[telegram] ✓ verzonden")
        return True
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(
                TELEGRAM_API.format(token=token),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_preview,
                },
                timeout=timeout,
            )
            if r.status_code == 200:
                print("[telegram] ✓ verzonden")
                return True
            # 429/5xx zijn transient → retry; overige 4xx (bad request,
            # verkeerd chat_id) worden niet beter van een retry.
            transient = r.status_code == 429 or r.status_code >= 500
            print(f"[telegram] HTTP {r.status_code}" + (" (retry)" if transient and attempt < len(RETRY_DELAYS) else ""))
            if not transient:
                return False
        except requests.RequestException as e:
            print(f"[telegram] fout: {sanitize_error(e)}")
        except Exception as e:
            print(f"[telegram] fout: {sanitize_error(e)}")
            return False
        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])
    return False


def _counter_path(name: str, counter_file: str | None) -> str:
    # RUNNER_TEMP overleeft de iteraties van de in-job kwartierloop (zelfde
    # runner) en wordt per job schoon — precies de gewenste throttle-scope.
    base = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    slug = re.sub(r"\W+", "_", name)
    return counter_file or os.path.join(base, f"crash_counter_{slug}")


def run_guarded(main_fn, name: str, *, chat_id: str | None = None,
                fail_threshold: int = 1, counter_file: str | None = None) -> None:
    """Top-level vangnet voor de runner-scripts: print een gesanitizede FATAL,
    alerteer via Telegram en exit 1.

    ``fail_threshold > 1`` is voor de kwartierloop-scripts: pas alerten na N
    *opeenvolgende* crashes (teller in een file die de loop-iteraties binnen
    één job-run overleeft), en alleen op de eerste overschrijding — een
    transient API-hikje spamt dan niet, een echte storing alert precies één
    keer. Een geslaagde run reset de teller. ``SystemExit`` (bewuste exits met
    eigen melding, zoals de tado-auth-paden) passeert ongemoeid; onder
    ``DRY_RUN=1`` wordt niet verzonden."""
    counter = _counter_path(name, counter_file)
    try:
        main_fn()
    except Exception as e:
        err = sanitize_error(e)
        print(f"FATAL: {err}", file=sys.stderr)
        fails = 1
        try:
            with open(counter) as f:
                fails = int(f.read().strip() or 0) + 1
        except (OSError, ValueError):
            pass
        try:
            with open(counter, "w") as f:
                f.write(str(fails))
        except OSError:
            pass
        if fails == fail_threshold and os.environ.get("DRY_RUN") != "1":
            suffix = f" ({fails}× op rij)" if fail_threshold > 1 else ""
            # html.escape: excepties als '<Response [500]>' zouden anders de
            # HTML-parse van Telegram breken en de alert laten mislukken.
            send_telegram(f"⚠ <b>{html.escape(name)}</b> crashte{suffix}:\n"
                          f"<code>{html.escape(err)}</code>",
                          chat_id=chat_id)
        sys.exit(1)
    else:
        try:
            os.remove(counter)
        except OSError:
            pass
