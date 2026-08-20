// camping.js — Kampeerkompas (Project 15), ronde 2: posterthema + dag/nacht-
// tegels + verdieping. Leespagina zonder Gist/token en zonder Chart.js: alles
// is kale divs, gevoed door camping_data.json (gegenereerd door de Action).
"use strict";

const state = { data: null, waarom: false };

const CAT_LABEL = { top: "top", goed: "goed", matig: "matig", slecht: "slecht", rood: "rode vlag" };
const LEVEL_LABEL = { yellow: "geel", orange: "oranje", red: "rood" };
const LAND_NAAM = { NL: "Nederland", AT: "Oostenrijk", FR: "Frankrijk" };
const VLAG_TEKST = {
  waarschuwing: "officiële waarschuwing",
  hitte_extreem: "extreme hitte",
  koude_nacht_extreem: "veel te koude nacht",
  storm: "zware windstoten",
  stortregen: "zware regen",
  stortregen_nacht: "zware regen 's nachts",
};
// Datumnummer op de dagtegel: lichte tekst op donkere vullingen, navy op lichte.
// (matig = stormblauw → licht, slecht = amber → donker; zie de palet-comment.)
const TILE_TEKST = { top: "tile-licht", goed: "tile-donker", matig: "tile-licht",
                     slecht: "tile-donker", rood: "tile-licht" };
// "Waarom?"-toggle: één icoon per matig/slecht-cel voor de dominante reden
// (main_reason uit het artefact — de zwaarste reden van de zwaarste helft).
const REDEN_ICOON = {
  dagregen_licht: "☂", dagregen_matig: "☂", dagregen_zwaar: "☂",
  wisselvallig: "☂", wisselvallig_nat: "☂",
  nachtregen_licht: "☂", nachtregen_matig: "☂", nachtregen_zwaar: "☂", nachtregen_wisselvallig: "☂",
  hitte_naderend: "☀", hitte: "☀",
  koele_nacht: "❄", koude_nacht: "❄", te_koude_nacht: "❄",
  dauw_krap: "💧", dauw_nat: "💧",
  wind_fris: "💨", wind_hard: "💨",
};
// Zelfde toggle, maar dan voor rode cellen: de vlag die 'm rood máákte
// (red_flags), niet de score-reden — "waarschuwing" heeft al zijn eigen ⚠
// en staat hier bewust niet in. Vaste volgorde bij meerdere vlaggen tegelijk
// (zeldzaam), zodat het icoon niet met de dag-tot-dag JSON-volgorde wiebelt.
const VLAG_ICOON_VOLGORDE = ["hitte_extreem", "koude_nacht_extreem", "stortregen", "stortregen_nacht", "storm"];
const VLAG_ICOON = {
  hitte_extreem: "☀", koude_nacht_extreem: "❄", stortregen: "☂", stortregen_nacht: "☂", storm: "💨",
};
function vlagIcoon(vlaggen) {
  for (const f of VLAG_ICOON_VOLGORDE) {
    if (vlaggen.includes(f)) return VLAG_ICOON[f];
  }
  return "";
}
const REDEN_TEKST = {
  hitte_naderend: "warme dag (27–30°)", hitte: "te warme dag (≥30°)",
  koele_nacht: "koele nacht (10–12°)", koude_nacht: "koude nacht (8–10°)",
  te_koude_nacht: "veel te koude nacht",
  dauw_krap: "krappe dauwmarge", dauw_nat: "natte tent door dauw",
  dagregen_licht: "wat dagregen", dagregen_matig: "matige dagregen", dagregen_zwaar: "zware dagregen",
  wisselvallig: "wisselvallig — kans op een bui",
  wisselvallig_nat: "wisselvallig — vrijwel de hele dag kans op regen",
  nachtregen_licht: "wat nachtregen", nachtregen_matig: "matige nachtregen",
  nachtregen_zwaar: "zware nachtregen",
  nachtregen_wisselvallig: "wisselvallig — hoge buienkans 's nachts",
  wind_fris: "frisse wind", wind_hard: "harde windstoten",
};
const DAG_KORT = ["zo", "ma", "di", "wo", "do", "vr", "za"];
const FAR_VANAF = 10; // vanaf deze dag-index is de voorspelling indicatief

