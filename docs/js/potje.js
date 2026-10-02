// potje.js — zindelijkheidstraining (Project 17). Registreert plas-/poepmomenten
// in potty_log.json (privé GIST_ID-gist; deze pagina is de enige schrijver) en
// rekent de analyse client-side uit dat logboek + potty_state.json (de
// herinneringslog die potty_reminder.py schrijft).
//
// Privacy: zonder gekoppeld account toont de pagina niets — het logboek is
// gedragsdata van het huishouden. En bewust géén workflow-dispatch bij opslaan:
// de herinneringsloop leest de Gist elke 5 minuten vanzelf.

const LOG_FILE = "potty_log.json";
const STATE_FILE = "potty_state.json";

// Gespiegeld uit potty_reminder.py — tests/test_potty_reminder.py bewaakt dat
// deze waarden gelijk blijven (anders voorspelt de tegel een ander moment dan
// de herinnering die echt uitgaat).
const RULES = {
  INTERVAL_PEE_MIN: 90,
  INTERVAL_TRY_MIN: 30,
  INTERVAL_REPEAT_MIN: 30,
  MAX_REMINDERS_PER_ANCHOR: 2,
  DAY_START_H: 7,
  DAY_END_H: 19,
  STALE_MIN: 60,
};

// Hoe lang na een herinnering een registratie nog als "reactie" telt.
const RESPONSE_WINDOW_MIN = 30;

const WHERES = ["wc", "potje", "ongeluk", "geprobeerd"];
const WHERE_LABEL = { wc: "wc", potje: "potje", ongeluk: "ongelukje", geprobeerd: "geprobeerd" };
const WHERE_ICON = { wc: "🚽", potje: "🪣", ongeluk: "💦", geprobeerd: "🤞" };
const KIND_ICON = { plas: "💧", poep: "💩" };
// Zelfde waarden als de CSS-variabelen in potje.html (gevalideerd palet).
const WHERE_COLORS = { wc: "#3a8a4a", potje: "#2f62b0", ongeluk: "#c94b2a", geprobeerd: "#9a6cc4" };
const SUCCESS = new Set(["wc", "potje"]);
const REAL_PEE = new Set(["wc", "potje", "ongeluk"]);

const ui = { selected: { plas: null, poep: null }, ago: 0, days: 14, charts: {} };
let store = { events: [], state: {} };

document.getElementById("folio-mark").textContent = `Terroir de Utrecht · Est. ${new Date().getFullYear()} · Potje`;
document.getElementById("today-date").textContent = new Date().toLocaleDateString("nl-NL", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
document.getElementById("refresh-btn").addEventListener("click", loadData);

// ── Hulpjes ─────────────────────────────────────────────────────────────────
const pad = (n) => String(n).padStart(2, "0");
const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const minutesBetween = (a, b) => (b - a) / 60000;

function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const a = Math.abs(off);
  return `${dayKey(d)}T${hhmm(d)}:${pad(d.getSeconds())}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

function newId() {
  if (window.crypto?.randomUUID) return crypto.randomUUID().slice(0, 12);
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function gistConfigured() {
  return CONFIG.gistId && CONFIG.gistId !== "__GIST_ID__" && CONFIG.githubToken;
}

// ── Gist-I/O ────────────────────────────────────────────────────────────────
async function fetchGistFiles() {
  const r = await fetch(`https://api.github.com/gists/${CONFIG.gistId}`,
    { headers: { Authorization: `token ${CONFIG.githubToken}` }, cache: "no-store" });
  if (!r.ok) throw new Error(`Gist fetch: HTTP ${r.status}`);
  const files = (await r.json()).files || {};
  // Boven ~1 MB kapt de API `content` af; dat duurt jaren, maar liever een
  // duidelijke fout dan een halve lijst die bij opslaan de rest wegschrijft.
  if (files[LOG_FILE]?.truncated) throw new Error("potty_log.json is te groot geworden voor de Gist-API");
  const parse = (f) => { try { return f?.content ? JSON.parse(f.content) : {}; } catch { return {}; } };
  return { log: parse(files[LOG_FILE]), state: parse(files[STATE_FILE]) };
}

