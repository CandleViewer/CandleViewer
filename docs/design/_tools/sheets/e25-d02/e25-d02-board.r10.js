// E25-D02 board script r10 — the boards lens round-2 fold (B2 + m7), a declared patch of the r9 draw.
// Plugin-context body (penpot, storage in scope). Idempotent: every shape is found by board id, layer name and
// words, and every position is computed from its fieldset, never from its own last position.
// Boards: 10 scr-059-dialog-fieldsets and 11 scr-059-states on the page `E25-D02 Detector wireframes`.
// B2 (`15` CMP-008 / CMP-007 / CMP-040; E30-D04 §2.5 RULED): on a T2 number field the label stays outside the
// well in color.text.secondary and the CMP-019 lock leads the value inside the well (both color.text.tertiary).
// m7 (`15` CMP-008 tokens): every stepper well carries its [−] [+] step buttons, CMP-002 ghost, square at the
// well's height, space.inset.xs (4 px) apart and from the well; on a T2 field they share the field's reason
// (the T2 look, no own lock); at a bound the matching button is plain disabled (opacity.disabled 0.45).
const PAGE_ID = "f52ab5af-ed04-803f-8008-dca7511d82ea";
const BOARDS = [
  ["72481af1-849e-80bc-8008-dcd037183744", "E25-D02 / 10 scr-059-dialog-fieldsets"],
  ["0605c48b-7da1-80e2-8008-dd10bcea663c", "E25-D02 / 11 scr-059-states"],
];
const NS = "cv:e25-d02";
const TAG = "cv:e25-d02:r10";
const P = "E25-D02 / ";
const WELL_DX = 148; // the well's left edge from its fieldset's (was 164)
const KEY_DX = 10; // the label's left edge from its fieldset's
const WELL_W = 56; // a stepper well (was 70); the CMP-003 `mode` well keeps 70
const BTN = 18; // the step button: square at the well's height
const GAP = 4; // space.inset.xs
const RANGE_END = 346; // the range text's right edge from its fieldset's (unchanged)
const OPACITY_DISABLED = 0.45;

const pg = penpot.currentFile.pages.find((p) => p.id === PAGE_ID);
if (!pg) throw new Error("page not found");
await penpot.openPage(pg);
await new Promise((r) => setTimeout(r, 1200));
const page = penpot.currentPage;
const nm = (s) => (s.name || "").replace(P, "");
const meta = (s) => {
  try {
    return JSON.parse(s.getPluginData(NS + ":meta") || "{}");
  } catch (e) {
    return {};
  }
};
const setMeta = (s, m) => {
  s.setPluginData(NS, "v1");
  s.setPluginData(NS + ":meta", JSON.stringify(m));
};
const near = (a, b, d) => Math.abs(a - b) <= d;
const report = [];