document.getElementById("today-date").textContent =
  new Date().toLocaleDateString("nl-NL", { weekday: "short", day: "numeric", month: "short" });
document.getElementById("refresh-btn").addEventListener("click", loadData);

// ── hulpjes ──────────────────────────────────────────────────────────────────

function parseDag(s) { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
function dagKort(s) { const d = parseDag(s); return `${DAG_KORT[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}`; }
function dagLang(s) {
  return parseDag(s).toLocaleDateString("nl-NL", { weekday: "short", day: "numeric", month: "short" });
}
function fmt1(x) {
  if (x === null || x === undefined) return "–";
  return x.toLocaleString("nl-NL", { maximumFractionDigits: 1 });
}
function vandaagIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function ageLabel(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 2) return "zojuist";
  if (mins < 60) return `${mins} min geleden`;
  const h = Math.round(mins / 60);
  return h < 48 ? `${h} uur geleden` : `${Math.round(h / 24)} dagen geleden`;
}
function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Fallbacks op het ronde-1-artefact: de ?v=2-pagina gaat live vóór de eerste
// ronde-2-datarun. Dood pad zodra die run gecommit heeft.
function catDag(dag) { return dag.cat_day ?? dag.cat; }
function catNacht(dag) { return dag.cat_night ?? (dag.night_partial ? null : dag.cat); }
function vlaggenDag(dag) { return dag.red_flags_day ?? dag.red_flags ?? []; }
function vlaggenNacht(dag) { return dag.red_flags_night ?? dag.red_flags ?? []; }

function glyphVoor(vlaggen) {
  if (!vlaggen.length) return "";
  return vlaggen.includes("waarschuwing") ? "⚠" : "✕";
}
function vlagRegel(vlaggen) {
  return vlaggen.length ? ` · ${vlaggen.map((f) => VLAG_TEKST[f] || f).join(", ")}` : "";
}

// Per regio: vensters als [startIdx, eindIdx] in de gedeelde `datums`-as, voor
// het amber .win-mark-kader (één grid-item per venster, zie camping.html).
function windowSpans(region, datums) {
  const idx = new Map(datums.map((d, i) => [d, i]));
  const spans = [];
  for (const w of region.windows || []) {
    const a = idx.get(w.start);
    const b = idx.get(w.end_night);
    if (a === undefined || b === undefined) continue;
    spans.push([a, b]);
  }
  return spans;
}

// ── matrixcellen (gecombineerde kampeernacht — ongewijzigd t.o.v. ronde 1) ──

function celTitle(dag) {
  const delen = [
    `${dagLang(dag.date)} · ${CAT_LABEL[dag.cat] || dag.cat}`,
  ];
  if (dag.main_reason && REDEN_TEKST[dag.main_reason]) {
    delen.push(`vooral: ${REDEN_TEKST[dag.main_reason]}`);
  }
  delen.push(
    `dag ${fmt1(dag.tmax)}° · nacht ${fmt1(dag.tmin_night)}°`,
    `regen ${fmt1(dag.rain_day_mm)}/${fmt1(dag.rain_night_mm)} mm (dag/nacht)`,
    `dauwmarge ${fmt1(dag.dew_margin_night)}°`,
    `zekerheid ${dag.conf}`,
  );
  if (dag.warning) {
    delen.push(`⚠ ${LEVEL_LABEL[dag.warning.level] || dag.warning.level}: ${dag.warning.events.join(", ")}`);
  }
  const extra = (dag.red_flags || []).filter((f) => f !== "waarschuwing").map((f) => VLAG_TEKST[f] || f);
  if (extra.length) delen.push(`✕ ${extra.join(", ")}`);
  return delen.join(" · ");
}

