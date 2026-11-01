// THROWAWAY SPIKE HARNESS (E14-K01 #356). Browser side: a synthetic scene, three surrogate strategies,
// a synthetic cursor and viewport (the shapes of ChartEvents.crosshair and viewportChanged), a keyboard
// drawing flow, a live-region announcer and the probes run.mjs reads. It imports nothing from the engine or the app.
// Rule for text: every string reaches the DOM through setName (aria-label property API) or setText (a single
// text node). There is no HTML setter anywhere in this file, and run.mjs scans for one.
import {
  makeFixture,
  nameOf,
  anchorName,
  TOOLS,
  VIEW0,
  WIDTH,
  TICK,
  P0,
  fmtT,
  fmtP,
  sortOrder,
  mulberry32,
} from "./fixture.mjs";

const q = new URLSearchParams(location.search);
const STRAT = q.get("s") || "c"; // a | b | c | none
const N = Number(q.get("n") || 50);
const SEED = Number(q.get("seed") || 356);
const FORCE_K = Number(q.get("k") || 0); // sweep only: a capped window of exactly K drawings (strategy c)
const PW = 1200,
  PH = 600,
  PLO = 63400,
  PHI = 64600;
const $ = (id) => document.getElementById(id);
const chart = $("chart"),
  mirror = $("mirror"),
  drawer = $("drawer");

// ---- pointer-event counter (the keyboard-only runs must record zero) -------------------------------------------
const ptr = { n: 0, by: {} };
for (const t of [
  "pointerdown",
  "pointerup",
  "pointermove",
  "mousedown",
  "mouseup",
  "mousemove",
  "click",
  "dblclick",
  "wheel",
  "touchstart",
  "contextmenu",
])
  window.addEventListener(
    t,
    (e) => {
      if (t === "click" && e.detail === 0) {
        ptr.kbClicks = (ptr.kbClicks || 0) + 1;
        ptr.kbTargets = [
          ...(ptr.kbTargets || []),
          e.target.tagName + ":" + (e.target.id || e.target.dataset.kind || ""),
        ];
        return;
      } // keyboard activation of a button
      ptr.n += 1;
      ptr.by[t] = (ptr.by[t] || 0) + 1;
    },
    true,
  );

// ---- text sinks -------------------------------------------------------------------------------------------------
const setName = (el, s) => el.setAttribute("aria-label", s);
const setText = (el, s) => {
  el.textContent = s;
};

// ---- scene and synthetic viewport/cursor -----------------------------------------------------------------------
const scene = new Map(); // id -> drawing
let order = []; // ids in time-then-price order
let ranks = new Map();
for (const d of makeFixture(SEED).slice(0, N)) scene.set(d.id, d);
const bounds = (d) => {
  if (d.tool === "horizontal_line") return [-Infinity, Infinity];
  let a = Infinity,
    b = -Infinity;
  for (const k of d.anchors) {
    if (k.t < a) a = k.t;
    if (k.t > b) b = k.t;
  }
  return [a, b];
};
const resort = () => {
  order = sortOrder([...scene.values()]).map((d) => d.id);
  ranks = new Map(order.map((id, i) => [id, i + 1]));
};
resort();
const V = { start: VIEW0, width: WIDTH };
const bus = new EventTarget(); // 'viewportChanged' { timeStart, timeEnd, barSpacing }, 'crosshair' { time, price, barIndex }
const xOf = (t) => ((t - V.start) / V.width) * PW;
const yOf = (p) => ((PHI - p) / (PHI - PLO)) * PH;
const S = {
  focus: null,
  rov: null,
  selected: new Set(),
  tool: null,
  cursor: null,
  snap: 0,
  seq: 0,
  undo: [],
  measuring: false,
};
const stats = { rec: [], query: [], windowSize: [] };
const nodes = new Map(); // id -> { els, c }
const lastClose = Math.round(P0 / TICK) * TICK;

function setViewport(start) {
  V.start = start;
  bus.dispatchEvent(
    new CustomEvent("viewportChanged", {
      detail: { timeStart: start, timeEnd: start + V.width, barSpacing: PW / V.width },
    }),
  );
}

// ---- the window (strategy c) -----------------------------------------------------------------------------------
function windowIds() {
  if (STRAT === "a") return order;
  const want = new Set(S.selected);
  if (S.focus) want.add(S.focus.id);
  if (FORCE_K) {
    const mid = V.start + V.width / 2;
    let lo = 0,
      hi = order.length;
    while (lo < hi) {
      const m = (lo + hi) >> 1;
      if (bounds(scene.get(order[m]))[0] < mid) lo = m + 1;
      else hi = m;
    }
    const from = Math.max(0, Math.min(order.length - FORCE_K, lo - (FORCE_K >> 1)));
    for (let i = from; i < from + FORCE_K; i += 1) want.add(order[i]);
  } else {
    const t0 = V.start,
      t1 = V.start + V.width;
    for (const id of order) {
      const [a, b] = bounds(scene.get(id));
      if (b >= t0 && a <= t1) want.add(id);
    }
  }
  return order.filter((id) => want.has(id));
}