function parseEvents(log) {
  const out = [];
  for (const e of log?.events || []) {
    if (!e || !["plas", "poep"].includes(e.kind) || !WHERES.includes(e.where)) continue;
    const dt = new Date(e.t);
    if (isNaN(dt)) continue;
    out.push({ ...e, dt });
  }
  return out.sort((a, b) => a.dt - b.dt);
}

// ── Laden ───────────────────────────────────────────────────────────────────
async function loadData() {
  const banner = document.getElementById("banner-slot");
  banner.innerHTML = "";
  if (!gistConfigured()) {
    banner.innerHTML = `<div class="banner banner-warn">🔒 Deze pagina is privé — koppel je account ` +
      `(🔑 Account hierboven) om te registreren en de analyse te zien.</div>`;
    document.getElementById("app").hidden = true;
    return;
  }
  document.getElementById("source-label").innerHTML = '<span class="pulse">⋯ laden…</span>';
  try {
    const { log, state } = await fetchGistFiles();
    store = { events: parseEvents(log), state };
    document.getElementById("app").hidden = false;
    document.getElementById("source-label").textContent = `bijgewerkt ${hhmm(new Date())}`;
    renderAll();
  } catch (e) {
    banner.innerHTML = `<div class="banner banner-error"><strong>Kan het logboek niet laden:</strong> ${e.message}</div>`;
    document.getElementById("source-label").textContent = "";
  }
}

// ── Registreren ─────────────────────────────────────────────────────────────
document.getElementById("pick").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".cell");
  if (!btn) return;
  const { kind, where } = btn.dataset;
  ui.selected[kind] = ui.selected[kind] === where ? null : where;
  syncPick();
});

function syncPick() {
  document.querySelectorAll("#pick .cell").forEach((b) => {
    const on = ui.selected[b.dataset.kind] === b.dataset.where;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.style.setProperty("--c", WHERE_COLORS[b.dataset.where]);
  });
  document.getElementById("save-btn").disabled = !(ui.selected.plas || ui.selected.poep);
}

document.getElementById("when").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  ui.ago = Number(chip.dataset.ago);
  document.getElementById("when-time").value = "";
  syncWhen();
});
document.getElementById("when-time").addEventListener("input", () => { ui.ago = null; syncWhen(); });

function syncWhen() {
  document.querySelectorAll("#when .chip").forEach((c) =>
    c.classList.toggle("active", ui.ago !== null && Number(c.dataset.ago) === ui.ago));
}

function chosenTime() {
  const now = new Date();
  const val = document.getElementById("when-time").value;
  if (ui.ago === null && val) {
    const [h, m] = val.split(":").map(Number);
    const d = new Date(now);
    d.setHours(h, m, 0, 0);
    return d;
  }
  return new Date(now.getTime() - (ui.ago || 0) * 60000);
}

document.getElementById("save-btn").addEventListener("click", async () => {
  const status = document.getElementById("save-status");
  const t = chosenTime();
  if (t.getTime() > Date.now() + 60000) { status.textContent = "Dat tijdstip ligt in de toekomst."; return; }
  const fresh = Object.entries(ui.selected)
    .filter(([, where]) => where)
    .map(([kind, where]) => ({ id: newId(), t: isoLocal(t), kind, where }));
  const btn = document.getElementById("save-btn");
  btn.disabled = true;
  status.textContent = "Opslaan…";
  try {
    // Verse read vlak vóór de PATCH: twee telefoons die kort na elkaar opslaan
    // mogen elkaars registratie niet overschrijven.
    const { log } = await fetchGistFiles();
    const events = Array.isArray(log.events) ? log.events : [];
    events.push(...fresh);
    await gistWriteFile(LOG_FILE, JSON.stringify({ events }, null, 1));
    status.textContent = "✓ Opgeslagen: " + fresh.map((e) => `${KIND_ICON[e.kind]} ${WHERE_LABEL[e.where]}`).join(" + ") + ` om ${hhmm(t)}`;
    ui.selected = { plas: null, poep: null };
    ui.ago = 0;
    document.getElementById("when-time").value = "";
    syncWhen();
    syncPick();
    await loadData();
  } catch (e) {
    status.textContent = "Niet opgeslagen: " + e.message;
    btn.disabled = false;
  }
});

