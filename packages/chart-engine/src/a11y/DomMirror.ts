// The DOM mirror (E11-S13 PR-2; 26 §12, E06-D03 D1/D2/D4, E47-D06 R-3/R-6/§4/§8 at #5443 head
// 7a9002db, if it merges as is): a visually hidden <table> of the cursor-centred window, one row
// per bar at every LOD, placed in the loaded series by aria-rowcount/aria-rowindex, the cursor's
// row marked aria-current, the time cell the row header (D4). Rows are a bar-keyed pool (a shift of
// k bars moves k rows and formats 7k cells; a row whose values did not change formats nothing);
// every write is textContent, never markup; all writes land in one batch per frame.
// It also rolls the canvas `img` label (D06 L-1) at the R-6 cadence. Typed structurally and handed
// the root's document by the host adapter (no DOM global, C-2.16). The canvas is presentation; the
// mirror, the cursor region and the label carry the semantics; conformance evidence is E11-Q05's.
import { A11Y_WINDOW_ROWS_MAX, type A11yRows, type A11yWindow } from "./window.js";

/** The element members the mirror uses (an HTMLElement fits). */
export interface MirrorNode {
  textContent: string | null;
  setAttribute(name: string, value: string): void;
  removeAttribute(name: string): void;
  appendChild(child: MirrorNode): unknown;
  insertBefore(child: MirrorNode, ref: MirrorNode | null): unknown;
  remove(): void;
}

export interface MirrorDeps {
  readonly root: MirrorNode;
  createElement(tag: string): MirrorNode;
  /** Runs `cb` once on the next frame (the page's rAF): the one batched write. */
  schedule(cb: () => void): void;
  now(): number;
  setTimer(cb: () => void, ms: number): () => void;
  /** Sets the canvas `img` label (the host re-applies it on a replaced canvas). */
  setCanvasLabel(text: string): void;
  readonly locale?: string;
  readonly timeZone?: string;
  /** E06-D03 `a11y.ambientCadenceMs` (D06 R-6, the SCR-117 default 1 per 2 s). */
  readonly ambientCadenceMs?: number;
}

/** `engine.a11y.*`: mirror_nodes, mirror_update_ms, desync_detected, mirror_rewindows (D06-G1). */
export class MirrorCounters {
  mirrorNodes = 0;
  mirrorUpdateMs = 0;
  desyncDetected = 0;
  mirrorRewindows = 0;
}

export const AMBIENT_CADENCE_MS = 2000;
/** 7 cells per row (26 §12); the words are E47-D07's (#1306) and provisional until PR-3's copy. */
const HEADERS = ["Time", "Open", "High", "Low", "Close", "Volume", "Delta"] as const;
const FIXED_NODES = 4 + HEADERS.length; // table, thead, header row, tbody + the header cells
/** E06-D03 D4: "Bars around the cursor", not "Visible bars" (the window is cursor-centred, D1). */
export const MIRROR_TABLE_LABEL = "Bars around the cursor";

interface Row {
  readonly tr: MirrorNode;
  readonly cells: MirrorNode[];
  readonly text: string[];
  /** The raw values last formatted, per cell (NaN = never), valid while `gen` is the mirror's. */
  readonly vals: Float64Array;
  gen: number;
  bar: number;
}

export class DomMirror {
  readonly counters = new MirrorCounters();
  private readonly table: MirrorNode;
  private readonly body: MirrorNode;
  private readonly live = new Map<number, Row>();
  private readonly free: Row[] = [];
  private readonly time: Intl.DateTimeFormat;
  private readonly qty: Intl.NumberFormat;
  private readonly signed: Intl.NumberFormat;
  private readonly cadence: number;
  private pendingW: A11yWindow | null = null;
  private pendingRows: A11yRows | null = null;
  private pendingBarCount = 0;
  private scheduled = false;
  private readonly onFrame = (): void => this.flush();
  /** The price format the rows' cached values were formatted with; a change bumps `gen`. */
  private gen = 0;
  private fmtOrigin = Number.NaN;
  private fmtTick = Number.NaN;
  private fmtDecimals = -1;
  private first = 0;
  private count = 0;
  private current: Row | null = null;
  private rowCount = "";
  private label = "";
  private labelShown = "";
  private labelN = -1;
  private labelClose = Number.NaN;
  private labelDelta = Number.NaN;
  private labelGen = -1;
  private labelAt = Number.NEGATIVE_INFINITY;
  private cancelLabel: (() => void) | null = null;
  private disposed = false;

