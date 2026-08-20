"""Tests voor het nachtvoorspelling-verificatiespoor (`tools/night_verify.py`) en de
wekelijkse evaluatie-workflow (twin-eval.yml). Geen netwerk: de verificatie draait op
een synthetisch gelogde nacht tegen een handgemaakte meetreeks."""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta

from shared_const import TZ

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "night_verify", os.path.join(_ROOT, "tools", "night_verify.py"))
nv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv)

# Ruim in het verleden zodat "nacht nog niet om" nooit per ongeluk triggert.
EVE = datetime(2026, 7, 1, 18, 45, tzinfo=TZ)


def _row(offset: float = 0.3, n: int = 12) -> dict:
    series = [[int((EVE + timedelta(minutes=15 * i)).timestamp()),
               int(round((21.0 + offset) * 10))] for i in range(n)]
    return {"date": EVE.date().isoformat(), "t": EVE.isoformat(), "sent": True,
            "tog": "1.0 tog",
            "scenarios": {"dicht": {"min": 20.0, "max": 22.0, "mean": 21.0,
                                    "marks": {"23": 21.0 + offset}}},
            "series_dicht": series}


def _measured(n: int = 12):
    ts = [EVE + timedelta(minutes=15 * i) for i in range(n)]
    # Merkuur 23:00 heeft óók een meetpunt nodig (binnen MARK_TOL_MIN).
    ts.append(EVE.replace(hour=23, minute=0))
    ts.sort()
    return (ts, [21.0] * len(ts))


def test_afgeronde_nacht_scoort_de_ingebouwde_offset():
    """Een gelogde voorspelling die structureel +0.3° naast de meting zit moet exact
    die 0.3 als RMSE én bias terugrapporteren — de hele reden van het spoor."""
    v = nv.verify_night(_row(0.3), _measured())
    assert v is not None
    assert abs(v["rmse"] - 0.3) < 0.01
    assert abs(v["bias"] - 0.3) < 0.01
    assert v["marks"]["23"] == 0.3
    assert v["n"] == 12


def test_lopende_nacht_wordt_overgeslagen():
    """Een nacht waarvan de serie nog in de toekomst eindigt is niet af te rekenen."""
    row = _row()
    future = datetime.now(TZ) + timedelta(hours=6)
    row["series_dicht"] = [[int(future.timestamp()), 210]]
    assert nv.verify_night(row, _measured()) is None


def test_nacht_zonder_metingen_wordt_overgeslagen():
    assert nv.verify_night(_row(), ([], [])) is None


def test_aggregatie_weegt_op_punten():
    """De gepoolde RMSE weegt nachten naar hun #meetpunten, niet plat per nacht."""
    nights = [{"date": "2026-07-01", "sent": True, "n": 10, "rmse": 1.0, "bias": 1.0,
               "marks": {"7": 1.0}},
              {"date": "2026-07-02", "sent": True, "n": 30, "rmse": 0.0, "bias": 0.0,
               "marks": {}}]
    agg = nv._agg(nights)
    assert agg["nights"] == 2
    assert abs(agg["rmse"] - (10 / 40) ** 0.5) < 1e-9
    assert abs(agg["bias"] - 0.25) < 1e-9
    assert agg["bias_07"] == 1.0


def test_workflow_checkout_pint_branch_tip(assert_checkout_pinned):
    """twin-eval.yml commit een groeiend spoor (twin_eval.json) — branch-tip-pin
    verplicht, zelfde reden als station-accuracy."""
    assert_checkout_pinned("twin-eval.yml")
