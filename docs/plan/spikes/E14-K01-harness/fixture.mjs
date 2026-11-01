// THROWAWAY SPIKE HARNESS (E14-K01 #356). The synthetic scene shared by the page and the Node runner:
// a seeded RNG, the drawing fixture, and the harness's own simplified name grammar (a stand-in for D07's
// template engine; the finding compares the two separately).
export const VIEW0 = 50000; // first visible bar of the initial viewport
export const WIDTH = 100; // the viewport is 100 bars wide
export const TICK = 0.5;
export const P0 = 64000;
export const CAP_FOR_FIXTURE = 500;

export function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The tool mix: the 24 non-brush registry tools in four anchor classes (brush is the pointer-only exception).
const mk = (id, name, anchors) => [id, { id, name, anchors }];
export const TOOLS = Object.fromEntries([
  mk("horizontal_line", "Horizontal line", 1),
  mk("vertical_line", "Vertical line", 1),
  mk("text", "Text", 1),
  mk("anchored_vwap", "Anchored VWAP", 1),
  mk("trendline", "Trendline", 2),
  mk("ray", "Ray", 2),
  mk("extended_line", "Extended line", 2),
  mk("rectangle", "Rectangle", 2),
  mk("ellipse", "Ellipse", 2),
  mk("fib_retracement", "Fib retracement", 2),
  mk("fib_timezone", "Fib time zones", 2),
  mk("gann_fan", "Gann fan", 2),
  mk("arrow", "Arrow", 2),
  mk("callout", "Callout", 2),
  mk("measure", "Measure", 2),
  mk("price_range", "Price range", 2),
  mk("date_range", "Date range", 2),
  mk("parallel_channel", "Parallel channel", 3),
  mk("triangle", "Triangle", 3),
  mk("fib_extension", "Fib extension", 3),
  mk("pitchfork", "Pitchfork", 3),
  mk("long_position", "Long position", 3),
  mk("short_position", "Short position", 3),
  mk("polyline", "Polyline", 0), // N anchors
]);
const CLASSES = [
  { w: 0.22, tools: ["horizontal_line", "vertical_line", "text", "anchored_vwap"] },
  {
    w: 0.58,
    tools: [
      "trendline",
      "ray",
      "extended_line",
      "rectangle",
      "ellipse",
      "fib_retracement",
      "fib_timezone",
      "gann_fan",
      "arrow",
      "callout",
      "measure",
      "price_range",
      "date_range",
    ],
  },
  {
    w: 0.15,
    tools: [
      "parallel_channel",
      "triangle",
      "fib_extension",
      "pitchfork",
      "long_position",
      "short_position",
    ],
  },
  { w: 0.05, tools: ["polyline"] },
];
const WORDS = [
  "weekly support",
  "retest",
  "key level",
  "range high",
  "range low",
  "invalidation",
  "target",
];
const TEXTS = ["FOMC", "retest", "entry", "CPI", "unlock"];

export const fmtT = (bar) => {
  const d = new Date((bar + 0) * 60000 + Date.UTC(2026, 0, 1));
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};
export const fmtP = (p) => {
  const s = (Math.round(p * 10) / 10).toFixed(1).replace(/\.0$/, "");
  const [i, f] = s.split(".");
  return i.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (f ? "." + f : "");
};

// One fixture for every strategy: 500 drawings are generated once, and 50 and 200 are prefixes of it.
export function makeFixture(seed, n = CAP_FOR_FIXTURE) {
  const rnd = mulberry32(seed);
  const ri = (a, b) => a + Math.floor(rnd() * (b - a + 1));
  const out = [];
  for (let i = 0; i < n; i += 1) {
    let r = rnd();
    let cls = CLASSES[0];
    for (const c of CLASSES) {
      cls = c;
      if ((r -= c.w) < 0) break;
    }
    const tool = cls.tools[ri(0, cls.tools.length - 1)];
    const def = TOOLS[tool];
    const count = def.anchors || ri(4, 8);
    let t = VIEW0 - 450 + ri(0, 1000);
    let p = P0 + Math.round(((rnd() - 0.5) * 1200) / TICK) * TICK;
    const anchors = [];
    for (let k = 0; k < count; k += 1) {
      anchors.push({ t, p });
      t += ri(3, 40);
      p = Math.round((p + (rnd() - 0.5) * 300) / TICK) * TICK;
    }
    const d = { id: `d${i}`, tool, anchors, locked: i % 20 === 7 };
    if (tool === "text" || tool === "callout") d.text = TEXTS[ri(0, TEXTS.length - 1)];
    if (rnd() < 0.4) d.label = WORDS[ri(0, WORDS.length - 1)];
    out.push(d);
  }
  return out;
}

export function nameOf(d) {
  const T = TOOLS[d.tool];
  const A = d.anchors;
  const pt = (a) => `${fmtT(a.t)} ${fmtP(a.p)}`;
  let core;
  if (d.tool === "horizontal_line") core = `${T.name} ${fmtP(A[0].p)}`;
  else if (d.tool === "vertical_line") core = `${T.name} ${fmtT(A[0].t)}`;
  else if (d.tool === "polyline")
    core = `${T.name} ${fmtT(A[0].t)} → ${fmtT(A[A.length - 1].t)} · ${A.length} points`;
  else if (d.text) core = `${T.name} '${d.text}' ${A.map(pt).join(" → ")}`;
  else core = `${T.name} ${A.map(pt).join(" → ")}`;
  return d.label ? `${core} · ${d.label}` : core;
}
export const anchorName = (d, k) =>
  `${TOOLS[d.tool].name}, anchor ${k + 1} of ${d.anchors.length}, ${fmtT(d.anchors[k].t)} ${fmtP(d.anchors[k].p)}`;

// Time-then-price order (D02:428).
export const keyOf = (d) => [
  Math.min(...d.anchors.map((a) => a.t)),
  Math.min(...d.anchors.map((a) => a.p)),
];
export function sortOrder(ds) {
  return [...ds].sort((x, y) => {
    const a = keyOf(x),
      b = keyOf(y);
    return a[0] - b[0] || a[1] - b[1] || (x.id < y.id ? -1 : 1);
  });
}