async function removeEvent(id) {
  if (!confirm("Deze registratie verwijderen?")) return;
  const status = document.getElementById("save-status");
  try {
    const { log } = await fetchGistFiles();
    const events = (log.events || []).filter((e) => e.id !== id);
    await gistWriteFile(LOG_FILE, JSON.stringify({ events }, null, 1));
    status.textContent = "Verwijderd.";
    await loadData();
  } catch (e) {
    status.textContent = "Verwijderen mislukt: " + e.message;
  }
}

document.getElementById("today-list").addEventListener("click", (ev) => {
  const b = ev.target.closest(".rm");
  if (b) removeEvent(b.dataset.id);
});

// ── Herinneringslogica (spiegel van potty_reminder.next_reminder) ─────────
function nextReminder(events, state, now) {
  const today = dayKey(now);
  let anchor = null;
  for (const e of events) {
    if (e.kind === "plas" && e.dt <= now && dayKey(e.dt) === today &&
        (!anchor || e.dt >= anchor.dt)) anchor = e;
  }
  if (!anchor) return null;
  const key = String(anchor.id || anchor.t);
  const sent = (state.reminders || []).filter((r) => r && r.anchor === key);
  if (sent.length >= RULES.MAX_REMINDERS_PER_ANCHOR) return { done: true, anchor };
  if (sent.length) {
    return { due: new Date(new Date(sent[sent.length - 1].t).getTime() + RULES.INTERVAL_REPEAT_MIN * 60000), kind: "herhaal", anchor };
  }
  const mins = anchor.where === "geprobeerd" ? RULES.INTERVAL_TRY_MIN : RULES.INTERVAL_PEE_MIN;
  return { due: new Date(anchor.dt.getTime() + mins * 60000), kind: anchor.where === "geprobeerd" ? "poging" : "plas", anchor };
}

function reminderText(now) {
  const nxt = nextReminder(store.events, store.state, now);
  if (!nxt) return ["—", "pas na de eerste registratie van vandaag"];
  if (nxt.done) return ["—", "al herinnerd; wacht op de volgende registratie"];
  const start = new Date(now); start.setHours(RULES.DAY_START_H, 0, 0, 0);
  const end = new Date(now); end.setHours(RULES.DAY_END_H, 0, 0, 0);
  let fire = nxt.due < start ? start : nxt.due;
  if (fire >= end || minutesBetween(nxt.due, fire) > RULES.STALE_MIN ||
      minutesBetween(nxt.due, now) > RULES.STALE_MIN) {
    return ["—", "geen meer vandaag"];
  }
  const label = { plas: "na het laatste plasje", poging: "na de poging", herhaal: "herhaling" }[nxt.kind];
  if (fire < now) fire = now;
  const inMin = Math.max(0, Math.round(minutesBetween(now, fire)));
  return [`~${hhmm(fire)}`, `${label} · over ${inMin} min (±5)`];
}

// ── Analyse ─────────────────────────────────────────────────────────────────
function periodDays(n, endOffset = 0) {
  const out = [];
  const base = new Date(); base.setHours(12, 0, 0, 0);
  for (let i = n - 1 + endOffset; i >= endOffset; i--) {
    const d = new Date(base); d.setDate(d.getDate() - i);
    out.push(dayKey(d));
  }
  return out;
}

function dryRate(evs) {
  const real = evs.filter((e) => e.kind === "plas" && REAL_PEE.has(e.where));
  if (!real.length) return null;
  return real.filter((e) => SUCCESS.has(e.where)).length / real.length;
}

function renderAll() {
  renderToday();
  renderTiles();
  renderTimeline();
  renderDayCharts();
  renderHours();
  renderGaps();
  renderReminders();
  renderPoop();
}