// ---- the DOM mirror ----------------------------------------------------------------------------------------------
let grp = null,
  host = null,
  act = null,
  gridRows = null,
  gridCounts = new Map(),
  rovEl = null;
function buildContainer() {
  mirror.replaceChildren();
  nodes.clear();
  rovEl = null;
  gridCounts = new Map();
  if (STRAT === "none") return;
  if (STRAT === "b") {
    host = document.createElement("div");
    host.id = "host";
    host.setAttribute("role", "application");
    host.tabIndex = 0;
    setName(
      host,
      "Drawings, summary grid. Page Up and Page Down move between items. Arrows nudge.",
    );
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    setName(grid, "Drawing summary");
    const mkRow = (id) => {
      const r = document.createElement("div");
      r.setAttribute("role", "row");
      if (id) r.id = id;
      return r;
    };
    const mkCell = (t) => {
      const c = document.createElement("div");
      c.setAttribute("role", "gridcell");
      setText(c, t);
      return c;
    };
    const head = mkRow();
    head.append(mkCell("Tool"), mkCell("Count"));
    grid.append(head);
    const kinds = new Map();
    for (const d of scene.values()) kinds.set(d.tool, (kinds.get(d.tool) || 0) + 1);
    for (const [k, n] of kinds) {
      const r = mkRow();
      const c = mkCell(String(n));
      r.append(mkCell(TOOLS[k].name), c);
      grid.append(r);
      gridCounts.set(k, { c, n });
    }
    act = mkRow("act");
    setName(act, "No drawing focused");
    grid.append(act);
    host.setAttribute("aria-activedescendant", "act");
    host.append(grid);
    mirror.append(host);
    return;
  }
  grp = document.createElement("div");
  grp.setAttribute("role", "group");
  grp.id = "grp";
  grp.setAttribute("aria-describedby", "grpdesc");
  const desc = document.createElement("span");
  desc.id = "grpdesc";
  setText(desc, "Page Up / Page Down move between items. Arrows nudge.");
  grp.append(desc);
  mirror.append(grp);
}
const btn = (kind, id, anchor) => {
  const e = document.createElement("button");
  e.type = "button";
  e.tabIndex = -1;
  e.className = "sur";
  e.dataset.kind = kind;
  e.dataset.id = id;
  if (anchor >= 0) e.dataset.anchor = String(anchor);
  return e;
};
function create(d) {
  const els = [btn("obj", d.id, -1)];
  for (let k = 0; k < d.anchors.length; k += 1) els.push(btn("anchor", d.id, k));
  return { els, c: { an: [] } };
}
const r2 = (x) => Math.round(x * 100) / 100;
function put(el, c, key, x, y, w, h) {
  const tr = `translate(${r2(x)}px,${r2(y)}px)`;
  if (c[key + "t"] !== tr) {
    el.style.transform = tr;
    c[key + "t"] = tr;
  }
  const sz = `${r2(w)}x${r2(h)}`;
  if (c[key + "s"] !== sz) {
    el.style.width = `${r2(w)}px`;
    el.style.height = `${r2(h)}px`;
    c[key + "s"] = sz;
  }
}
function update(rec, d, rank) {
  const c = rec.c,
    o = rec.els[0],
    total = scene.size;
  const [a, b] = bounds(d);
  let pLo = Infinity,
    pHi = -Infinity;
  for (const k of d.anchors) {
    if (k.p < pLo) pLo = k.p;
    if (k.p > pHi) pHi = k.p;
  }
  const x0 = Number.isFinite(a) ? xOf(a) : 0,
    x1 = Number.isFinite(b) ? xOf(b) : PW;
  const top = yOf(pHi),
    bot = yOf(pLo);
  const w = Math.max(24, x1 - x0),
    h = Math.max(24, bot - top);
  put(o, c, "o", x0 - (w - (x1 - x0)) / 2, top - (h - (bot - top)) / 2, w, h);
  const nm = `${nameOf(d)}, item ${rank} of ${total}${d.locked ? ", locked" : ""}`;
  if (c.nm !== nm) {
    setName(o, nm);
    c.nm = nm;
  }
  if (c.rk !== rank) {
    o.setAttribute("aria-posinset", String(rank));
    c.rk = rank;
  }
  if (c.sz !== total) {
    o.setAttribute("aria-setsize", String(total));
    c.sz = total;
  }
  const pr = S.selected.has(d.id);
  if (c.pr !== pr) {
    o.setAttribute("aria-pressed", String(pr));
    c.pr = pr;
  }
  for (let k = 0; k < d.anchors.length; k += 1) {
    const e = rec.els[k + 1],
      an = d.anchors[k];
    put(e, c, "a" + k, xOf(an.t) - 12, yOf(an.p) - 12, 24, 24);
    const n2 = anchorName(d, k);
    if (c.an[k] !== n2) {
      setName(e, n2);
      c.an[k] = n2;
    }
  }
}
function sync(ids) {
  const want = new Set(ids);
  for (const [id, rec] of nodes)
    if (!want.has(id)) {
      for (const e of rec.els) e.remove();
      nodes.delete(id);
    }
  let prev = null;
  for (const id of ids) {
    const d = scene.get(id);
    let rec = nodes.get(id);
    if (!rec) {
      rec = create(d);
      if (prev) prev.els[prev.els.length - 1].after(...rec.els);
      else grp.firstChild.after(...rec.els);
      nodes.set(id, rec);
    }
    update(rec, d, ranks.get(id));
    prev = rec;
  }
  // roving tabindex: exactly one Tab stop in the set
  let target = S.rov && nodes.get(S.rov.id) ? nodes.get(S.rov.id).els[S.rov.anchor + 1] : null;
  if (!target && ids.length) target = nodes.get(ids[0]).els[0];
  if (target !== rovEl) {
    if (rovEl) rovEl.tabIndex = -1;
    if (target) target.tabIndex = 0;
    rovEl = target;
  }
}
function reconcileB() {
  const kinds = new Map();
  for (const d of scene.values()) kinds.set(d.tool, (kinds.get(d.tool) || 0) + 1);
  for (const [k, g] of gridCounts) {
    const n = kinds.get(k) || 0;
    if (g.n !== n) {
      setText(g.c, String(n));
      g.n = n;
    }
  }
  const d = S.focus ? scene.get(S.focus.id) : null;
  const nm = d
    ? S.focus.anchor >= 0
      ? anchorName(d, S.focus.anchor)
      : `${nameOf(d)}, item ${ranks.get(d.id)} of ${scene.size}${d.locked ? ", locked" : ""}`
    : "No drawing focused";
  if (act._nm !== nm) {
    setName(act, nm);
    act._nm = nm;
  }
  if (d) {
    act.setAttribute("aria-posinset", String(ranks.get(d.id)));
    act.setAttribute("aria-setsize", String(scene.size));
  }
}
function reconcile() {
  performance.mark("r0");
  if (STRAT === "b") reconcileB();
  else if (STRAT !== "none") {
    performance.mark("q0");
    const ids = windowIds();
    performance.mark("q1");
    sync(ids);
    if (S.measuring) {
      stats.query.push(performance.measure("qq", "q0", "q1").duration);
      stats.windowSize.push(ids.length);
    }
  }
  performance.mark("r1");
  const m = performance.measure("rec", "r0", "r1");
  if (S.measuring) stats.rec.push(m.duration);
  performance.clearMarks();
  performance.clearMeasures();
}
bus.addEventListener("viewportChanged", () => reconcile());

