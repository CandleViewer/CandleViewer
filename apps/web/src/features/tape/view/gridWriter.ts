// E22-S01 (#714) PR-B: the tape's windowed grid writer (C-70, RULED: a feature-local writer on
// CMP-049's tokens and row anatomy; rows never pass through React). A fixed pool of at most 60 row
// nodes is created once; each animation frame rewrites in one pass only the slots whose print,
// state or divider text changed (D4-01, S01-u-01). Rows are written in place: no transform,
// translate, transition or animation is ever set on a row or the list (D4-01..D4-09, S01-u-04), so
// reduced motion renders the same frames (S01-u-05). The tier state is set with the row's print in
// its first frame and never changes while that print is shown (D4-02, S01-u-02).
import { BLOCK_TAG, LIQ_TAG, clusterTag } from "../copy";
import {
  baseAsset,
  formatDecimal,
  formatNotional,
  formatTime,
  rowName,
  sideWord,
  splitTime,
  type TapeTier,
} from "../format";
import type { Cursor, DisplayList } from "../model/displayList";
import { newCursor } from "../model/displayList";
import {
  FLAG_BIG,
  FLAG_BLOCK,
  FLAG_LIQUIDATION,
  SIDE_BUY,
  type TapeRing,
  type TapeSide,
} from "../model/ring";

/** SCR-053 (`14`:1258), D02 §15: at most 60 row nodes, the dividers and the header included. */
export const MAX_DOM_ROWS = 60;
/** The pool: every node a print or a divider row, beside the one column-header row. */
export const POOL_SIZE = MAX_DOM_ROWS - 1;
/** `size.row.compact` (D02 §2; compact is the default). */
export const ROW_HEIGHT_PX = 24;
/** The rows kept above the viewport while scrolled; the rest of the pool is below (D02 §2). */
const OVERSCAN_ABOVE = 10;
export const COLUMN_COUNT = 5;

/** Tier 1 from the server's `is_big_trade` only (BQ-210); tier 2 is E22-S02's to inject. */
export type TierOf = (flags: number) => TapeTier;
export const serverTier: TierOf = (flags) => ((flags & FLAG_BIG) !== 0 ? 1 : 0);

interface Slot {
  readonly row: HTMLDivElement;
  readonly cells: readonly HTMLDivElement[];
  readonly prefix: HTMLSpanElement;
  readonly rest: HTMLSpanElement;
  readonly sideGlyph: HTMLSpanElement;
  readonly price: HTMLSpanElement;
  readonly size: HTMLSpanElement;
  readonly tierGlyph: HTMLSpanElement;
  readonly notional: HTMLDivElement;
  readonly word: HTMLSpanElement;
  readonly tags: HTMLSpanElement;
  readonly divider: HTMLSpanElement;
  /** Each text-bearing node's one Text child, created once: a write sets its `data` (BQ-215). */
  readonly nodes: SlotText;
  readonly written: Written;
  key: number;
  state: number;
  text: string;
  shown: boolean;
  isDivider: boolean;
}

/**
 * The slot's Text nodes. Writing `Text.data` keeps the node and its layout object and only marks
 * the text dirty; `textContent =` would remove the node and insert a new one, so every print would
 * rebuild its layout objects. That rebuild was the ingest frame's cost at 2 000 prints/s (BQ-215).
 */
type SlotText = Readonly<
  Record<
    | "prefix"
    | "rest"
    | "sideGlyph"
    | "price"
    | "size"
    | "tierGlyph"
    | "notional"
    | "word"
    | "tags"
    | "divider",
    Text
  >
>;

/** Sets a Text node's data only when it differs (no mutation record, no relayout otherwise). */
const setText = (node: Text, value: string): void => {
  if (node.data !== value) node.data = value;
};

export interface RenderInput {
  /** The display index at the window's top. */
  readonly first: number;
  /** The roving cursor's item key, or `null` (no row active). */
  readonly activeKey: number | null;
  readonly activeCol: number;
  /** The active row is selected (a located print; released by `Esc` in a hard pause, P13). */
  readonly selected: boolean;
  /** The grid holds DOM focus: the active cell shows the focus ring (D4-09). */
  readonly focused: boolean;
  /**
   * The most slots to show, `POOL_SIZE` when omitted. Live, the controller passes the viewport's
   * rows plus a small overscan: every 100 ms window replaces every shown print, so each row kept
   * below the fold is pure layout cost on the ingest frame (BQ-215).
   */
  readonly limit?: number;
}

