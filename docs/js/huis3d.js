// ===================== HET HUIS IN 3D =====================
// Subpagina van het Ventilatie-dashboard (Project 13): hetzelfde luchtstroomnetwerk als de
// speeltuin, maar dan als draaibaar 3D-huis met stromende deeltjes. Leest vent_data.json
// uit de privé artefact-gist (dezelfde token-poort als vent.html) en schrijft NIETS — elke
// raam-/deurwissel hier is een lokale wat-als, geen melding.
//
// Hergebruik i.p.v. een tweede fysica-port: `buildOpeningsJS`/`solveNetwork`/`simConst`/
// `normState` komen uit speeltuin.js (vóór dit script geladen). Wat hier nieuw is, is
// uitsluitend tekenwerk:
//   1. H3_DEFAULT_LAYOUT — een GESTILEERDE indeling. Het huismodel kent volumes,
//      verdiepingen en gevelrichtingen maar geen maten; de rechthoeken hieronder zijn daaruit
//      verzonnen (oppervlak ≈ volume / hoogte) en zijn nadrukkelijk géén plattegrond op schaal.
//      Een echte indeling hoort NIET in deze publieke repo: wie dat wil, zet een
//      `huis3d_layout.json` in de privé artefact-gist (zelfde vorm, zie h3Layout) en de
//      pagina gebruikt die. Zet hier dus nooit echte maten of een echte kamerschikking neer.
//   2. de openingen worden automatisch geplaatst uit house_meta (gevel-azimut → wand,
//      plan_pos → plek langs de wand, center_height_m → hoogte, area_m2 → afmeting);
//   3. een deeltjes-"agent" volgt de netwerkdebieten van opening naar opening, zodat de
//      stroom door het hele huis massabehoudend oogt.
// Twee visuele toevoegingen bovenop het netto netwerkdebiet, beide alleen voor het beeld:
// eenzijdige uitwisseling door één open raam (de Gids & Phaff) en de tegenstroom door een
// open binnendeur tussen kamers van verschillende temperatuur (Brown–Solvason). Zonder
// die twee zou een open raam in een dichte kamer onterecht "stil" lijken.
"use strict";

const H3_RAD = Math.PI / 180;
// x: tuingevel (0) → straatgevel; z: zijgevel (0) → overzijde; y: hoogte. Meters, gestileerd.
const H3_DEFAULT_LAYOUT = { zones: {
  living:  { x: [0, 8.5],   z: [0, 6.5],    y: [0, 2.7] },
  hall:    { x: [0, 8.5],   z: [6.5, 7.8],  y: [0, 2.7] },
  bath:    { x: [0, 2.6],   z: [7.8, 10.8], y: [0, 2.7] },
  stair:   { x: [2.6, 4.5], z: [7.8, 10.8], y: [0, 8.3] },
  nursery: { x: [4.5, 8.5], z: [7.8, 10.8], y: [0, 2.7] },
  bedroom: { x: [4.5, 8.5], z: [7.8, 10.8], y: [2.8, 5.5] },
  office:  { x: [4.5, 8.5], z: [7.8, 10.8], y: [5.6, 8.3] },
} };
const H3_LEVELS = [[0, 2.7], [2.8, 5.5], [5.6, 8.3]];   // verdiepingen (voor het uit elkaar trekken)
const H3_EXPLODE_M = 3.2;                               // extra tussenruimte per verdieping bij 100 %
const H3_COL = { open: 0x7cffb2, tilt: 0xffd166, dicht: 0x6b7a94, fixed: 0x3d4a66 };
const H3_MAXP = 7000, H3_TRAIL = 7;

const h3 = {
  data: null, meta: null, params: {}, states: {}, live: {}, env: {}, liveEnv: {},
  layout: H3_DEFAULT_LAYOUT, extras: [],
  view: { explode: 0, glass: 0.3, roof: true, speed: 3, density: 0.6, spin: true },
  zones: [], box: {}, portals: [], portalById: {}, edges: [], outOf: {}, inflow: [],
  zoneTemp: {}, fresh: {}, flowInfo: {}, tRange: [16, 26], ready: false,
};

