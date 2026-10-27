// Live post-steps on ONE board root (found by exact name on its page): U+2215 -> "/" in frame names,
// "dashed · …" strokes -> dashed, "hatch line · …" rects rotated 45° about their centre (idempotent via pluginData).
// set_post_export.py fills the placeholders (JSON literals); run it after render, before export.
const PAGE = "__PAGE__",
  ROOT = "__ROOT__";
const DO_HATCH = __HATCH__,
  DO_DASH = __DASH__;
const pg = penpotUtils.getPageByName(PAGE);
if (!pg) return { abort: "page not found", PAGE };
if (!penpot.currentPage || penpot.currentPage.id !== pg.id) await penpot.openPage(pg);
const page = penpot.currentPage;
if (!page || page.id !== pg.id) return { retry: "page" };
const nz = (x) => String(x).replace(/\s*\/\s*/g, "/");
const roots = page.root.children.filter((s) => nz(s.name) === nz(ROOT));
if (roots.length !== 1) return { abort: "roots", n: roots.length, ROOT };
const root = roots[0];
const all = [];
const walk = (s) => {
  all.push(s);
  if (s.children) s.children.forEach(walk);
};
walk(root);
let renamed = 0,
  dashed = 0,
  rotated = 0,
  already = 0;
for (const s of all) {
  if (s.name && s.name.includes("∕")) {
    s.name = s.name.split("∕").join("/");
    renamed++;
  }
  if (DO_DASH && s.name && s.name.startsWith("dashed · ")) {
    s.strokes = (s.strokes || []).map((st) => Object.assign({}, st, { strokeStyle: "dashed" }));
    dashed++;
  }
  if (DO_HATCH && s.type === "rectangle" && s.name && s.name.startsWith("hatch line · ")) {
    if (s.getPluginData("cvRot45") === "1") {
      already++;
      continue;
    }
    s.rotate(45);
    s.setPluginData("cvRot45", "1");
    rotated++;
  }
}
return {
  page: page.id,
  root: root.name,
  w: root.width,
  h: root.height,
  renamed,
  dashed,
  rotated,
  already,
  shapes: all.length,
};