export interface RenderStats {
  /** Slots rewritten this frame. */
  readonly written: number;
  /** Row nodes shown (dividers included), at most `MAX_DOM_ROWS`. */
  readonly shown: number;
  /** The oldest ring `seq` in the window, or -1: the paused window's pin (S22, D02-G7). */
  readonly oldestSeqShown: number;
}

/** A print's display strings, made once per ring print. */
interface PrintTexts {
  readonly prefix: string;
  readonly rest: string;
  readonly price: string;
  readonly size: string;
  readonly notional: string;
  readonly tags: string;
  readonly label: string;
}

/** What a slot last wrote, so a frame touches only what changed. */
interface Written {
  rowIndex: number;
  label: string;
  selected: boolean;
  /** tier * 4 + buy * 2 + selected: a number, so no string is built per written row. */
  look: number;
  tier: number;
  side: string;
  accent: string;
  background: string;
  prefixColor: string;
  hue: string;
  weight: string;
  ringCol: number;
}

const freshWritten = (): Written => ({
  rowIndex: -1,
  label: "",
  selected: false,
  look: -1,
  tier: -1,
  side: "",
  accent: "",
  background: "",
  prefixColor: "",
  hue: "",
  weight: "",
  ringCol: -1,
});

interface PrintFields {
  tsMs: number;
  price: string;
  size: string;
  side: TapeSide;
  flags: number;
  clusterSize: number;
  priceNum: number;
  sizeNum: number;
}

const ACCENT = ["transparent", "var(--color-buy-default)", "var(--color-sell-default)"] as const;
const WEIGHT = [
  "var(--font-weight-regular)",
  "var(--font-weight-medium)",
  "var(--font-weight-bold)",
] as const;

const css = (el: HTMLElement, styles: Readonly<Record<string, string>>): void => {
  for (const [k, v] of Object.entries(styles)) el.style.setProperty(k, v);
};

export class GridWriter {
  private readonly slots: Slot[] = [];
  private readonly cursor: Cursor = newCursor();
  private readonly fields: PrintFields = {
    tsMs: 0,
    price: "",
    size: "",
    side: SIDE_BUY,
    flags: 0,
    clusterSize: 1,
    priceNum: 0,
    sizeNum: 0,
  };
  private lastFirst = -1;
  private lastTotal = -1;
  private lastRowCount = -1;
  private lastActiveId: string | null = null;
  /** `render`'s result, reused: read it before the next call (no object per frame). */
  private readonly stats: { written: number; shown: number; oldestSeqShown: number } = {
    written: 0,
    shown: 0,
    oldestSeqShown: -1,
  };
  private readonly base: string;
  private readonly cache: (PrintTexts | undefined)[];
  private readonly cachedSeq: Float64Array;
  private readonly cachedTier: Int8Array;

  constructor(
    private readonly grid: HTMLElement,
    private readonly body: HTMLElement,
    private readonly windowEl: HTMLElement,
    private readonly ring: TapeRing,
    symbol: string,
    private readonly idBase: string,
    private readonly tierOf: TierOf = serverTier,
  ) {
    this.base = baseAsset(symbol);
    this.cache = new Array<PrintTexts | undefined>(ring.capacity).fill(undefined);
    this.cachedSeq = new Float64Array(ring.capacity).fill(-1);
    this.cachedTier = new Int8Array(ring.capacity);
    const doc = windowEl.ownerDocument;
    const fragment = doc.createDocumentFragment();
    for (let p = 0; p < POOL_SIZE; p += 1) {
      const slot = this.createSlot(doc, p);
      this.slots.push(slot);
      fragment.append(slot.row);
    }
    windowEl.append(fragment);
  }

  /** The id of the cell `col` of slot `p` (the `aria-activedescendant` target). */
  cellId(p: number, col: number): string {
    return `${this.idBase}-r${p}-c${col}`;
  }

  /** How many slots the window shows for `list` at `first`. */
  static windowSize(total: number, first: number, limit: number = POOL_SIZE): number {
    return Math.max(0, Math.min(POOL_SIZE, limit, total - first));
  }

  /** The window's first display index for a scroll position (D02 §2's overscan). */
  static firstFor(scrollTop: number, total: number): number {
    const top = Math.floor(Math.max(0, scrollTop) / ROW_HEIGHT_PX);
    return Math.max(0, Math.min(top - OVERSCAN_ABOVE, total - POOL_SIZE));
  }