// ---------------------------------------------------------------- kleine helpers
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const rnd = (a, b) => a + Math.random() * (b - a);
const sstep = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const levelOf = y => (y < 2.75 ? 0 : y < 5.55 ? 1 : 2);
const dispY = y => y + h3.view.explode * H3_EXPLODE_M * (sstep(2.7, 2.8, y) + sstep(5.5, 5.6, y));
const esc = s => ("" + s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const shortLabel = s => ("" + s).split(" (")[0].split(" — ")[0];
// Lokale huis-as voor een kompasrichting: +x kijkt naar de straatgevel (PLAN_FRONT_AZ).
const localDir = az => ({ x: Math.cos((az - PLAN_FRONT_AZ) * H3_RAD), z: Math.cos((az - PLAN_FRONT_AZ - 90) * H3_RAD) });

function tempColor(t, out) {                      // koud blauw → neutraal → warm oranje
  const [lo, hi] = h3.tRange, k = clamp((t - lo) / (hi - lo), 0, 1);
  const a = k < 0.5 ? [0.23, 0.63, 1.0] : [0.91, 0.96, 1.0], b = k < 0.5 ? [0.91, 0.96, 1.0] : [1.0, 0.54, 0.24];
  const f = k < 0.5 ? k * 2 : (k - 0.5) * 2;
  out[0] = lerp(a[0], b[0], f); out[1] = lerp(a[1], b[1], f); out[2] = lerp(a[2], b[2], f);
  return out;
}

// ---------------------------------------------------------------- data + poort
function overlay(html, pulse = false) {
  const o = document.getElementById("overlay"), b = document.getElementById("overlay-box");
  if (html == null) { o.classList.add("hidden"); return; }
  o.classList.remove("hidden"); b.classList.toggle("pulse", pulse); b.innerHTML = html;
}

async function h3Load() {
  if (!window.THREE || !THREE.OrbitControls) {
    overlay("De 3D-bibliotheek kon niet geladen worden (cdn.jsdelivr.net geblokkeerd?)."); return;
  }
  // Zelfde poort als vent.html: zonder token + artefact-gist is er niets te tonen.
  if (!(CONFIG.githubToken && CONFIG.artefactGistId)) {
    overlay(`🔒 Deze pagina is privé — ze toont de gemelde raamstanden en kamertemperaturen.<br><br>` +
            `<button class="btn" id="account-btn" type="button">🔑 Account koppelen</button>`);
    document.getElementById("account-btn").addEventListener("click", () => { openAccountSettings(); h3Load(); });
    return;
  }
  overlay("⋯ het huis wordt opgebouwd…", true);
  let d;
  try {
    const files = await h3ReadArtefacts(["vent_data.json", "huis3d_layout.json"]);
    d = files["vent_data.json"];
    h3.layout = h3Layout(files["huis3d_layout.json"]);
  } catch (e) { overlay(`Kon <code>vent_data.json</code> niet laden (${esc(e.message)}).`); return; }
  if (!d || !d.house_meta) { overlay("Het artefact draagt geen huisgeometrie (house_meta)."); return; }
  h3.data = d; h3.meta = d.house_meta; h3.params = (d.learned && d.learned.params) || {};
  simConst(d);
  const w = d.weather || {};
  h3.liveEnv = { tOut: w.outside_temp ?? 18, wind: w.wind_speed ?? 2, dir: w.wind_dir ?? 240 };
  h3.env = Object.assign({}, h3.liveEnv);
  h3.live = {};
  (d.controls || []).forEach(c => { if (["window", "vent", "door"].includes(c.kind)) h3.live[c.id] = normState(c.state, c.kind); });
  h3.states = Object.assign({}, h3.live);
  try {
    if (!h3.ready) h3Init();
    h3BuildHouse(); h3BuildPanel(); h3Recompute();
  } catch (e) {
    console.error(e); overlay(`Het 3D-beeld kon niet starten (${esc(e.message)}). Ondersteunt deze browser WebGL?`); return;
  }
  overlay(null);
}

// Beide bestanden in één call uit de privé artefact-gist. Bewust géén terugval op een pad
// onder docs/: de indeling is privé en mag nooit vanaf Pages geserveerd worden.
async function h3ReadArtefacts(names) {
  const r = await fetch(`https://api.github.com/gists/${CONFIG.artefactGistId}`,
    { headers: { Authorization: `token ${CONFIG.githubToken}` }, cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const files = (await r.json()).files || {}, out = {};
  for (const n of names) {
    let txt = null;
    try { txt = await gistFileText(files[n]); } catch (e) { console.warn(n, e); }
    try { out[n] = txt ? JSON.parse(txt) : null; } catch (e) { console.warn(`${n}: geen geldige JSON`); out[n] = null; }
  }
  return out;
}

// Privé-indeling valideren; alles wat niet klopt → de verzonnen standaard. Vorm:
//   { "zones":  { "<zone-id>": { "x":[a,b], "z":[a,b], "y":[a,b],
//                                "parts":[{ "x":[a,b], "z":[a,b] }] } },   // parts: uitbouw die aan
//     "extras": [ { "x":[a,b], "z":[a,b], "y":[a,b], "label":"…", "solid":true } ],  // de hoofddoos raakt
//     "place":  { "<element-id>": { "side":"x0|x1|z0|z1|roof", "pos":0.5 } } }
// `extras` doen niet mee in de luchtstroom (solid = dicht blok, anders een lege ruimte).
function h3Layout(raw) {
  const pair = v => Array.isArray(v) && v.length === 2 && v.every(n => typeof n === "number" && isFinite(n)) && v[1] > v[0];
  const boxOk = (b, needY) => b && pair(b.x) && pair(b.z) && (needY ? pair(b.y) : true);
  if (!raw || typeof raw.zones !== "object" || !raw.zones) return H3_DEFAULT_LAYOUT;
  const zones = {};
  for (const [id, z] of Object.entries(raw.zones)) {
    if (!boxOk(z, true)) { console.warn(`huis3d_layout: zone ${id} ongeldig — standaardindeling gebruikt`); return H3_DEFAULT_LAYOUT; }
    zones[id] = { x: z.x, z: z.z, y: z.y, parts: (z.parts || []).filter(q => boxOk(q, false)) };
  }
  return { zones, extras: (raw.extras || []).filter(e => boxOk(e, true)), place: raw.place || {}, custom: true };
}

// ---------------------------------------------------------------- geometrie uit het model
function h3Boxes() {
  const m = h3.meta, all = Object.assign({}, m.rooms || {}, m.junctions || {});
  h3.zones = Object.keys(all); h3.box = {};
  const mk = (L, y) => ({ x0: L.x[0], x1: L.x[1], z0: L.z[0], z1: L.z[1], y0: (L.y || y)[0], y1: (L.y || y)[1] });
  let spareZ = 0;
  Object.values(h3.layout.zones).forEach(L => { spareZ = Math.max(spareZ, L.z[1]); });
  let spare = 0;
  h3.zones.forEach(z => {
    const L = h3.layout.zones[z];
    let b;
    if (L) { b = mk(L); b.parts = [b].concat((L.parts || []).map(q => mk(q, L.y))); }
    else {   // Zone die de indeling (nog) niet kent: een losse doos naast het huis, uit het volume.
      const lv = H3_LEVELS[clamp(all[z].floor || 0, 0, 2)], s = Math.sqrt((all[z].volume_m3 || 20) / 2.7);
      b = { x0: spare, x1: spare + s, z0: spareZ + 1.2, z1: spareZ + 1.2 + s, y0: lv[0], y1: lv[1] }; b.parts = [b];
      spare += s + 0.6;
    }
    // Doorgang van elke uitbouw naar de hoofddoos: een punt nét binnen de hoofddoos, waar de
    // deeltjes langs moeten — een rechte lijn uitbouw↔kamer snijdt anders de inspringende hoek.
    b.parts.slice(1).forEach(q => {
      for (const [ax, o] of [["x", "z"], ["z", "x"]]) for (const sg of [1, -1]) {
        const face = sg > 0 ? b[ax + "0"] : b[ax + "1"], mine = sg > 0 ? q[ax + "1"] : q[ax + "0"];
        const lo = Math.max(b[o + "0"], q[o + "0"]), hi = Math.min(b[o + "1"], q[o + "1"]);
        if (Math.abs(face - mine) > 0.06 || hi - lo < 0.6) continue;
        q.gate = { ax, o, at: face + sg * 0.45, lo: lo + 0.3, hi: hi - 0.3 };
      }
    });
    h3.box[z] = b;
  });
  h3.extras = (h3.layout.extras || []).map(e => Object.assign(mk(e), { label: e.label, solid: !!e.solid }));
}

const inBox = (B, x, z, tol) => x >= B.x0 - tol && x <= B.x1 + tol && z >= B.z0 - tol && z <= B.z1 + tol;
// In welk deel van de zone ligt dit punt? 0 = hoofddoos (wint bij twijfel), −1 = nergens.
function partAt(B, x, z) {
  if (inBox(B, x, z, 0.02)) return 0;
  for (let k = 1; k < B.parts.length; k++) if (inBox(B.parts[k], x, z, 0.12)) return k;
  return inBox(B, x, z, 0.25) ? 0 : -1;
}

function wallSide(az) {
  const d = localDir(az);
  return Math.abs(d.x) >= Math.abs(d.z) ? (d.x > 0 ? "x1" : "x0") : (d.z > 0 ? "z1" : "z0");
}

function h3Portals() {
  const m = h3.meta, V = THREE.Vector3, up = new V(0, 1, 0);
  h3.portals = []; h3.portalById = {};
  const add = p => { p.u = p.u || new V().crossVectors(up, p.n).normalize(); p.v = p.v || up.clone(); h3.portals.push(p); h3.portalById[p.id] = p; };
  const ext = (id, el, kind) => {
    const B = h3.box[el.room]; if (!B) return;
    const area = Math.max(el.area_m2 || 0.05, 0.02), operable = id in h3.live;
    const hasTilt = kind === "window" && el.tilt_frac > 0 && el.tilt_frac < 1;
    const ov = (h3.layout.place || {})[id] || {};
    const side = ["x0", "x1", "z0", "z1", "roof"].includes(ov.side) ? ov.side : wallSide(el.facade_azimuth_deg || 0);
    const t = typeof ov.pos === "number" ? ov.pos : (el.plan_pos ?? 0.5);
    if (side === "roof" || (kind === "window" && el.kind === "skylight")) {
      const s = kind === "vent" ? 0.45 : clamp(Math.sqrt(area), 0.45, 1.8), small = side === "roof" || (B.x1 - B.x0) < 3 || (B.z1 - B.z0) < 3;
      let x = (B.x0 + B.x1) / 2, z = (B.z0 + B.z1) / 2;
      if (!small) {
        const ins = s / 2 + 0.6;
        if (side[0] === "x") { x = side === "x0" ? B.x0 + ins : B.x1 - ins; z = clamp(lerp(B.z0, B.z1, t), B.z0 + ins, B.z1 - ins); }
        else { z = side === "z0" ? B.z0 + ins : B.z1 - ins; x = clamp(lerp(B.x0, B.x1, t), B.x0 + ins, B.x1 - ins); }
      }
      add({ id, kind: kind === "vent" ? "vent" : "skylight", roof: true, a: el.room, b: "outside", el, operable, hasTilt, hole: operable && kind !== "vent",
            c: new V(x, B.y1, z), n: new V(0, 1, 0), u: new V(0, 0, 1), v: new V(1, 0, 0), hw: s / 2, hh: kind === "vent" ? 0.05 : s / 2 });
      return;
    }
    // De gevel aan deze kant = alle delen van de zone die op het buitenste vlak liggen.
    const alongX = side[0] === "z", far = side[1] === "1";
    const edge = B.parts.reduce((mm, q) => (far ? Math.max(mm, q[side]) : Math.min(mm, q[side])), far ? -1e9 : 1e9);
    const segs = B.parts.filter(q => Math.abs(q[side] - edge) < 0.06).map(q => ({ a0: alongX ? q.x0 : q.z0, a1: alongX ? q.x1 : q.z1, pl: q[side] }));
    const a0 = Math.min(...segs.map(q => q.a0)), a1 = Math.max(...segs.map(q => q.a1)), want = lerp(a0, a1, t);
    const seg = segs.find(q => want >= q.a0 && want <= q.a1) || segs[0];
    let w, h, yc;
    const doorlike = kind === "window" && (el.center_height_m ?? 1.5) <= 1.05 && area >= 1.5;
    if (kind === "vent") { w = clamp(area / 0.04, 0.3, 1.3); h = 0.1; }
    else if (doorlike) { h = 2.05; w = area / h; }
    else { w = Math.sqrt(area * 1.5); h = area / w; if (h > 1.7) { h = 1.7; w = area / h; } }
    w = Math.max(0.3, Math.min(w, (seg.a1 - seg.a0) - 0.5));
    yc = doorlike ? B.y0 + h / 2 + 0.03 : clamp(el.center_height_m ?? (B.y0 + 1.4), B.y0 + h / 2 + 0.12, B.y1 - h / 2 - 0.12);
    const al = clamp(want, seg.a0 + w / 2 + 0.25, seg.a1 - w / 2 - 0.25);
    const plane = seg.pl, sgn = far ? 1 : -1;
    add({ id, kind, a: el.room, b: "outside", el, operable, hasTilt, doorlike, hole: operable && kind === "window",
          c: alongX ? new V(al, yc, plane) : new V(plane, yc, al),
          n: alongX ? new V(0, 0, sgn) : new V(sgn, 0, 0), hw: w / 2, hh: h / 2 });
  };
  Object.entries(m.windows || {}).forEach(([id, el]) => ext(id, el, "window"));
  Object.entries(m.vents || {}).forEach(([id, el]) => ext(id, el, "vent"));
  Object.entries(m.doors || {}).forEach(([id, el]) => {
    if (!el.between) return;
    const [a, b] = el.between, ZA = h3.box[a], ZB = h3.box[b]; if (!ZA || !ZB) return;
    const y0 = Math.max(ZA.y0, ZB.y0), h = 2.05, w = clamp((el.area_m2 || 1.8) / h, 0.75, 1.15), t = el.plan_pos ?? 0.5;
    let c = null, n = null;
    for (const A of ZA.parts) for (const B of ZB.parts) for (const [ax, o] of [["x", "z"], ["z", "x"]]) for (const sgn of [1, -1]) {
      if (c) continue;
      const pa = sgn > 0 ? A[ax + "1"] : A[ax + "0"], pb = sgn > 0 ? B[ax + "0"] : B[ax + "1"];
      const lo = Math.max(A[o + "0"], B[o + "0"]), hi = Math.min(A[o + "1"], B[o + "1"]);
      if (Math.abs(pa - pb) > 0.05 || hi - lo < w + 0.2) continue;
      const al = clamp(lerp(lo, hi, t), lo + w / 2 + 0.1, hi - w / 2 - 0.1);
      c = ax === "x" ? new V(pa, y0 + h / 2 + 0.03, al) : new V(al, y0 + h / 2 + 0.03, pa);
      n = ax === "x" ? new V(sgn, 0, 0) : new V(0, 0, sgn);
    }
    if (!c) return;   // geen gedeelde wand in de gestileerde indeling → deur niet tekenbaar
    add({ id, kind: "door", a, b, el, operable: id in h3.live, fixed: !!el.fixed, hole: true, c, n, hw: w / 2, hh: h / 2 });
  });
}

// Vlak paneel (wand/dak) met rechthoekige gaten; U×V = de kant waar je 'm vanaf ziet.
function h3Panel(O, U, Vv, L, H, holes, mat) {
  const sh = new THREE.Shape();
  sh.moveTo(0, 0); sh.lineTo(L, 0); sh.lineTo(L, H); sh.lineTo(0, H); sh.closePath();
  const used = [];
  holes.forEach(r => {
    const mu = r.full ? 0.012 : 0.03, u0 = clamp(r.u0, mu, L - mu), u1 = clamp(r.u1, mu, L - mu);
    const v0 = r.full ? 0.012 : clamp(r.v0, 0.02, H - 0.03), v1 = r.full ? H - 0.012 : clamp(r.v1, 0.02, H - 0.03);
    if (u1 - u0 < 0.1 || v1 - v0 < 0.1) return;
    if (used.some(q => u0 < q[1] && u1 > q[0] && v0 < q[3] && v1 > q[2])) return;   // overlappende gaten breken de triangulatie
    used.push([u0, u1, v0, v1]);
    const p = new THREE.Path(); p.moveTo(u0, v0); p.lineTo(u0, v1); p.lineTo(u1, v1); p.lineTo(u1, v0); p.closePath(); sh.holes.push(p);
  });
  const g = new THREE.ShapeGeometry(sh), N = new THREE.Vector3().crossVectors(U, Vv);
  g.applyMatrix4(new THREE.Matrix4().makeBasis(U, Vv, N).setPosition(O));
  return new THREE.Mesh(g, mat);
}

function h3BuildHouse() {
  const T = THREE, V = T.Vector3;
  if (h3.houseInner) { h3.houseOuter.remove(h3.houseInner); }
  h3Boxes(); h3Portals();
  const inner = h3.houseInner = new T.Group();
  // Alle dozen die getekend worden: elk deel van elke zone + de extra's (zonder luchtstroom).
  const all = [];
  h3.zones.forEach(zid => h3.box[zid].parts.forEach((B, k) => all.push({ B, zid, k })));
  h3.extras.forEach((B, k) => all.push({ B, zid: null, k }));
  let X0 = 1e9, X1 = -1e9, Z0 = 1e9, Z1 = -1e9;
  all.forEach(({ B }) => { X0 = Math.min(X0, B.x0); X1 = Math.max(X1, B.x1); Z0 = Math.min(Z0, B.z0); Z1 = Math.max(Z1, B.z1); });
  inner.position.set(-(X0 + X1) / 2, 0, -(Z0 + Z1) / 2);
  h3.houseOuter.add(inner);
  h3.levelGroups = [0, 1, 2].map(() => { const g = new T.Group(); inner.add(g); return g; });
  h3.roofGroups = [0, 1, 2].map(i => { const g = new T.Group(); h3.levelGroups[i].add(g); return g; });
  h3.wallMat = new T.MeshLambertMaterial({ color: 0xa9bfe6, transparent: true, opacity: 0.3, depthWrite: false, side: T.FrontSide });
  h3.roofMat = new T.MeshLambertMaterial({ color: 0x8fa6d0, transparent: true, opacity: 0.4, depthWrite: false, side: T.DoubleSide });
  h3.edgeMat = new T.LineBasicMaterial({ color: 0x9fc4ff, transparent: true, opacity: 0.55 });
  h3.floorMats = {}; h3.labels = {};
  const up = new V(0, 1, 0);
  const extraFloor = new T.MeshLambertMaterial({ color: 0x141b29 });
  const solidMat = new T.MeshLambertMaterial({ color: 0x232c3f, transparent: true, opacity: 0.82 });
  const solidEdge = new T.LineBasicMaterial({ color: 0x55637f, transparent: true, opacity: 0.6 });
  const label = (key, B) => {
    const cv = document.createElement("canvas"); cv.width = 512; cv.height = 150;
    const tex = new T.CanvasTexture(cv), sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false }));
    sp.scale.set(3.2, 0.94, 1); sp.renderOrder = 20;
    const ly = Math.min(B.y1, B.y0 + 2.7) - 0.75;
    sp.position.set((B.x0 + B.x1) / 2, ly, (B.z0 + B.z1) / 2);
    h3.levelGroups[levelOf(ly)].add(sp);
    h3.labels[key] = { cv, tex, sp };
  };

  all.forEach(({ B, zid, k }) => {
    const cx = (B.x0 + B.x1) / 2, cz = (B.z0 + B.z1) / 2, dx = B.x1 - B.x0, dz = B.z1 - B.z0;
    if (!zid && B.solid) {                                      // dicht blok: hoort niet bij het huis
      const H = B.y1 - B.y0, G = h3.levelGroups[levelOf(B.y0 + 0.1)];
      const bm = new T.Mesh(new T.BoxGeometry(dx - 0.04, H, dz - 0.04), solidMat); bm.position.set(cx, B.y0 + H / 2, cz); G.add(bm);
      const bl = new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(dx, H, dz)), solidEdge); bl.position.copy(bm.position); G.add(bl);
      if (B.label) { label("extra:" + k, B); h3Label("extra:" + k, B.label, ""); }
      return;
    }
    const sibs = zid ? h3.box[zid].parts.filter(q => q !== B) : [];
    const segs = H3_LEVELS.map(([a, b]) => [Math.max(a, B.y0), Math.min(b, B.y1)]).filter(sg => sg[1] - sg[0] > 0.5);
    const fm = zid ? (h3.floorMats[zid] = h3.floorMats[zid] || new T.MeshLambertMaterial({ color: 0x1a2233 })) : extraFloor;
    segs.forEach(([y0, y1], si) => {
      const G = h3.levelGroups[levelOf(y0 + 0.1)], H = y1 - y0;
      if (si === 0) {                                           // vloerplaat alleen onderin
        const f = new T.Mesh(new T.BoxGeometry(dx, 0.1, dz), fm); f.position.set(cx, y0 - 0.05, cz); G.add(f);
      }
      const sides = [
        { O: new V(B.x0, y0, B.z1), U: new V(0, 0, -1), L: dz, ax: "x", o: "z", pl: B.x0, opp: "x1" },
        { O: new V(B.x1, y0, B.z0), U: new V(0, 0, 1),  L: dz, ax: "x", o: "z", pl: B.x1, opp: "x0" },
        { O: new V(B.x0, y0, B.z0), U: new V(1, 0, 0),  L: dx, ax: "z", o: "x", pl: B.z0, opp: "z1" },
        { O: new V(B.x1, y0, B.z1), U: new V(-1, 0, 0), L: dx, ax: "z", o: "x", pl: B.z1, opp: "z0" },
      ];
      sides.forEach(sd => {
        const uOf = val => (val - sd.O[sd.o]) * sd.U[sd.o];
        const holes = !zid ? [] : h3.portals.filter(p => p.hole && !p.roof && (p.a === zid || p.b === zid) &&
            Math.abs(p.n[sd.ax]) > 0.9 && Math.abs(p.c[sd.ax] - sd.pl) < 0.03 && p.c.y > y0 && p.c.y < y1 &&
            p.c[sd.o] > B[sd.o + "0"] && p.c[sd.o] < B[sd.o + "1"])
          .map(p => { const u = uOf(p.c[sd.o]); return { u0: u - p.hw, u1: u + p.hw, v0: p.c.y - p.hh - y0, v1: p.c.y + p.hh - y0 }; });
        // Waar een ander deel van dezelfde kamer aansluit hoort geen wand: de kamer loopt door.
        let whole = false;
        sibs.forEach(q => {
          const lo = Math.max(B[sd.o + "0"], q[sd.o + "0"]), hi = Math.min(B[sd.o + "1"], q[sd.o + "1"]);
          if (Math.abs(q[sd.opp] - sd.pl) > 0.06 || hi - lo < 0.2) return;
          if (hi - lo > sd.L - 0.1) { whole = true; return; }
          const ua = uOf(lo), ub = uOf(hi);
          holes.push({ u0: Math.min(ua, ub), u1: Math.max(ua, ub), full: true });
        });
        if (!whole) G.add(h3Panel(sd.O, sd.U, up, sd.L, H, holes, h3.wallMat));
      });
      const ln = new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(dx, H, dz)), h3.edgeMat); ln.position.set(cx, y0 + H / 2, cz); G.add(ln);
    });
    // Dak waar geen andere doos bovenop staat.
    const covered = all.some(({ B: C }) => C !== B && Math.abs(C.y0 - B.y1) < 0.2 && C.x0 < B.x1 - 0.1 && C.x1 > B.x0 + 0.1 && C.z0 < B.z1 - 0.1 && C.z1 > B.z0 + 0.1);
    if (!covered) {
      const holes = !zid ? [] : h3.portals.filter(p => p.roof && p.a === zid && p.hole && inBox(B, p.c.x, p.c.z, 0))
        .map(p => ({ u0: p.c.z - B.z0 - p.hw, u1: p.c.z - B.z0 + p.hw, v0: p.c.x - B.x0 - p.hh, v1: p.c.x - B.x0 + p.hh }));
      h3.roofGroups[levelOf(B.y1 - 0.1)].add(h3Panel(new V(B.x0, B.y1, B.z0), new V(0, 0, 1), new V(1, 0, 0), dz, dx, holes, h3.roofMat));
    }
    // Trap: een paar treden per verdieping in een zone die meerdere lagen beslaat.
    if (zid && segs.length > 1) {
      const sm = new T.MeshLambertMaterial({ color: 0x4a5a7c, transparent: true, opacity: 0.75 });
      segs.forEach(([y0], si) => {
        if (si === segs.length - 1) return;
        const n = 10, rise = (H3_LEVELS[levelOf(y0 + 0.1) + 1][0] - y0) / n, wx = dx * 0.46, run = (dz - 0.6) / n;
        for (let j = 0; j < n; j++) {
          const st = new T.Mesh(new T.BoxGeometry(wx, 0.05, run * 0.9), sm), zz = si % 2 ? B.z1 - 0.3 - (j + 0.5) * run : B.z0 + 0.3 + (j + 0.5) * run;
          st.position.set(si % 2 ? B.x1 - wx / 2 - 0.05 : B.x0 + wx / 2 + 0.05, y0 + (j + 1) * rise, zz);
          h3.levelGroups[levelOf(y0 + 0.1)].add(st);
        }
      });
    }
    if (zid && k === 0) label(zid, B);
    if (!zid && B.label) { label("extra:" + k, B); h3Label("extra:" + k, B.label, ""); }
  });

  // Openingen: kozijn + draaiend blad + onzichtbaar klikvlak.
  h3.hits = [];
  h3.portals.forEach(p => {
    const g = new T.Group();
    g.applyMatrix4(new T.Matrix4().makeBasis(p.u, p.v, p.n).setPosition(p.c));
    h3.levelGroups[levelOf(p.c.y - 0.06)].add(g);
    const W = p.hw * 2, Hh = p.hh * 2;
    p.frameMat = new T.LineBasicMaterial({ color: H3_COL.fixed });
    if (p.kind === "vent") {
      p.barMat = new T.MeshBasicMaterial({ color: H3_COL.dicht });
      g.add(new T.Mesh(new T.BoxGeometry(W, 0.09, 0.07), p.barMat));
    } else {
      g.add(new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(W, Hh, 0.08)), p.frameMat));
      if (!(p.kind === "door" && p.fixed)) {
        const isDoor = p.kind === "door";
        const paneMat = isDoor ? new T.MeshLambertMaterial({ color: 0xc9a978, transparent: true, opacity: 0.85 })
          : new T.MeshLambertMaterial({ color: 0x8fd3ff, transparent: true, opacity: p.operable ? 0.42 : 0.2, depthWrite: false, side: T.DoubleSide });
        p.tiltPivot = new T.Group(); p.tiltPivot.position.set(0, -p.hh, 0);
        p.hinge = new T.Group(); p.hinge.position.set(-p.hw, p.hh, 0);
        const pane = new T.Mesh(new T.BoxGeometry(W - 0.05, Hh - 0.05, 0.035), paneMat); pane.position.set(p.hw, 0, 0);
        p.hinge.add(pane); p.tiltPivot.add(p.hinge); g.add(p.tiltPivot);
        p.cur = { hinge: 0, tilt: 0 };
      }
    }
    if (p.operable) {
      const hit = new T.Mesh(new T.BoxGeometry(W + 0.25, Math.max(Hh, 0.4) + 0.25, 0.5), new T.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
      hit.userData.pid = p.id; g.add(hit); h3.hits.push(hit);
    }
  });
  h3ApplyView(true);
}

