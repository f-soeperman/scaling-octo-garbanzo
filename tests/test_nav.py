"""Elk dashboard draagt dezelfde navigatierij, in dezelfde volgorde.

Een nieuw tabblad kwam eerder maar op een paar pagina's terecht (potje stond
niet bij Ramen, en potje zelf linkte maar naar drie pagina's). Wie hier een
pagina toevoegt, moet hem dus op álle pagina's in de <nav> zetten.
camping.html is bewust standalone (Project 15) en model.html is een subpagina
van Bodem; die doen niet mee.
"""

import os
import re

import pytest

_DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

NAV = ["index.html", "mowing.html", "window.html", "vent.html",
       "grafiek.html", "accuracy.html", "potje.html"]


def _nav_hrefs(page: str) -> list[str]:
    html = open(os.path.join(_DOCS, page), encoding="utf-8").read()
    navs = re.findall(r'<nav aria-label="Dashboards".*?</nav>', html, re.DOTALL)
    assert len(navs) == 1, f"{page}: verwacht precies één Dashboards-<nav>"
    return re.findall(r'href="([^"]+)"', navs[0])


@pytest.mark.parametrize("page", NAV)
def test_navigatie_is_overal_gelijk(page):
    hrefs = [h for h in _nav_hrefs(page) if h in NAV]
    assert hrefs == NAV


@pytest.mark.parametrize("page", NAV)
def test_huidige_pagina_is_gemarkeerd(page):
    html = open(os.path.join(_DOCS, page), encoding="utf-8").read()
    assert re.search(rf'href="{re.escape(page)}" aria-current="page"', html)
