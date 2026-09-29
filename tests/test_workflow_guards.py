"""De guard-jobs van de avond-/dagslot-workflows moeten een verláte fallback-cron
overslaan. GitHub's scheduler vertraagt crons soms uren: de 19:15-cron van de
nachtvoorspelling vuurde eens pas om 00:30, en een guard die alleen "sinds
middernacht" telde zag dan een nieuwe dag zonder runs en meldde dubbel.

We draaien het échte guard-script uit de workflow met een nagebootste klok
(`date`-stub) en een `gh`-stub die "geen eerdere runs" antwoordt — dus alleen de
klokpoort kan de run tegenhouden."""

import os
import pathlib
import stat
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


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