function h3Label(zid, line1, line2) {
  const L = h3.labels[zid]; if (!L) return;
  const c = L.cv.getContext("2d"); c.clearRect(0, 0, 512, 150);
  c.textAlign = "center";
  c.font = 'italic 600 50px "Cormorant Garamond", Georgia, serif';
  const w1 = c.measureText(line1).width; c.font = '600 36px "JetBrains Mono", monospace';
  const w = Math.min(500, Math.max(w1, c.measureText(line2).width) + 56), x0 = 256 - w / 2;
  c.fillStyle = "rgba(7,11,20,.72)"; c.beginPath();
  c.moveTo(x0 + 22, 6); c.arcTo(x0 + w, 6, x0 + w, 144, 22); c.arcTo(x0 + w, 144, x0, 144, 22); c.arcTo(x0, 144, x0, 6, 22); c.arcTo(x0, 6, x0 + w, 6, 22); if (line2) c.fill();
  c.fillStyle = "#cfe0ff"; c.fillText(line2, 256, 122);
  c.font = 'italic 600 50px "Cormorant Garamond", Georgia, serif'; c.fillStyle = line2 ? "#f3ecd9" : "#9aa6bd"; c.fillText(line1, 256, line2 ? 62 : 92);
  L.tex.needsUpdate = true;
}

