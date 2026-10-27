// Activate the `high-contrast` token theme of the open file (themes are file-wide); returns the themes, active first.
// Wait 90 s after a switch before exporting: text token binds re-resolve slowly.
const MODE = "high-contrast";
const cat = penpot.library.local.tokens;
const list = () => cat.themes.map((t) => (t.active ? "*" : " ") + (t.group || "") + "/" + t.name);
if (MODE !== "read") {
  const t = cat.themes.find((x) => x.name === MODE);
  if (!t) return { abort: "no theme", themes: list() };
  if (!t.active) t.toggleActive();
}
return { themes: list(), activeSets: cat.sets.filter((s) => s.active).map((s) => s.name) };
