#!/usr/bin/env python3
"""campingmap_build.py — genereert docs/js/campingmap.js (Project 15).

Eenmalige/handmatige build-tool (zelfde status als train_surrogate.py voor
Project 13's surrogaat): geen pytest-module, niet in CI. Haalt Natural Earth
1:50m admin-0 country boundaries op, clipt/vereenvoudigt ze tot een kleine
contourset rond de dertien kampeerstreken (NL/FR + buurlanden als context),
projecteert (equirechthoekig met een cos(lat0)-correctie) en schrijft het
resultaat als een klein statisch JS-contract (`CAMPING_MAP`) dat het
kaartpaneel op docs/camping.html tekent.

Herdraaien is alleen nodig als de kaart-bounding-box, het landenlijstje of de
vereenvoudigingstolerantie wijzigt — de landsgrenzen zelf veranderen niet.
Committed output: docs/js/campingmap.js (net als surrogate.json — een
build-artefact, geen gegenereerd run-artefact van een workflow).

Vereist netwerktoegang (haalt eenmalig ~3 MB GeoJSON op van
nvkelso/natural-earth-vector — geen secret, geen repo-data).
"""

import json
import math
import os
import sys
import urllib.request

NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
          "master/geojson/ne_50m_admin_0_countries.geojson")
CACHE_PATH = os.getenv("CAMPINGMAP_NE_CACHE", "/tmp/ne_50m_admin_0_countries.geojson")
OUT_PATH = os.getenv("CAMPINGMAP_OUT", "docs/js/campingmap.js")

# Kampeer-window: lon/lat-bounding box die alle dertien streken + genoeg
# buurland-context dekt. Bewust ONGEWIJZIGD gehouden toen Oostenrijk en
# Noordwest-Frankrijk vervielen voor de Oost-Franse steden (aug 2026): de
# noord-zuid-spreiding (Utrecht t/m Valence) is nauwelijks kleiner geworden,
# dus een kleinere box zou vooral de kaart onnodig portrait-achtig maken
# zonder de crowding rond de nieuwe, dicht opeen liggende steden op te
# lossen — dat leunt op LABEL_OFFSET, niet op zoomen.
LON_MIN, LON_MAX = -6.0, 19.2
LAT_MIN, LAT_MAX = 42.5, 54.2
VIEW_W = 1000
LAT0 = 48.0  # referentiebreedte voor de cos-correctie
COS_LAT0 = math.cos(math.radians(LAT0))
SCALE = VIEW_W / ((LON_MAX - LON_MIN) * COS_LAT0)
VIEW_H = (LAT_MAX - LAT_MIN) * SCALE

# "focus" = de landen waar de streken in liggen (dikke inktlijn); "ctx" =
# buurlanden, alleen voor oriëntatie (dunne, verbleekte lijn). Oostenrijk
# schoof van focus naar ctx toen de laatste AT-streek verviel (aug 2026) —
# blijft in beeld voor de Alpen-oriëntatie bij Chamonix/Annecy, maar draagt
# geen streek meer.
WANTED = {
    "Netherlands": "focus", "France": "focus",
    "Austria": "ctx", "Belgium": "ctx", "Luxembourg": "ctx", "Germany": "ctx",
    "Switzerland": "ctx", "Italy": "ctx", "Czechia": "ctx", "Slovenia": "ctx",
    "Denmark": "ctx", "United Kingdom": "ctx", "Spain": "ctx", "Poland": "ctx",
    "Liechtenstein": "ctx", "Monaco": "ctx", "Andorra": "ctx",
}