function renderToday() {
  const today = dayKey(new Date());
  const list = store.events.filter((e) => dayKey(e.dt) === today).reverse();
  const el = document.getElementById("today-list");
  if (!list.length) { el.innerHTML = `<div style="color:var(--ink-soft);font-style:italic;padding:6px 0;">Nog niets vandaag.</div>`; return; }
  el.innerHTML = list.map((e) =>
    `<div class="row"><span>${hhmm(e.dt)} · ${KIND_ICON[e.kind]} ${WHERE_ICON[e.where]} ${WHERE_LABEL[e.where]}</span>` +
    `<button class="rm" data-id="${String(e.id || "").replace(/[^\w-]/g, "")}" aria-label="Verwijderen" title="Verwijderen">✕</button></div>`
  ).join("");
}

function tile(label, big, sub) {
  return `<div class="specimen-card tile"><div class="corner-mark">${label}</div>` +
    `<div class="big-num">${big}</div><div class="sub">${sub}</div></div>`;
}

function renderTiles() {
  const now = new Date();
  const today = dayKey(now);
  const todays = store.events.filter((e) => dayKey(e.dt) === today);
  const lastPee = [...todays].reverse().find((e) => e.kind === "plas" && REAL_PEE.has(e.where));
  const realToday = todays.filter((e) => e.kind === "plas" && REAL_PEE.has(e.where));
  const okToday = realToday.filter((e) => SUCCESS.has(e.where)).length;

  const inRange = (keys) => { const s = new Set(keys); return store.events.filter((e) => s.has(dayKey(e.dt))); };
  const cur = dryRate(inRange(periodDays(ui.days)));
  const prev = dryRate(inRange(periodDays(ui.days, ui.days)));
  let trend = "geen vergelijking";
  if (cur !== null && prev !== null) {
    const d = Math.round((cur - prev) * 100);
    trend = `${d >= 0 ? "▲" : "▼"} ${Math.abs(d)} pt t.o.v. de ${ui.days} dagen ervoor`;
  }

  const [remBig, remSub] = reminderText(now);
  document.getElementById("tiles").innerHTML = [
    tile("Laatste plasje", lastPee ? hhmm(lastPee.dt) : "—",
      lastPee ? `${Math.round(minutesBetween(lastPee.dt, now))} min geleden · ${WHERE_LABEL[lastPee.where]}` : "nog niet vandaag"),
    tile("Volgende herinnering", remBig, remSub),
    tile("Droog vandaag", realToday.length ? `${okToday}/${realToday.length}` : "—",
      realToday.length ? `${Math.round(okToday / realToday.length * 100)}% op wc of potje` : "nog geen plasjes"),
    tile(`Droog · ${ui.days} dagen`, cur === null ? "—" : `${Math.round(cur * 100)}%`, trend),
    tile("Droge reeks", `${dryStreak()}`, "dagen op rij zonder plas-ongelukje"),
  ].join("");
}

// Dagen op rij (terug vanaf vandaag) met registraties maar zonder plas-ongelukje.
// Een dag zonder enige registratie telt niet mee en breekt de reeks niet.
function dryStreak() {
  const byDay = {};
  for (const e of store.events) (byDay[dayKey(e.dt)] ||= []).push(e);
  let streak = 0;
  const d = new Date(); d.setHours(12, 0, 0, 0);
  for (let i = 0; i < 365; i++) {
    const evs = byDay[dayKey(d)];
    if (evs) {
      if (evs.some((e) => e.kind === "plas" && e.where === "ongeluk")) break;
      streak++;
    }
    d.setDate(d.getDate() - 1);
  }
  return streak;
}

function legend(id, keys) {
  document.getElementById(id).innerHTML = keys.map((k) =>
    `<span><i style="background:${WHERE_COLORS[k]}"></i>${WHERE_ICON[k]} ${WHERE_LABEL[k]}</span>`).join("");
}

