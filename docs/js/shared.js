// shared.js — gedeelde Gist/token/artefact-logica voor de dashboards die een
// privé artefact lezen of naar de Gist schrijven (index, mowing, vent, window,
// grafiek). Vóór het pagina-script laden.
//
// Het token staat alleen in déze browser (localStorage) en hoort een
// fine-grained token te zijn dat tot de ene Gist is gescopet. De puur publieke
// pagina's (accuracy, model, camping) laden dit niet — die hebben geen
// artefact-gist of token nodig.

const CONFIG = { gistId: "__GIST_ID__", githubToken: null, artefactGistId: null };

{
  const lsGist = localStorage.getItem("gist_id");
  const lsToken = localStorage.getItem("gh_token");
  const lsArtefact = localStorage.getItem("artefact_gist_id");
  if (lsGist) CONFIG.gistId = lsGist;
  if (lsToken) CONFIG.githubToken = lsToken;
  if (lsArtefact) CONFIG.artefactGistId = lsArtefact;
}

// Eerste keer: vraag Gist ID + token en bewaar ze. Geeft false bij annuleren.
function ensureGistConfig() {
  if (CONFIG.gistId && CONFIG.gistId !== "__GIST_ID__" && CONFIG.githubToken) return true;
  const gid = prompt("Eerste keer: plak je Gist ID (uit de URL van je gist):");
  if (!gid) return false;
  const cleanGid = gid.trim();
  if (!/^[a-f0-9]{20,}$/i.test(cleanGid)) {
    alert("Dit ziet er niet uit als een Gist ID (verwacht een hex-string).");
    return false;
  }
  const token = prompt(
    "Plak een GitHub fine-grained token met 'Gists: read & write' " +
    "(scope dit token tot alleen deze gist).\n\n" +
    "Let op: het token wordt in jouw browser opgeslagen — gebruik geen " +
    "classic PAT met brede 'gist' scope, want die geeft toegang tot al je gists."
  );
  if (!token) return false;
  const cleanToken = token.trim();
  // github_pat_ = fine-grained, ghp_ = classic. Waarschuw bij classic.
  if (cleanToken.startsWith("ghp_")) {
    const ok = confirm(
      "Dit lijkt een classic PAT (ghp_…). Die geeft toegang tot ÁL jouw gists, " +
      "niet alleen deze. Liever een fine-grained token (github_pat_…) maken.\n\n" +
      "Toch doorgaan?"
    );
    if (!ok) return false;
  }
  localStorage.setItem("gist_id", cleanGid);
  localStorage.setItem("gh_token", cleanToken);
  CONFIG.gistId = cleanGid;
  CONFIG.githubToken = cleanToken;
  return true;
}

function forgetCredentials() {
  if (!confirm("Gist ID, token en artefact-gist ID uit deze browser verwijderen?")) return;
  localStorage.removeItem("gist_id");
  localStorage.removeItem("gh_token");
  localStorage.removeItem("artefact_gist_id");
  CONFIG.gistId = "__GIST_ID__";
  CONFIG.githubToken = null;
  CONFIG.artefactGistId = null;
  alert("Verwijderd. Je krijgt opnieuw de prompt zodra je iets opslaat.");
  location.reload();
}

// ── Discoverable "login" (aug 2026) ──────────────────────────────────────────
// Vóór dit knopje bestond alleen een reactieve prompt (bij een mislukte laadpoging
// of de eerste keer opslaan) — geen zichtbare plek om de koppeling in te zien of
// te wijzigen. De #account-btn (index/mowing/vent/window/grafiek) opent dit;
// localStorage is gedeeld over de hele site, dus één keer instellen volstaat
// voor alle pagina's.
function accountStatusText() {
  const g = CONFIG.gistId && CONFIG.gistId !== "__GIST_ID__";
  const t = !!CONFIG.githubToken;
  const a = !!CONFIG.artefactGistId;
  if (g && t && a) return "Gekoppeld: Gist + token + artefact-gist.";
  if (g && t) return "Gist + token gekoppeld — artefact-gist (privé dashboard-data) nog niet.";
  return "Nog niet gekoppeld.";
}

