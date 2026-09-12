#!/usr/bin/env python3
"""campingmap_build.py — genereert docs/js/campingmap.js (Project 15).

Eenmalige/handmatige build-tool (zelfde status als train_surrogate.py voor
Project 13's surrogaat): geen pytest-module, niet in CI. Haalt Natural Earth
1:50m admin-0 country boundaries op, clipt/vereenvoudigt ze tot een kleine
contourset rond de vier steden (NL/DE/FR/ES + buurlanden als context),
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

# Reis-window: lon/lat-bounding box die alle vier de steden + genoeg
# buurland-context dekt. Bij de stedenwissel (sep 2026) moest de box wél mee:
# Madrid ligt op 40.4° en viel ruim onder de oude ondergrens van 42.5°, dus de
# pin zou buiten de viewBox vallen. Naar het zuiden tot 39° (marge onder
# Madrid) en naar het westen tot -9.8° zodat het Iberisch schiereiland als
# herkenbare vorm in beeld komt i.p.v. half afgesneden; in het oosten is 16.5°
# genoeg voor Berlijn met wat Poolse context erachter.
LON_MIN, LON_MAX = -9.8, 16.5
LAT_MIN, LAT_MAX = 39.0, 54.2
VIEW_W = 1000
LAT0 = 46.5  # referentiebreedte voor de cos-correctie (midden van de nieuwe box)
COS_LAT0 = math.cos(math.radians(LAT0))
SCALE = VIEW_W / ((LON_MAX - LON_MIN) * COS_LAT0)
VIEW_H = (LAT_MAX - LAT_MIN) * SCALE

# "focus" = de landen waar de steden in liggen (dikke inktlijn); "ctx" =
# buurlanden, alleen voor oriëntatie (dunne, verbleekte lijn). Duitsland en
# Spanje schoven van ctx naar focus bij de stedenwissel (sep 2026); Oostenrijk
# bleef ctx (geen stad meer sinds aug 2026) en Portugal kwam erbij, omdat een
# Iberisch schiereiland zonder westrand niet als schiereiland leest.
WANTED = {
    "Netherlands": "focus", "France": "focus", "Germany": "focus", "Spain": "focus",
    "Austria": "ctx", "Belgium": "ctx", "Luxembourg": "ctx", "Portugal": "ctx",
    "Switzerland": "ctx", "Italy": "ctx", "Czechia": "ctx", "Slovenia": "ctx",
    "Denmark": "ctx", "United Kingdom": "ctx", "Poland": "ctx",
    "Liechtenstein": "ctx", "Monaco": "ctx", "Andorra": "ctx",
}

# Hand-getunede label-offsets [dx, dy, anchor] in geprojecteerde px. Sinds de
# stedenwissel (sep 2026) is het hand-tunen grotendeels overbodig: vier steden
# over half Europa hebben geen clusters meer die overlappen (de dichtste twee,
# Utrecht en Berlijn, liggen ~315px uit elkaar), dus ze staan allemaal op de
# gewone "label rechts van de pin"-stand. Blijft staan als expliciet contract —
# camping.js valt terug op een vaste default voor een stad die hier ontbreekt.
LABEL_OFFSET = {
    "utrecht": [14, -6, "start"],
    "berlijn": [14, -6, "start"],
    "parijs": [14, -6, "start"],
    "madrid": [14, -6, "start"],
}

# Mirror van camping_forecast.py's REGIONS (id/label/country/lat/lon) — bewust
# hier gedupliceerd i.p.v. uit het live artefact gelezen: dit zijn de vaste
# referentiepunten waarop Open-Meteo per stad wordt bevraagd, geen gemeten
# data. Een stad die tijdelijk "unavailable" is (fetch-fout) draagt in het
# artefact geen lat/lon; de kaart moet toch alle vier de pins tonen. Bij een
# wijziging in camping_forecast.py's REGIONS moet dit lijstje meeveranderen —
# er is bewust geen runtime-koppeling (dit is een build-time contour/pin-
# contract, geen live data-laag).
# Zelfde volgorde als camping_forecast.py's REGIONS (thuisbasis eerst, daarna
# noord→zuid) — het dashboard toont ze in deze volgorde.
REGIONS = [
    {"id": "utrecht", "label": "Utrecht", "country": "NL", "lat": 52.09, "lon": 5.12},
    {"id": "berlijn", "label": "Berlijn", "country": "DE", "lat": 52.52, "lon": 13.40},
    {"id": "parijs", "label": "Parijs", "country": "FR", "lat": 48.86, "lon": 2.35},
    {"id": "madrid", "label": "Madrid", "country": "ES", "lat": 40.42, "lon": -3.70},
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
        # Uit de constanten opgebouwd i.p.v. met de hand meegeschreven — deze
        # regel liep bij de stedenwissel anders stilzwijgend achter op de box.
        f"// geclipt op het reis-window (lon {LON_MIN}..{LON_MAX}, lat {LAT_MIN}..{LAT_MAX}),",
        "// vereenvoudigd met Ramer-Douglas-Peucker en geprojecteerd (equirechthoekig",
        f"// met een cos({LAT0:g}°)-correctie, zodat de landen onderling niet vervormen).",
        "// Regenereren: `python3 tools/campingmap_build.py`.",
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