  private createSlot(doc: Document, p: number): Slot {
    const row = doc.createElement("div");
    row.setAttribute("role", "row");
    row.id = `${this.idBase}-r${p}`;
    css(row, {
      display: "none",
      "align-items": "center",
      height: `${ROW_HEIGHT_PX}px`,
      "box-sizing": "border-box",
      "border-left": "2px solid transparent",
      "padding-inline": "calc(var(--space-3) - 2px) var(--space-3)",
      gap: "var(--space-2)",
      "white-space": "nowrap",
      overflow: "hidden",
      cursor: "default",
    });
    const cell = (col: number, styles: Readonly<Record<string, string>>): HTMLDivElement => {
      const c = doc.createElement("div");
      c.setAttribute("role", "gridcell");
      c.id = this.cellId(p, col);
      css(c, { "outline-offset": "-2px", "min-width": "0", overflow: "clip", ...styles });
      row.append(c);
      return c;
    };
    const span = (parent: HTMLElement, hidden = false): HTMLSpanElement => {
      const s = doc.createElement("span");
      if (hidden) s.setAttribute("aria-hidden", "true");
      parent.append(s);
      return s;
    };
    const time = cell(0, { flex: "0 0 12ch" });
    const prefix = span(time);
    const rest = span(time);
    const priceCell = cell(1, { flex: "0 0 11ch", "text-align": "right" });
    const sideGlyph = span(priceCell, true);
    sideGlyph.style.setProperty("margin-inline-end", "var(--space-1)");
    const price = span(priceCell);
    const sizeCell = cell(2, { flex: "0 0 8ch", "text-align": "right" });
    const size = span(sizeCell);
    const tierGlyph = span(sizeCell, true);
    css(tierGlyph, { display: "inline-block", width: "1ch", "margin-inline-start": "2px" });
    const notional = cell(3, { flex: "0 0 7ch", "text-align": "right" });
    const sideCell = cell(4, { flex: "1 1 0%", "text-align": "left" });
    const word = span(sideCell);
    const tags = span(sideCell);
    css(tags, {
      color: "var(--color-text-secondary)",
      "margin-inline-start": "var(--space-1)",
    });
    // a divider is the same node as `presentation` with its cells hidden: never focusable (D3)
    const divider = doc.createElement("span");
    css(divider, {
      display: "none",
      flex: "1 1 auto",
      "text-align": "center",
      color: "var(--color-text-secondary)",
      overflow: "hidden",
    });
    row.append(divider);
    const textIn = (parent: HTMLElement): Text => parent.appendChild(doc.createTextNode(""));
    const nodes: SlotText = {
      prefix: textIn(prefix),
      rest: textIn(rest),
      sideGlyph: textIn(sideGlyph),
      price: textIn(price),
      size: textIn(size),
      tierGlyph: textIn(tierGlyph),
      notional: textIn(notional),
      word: textIn(word),
      tags: textIn(tags),
      divider: textIn(divider),
    };
    return {
      row,
      cells: [time, priceCell, sizeCell, notional, sideCell],
      prefix,
      rest,
      sideGlyph,
      price,
      size,
      tierGlyph,
      notional,
      word,
      tags,
      divider,
      nodes,
      written: freshWritten(),
      key: Number.NaN,
      state: -1,
      text: "",
      shown: false,
      isDivider: false,
    };
  }