function renderTimeline() {
  const now = new Date();
  const today = dayKey(now);
  const H0 = 6, H1 = 20;
  const pos = (d) => Math.max(0, Math.min(100, ((d.getHours() + d.getMinutes() / 60) - H0) / (H1 - H0) * 100));
  const todays = store.events.filter((e) => dayKey(e.dt) === today);
  const rems = (store.state.reminders || []).map((r) => new Date(r.t)).filter((d) => !isNaN(d) && dayKey(d) === today);
  const lane = (kind, label) => {
    const dots = todays.filter((e) => e.kind === kind).map((e) =>
      `<div class="dot ${e.where === "geprobeerd" ? "try" : ""}" style="left:${pos(e.dt)}%;background:${WHERE_COLORS[e.where]}" ` +
      `title="${hhmm(e.dt)} · ${WHERE_LABEL[e.where]}"></div>`).join("");
    const ticks = kind === "plas" ? rems.map((d) => `<div class="rem" style="left:${pos(d)}%" title="herinnering ${hhmm(d)}"></div>`).join("") : "";
    return `<div class="lane"><div class="lane-label">${label}</div><div class="lane-track">${ticks}${dots}</div></div>`;
  };
  const nowTick = `<div class="rem" style="left:${pos(now)}%;background:var(--clay);opacity:1" title="nu"></div>`;
  let axis = "";
  for (let h = H0; h <= H1; h += 2) axis += `<span style="left:${(h - H0) / (H1 - H0) * 100}%">${pad(h)}</span>`;
  document.getElementById("timeline").innerHTML =
    lane("plas", "💧 plas") + lane("poep", "💩 poep") +
    `<div class="lane" style="height:0;border:0"><div class="lane-track" style="height:68px;top:-68px">${nowTick}</div></div>` +
    `<div class="axis">${axis}</div>`;
  document.getElementById("legend-tl").innerHTML =
    WHERES.map((k) => `<span><i style="background:${WHERE_COLORS[k]}"></i>${WHERE_LABEL[k]}</span>`).join("") +
    `<span><i style="background:var(--ink);opacity:.5;width:2px"></i>herinnering</span>` +
    `<span><i style="background:var(--clay);width:2px"></i>nu</span>`;
}

function chart(id, config) {
  ui.charts[id]?.destroy();
  ui.charts[id] = new Chart(document.getElementById(id), config);
}

const AXIS = {
  grid: { color: "#2a241b14" },
  ticks: { color: COLORS.inkSoft, font: { family: "JetBrains Mono", size: 10 } },
  border: { color: "#2a241b44" },
};
const BAR = { borderRadius: 4, borderColor: COLORS.parchment, borderWidth: 1, maxBarThickness: 28 };