function celHTML(dag, col, row) {
  const cls = ["mx-cell", `cat-${dag.cat}`, `conf-${dag.conf}`];
  let glyph = "";
  if (dag.cat === "rood") glyph = dag.warning ? "⚠" : "✕";
  // Reden-icoon achter de "waarom?"-toggle. Op matig/slecht (top/goed
  // behoeven geen uitleg) is dat main_reason zoals voorheen; op rood was er
  // tot nu toe geen "waarom" te zien, alleen het kale ⚠/✕. Daar komt het
  // icoon uit de vlag die 'm rood maakte (CSS beslist hieronder of het
  // ✕ vervángt — die heeft geen eigen tekst — of náást de ⚠ komt te staan,
  // want een officiële waarschuwing IS al een reden). Oud artefact zonder
  // main_reason/red_flags → leeg attribuut, de toggle doet dan niets.
  let icoon = "";
  if (dag.cat === "matig" || dag.cat === "slecht") {
    icoon = dag.main_reason ? REDEN_ICOON[dag.main_reason] || "" : "";
  } else if (dag.cat === "rood") {
    icoon = vlagIcoon(dag.red_flags || []);
  }
  return `<div class="${cls.join(" ")}${glyph ? " mx-glyph" : ""}"` +
         ` style="grid-column:${col};grid-row:${row};"` +
         `${glyph ? ` data-glyph="${glyph}"` : ""}${icoon ? ` data-icoon="${icoon}"` : ""}` +
         ` title="${esc(celTitle(dag))}"></div>`;
}

function matrixCardHTML(d) {
  const okRegions = d.regions.filter((r) => r.status === "ok" && (r.days || []).length);
  if (!okRegions.length) return "";
  // De datum-as volgt de regio met de mééste dagen: Open-Meteo levert per
  // locatie soms een dag minder (vroege ochtend), en de eerste regio als as
  // nemen zou dan bij iedereen de laatste dag verzwijgen. Regio's zonder die
  // laatste dag krijgen gewoon een lege (mx-missing) cel.
  const langste = okRegions.reduce((a, r) => (r.days.length > a.days.length ? r : a), okRegions[0]);
  const datums = langste.days.map((x) => x.date);
  const vandaag = vandaagIso();

  // Elk grid-item krijgt een expliciete grid-column/row (i.p.v. auto-flow):
  // de .win-mark-overlays hieronder hebben sowieso een expliciete plek nodig
  // om een venster van meerdere cellen te kunnen overspannen, en CSS Grid's
  // auto-plaatsing behandelt zo'n expliciet geplaatst item als "bezet" — een
  // auto-geplaatste cel op diezelfde rij/kolom springt er dan overheen naar
  // de eerstvolgende vrije plek, wat de hele rij (en alles erna) opschuift.
  // Met alles expliciet geplaatst is er niets meer om overheen te springen.
  let head = `<div style="grid-column:1;grid-row:1;"></div>`;
  datums.forEach((datum, i) => {
    const dt = parseDag(datum);
    const cls = ["mx-head"];
    if (datum === vandaag) cls.push("mx-today");
    if (i === FAR_VANAF) cls.push("mx-far-first");
    head += `<div class="${cls.join(" ")}" style="grid-column:${i + 2};grid-row:1;">${DAG_KORT[dt.getDay()]}<b>${dt.getDate()}</b></div>`;
  });

  let rijen = "";
  // Losse .win-mark-overlays, na alle cellen in de DOM zodat ze er bovenop
  // tekenen (grid-items zonder z-index schilderen in DOM-volgorde).
  let marks = "";
  d.regions.forEach((r, ri) => {
    const rijLijn = ri + 2; // grid-row 1 = kopregel
    rijen += `<div class="mx-region" style="grid-column:1;grid-row:${rijLijn};" title="${esc(r.label)}">${esc(r.label)}</div>`;
    if (r.status !== "ok") {
      datums.forEach((_, i) => {
        rijen += `<div class="mx-cell mx-missing${i === FAR_VANAF ? " mx-far-first" : ""}" style="grid-column:${i + 2};grid-row:${rijLijn};" title="${esc(r.label)}: gegevens niet beschikbaar"></div>`;
      });
      return;
    }
    const perDatum = {};
    (r.days || []).forEach((x) => { perDatum[x.date] = x; });
    datums.forEach((datum, i) => {
      const dag = perDatum[datum];
      if (!dag) {
        rijen += `<div class="mx-cell mx-missing" style="grid-column:${i + 2};grid-row:${rijLijn};"></div>`;
        return;
      }
      let cel = celHTML(dag, i + 2, rijLijn);
      if (i === FAR_VANAF) cel = cel.replace('class="mx-cell', 'class="mx-cell mx-far-first');
      rijen += cel;
    });
    for (const [a, b] of windowSpans(r, datums)) {
      marks += `<div class="win-mark" style="grid-column:${a + 2} / ${b + 3};grid-row:${rijLijn};"></div>`;
    }
  });

  return `
  <div class="grid" style="grid-template-columns:1fr;">
    <div class="park-card"><div class="card-pad">
      <div class="mx-card-head">
        <div class="park-rule" style="margin-top:0;">In één oogopslag · ${datums.length} dagen</div>
        <button class="btn btn-mini" id="waarom-btn">waarom? ${state.waarom ? "uit" : "aan"}</button>
      </div>
      <div class="matrix-scroll"><div class="matrix${state.waarom ? " toon-waarom" : ""}" style="--nd:${datums.length};">${head}${rijen}${marks}</div></div>
      <div class="mx-note">Tot ~${FAR_VANAF} dagen redelijk betrouwbaar; rechts van de stippellijn indicatief. De matrix toont het zwaarste van dagdeel en nacht.</div>
      <div class="mx-legend">
        <span><i class="sw cat-top"></i>top</span>
        <span><i class="sw cat-goed"></i>goed</span>
        <span><i class="sw cat-matig"></i>matig</span>
        <span><i class="sw cat-slecht"></i>slecht</span>
        <span><i class="sw cat-rood"></i>⚠/✕ rode vlag</span>
        <span><i class="sw cat-goed conf-laag"></i>bleek/gearceerd = onzeker</span>
        <span><i class="sw sw-win"></i>venster ≥ ${d.params.MIN_NIGHTS} nachten</span>
      </div>
      <div class="mx-legend" id="waarom-legend"${state.waarom ? "" : " hidden"}>
        <span>icoon = grootste probleem van die dag (ook op ⚠/✕):</span>
        <span>☂ regen</span><span>☀ hitte</span><span>❄ koude nacht</span>
        <span>💧 dauw</span><span>💨 wind</span>
      </div>
    </div></div>
  </div>`;
}

