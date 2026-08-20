#!/usr/bin/env python3
"""
vent_suggest.py — scenariozoeker + rangschikking voor het avond-koelplan (Project 14).

De tweeling voorspelt al twaalf uur vooruit per kamer, maar beantwoordde nooit de vraag
waar dat voorspellen voor bestaat: *welke* ramen en deuren moeten vanavond open om het
huis echt te koelen? Dit is de zuivere kern: een gecureerde scenario-grammatica over de
beweegbare elementen (~15 sims — geen 2^n-zoektocht: een vaste grammatica is uitlegbaar,
snapshot-testbaar en kan geen fysiek onzinnige combinaties voorstellen), een praktische
filterlaag (regen/windstoten/nacht-veiligheid via de additieve `advice`-blokken in
house_model.json), en een score die het *kleinste effectieve* plan laat winnen.

Alles hier is een zuivere functie over gewone dicts — geen I/O, geen netwerk; de runner
(`cooldown_notify.py`) voert de sims en het Telegram-bericht aan. Zelfde vorm als
`vent_forecast.py`.

Eerlijkheidsgrenzen, bewust in de teksten verwerkt: de deltas zijn model-afgeleid en
alleen op wérkelijk bezochte raamstanden gevalideerd (uncertainty.json zegt dat zelf);
een gesloten huis wisselt in het model exact nul lucht (infiltratie zit in de geleerde
ua_env), dus open-vs-dicht-verschillen zijn een optimistische bovengrens. Vandaar de
zendpoort op `DELTA_MIN_C`, afronding van de kop-delta op 0,5 °C en het "alles open"-
plafond dat nadrukkelijk géén advies is.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Kamer-comfortbanden: read-only meegelift uit de raam-adviseur (zelfde tado-kamernamen),
# net als vent_twin dat doet — één waarheid voor wat "te warm" betekent.
from window_advisor import ROOM_COMFORT

MORNING_H = 8            # het plan loopt tot morgen 08:00 (zelfde horizon als Kinderkamer-nacht)
MARK_H = 7               # het kop-getal per kamer: de temperatuur om 07:00
MARK_TOL_MIN = 30.0      # dichtstbijzijnde rasterpunt binnen een half uur, anders geen mark

RAIN_MM_H = 0.2          # ≥ dit in enig nachtuur → regen-restricties actief
GUST_MS = 14.0           # ≈ 50 km/u windstoten → open klapramen terug naar kiep

DELTA_MIN_C = 0.7        # zendpoort: beste plan moet minstens dit aan som-voordeel geven
                         # (~ de gepoolde 12u-backtestfout — kleiner kan het model niet
                         # onderscheiden, dus dat is geen bericht waard)
OVERCOOL_MARGIN_C = 0.5  # onderkoeling telt pas onder (comfort_low − dit)
OVERCOOL_W = 0.5         # gewicht per °C·h onderkoeling
ACTION_COST = 0.05       # kleine aftrek per handeling: het minimale effectieve plan wint
MAX_PLANS = 2            # hoofdplan + één runner-up in het bericht

SEASON_MONTHS = range(5, 10)   # mei–sep, zelfde poort als de kinderkamer-nachtvoorspelling


# ── Tijd & standen ────────────────────────────────────────────────────────────────────

def hours_until_morning(now: datetime, end_h: int = MORNING_H) -> float:
    """Uren van nu tot morgen `end_h`:00 lokale tijd (de plan-horizon)."""
    target = (now + timedelta(days=1)).replace(hour=end_h, minute=0,
                                               second=0, microsecond=0)
    return (target - now).total_seconds() / 3600.0


def apply_scenario(timeline: list[dict], now: datetime, states: dict) -> list[dict]:
    """Kopie van de timeline met `states` afgedwongen op elke stap vanaf `now`; het
    verleden (de gemelde log) blijft onaangeroerd en het origineel wordt niet gemuteerd.
    Generalisatie van night_forecast.scenario_timeline naar een vrije standen-dict."""
    return [({**step, "states": {**step["states"], **states}}
             if step["t"] >= now else step)
            for step in timeline]


def operable_windows(house: dict) -> dict:
    return {wid: w for wid, w in (house.get("windows") or {}).items()
            if w.get("max_open_area_m2")}


def baseline_states(house: dict) -> dict:
    """Het "doe niets"-nachtscenario waartegen elk plan wordt afgezet: alle beweegbare
    ramen dicht + de deur van de kinderkamer dicht (de vaste avondroutine-aanname, zelfde als
    het hoofdscenario van de nachtvoorspelling). Overige deuren/roosters volgen de
    gemelde log — die standen zijn geen onderdeel van de vraag."""
    states = {wid: "dicht" for wid in operable_windows(house)}
    if "nursery_stair" in (house.get("doors") or {}):
        states["nursery_stair"] = "dicht"
    return states


def scenario_set(house: dict) -> list[dict]:
    """De gecureerde grammatica: per raam een solo, per slaapkamer een "stapel" (raam +
    eigen trapdeur + dak-uitlaat — de lage-inlaat/hoge-uitlaat-route waar de koker met
    deuren op 1.0/3.9/7.0 m en een daklicht op 8.7 m letterlijk voor bestaat), living-
    dwarsventilatie, een huis-stapel, en "alles open" als plafond (nooit advies).
    Afgeleid uit de geometrie — geen hardgecodeerde element-lijst."""
    wins = operable_windows(house)
    doors = house.get("doors") or {}
    room_of = {wid: w.get("room") for wid, w in wins.items()}
    sky = sorted(wid for wid, rid in room_of.items() if rid == "stair")
    # `fixed` deuren (open doorgangen zonder deurblad) zijn geen handeling.
    stack_doors = sorted(d for d, cfg in doors.items()
                         if d.endswith("_stair") and not cfg.get("fixed")
                         and d[: -len("_stair")] in (house.get("rooms") or {}))
    scen = []

    def add(sid, states, ceiling=False):
        scen.append({"id": sid, "states": dict(states), "ceiling": ceiling})

    for wid in sorted(wins):
        if room_of[wid] == "stair":
            continue
        add(f"solo:{wid}", {wid: "open"})

    sky_open = {s: "open" for s in sky}
    for door in stack_doors:
        rid = door[: -len("_stair")]
        for wid in sorted(w for w, r in room_of.items() if r == rid):
            add(f"stapel:{rid}", {wid: "open", door: "open", **sky_open})

    living_w = sorted(w for w, r in room_of.items() if r == "living")
    if len(living_w) >= 2:
        add("dwars:living", {w: "open" for w in living_w})
        hall_chain = [d for d in ("living_hall", "hall_stair")
                      if d in doors and not doors[d].get("fixed")]
        if hall_chain and sky:
            add("stapel:living", {**{w: "open" for w in living_w},
                                  **{d: "open" for d in hall_chain}, **sky_open})

    huis = dict(sky_open)
    for door in stack_doors:
        rid = door[: -len("_stair")]
        huis.update({w: "open" for w, r in room_of.items() if r == rid})
        huis[door] = "open"
    if huis:
        add("stapel:huis", huis)

    add("alles_open", {**{w: "open" for w in (house.get("windows") or {})},
                       **{d: "open" for d in doors}}, ceiling=True)
    return scen


# ── Praktische filterlaag ─────────────────────────────────────────────────────────────

def night_weather(steps: list[dict], now: datetime) -> tuple[bool, bool]:
    """(nat, vlagerig) over de toekomstige stappen: regen ≥ RAIN_MM_H in enig uur, of
    windstoten ≥ GUST_MS."""
    fut = [s.get("weather") or {} for s in steps if s["t"] >= now]
    wet = any((w.get("precip") or 0.0) >= RAIN_MM_H for w in fut)
    gusty = any((w.get("gust") or 0.0) >= GUST_MS for w in fut)
    return wet, gusty


def allowed_state(cfg: dict, want: str, wet: bool, gusty: bool) -> str | None:
    """Wat mag dit raam vannacht, gegeven het weer en zijn `advice`-vlaggen?
    None = element vervalt uit het scenario. Kiepbaar (tilt_frac) mag terugvallen op
    "tilt"; een klapdeur zonder kiepstand valt gewoon af. `night_ok: false` = 's nachts
    nooit vol open (inbraak/veiligheid — het hele plan ís een nachtplan)."""
    if want != "open":
        return want
    adv = cfg.get("advice") or {}
    # Kiep-terugval mag per element uitgezet worden (`advice.tilt_ok: false`): het platte
    # daklicht heeft tilt_frac 1.0 (zijn "open" ís de kierstand) maar hoort bij regen
    # gewoon dicht — een kier in een plat dak vangt water.
    tilt_ok = adv.get("tilt_ok", bool(cfg.get("tilt_frac")))
    if not adv.get("night_ok", True):
        return "tilt" if tilt_ok else None
    if wet and not adv.get("rain_ok", False):
        return "tilt" if tilt_ok else None
    if gusty:
        return "tilt" if tilt_ok else None
    return "open"


def practical_filter(scenarios: list[dict], house: dict, wet: bool,
                     gusty: bool) -> list[dict]:
    """Snoei de scenario's op het weer en de veiligheidsvlaggen vóórdat er gesimuleerd
    wordt. Deuren zijn binnenshuis en blijven ongemoeid; een scenario zonder enig
    (deels) open raam vervalt — er valt niets meer te ventileren. Het plafond
    ("alles open") wordt bewust niet gesnoeid: het is een bovengrens, geen advies."""
    wins = house.get("windows") or {}
    out, seen = [], set()
    for sc in scenarios:
        if sc.get("ceiling"):
            out.append(sc)
            continue
        states, beperkt = {}, False
        for eid, want in sc["states"].items():
            cfg = wins.get(eid)
            if cfg is None:                  # deur — geen weer-restrictie
                states[eid] = want
                continue
            allowed = allowed_state(cfg, want, wet, gusty)
            if allowed is None:
                beperkt = True
                continue
            beperkt = beperkt or allowed != want
            states[eid] = allowed
        if not any(states.get(w) in ("open", "tilt") for w in wins):
            continue
        # Twee scenario's die na het snoeien op dezelfde standen uitkomen (bv. de
        # living-dwarsventilatie die 's nachts tot het kiepraam reduceert) zijn één sim
        # en één advies waard, niet twee.
        key = frozenset(states.items())
        if key in seen:
            continue
        seen.add(key)
        out.append({**sc, "states": states, "beperkt": beperkt})
    return out


# ── Score ─────────────────────────────────────────────────────────────────────────────

def room_bands(house: dict) -> dict:
    """{kamer-id: (low, high)} voor de advieskamers — de comfortbanden van de
    raam-adviseur, vertaald van tado-naam naar zone-id via `from_window_data`."""
    bands = {}
    for rid, r in (house.get("rooms") or {}).items():
        name = r.get("from_window_data")
        if name and name in ROOM_COMFORT:
            bands[rid] = ROOM_COMFORT[name]
    return bands


def mark_temp(series: list[tuple], now: datetime, hour: int = MARK_H) -> float | None:
    """Temperatuur op het merkuur morgenochtend (dichtstbijzijnde rasterpunt binnen
    MARK_TOL_MIN), zoals night_stats dat voor de nachtvoorspelling doet."""
    if not series:
        return None
    base = now if hour >= 21 else now + timedelta(days=1)
    mark = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    t, v = min(series, key=lambda s: abs((s[0] - mark).total_seconds()))
    return v if abs((t - mark).total_seconds()) <= MARK_TOL_MIN * 60 else None


def score_plan(base_series: dict, scen_series: dict, bands: dict, now: datetime,
               n_actions: int) -> dict | None:
    """Score één scenario tegen de dicht-baseline. Per advieskamer: voordeel =
    (T_dicht@07 − T_scenario@07), alleen voor kamers die om 07:00 boven hun comfort-
    band zouden zitten, en geklemd op comfort_low — koelen ónder de band is niets
    waard. Onderkoeling (graad-uren onder low − OVERCOOL_MARGIN_C) telt als straf,
    en elke handeling kost een beetje: het kleinste effectieve plan wint gelijkspel.
    None als geen enkele kamer een bruikbaar merkpunt heeft."""
    rooms, benefit_sum, overcool_sum = {}, 0.0, 0.0
    scored = False
    for rid, (low, high) in bands.items():
        b07 = mark_temp(base_series.get(rid) or [], now)
        s07 = mark_temp(scen_series.get(rid) or [], now)
        if b07 is None or s07 is None:
            continue
        scored = True
        needs = b07 > high
        benefit = max(0.0, b07 - max(s07, low)) if needs else 0.0
        oc = 0.0
        floor = low - OVERCOOL_MARGIN_C
        for t, v in scen_series.get(rid) or []:
            if t >= now and v < floor:
                oc += (floor - v) * 0.25            # kwartierstappen → °C·h
        benefit_sum += benefit
        overcool_sum += oc * OVERCOOL_W
        rooms[rid] = {"b07": b07, "s07": s07, "needs": needs, "benefit": benefit,
                      "overcool_ch": round(oc, 2)}
    if not scored:
        return None
    return {"rooms": rooms, "benefit": benefit_sum, "overcool": overcool_sum,
            "score": benefit_sum - overcool_sum - ACTION_COST * n_actions}


def rank_plans(scored: list[dict]) -> list[dict]:
    """Adviesplannen (niet-plafond) op score, hoogste eerst."""
    return sorted([s for s in scored if not s.get("ceiling")],
                  key=lambda s: s["score"], reverse=True)


def should_send(now: datetime, ranked: list[dict]) -> bool:
    """Zendpoort: zomerseizoen, minstens één kamer die koeling nodig heeft, en een
    beste plan dat boven de onderscheidingsgrens uitkomt. Anders stilte — een koele
    avond heeft geen koelplan nodig en een marginaal plan is ruis."""
    if now.month not in SEASON_MONTHS:
        return False
    if not ranked:
        return False
    best = ranked[0]
    if not any(r["needs"] for r in best["rooms"].values()):
        return False
    return best["score"] >= DELTA_MIN_C


# ── Berichttekst ──────────────────────────────────────────────────────────────────────

def element_name(eid: str, house: dict) -> str:
    """Korte naam voor in het bericht: `advice.naam` als die er is, anders het label,
    anders het id."""
    for kind in ("windows", "doors", "vents"):
        cfg = (house.get(kind) or {}).get(eid)
        if cfg:
            adv = cfg.get("advice") or {}
            return adv.get("naam") or cfg.get("label") or eid
    return eid


def actions_text(states: dict, house: dict) -> str:
    """"X open, Y op kiep, …" — alleen de open/tilt-handelingen, deuren achteraan."""
    wins = house.get("windows") or {}
    parts = []
    for eid, st in sorted(states.items(), key=lambda kv: (kv[0] not in wins, kv[0])):
        if st == "open":
            parts.append(f"{element_name(eid, house)} open")
        elif st == "tilt":
            parts.append(f"{element_name(eid, house)} op kiep")
    return ", ".join(parts)


def build_message(now: datetime, ranked: list[dict], ceiling: dict | None,
                  house: dict, out_min: float | None, wet: bool,
                  band_line: str | None = None) -> str:
    """Het avondbericht: het beste plan met per kamer "X° om 07:00 i.p.v. Y°", één
    runner-up, en het alles-open-plafond nadrukkelijk als bovengrens. De kop-delta is
    op 0,5 °C afgerond — preciezer kan het model niet waarmaken (zie de module-
    docstring); de kamer-getallen houden één decimaal, zoals de nachtvoorspelling."""
    from shared_const import format_date_nl
    best = ranked[0]
    lines = [f"🌬 <b>Koelplan voor vannacht</b> — {format_date_nl(now.date())}"]
    if out_min is not None:
        lines.append(f"Buiten koelt naar {out_min:.0f}°")

    def halfjes(x):
        return round(x * 2) / 2

    lines.append(f"\nBeste plan (samen tot ~{halfjes(best['benefit']):.1f}° koeler om 07:00):")
    lines.append(f"• {actions_text(best['states'], house)}")
    for rid, r in sorted(best["rooms"].items(), key=lambda kv: -kv[1]["benefit"]):
        if not r["needs"]:
            continue
        label = (house.get("rooms", {}).get(rid) or {}).get("label") or rid
        if r["benefit"] < 0.1:
            # Te warm maar dit plan doet er niets aan — dat verzwijgen zou de indruk
            # wekken dat het plan het hele huis dekt.
            lines.append(f"→ {label}: blijft ~{r['s07']:.1f}° (dit plan helpt hier niet)")
        else:
            lines.append(f"→ {label}: <b>{r['s07']:.1f}°</b> om 07:00 (dicht: {r['b07']:.1f}°)")
    if band_line:
        lines.append(band_line)

    for alt in ranked[1:MAX_PLANS]:
        if alt["score"] < DELTA_MIN_C:
            break
        lines.append(f"\nOok goed (~{halfjes(alt['benefit']):.1f}°): "
                     f"{actions_text(alt['states'], house)}")

    if ceiling and ceiling.get("benefit", 0.0) > best["benefit"] + 0.25:
        lines.append(f"\n🏠 Alles open zou ~{halfjes(ceiling['benefit']):.1f}° geven — "
                     "bovengrens, geen advies.")
    if wet:
        lines.append("🌧 Regen verwacht — open standen waar nodig teruggebracht naar kiep.")
    return "\n".join(lines)