// ---------------------------------------------------------------- netwerk → stroomgraaf
function h3Recompute() {
  const d = h3.data, m = h3.meta, env = h3.env;
  const rooms = d.rooms || {}, zt = h3.zoneTemp = {};
  h3.zones.forEach(z => { const r = rooms[z] || {}; const t = r.predicted_air_temp ?? r.predicted_temp ?? r.actual_temp; if (t != null) zt[z] = t; });
  // Zone zonder eigen temperatuur (het gangetje): gemiddelde van de buren waar een deur naartoe gaat.
  h3.zones.forEach(z => {
    if (zt[z] != null) return;
    const nb = Object.values(m.doors || {}).filter(dr => dr.between && dr.between.includes(z))
      .map(dr => zt[dr.between[0] === z ? dr.between[1] : dr.between[0]]).filter(v => v != null);
    zt[z] = nb.length ? nb.reduce((s, v) => s + v, 0) / nb.length : env.tOut;
  });
  const ops = buildOpeningsJS(m, h3.states, { wind_speed: env.wind, wind_dir: env.dir }, h3.params, env.tOut);
  const net = solveNetwork(h3.zones, ops, zt, env.tOut);
  const tOf = z => (z === "outside" ? env.tOut : zt[z]);
  const temps = Object.values(zt).concat([env.tOut]); let lo = Math.min(...temps), hi = Math.max(...temps);
  if (hi - lo < 5) { const mid = (lo + hi) / 2; lo = mid - 2.5; hi = mid + 2.5; }
  h3.tRange = [lo, hi];

  const edges = h3.edges = [], info = h3.flowInfo = {}, fresh = h3.fresh = Object.assign({}, net.fresh);
  ops.forEach((op, i) => {
    const q = net.flows[i];
    if (op.id.startsWith("_leak_")) { if (q > 2e-5) edges.push({ from: op.a, to: "sink", q }); return; }
    const p = h3.portalById[op.id]; if (!p) return;
    const vmax = clamp(Math.abs(q) / Math.max(op.area, 0.01), 0.3, 2.2);
    if (Math.abs(q) > 2e-5) edges.push(q > 0 ? { from: op.a, to: op.b, p, q, half: 0, v: vmax } : { from: op.b, to: op.a, p, q: -q, half: 0, v: vmax });
    // Uitwisseling in twee richtingen door dezelfde opening (alleen voor het beeld, zie kop).
    const dT = Math.abs(tOf(op.a) - tOf(op.b)), H = p.hh * 2;
    let qx = 0;
    if (op.b === "outside" && p.kind !== "vent") qx = 0.5 * op.area * Math.sqrt(0.001 * env.wind * env.wind + 0.0035 * H * dT + 0.01);
    else if (op.b !== "outside") qx = 0.2 * op.area * Math.sqrt(9.81 * H * dT / 295);
    qx = Math.max(0, qx - Math.abs(q));
    if (qx > 1e-4) {
      const aCold = tOf(op.a) < tOf(op.b);                      // koude lucht stroomt onderlangs
      edges.push({ from: op.a, to: op.b, p, q: qx, half: aCold ? -1 : 1, v: 0.45 });
      edges.push({ from: op.b, to: op.a, p, q: qx, half: aCold ? 1 : -1, v: 0.45 });
      if (op.b === "outside") fresh[op.a] = (fresh[op.a] || 0) + qx * 0.5;
    }
    info[op.id] = { q, qx };
  });
  h3.outOf = {}; h3.inflow = [];
  edges.forEach((e, i) => { e.i = i; e.w = Math.pow(e.q, 0.7); (h3.outOf[e.from] = h3.outOf[e.from] || []).push(e); if (e.from === "outside") h3.inflow.push(e); });
  const qin = h3.inflow.reduce((s, e) => s + e.q, 0);
  h3.active = Math.round(H3_MAXP * h3.view.density * clamp(0.12 + 0.88 * Math.sqrt(qin / 0.6), 0.1, 1));
  h3Rechoose();

  // Uitlezing: labels, vloerkleur, kozijnkleur, paneel.
  const col = [0, 0, 0];
  h3.zones.forEach(z => {
    const meta = (m.rooms || {})[z] || (m.junctions || {})[z] || {}, vol = meta.volume_m3 || 30;
    const ach = (fresh[z] || 0) * 3600 / vol;
    h3Label(z, shortLabel(meta.label || z).replace(/ \+.*$/, ""), `${zt[z].toFixed(1)}° · ${ach.toFixed(1)}×/u`);
    tempColor(zt[z], col); h3.floorMats[z].color.setRGB(lerp(0.06, col[0], 0.2), lerp(0.08, col[1], 0.2), lerp(0.12, col[2], 0.2));
  });
  h3.portals.forEach(p => {
    const st = p.operable ? h3.states[p.id] : (p.kind === "vent" ? normState(p.el.default_state ?? "open", "vent") : (p.fixed ? "open" : "fixed"));
    p.state = st;
    const c = H3_COL[st] ?? H3_COL.fixed;
    p.frameMat.color.setHex(c); if (p.barMat) p.barMat.color.setHex(c);
    if (p.cur) {
      const out = p.kind === "door" ? 1 : -1;
      p.target = { hinge: 0, tilt: 0 };
      if (p.roof) p.target.tilt = st === "open" ? 0.5 : st === "tilt" ? 0.18 : 0;
      else if (st === "open" && p.el.tilt_frac === 1) p.target.tilt = -0.3;      // kiepraam: "open" = gekiept
      else if (st === "open") p.target.hinge = out * 1.45;
      else if (st === "tilt") p.target.tilt = -0.22;
    }
  });
  const totalFresh = Object.values(fresh).reduce((s, v) => s + v, 0) * 3600;
  document.getElementById("stat-line").innerHTML =
    `buiten <b>${fmt(env.tOut)}°</b> · wind <b>${bftText(env.wind)} ${dirName(env.dir)}</b> · verse lucht <b>${Math.round(totalFresh)} m³/u</b>`;
  document.getElementById("leg-min").textContent = `${lo.toFixed(0)}°`;
  document.getElementById("leg-max").textContent = `${hi.toFixed(0)}°`;
  h3SyncPanel(); h3Wind();
}