// ---- focus -----------------------------------------------------------------------------------------------------
const elOf = (f) => (f && nodes.get(f.id) ? nodes.get(f.id).els[f.anchor + 1] : null);
function applyFocus() {
  if (STRAT === "b") {
    if (document.activeElement !== host) host.focus({ preventScroll: true });
    return;
  }
  const el = elOf(S.focus);
  if (el && document.activeElement !== el) el.focus({ preventScroll: true });
}
function ensureVisible(d) {
  const [a, b] = bounds(d);
  if (Number.isFinite(a) && (b < V.start || a > V.start + V.width)) setViewport(a - 20);
}
function focusItem(id, anchor) {
  S.focus = { id, anchor };
  S.rov = { id, anchor };
  ensureVisible(scene.get(id));
  reconcile();
  applyFocus();
}
chart.addEventListener("focusin", (e) => {
  const t = e.target;
  if (STRAT === "b" && t === host) {
    if (!S.focus)
      S.focus =
        S.rov && scene.has(S.rov.id) ? S.rov : order.length ? { id: order[0], anchor: -1 } : null;
    S.rov = S.focus;
    reconcile();
  } else if (t.dataset && t.dataset.id) {
    S.focus = { id: t.dataset.id, anchor: Number(t.dataset.anchor ?? -1) };
    S.rov = S.focus;
  }
});
const flat = () => {
  const out = [];
  for (const id of order) {
    out.push([id, -1]);
    for (let k = 0; k < scene.get(id).anchors.length; k += 1) out.push([id, k]);
  }
  return out;
};
function focusInfo() {
  const a = document.activeElement;
  if (STRAT === "b" && a === host && S.focus) {
    return {
      kind: S.focus.anchor >= 0 ? "anchor" : "obj",
      id: S.focus.id,
      anchor: S.focus.anchor,
      label: act.getAttribute("aria-label"),
      pos: Number(act.getAttribute("aria-posinset")),
      size: Number(act.getAttribute("aria-setsize")),
    };
  }
  if (a && a.dataset && a.dataset.id)
    return {
      kind: a.dataset.kind,
      id: a.dataset.id,
      anchor: Number(a.dataset.anchor ?? -1),
      label: a.getAttribute("aria-label"),
      pos: Number(a.getAttribute("aria-posinset")),
      size: Number(a.getAttribute("aria-setsize")),
    };
  return { kind: a ? a.id || a.tagName.toLowerCase() : "none" };
}

