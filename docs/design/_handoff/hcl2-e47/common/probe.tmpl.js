// Theme probe for ONE board (read-only): the active token sets and themes, and the first shape in the root whose fill
// is bound to color.surface.canvas, with its resolved colour. Run it ~90 s after a theme-*.js switch, before export:
// canvas.fill must equal tokenValue of the theme just switched to; when it still shows the old value, wait and probe again.
const NAME = "__NAME__";
const root = penpot.currentPage.root.children.find((s) => s.name === NAME);
if (!root) return { err: "no root" };
let hit = null;
const walk = (s) => {
  if (hit) return;
  const tk = s.tokens || {};
  if (tk.fill === "color.surface.canvas") hit = { n: s.name.slice(0, 40), fill: (s.fills || [])[0] && s.fills[0].fillColor };
  for (const k of s.children || []) walk(k);
};
walk(root);
const cat = penpot.library.local.tokens;
const tok = {};
for (const st of cat.sets.filter((x) => x.active)) {
  const t = st.tokens.find((x) => x.name === "color.surface.canvas");
  if (t) tok[st.name] = t.value;
}
return {
  themes: cat.themes.filter((t) => t.active).map((t) => (t.group || "") + "/" + t.name),
  activeSets: cat.sets.filter((x) => x.active).map((x) => x.name),
  canvas: hit,
  tokenValue: tok,
};