  /** Writes the window for `list` in one pass; returns what it did (one reused object). */
  render(list: DisplayList, input: RenderInput): RenderStats {
    const total = list.length;
    const first = Math.max(0, Math.min(input.first, Math.max(0, total - 1)));
    const count = GridWriter.windowSize(total, first, input.limit);
    let written = 0;
    let oldestSeqShown = -1;
    let activeId: string | null = null;
    if (total !== this.lastTotal) {
      this.body.style.setProperty("height", `${total * ROW_HEIGHT_PX}px`);
      this.lastTotal = total;
    }
    if (first !== this.lastFirst) {
      this.windowEl.style.setProperty("top", `${first * ROW_HEIGHT_PX}px`);
      this.lastFirst = first;
    }
    if (list.rowCount !== this.lastRowCount) {
      this.grid.setAttribute("aria-rowcount", String(list.rowCount + 1));
      this.lastRowCount = list.rowCount;
    }
    for (let p = 0; p < POOL_SIZE; p += 1) {
      const slot = this.slots[p] as Slot;
      if (p >= count) {
        if (slot.shown) {
          slot.row.style.setProperty("display", "none");
          slot.shown = false;
          slot.key = Number.NaN;
          written += 1;
        }
        continue;
      }
      const c = this.cursor;
      list.at(first + p, c);
      if (c.kind === "divider") {
        const text = c.divider?.text ?? "";
        if (!slot.shown || !slot.isDivider || slot.text !== text || slot.key !== c.key) {
          this.setDividerMode(slot, true);
          slot.row.style.setProperty("display", "flex");
          setText(slot.nodes.divider, text);
          slot.text = text;
          slot.key = c.key;
          slot.isDivider = true;
          slot.shown = true;
          slot.state = -1;
          written += 1;
        }
        continue;
      }
      if (c.kind === "row") {
        if (oldestSeqShown === -1 || c.seq < oldestSeqShown) oldestSeqShown = c.seq;
      }
      const active = input.activeKey !== null && c.key === input.activeKey;
      const state = active
        ? 1 + (input.selected ? 2 : 0) + (input.focused ? 4 : 0) + input.activeCol * 8
        : 0;
      if (active) activeId = this.cellId(p, input.activeCol);
      if (slot.shown && !slot.isDivider && slot.key === c.key && slot.state === state) {
        // the cached index, not a DOM read or a string per frame (no per-frame allocation)
        if (slot.written.rowIndex !== c.rowIndex + 1) {
          slot.written.rowIndex = c.rowIndex + 1;
          slot.row.setAttribute("aria-rowindex", String(c.rowIndex + 1));
        }
        continue;
      }
      if (!this.read(c)) continue;
      this.writeRow(slot, c, state, input);
      written += 1;
    }
    if (activeId !== this.lastActiveId) {
      if (activeId === null) this.grid.removeAttribute("aria-activedescendant");
      else this.grid.setAttribute("aria-activedescendant", activeId);
      this.lastActiveId = activeId;
    }
    const stats = this.stats;
    stats.written = written;
    stats.shown = count;
    stats.oldestSeqShown = oldestSeqShown;
    return stats;
  }

  /** Turns a slot into a divider (`presentation`, cells hidden) or back into a print row. */
  private setDividerMode(slot: Slot, divider: boolean): void {
    const row = slot.row;
    if (divider) {
      row.setAttribute("role", "presentation");
      for (const a of ["aria-rowindex", "aria-label", "aria-selected"]) row.removeAttribute(a);
      row.style.setProperty("border-left-color", "transparent");
      row.style.setProperty("background", "var(--color-surface-raised)");
    } else row.setAttribute("role", "row");
    Object.assign(slot.written, freshWritten());
    for (const cell of slot.cells) {
      cell.style.setProperty("display", divider ? "none" : "");
      cell.style.removeProperty("outline");
    }
    slot.divider.style.setProperty("display", divider ? "block" : "none");
  }

  private read(c: Cursor): boolean {
    const f = this.fields;
    if (c.kind === "row") {
      const ring = this.ring;
      if (!ring.has(c.seq)) return false;
      const i = ring.slot(c.seq);
      f.tsMs = ring.tsMs[i] ?? 0;
      f.price = ring.priceText(c.seq);
      f.size = ring.sizeText(c.seq);
      f.side = ring.side[i] === SIDE_BUY ? SIDE_BUY : 1;
      f.flags = ring.flags[i] ?? 0;
      f.clusterSize = ring.clusterSize[i] ?? 1;
      f.priceNum = ring.price[i] ?? 0;
      f.sizeNum = ring.size[i] ?? 0;
      return true;
    }
    const e = c.extra;
    if (e === null) return false;
    f.tsMs = e.tsMs;
    f.price = e.price;
    f.size = e.size;
    f.side = e.side;
    f.flags = e.flags;
    f.clusterSize = e.clusterSize;
    f.priceNum = Number(e.price);
    f.sizeNum = Number(e.size);
    return true;
  }

  /** The print's text, made once per ring print and reused while it scrolls (D4-01's budget). */
  private texts(c: Cursor, tier: TapeTier): PrintTexts {
    const f = this.fields;
    const ring = this.ring;
    const i = c.kind === "row" ? ring.slot(c.seq) : -1;
    if (i >= 0 && this.cachedSeq[i] === c.seq && this.cachedTier[i] === tier) {
      return this.cache[i] as PrintTexts;
    }
    const time = formatTime(f.tsMs);
    const notional = f.priceNum * f.sizeNum;
    const [prefix, rest] = splitTime(time);
    let tags = "";
    if (f.clusterSize > 1) tags = clusterTag(f.clusterSize);
    if ((f.flags & FLAG_LIQUIDATION) !== 0) tags = tags === "" ? LIQ_TAG : `${tags} ${LIQ_TAG}`;
    if ((f.flags & FLAG_BLOCK) !== 0) tags = tags === "" ? BLOCK_TAG : `${tags} ${BLOCK_TAG}`;
    const t: PrintTexts = {
      prefix,
      rest,
      price: formatDecimal(f.price),
      size: formatDecimal(f.size),
      notional: formatNotional(notional),
      tags,
      label: rowName({
        side: f.side,
        size: f.size,
        base: this.base,
        price: f.price,
        notional,
        tier,
        time,
        clusterSize: f.clusterSize,
        liquidation: (f.flags & FLAG_LIQUIDATION) !== 0,
        block: (f.flags & FLAG_BLOCK) !== 0,
      }),
    };
    if (i >= 0) {
      this.cache[i] = t;
      this.cachedSeq[i] = c.seq;
      this.cachedTier[i] = tier;
    }
    return t;
  }