// ---- announcer (the policy under test: D10 section 7 / 8.2 as the BQ default) -----------------------------------
class Announcer {
  constructor() {
    this.regions = { cursor: $("cursorRegion"), draw: $("drawRegion") };
    this.q = [];
    this.pend = new Map();
    this.lastKey = new Map();
    this.recent = [];
    this.lastAny = -1e9;
    this.log = [];
    this.enq = [];
    this.written = [];
    this.upd = 0;
    this.dropped = 0;
    this.lat = [];
    this.timer = null;
    // counts the DOM mutation records of the two status regions, to cross-check the write count
    this.mo2 = new MutationObserver((rs) => {
      this.mut2 += rs.length;
    });
    this.mut2 = 0;
    for (const r of Object.values(this.regions))
      this.mo2.observe(r, { childList: true, characterData: true, subtree: true });
  }
  confirm(text, region = "draw") {
    this.enq.push(text);
    this.q.push({ text, region, t: performance.now() });
    this.kick();
  }
  value(key, text, region = "draw") {
    this.upd += 1;
    if (this.pend.has(key)) this.dropped += 1; // the earlier value is overwritten: latest wins
    this.pend.set(key, { text, region, t: performance.now() });
    this.kick();
  }
  kick() {
    if (!this.timer) this.timer = setInterval(() => this.tick(), 25);
  }
  free(now) {
    this.recent = this.recent.filter((t) => now - t < 1000);
    return this.recent.length < 2;
  }
  write(now, region, text, kind, key, t0) {
    setText(this.regions[region], text);
    this.recent.push(now);
    this.lastAny = now;
    if (key) this.lastKey.set(key, now);
    this.log.push({ t: now, region, kind });
    if (kind === "confirm") this.written.push(text);
    this.lat.push({ kind, ms: now - t0 });
  }
  tick() {
    const now = performance.now();
    if (!this.free(now)) return;
    if (this.q.length) {
      if (now - this.lastAny >= 500) {
        const e = this.q.shift();
        this.write(now, e.region, e.text, "confirm", null, e.t);
      }
    } else {
      for (const [key, e] of this.pend) {
        if (now - (this.lastKey.get(key) ?? -1e9) >= 500 && now - this.lastAny >= 250) {
          this.pend.delete(key);
          this.write(now, e.region, e.text, "value", key, e.t);
          break;
        }
      }
    }
    if (!this.q.length && !this.pend.size) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
  report() {
    const ts = this.log.map((x) => x.t);
    let slide = 0;
    for (let i = 0; i < ts.length; i += 1) {
      let c = 0;
      for (let j = i; j < ts.length && ts[j] - ts[i] < 1000; j += 1) c += 1;
      slide = Math.max(slide, c);
    }
    const buckets = new Map();
    for (const t of ts) {
      const b = Math.floor((t - ts[0]) / 1000);
      buckets.set(b, (buckets.get(b) || 0) + 1);
    }
    const conf = this.lat
      .filter((x) => x.kind === "confirm")
      .map((x) => x.ms)
      .sort((x, y) => x - y);
    const val = this.lat
      .filter((x) => x.kind === "value")
      .map((x) => x.ms)
      .sort((x, y) => x - y);
    const pc = (a, p) => (a.length ? a[Math.min(a.length - 1, Math.ceil(p * a.length) - 1)] : null);
    return {
      writes: this.log.length,
      domMutationRecords: this.mut2,
      maxPerFixedSecond: Math.max(0, ...buckets.values()),
      maxPerSlidingSecond: slide,
      valueUpdates: this.upd,
      droppedValueWrites: this.dropped,
      confirmWrites: conf.length,
      confirmationsPending: this.q.length,
      confirmLatencyMs: {
        p50: pc(conf, 0.5),
        p95: pc(conf, 0.95),
        max: conf.length ? conf[conf.length - 1] : null,
      },
      valueLatencyMs: {
        p50: pc(val, 0.5),
        p95: pc(val, 0.95),
        max: val.length ? val[val.length - 1] : null,
      },
    };
  }
}
const ann = new Announcer();

// ---- keyboard drawing flow (D02 keys; the two Alt keys marked harness-only are not proposals) -------------------
const HOTKEYS = {
  KeyL: "trendline",
  KeyH: "horizontal_line",
  KeyR: "rectangle",
  KeyO: "fib_retracement",
  KeyD: "measure",
  KeyC: "parallel_channel", // harness-only key, not a proposal
  KeyP: "polyline", // harness-only key, not a proposal
};
const SNAPS = ["off", "high", "low", "close"];
const curText = () => `${fmtT(S.cursor.t)} ${fmtP(S.cursor.p)}`;
function arm(tool) {
  S.tool = { id: tool, anchors: [] };
  if (!S.cursor) S.cursor = { t: V.start + WIDTH / 2, p: lastClose };
  chart.focus({ preventScroll: true });
  ann.confirm(`${TOOLS[tool].name} tool on.`);
}
function commit() {
  const t = S.tool;
  const d = {
    id: `n${++S.seq}`,
    tool: t.id,
    anchors: t.anchors.map((a) => ({ ...a })),
    locked: false,
  };
  scene.set(d.id, d);
  resort();
  S.tool = null;
  S.selected = new Set([d.id]);
  S.undo.push({
    id: null,
    fn: () => {
      scene.delete(d.id);
      S.selected.delete(d.id);
      resort();
    },
  });
  focusItem(d.id, -1);
  ann.confirm(`${TOOLS[d.tool].name} created. Selected.`);
}
function armedKey(e) {
  const k = e.key,
    m = e.shiftKey ? 10 : 1,
    t = S.tool,
    def = TOOLS[t.id];
  let used = true;
  if (e.ctrlKey && (k === "ArrowUp" || k === "ArrowDown")) {
    S.snap = (S.snap + (k === "ArrowUp" ? 1 : 3)) % 4;
    ann.value("snap", `Snap ${SNAPS[S.snap]}.`);
  } else if (k === "ArrowLeft") {
    S.cursor.t -= m;
    ann.value("pending", curText());
  } else if (k === "ArrowRight") {
    S.cursor.t += m;
    ann.value("pending", curText());
  } else if (k === "ArrowUp") {
    S.cursor.p += TICK * m;
    ann.value("pending", curText());
  } else if (k === "ArrowDown") {
    S.cursor.p -= TICK * m;
    ann.value("pending", curText());
  } else if (k === "Enter") {
    // Shift+Enter closes the polyline here: harness-only, not a proposal of this spike (D02 T27 owns the key)
    if (e.shiftKey && t.id === "polyline" && t.anchors.length >= 2) {
      e.preventDefault();
      return commit();
    }
    t.anchors.push({ t: S.cursor.t, p: S.cursor.p });
    const need = def.anchors || "N";
    ann.confirm(`Anchor ${t.anchors.length} of ${need} at ${curText()}.`);
    if (def.anchors && t.anchors.length === def.anchors) commit();
  } else if (k === "Escape") {
    if (t.anchors.length) {
      t.anchors.pop();
      ann.confirm(`Placement cancelled. ${def.name} tool still on.`);
    } else {
      S.tool = null;
      ann.confirm(`${def.name} tool off.`);
    }
  } else used = false;
  if (used) e.preventDefault();
}
function nudge(e, f) {
  const d = scene.get(f.id),
    k = e.key,
    m = e.shiftKey ? 10 : 1;
  if (d.locked) {
    ann.confirm("This drawing is locked.");
    return;
  }
  const dt = k === "ArrowRight" ? m : k === "ArrowLeft" ? -m : 0,
    dp = k === "ArrowUp" ? TICK * m : k === "ArrowDown" ? -TICK * m : 0;
  const before = d.anchors.map((a) => ({ ...a }));
  const hit = f.anchor >= 0 ? [d.anchors[f.anchor]] : d.anchors;
  for (const a of hit) {
    a.t += dt;
    a.p += dp;
  }
  S.undo.push({
    id: d.id,
    fn: () => {
      d.anchors = before;
      resort();
    },
  });
  resort();
  reconcile();
  ann.value("nudge", `${fmtP(hit[0].p)}`);
}
function del(f) {
  const d = scene.get(f.id);
  if (d.locked) {
    ann.confirm("This drawing is locked.");
    return;
  }
  const idx = order.indexOf(f.id);
  scene.delete(f.id);
  S.selected.delete(f.id);
  resort();
  S.undo.push({
    id: d.id,
    fn: () => {
      scene.set(d.id, d);
      resort();
    },
  });
  const next = order[Math.min(idx, order.length - 1)];
  if (next) focusItem(next, -1);
  else {
    S.focus = null;
    reconcile();
    chart.focus();
  }
  ann.confirm(`${TOOLS[d.tool].name} removed. Undo available.`);
}
function handlesKey(e) {
  const f = S.focus,
    k = e.key;
  if (!f) return;
  const fl = flat(),
    i = fl.findIndex(([id, a]) => id === f.id && a === f.anchor);
  let used = true;
  if (k === "PageDown") focusItem(...fl[Math.min(fl.length - 1, i + 1)]);
  else if (k === "PageUp") focusItem(...fl[Math.max(0, i - 1)]);
  else if (k === "Home") focusItem(...fl[0]);
  else if (k === "End") focusItem(...fl[fl.length - 1]);
  else if (k.startsWith("Arrow")) nudge(e, f);
  else if (k === " ") {
    if (!S.selected.delete(f.id)) S.selected.add(f.id);
    reconcile();
  } else if (k === "Delete" || k === "Backspace") del(f);
  else if (k === "Escape") {
    S.selected.clear();
    S.focus = null;
    reconcile();
    chart.focus();
  } else used = false;
  if (used) e.preventDefault();
}
chart.addEventListener("keydown", (e) => {
  if (e.altKey && !e.ctrlKey && HOTKEYS[e.code]) {
    arm(HOTKEYS[e.code]);
    e.preventDefault();
    return;
  }
  if (e.ctrlKey && e.key.toLowerCase() === "z") {
    e.preventDefault();
    const u = S.undo.pop();
    if (!u) return;
    u.fn();
    if (u.id && scene.has(u.id))
      focusItem(u.id, -1); // the object surrogate takes focus
    else {
      S.focus = null;
      reconcile();
      chart.focus();
    }
    ann.confirm("Undone.");
    return;
  }
  if (S.tool) return armedKey(e);
  if (e.target !== chart) handlesKey(e);
});
// a trail of focus targets after every key, so run.mjs reads one array instead of one round trip per key
const trail = [];
let trailOn = false;
document.addEventListener("keyup", () => {
  if (trailOn) trail.push(focusInfo());
});

// ---- synthetic main-thread load: a 100k-bar series, autoscaled and redrawn each frame ---------------------------
const BARS = 100000;
const hi = new Float32Array(BARS),
  lo = new Float32Array(BARS),
  cl = new Float32Array(BARS);
{
  const r = mulberry32(SEED + 1);
  let p = P0;
  for (let i = 0; i < BARS; i += 1) {
    p += (r() - 0.5) * 8;
    cl[i] = p;
    hi[i] = p + r() * 4;
    lo[i] = p - r() * 4;
  }
}
const ctx = $("cv").getContext("2d");
function drawLoad() {
  let mn = Infinity,
    mx = -Infinity;
  for (let i = 0; i < BARS; i += 1) {
    if (lo[i] < mn) mn = lo[i];
    if (hi[i] > mx) mx = hi[i];
  }
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, PW, PH);
  ctx.strokeStyle = "#4a8";
  ctx.beginPath();
  const per = BARS / PW;
  for (let x = 0; x < PW; x += 1) {
    let a = Infinity,
      b = -Infinity;
    for (let i = Math.floor(x * per), e = Math.floor((x + 1) * per); i < e; i += 1) {
      if (lo[i] < a) a = lo[i];
      if (hi[i] > b) b = hi[i];
    }
    const s = (v) => PH - ((v - mn) / (mx - mn)) * PH * 0.3;
    ctx.moveTo(x, s(a));
    ctx.lineTo(x, s(b));
  }
  ctx.stroke();
  ctx.strokeStyle = "#ccc";
  for (let i = 0; i < WIDTH; i += 1) {
    const b = VIEW0 + i,
      x = i * (PW / WIDTH),
      y1 = yOf(hi[b]),
      y2 = yOf(lo[b]);
    ctx.strokeRect(x + 2, Math.min(y1, y2), 6, Math.abs(y2 - y1) + 1);
  }
}

