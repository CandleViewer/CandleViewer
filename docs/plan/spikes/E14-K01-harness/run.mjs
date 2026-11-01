// THROWAWAY SPIKE HARNESS (E14-K01 #356). Node driver: serves this folder on 127.0.0.1, drives headless Chromium
// through Playwright (the one apps/web already has), reads Chromium's accessibility tree through the DevTools
// Accessibility domain, and writes ../E14-K01-results.json. No network, no new dependency.
// Run from apps/web:  node ../../docs/plan/spikes/E14-K01-harness/run.mjs [--smoke] [--seed 356] [--at-n 40] [--frames 400]
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { cpus, loadavg, release, totalmem } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
  makeFixture,
  sortOrder,
  nameOf,
  fmtT,
  fmtP,
  mulberry32,
  VIEW0,
  WIDTH,
  P0,
  TICK,
} from "./fixture.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const { values: a } = parseArgs({
  options: {
    seed: { type: "string", default: "356" },
    "at-n": { type: "string", default: "40" },
    frames: { type: "string", default: "400" },
    "session-s": { type: "string", default: "60" },
    out: { type: "string", default: resolve(here, "..") },
    chromium: { type: "string", default: "" }, // path to a Chromium or headless-shell binary when the browser build on the host differs from Playwright's pin
    smoke: { type: "boolean", default: false },
  },
});
const SEED = Number(a.seed);
const AT_N = a.smoke ? 3 : Number(a["at-n"]);
const FRAMES = a.smoke ? 40 : Number(a.frames);
const WARM = a.smoke ? 5 : 30;
const SESSION_S = a.smoke ? 6 : Number(a["session-s"]);
const SIZES = [50, 200, 500];
const SWEEP = a.smoke ? [50, 200] : [25, 50, 100, 150, 200, 300, 400, 500];
// The gates and the decision rule, fixed before the run (BQ-06; T AC3). Edit here, not in the page.
const GATE_AT_MS = 100,
  GATE_DRAG_MS = 2,
  FRAME_BUDGET_MS = 1000 / 58;
const TIEBREAK_PER_DRAWING_NODES = true; // BQ-06 (ruled): among survivors prefer the strategy that gives every drawing its own AT node
const ADOPT_CAP_MAX = 200; // BQ-07: a measured cap above 200 is adopted as 200

const { chromium } = createRequire(join(process.cwd(), "package.json"))("@playwright/test");
const pwVersion = createRequire(join(process.cwd(), "package.json"))(
  "@playwright/test/package.json",
).version;