// ── flex-tegels (super-regio's): beste route mét verkassen ──────────────────
// Gevoed door het additieve super_regions-blok (ronde 3): per grote regio de
// optimale route langs de subregio's met minimaal MIN_NIGHTS nachten per plek,
// server-side uitgerekend. Oud artefact zonder het blok → sectie afwezig.

function besteSuper(supers) {
  const ok = supers.filter((s) => s.status === "ok");
  if (!ok.length) return null;
  return ok.reduce((a, s) => {
    if (s.nights_ok > a.nights_ok) return s;
    if (s.nights_ok === a.nights_ok && s.moves < a.moves) return s;
    return a;
  }).id;
}

function flexCelTitle(dag) {
  const delen = [`${dagLang(dag.date)} · ${dag.region_label} · ${CAT_LABEL[dag.cat] || dag.cat}`];
  if (dag.move) delen.push("verkasdag — hier opbouwen");
  if (dag.main_reason && REDEN_TEKST[dag.main_reason]) {
    delen.push(`vooral: ${REDEN_TEKST[dag.main_reason]}`);
  }
  delen.push(`dag ${fmt1(dag.tmax)}° · nacht ${fmt1(dag.tmin_night)}°`, `zekerheid ${dag.conf}`);
  const extra = (dag.red_flags || []).filter((f) => f !== "waarschuwing").map((f) => VLAG_TEKST[f] || f);
  if (extra.length) delen.push(`✕ ${extra.join(", ")}`);
  return delen.join(" · ");
}