// ---- probes ----------------------------------------------------------------------------------------------------
const pick = () => {
  const id = order[Math.floor(order.length / 2)];
  return scene.get(id).locked ? order[Math.floor(order.length / 2) + 1] : id;
};
function drag({ frames, warm }) {
  const id = pick(),
    d = scene.get(id),
    base = d.anchors.map((a) => ({ ...a })),
    start0 = V.start;
  S.focus = { id, anchor: -1 };
  S.rov = S.focus;
  S.selected = new Set([id]);
  reconcile();
  applyFocus();
  stats.rec = [];
  stats.query = [];
  stats.windowSize = [];
  return new Promise((resolve) => {
    let i = 0,
      last = null;
    const ints = [];
    const f = (ts) => {
      if (i === warm) S.measuring = true;
      drawLoad();
      d.anchors.forEach((a, k) => {
        a.p = base[k].p + TICK * Math.round(8 * Math.sin(i / 15));
        a.t = base[k].t + Math.round(2 * Math.sin(i / 40));
      });
      resort();
      setViewport(start0 + 40 * Math.sin(i / 60)); // edge-pan while dragging: every surrogate moves each frame
      if (last !== null && i >= warm) ints.push(ts - last);
      last = ts;
      i += 1;
      if (i < frames + warm) requestAnimationFrame(f);
      else {
        S.measuring = false;
        d.anchors = base;
        resort();
        setViewport(start0);
        resolve({
          rec: stats.rec.slice(),
          query: stats.query.slice(),
          win: stats.windowSize.slice(),
          ints,
        });
      }
    };
    requestAnimationFrame(f);
  });
}
function rebuild() {
  S.focus = null;
  S.rov = null;
  S.selected.clear();
  V.start = VIEW0;
  buildContainer();
  reconcile();
  return count();
}
const count = () => mirror.querySelectorAll("*").length;

