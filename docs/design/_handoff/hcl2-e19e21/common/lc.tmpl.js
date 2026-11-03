const NAME = "__NAME__";
const roots = penpot.currentPage.root.children.filter((s) => s.name === NAME);
if (roots.length !== 1) return { err: "roots " + roots.length };
const root = roots[0];
let count = 0, texts = 0;
const clipped = [];
const T = 0.5;
function walk(s, clips, path) {
  count++;
  if (s.type === "text") {
    texts++;
    for (const c of clips) {
      if (s.x < c.x - T || s.y < c.y - T || s.x + s.width > c.x + c.width + T || s.y + s.height > c.y + c.height + T) {
        clipped.push({ p: path.slice(-90), t: (s.characters || "").slice(0, 50), by: c.name.slice(0, 40),
          dx0: Math.round(c.x - s.x), dy0: Math.round(c.y - s.y),
          dx1: Math.round(s.x + s.width - c.x - c.width), dy1: Math.round(s.y + s.height - c.y - c.height) });
        break;
      }
    }
  }
  const kids = s.children || [];
  const nc = (s.type === "board" && s.clipContent) ? [...clips, s] : clips;
  for (const k of kids) walk(k, nc, path + "/" + k.name);
}
walk(root, [], root.name);
const ann = root.children.find((c) => c.name === "annotations");
const FOOT = ["footer · data statement", "footer · data", "footer · synthetic"];
const foot = root.children.find((c) => FOOT.includes(c.name));
const annEnd = ann ? ann.y + ann.height - root.y : null;
const footEnd = foot ? foot.y + foot.height - root.y : null;
const want = Math.max(annEnd || 0, footEnd || 0) + 80;
const frames = root.children.filter((c) => c.type === "board" && c.name !== "annotations").map((f) => {
  let spill = 0;
  for (const k of (f.children || [])) if (k.x < f.x - T || k.y < f.y - T || k.x + k.width > f.x + f.width + T || k.y + k.height > f.y + f.height + T) spill++;
  return { n: f.name.slice(0, 50), x: f.x - root.x, y: f.y - root.y, w: f.width, h: f.height, clip: f.clipContent, spill };
});
return { id: root.id, x: root.x, y: root.y, w: root.width, h: root.height, count, texts, annEnd, footEnd, want,
  frames, clippedN: clipped.length, clipped: clipped.slice(0, 30) };