function flowText(id) {
  const f = h3.flowInfo[id]; if (!f) return "dicht";
  const q = Math.round(Math.abs(f.q) * 3600), x = Math.round(f.qx * 3600), p = h3.portalById[id];
  const parts = [];
  if (q >= 1) parts.push(p && p.b === "outside" ? `${f.q > 0 ? "↗ uit" : "↘ in"} ${q} m³/u` : `→ ${q} m³/u`);
  if (x >= 1) parts.push(`⇄ ${x} m³/u`);
  return parts.length ? parts.join(" · ") : "≈ 0";
}

// ---------------------------------------------------------------- deeltjes
function h3InitParticles() {
  const T = THREE, N = H3_MAXP, P = h3.P = {
    pos: new Float32Array(N * 3), vel: new Float32Array(N * 3), tgt: new Float32Array(N * 3), exit: new Float32Array(N * 3),
    phase: new Uint8Array(N), zone: new Int16Array(N).fill(-1), edge: new Int32Array(N).fill(-1), temp: new Float32Array(N),
    life: new Float32Array(N), part: new Uint8Array(N), ttl: new Float32Array(N), alpha: new Float32Array(N), seed: new Float32Array(N), age: new Uint8Array(N), spd: new Float32Array(N),
    hist: Array.from({ length: H3_TRAIL + 1 }, () => new Float32Array(N * 3)), head: 0,
  };
  for (let i = 0; i < N; i++) { P.seed[i] = Math.random() * 100; P.life[i] = Math.random() * 6; }
  const cv = document.createElement("canvas"); cv.width = cv.height = 64;
  const c = cv.getContext("2d"), gr = c.createRadialGradient(32, 32, 0, 32, 32, 32);
  gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.25, "rgba(255,255,255,.55)"); gr.addColorStop(1, "rgba(255,255,255,0)");
  c.fillStyle = gr; c.fillRect(0, 0, 64, 64);
  const pg = new T.BufferGeometry();
  P.dpos = new Float32Array(N * 3); P.dcol = new Float32Array(N * 3);
  pg.setAttribute("position", new T.BufferAttribute(P.dpos, 3)); pg.setAttribute("color", new T.BufferAttribute(P.dcol, 3));
  h3.points = new T.Points(pg, new T.PointsMaterial({ size: 0.2, map: new T.CanvasTexture(cv), vertexColors: true, transparent: true,
    blending: T.AdditiveBlending, depthWrite: false, sizeAttenuation: true }));
  h3.points.frustumCulled = false; h3.points.renderOrder = 10;
  const lg = new T.BufferGeometry();
  P.lpos = new Float32Array(N * H3_TRAIL * 6); P.lcol = new Float32Array(N * H3_TRAIL * 6);
  lg.setAttribute("position", new T.BufferAttribute(P.lpos, 3)); lg.setAttribute("color", new T.BufferAttribute(P.lcol, 3));
  h3.trails = new T.LineSegments(lg, new T.LineBasicMaterial({ vertexColors: true, transparent: true, blending: T.AdditiveBlending, depthWrite: false }));
  h3.trails.frustumCulled = false; h3.trails.renderOrder = 9;
}

function pickEdge(list) {
  if (!list || !list.length) return null;
  let tot = 0; for (const e of list) tot += e.w;
  let r = Math.random() * tot;
  for (const e of list) { r -= e.w; if (r <= 0) return e; }
  return list[list.length - 1];
}
function portalPoint(e, out, off) {                 // willekeurig punt in de opening (onder-/bovenhelft bij uitwisseling)
  const p = e.p, a = rnd(-0.8, 0.8) * p.hw, b = (e.half === 0 ? rnd(-0.8, 0.8) : e.half * rnd(0.1, 0.85)) * p.hh;
  const vert = p.roof ? rnd(-0.8, 0.8) * p.hh : b;
  out[off] = p.c.x + p.u.x * a + p.v.x * vert; out[off + 1] = p.c.y + p.u.y * a + p.v.y * vert; out[off + 2] = p.c.z + p.u.z * a + p.v.z * vert;
}
function teleport(i) { h3.P.age[i] = 0; }

function spawn(i) {
  const P = h3.P, e = pickEdge(h3.inflow), o = i * 3;
  if (!e) { P.phase[i] = 0; P.life[i] = rnd(0.5, 2); return; }
  portalPoint(e, P.tgt, o);
  const p = e.p, wl = h3.windLocal, d = rnd(1.2, 3.6), j = rnd(-1.1, 1.1);
  P.pos[o] = P.tgt[o] + p.n.x * d + p.u.x * j - wl.x * rnd(0, 1.6);
  P.pos[o + 1] = Math.max(0.15, P.tgt[o + 1] + p.n.y * d + rnd(-0.5, 0.5));
  P.pos[o + 2] = P.tgt[o + 2] + p.n.z * d + p.u.z * j - wl.z * rnd(0, 1.6);
  P.vel[o] = P.vel[o + 1] = P.vel[o + 2] = 0;
  P.phase[i] = 1; P.edge[i] = e.i; P.zone[i] = -1; P.temp[i] = h3.env.tOut; P.alpha[i] = 0; P.spd[i] = e.v; P.ttl[i] = rnd(30, 70); teleport(i);
}