function targets() {
  let minW = Infinity,
    minH = Infinity,
    under = 0,
    n = 0;
  for (const el of mirror.querySelectorAll(".sur")) {
    const r = el.getBoundingClientRect();
    n += 1;
    minW = Math.min(minW, r.width);
    minH = Math.min(minH, r.height);
    if (r.width < 23.99 || r.height < 23.99) under += 1;
  }
  return { surrogates: n, minWidthPx: r2(minW), minHeightPx: r2(minH), under24: under };
}
function obscured() {
  const cr = chart.getBoundingClientRect(),
    dr = drawer.getBoundingClientRect();
  const area = (r) => Math.max(0, r.width) * Math.max(0, r.height);
  const inter = (a, b) => ({
    width: Math.min(a.right, b.right) - Math.max(a.left, b.left),
    height: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
  });
  const cover = (r, o) => area(inter(r, o)) / area(r);
  const rect = (x, y, w, h) => ({
    left: x,
    top: y,
    right: x + w,
    bottom: y + h,
    width: w,
    height: h,
  });
  const place = (r) => {
    const W = 260,
      H = 160;
    const c = [
      rect(r.right + 4, r.top, W, H),
      rect(r.left - 4 - W, r.top, W, H),
      rect(r.left, r.bottom + 4, W, H),
      rect(r.left, r.top - 4 - H, W, H),
    ];
    return (
      c.find(
        (p) => p.left >= cr.left && p.right <= cr.right && p.top >= cr.top && p.bottom <= cr.bottom,
      ) || c[2]
    );
  };
  const items = [...mirror.querySelectorAll(".sur")].filter((el) => {
    const r = el.getBoundingClientRect();
    return area(inter(r, cr)) > 0;
  });
  const out = {
    sampled: 0,
    dockedDrawerMax: 0,
    popoverPlacedMax: 0,
    controlOverlayDrawerMax: 0,
    controlNaivePopoverMax: 0,
  };
  const step = Math.max(1, Math.floor(items.length / 80));
  for (let i = 0; i < items.length; i += step) {
    const raw = items[i].getBoundingClientRect();
    out.sampled += 1;
    const v = inter(raw, cr),
      r = rect(Math.max(raw.left, cr.left), Math.max(raw.top, cr.top), v.width, v.height); // the mirror clips to the plot
    out.dockedDrawerMax = Math.max(out.dockedDrawerMax, cover(r, dr));
    out.popoverPlacedMax = Math.max(out.popoverPlacedMax, cover(r, place(r)));
    out.controlOverlayDrawerMax = Math.max(
      out.controlOverlayDrawerMax,
      cover(r, rect(cr.right - 320, cr.top, 320, PH)),
    );
    out.controlNaivePopoverMax = Math.max(
      out.controlNaivePopoverMax,
      cover(r, rect(r.left + r.width / 2 - 130, r.top + r.height / 2 - 80, 260, 160)),
    );
  }
  return out;
}
function sinkTest(labels) {
  const build = (strs) => {
    scene.clear();
    strs.forEach((s, i) =>
      scene.set(`s${i}`, {
        id: `s${i}`,
        tool: "text",
        anchors: [{ t: VIEW0 + 10 + i, p: P0 + i }],
        text: s,
        label: s,
        locked: false,
      }),
    );
    resort();
    V.start = VIEW0;
    S.selected.clear();
    S.focus = null;
    S.rov = null;
    buildContainer();
    reconcile();
    if (STRAT === "b")
      strs.forEach((_, i) => {
        S.focus = { id: `s${i}`, anchor: -1 };
        reconcile();
      });
  };
  build(labels.map(() => "plain"));
  const baseline = count();
  const results = [];
  for (let i = 0; i < labels.length; i += 1) {
    build(labels.slice(i, i + 1));
    const s = labels[i],
      els = [...mirror.querySelectorAll("*")];
    const badTag = els.filter((e) => !["DIV", "BUTTON", "SPAN"].includes(e.tagName)).length;
    const fromLabel = mirror.querySelectorAll("img,script,b,i,svg,a,iframe,style,input").length;
    const named =
      STRAT === "b"
        ? act.getAttribute("aria-label")
        : mirror.querySelector('[data-kind="obj"]').getAttribute("aria-label");
    const exact = named.includes(s);
    const kids = STRAT === "b" ? [...act.children].length : 0;
    results.push({
      case: i,
      len: s.length,
      badTag,
      fromLabel,
      exact,
      actChildren: kids,
      ok: badTag === 0 && fromLabel === 0 && exact && kids === 0 && window.__k01 === undefined,
    });
  }
  return { baselineNodes: baseline, handlerFired: window.__k01 !== undefined, results };
}
function panTest() {
  const before = focusInfo(),
    el0 = document.activeElement,
    size0 = windowIds().length;
  const out = { before, steps: [] };
  const step = (name, fn) => {
    fn();
    const a = document.activeElement;
    out.steps.push({
      name,
      sameElement: a === el0 || (STRAT === "b" && a === host),
      stillMirrored: S.focus ? STRAT === "b" || nodes.has(S.focus.id) : null,
      posinsetKept: focusInfo().pos === before.pos,
      windowSize: windowIds().length,
    });
  };
  step("pan +300 bars", () => setViewport(V.start + 300));
  step("pan -600 bars", () => setViewport(V.start - 600));
  step("zoom to 40 bars", () => {
    V.width = 40;
    setViewport(V.start);
  });
  step("resize plot to 800 px", () => {
    chart.style.width = "800px";
    reconcile();
  });
  V.width = WIDTH;
  chart.style.width = "1200px";
  setViewport(VIEW0);
  out.windowSizeBefore = size0;
  return out;
}

