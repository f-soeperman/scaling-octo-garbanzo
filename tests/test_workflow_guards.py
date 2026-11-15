"""De guard-jobs van de avond-/dagslot-workflows moeten een verláte fallback-cron
overslaan. GitHub's scheduler vertraagt crons soms uren: de 19:15-cron van de
nachtvoorspelling vuurde eens pas om 00:30, en een guard die alleen "sinds
middernacht" telde zag dan een nieuwe dag zonder runs en meldde dubbel.

We draaien het échte guard-script uit de workflow met een nagebootste klok
(`date`-stub) en een `gh`-stub die "geen eerdere runs" antwoordt — dus alleen de
klokpoort kan de run tegenhouden."""

import os
import pathlib
import shutil
import stat
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _guard_script(workflow: str) -> str:
    """Het `run: |`-blok van de guard-job, zonder YAML-parser (pyyaml staat
    bewust niet in de CI-requirements): de eerste `run: |` ná `  guard:`, tot
    de inspringing terugvalt."""
    lines = (ROOT / ".github/workflows" / workflow).read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "  guard:")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for ln in lines[run + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) < indent:
            break
        body.append(ln[indent:])
    return "\n".join(body)


def _run_guard(tmp_path, workflow: str, hhmm: str) -> bool:
    """True als de guard de run overslaat (handled=1) op lokale tijd `hhmm`."""
    hh, mm = hhmm.split(":")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "date").write_text(
        "#!/bin/bash\n"
        f'case "$*" in *%H*) echo {hh};; *%M*) echo {mm};; *) echo 1700000000;; esac\n')
    (bindir / "gh").write_text("#!/bin/bash\necho 0\n")
    for f in ("date", "gh"):
        (bindir / f).chmod((bindir / f).stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "out"
    out.write_text("")
    script = _guard_script(workflow).replace("${{ github.run_id }}", "1")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out)}
    subprocess.run(["bash", "-e", "-c", script], env=env, check=True, capture_output=True)
    return "handled=1" in out.read_text()


@pytest.mark.parametrize("workflow, late, on_time", [
    ("night-forecast.yml", "00:30", "19:15"),
    ("heating-temp-notify.yml", "00:30", "21:40"),
    ("weekjournaal.yml", "00:30", "20:40"),
    ("sandbox-notify.yml", "00:30", "20:40"),   # verlate avond-cron ≠ ochtend-slot
    ("sandbox-notify.yml", "13:10", "08:40"),   # verlate ochtend-cron ≠ avond-slot
])
def test_guard_slaat_verlate_fallback_cron_over(tmp_path, workflow, late, on_time):
    assert _run_guard(tmp_path, workflow, late) is True
    assert _run_guard(tmp_path, workflow, on_time) is False


# ── Ledger-dedup: het anker is het doelmoment, niet middernacht (nov 2026) ─────
# De klokpoort hierboven slaat een verlate cron van ná middernacht terecht over,
# maar die run eindigt als "success" in het ledger. Met middernacht als anker
# telde hij daarna als "vandaag al gedaan" — voor de orchestrator én voor de
# fallback van die dag. Zo viel de nachtvoorspelling dagen achter elkaar uit.

_AMS = "Europe/Amsterdam"

_DATE_STUB = r'''#!/usr/bin/env python3
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
t = datetime.fromtimestamp(int(os.environ["FAKE_NOW"]), ZoneInfo("Europe/Amsterdam"))
args = sys.argv[1:]
if "-d" in args:
    hh, mm = args[args.index("-d") + 1].split()[1].split(":")
    t = t.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
fmt = next(a for a in args if a.startswith("+"))[1:]
print(int(t.timestamp()) if fmt == "%s" else t.strftime(fmt))
'''

# `gh run list --workflow X … --jq EXPR` → de echte jq-expressie op een nagebootst
# ledger; al het andere (gh api, gh workflow run) levert niets op.
_GH_STUB = r'''#!/bin/bash
if [ "$1 $2" = "run list" ]; then
  wf=""; expr=""
  while [ $# -gt 0 ]; do
    case "$1" in --workflow) wf="$2"; shift;; --jq) expr="$2"; shift;; esac
    shift
  done
  f="$LEDGER_DIR/$wf.json"; [ -f "$f" ] || f="$LEDGER_DIR/empty.json"
  exec jq "$expr" "$f"
fi
exit 1
'''


def _epoch(y, mo, d, hh, mm):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return int(datetime(y, mo, d, hh, mm, tzinfo=ZoneInfo(_AMS)).timestamp())


def _iso_utc(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stage(tmp_path, ledger: dict):
    import json
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "date").write_text(_DATE_STUB)
    (bindir / "gh").write_text(_GH_STUB)
    for f in ("date", "gh"):
        (bindir / f).chmod((bindir / f).stat().st_mode | stat.S_IEXEC)
    ledgers = tmp_path / "ledger"
    ledgers.mkdir(exist_ok=True)
    (ledgers / "empty.json").write_text("[]")
    for wf, runs in ledger.items():
        (ledgers / wf).with_suffix(".yml.json").write_text(json.dumps(
            [{"databaseId": 100 + i, "createdAt": _iso_utc(t), "status": "completed",
              "conclusion": "success"} for i, t in enumerate(runs)]))
    return bindir, ledgers