function flexStripHTML(s) {
  const dagen = s.days || [];
  if (!dagen.length) return "";
  const vandaag = vandaagIso();
  // Zelfde expliciete grid-plaatsing als de matrix: de .win-mark-overlays
  // hebben een vaste plek nodig en auto-flow zou eroverheen springen.
  let head = "";
  let cellen = "";
  dagen.forEach((dag, i) => {
    const dt = parseDag(dag.date);
    const hcls = ["mx-head"];
    if (dag.date === vandaag) hcls.push("mx-today");
    head += `<div class="${hcls.join(" ")}" style="grid-column:${i + 1};grid-row:1;">${DAG_KORT[dt.getDay()]}<b>${dt.getDate()}</b></div>`;
    const cls = ["mx-cell", `cat-${dag.cat}`, `conf-${dag.conf}`];
    if (dag.move) cls.push("flex-move");
    const glyph = dag.cat === "rood" ? ((dag.red_flags || []).includes("waarschuwing") ? "⚠" : "✕") : "";
    cellen += `<div class="${cls.join(" ")}${glyph ? " mx-glyph" : ""}"` +
      ` style="grid-column:${i + 1};grid-row:2;"` +
      `${glyph ? ` data-glyph="${glyph}"` : ""} title="${esc(flexCelTitle(dag))}"></div>`;
  });
  let marks = "";
  for (const [a, b] of windowSpans(s, dagen.map((x) => x.date))) {
    marks += `<div class="win-mark" style="grid-column:${a + 1} / ${b + 2};grid-row:2;"></div>`;
  }
  return `<div class="flex-scroll"><div class="flex-strip" style="--nd:${dagen.length};">${head}${cellen}${marks}</div></div>`;
}

function flexRouteZin(s) {
  const segs = s.segments || [];
  if (!segs.length) return "";
  const delen = segs.map((seg) => `${esc(seg.region_label)} ${dagKort(seg.start)} – ${dagKort(seg.end_night)}`);
  return `<div class="flex-route">${delen.join(" → ")}</div>`;
}

function flexTileHTML(s, besteId) {
  const band = `<div class="park-eyebrow">${esc(s.label)} · met verkassen${s.id === besteId ? " · ★ beste keuze" : ""}</div>`;
  if (s.status !== "ok") {
    return `<div class="park-card">${band}<div class="card-pad">
      <div class="status-line" style="color:var(--night-soft);">Gegevens op dit moment niet beschikbaar.</div></div></div>`;
  }
  const verkassen = s.moves ? `${s.moves}× verkassen` : "zonder verkassen";
  const kop = `<div class="status-line"><strong>${s.nights_ok} van ${s.nights_total}</strong> nachten goed · ${verkassen}</div>`;
  const rood = s.red_days
    ? `<div class="warn-line">⚠ ${s.red_days} ${s.red_days === 1 ? "dag" : "dagen"} met rode vlag onvermijdelijk in deze streek.</div>`
    : "";
  return `<div class="park-card">${band}<div class="card-pad">
    ${kop}${flexStripHTML(s)}${flexRouteZin(s)}${rood}
  </div></div>`;
}

function flexSectionHTML(d) {
  const supers = d.super_regions || []; // oud artefact → geen sectie
  if (!supers.length) return "";
  const beste = besteSuper(supers);
  return `<div class="strip-legende">Grote regio's, mét verkassen (minimaal ${d.params.MIN_NIGHTS} nachten per plek): per landstreek de beste route langs de streken hierboven — donkere linkerrand = verkasdag. De route is indicatief en kan per run verschuiven; de kopcijfers zijn stabieler.</div>` +
    `<div class="grid grid-tiles">${supers.map((s) => flexTileHTML(s, beste)).join("")}</div>`;
}

// ── dag/nacht-strip ──────────────────────────────────────────────────────────

