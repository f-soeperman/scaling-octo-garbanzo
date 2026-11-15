"""Gedeelde correctie voor de stralings-/plaatsingsfout van het WU-station.

Het eigen Weather-Underground PWS leest op zonnige momenten te warm: een
radiatieve fout die lineair meeschaalt met de instraling (W/m²), bijna nul is
's nachts, en wordt veroorzaakt door directe zon op de (passief geventileerde,
in stille lucht onvoldoende doorspoelde) stralingskap aan de rand van een
zonnige houten schuur. Zie Project 7 (station_accuracy.py / docs/accuracy.html)
voor de diagnose.

Deze module levert één bron-agnostische correctie die zowel het bodemproject
(soil_model.py) als de raam-adviseur (window_advisor.py) gebruiken, zodat de
fout aan de bron verdwijnt in plaats van per project.

    T_gecorrigeerd = T_gemeten − SOLAR_BIAS_SLOPE · max(0, instraling_W/m²)

Alleen het positieve, zon-gedreven surplus wordt verwijderd; de nacht-/basislijn
blijft zoals gemeten (negatieve instraling/None → geen correctie).

KALIBRATIE — SOLAR_BIAS_SLOPE
-----------------------------
De helling wordt empirisch bepaald door station_accuracy.py, dat de bias
(WU − ERA5) fit tegen twee kandidaat-drivers: Open-Meteo (grid) én de eigen WU-
pyranometer (lokaal, co-located → vangt directe-zon/halfbewolkte pieken die het
grid-model uitsmeert). De co-located WU-driver is doorgaans de strakste en dus
de voorkeur; station_accuracy.py print de aanbevolen driver + waarde.

GEKALIBREERD (periode 2026-05-02…05-31, n=718 gekoppelde uren):
  - WU-pyranometer : +0.421 °C/100 W/m², corr(bias) 0.652  → GEKOZEN driver
  - Open-Meteo grid: +0.365 °C/100 W/m², corr(bias) 0.617
De co-located WU-driver vangt de bias het strakst (zoals verwacht), dus
Dat gaf 0.00421, de waarde tot nov 2026.

HERIJKT (nov 2026, 2026-04…10, n=4797 uren, referentie KNMI, eigen pyranometer):
  - intercept + helling : +0.29 °C + 0.289 °C/100 W/m²   → GEKOZEN helling
  - helling alleen      : 0.349 °C/100 W/m² (de helling slokt dan de offset op)
De +0.29 °C die er ook zonder zon staat is het gedeelde microklimaat (buur-
coherentietoets: GEDEELD) en wordt bewust níet gecorrigeerd. Alleen wat met de
zon meeschaalt is de fout van de kap, en dat is de helling uit de fit mét
intercept: per maand stabiel 0.24–0.31 °C/100 W/m². De oude 0.00421 kwam uit
één meimaand tegen ERA5 en trok op een zonnige middag (800 W/m²) ruim 1 °C te
veel af. SOLAR_BIAS_SLOPE = 0.0029. De vorm blijft een zuivere zon-term.
Recalibreren: `python tools/bias_backtest.py --reference knmi --driver wu_solar`
en de helling van "intercept + helling" overnemen.
"""

from __future__ import annotations

from typing import Optional

# °C per W/m². WU-pyranometer-fit tegen KNMI, zie kalibratie-noot hierboven.
SOLAR_BIAS_SLOPE = 0.0029


def correct_temp(temp_c: Optional[float],
                 solar_wm2: Optional[float]) -> Optional[float]:
    """Trek het zon-gedreven warmte-surplus van een WU-temperatuur af.

    Bron-agnostisch: `solar_wm2` mag van de WU-pyranometer of van Open-Meteo
    komen (de aanroeper kiest, met fallback). None-temp → None; None-instraling
    → ongewijzigd (geen correctie); negatieve instraling → geklemd op 0.
    Rondt niet af — de aanroeper rondt volgens eigen conventie.
    """
    if temp_c is None:
        return None
    if solar_wm2 is None:
        return temp_c
    return temp_c - SOLAR_BIAS_SLOPE * max(0.0, solar_wm2)


def bias_estimate(solar_wm2: Optional[float]) -> float:
    """De geschatte °C die `correct_temp` zou aftrekken bij deze instraling —
    handig om als diagnostisch veld (bias_corr) weg te schrijven."""
    return SOLAR_BIAS_SLOPE * max(0.0, solar_wm2 or 0.0)