function renderDayCharts() {
  const keys = periodDays(ui.days);
  const labels = keys.map((k) => new Date(k + "T12:00").toLocaleDateString("nl-NL", { weekday: "short", day: "numeric" }));
  const pees = store.events.filter((e) => e.kind === "plas");
  const count = (k, w) => pees.filter((e) => dayKey(e.dt) === k && e.where === w).length;
  legend("legend-days", WHERES);
  chart("chart-days", {
    type: "bar",
    data: { labels, datasets: WHERES.map((w) => ({ label: WHERE_LABEL[w], data: keys.map((k) => count(k, w)), backgroundColor: WHERE_COLORS[w], ...BAR })) },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false } },
      scales: { x: { stacked: true, ...AXIS }, y: { stacked: true, beginAtZero: true, ...AXIS, ticks: { ...AXIS.ticks, precision: 0 } } },
    },
  });

  const daily = keys.map((k) => {
    const r = dryRate(pees.filter((e) => dayKey(e.dt) === k));
    return r === null ? null : Math.round(r * 100);
  });
  const rolling = keys.map((_, i) => {
    const win = keys.slice(Math.max(0, i - 2), i + 1);
    const r = dryRate(pees.filter((e) => win.includes(dayKey(e.dt))));
    return r === null ? null : Math.round(r * 100);
  });
  chart("chart-rate", {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "3-daags", data: rolling, borderColor: COLORS.moss, borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: true },
        { label: "per dag", data: daily, borderColor: COLORS.moss, backgroundColor: COLORS.parchment, showLine: false, pointRadius: 4, pointBorderWidth: 2 },
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y ?? "—"}%` } } },
      scales: { x: AXIS, y: { min: 0, max: 100, ...AXIS, ticks: { ...AXIS.ticks, callback: (v) => v + "%" } } },
    },
  });
}

function renderHours() {
  const keys = new Set(periodDays(ui.days));
  const hours = [];
  for (let h = 6; h <= 20; h++) hours.push(h);
  const pees = store.events.filter((e) => e.kind === "plas" && keys.has(dayKey(e.dt)));
  const sets = ["wc", "potje", "ongeluk"];
  legend("legend-hours", sets);
  chart("chart-hours", {
    type: "bar",
    data: {
      labels: hours.map((h) => pad(h) + "u"),
      datasets: sets.map((w) => ({ label: WHERE_LABEL[w], data: hours.map((h) => pees.filter((e) => e.where === w && e.dt.getHours() === h).length), backgroundColor: WHERE_COLORS[w], ...BAR })),
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false } },
      scales: { x: { stacked: true, ...AXIS }, y: { stacked: true, beginAtZero: true, ...AXIS, ticks: { ...AXIS.ticks, precision: 0 } } },
    },
  });
}

// Minuten sinds het vorige echte plasje (zelfde dag), per uitkomst. Antwoordt
// op "is 90 minuten het goede interval?": vallen de ongelukjes vóór 90 min,
// dan komt de herinnering structureel te laat.
function renderGaps() {
  const keys = new Set(periodDays(ui.days));
  const real = store.events.filter((e) => e.kind === "plas" && REAL_PEE.has(e.where));
  const gaps = { ok: [], acc: [] };
  for (let i = 1; i < real.length; i++) {
    const a = real[i - 1], b = real[i];
    if (!keys.has(dayKey(b.dt)) || dayKey(a.dt) !== dayKey(b.dt)) continue;
    (SUCCESS.has(b.where) ? gaps.ok : gaps.acc).push(minutesBetween(a.dt, b.dt));
  }
  const edges = [0, 30, 60, 90, 120, 150, 180];
  const labels = edges.map((e, i) => i < edges.length - 1 ? `${e}–${edges[i + 1]}` : `${e}+`);
  const bin = (xs) => edges.map((e, i) => xs.filter((x) => x >= e && (i === edges.length - 1 || x < edges[i + 1])).length);
  document.getElementById("legend-gap").innerHTML =
    `<span><i style="background:${WHERE_COLORS.potje}"></i>gelukt (wc/potje)</span>` +
    `<span><i style="background:${WHERE_COLORS.ongeluk}"></i>ongelukje</span>`;
  chart("chart-gap", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "gelukt", data: bin(gaps.ok), backgroundColor: WHERE_COLORS.potje, ...BAR },
        { label: "ongelukje", data: bin(gaps.acc), backgroundColor: WHERE_COLORS.ongeluk, ...BAR },
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: (c) => `${c[0].label} min na het vorige plasje` } } },
      scales: { x: { ...AXIS, title: { display: true, text: "minuten sinds vorig plasje", color: COLORS.inkSoft, font: { family: "JetBrains Mono", size: 10 } } }, y: { beginAtZero: true, ...AXIS, ticks: { ...AXIS.ticks, precision: 0 } } },
    },
  });
  const mOk = median(gaps.ok), mAcc = median(gaps.acc);
  let txt = "";
  if (mOk !== null) txt += `Geslaagde plasjes kwamen mediaan <b>${Math.round(mOk)} min</b> na het vorige. `;
  if (mAcc !== null) txt += `Ongelukjes mediaan na <b>${Math.round(mAcc)} min</b>. `;
  if (gaps.acc.length >= 3 && mAcc < RULES.INTERVAL_PEE_MIN) {
    txt += `De meeste ongelukjes vallen vóór de herinnering (${RULES.INTERVAL_PEE_MIN} min) — een korter interval, bijvoorbeeld ~${Math.max(30, Math.round((mAcc - 10) / 15) * 15)} min, kan helpen.`;
  } else if (gaps.acc.length >= 3) {
    txt += `De ongelukjes vallen ná het herinneringsmoment — het interval lijkt goed; let vooral op of er na de herinnering ook echt geprobeerd wordt.`;
  } else if (!txt) {
    txt = "Nog te weinig plasjes op één dag om het ritme te zien.";
  }
  document.getElementById("gap-insight").innerHTML = txt;
}

function renderReminders() {
  const keys = new Set(periodDays(ui.days));
  const rems = (store.state.reminders || []).map((r) => ({ ...r, dt: new Date(r.t) }))
    .filter((r) => !isNaN(r.dt) && keys.has(dayKey(r.dt)));
  const el = document.getElementById("reminders");
  if (!rems.length) { el.innerHTML = `<p class="insight" style="font-style:italic;color:var(--ink-soft)">Nog geen herinneringen in deze periode.</p>`; return; }
  const out = { gelukt: 0, geprobeerd: 0, ongeluk: 0, geen: 0 };
  for (const r of rems) {
    const next = store.events.find((e) => e.kind === "plas" && e.dt > r.dt && minutesBetween(r.dt, e.dt) <= RESPONSE_WINDOW_MIN);
    if (!next) out.geen++;
    else if (SUCCESS.has(next.where)) out.gelukt++;
    else if (next.where === "geprobeerd") out.geprobeerd++;
    else out.ongeluk++;
  }
  const n = rems.length;
  const pct = (x) => `${Math.round(x / n * 100)}%`;
  const row = (icon, label, x) => `<tr><td>${icon} ${label}</td><td>${x}</td><td>${pct(x)}</td></tr>`;
  el.innerHTML =
    `<p class="insight">${n} herinneringen in ${ui.days} dagen. Wat volgde er binnen ${RESPONSE_WINDOW_MIN} minuten?</p>` +
    `<table class="data"><thead><tr><th>Reactie</th><th>Aantal</th><th>Deel</th></tr></thead><tbody>` +
    row("✅", "plasje op wc/potje", out.gelukt) + row(WHERE_ICON.geprobeerd, "geprobeerd", out.geprobeerd) +
    row(WHERE_ICON.ongeluk, "ongelukje", out.ongeluk) + row("·", "niets geregistreerd", out.geen) +
    `</tbody></table>`;
}

function renderPoop() {
  const keys = periodDays(ui.days);
  const ks = new Set(keys);
  const poops = store.events.filter((e) => e.kind === "poep" && ks.has(dayKey(e.dt)));
  const el = document.getElementById("poop");
  const all = store.events.filter((e) => e.kind === "poep" && e.where !== "geprobeerd");
  const last = all[all.length - 1];
  const real = poops.filter((e) => e.where !== "geprobeerd");
  const ok = real.filter((e) => SUCCESS.has(e.where)).length;
  const daysWith = new Set(real.map((e) => dayKey(e.dt))).size;
  const mtRaw = median(real.map((e) => e.dt.getHours() * 60 + e.dt.getMinutes()));
  const mt = mtRaw === null ? null : Math.round(mtRaw);
  const sinceDays = last ? Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(last.dt).setHours(0, 0, 0, 0)) / 864e5) : null;
  const rows = WHERES.map((w) => `<tr><td>${WHERE_ICON[w]} ${WHERE_LABEL[w]}</td><td>${poops.filter((e) => e.where === w).length}</td></tr>`).join("");
  el.innerHTML =
    `<p class="insight">` +
    (real.length ? `${ok} van ${real.length} poepjes op wc of potje (${Math.round(ok / real.length * 100)}%). ` : "Nog geen poepjes in deze periode. ") +
    (real.length ? `Gepoept op ${daysWith} van de ${keys.length} dagen` + (mt !== null ? `, meestal rond <b>${pad(Math.floor(mt / 60))}:${pad(mt % 60)}</b>` : "") + ". " : "") +
    (sinceDays !== null ? `Laatste poepje: ${sinceDays === 0 ? "vandaag" : sinceDays === 1 ? "gisteren" : sinceDays + " dagen geleden"}.` : "") +
    `</p><table class="data"><thead><tr><th>Waar</th><th>Aantal</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ── Periodekeuze ────────────────────────────────────────────────────────────
document.querySelector(".range").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  ui.days = Number(chip.dataset.days);
  document.querySelectorAll(".range .chip").forEach((c) => c.classList.toggle("active", c === chip));
  renderAll();
});

syncPick();
loadData();
// Tegels en tijdlijn lopen met de klok mee (herinnering "over N min").
setInterval(() => { if (!document.getElementById("app").hidden) { renderTiles(); renderTimeline(); } }, 60000);