# Hand-getunede label-offsets [dx, dy, anchor] in geprojecteerde px, zodat de
# twee dichte clusters leesbaar blijven — de Zuidoost-Alpen-hoek (grenoble/
# chambery/annecy/chamonix/valbonnais/valence, aug 2026: allemaal binnen een
# klein blokje sinds de focus op Oost-Frankrijk verschoof) en de Elzas-steden
# (mulhouse/colmar, amper 20px verticaal uiteen op deze schaal). camping.js
# valt terug op een vaste default voor een streek die hier ontbreekt.
LABEL_OFFSET = {
    "utrecht": [14, -6, "start"],
    "grenoble": [-52, 22, "end"],
    "chambery": [-64, -6, "end"],
    "annecy": [-6, -26, "middle"],
    "chamonix": [26, -6, "start"],
    "vitry_le_francois": [14, -10, "start"],
    "besancon": [4, -40, "middle"],
    "valbonnais": [-8, 40, "middle"],
    "dijon": [-18, -4, "end"],
    "montbeliard": [20, 40, "start"],
    "mulhouse": [26, 22, "start"],
    "colmar": [22, -18, "start"],
    "valence": [-14, 34, "end"],
}

# Mirror van camping_forecast.py's REGIONS (id/label/country/lat/lon) — bewust
# hier gedupliceerd i.p.v. uit het live artefact gelezen: dit zijn de vaste
# referentiepunten waarop Open-Meteo per streek wordt bevraagd (aug 2026: de
# gevraagde steden/dorpen zelf, geen representatieve streek-benadering meer —
# zie camping_forecast.py), geen gemeten data. Een streek die tijdelijk
# "unavailable" is (fetch-fout) draagt in het artefact geen lat/lon; de kaart
# moet toch alle dertien pins tonen. Bij een wijziging in camping_forecast.py's
# REGIONS moet dit lijstje meeveranderen — er is bewust geen runtime-koppeling
# (dit is een build-time contour/pin-contract, geen live data-laag).
REGIONS = [
    {"id": "utrecht", "label": "Utrecht", "country": "NL", "lat": 52.09, "lon": 5.12},
    {"id": "grenoble", "label": "Grenoble", "country": "FR", "lat": 45.19, "lon": 5.72},
    {"id": "chambery", "label": "Chambéry", "country": "FR", "lat": 45.56, "lon": 5.92},
    {"id": "annecy", "label": "Annecy", "country": "FR", "lat": 45.90, "lon": 6.13},
    {"id": "chamonix", "label": "Chamonix", "country": "FR", "lat": 45.92, "lon": 6.87},
    {"id": "vitry_le_francois", "label": "Vitry-le-François", "country": "FR", "lat": 48.73, "lon": 4.58},
    {"id": "besancon", "label": "Besançon", "country": "FR", "lat": 47.24, "lon": 6.02},
    {"id": "valbonnais", "label": "Valbonnais", "country": "FR", "lat": 44.98, "lon": 5.92},
    {"id": "dijon", "label": "Dijon", "country": "FR", "lat": 47.32, "lon": 5.04},
    {"id": "montbeliard", "label": "Montbéliard", "country": "FR", "lat": 47.51, "lon": 6.80},
    {"id": "mulhouse", "label": "Mulhouse", "country": "FR", "lat": 47.75, "lon": 7.34},
    {"id": "colmar", "label": "Colmar", "country": "FR", "lat": 48.08, "lon": 7.36},
    {"id": "valence", "label": "Valence", "country": "FR", "lat": 44.93, "lon": 4.89},
]


def project(lon, lat):
    x = (lon - LON_MIN) * COS_LAT0 * SCALE
    y = (LAT_MAX - lat) * SCALE
    return x, y


def ring_touches_bbox(ring, margin=2.0):
    for lon, lat in ring:
        if LON_MIN - margin <= lon <= LON_MAX + margin and LAT_MIN - margin <= lat <= LAT_MAX + margin:
            return True
    return False


def rdp(points, eps):
    """Ramer-Douglas-Peucker, iteratief, op (x, y)-tuples in projected px."""
    if len(points) < 3:
        return points
    stack = [(0, len(points) - 1)]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        max_d, max_i = -1.0, -1
        for i in range(start + 1, end):
            xi, yi = points[i]
            d = math.hypot(xi - x1, yi - y1) if norm == 0 else abs(dy * xi - dx * yi + x2 * y1 - y2 * x1) / norm
            if d > max_d:
                max_d, max_i = d, i
        if max_d > eps:
            keep[max_i] = True
            stack.append((start, max_i))
            stack.append((max_i, end))
    return [p for p, k in zip(points, keep) if k]