function enterZone(i, zid) {                         // kies de volgende opening + een tussenpunt in de kamer
  const P = h3.P, o = i * 3, B = h3.box[zid], e = pickEdge(h3.outOf[zid]);
  P.zone[i] = h3.zones.indexOf(zid);
  if (!e || !B) { P.phase[i] = 5; P.life[i] = 0.8; return; }
  const cl = (v, a, b) => clamp(v, a + 0.25, b - 0.25);
  const here = Math.max(0, partAt(B, P.pos[o], P.pos[o + 2]));
  let C = B.parts[here], viaGate = null;
  if (e.to === "sink") {
    P.tgt[o] = rnd(C.x0, C.x1); P.tgt[o + 1] = rnd(B.y0, Math.min(B.y1, P.pos[o + 1] + 1.5)); P.tgt[o + 2] = rnd(C.z0, C.z1);
    P.edge[i] = -2;
  } else {
    portalPoint(e, P.exit, o);
    const there = Math.max(0, partAt(B, P.exit[o], P.exit[o + 2]));
    if (here !== there) viaGate = (B.parts[here].gate || B.parts[there].gate);
    const k = rnd(0.25, 0.75), same = P.edge[i] >= 0 && h3.edges[P.edge[i]] && h3.edges[P.edge[i]].p === e.p;
    if (viaGate) {                                    // uitbouw ↔ kamer: eerst naar de doorgang
      const g = viaGate, along = rnd(g.lo, Math.max(g.lo, g.hi));
      P.tgt[o] = g.ax === "x" ? g.at : along; P.tgt[o + 2] = g.ax === "x" ? along : g.at;
      P.tgt[o + 1] = clamp(lerp(P.pos[o + 1], P.exit[o + 1], 0.5) + rnd(-0.3, 0.3), B.y0 + 0.3, B.y1 - 0.3);
    } else if (same) {                                // in en uit door dezelfde opening: een lus de kamer in
      const s = e.from === e.p.a ? -1 : 1, dpt = rnd(1.0, 3.2), j = rnd(-1.6, 1.6);
      P.tgt[o] = P.pos[o] + e.p.n.x * s * dpt + e.p.u.x * j; P.tgt[o + 1] = P.pos[o + 1] + rnd(-0.4, 0.4) - e.p.n.y * dpt * 0.6; P.tgt[o + 2] = P.pos[o + 2] + e.p.n.z * s * dpt + e.p.u.z * j;
    } else {
      P.tgt[o] = lerp(P.pos[o], P.exit[o], k) + rnd(-1.1, 1.1); P.tgt[o + 1] = lerp(P.pos[o + 1], P.exit[o + 1], k) + rnd(-0.5, 0.5); P.tgt[o + 2] = lerp(P.pos[o + 2], P.exit[o + 2], k) + rnd(-1.1, 1.1);
    }
    P.edge[i] = e.i; P.spd[i] = e.v;
  }
  P.part[i] = viaGate ? 255 : here;                   // 255 = onderweg door de doorgang, niet klemmen
  if (!viaGate) { P.tgt[o] = cl(P.tgt[o], C.x0, C.x1); P.tgt[o + 1] = cl(P.tgt[o + 1], B.y0, B.y1); P.tgt[o + 2] = cl(P.tgt[o + 2], C.z0, C.z1); }
  P.phase[i] = 2;
}

function h3Rechoose() {                              // na een herberekening: binnen blijven, nieuwe route kiezen
  const P = h3.P; if (!P) return;
  for (let i = 0; i < H3_MAXP; i++) {
    const ph = P.phase[i];
    if (ph === 2 || ph === 3) { P.edge[i] = -1; enterZone(i, h3.zones[P.zone[i]]); }
    else if (ph === 1) { P.phase[i] = 5; P.life[i] = 0.3; }
  }
}

function h3Step(dt, time) {
  const P = h3.P, ts = h3.view.speed, sdt = dt * ts, wl = h3.windLocal, col = [0, 0, 0];
  const steer = 1 - Math.exp(-sdt * 3.2), N = H3_MAXP, act = h3.active;
  P.head = (P.head + 1) % (H3_TRAIL + 1);
  const hNow = P.hist[P.head];
  for (let i = 0; i < N; i++) {
    const o = i * 3; let ph = P.phase[i];
    if (i >= act && (ph === 0 || ph === 4 || ph === 5) && P.alpha[i] <= 0.01) { P.phase[i] = 0; P.dcol[o] = P.dcol[o + 1] = P.dcol[o + 2] = 0; P.age[i] = 0; continue; }
    if (ph === 0) { P.life[i] -= dt; P.alpha[i] = 0; if (P.life[i] <= 0 && i < act) spawn(i); ph = P.phase[i]; if (ph === 0) { P.dcol[o] = P.dcol[o + 1] = P.dcol[o + 2] = 0; continue; } }
    if (ph === 4 || ph === 5) {
      P.life[i] -= sdt; P.alpha[i] = Math.max(0, P.alpha[i] - sdt * (ph === 4 ? 0.45 : 1.3));
      if (ph === 4) { const k = 1 - Math.exp(-sdt * 0.8); P.vel[o] = lerp(P.vel[o], wl.x * wl.s, k); P.vel[o + 1] = lerp(P.vel[o + 1], 0.12, k); P.vel[o + 2] = lerp(P.vel[o + 2], wl.z * wl.s, k); }
      else { P.vel[o] *= 0.96; P.vel[o + 1] *= 0.96; P.vel[o + 2] *= 0.96; }
      if (P.life[i] <= 0 || P.alpha[i] <= 0) { P.phase[i] = 0; P.life[i] = rnd(0, 0.6); P.alpha[i] = 0; }
    } else {
      const dx = P.tgt[o] - P.pos[o], dy = P.tgt[o + 1] - P.pos[o + 1], dz = P.tgt[o + 2] - P.pos[o + 2];
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1e-6;
      const near = ph === 2 ? 0 : clamp(1 - dist / 1.6, 0, 1), sp = lerp(0.55, P.spd[i], near), sd = P.seed[i], nz = 0.3 * (1 - near);
      const wx = dx / dist * sp + nz * Math.sin(time * 1.3 + sd * 17), wy = dy / dist * sp + nz * 0.5 * Math.sin(time * 1.7 + sd * 29), wz = dz / dist * sp + nz * Math.cos(time * 1.1 + sd * 13);
      P.vel[o] = lerp(P.vel[o], wx, steer); P.vel[o + 1] = lerp(P.vel[o + 1], wy, steer); P.vel[o + 2] = lerp(P.vel[o + 2], wz, steer);
      P.alpha[i] = Math.min(1, P.alpha[i] + sdt * 0.9);
      P.ttl[i] -= sdt; if (P.ttl[i] <= 0) { P.phase[i] = 5; P.life[i] = 1.0; continue; }
      if (dist < Math.max(0.22, sp * sdt * 1.6)) {
        if (ph === 2) {
          if (P.edge[i] === -2) { P.phase[i] = 5; P.life[i] = 1.2; }
          else { P.tgt[o] = P.exit[o]; P.tgt[o + 1] = P.exit[o + 1]; P.tgt[o + 2] = P.exit[o + 2]; P.phase[i] = 3; }
        } else {                                      // door de opening heen
          const e = h3.edges[P.edge[i]];
          if (!e) { P.phase[i] = 5; P.life[i] = 0.5; }
          else if (e.to === "outside") {
            const s = e.from === e.p.a ? 1 : -1;
            P.phase[i] = 4; P.life[i] = 3.2; P.zone[i] = -1;
            P.vel[o] = e.p.n.x * s * e.v; P.vel[o + 1] = e.p.n.y * s * e.v; P.vel[o + 2] = e.p.n.z * s * e.v;
          } else enterZone(i, e.to);
        }
      }
    }
    P.pos[o] += P.vel[o] * sdt; P.pos[o + 1] += P.vel[o + 1] * sdt; P.pos[o + 2] += P.vel[o + 2] * sdt;
    if (P.phase[i] === 2 && P.zone[i] >= 0 && P.part[i] !== 255) {   // tussenpunt-fase blijft binnen haar doos
      const Z = h3.box[h3.zones[P.zone[i]]], B = Z.parts[P.part[i]] || Z;
      P.pos[o] = clamp(P.pos[o], B.x0 + 0.08, B.x1 - 0.08); P.pos[o + 1] = clamp(P.pos[o + 1], Z.y0 + 0.08, Z.y1 - 0.08); P.pos[o + 2] = clamp(P.pos[o + 2], B.z0 + 0.08, B.z1 - 0.08);
    }
    const zt = P.zone[i] >= 0 ? h3.zoneTemp[h3.zones[P.zone[i]]] : h3.env.tOut;
    P.temp[i] += (zt - P.temp[i]) * (1 - Math.exp(-sdt * 0.22));
    tempColor(P.temp[i], col);
    const a = P.alpha[i];
    P.dpos[o] = P.pos[o]; P.dpos[o + 1] = dispY(P.pos[o + 1]); P.dpos[o + 2] = P.pos[o + 2];
    P.dcol[o] = col[0] * a; P.dcol[o + 1] = col[1] * a; P.dcol[o + 2] = col[2] * a;
    hNow[o] = P.pos[o]; hNow[o + 1] = P.pos[o + 1]; hNow[o + 2] = P.pos[o + 2];
    if (P.age[i] < 250) P.age[i]++;
  }
  // Staartjes: K segmenten terug in de ringbuffer, uitdovend.
  const K = H3_TRAIL, R = K + 1, ex = h3.view.explode > 0.001;
  for (let i = 0; i < N; i++) {
    const o = i * 3, base = i * K * 6, age = P.age[i];
    for (let j = 0; j < K; j++) {
      const q = base + j * 6;
      if (age <= j + 1) { for (let k = 0; k < 6; k++) { P.lcol[q + k] = 0; P.lpos[q + k] = 0; } continue; }
      const A = P.hist[(P.head - j + R) % R], Bq = P.hist[(P.head - j - 1 + R) % R], f0 = 0.55 * (1 - j / K), f1 = 0.55 * (1 - (j + 1) / K);
      const ya = ex ? dispY(A[o + 1]) : A[o + 1], yb = ex ? dispY(Bq[o + 1]) : Bq[o + 1];
      // Uit elkaar getrokken verdiepingen: een staartje dat de kier overbrugt zou een lange streep worden.
      if (ex && Math.abs(ya - yb) > 0.5) { for (let k = 0; k < 6; k++) { P.lcol[q + k] = 0; P.lpos[q + k] = 0; } continue; }
      P.lpos[q] = A[o]; P.lpos[q + 1] = ya; P.lpos[q + 2] = A[o + 2]; P.lpos[q + 3] = Bq[o]; P.lpos[q + 4] = yb; P.lpos[q + 5] = Bq[o + 2];
      P.lcol[q] = P.dcol[o] * f0; P.lcol[q + 1] = P.dcol[o + 1] * f0; P.lcol[q + 2] = P.dcol[o + 2] * f0;
      P.lcol[q + 3] = P.dcol[o] * f1; P.lcol[q + 4] = P.dcol[o + 1] * f1; P.lcol[q + 5] = P.dcol[o + 2] * f1;
    }
  }
  const pg = h3.points.geometry, lg = h3.trails.geometry;
  pg.attributes.position.needsUpdate = pg.attributes.color.needsUpdate = true;
  lg.attributes.position.needsUpdate = lg.attributes.color.needsUpdate = true;
}