function dagTegelHTML(dag, vandaag) {
  const cat = catDag(dag);
  const vlaggen = vlaggenDag(dag);
  const glyph = cat === "rood" ? glyphVoor(vlaggen) : "";
  const dt = parseDag(dag.date);
  const title = `${dagLang(dag.date)} overdag · ${CAT_LABEL[cat] || cat} · max ${fmt1(dag.tmax)}° · ` +
                `regen ${fmt1(dag.rain_day_mm)} mm · stoten ${fmt1(dag.gust_max_kmh)} km/u${vlagRegel(vlaggen)}`;
  return `<div class="dn-dag cat-${cat} conf-${dag.conf}${dag.date === vandaag ? " dn-vandaag" : ""}` +
         `${glyph ? " mx-glyph" : ""}"${glyph ? ` data-glyph="${glyph}"` : ""} title="${esc(title)}">` +
         `<span class="dn-datum ${TILE_TEKST[cat] || "tile-donker"}">${dt.getDate()}</span></div>`;
}

function nachtTegelHTML(dag, volgendeDatum) {
  const cat = catNacht(dag);
  if (cat === null || cat === undefined) {
    return `<div class="dn-nacht mx-missing" title="nacht buiten de horizon"></div>`;
  }
  const vlaggen = vlaggenNacht(dag);
  const glyph = cat === "rood" ? glyphVoor(vlaggen) : "";
  const title = `nacht ${dagKort(dag.date)} → ${dagKort(volgendeDatum)} · ${CAT_LABEL[cat] || cat} · ` +
                `min ${fmt1(dag.tmin_night)}° · regen ${fmt1(dag.rain_night_mm)} mm · ` +
                `dauwmarge ${fmt1(dag.dew_margin_night)}°${vlagRegel(vlaggen)}` +
                `${dag.night_partial ? " · (deels buiten horizon)" : ""}`;
  return `<div class="dn-nacht cat-${cat}${dag.night_partial ? " conf-laag" : ""}` +
         `${glyph ? " mx-glyph" : ""}"${glyph ? ` data-glyph="${glyph}"` : ""} title="${esc(title)}"></div>`;
}

function dagNachtStripHTML(days, vandaag) {
  if (!days.length) return "";
  const n = days.length;
  const kolommen = n > 1
    ? `repeat(${n - 1}, minmax(26px, 4fr) minmax(8px, 1fr)) minmax(26px, 4fr)`
    : `minmax(26px, 4fr)`;
  let cellen = "";
  days.forEach((dag, i) => {
    cellen += dagTegelHTML(dag, vandaag);
    if (i < n - 1) cellen += nachtTegelHTML(dag, days[i + 1].date);
    // De nacht van de allerlaatste dag valt buiten de horizon en krijgt geen
    // slottegel; de tooltip van die dagtegel volstaat.
  });
  return `<div class="dn-scroll"><div class="dn-strip" style="grid-template-columns:${kolommen};">${cellen}</div></div>`;
}

// ── verdieping per regiokaart ────────────────────────────────────────────────

function vertrekTekst(w) {
  if (w.droog_vertrek) return ` · droog vertrek ${dagKort(w.vertrek)}`;
  if (w.beste_vertrek) return ` · beste vertrek ${dagKort(w.beste_vertrek)} (laatste nacht nat)`;
  return " · geen droge vertrekochtend in zicht";
}

function windowZin(w, vandaag) {
  const lopend = w.start <= vandaag && vandaag <= w.end_night;
  const kern = lopend
    ? `<strong>Nu geschikt</strong> — t/m ${dagLang(w.end_night)} (${w.nights} nachten)`
    : `${dagLang(w.start)} t/m ${dagLang(w.end_night)} · ${w.nights} nachten`;
  return kern + vertrekTekst(w);
}

function statsOver(dagen) {
  const aanw = (k) => dagen.map((x) => x[k]).filter((v) => v !== null && v !== undefined);
  const som = (k) => aanw(k).reduce((a, b) => a + b, 0);
  return {
    tmax: Math.max(...aanw("tmax")),
    tmin: aanw("tmin_night").length ? Math.min(...aanw("tmin_night")) : null,
    dauw: aanw("dew_margin_night").length ? Math.min(...aanw("dew_margin_night")) : null,
    regenDag: som("rain_day_mm"),
    regenNacht: som("rain_night_mm"),
    gust: aanw("gust_max_kmh").length ? Math.max(...aanw("gust_max_kmh")) : null,
  };
}