  constructor(private readonly deps: MirrorDeps) {
    const tz = deps.timeZone ?? "UTC";
    this.time = new Intl.DateTimeFormat(deps.locale ?? "en-GB", {
      timeZone: tz,
      dateStyle: "short",
      timeStyle: "medium",
    });
    this.qty = new Intl.NumberFormat(deps.locale ?? "en-GB", { maximumFractionDigits: 3 });
    this.signed = new Intl.NumberFormat(deps.locale ?? "en-GB", {
      maximumFractionDigits: 3,
      signDisplay: "exceptZero",
    });
    this.cadence = deps.ambientCadenceMs ?? AMBIENT_CADENCE_MS;
    this.table = deps.createElement("table");
    this.table.setAttribute("data-cv-mirror-table", "");
    this.table.setAttribute("aria-label", MIRROR_TABLE_LABEL);
    const head = deps.createElement("thead");
    const tr = deps.createElement("tr");
    tr.setAttribute("aria-rowindex", "1");
    for (const h of HEADERS) {
      const th = deps.createElement("th");
      th.setAttribute("scope", "col");
      th.textContent = h;
      tr.appendChild(th);
    }
    head.appendChild(tr);
    this.body = deps.createElement("tbody");
    this.table.appendChild(head);
    this.table.appendChild(this.body);
    deps.root.appendChild(this.table);
    this.counters.mirrorNodes = FIXED_NODES;
  }

  /** Takes the latest `a11y` message (latest wins) and schedules one write for the next frame. */
  update(w: A11yWindow, rows: A11yRows | null, barCount: number): void {
    if (this.disposed) return;
    this.pendingW = w;
    this.pendingRows = rows;
    this.pendingBarCount = barCount;
    if (this.scheduled) return;
    this.scheduled = true;
    this.deps.schedule(this.onFrame);
  }

  /** The frame's one batched write. */
  flush(): void {
    this.scheduled = false;
    const w = this.pendingW;
    const rows = this.pendingRows;
    const barCount = this.pendingBarCount;
    this.pendingW = null;
    this.pendingRows = null;
    if (w === null || this.disposed) return;
    const t0 = this.deps.now();
    const size =
      w.lastBar < w.firstBar ? 0 : Math.min(w.lastBar - w.firstBar + 1, A11Y_WINDOW_ROWS_MAX);
    if (size === 0) this.place(0, 0);
    else if (rows !== null && rows.firstBar === w.firstBar && rows.count === size) {
      this.place(w.firstBar, size);
      this.fill(rows);
    } else if (rows !== null) this.counters.desyncDetected += 1; // never draw a mismatched window
    this.mark(this.live.get(w.cursorBar) ?? null);
    // The full-table count (D4, + the header row) only while bar rows are drawn: a header-only
    // table never claims rows it does not have.
    const rowCount = this.live.size === 0 ? "" : String(Math.max(0, barCount) + 1);
    if (rowCount !== this.rowCount) {
      this.rowCount = rowCount;
      if (rowCount === "") this.table.removeAttribute("aria-rowcount");
      else this.table.setAttribute("aria-rowcount", rowCount);
    }
    this.counters.mirrorNodes = FIXED_NODES + this.live.size * (1 + HEADERS.length);
    this.rollLabel(w, rows, barCount);
    this.counters.mirrorUpdateMs = this.deps.now() - t0;
  }

  /** Removes the table and stops the label timer. Idempotent. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.cancelLabel?.();
    this.cancelLabel = null;
    this.table.remove();
    this.live.clear();
    this.free.length = 0;
  }

  /** Moves the pool to bars [first, first + count): kept rows keep their nodes (D2). */
  private place(first: number, count: number): void {
    const end = first + count;
    const overlaps = this.count > 0 && first < this.first + this.count && this.first < end;
    if (this.count > 0 && count > 0 && !overlaps) this.counters.mirrorRewindows += 1;
    // The live keys are exactly [this.first, this.first + this.count): an index walk, no iterator.
    for (let bar = this.first, prevEnd = this.first + this.count; bar < prevEnd; bar += 1) {
      if (bar >= first && bar < end) continue;
      const row = this.live.get(bar);
      if (row === undefined) continue;
      row.tr.remove();
      this.live.delete(bar);
      this.free.push(row);
    }
    const kept = overlaps ? (this.live.get(Math.max(first, this.first))?.tr ?? null) : null;
    for (let bar = first; bar < end; bar += 1) {
      if (this.live.has(bar)) continue;
      const row = this.free.pop() ?? this.makeRow();
      row.bar = bar;
      row.tr.setAttribute("aria-rowindex", String(bar + 2));
      if (kept !== null && bar < this.first) this.body.insertBefore(row.tr, kept);
      else this.body.appendChild(row.tr);
      this.live.set(bar, row);
    }
    this.first = first;
    this.count = count;
  }

