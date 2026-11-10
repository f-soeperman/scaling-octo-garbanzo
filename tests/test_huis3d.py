"""De 3D-pagina (docs/huis3d.html) is een subpagina van het Ventilatie-dashboard.

Ze toont de gemelde raamstanden en kamertemperaturen, dus ze moet dezelfde
token-poort dragen als vent.html en mag — net als elk ander dashboard — niets
schrijven. Bewaakt verder de CSP-/SRI-afspraken uit CLAUDE.md voor de enige
pagina die three.js van de CDN laadt.
"""

import os
import re

_DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")


def _read(*parts: str) -> str:
    return open(os.path.join(_DOCS, *parts), encoding="utf-8").read()


def test_pagina_is_gepoort_op_token_en_artefact_gist():
    js = _read("js", "huis3d.js")
    gate = js.index("CONFIG.githubToken && CONFIG.artefactGistId")
    assert gate < js.index("h3ReadArtefacts(["), "poort moet vóór de fetch staan"


def test_echte_indeling_komt_alleen_uit_de_prive_gist():
    """De standaardindeling in de broncode is verzonnen. Een echte indeling leest de
    pagina uit de privé artefact-gist — nooit van een pad onder docs/, want dat is
    publiek geserveerd."""
    js = _read("js", "huis3d.js")
    assert '"huis3d_layout.json"' in js
    assert not os.path.exists(os.path.join(_DOCS, "huis3d_layout.json"))
    reader = js[js.index("async function h3ReadArtefacts"):js.index("function h3Layout")]
    assert "api.github.com/gists/" in reader
    assert "artefactReadJSON" not in js, "die helper valt terug op een publiek docs/-pad"


def test_pagina_schrijft_niets():
    """Een wissel in 3D is een lokale wat-als, geen melding: geen Gist-schrijf,
    geen opslag in de browser."""
    js = re.sub(r"(^|\s)//[^\n]*", " ", _read("js", "huis3d.js"))
    for verboden in ("gistWriteFile", "localStorage.setItem", "method:"):
        assert verboden not in js


def test_geen_inline_script_en_cdn_met_sri():
    html = _read("huis3d.html")
    csp = re.search(r'Content-Security-Policy" content="(.*?)"', html, re.DOTALL).group(1)
    script_src = re.search(r"script-src([^;]*);", csp).group(1)
    assert "unsafe-inline" not in script_src and "unsafe-eval" not in script_src
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.DOTALL)
    assert scripts
    for attrs, body in scripts:
        assert not body.strip(), "inline <script> is door de CSP verboden"
        if "https://" in attrs:
            assert re.search(r"/npm/[\w.-]+@\d+\.\d+\.\d+/", attrs), "CDN-versie moet exact gepind zijn"
            assert 'integrity="sha384-' in attrs and "crossorigin" in attrs
    assert not re.search(r"\son\w+=", html), "geen inline event-handlers"


def test_netwerkfysica_komt_uit_de_speeltuin():
    """Geen tweede port van de druksolver: de pagina laadt speeltuin.js vóór het
    eigen script en definieert de solver niet opnieuw."""
    html, js = _read("huis3d.html"), _read("js", "huis3d.js")
    assert html.index("js/speeltuin.js") < html.index("js/huis3d.js")
    assert "buildOpeningsJS(" in js and "solveNetwork(" in js
    assert not re.search(r"function\s+(solveNetwork|buildOpeningsJS|massflow)\b", js)


def test_speeltuin_versie_is_op_beide_paginas_gelijk():
    v = [re.search(r"js/speeltuin\.js\?v=(\d+)", _read(p)).group(1) for p in ("vent.html", "huis3d.html")]
    assert v[0] == v[1]


def test_bereikbaar_vanaf_het_ventilatie_dashboard():
    assert 'href="huis3d.html"' in _read("vent.html")
    assert 'href="vent.html"' in _read("huis3d.html")