function dagRijenHTML(bron) {
  if (!bron.length) return "";
  let rijen = `
    <span class="hdr">d·n</span><span class="hdr">dag</span>
    <span class="hdr num-r">dag°</span><span class="hdr num-r">nacht°</span>
    <span class="hdr num-r">regen d·n</span><span class="hdr num-r">dauw</span><span class="hdr num-r">wind</span>`;
  for (const dag of bron) {
    rijen += `
      <span><i class="dr-sw cat-${catDag(dag)}"></i><i class="dr-sw cat-${catNacht(dag) ?? "missing"}"></i></span>
      <span>${dagKort(dag.date)}</span>
      <span class="num-r">${fmt1(dag.tmax)}°</span>
      <span class="num-r">${fmt1(dag.tmin_night)}°</span>
      <span class="num-r">${fmt1(dag.rain_day_mm)} · ${fmt1(dag.rain_night_mm)}</span>
      <span class="num-r">${fmt1(dag.dew_margin_night)}°</span>
      <span class="num-r">${fmt1(dag.gust_max_kmh)}</span>`;
  }
  return `<div class="day-rows">${rijen}</div>`;
}

function regionCardHTML(r, d) {
  const hoogte = r.elevation_m !== null && r.elevation_m !== undefined
    ? ` · ±${Math.round(r.elevation_m)} m` : "";
  const band = `<div class="park-eyebrow">${esc(r.label)} · ${LAND_NAAM[r.country] || r.country}${hoogte}</div>`;

  if (r.status !== "ok") {
    return `<div class="park-card">${band}<div class="card-pad">
      <div class="status-line" style="color:var(--night-soft);">Gegevens op dit moment niet beschikbaar.</div></div></div>`;
  }

  const vandaag = vandaagIso();
  const windows = r.windows || [];
  const eerste = windows.find((w) => w.end_night >= vandaag) || null;
  const status = eerste
    ? `<div class="status-line">${windowZin(eerste, vandaag)}</div>`
    : `<div class="status-line" style="color:var(--night-soft);">Geen venster van ≥ ${d.params.MIN_NIGHTS} nachten binnen ${d.horizon_days} dagen.</div>`;

  let extraWins = "";
  for (const w of windows.filter((x) => x !== eerste && x.end_night >= vandaag).slice(0, 2)) {
    extraWins += `<div class="win-extra">daarna: ${dagKort(w.start)} – ${dagKort(w.end_night)} · ${w.nights} nachten · ${w.conf}</div>`;
  }

  // Cijfers en verwachting over het venster; zonder venster de komende 5 dagen.
  const bron = eerste
    ? (r.days || []).filter((x) => x.date >= eerste.start && x.date <= eerste.end_night)
    : (r.days || []).slice(0, 5);
  const bronLabel = eerste ? "het venster" : "komende 5 dagen";
  const verw = eerste ? eerste.verwachting : r.verwachting;
  const verwBlok = verw
    ? `<div class="park-rule">Wat je kunt verwachten · ${bronLabel}</div><p class="verwachting">${esc(verw)}</p>`
    : "";

  let stats = "";
  if (bron.length) {
    const s = statsOver(bron);
    stats = `
      <div style="margin-top:14px;">
        <div class="stat-row"><span class="lbl">dag max</span><span>${fmt1(s.tmax)}°</span></div>
        <div class="stat-row"><span class="lbl">nacht min</span><span>${fmt1(s.tmin)}°</span></div>
        <div class="stat-row"><span class="lbl">dauwmarge (min)</span><span>${fmt1(s.dauw)}°</span></div>
        <div class="stat-row"><span class="lbl">regen dag · nacht</span><span>${fmt1(s.regenDag)} · ${fmt1(s.regenNacht)} mm</span></div>
        <div class="stat-row"><span class="lbl">windstoten max</span><span>${fmt1(s.gust)} km/u</span></div>
      </div>`;
  }

  let warns = "";
  for (const w of (r.warnings_active || []).slice(0, 4)) {
    warns += `<div class="warn-line">⚠ ${LEVEL_LABEL[w.level] || w.level} — ${esc(w.event)} · ${esc(w.area)} · t/m ${new Date(w.expires).toLocaleString("nl-NL", { weekday: "short", hour: "2-digit", minute: "2-digit" })}</div>`;
  }

  let conf = "";
  if (r.ensemble !== "ok") {
    conf = `<div class="conf-line">Zekerheid indicatief — ensemble niet beschikbaar deze run.</div>`;
  } else if (eerste) {
    conf = `<div class="conf-line">Zekerheid venster: ${eerste.conf}.</div>`;
  }

  return `<div class="park-card">${band}<div class="card-pad">
    ${status}${extraWins}
    ${dagNachtStripHTML(r.days || [], vandaag)}
    ${verwBlok}
    ${dagRijenHTML(bron)}
    ${stats}${warns}${conf}
  </div></div>`;
}

