"""Pytest bootstrap: make the repo root importable so tests can do
``import soil_model`` / ``import notify`` regardless of pytest's import mode.
"""
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture(autouse=True)
def _geen_wachttijd_op_gist_herkansing(monkeypatch):
    """gist_io herkanst een GET op transiënte fouten met echte pauzes (2+6 s).
    De herkansing zelf blijft in tests actief; alleen het wachten vervalt —
    anders kost elke test die een netwerkfout nabootst acht seconden."""
    import gist_io
    monkeypatch.setattr(gist_io, "READ_RETRY_DELAYS",
                        (0,) * len(gist_io.READ_RETRY_DELAYS))


@pytest.fixture
def assert_checkout_pinned():
    """Bewaakt dat een workflow zijn checkout op de branch-tip pint.

    Zonder pin pakt actions/checkout `github.sha` — de stand van het moment van
    inplannen. Bij de zelf-gestuurde kwartierloops (raam-adviseur, tweeling) wordt
    een restart-kick tot ~5u door de concurrency-guard vastgehouden, dus de
    overnemende run leest een uren-oud artefact en rebaset de tussenliggende
    samples eruit (gemeten 5 aug 2026, zie window-notify.yml).
    """
    def check(workflow: str):
        wf = (pathlib.Path(__file__).resolve().parent
              / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        lines = wf.splitlines()
        idx = [i for i, ln in enumerate(lines) if "actions/checkout" in ln]
        assert idx, f"geen checkout-stap in {workflow}"
        for i in idx:
            assert any("ref: ${{ github.ref_name }}" in ln for ln in lines[i:i + 3]), \
                f"checkout zonder branch-tip-pin in {workflow}"
    return check
