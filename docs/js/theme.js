// =======================================================================
// THEME  — gedeeld kleurenpalet voor alle dashboards (één bron)
// Geladen vóór het pagina-script; definieert de globale `COLORS`.
// (camping.html heeft bewust z'n eigen posterthema en laadt dit niet.)
// =======================================================================

const COLORS = {
  parchment: "#f3ecd9", parchmentDeep: "#e8dec3",
  ink: "#2a241b", inkSoft: "#5c4f3c",
  moss: "#3d5a3a", mossLight: "#6b8562",
  clay: "#b8532a", sand: "#c9a978",
  rain: "#4a6b8a", sun: "#d4a017",
  dry: "#a0421a", wet: "#2d4a5c",
};

// HTML-escape voor alles wat niet-numeriek in een innerHTML-template landt
// (labels uit artefacten, foutteksten, Gist-waarden). De token-pagina's houden
// een Gist-token in localStorage; een onge-escapete waarde is daar een
// persistente injectie zodra iemand ooit schrijftoegang tot de gist had.
function escHTML(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