// ---------------------------------------------------------------- scène
function h3Init() {
  const T = THREE, stage = document.getElementById("stage");
  const r = h3.renderer = new T.WebGLRenderer({ antialias: true });
  r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  stage.appendChild(r.domElement);
  const scene = h3.scene = new T.Scene();
  // Achtergrond als textuur i.p.v. CSS achter een doorzichtig canvas: additief gemengde
  // deeltjes tellen ook hun alpha op, en dan dekt een "onzichtbaar" zwart staartje de pagina af.
  const bg = document.createElement("canvas"); bg.width = 512; bg.height = 512;
  const bc = bg.getContext("2d"), bgr = bc.createRadialGradient(256, 190, 0, 256, 256, 400);
  bgr.addColorStop(0, "#1b2a45"); bgr.addColorStop(0.55, "#0b1120"); bgr.addColorStop(1, "#05070d");
  bc.fillStyle = bgr; bc.fillRect(0, 0, 512, 512); scene.background = new T.CanvasTexture(bg);
  const cam = h3.camera = new T.PerspectiveCamera(38, 1, 0.1, 200); cam.position.set(17, 13, 21.5);
  const oc = h3.controls = new T.OrbitControls(cam, r.domElement);
  oc.target.set(0, 3, 0); oc.enableDamping = true; oc.dampingFactor = 0.08; oc.minDistance = 6; oc.maxDistance = 60;
  oc.maxPolarAngle = Math.PI * 0.495; oc.autoRotate = true; oc.autoRotateSpeed = 0.6;
  scene.add(new T.HemisphereLight(0xcfe0ff, 0x101624, 0.95));
  const sun = new T.DirectionalLight(0xfff1d6, 0.55); sun.position.set(8, 14, 6); scene.add(sun);
  const ground = new T.Mesh(new T.CircleGeometry(20, 72), new T.MeshBasicMaterial({ color: 0x0a101c, transparent: true, opacity: 0.85 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.12; scene.add(ground);
  const grid = new T.GridHelper(40, 40, 0x2a3a5c, 0x16203a); grid.position.y = -0.11; grid.material.transparent = true; grid.material.opacity = 0.6; scene.add(grid);
  // Kompas (N = −z in wereldcoördinaten).
  [["N", 0], ["O", 90], ["Z", 180], ["W", 270]].forEach(([t, az]) => {
    const cv = document.createElement("canvas"); cv.width = cv.height = 96; const c = cv.getContext("2d");
    c.font = '600 60px "JetBrains Mono", monospace'; c.textAlign = "center"; c.textBaseline = "middle"; c.fillStyle = t === "N" ? "#ff8a3d" : "#8fa6d0"; c.fillText(t, 48, 52);
    const sp = new T.Sprite(new T.SpriteMaterial({ map: new T.CanvasTexture(cv), transparent: true, depthWrite: false })); sp.scale.set(1.3, 1.3, 1);
    sp.position.set(Math.sin(az * H3_RAD) * 14.5, 0.5, -Math.cos(az * H3_RAD) * 14.5); scene.add(sp);
  });
  h3.houseOuter = new T.Group(); h3.houseOuter.rotation.y = (90 - PLAN_FRONT_AZ) * H3_RAD; scene.add(h3.houseOuter);
  h3InitParticles();
  // Omgevingswind: losse stofjes die met de wind over het erf drijven.
  const NA = 500, ap = h3.amb = { n: NA, pos: new Float32Array(NA * 3) };
  for (let i = 0; i < NA; i++) { const a = Math.random() * 6.283, rr = Math.sqrt(Math.random()) * 17; ap.pos[i * 3] = Math.cos(a) * rr; ap.pos[i * 3 + 1] = rnd(0.2, 9); ap.pos[i * 3 + 2] = Math.sin(a) * rr; }
  const ag = new T.BufferGeometry(); ag.setAttribute("position", new T.BufferAttribute(ap.pos, 3));
  h3.ambPts = new T.Points(ag, new T.PointsMaterial({ size: 0.09, color: 0x7f9fd0, transparent: true, opacity: 0.5, blending: T.AdditiveBlending, depthWrite: false, map: h3.points.material.map }));
  scene.add(h3.ambPts);
  h3.windArrow = new T.ArrowHelper(new T.Vector3(1, 0, 0), new T.Vector3(), 3, 0xffd166, 1.1, 0.7); scene.add(h3.windArrow);

  const resize = () => {
    const w = stage.clientWidth, hh = stage.clientHeight; r.setSize(w, hh, false); cam.aspect = w / hh;
    cam.fov = cam.aspect < 1 ? 58 : 38;                 // staand scherm: wijder, anders past het huis niet
    cam.updateProjectionMatrix();
  };
  window.addEventListener("resize", resize); resize();
  h3Pointer(r.domElement);
  h3.clock = new T.Clock(); h3.ready = true;
  r.setAnimationLoop(h3Frame);
}

function h3Wind() {                                   // windvector (waait náár dir+180) in wereld- en huis-assen
  const to = (h3.env.dir + 180) * H3_RAD, s = 0.35 + h3.env.wind * 0.3;
  h3.windWorld = { x: Math.sin(to), z: -Math.cos(to), s };
  const l = localDir(h3.env.dir + 180); h3.windLocal = { x: l.x, z: l.z, s };
  const len = 2 + Math.min(h3.env.wind, 12) * 0.45, w = h3.windWorld;
  h3.windArrow.position.set(-w.x * 13, 0.4, -w.z * 13); h3.windArrow.setDirection(new THREE.Vector3(w.x, 0, w.z)); h3.windArrow.setLength(len, 1.0, 0.65);
  h3.windArrow.visible = h3.env.wind > 0.3;
}

function h3ApplyView(force) {
  const v = h3.view; if (!h3.levelGroups) return;
  h3.wallMat.opacity = lerp(0.04, 0.85, v.glass); h3.wallMat.depthWrite = v.glass > 0.8;
  h3.edgeMat.opacity = lerp(0.75, 0.35, v.glass);
  if (force) h3.roofLift = v.roof ? 0 : 1;
  const dy = (v.explode - (h3.lastExplode || 0)) * H3_EXPLODE_M;   // camera schuift mee omhoog
  if (dy) { h3.controls.target.y += dy; h3.camera.position.y += dy; h3.camera.position.multiplyScalar(1 + dy * 0.02); }
  h3.lastExplode = v.explode;
}

function h3Frame() {
  const dt = Math.min(h3.clock.getDelta(), 0.05), time = h3.clock.elapsedTime, v = h3.view;
  if (h3.levelGroups) {
    h3.levelGroups.forEach((g, i) => { g.position.y = v.explode * H3_EXPLODE_M * i; });
    h3.roofLift = lerp(h3.roofLift, v.roof ? 0 : 1, 1 - Math.exp(-dt * 5));
    h3.roofGroups.forEach(g => { g.position.y = h3.roofLift * 4.5; g.visible = h3.roofLift < 0.97; });
    h3.roofMat.opacity = lerp(0.06, 0.55, v.glass) * (1 - h3.roofLift);
    const k = 1 - Math.exp(-dt * 7);
    h3.portals.forEach(p => { if (p.cur && p.target) { p.cur.hinge = lerp(p.cur.hinge, p.target.hinge, k); p.cur.tilt = lerp(p.cur.tilt, p.target.tilt, k); p.hinge.rotation.y = p.cur.hinge; p.tiltPivot.rotation.x = p.cur.tilt; } });
    h3Step(dt, time);
    // Omgevingswind.
    const a = h3.amb, w = h3.windWorld, sp = w.s * 1.6 * v.speed * dt;
    for (let i = 0; i < a.n; i++) {
      const o = i * 3; a.pos[o] += w.x * sp; a.pos[o + 2] += w.z * sp; a.pos[o + 1] += Math.sin(time + i) * 0.002;
      if (a.pos[o] * a.pos[o] + a.pos[o + 2] * a.pos[o + 2] > 17 * 17) { const lat = rnd(-17, 17), back = Math.sqrt(Math.max(0, 289 - lat * lat)); a.pos[o] = -w.x * back + -w.z * lat; a.pos[o + 2] = -w.z * back + w.x * lat; a.pos[o + 1] = rnd(0.2, 9); }
    }
    h3.ambPts.geometry.attributes.position.needsUpdate = true;
    if (h3.points.parent !== h3.houseInner) { h3.houseInner.add(h3.trails); h3.houseInner.add(h3.points); }
  }
  h3.controls.autoRotate = v.spin; h3.controls.update();
  h3.renderer.render(h3.scene, h3.camera);
}

// ---------------------------------------------------------------- interactie
function cycleState(id) {
  const p = h3.portalById[id]; if (!p || !p.operable) return;
  const order = p.hasTilt ? ["dicht", "tilt", "open"] : ["dicht", "open"];
  h3.states[id] = order[(order.indexOf(h3.states[id]) + 1) % order.length];
  h3Recompute();
}

function h3Pointer(el) {
  const ray = new THREE.Raycaster(), m = new THREE.Vector2(), tip = document.getElementById("tip");
  let down = null;
  const pick = ev => {
    const rc = el.getBoundingClientRect();
    m.set(((ev.clientX - rc.left) / rc.width) * 2 - 1, -((ev.clientY - rc.top) / rc.height) * 2 + 1);
    ray.setFromCamera(m, h3.camera);
    const hit = ray.intersectObjects(h3.hits || [], false)[0];
    return hit ? hit.object.userData.pid : null;
  };
  el.addEventListener("pointerdown", ev => { down = { x: ev.clientX, y: ev.clientY }; h3.view.spin = false; const b = document.querySelector('[data-view="spin"]'); if (b) b.classList.remove("on"); });
  el.addEventListener("pointerup", ev => {
    if (!down || Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 6) return;
    const id = pick(ev); if (id) cycleState(id);
  });
  el.addEventListener("pointermove", ev => {
    if (ev.buttons) { tip.style.display = "none"; return; }
    const id = pick(ev), p = id && h3.portalById[id];
    el.style.cursor = p ? "pointer" : "grab";
    document.querySelectorAll(".op-row.hot").forEach(r => r.classList.remove("hot"));
    if (!p) { tip.style.display = "none"; return; }
    const row = document.querySelector(`.op-row[data-id="${id}"]`); if (row) row.classList.add("hot");
    const nm = { open: "open", tilt: "kier", dicht: "dicht" }[h3.states[id]];
    tip.innerHTML = `<b>${esc(shortLabel(p.el.label || id))}</b>${nm}${h3.states[id] === "dicht" ? "" : " · " + flowText(id)}<br><span style="opacity:.6">klik om te wisselen</span>`;
    tip.style.display = "block"; tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 270) + "px"; tip.style.top = (ev.clientY + 14) + "px";
  });
  el.addEventListener("pointerleave", () => { tip.style.display = "none"; });
}

function h3BuildPanel() {
  const m = h3.meta, e = h3.env, v = h3.view;
  const sl = (key, label, min, max, step) => `<div class="row"><label for="s-${key}">${label}</label><span class="val" id="v-${key}"></span></div>` +
    `<div class="slider"><input type="range" id="s-${key}" data-s="${key}" min="${min}" max="${max}" step="${step}"></div>`;
  const zl = z => shortLabel(((m.rooms || {})[z] || (m.junctions || {})[z] || {}).label || z);
  const groups = {};
  h3.portals.filter(p => p.operable).forEach(p => { const key = p.kind === "door" ? "Binnendeuren" : zl(p.a); (groups[key] = groups[key] || []).push(p); });
  let ops = "";
  Object.entries(groups).forEach(([title, list]) => {
    ops += `<div class="room-title">${esc(title)}</div>`;
    list.forEach(p => {
      const vals = p.hasTilt ? ["dicht", "tilt", "open"] : ["dicht", "open"], nm = { dicht: "Dicht", tilt: "Kier", open: "Open" };
      ops += `<div class="op-row" data-id="${esc(p.id)}"><div><div class="name">${esc(shortLabel(p.el.label || p.id))}</div><div class="flow" data-flow="${esc(p.id)}"></div></div>` +
        `<div class="seg">${vals.map(x => `<button type="button" data-id="${esc(p.id)}" data-v="${x}">${nm[x]}</button>`).join("")}</div></div>`;
    });
  });
  document.getElementById("panel").innerHTML =
    `<div class="grp">Weer</div>` + sl("tOut", "Buitentemperatuur", -5, 36, 0.5) + sl("bft", "Windkracht", 0, 9, 1) + sl("dir", "Windrichting (uit)", 0, 355, 5) +
    `<div class="grp">Beeld</div>` + sl("explode", "Verdiepingen uit elkaar", 0, 1, 0.01) + sl("glass", "Wanden: glas ↔ massief", 0, 1, 0.01) +
    sl("speed", "Tijdversnelling", 0.5, 8, 0.5) + sl("density", "Deeltjes", 0.1, 1, 0.05) +
    `<div class="btns"><button class="btn" type="button" data-view="roof">Dak eraf</button><button class="btn" type="button" data-view="spin">Draaien</button></div>` +
    `<div class="grp">Ramen, roosters &amp; deuren</div>` +
    `<div class="btns"><button class="btn" type="button" data-all="live">↺ Live stand</button><button class="btn" type="button" data-all="open">Alles open</button><button class="btn" type="button" data-all="dicht">Alles dicht</button></div>` +
    ops + `<p class="hint">Wat je hier wisselt is een wat-als in deze browser — er wordt niets gemeld of opgeslagen. De kamertemperaturen blijven op de laatste modelstand staan; alleen de luchtstroom rekent mee.</p>`;
  const set = (k, val) => { document.getElementById("s-" + k).value = val; };
  set("tOut", e.tOut); set("bft", beaufort(e.wind) ?? 2); set("dir", Math.round(e.dir / 5) * 5 % 360);
  set("explode", v.explode); set("glass", v.glass); set("speed", v.speed); set("density", v.density);
  h3SyncPanel();
}

function h3SyncPanel() {
  const e = h3.env, v = h3.view, t = (k, s) => { const n = document.getElementById("v-" + k); if (n) n.textContent = s; };
  t("tOut", `${fmt(e.tOut)} °C`); t("bft", bftText(e.wind)); t("dir", `${dirName(e.dir)} ${Math.round(e.dir)}°`);
  t("explode", `${Math.round(v.explode * 100)} %`); t("glass", `${Math.round(v.glass * 100)} %`); t("speed", `${v.speed}×`); t("density", `${Math.round(v.density * 100)} %`);
  document.querySelectorAll("#panel .seg button").forEach(b => b.classList.toggle("on", h3.states[b.dataset.id] === b.dataset.v));
  document.querySelectorAll("#panel [data-flow]").forEach(n => { n.textContent = h3.states[n.dataset.flow] === "dicht" ? "" : flowText(n.dataset.flow); });
  const rb = document.querySelector('[data-view="roof"]'), sb = document.querySelector('[data-view="spin"]');
  if (rb) rb.classList.toggle("on", !v.roof); if (sb) sb.classList.toggle("on", v.spin);
}

function h3BindPanel() {
  const panel = document.getElementById("panel");
  panel.addEventListener("input", ev => {
    const k = ev.target.dataset && ev.target.dataset.s; if (!k) return;
    const val = +ev.target.value;
    if (k === "tOut") h3.env.tOut = val; else if (k === "bft") h3.env.wind = beaufortToMs(val); else if (k === "dir") h3.env.dir = val;
    else { h3.view[k] = val; h3ApplyView(); if (k !== "density") { h3SyncPanel(); return; } }
    h3Recompute();
  });
  panel.addEventListener("click", ev => {
    const b = ev.target.closest("button"); if (!b) return;
    if (b.dataset.v) { h3.states[b.dataset.id] = b.dataset.v; h3Recompute(); }
    else if (b.dataset.view) { const k = b.dataset.view; h3.view[k] = !h3.view[k]; h3SyncPanel(); }
    else if (b.dataset.all) {
      const a = b.dataset.all;
      if (a === "live") { h3.states = Object.assign({}, h3.live); h3.env = Object.assign({}, h3.liveEnv); h3BuildPanel(); }
      else Object.keys(h3.states).forEach(id => { h3.states[id] = a; });
      h3Recompute();
    }
  });
  const tg = document.getElementById("panel-toggle");
  tg.addEventListener("click", () => panel.classList.toggle("closed"));
  if (window.innerWidth < 760) panel.classList.add("closed");
}

document.addEventListener("DOMContentLoaded", () => { h3BindPanel(); h3Load(); });