for (const [bid, bname] of BOARDS) {
  const b = page.getShapeById(bid);
  if (!b || b.name !== bname) throw new Error("board mismatch " + bid);
  const K = () => b.children;
  // token -> colour on this board (each board is drawn in its own theme)
  const tok = {};
  for (const c of K()) {
    const m = meta(c);
    if (m.tok && c.fills && c.fills[0] && !tok[m.tok]) tok[m.tok] = c.fills[0].fillColor;
    if (m.strokeTok && c.strokes && c.strokes[0] && !tok[m.strokeTok])
      tok[m.strokeTok] = c.strokes[0].strokeColor;
  }
  for (const t of [
    "color.text.secondary",
    "color.text.tertiary",
    "color.surface.hover",
    "color.surface.raised",
    "color.border.default",
  ])
    if (!tok[t]) throw new Error("token colour missing on " + bname + ": " + t);
  // the revision stamp: the subtitle's "script rN", the footer's "· rN" and the board's hpe1ver
  for (const c of K()) {
    if (c.type !== "text") continue;
    if (nm(c) === "board-subtitle" && /script r\d+[a-z]?$/.test(c.characters))
      c.characters = c.characters.replace(/script r\d+[a-z]?$/, "script r10");
    if (nm(c) === "footer" && /· r\d+[a-z]?$/.test(c.characters))
      c.characters = c.characters.replace(/· r\d+[a-z]?$/, "· r10");
  }
  b.setPluginData("hpe1ver", "r10");
  const fill = (s, t) => {
    s.fills = [{ fillColor: tok[t], fillOpacity: 1 }];
  };
  // the step button is drawn as the dialog's × icon button is (board 11's, the same in both themes but colour)
  const tb = page.getShapeById(BOARDS[1][0]).children;
  const tplRect = tb.find((c) => nm(c) === "icon-button");
  const tplText = tb.find((c) => nm(c) === "icon-glyph");
  if (!tplRect || !tplText) throw new Error("templates missing");
  const tagged = (v) => K().find((c) => c.getPluginData(TAG) === v);
  const make = (tpl, v) => {
    let s = tagged(v);
    if (!s) {
      s = tpl.clone();
      b.appendChild(s);
      s.setPluginData(TAG, v);
    }
    return s;
  };

  const wells = K().filter((c) => nm(c) === "field" || nm(c) === "field-invalid");
  for (const w of wells) {
    const fs = K().find(
      (c) =>
        nm(c) === "fieldset" &&
        c.x <= w.x &&
        c.x + c.width >= w.x + w.width &&
        c.y <= w.y &&
        c.y + c.height >= w.y + w.height,
    );
    if (!fs) throw new Error("no fieldset for a well on " + bname);
    const inFs = (c) => c.x >= fs.x - 1 && c.x <= fs.x + fs.width;
    const row = (n) => K().filter((c) => nm(c) === n && near(c.y, w.y + 2, 3) && inFs(c));
    const key = row("field-key").find((c) => c.x < w.x);
    const val = row("field-value").find((c) => c.x >= w.x - 1 && c.x < w.x + w.width);
    const rng = row("field-range").find((c) => c.x > w.x);
    const lock = row("t2-glyph").find((c) => c.x < w.x + w.width);
    const err = K().find(
      (c) => nm(c) === "field-error" && near(c.x, w.x, 1) && near(c.y, w.y + w.height + 2, 3),
    );
    if (!key || !val || !rng)
      throw new Error("incomplete row on " + bname + " at y " + Math.round(w.y - b.y));
    const isMode = key.characters.trim() === "mode";
    const wx = fs.x + WELL_DX;
    w.x = wx;
    if (err) err.x = wx;
    key.x = fs.x + KEY_DX;
    key.resize(WELL_DX - KEY_DX - GAP, key.height);
    if (isMode) {
      w.resize(70, w.height);
      val.x = wx + 4;
      rng.x = wx + 72;
      report.push([
        bname.slice(10, 12),
        Math.round(w.y - b.y),
        "mode",
        "no step buttons (CMP-003)",
      ]);
      continue;
    }
    w.resize(WELL_W, w.height);
    if (lock) {
      // B2: the lock leads the value inside the well; the label back to secondary
      lock.x = wx + 3;
      lock.y = val.y;
      lock.resize(16, lock.height);
      lock.bringToFront(); // r9 drew the lock before the well; inside the well it must sit above it
      val.x = wx + 3 + 16;
      fill(key, "color.text.secondary");
      setMeta(key, { ...meta(key), tok: "color.text.secondary" });
    } else {
      val.x = wx + 4;
    }
    val.resize(wx + WELL_W - 2 - val.x, val.height);
    rng.x = wx + WELL_W + GAP + BTN + GAP + BTN + GAP;
    rng.resize(fs.x + RANGE_END - rng.x, rng.height);
    rng.growType = "auto-height";
    // the bounds from the range text ("2–50 · 3", "≥ 0 · 0.5", "Decimal · —")
    const r = rng.characters.split("·")[0].trim();
    let lo = null;
    let hi = null;
    let m2 = r.match(/^(-?[\d.]+)\s*–\s*(-?[\d.]+)$/);
    if (m2) {
      lo = +m2[1];
      hi = +m2[2];
    } else if ((m2 = r.match(/^≥\s*(-?[\d.]+)$/))) lo = +m2[1];
    const v = +val.characters.replace(/,/g, "");
    const t2 = !!lock;
    const wid = w.id;
    [
      ["minus", "−", 0, lo !== null && !isNaN(v) && v <= lo],
      ["plus", "+", 1, hi !== null && !isNaN(v) && v >= hi],
    ].forEach(([dir, g, i, atBound]) => {
      const bx = wx + WELL_W + GAP + i * (BTN + GAP);
      const rect = make(tplRect, wid + ":" + dir);
      rect.name = P + "step-button";
      rect.x = bx;
      rect.y = w.y;
      rect.resize(BTN, BTN);
      const rt = t2 ? "color.surface.raised" : "color.surface.hover";
      fill(rect, rt);
      rect.strokes = [
        {
          strokeColor: tok["color.border.default"],
          strokeOpacity: 1,
          strokeWidth: 1,
          strokeAlignment: "inner",
          strokeStyle: "solid",
        },
      ];
      setMeta(rect, { role: "wire", tok: rt, strokeTok: "color.border.default", bg: false });
      const txt = make(tplText, wid + ":" + dir + ":glyph");
      txt.name = P + "step-glyph";
      if (txt.characters !== g) txt.characters = g;
      txt.x = bx;
      txt.y = w.y + 1;
      txt.resize(BTN, 16);
      txt.textAlign = "center";
      const gt = t2 ? "color.text.tertiary" : "color.text.secondary";
      fill(txt, gt);
      setMeta(txt, { role: "text", tok: gt });
      const op = !t2 && atBound ? OPACITY_DISABLED : 1;
      rect.opacity = op;
      txt.opacity = op;
      if (op < 1)
        report.push([
          bname.slice(10, 12),
          Math.round(w.y - b.y),
          key.characters,
          dir + " at bound",
        ]);
    });
  }
}
await new Promise((r) => setTimeout(r, 1500));
return { ok: true, version: "r10", notes: report };