// ── render ───────────────────────────────────────────────────────────────────

function render() {
  const d = state.data;
  document.getElementById("source-label").textContent =
    `Open-Meteo + ECMWF-ensemble + MeteoAlarm · ververst ${ageLabel(d.generated_at)}`;

  const banners = [];
  const uurOud = (Date.now() - new Date(d.generated_at).getTime()) / 3.6e6;
  if (uurOud > 8) {
    banners.push(`<div class="banner banner-warn">⏳ De data is ${Math.round(uurOud)} uur oud — de Action hoort 4×/dag te draaien.</div>`);
  }
  for (const [land, st] of Object.entries(d.warnings_status || {})) {
    if (st !== "ok") {
      banners.push(`<div class="banner banner-warn">⚠ Waarschuwingsfeed ${LAND_NAAM[land] || land} onbereikbaar — rode vlaggen kunnen daar ontbreken.</div>`);
    }
  }
  const kapot = d.regions.filter((r) => r.status !== "ok");
  if (kapot.length) {
    banners.push(`<div class="banner banner-warn">🌐 Geen gegevens voor: ${kapot.map((r) => esc(r.label)).join(", ")}.</div>`);
  }
  document.getElementById("banner-slot").innerHTML = banners.join("");

  document.getElementById("content").innerHTML =
    matrixCardHTML(d) +
    flexSectionHTML(d) +
    `<div class="strip-legende">Per streek: brede tegel = de dag (9–21u) · smalle tegel ertussen = de nacht die die avond begint (21–9u) · ⚠ = officiële waarschuwing (oranje of rood) · ✕ = extreme voorspelde waarden</div>` +
    `<div class="grid grid-tiles">${d.regions.map((r) => regionCardHTML(r, d)).join("")}</div>`;

  // "Waarom?"-toggle (CSP: geen inline handlers — na elke render opnieuw
  // aangehaakt, want innerHTML vervangt de knop).
  const waaromBtn = document.getElementById("waarom-btn");
  if (waaromBtn) {
    waaromBtn.addEventListener("click", () => {
      state.waarom = !state.waarom;
      const matrix = document.querySelector(".matrix");
      if (matrix) matrix.classList.toggle("toon-waarom", state.waarom);
      const legende = document.getElementById("waarom-legend");
      if (legende) legende.hidden = !state.waarom;
      waaromBtn.textContent = `waarom? ${state.waarom ? "uit" : "aan"}`;
    });
  }
}

async function loadData() {
  document.getElementById("banner-slot").innerHTML = "";
  document.getElementById("source-label").innerHTML = '<span class="pulse">⋯ data laden…</span>';
  try {
    const res = await fetch(`camping_data.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.data = await res.json();
    render();
  } catch (e) {
    document.getElementById("banner-slot").innerHTML =
      `<div class="banner banner-error"><strong>Kan data niet laden:</strong> ${esc(e.message)}. Heeft de GitHub Action al gedraaid?</div>`;
    document.getElementById("source-label").textContent = "";
  }
}

loadData();
