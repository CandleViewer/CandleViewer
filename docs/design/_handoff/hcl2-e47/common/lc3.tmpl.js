// lc3: every text vs every clipping ancestor. A clipper is a scroll viewport when a shape between it and the text is
// larger than it (overflowing content, the md's scrolling regions). Texts lying fully outside some scroll viewport are
// "scrolled away" (by design). Otherwise every clipper that cuts the text (> 0.5 px) is listed.
const NAME = "__NAME__";
const root = penpot.currentPage.root.children.find((s) => s.name === NAME);
if (!root) return { err: "no root" };
const T = 0.5;
const cuts = []; let away = 0, scrollEdge = 0, texts = 0;
const isOut = (s, c) => s.x >= c.x + c.width - T || s.y >= c.y + c.height - T || s.x + s.width <= c.x + T || s.y + s.height <= c.y + T;
const cutBy = (s, c) => s.x < c.x - T || s.y < c.y - T || s.x + s.width > c.x + c.width + T || s.y + s.height > c.y + c.height + T;
function walk(s, anc) {
  if (s.type === "text") {
    texts++;
    const clips = [];
    for (let i = 0; i < anc.length; i++) {
      const c = anc[i];
      if (!(c.type === "board" && c.clipContent)) continue;
      let scroll = false;
      for (let j = i + 1; j < anc.length; j++) if (anc[j].height > c.height + T || anc[j].width > c.width + T) scroll = true;
      clips.push({ c, scroll });
    }
    if (clips.some((k) => k.scroll && isOut(s, k.c))) away++;
    else {
      const bad = clips.filter((k) => cutBy(s, k.c));
      if (bad.length) {
        if (bad.every((k) => k.scroll)) scrollEdge++;
        else cuts.push({ t: (s.characters || "").slice(0, 36), p: anc.slice(2).map((a) => a.name).join("/").slice(-120) + "/" + s.name,
          by: bad.filter((k) => !k.scroll).map((k) => k.c.name.slice(0, 40) + " [" + [Math.round(k.c.x - s.x), Math.round(k.c.y - s.y), Math.round((s.x + s.width - k.c.x - k.c.width) * 10) / 10, Math.round((s.y + s.height - k.c.y - k.c.height) * 10) / 10].join(",") + "]") });
      }
    }
  }
  for (const k of (s.children || [])) walk(k, anc.concat([s]));
}
walk(root, []);
return { texts, away, scrollEdge, cutN: cuts.length, cuts: cuts.slice(0, 40) };
