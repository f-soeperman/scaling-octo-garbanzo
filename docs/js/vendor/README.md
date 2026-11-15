# Gevendorde bibliotheken

Onveranderde kopieën uit de npm-releases (allemaal MIT), zodat de dashboards
`script-src 'self'` kunnen voeren i.p.v. een hele CDN-host toe te staan.

| Bestand | Pakket |
|---|---|
| `chart.umd.js` | chart.js 4.4.1 |
| `chartjs-plugin-annotation.min.js` | chartjs-plugin-annotation 3.0.1 |
| `chartjs-adapter-date-fns.bundle.min.js` | chartjs-adapter-date-fns 3.0.0 |
| `three/*` | three 0.147.0 (`build/` + `examples/js/`) |

Bijwerken: `npm pack <pakket>@<versie>`, het bestand hierheen kopiëren en de
`integrity`-hash in de HTML opnieuw berekenen
(`openssl dgst -sha384 -binary <bestand> | base64`).
`tests/test_privacy.py` bewaakt dat bestand en hash overeenkomen.