def ring_to_path(ring, eps):
    pts = rdp([project(lon, lat) for lon, lat in ring], eps)
    if len(pts) < 3:
        return None
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"


def fetch_ne_geojson():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            return json.load(f)
    print(f"downloading {NE_URL} …", file=sys.stderr)
    with urllib.request.urlopen(NE_URL, timeout=60) as resp:
        raw = resp.read()
    with open(CACHE_PATH, "wb") as f:
        f.write(raw)
    return json.loads(raw)


def build_borders(geojson):
    out = {"focus": [], "ctx": []}
    for feat in geojson["features"]:
        name = feat["properties"].get("ADMIN")
        if name not in WANTED:
            continue
        kind = WANTED[name]
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        eps = 0.9 if kind == "focus" else 1.4  # tolerantie in geprojecteerde px
        paths = []
        for poly in polys:
            outer_ring = poly[0]
            if not ring_touches_bbox(outer_ring):
                continue
            d = ring_to_path(outer_ring, eps)
            if d:
                paths.append(d)
        if paths:
            out[kind].append({"name": name, "d": " ".join(paths)})
    return out


def render_js(borders):
    def js_str(s):
        return json.dumps(s)

    lines = [
        "// campingmap.js — Project 15: statisch, vooraf gegenereerd kaartcontract voor",
        "// het kaartpaneel op het Kampeerkompas-dashboard (camping.js bouwt de pins).",
        "//",
        "// De landsgrenzen zijn geen live kaartlaag (CSP staat geen tegel-CDN toe en",
        "// hoort ook niet bij een statische GitHub Pages-site) maar een eenmalig",
        "// vereenvoudigd contourbestand: Natural Earth 1:50m admin-0 countries,",
        "// geclipt op de kampeer-window (lon -6..19.2, lat 42.5..54.2), vereenvoudigd",
        "// met Ramer-Douglas-Peucker en geprojecteerd (equirechthoekig met een",
        "// cos(48°)-correctie, zodat Nederland en Frankrijk niet vervormen t.o.v.",
        "// elkaar). Regenereren: `python3 tools/campingmap_build.py`.",
        "// Geladen vóór camping.js; definieert de globale `CAMPING_MAP`.",
        '"use strict";',
        "",
        "const CAMPING_MAP = {",
        f"  viewW: {VIEW_W},",
        f"  viewH: {VIEW_H:.1f},",
        "  // project(lon, lat) -> [x, y] moet clientside met dezelfde formule (zie",
        "  // camping.js) omdat de pins uit de live regio-lat/lon in camping_data.json",
        "  // komen, niet uit dit statische bestand.",
        f"  proj: {{ lonMin: {LON_MIN}, latMax: {LAT_MAX}, cosLat0: {COS_LAT0:.6f}, scale: {SCALE:.4f} }},",
        f"  labelOffset: {json.dumps(LABEL_OFFSET)},",
        f"  regions: {json.dumps(REGIONS)},",
        "  borders: {",
    ]
    for kind in ("focus", "ctx"):
        lines.append(f"    {kind}: [")
        for c in borders[kind]:
            lines.append(f"      {{ name: {js_str(c['name'])}, d: {js_str(c['d'])} }},")
        lines.append("    ],")
    lines.append("  },")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main():
    geojson = fetch_ne_geojson()
    borders = build_borders(geojson)
    js = render_js(borders)
    with open(OUT_PATH, "w") as f:
        f.write(js)
    print(f"wrote {OUT_PATH} ({len(js.encode('utf-8'))} bytes); "
          f"focus={[c['name'] for c in borders['focus']]} "
          f"ctx={[c['name'] for c in borders['ctx']]}")


if __name__ == "__main__":
    main()