function openAccountSettings() {
  const gid = prompt(
    accountStatusText() +
    "\n\nHoofd-Gist ID (schrijven — openingen/irrigaties/mowings/etc.), " +
    "of typ 'reset' om alles te ontkoppelen:",
    CONFIG.gistId !== "__GIST_ID__" ? CONFIG.gistId : ""
  );
  if (gid === null) return;
  if (gid.trim().toLowerCase() === "reset") { forgetCredentials(); return; }
  const cleanGid = gid.trim();
  if (cleanGid && !/^[a-f0-9]{20,}$/i.test(cleanGid)) {
    alert("Dit ziet er niet uit als een Gist ID (verwacht een hex-string)."); return;
  }
  const tokenHint = CONFIG.githubToken ? " (leeg laten = ongewijzigd)" : "";
  const token = prompt(
    "GitHub fine-grained token ('Gists: read & write', gescopet tot je gist(en))" +
    tokenHint + ":"
  );
  if (token === null) return;
  const cleanToken = token.trim();
  if (cleanToken.startsWith("ghp_")) {
    const ok = confirm(
      "Dit lijkt een classic PAT (ghp_…). Die geeft toegang tot ÁL jouw gists, " +
      "niet alleen deze. Liever een fine-grained token (github_pat_…) maken.\n\n" +
      "Toch doorgaan?"
    );
    if (!ok) return;
  }
  const artefact = prompt(
    "Artefact-Gist ID (privé dashboard-data — data.json, mowing_data.json, " +
    "vent_data.json/vent_forecast.json/vent_learned.json):",
    CONFIG.artefactGistId || ""
  );
  if (artefact === null) return;
  const cleanArtefact = artefact.trim();
  if (cleanArtefact && !/^[a-f0-9]{20,}$/i.test(cleanArtefact)) {
    alert("Dit ziet er niet uit als een Gist ID."); return;
  }
  if (cleanGid)      { localStorage.setItem("gist_id", cleanGid); CONFIG.gistId = cleanGid; }
  if (cleanToken)    { localStorage.setItem("gh_token", cleanToken); CONFIG.githubToken = cleanToken; }
  if (cleanArtefact) { localStorage.setItem("artefact_gist_id", cleanArtefact); CONFIG.artefactGistId = cleanArtefact; }
  alert("Opgeslagen — de pagina herlaadt.");
  location.reload();
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("account-btn");
  if (btn) btn.addEventListener("click", openAccountSettings);
});

// Cache-bust: de data-JSONs worden door Actions ververst en GitHub Pages
// cachet agressief — altijd een verse timestamp aan de URL (zie CLAUDE.md).
function bust(url) {
  return url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
}

// Geparsede JSON uit de Gist, of fallback als het bestand ontbreekt/leeg is.
// Lege string telt als ontbrekend (zelfde semantiek als gist_io.read_json).
async function gistReadJSON(filename, fallback = null) {
  const content = await gistReadFileContent(filename, null);
  return content ? JSON.parse(content) : fallback;
}

// ── Privé artefact-gist (data.json / mowing_data.json — privatisering aug 2026) ──
// De live bodem-/maai-artefacten bevatten de gedateerde handmatige-actie-logboeken
// en zijn daarom uit de publieke repo gehaald; ze leven in een eigen privé Gist
// (localStorage `artefact_gist_id`, gelezen met het bestaande token). Zolang die
// niet geconfigureerd is valt de lezer terug op het lokale Pages-bestand (dat
// alleen nog bestaat zolang de migratie niet geactiveerd is).
function ensureArtefactConfig() {
  if (CONFIG.artefactGistId) return true;
  if (!CONFIG.githubToken) return false;   // eerst de gewone Gist-config (token)
  const gid = prompt("Plak het Gist ID van de artefact-gist (privé dashboard-data):");
  if (!gid) return false;
  const clean = gid.trim();
  if (!/^[a-f0-9]{20,}$/i.test(clean)) {
    alert("Dit ziet er niet uit als een Gist ID (verwacht een hex-string).");
    return false;
  }
  localStorage.setItem("artefact_gist_id", clean);
  CONFIG.artefactGistId = clean;
  return true;
}

async function artefactReadJSON(filename, fallbackUrl) {
  if (CONFIG.artefactGistId && CONFIG.githubToken) {
    const r = await fetch(`https://api.github.com/gists/${CONFIG.artefactGistId}`,
      { headers: { Authorization: `token ${CONFIG.githubToken}` }, cache: "no-store" });
    if (r.ok) {
      const f = (await r.json()).files?.[filename];
      // Artefacten blijven ruim onder de ~1 MB-truncatiegrens van de Gist-API;
      // mocht dat ooit schuiven, dan is f.truncated het signaal.
      if (f?.content) return JSON.parse(f.content);
    }
    // Gist geconfigureerd maar (tijdelijk) onbereikbaar → probeer het lokale pad.
  }
  const res = await fetch(bust(fallbackUrl));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Content van één bestand uit de Gist (string), of fallback als het ontbreekt.
async function gistReadFileContent(filename, fallback = null) {
  const r = await fetch(`https://api.github.com/gists/${CONFIG.gistId}`,
    { headers: { Authorization: `token ${CONFIG.githubToken}` } });
  if (!r.ok) throw new Error(`Gist fetch: HTTP ${r.status}`);
  const j = await r.json();
  return j.files?.[filename]?.content ?? fallback;
}

async function gistWriteFile(filename, content) {
  const r = await fetch(`https://api.github.com/gists/${CONFIG.gistId}`, {
    method: "PATCH",
    headers: { Authorization: `token ${CONFIG.githubToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ files: { [filename]: { content } } }),
  });
  if (!r.ok) throw new Error(`Gist save: HTTP ${r.status}`);
}

// Bewust géén dispatchWorkflow-helper meer: een browser-getriggerde workflow-run is
// publiek zichtbaar in de Actions-lijst (actor + tijdstip op de minuut) en dateert zo
// elke dashboard-interactie. Alle pijplijnen draaien op hun eigen cadans (bodem/maaien
// uurlijks, tweeling per kwartier), dus een registratie wordt vanzelf opgepikt.