// the served files are read once here, from fixed names; a request only selects one of them
const files = Object.fromEntries(
  [
    ["page.html", "text/html"],
    ["harness.mjs", "text/javascript"],
    ["fixture.mjs", "text/javascript"],
  ].map(([name, type]) => [`/${name}`, { type, body: readFileSync(join(here, name)) }]),
);
const server = createServer((req, res) => {
  const p = (req.url || "/").split("?")[0];
  const file = files[p];
  if (!file) {
    res.writeHead(404).end();
    return;
  }
  // cross-origin isolation gives performance.now() 5 microsecond resolution instead of 100
  res
    .writeHead(200, {
      "content-type": file.type,
      "cross-origin-opener-policy": "same-origin",
      "cross-origin-embedder-policy": "require-corp",
    })
    .end(file.body);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(a.chromium ? { executablePath: a.chromium } : {});
const chromiumVersion = browser.version();

// nearest-rank percentile with a floor: at small n the "p95" is the maximum
const pct = (xs, p) => {
  const s = [...xs].sort((x, y) => x - y);
  return s.length ? s[Math.min(s.length - 1, Math.max(0, Math.ceil(p * s.length) - 1))] : null;
};
const st = (xs) => ({
  n: xs.length,
  min: pct(xs, 0),
  p50: pct(xs, 0.5),
  p95: pct(xs, 0.95),
  max: pct(xs, 1),
  mean: xs.reduce((x, y) => x + y, 0) / (xs.length || 1),
});
const f = (x, d = 2) => (x === null || x === undefined ? "n/a" : x.toFixed(d));
const pointer = { n: 0, by: {}, pages: 0 };

async function open(s, n, extra = "") {
  const page = await browser.newPage({ viewport: { width: 1600, height: 760 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${origin}/page.html?s=${s}&n=${n}&seed=${SEED}${extra}`);
  await page.waitForFunction(() => window.ready === true);
  page.errors = errors;
  return page;
}
async function close(page) {
  const p = await page.evaluate(() => window.__h.ptr());
  pointer.n += p.n;
  pointer.pages += 1;
  pointer.keyboardClicks = (pointer.keyboardClicks || 0) + p.kbClicks;
  pointer.keyboardClickTargets = [...(pointer.keyboardClickTargets || []), ...p.kbTargets];
  for (const [k, v] of Object.entries(p.by)) pointer.by[k] = (pointer.by[k] || 0) + v;
  await page.close();
}
const raf2 = (page) =>
  page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));

async function atSamples(page, cdp, n) {
  const ms = [];
  let ax = 0,
    roles = {};
  for (let i = 0; i < n; i += 1) {
    await page.evaluate(() => window.__h.rebuild());
    await raf2(page);
    const t0 = performance.now();
    await cdp.send("Accessibility.enable");
    const { nodes } = await cdp.send("Accessibility.getFullAXTree");
    ms.push(performance.now() - t0);
    await cdp.send("Accessibility.disable");
    if (i === n - 1) {
      ax = nodes.length;
      roles = {};
      for (const nd of nodes) {
        const r = nd.role && nd.role.value;
        if (r) roles[r] = (roles[r] || 0) + 1;
      }
    }
  }
  return { ms, ax, roles };
}

async function runCell(s, n, k = 0) {
  const la0 = loadavg()[0];
  const page = await open(s, n, k ? `&k=${k}` : "");
  const cdp = await page.context().newCDPSession(page);
  await page.evaluate(() => window.__h.rebuild());
  const nodes = await page.evaluate(() => window.__h.count());
  const at = await atSamples(page, cdp, AT_N);
  await page.evaluate(() => window.__h.rebuild());
  await cdp.send("Accessibility.enable"); // AT attached: the conservative drag condition
  const dAt = await page.evaluate((o) => window.__h.drag(o), { frames: FRAMES, warm: WARM });
  await cdp.send("Accessibility.disable");
  await page.evaluate(() => window.__h.rebuild());
  const dNo = await page.evaluate((o) => window.__h.drag(o), { frames: FRAMES, warm: WARM });
  const cell = {
    strategy: s,
    n,
    k: k || null,
    nodes,
    axNodes: at.ax,
    axRoles: at.roles,
    at: st(at.ms),
    drag: st(dAt.rec),
    dragNoAt: st(dNo.rec),
    query: st(dAt.query),
    window: st(dAt.win),
    frame: {
      atAttachedMs: st(dAt.ints),
      noAtMs: st(dNo.ints),
      overBudgetPctAtAttached: +(
        (100 * dAt.ints.filter((x) => x > FRAME_BUDGET_MS).length) /
        (dAt.ints.length || 1)
      ).toFixed(1),
      overBudgetPctNoAt: +(
        (100 * dNo.ints.filter((x) => x > FRAME_BUDGET_MS).length) /
        (dNo.ints.length || 1)
      ).toFixed(1),
    },
    loadavgBefore: la0,
    loadavgAfter: loadavg()[0],
    pageErrors: page.errors,
  };
  await close(page);
  return cell;
}

// ---- keyboard-only script (T AC2 actions, one flow per anchor class), per strategy ------------------------------
async function runScript(s) {
  const page = await open(s, 50);
  const log = [];
  const check = (name, ok, detail = "") => {
    log.push({ name, ok: !!ok, detail: ok ? "" : String(detail) });
  };
  const K = (k) => page.keyboard.press(k);
  const info = () => page.evaluate(() => window.__h.focusInfo());
  const snap = () => page.evaluate(() => window.__h.snapshot());
  // the announcer serialises confirmations 500 ms apart, so a step is checked as "queued" and the whole queue is checked at the end
  const said = async (re) =>
    (await page.evaluate(() => window.__h.annState())).enq.some((t) => re.test(t));
  const rep = async (k, n) => {
    for (let i = 0; i < n; i += 1) await K(k);
  };
  const base = makeFixture(SEED).slice(0, 50);
  const rankOf = (extra, id) => sortOrder([...base, ...extra]).findIndex((d) => d.id === id) + 1;
  const extra = [];
  const pt = (t, p) => `${fmtT(t)} ${fmtP(p)}`;
  const expectObj = async (name, prefix, count, id) => {
    const i = await info(),
      sn = await snap();
    const pos = i.id && id ? rankOf(extra, id) : -1;
    check(`${name}: focus on the object surrogate`, i.kind === "obj", JSON.stringify(i));
    check(
      `${name}: aria-label`,
      typeof i.label === "string" &&
        i.label.startsWith(prefix) &&
        i.label.endsWith(`, item ${pos} of ${count}`),
      `${i.label} | want ${prefix} ... item ${pos} of ${count}`,
    );
    check(`${name}: setsize`, i.size === count && sn.count === count, `${i.size}/${sn.count}`);
    return i;
  };
  const c0 = VIEW0 + WIDTH / 2,
    p0 = Math.round(P0 / TICK) * TICK;

  await K("Tab");
  await K("Tab");
  check(
    "Tab twice: focus on the plot stop",
    (await info()).kind === "chart",
    JSON.stringify(await info()),
  );
  // 1 create a trendline
  await K("Alt+KeyL");
  check("arm trendline (Alt+L)", (await snap()).tool === "trendline");
  check("arm announced", await said(/Trendline tool on\./));
  await rep("ArrowRight", 3);
  await rep("ArrowUp", 2);
  await K("Enter");
  const A1 = { t: c0 + 3, p: p0 + 1 };
  check("anchor 1 announced", await said(new RegExp(`Anchor 1 of 2 at ${pt(A1.t, A1.p)}`)));
  await K("Shift+ArrowRight");
  await K("Shift+ArrowDown");
  await K("Enter");
  const A2 = { t: c0 + 13, p: p0 + 1 - 5 };
  extra.push({ id: "n1", tool: "trendline", anchors: [A1, A2], locked: false });
  const nm = (d) => nameOf(d);
  let i = await expectObj("create trendline", nm(extra[0]), 51, "n1");
  check("create announced", await said(/Trendline created\. Selected\./));
  // 2 nudge the whole drawing
  await rep("ArrowUp", 2);
  await K("Shift+ArrowRight");
  const B1 = { t: A1.t + 10, p: A1.p + 1 },
    B2 = { t: A2.t + 10, p: A2.p + 1 };
  extra[0] = { ...extra[0], anchors: [B1, B2] };
  await expectObj("nudge object", nm(extra[0]), 51, "n1");
  // 3 nudge one anchor
  await K("PageDown");
  i = await info();
  check(
    "PageDown: anchor surrogate",
    i.kind === "anchor" && i.label === `Trendline, anchor 1 of 2, ${pt(B1.t, B1.p)}`,
    JSON.stringify(i),
  );
  await K("ArrowDown");
  i = await info();
  check(
    "nudge anchor 1 by one tick",
    i.label === `Trendline, anchor 1 of 2, ${pt(B1.t, B1.p - TICK)}`,
    i.label,
  );
  extra[0] = { ...extra[0], anchors: [{ t: B1.t, p: B1.p - TICK }, B2] };
  // 4 leave and re-enter the handles stop
  await K("Escape");
  check("Esc: back to the plot stop", (await info()).kind === "chart");
  await K("Tab");
  i = await info();
  check("Tab: into the handles stop", i.kind === "anchor" || i.kind === "obj", JSON.stringify(i));
  check("one Tab stop for the set", (await page.evaluate(() => window.__h.tabStops())) === 1);
  // 5 delete and undo
  await K("PageUp");
  await K("Delete");
  const sn = await snap();
  check("delete: the drawing is gone", sn.count === 50, sn.count);
  check(
    "delete: focus on a surrogate or the plot stop",
    ["obj", "chart"].includes((await info()).kind),
    JSON.stringify(await info()),
  );
  check("delete announced", await said(/removed\. Undo available\./));
  await K("Control+z");
  await expectObj("undo", nm(extra[0]), 51, "n1");
  check("undo announced", await said(/Undone\./));
  // 6 one-anchor class
  await K("Escape");
  await K("Alt+KeyH");
  await K("Enter");
  const cur = { t: c0 + 13, p: p0 - 4 };
  extra.push({ id: "n2", tool: "horizontal_line", anchors: [cur], locked: false });
  await expectObj("one-anchor (horizontal line)", nm(extra[1]), 52, "n2");
  // 7 three-anchor class (the Alt+C key is harness-only, not a proposal)
  await K("Alt+KeyC");
  await K("Enter");
  await rep("ArrowRight", 5);
  await rep("ArrowUp", 4);
  await K("Enter");
  await rep("ArrowRight", 5);
  await rep("ArrowDown", 2);
  await K("Enter");
  extra.push({
    id: "n3",
    tool: "parallel_channel",
    anchors: [
      { t: cur.t, p: cur.p },
      { t: cur.t + 5, p: cur.p + 2 },
      { t: cur.t + 10, p: cur.p + 1 },
    ],
    locked: false,
  });
  await expectObj("three-anchor (parallel channel)", nm(extra[2]), 53, "n3");
  // 8 N-anchor class: Enter per anchor; the closing key Shift+Enter is harness-only, not a proposal
  const q = { t: cur.t + 10, p: cur.p + 1 };
  await K("Alt+KeyP");
  await K("Enter");
  await rep("ArrowRight", 4);
  await K("Enter");
  await rep("ArrowRight", 4);
  await rep("ArrowUp", 2);
  await K("Enter");
  await rep("ArrowRight", 4);
  await K("Enter");
  await K("Shift+Enter");
  extra.push({
    id: "n4",
    tool: "polyline",
    anchors: [q, { t: q.t + 4, p: q.p }, { t: q.t + 8, p: q.p + 1 }, { t: q.t + 12, p: q.p + 1 }],
    locked: false,
  });
  await expectObj("N-anchor (polyline)", nm(extra[3]), 54, "n4");
  // 9 cancel ladder
  await K("Escape");
  await K("Alt+KeyL");
  await K("Enter");
  await K("Escape");
  check("Esc drops the pending anchor, the tool stays armed", (await snap()).tool === "trendline");
  await K("Escape");
  check("Esc again disarms", (await snap()).tool === null && (await snap()).count === 54);
  check("cancel announced", await said(/tool off\./));
  // 10 locked drawing refuses the edit keys
  await K("Tab");
  const lockedId = await page.evaluate(() => window.__h.lockedId());
  const flat = await page.evaluate(() => window.__h.flat());
  await K("Home");
  await rep("PageDown", flat.indexOf(`${lockedId}:-1`));
  i = await info();
  check(
    "reached the locked drawing by keys",
    i.id === lockedId && /, locked$/.test(i.label),
    JSON.stringify(i),
  );
  const before = JSON.stringify(
    (await page.evaluate((id) => window.__h.model(id), lockedId)).anchors,
  );
  await K("ArrowUp");
  await K("Delete");
  const after = JSON.stringify(
    (await page.evaluate((id) => window.__h.model(id), lockedId)).anchors,
  );
  check("locked: edit keys change nothing", before === after && (await snap()).count === 54);
  check("locked refusal announced", await said(/This drawing is locked\./));
  await page.waitForFunction(() => window.__h.annState().pending === 0, null, { timeout: 60000 });
  await page.waitForTimeout(700);
  const stt = await page.evaluate(() => window.__h.annState());
  check(
    "every queued confirmation was written, in order, none dropped",
    JSON.stringify(stt.enq) === JSON.stringify(stt.written),
    `${stt.enq.length} queued, ${stt.written.length} written`,
  );
  const ptrN = (await page.evaluate(() => window.__h.ptr())).n;
  const ok = log.filter((x) => x.ok).length;
  await close(page);
  return {
    strategy: s,
    steps: log.length,
    passed: ok,
    failed: log.filter((x) => !x.ok),
    pointerEvents: ptrN,
    pageErrors: page.errors,
  };
}

// ---- reachability, Tab order, window shifts ---------------------------------------------------------------------
async function runReach(s) {
  const page = await open(s, 500);
  const K = (k) => page.keyboard.press(k);
  await K("Tab");
  await K("Tab");
  await K("Tab"); // before -> chart -> the set
  const flat = await page.evaluate(() => window.__h.flat());
  await K("Home");
  await page.evaluate(() => window.__h.trailOn(true));
  const t0 = performance.now();
  for (let i = 1; i < flat.length; i += 1) await K("PageDown");
  const trail = await page.evaluate(() => window.__h.trail());
  const walkMs = performance.now() - t0;
  const got = trail.map((x) => `${x.id}:${x.anchor}`);
  const want = flat.slice(1);
  const mism = got.findIndex((x, i) => x !== want[i]);
  const ids = new Set(trail.map((x) => x.id));
  ids.add(flat[0].split(":")[0]);
  await K("End");
  const end = await page.evaluate(() => window.__h.focusInfo());
  const out = {
    strategy: s,
    presses: flat.length - 1,
    flatItems: flat.length,
    reachedDrawings: ids.size,
    of: 500,
    sequenceMatches: mism === -1 && got.length === want.length,
    firstMismatch: mism,
    endKeyLands: `${end.id}:${end.anchor}` === flat[flat.length - 1],
    walkMs: Math.round(walkMs),
  };
  out.all = out.reachedDrawings === 500 && out.sequenceMatches && out.endKeyLands;
  await close(page);
  return out;
}
async function runOrder(s) {
  const page = await open(s, 200);
  const K = (k) => page.keyboard.press(k);
  const id = () =>
    page.evaluate(() => {
      const a = document.activeElement;
      return a.id || (a.dataset && a.dataset.kind ? "set" : a.tagName.toLowerCase());
    });
  const seq = [];
  await K("Tab");
  seq.push(await id());
  await K("Tab");
  seq.push(await id());
  await K("Tab");
  seq.push(await id());
  await K("Tab");
  seq.push(await id());
  const back = [];
  await K("Shift+Tab");
  back.push(await id());
  await K("Shift+Tab");
  back.push(await id());
  const stops = await page.evaluate(() => window.__h.tabStops());
  await close(page);
  return {
    strategy: s,
    forward: seq,
    backward: back,
    tabStopsInSet: stops,
    pass:
      seq[0] === "before" &&
      seq[1] === "chart" &&
      (seq[2] === "set" || seq[2] === "host") &&
      seq[3] === "next" &&
      stops === 1 &&
      back[0] === seq[2] &&
      back[1] === "chart",
  };
}
async function runPan(s) {
  const page = await open(s, 200);
  const K = (k) => page.keyboard.press(k);
  await K("Tab");
  await K("Tab");
  await K("Tab");
  for (let i = 0; i < 40; i += 1) await K("PageDown");
  const r = await page.evaluate(() => window.__h.panTest());
  const ok = r.steps.every((x) => x.sameElement && x.stillMirrored && x.posinsetKept);
  await close(page);
  return { strategy: s, ...r, pass: ok };
}

// ---- the sink, the 24 px target, the obscured check, the live-region session ------------------------------------
const SINK_LABELS = [
  "<b>bold</b>",
  '<img src=x onerror="window.__k01=1">',
  '" onmouseover="window.__k01=1" x="',
  "<script>window.__k01=1</script>",
  "A".repeat(5000),
  "left‮right",
  "javascript:window.__k01=1",
  "&lt;i&gt; &amp; </div><div>",
];
async function runSink(s) {
  const page = await open(s, 50);
  const r = await page.evaluate((l) => window.__h.sinkTest(l), SINK_LABELS);
  await close(page);
  return {
    strategy: s,
    cases: r.results.length,
    passed: r.results.filter((x) => x.ok).length,
    handlerFired: r.handlerFired,
    results: r.results,
  };
}
async function runGeometry() {
  const out = {};
  for (const s of ["a", "c"]) {
    const page = await open(s, 200);
    out[s] = await page.evaluate(() => window.__h.targets());
    if (s === "c") out.obscured = await page.evaluate(() => window.__h.obscured());
    await close(page);
  }
  return out;
}
async function runSession() {
  const page = await open("c", 50);
  await page.evaluate(
    ([ms, seed]) => window.__h.runSession(ms, seed),
    [SESSION_S * 1000, SEED + 7],
  );
  const r = await page.evaluate(() => window.__h.annReport());
  await close(page);
  return { sessionSeconds: SESSION_S, ...r };
}

// ---- run -----------------------------------------------------------------------------------------------------------
const startedAt = new Date().toISOString();
const la0 = loadavg().map((x) => +x.toFixed(2));
const rng = mulberry32(SEED);
const grid = [];
for (const s of ["a", "b", "c"]) for (const n of SIZES) grid.push([s, n]);
for (let i = grid.length - 1; i > 0; i -= 1) {
  const j = Math.floor(rng() * (i + 1));
  [grid[i], grid[j]] = [grid[j], grid[i]];
}
const cells = [];
for (const [s, n] of grid) {
  cells.push(await runCell(s, n));
  console.log("cell", s, n);
}
const baseline = await runCell("none", 500);
console.log("baseline");
const sweep = [];
for (const k of SWEEP) {
  sweep.push(await runCell("c", 500, k));
  console.log("sweep", k);
}
const reach = {},
  order = {},
  pan = {},
  script = {},
  sink = {};
for (const s of ["a", "b", "c"]) {
  reach[s] = await runReach(s);
  console.log("reach", s);
}
for (const s of ["a", "b", "c"]) {
  order[s] = await runOrder(s);
  pan[s] = await runPan(s);
}
for (const s of ["a", "b", "c"]) {
  script[s] = await runScript(s);
  console.log("script", s, script[s].passed, "/", script[s].steps);
}
for (const s of ["a", "b", "c"]) sink[s] = await runSink(s);
const geometry = await runGeometry();
const session = await runSession();
console.log("session");
const laEnd = loadavg().map((x) => +x.toFixed(2));

// ---- decision (the rule written before the run: BQ-06 / BQ-07) -------------------------------------------------
const cell = (s, n) => cells.find((c) => c.strategy === s && c.n === n);
const gate = (c) => c.at.p95 <= GATE_AT_MS && c.drag.p95 <= GATE_DRAG_MS;
const verdictOf = (c) =>
  `${c.at.p95 <= GATE_AT_MS ? "AT ok" : "AT over"}, ${c.drag.p95 <= GATE_DRAG_MS ? "drag ok" : "drag over"}`;
const survivors = ["a", "b", "c"].filter((s) => gate(cell(s, 500)));
const reachable = survivors.filter((s) => reach[s].all);
const nodesPerDrawing = { a: true, b: false, c: true };
let pool = reachable;
if (TIEBREAK_PER_DRAWING_NODES && pool.some((s) => nodesPerDrawing[s]))
  pool = pool.filter((s) => nodesPerDrawing[s]);
pool.sort((x, y) => cell(x, 500).at.p95 - cell(y, 500).at.p95);
const NAMES = {
  a: "(a) one surrogate per drawing",
  b: "(b) one application host with a grid summary",
  c: "(c) visible, selected and focused drawings only",
};
const rec = pool[0] || "c";
const fellBack = !pool.length;
let cap = 0;
for (const c of sweep.slice().sort((x, y) => x.k - y.k)) {
  if (c.at.p95 <= GATE_AT_MS && c.drag.p95 <= GATE_DRAG_MS) cap = c.k;
  else break;
}
const capAdopted = Math.min(cap, ADOPT_CAP_MAX);
const rovingOk = reach.c.all && order.c.pass && pan.c.pass;
const activeOk = reach.b.all && order.b.pass && pan.b.pass;

const fixtureHash = createHash("sha256")
  .update(JSON.stringify(makeFixture(SEED)))
  .digest("hex");
const staticScan =
  /innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser|createContextualFragment|srcdoc/.test(
    readFileSync(join(here, "harness.mjs"), "utf8"),
  )
    ? "html setter found"
    : "0 HTML setters in harness.mjs";
const cpu = cpus();
const host = `${cpu[0].model.trim()}, ${cpu.length} logical CPUs, ${(totalmem() / 2 ** 30).toFixed(0)} GB, kernel ${release()}, Node ${process.version}; load average 1/5/15 min at the start ${la0.join("/")}, at the end ${laEnd.join("/")}; other agents' jobs share this machine`;
const sw = session;
const win = (n) => cell("c", n).window;

const M = {};
for (const c of cells) {
  const p = `${c.strategy}_${c.n}`;
  M[`${p}_nodes`] = String(c.nodes);
  M[`${p}_at_p50`] = f(c.at.p50);
  M[`${p}_at_p95`] = f(c.at.p95);
  M[`${p}_drag_p50`] = f(c.drag.p50, 3);
  M[`${p}_drag_p95`] = f(c.drag.p95, 3);
}
M.chromium_version = `${chromiumVersion} (Playwright ${pwVersion}, headless)`;
M.host_description = `(${host})`;
M.run_order =
  `in a seeded shuffled order, ${grid.map(([s, n]) => `${s}-${n}`).join(", ")}; then the load-only baseline, then the cap sweep ascending (K = ${SWEEP.join(", ")}), then the key scripts, the sink and the 60 s session`.replace(
    "60 s",
    `${SESSION_S} s`,
  );
M.n_samples = `${AT_N} AT-tree builds and ${FRAMES} drag frames (after ${WARM} warm-up frames, dropped)`;
M.seed = String(SEED);
M.fixture_hash = `Fixture sha256 ${fixtureHash} (JSON of the 500 drawings; 50 and 200 are prefixes of it).`;
M.fps_note = `${(() => {
  const w = Math.max(...cells.map((c) => c.frame.overBudgetPctAtAttached));
  const bl = baseline.frame.atAttachedMs.p50;
  return `was measured in headless Chromium's rAF (software rendering, canvas 2D, not the engine): the load-only baseline frame interval is p50 ${f(bl, 1)} ms (${f(1000 / bl, 1)} fps); across the nine cells the worst share of frames over ${f(FRAME_BUDGET_MS, 1)} ms (58 fps) with a tree attached is ${w}%, against the baseline's ${baseline.frame.overBudgetPctAtAttached}%; a contended host, so a miss is inconclusive`;
})()}`;
for (const s of ["a", "b", "c"])
  M[`reachability_${s}`] =
    `${reach[s].reachedDrawings} of ${reach[s].of} drawings reached by PageDown (${reach[s].presses} presses, the sequence ${reach[s].sequenceMatches ? "matches" : "differs from"} the time-then-price order, End lands on the last item: ${reach[s].endKeyLands})`;
M.table_reading =
  ["a", "b", "c"]
    .map((s) => {
      const c5 = cell(s, 500),
        c1 = cell(s, 50);
      return `(${s}) at 500: ${c5.nodes} nodes (${c1.nodes} at 50), ${c5.axNodes} AT nodes, AT build p50 ${f(c5.at.p50)} / p95 ${f(c5.at.p95)} ms, drag p50 ${f(c5.drag.p50, 3)} / p95 ${f(c5.drag.p95, 3)} ms (without a tree attached p50 ${f(c5.dragNoAt.p50, 3)}); the window query is p50 ${f(c5.query.p50, 3)} ms of that; ${verdictOf(c5)}.`;
    })
    .join(" ") +
  ` Empty-mirror floor (the CDP round trip plus the page's own tree): ${f(baseline.at.p50)} ms p50, ${baseline.axNodes} AT nodes.`;
M.recommended_strategy = NAMES[rec];
const costOf = (s) =>
  `${cell(s, 500).nodes} nodes, AT p95 ${f(cell(s, 500).at.p95)} ms, drag p95 ${f(cell(s, 500).drag.p95, 3)} ms`;
const tieLosers = reachable.filter((s) => !nodesPerDrawing[s]);
M.recommendation_reason = fellBack
  ? `no strategy met the gates and kept every drawing reachable on this host, so (c) is adopted by BQ-06's timebox default and the residual risk is written on E14-S08; survivors ${survivors.join(", ") || "none"}`
  : `${survivors.length === 3 ? "all three meet both gates at 500 on this host" : `survivors of the gates at 500: ${survivors.map((s) => `(${s})`).join(", ")}`}; reachable by keys alone at 500: ${reachable.map((s) => `(${s})`).join(", ")}; ${
      TIEBREAK_PER_DRAWING_NODES && tieLosers.length
        ? `the gates do not separate them, so the tie-break decides, and it is accessibility, not cost (BQ-06): the strategy that gives each drawing its own named, focusable node (setsize and posinset, pressed state) wins; ${tieLosers.map((s) => `(${s})`).join(", ")} gives 0 per-drawing nodes and nests a second application role, so it loses although it is cheaper at 500 (${tieLosers.map((s) => `(${s}) ${costOf(s)}`).join("; ")}; (${rec}) ${costOf(rec)})${pool.length > 1 ? "; among the rest, the lower AT-tree p95 at 500" : ""}`
        : `the lower AT-tree p95 at 500: (${rec}) ${costOf(rec)}`
    }`;
M.focus_model =
  rovingOk && activeOk
    ? "roving tabindex (both models pass the four checks here, so the D02 default stands)"
    : rovingOk
      ? "roving tabindex (active-descendant fails a check here)"
      : activeOk
        ? "active-descendant (roving tabindex fails a check here)"
        : "neither model passes all checks here";
M.window_cap = cap
  ? cap > ADOPT_CAP_MAX
    ? `${ADOPT_CAP_MAX} (measured ${cap}, capped for symmetry with E06-D03)`
    : String(cap)
  : "not met at any swept K";
M.window_cap_basis = `sweep of a capped window of K drawings in the 500-case, K = ${SWEEP.join(", ")}; largest K whose AT p95 <= ${GATE_AT_MS} ms and drag p95 <= ${GATE_DRAG_MS} ms with a tree attached: ${cap}; ${sweep.map((c) => `K=${c.k}: ${c.nodes} nodes, AT p95 ${f(c.at.p95)}, drag p95 ${f(c.drag.p95, 3)}`).join("; ")}; n = ${AT_N} builds and ${FRAMES} frames per K; headless Chromium on a contended host`;
M.window_default = `the rule's natural window in this fixture: p50 ${f(win(500).p50, 0)} of 500 drawings (min ${f(win(500).min, 0)}..max ${f(win(500).max, 0)}), p50 ${f(win(200).p50, 0)} of 200, p50 ${f(win(50).p50, 0)} of 50 over the drag path; E06-D03's 60 rows is a precedent for bars, and this run states no fixed default for drawings`;
M.pointer_events = String(pointer.n);
const isolated = await (async () => {
  const pg = await open("none", 0);
  const v = await pg.evaluate(() => window.crossOriginIsolated);
  await close(pg);
  return v;
})();
M.script_result =
  ["a", "b", "c"]
    .map((s) => `(${s}) ${script[s].passed} of ${script[s].steps} assertions passed`)
    .join(", ") +
  `; pointer, mouse, touch and wheel events ${pointer.n} (keyboard activation of a button, click with detail 0: ${pointer.keyboardClicks})`;
M.window_reach_check = `Harness: ${reach.c.reachedDrawings} of 500 drawings reached by PageDown in (c), the focused surrogate stayed through pan +300, pan -600, zoom to 40 bars and a plot resize with focus kept: ${pan.c.pass}`;
M.target_size_check = `(measured: the smallest surrogate rectangle is ${geometry.c.minWidthPx} x ${geometry.c.minHeightPx} px over ${geometry.c.surrogates} surrogates in (c) at 200 and ${geometry.a.minWidthPx} x ${geometry.a.minHeightPx} px over ${geometry.a.surrogates} in (a); under 24 px: ${geometry.c.under24} and ${geometry.a.under24}; equality with the engine's pickable bounds is not measurable here, because the stand-in builds the rectangle from the same bounds)`;
M.sink_result =
  ["a", "b", "c"].map((s) => `(${s}) ${sink[s].passed} of ${sink[s].cases} passed`).join(", ") +
  `; handler fired: ${Object.values(sink).some((x) => x.handlerFired)}; ${staticScan}`;
M.sink_cases = String(SINK_LABELS.length);
M.focus_reach_roving = `${reach.c.reachedDrawings} of 500 (c) and ${reach.a.reachedDrawings} of 500 (a)`;
M.focus_reach_active = `${reach.b.reachedDrawings} of 500 (b)`;
M.focus_order_result = ["a", "b", "c"]
  .map(
    (s) =>
      `(${s}) ${order[s].pass ? "pass" : "fail"}: Tab visits ${order[s].forward.slice(0, 4).join(" > ")}, ${order[s].tabStopsInSet} Tab stop in the set`,
  )
  .join("; ");
M.obscured_result = `docked drawer max covered fraction ${f(geometry.obscured.dockedDrawerMax, 3)}, placed popover ${f(geometry.obscured.popoverPlacedMax, 3)} over ${geometry.obscured.sampled} surrogates (by geometry, so close to by construction); the controls show the check can fail: an overlaying drawer covers up to ${f(geometry.obscured.controlOverlayDrawerMax, 2)}, a centred popover ${f(geometry.obscured.controlNaivePopoverMax, 2)}`;
M.writes_per_second_max = `${sw.maxPerFixedSecond} (fixed 1 s buckets), ${sw.maxPerSlidingSecond} in any sliding 1 s`;
M.dropped_writes = `${sw.droppedValueWrites} of ${sw.valueUpdates} value updates overwritten before a write (latest wins); confirmations written ${sw.confirmWrites}, left queued ${sw.confirmationsPending}, confirmation latency p50 ${f(sw.confirmLatencyMs.p50, 0)} / p95 ${f(sw.confirmLatencyMs.p95, 0)} / max ${f(sw.confirmLatencyMs.max, 0)} ms`;

const results = {
  harness: "E14-K01 (#356), throwaway",
  startedAt,
  finishedAt: new Date().toISOString(),
  params: {
    seed: SEED,
    atBuilds: AT_N,
    dragFrames: FRAMES,
    warmFrames: WARM,
    sessionSeconds: SESSION_S,
    sizes: SIZES,
    sweep: SWEEP,
    gates: { atMs: GATE_AT_MS, dragMs: GATE_DRAG_MS, frameBudgetMs: +FRAME_BUDGET_MS.toFixed(2) },
    tiebreakPerDrawingNodes: TIEBREAK_PER_DRAWING_NODES,
    adoptCapMax: ADOPT_CAP_MAX,
    smoke: a.smoke,
  },
  environment: {
    chromium: chromiumVersion,
    playwright: pwVersion,
    node: process.version,
    host,
    loadavgStart: la0,
    loadavgEnd: laEnd,
  },
  fixtureSha256: fixtureHash,
  viewportBars: WIDTH,
  crossOriginIsolated: isolated,
  evidenceClass:
    "headless Chromium on a contended shared host: a gate met is conservative, a gate missed is inconclusive",
  cells,
  baseline,
  sweep,
  reach,
  focusOrder: order,
  windowShift: pan,
  script,
  sink,
  geometry,
  liveRegion: session,
  pointer,
  decision: {
    survivors,
    reachable,
    recommended: rec,
    fellBack,
    cap,
    capAdopted,
    verdicts: Object.fromEntries(cells.map((c) => [`${c.strategy}_${c.n}`, verdictOf(c)])),
  },
  measures: M,
};
const outFile = a.smoke
  ? resolve(process.env.TMPDIR || here, "E14-K01-smoke.json")
  : join(a.out, "E14-K01-results.json");
writeFileSync(outFile, JSON.stringify(results, null, 2) + "\n");
console.log("wrote", outFile);
await browser.close();
server.close();
