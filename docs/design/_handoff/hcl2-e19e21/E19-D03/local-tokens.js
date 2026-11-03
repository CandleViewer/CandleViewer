// E19-D03 only: create the three LOCAL token sets of local-tokens.json (the PROPOSED color.tpo.letter and
// color.tpo.initialbalance rows, spec §2.1) and add each set to its own theme only, after the theme's repo sets.
// Run it after the repo's `themes` emit and before run/theme-dark.js. Idempotent: existing sets, rows and theme
// links are kept. The rows mirror local-tokens.json; that file and this one change together.
const T = penpot.library.local.tokens;
const ROWS = [
  ["E19-D03 local · dark", "color.tpo.letter", "color", "{palette.neutral.700}"],
  ["E19-D03 local · light", "color.tpo.letter", "color", "{palette.light.neutral.700}"],
  ["E19-D03 local · hc", "color.tpo.letter", "color", "{palette.neutral.700}"],
  ["E19-D03 local · dark", "color.tpo.initialbalance", "color", "{palette.cyan.400}"],
  ["E19-D03 local · light", "color.tpo.initialbalance", "color", "{palette.light.cyan.300}"],
  ["E19-D03 local · hc", "color.tpo.initialbalance", "color", "{palette.cyan.400}"],
];
const THEME_OF = {
  "E19-D03 local · dark": "dark",
  "E19-D03 local · light": "light",
  "E19-D03 local · hc": "high-contrast",
};
let added = 0, kept = 0;
const errs = [];
for (const [setName, name, type, value] of ROWS) {
  let set = T.sets.find((s) => s.name === setName);
  if (!set) set = T.addSet({ name: setName });
  if (set.tokens.some((t) => t.name === name)) { kept++; continue; }
  try { set.addToken({ type, name, value }); added++; } catch (e) { errs.push(name + ": " + String(e.message || e).slice(0, 80)); }
}
const themes = [];
for (const [setName, themeName] of Object.entries(THEME_OF)) {
  const th = T.themes.find((t) => t.group === "theme" && t.name === themeName);
  const set = T.sets.find((s) => s.name === setName);
  if (!th || !set) { errs.push("missing " + (th ? "set " + setName : "theme " + themeName)); continue; }
  if (!th.activeSets.some((s) => s.name === setName)) th.addSet(set);
  themes.push(themeName + ":" + th.activeSets.map((s) => s.name).join("+"));
}
return { added, kept, themes, errors: errs.slice(0, 8), nerr: errs.length };