  private makeRow(): Row {
    const tr = this.deps.createElement("tr");
    const cells: MirrorNode[] = [];
    for (let i = 0; i < HEADERS.length; i += 1) {
      // D4: the time cell is the row header (05 §6.3), so each value is announced with its bar.
      const cell = this.deps.createElement(i === 0 ? "th" : "td");
      if (i === 0) cell.setAttribute("scope", "row");
      tr.appendChild(cell);
      cells.push(cell);
    }
    const vals = new Float64Array(HEADERS.length).fill(Number.NaN);
    return { tr, cells, text: HEADERS.map(() => ""), vals, gen: -1, bar: -1 };
  }

  private fill(r: A11yRows): void {
    const fmtChanged =
      r.priceOrigin !== this.fmtOrigin ||
      r.tickSize !== this.fmtTick ||
      r.priceDecimals !== this.fmtDecimals;
    if (fmtChanged) this.gen += 1;
    this.fmtOrigin = r.priceOrigin;
    this.fmtTick = r.tickSize;
    this.fmtDecimals = r.priceDecimals;
    for (let i = 0; i < r.count; i += 1) {
      const row = this.live.get(r.firstBar + i);
      if (row === undefined) continue;
      if (row.gen !== this.gen) {
        row.gen = this.gen;
        row.vals.fill(Number.NaN);
      }
      // Each cell formats only when its raw value changed (NaN never matches: the first fill).
      const v = row.vals;
      const t = r.time[i] ?? 0;
      if (v[0] !== t) this.cell(row, 0, t, this.time.format(Math.floor(t / 1000)));
      const o = r.open[i] ?? 0;
      if (v[1] !== o) this.cell(row, 1, o, this.price(r, o));
      const h = r.high[i] ?? 0;
      if (v[2] !== h) this.cell(row, 2, h, this.price(r, h));
      const l = r.low[i] ?? 0;
      if (v[3] !== l) this.cell(row, 3, l, this.price(r, l));
      const c = r.close[i] ?? 0;
      if (v[4] !== c) this.cell(row, 4, c, this.price(r, c));
      const vol = r.volume[i] ?? 0;
      if (v[5] !== vol) this.cell(row, 5, vol, this.qty.format(vol));
      const d = r.delta[i] ?? 0;
      if (v[6] !== d) this.cell(row, 6, d, this.signed.format(d));
    }
  }

  private price(r: A11yRows, ticks: number | undefined): string {
    return (r.priceOrigin + (ticks ?? 0) * r.tickSize).toFixed(r.priceDecimals);
  }

  /** textContent only, and only when the text changed (an unchanged cell is never written). */
  private cell(row: Row, i: number, raw: number, text: string): void {
    row.vals[i] = raw;
    if (row.text[i] === text) return;
    row.text[i] = text;
    const td = row.cells[i];
    if (td !== undefined) td.textContent = text;
  }

  private mark(row: Row | null): void {
    if (row === this.current) return;
    this.current?.tr.removeAttribute("aria-current");
    row?.tr.setAttribute("aria-current", "true");
    this.current = row;
  }

  /**
   * D06 L-1 without the symbol and interval prefix (PR-3's copy), at the R-6 cadence. The last
   * close is the latest loaded bar's, named only while that bar is in the rows: the label never
   * claims a value it does not have (D06 §8); a latest-bar field for a distant cursor is PR-3's.
   */
  private rollLabel(w: A11yWindow, rows: A11yRows | null, barCount: number): void {
    const n = Math.max(0, w.viewLastBar - w.viewFirstBar + 1);
    const at = rows === null ? -1 : barCount - 1 - rows.firstBar;
    const known = rows !== null && at >= 0 && at < rows.count;
    const close = known ? (rows.close[at] ?? 0) : Number.NaN;
    const delta = known ? (rows.delta[at] ?? 0) : Number.NaN;
    // Built only when an input changed (the gen covers a price-format change); one string per
    // changed cell, no per-frame closure.
    const same =
      n === this.labelN &&
      Object.is(close, this.labelClose) &&
      Object.is(delta, this.labelDelta) &&
      this.labelGen === this.gen;
    if (!same) {
      this.labelN = n;
      this.labelClose = close;
      this.labelDelta = delta;
      this.labelGen = this.gen;
      const tail = known
        ? `, last close ${this.price(rows, close)}, delta ${this.signed.format(delta)}`
        : "";
      this.label = `${n} bars visible${tail}`;
    }
    if (this.label === this.labelShown || this.cancelLabel !== null) return;
    const wait = this.labelAt + this.cadence - this.deps.now();
    if (wait <= 0) this.showLabel();
    else this.cancelLabel = this.deps.setTimer(() => this.showLabel(), wait);
  }

  private showLabel(): void {
    this.cancelLabel = null;
    if (this.disposed || this.label === this.labelShown) return;
    this.labelShown = this.label;
    this.labelAt = this.deps.now();
    this.deps.setCanvasLabel(this.label);
  }
}