window.__h = {
  strat: STRAT,
  n: N,
  seed: SEED,
  rebuild,
  count,
  drag,
  focusInfo,
  targets,
  obscured,
  sinkTest,
  panTest,
  trailOn: (v) => {
    trailOn = v;
    trail.length = 0;
  },
  trail: () => trail.slice(),
  setViewport,
  pan: (d) => setViewport(V.start + d),
  ptr: () => ({
    n: ptr.n,
    by: ptr.by,
    kbClicks: ptr.kbClicks || 0,
    kbTargets: ptr.kbTargets || [],
  }),
  snapshot: () => ({
    start: V.start,
    count: scene.size,
    window: STRAT === "none" ? 0 : windowIds().length,
    nodes: count(),
    cursor: S.cursor,
    tool: S.tool && S.tool.id,
    focus: S.focus,
    selected: [...S.selected],
    rank: Object.fromEntries(ranks),
  }),
  model: (id) => {
    const d = scene.get(id);
    return d ? { id, tool: d.tool, anchors: d.anchors, locked: d.locked, name: nameOf(d) } : null;
  },
  order: () => order.slice(),
  flat: () => flat().map(([id, a]) => `${id}:${a}`),
  lockedId: () => order.find((id) => scene.get(id).locked),
  tabStops: () => mirror.querySelectorAll('[tabindex="0"]').length,
  runSession(ms, seed) {
    const r = mulberry32(seed);
    const at = (t, fn) => setTimeout(fn, t);
    const cycle = 5000;
    for (let c0 = 0; c0 < ms; c0 += cycle) {
      const j = () => Math.floor(r() * 60);
      for (let t = 0; t < 1500; t += 33)
        at(c0 + t + (j() % 10), () => ann.value("nudge", `${fmtP(P0 + r() * 100)}`)); // key repeat at 30 Hz
      at(c0 + 1600 + j(), () => ann.confirm("Moved 64,000 to 64,120. Undo available."));
      for (let t = 2000; t < 3000; t += 33)
        at(c0 + t, () =>
          ann.value("cursor", `${fmtT(VIEW0 + r() * 100)} ${fmtP(P0 + r() * 100)}`, "cursor"),
        );
      at(c0 + 3200, () => ann.confirm("Trendline created. Selected.")); // a tight cluster: serialised, never dropped
      at(c0 + 3300, () => ann.confirm("Trendline tool on."));
      at(c0 + 3400, () => ann.confirm("Anchor 1 of 2 at 13:40, 63,980."));
      for (let t = 4000; t < 4500; t += 100)
        at(c0 + t, () => ann.value("snap", `Low ${fmtP(P0 - r() * 50)}.`));
      at(c0 + 4600, () => ann.confirm("Trendline removed. Undo available."));
      at(c0 + 4700, () => ann.confirm("Undone: moved trendline."));
      if (r() < 0.5) at(c0 + 4800, () => ann.confirm("This drawing is locked."));
    }
    return new Promise((res) => setTimeout(() => res(null), ms + 4000));
  },
  annReport: () => ann.report(),
  annState: () => ({ enq: ann.enq.slice(), written: ann.written.slice(), pending: ann.q.length }),
};

buildContainer();
reconcile();
window.ready = true;