  private writeRow(slot: Slot, c: Cursor, state: number, input: RenderInput): void {
    const f = this.fields;
    const tier = this.tierOf(f.flags);
    const buy = f.side === SIDE_BUY;
    const selected = (state & 2) !== 0;
    const t = this.texts(c, tier);
    const row = slot.row;
    const w = slot.written;
    if (slot.isDivider || !slot.shown) {
      this.setDividerMode(slot, false);
      row.style.setProperty("display", "flex");
    }
    // only what differs from the slot's last write is touched: one pass, no redundant DOM work
    if (w.rowIndex !== c.rowIndex + 1) {
      w.rowIndex = c.rowIndex + 1;
      row.setAttribute("aria-rowindex", String(w.rowIndex));
    }
    if (w.label !== t.label) row.setAttribute("aria-label", (w.label = t.label));
    if (w.selected !== selected) {
      if (selected) row.setAttribute("aria-selected", "true");
      else row.removeAttribute("aria-selected");
      w.selected = selected;
    }
    const look = tier * 4 + (buy ? 2 : 0) + (selected ? 1 : 0);
    if (w.look !== look) {
      w.look = look;
      // each property is written only when its value changes: a side flip on a tier-0 row touches
      // the glyph, its hue and the word, not the row's fill, accent or weights (BQ-215)
      const side = buy ? "buy" : "sell";
      if (w.tier !== tier) row.dataset["tier"] = String((w.tier = tier));
      if (w.side !== side) row.dataset["side"] = w.side = side;
      // the hue rides on the glyphs, the accent and the tier-2 fill only (D02 §3)
      const hue = buy ? "var(--color-buy-default)" : "var(--color-sell-default)";
      const accent = tier === 0 ? ACCENT[0] : hue;
      if (w.accent !== accent) row.style.setProperty("border-left-color", (w.accent = accent));
      const background = selected
        ? "var(--color-surface-selected)"
        : tier === 2
          ? buy
            ? "var(--color-buy-subtle)"
            : "var(--color-sell-subtle)"
          : "var(--color-surface-raised)";
      if (w.background !== background) {
        row.style.setProperty("background", (w.background = background));
      }
      // the `HH:MM:` prefix is dimmed on tiers 0-1, never on a tier-2 band or the selected row (D7)
      const prefixColor =
        tier === 2 || selected ? "var(--color-text-primary)" : "var(--color-text-tertiary)";
      if (w.prefixColor !== prefixColor) {
        slot.prefix.style.setProperty("color", (w.prefixColor = prefixColor));
      }
      if (w.hue !== hue) {
        w.hue = hue;
        slot.sideGlyph.style.setProperty("color", hue);
        slot.tierGlyph.style.setProperty("color", hue);
      }
      const weight = WEIGHT[tier];
      if (w.weight !== weight) {
        w.weight = weight;
        slot.size.style.setProperty("font-weight", weight);
        slot.notional.style.setProperty("font-weight", weight);
      }
      setText(slot.nodes.sideGlyph, buy ? "▲" : "▼");
      setText(slot.nodes.tierGlyph, tier === 1 ? "●" : tier === 2 ? "◆" : "");
      setText(slot.nodes.word, sideWord(f.side));
    }
    setText(slot.nodes.prefix, t.prefix);
    setText(slot.nodes.rest, t.rest);
    setText(slot.nodes.price, t.price);
    setText(slot.nodes.size, t.size);
    setText(slot.nodes.notional, t.notional);
    setText(slot.nodes.tags, t.tags);
    const ringCol = (state & 1) !== 0 && input.focused ? input.activeCol : -1;
    if (w.ringCol !== ringCol) {
      if (w.ringCol >= 0) slot.cells[w.ringCol]?.style.removeProperty("outline");
      if (ringCol >= 0) {
        slot.cells[ringCol]?.style.setProperty("outline", "2px solid var(--color-focus-ring)");
      }
      w.ringCol = ringCol;
    }
    slot.key = c.key;
    slot.state = state;
    slot.isDivider = false;
    slot.shown = true;
  }
}