def _orchestrator_dispatches(tmp_path, now_epoch: int, ledger: dict) -> list[str]:
    bindir, ledgers = _stage(tmp_path, ledger)
    lines = (WORKFLOWS / "orchestrator.yml").read_text(encoding="utf-8").splitlines()
    run = next(i for i, ln in enumerate(lines) if ln.strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for ln in lines[run + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) < indent:
            break
        body.append(ln[indent:])
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "DRY_RUN": "1",
           "FAKE_NOW": str(now_epoch), "LEDGER_DIR": str(ledgers), "GH_REPO": "o/r"}
    out = subprocess.run(["bash", "-c", "\n".join(body)], env=env, check=True,
                         capture_output=True, text=True).stdout
    return [ln.split("→ ", 1)[1] for ln in out.splitlines() if "zou dispatchen" in ln]


pytestmark_jq = pytest.mark.skipif(not shutil.which("jq"), reason="jq niet beschikbaar")


@pytestmark_jq
def test_verlate_cron_van_na_middernacht_blokkeert_de_avond_niet(tmp_path):
    """De reeks uit het run-ledger van nov 2026: de 19:15-fallback vuurt om 00:28,
    wordt door zijn guard overgeslagen en staat als geslaagde run in het ledger.
    Om 18:45 moet de orchestrator de nachtvoorspelling tóch dispatchen."""
    verlaat = _epoch(2026, 11, 14, 0, 28)
    avond = _epoch(2026, 11, 14, 18, 46)
    wie = _orchestrator_dispatches(tmp_path / "a", avond,
                                   {"night-forecast": [verlaat]})
    assert any(d.startswith("night-forecast.yml") for d in wie)
    # …en een run van ná het doelmoment telt gewoon als gedaan.
    wie = _orchestrator_dispatches(tmp_path / "b", avond + 900,
                                   {"night-forecast": [verlaat, avond]})
    assert not any(d.startswith("night-forecast.yml") for d in wie)


@pytestmark_jq
def test_verlate_avond_cron_blokkeert_de_ochtend_zandbak_niet(tmp_path):
    verlaat = _epoch(2026, 11, 14, 0, 40)
    ochtend = _epoch(2026, 11, 14, 8, 1)
    wie = _orchestrator_dispatches(tmp_path / "a", ochtend, {"sandbox-notify": [verlaat]})
    assert "sandbox-notify.yml -f mode=morning" in wie
    wie = _orchestrator_dispatches(tmp_path / "b", ochtend + 900,
                                   {"sandbox-notify": [verlaat, ochtend]})
    assert not any(d.startswith("sandbox-notify.yml") for d in wie)


@pytestmark_jq
@pytest.mark.parametrize("workflow, hhmm", [
    ("night-forecast.yml", (19, 15)), ("heating-temp-notify.yml", (21, 40)),
    ("weekjournaal.yml", (20, 40)), ("weather-briefing.yml", (5, 40)),
    ("shade-notify.yml", (8, 40)), ("sandbox-notify.yml", (8, 40)),
    ("sandbox-notify.yml", (20, 40)),
])
def test_fallback_draait_zelf_als_alleen_een_verlate_cron_in_het_ledger_staat(
        tmp_path, workflow, hhmm):
    """Spiegel aan de guard-kant: op zijn eigen tijdstip mag de fallback zich niet
    laten wegstrepen door de overgeslagen cron van 00:30 — wél door een echte run
    van ná het doelmoment."""
    verlaat = _epoch(2026, 11, 14, 0, 30)
    nu = _epoch(2026, 11, 14, *hhmm)

    def handled(path, runs):
        bindir, ledgers = _stage(path, {workflow[:-4]: runs})
        out = path / "out"
        out.write_text("")
        script = _guard_script(workflow).replace("${{ github.run_id }}", "1")
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
               "GITHUB_OUTPUT": str(out), "FAKE_NOW": str(nu), "LEDGER_DIR": str(ledgers)}
        subprocess.run(["bash", "-e", "-c", script], env=env, check=True,
                       capture_output=True)
        return "handled=1" in out.read_text()

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert handled(tmp_path / "a", [verlaat]) is False
    assert handled(tmp_path / "b", [verlaat, nu - 600]) is True


@pytest.mark.parametrize("workflow, late", [
    ("weather-briefing.yml", "00:30"), ("shade-notify.yml", "00:30"),
])
def test_ook_briefing_en_zonwering_slaan_een_verlate_cron_over(tmp_path, workflow, late):
    assert _run_guard(tmp_path, workflow, late) is True


def test_orchestrator_zet_zijn_eigen_opvolger_klaar():
    wf = (WORKFLOWS / "orchestrator.yml").read_text(encoding="utf-8")
    assert "gh workflow run orchestrator.yml --ref main" in wf
    assert "!inputs.dry_run && github.ref_name == 'main'" in wf
