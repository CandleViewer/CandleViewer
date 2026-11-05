// The pane chrome (E11-S09 PR 1b; E11-D02 §8, §12; ruling 6623589909 on BQ-11): DOM over the
// stacked panes, placed from the worker's `layout` message. One focusable `role="separator"` per
// boundary, named by the two panes it divides, with `aria-valuenow` the pane above's share (a
// percent) and `aria-valuetext` naming both. Its keys go to the worker: `↑` / `↓` move the boundary
// 2 % (`Shift` 10 %; `↓` shrinks the pane above, the ticket's AC), `End` gives the pane above the
// most the pane below can give, `Home` equal shares, `Esc` back to the chart; only the two
// adjacent panes change. Every key is announced once, from the `layout` the worker posts after it
// (never per frame), as is a collapse or a restore: `candleviewer:announce` under `chart:pane`,
// on the axis stops' cadence; the engine owns no live region. The rest hairline is the grid
// ring's (one draw); the grip, the focus ring, the collapse chevrons and the collapsed stubs are
// DOM. Pointers pass through the bands to the canvas, where the worker drags the splitter (the
// band takes only a pointer-down); hovering a band sets the `row-resize` cursor and the D02 §8
// hover colours, a drag the drag colour, and a click in a band (under 3 px of travel) focuses
// its separator, the non-drag path of WCAG 2.5.7 (05 §3.1 item 8). Each key carries a `seq` the
// worker echoes as the `layout`'s `ack`, so only that layout announces it. Each pane is an
// `aria-label`led region in the DOM mirror. DOM program: it reaches the document via the container.
import { SPLITTER_BAND_PX } from "../scene/layout-engine.js";
import type { Command, FromWorker, PaneRow } from "../worker/protocol.js";
import { type AnnounceClock, createAnnouncer } from "./axis-stop.js";

export type LayoutMessage = Extract<FromWorker, { t: "layout" }>;

/** The shell announcer's key for pane changes (each message replaces the last). */
export const PANE_ANNOUNCE_KEY = "chart:pane";
/** E11-D02 §8: `↑` / `↓` move the boundary by 2 % of the stack, `Shift` by 10 %. */
export const SPLITTER_STEP = 0.02;
export const SPLITTER_BIG_STEP = 0.1;
/** E11-D02 §12: a control's target, 24 × 24 CSS px. */
const TARGET_PX = 24;
/** WCAG 2.5.7: a pointer-down and -up in a band less than this far apart is a click, not a drag. */
const CLICK_SLOP_PX = 3;
/** BQ-15: a pane label's cap, in characters, after trimming and collapsing whitespace. */
export const PANE_LABEL_MAX = 64;

/**
 * BQ-15: the host's `PaneOptions.label`, trimmed, whitespace collapsed and capped at
 * `PANE_LABEL_MAX` characters; `fallback` when nothing is left or it is not a string.
 */
export function paneLabel(raw: unknown, fallback: string): string {
  if (typeof raw !== "string") return fallback;
  const chars = Array.from(raw.replace(/\s+/g, " ").trim());
  return chars.length === 0 ? fallback : chars.slice(0, PANE_LABEL_MAX).join("").trimEnd();
}

export interface PaneChromeSink {
  command(cmd: Command): void;
}

export interface PaneChrome {
  /** The separators, in boundary order (read by tests and by E11-S13's Tab order). */
  readonly separators: readonly HTMLElement[];
  /** Applies a worker `layout`: places the chrome and announces a key's result or a collapse. */
  update(msg: LayoutMessage): void;
  setTheme(colors: Readonly<Record<string, string>>): void;
  dispose(): void;
}

interface RowChrome {
  readonly region: HTMLElement;
  readonly collapse: HTMLButtonElement;
  readonly stub: HTMLElement;
  readonly name: HTMLElement;
  readonly word: HTMLElement;
  readonly restore: HTMLButtonElement;
}

const Pending = { none: 0, step: 1, end: 2, home: 3 } as const;
const pct = (share: number): number => Math.round(share * 100);

export function createPaneChrome(
  container: HTMLElement,
  mirrorRoot: HTMLElement,
  sink: PaneChromeSink,
  labelOf: (pane: number) => string,
  colors: Readonly<Record<string, string>>,
  clock: AnnounceClock,
  compact: () => boolean = () => false,
): PaneChrome {
  const doc = container.ownerDocument;
  let theme = colors;
  let rows: readonly PaneRow[] = [];
  let pending: number = Pending.none;
  let pendingSep = -1;
  let seq = 0; // the last key's `seq`; the worker's `layout.ack` names the one it answers
  let hot = -1; // the band under the pointer (hover colours)
  let held = -1; // the band a pointer-down started in (drag colour; a click focuses it)
  let downX = 0;
  let downY = 0;
  const say = createAnnouncer(container, clock, PANE_ANNOUNCE_KEY);
  const separators: HTMLElement[] = [];
  const grips: HTMLElement[] = [];
  const lines: HTMLElement[] = [];
  const chrome: RowChrome[] = [];
  const color = (token: string): string => theme[token] ?? "";
  const div = (parent: HTMLElement): HTMLElement => parent.appendChild(doc.createElement("div"));
  const button = (parent: HTMLElement, onPress: () => void): HTMLButtonElement => {
    const b = parent.appendChild(doc.createElement("button"));
    b.setAttribute("type", "button");
    Object.assign(b.style, { minWidth: `${TARGET_PX}px`, height: `${TARGET_PX}px` });
    b.style.pointerEvents = "auto";
    b.addEventListener("click", onPress); // Enter and Space press a native button
    return b;
  };
  const collapse = (i: number, collapsed: boolean): void => {
    const row = rows[i];
    if (row !== undefined) sink.command({ k: "setPaneCollapsed", pane: row.pane, collapsed });
  };

  function separator(i: number): HTMLElement {
    const el = div(container);
    el.setAttribute("role", "separator");
    el.setAttribute("aria-orientation", "horizontal");
    el.setAttribute("tabindex", "0");
    el.setAttribute("data-cv-splitter", String(i));
    Object.assign(el.style, { position: "absolute", left: "0px", right: "0px" });
    el.style.height = `${SPLITTER_BAND_PX}px`;
    el.style.pointerEvents = "none"; // the worker drags it; hover and the crosshair pass through
    el.style.outline = "none";
    const line = div(el); // the focus hairline; at rest the grid ring draws it
    Object.assign(line.style, { position: "absolute", left: "0px", right: "0px", height: "1px" });
    line.style.top = `${SPLITTER_BAND_PX / 2}px`;
    const grip = div(el);
    Object.assign(grip.style, { position: "absolute", left: "50%", height: "4px" });
    grip.style.top = `${SPLITTER_BAND_PX / 2 - 2}px`;
    grip.style.borderRadius = "9999px"; // `radius.pill`
    el.addEventListener("focus", () => state(i));
    el.addEventListener("blur", () => state(i));
    el.addEventListener("keydown", (e) => onKey(e, i));
    grips.push(grip);
    lines.push(line);
    state(i, el);
    return el;
  }

  /**
   * D02 §8's splitter states on separator `i`: rest (grip `color.text.tertiary`, the ≥ 3:1
   * boundary; the grid ring draws the hairline), hover (grip `color.text.secondary`, hairline
   * `color.border.strong`), drag (grip `color.focus.ring`) and focus (CMP-039 around the grip,
   * hairline `color.focus.ring`). Also the repaint on a theme switch.
   */
  function state(i: number, el = separators[i]): void {
    const [grip, line] = [grips[i], lines[i]];
    if (grip === undefined || line === undefined) return;
    const focused = el !== undefined && doc.activeElement === el;
    const ring = color("color.focus.ring");
    grip.style.background = color(
      held === i ? "color.focus.ring" : hot === i ? "color.text.secondary" : "color.text.tertiary",
    );
    grip.style.outline = focused ? `2px solid ${ring}` : "none";
    line.style.background = focused
      ? ring
      : hot === i || held === i
        ? color("color.border.strong")
        : "transparent";
  }

  function onKey(e: KeyboardEvent, i: number): void {
    const above = rows[i];
    if (above === undefined) return;
    const step = e.shiftKey ? SPLITTER_BIG_STEP : SPLITTER_STEP;
    if (e.key === "ArrowUp" || e.key === "ArrowDown" || e.key === "End") {
      const by = e.key === "End" ? 1 : e.key === "ArrowUp" ? step : -step;
      seq += 1;
      sink.command({ k: "moveSplitter", pane: above.pane, by, seq });
      [pending, pendingSep] = [e.key === "End" ? Pending.end : Pending.step, i];
    } else if (e.key === "Home") {
      const open = rows.filter((r) => !r.collapsed);
      seq += 1;
      const shares = open.map((r): [number, number] => [r.pane, 1 / open.length]);
      sink.command({ k: "setPaneShares", shares, seq });
      pending = Pending.home;
    } else if (e.key === "Escape")
      container.focus({ preventScroll: true }); // G-S09g
    else return; // Tab and the page's own keys pass
    e.preventDefault();
    e.stopPropagation(); // the chart's plot keys never see a splitter key
  }

  function rowChrome(): RowChrome {
    const i = chrome.length;
    const region = div(mirrorRoot);
    region.setAttribute("role", "region");
    const fold = button(container, () => collapse(i, true));
    fold.textContent = "\u25B4"; // the chevron; its name is the label
    Object.assign(fold.style, { position: "absolute", left: "4px" });
    const stub = div(container);
    Object.assign(stub.style, { position: "absolute", left: "0px", right: "0px", display: "none" });
    const name = div(stub);
    const word = div(stub);
    word.textContent = "collapsed";
    const restore = button(stub, () => collapse(i, false));
    restore.textContent = "Restore";
    for (const el of [name, word, restore]) el.style.display = "inline-block";
    return { region, collapse: fold, stub, name, word, restore };
  }

  function paint(c: RowChrome, row: PaneRow, label: string, open: number): void {
    c.region.setAttribute("aria-label", label);
    const s = c.stub.style;
    s.display = row.collapsed ? "block" : "none";
    Object.assign(s, { top: `${row.top}px`, height: `${row.height}px` });
    s.background = color("color.surface.raised");
    c.name.textContent = label;
    c.name.style.color = color("color.text.primary");
    c.word.style.color = color("color.text.secondary");
    c.restore.setAttribute("aria-label", `Restore ${label}`);
    // The last open pane never folds (BQ-11): its chevron goes rather than refusing silently.
    c.collapse.style.display = row.collapsed || open < 2 ? "none" : "block";
    c.collapse.style.top = `${row.top + 4}px`;
    c.collapse.setAttribute("aria-label", `Collapse ${label}`);
  }

  function aria(el: HTMLElement, grip: HTMLElement, a: PaneRow, b: PaneRow): void {
    const [la, lb] = [labelOf(a.pane), labelOf(b.pane)];
    el.setAttribute("aria-label", `Resize ${la} and ${lb}`);
    el.setAttribute("aria-valuemin", "0");
    el.setAttribute("aria-valuemax", String(pct(a.share + b.share)));
    el.setAttribute("aria-valuenow", String(pct(a.share)));
    // Beside a stub the share is 0: say "collapsed", as the stub does, never "0 percent".
    const part = (r: PaneRow, l: string): string =>
      r.collapsed ? `${l} collapsed` : `${l} ${pct(r.share)} percent`;
    el.setAttribute("aria-valuetext", `${part(a, la)}, ${part(b, lb)}`);
    el.style.top = `${a.top + a.height - SPLITTER_BAND_PX / 2}px`;
    const w = compact() ? 24 : 32; // D02:94
    Object.assign(grip.style, { width: `${w}px`, marginLeft: `${-w / 2}px` });
  }

  /**
   * One sentence per layout at most: a collapse or a restore first, else the key's result. A key
   * is answered only by the `layout` whose `ack` is its `seq`, which settles it either way.
   */
  function announcement(prev: readonly PaneRow[], ack: number | undefined): string | null {
    const kind = pending !== Pending.none && ack === seq ? pending : Pending.none;
    if (kind !== Pending.none) pending = Pending.none;
    for (const row of rows) {
      const was = prev.find((p) => p.pane === row.pane);
      if (was !== undefined && was.collapsed !== row.collapsed) {
        return `${labelOf(row.pane)} ${row.collapsed ? "collapsed" : "restored"}`;
      }
    }
    if (kind === Pending.home) return "Panes equal";
    const row = rows[kind === Pending.end ? pendingSep : pendingSep + 1];
    if (kind === Pending.none || row === undefined) return null;
    return `${labelOf(row.pane)} ${pct(row.share)} percent`;
  }

  const drop = (c: RowChrome | undefined): void => {
    c?.region.remove();
    c?.collapse.remove();
    c?.stub.remove();
  };

  /** The container's y of a pointer event: `offsetY` is the target's, a chevron's or a stub's. */
  const yOf = (e: PointerEvent): number => e.clientY - container.getBoundingClientRect().top;
  /** The separator whose band holds container y `y`, or -1. */
  const bandAt = (y: number): number => {
    for (let i = 0; i < rows.length - 1; i += 1) {
      const r = rows[i] as PaneRow;
      if (Math.abs(y - r.top - r.height) <= SPLITTER_BAND_PX / 2) return i;
    }
    return -1;
  };
  const setHot = (i: number): void => {
    if (i === hot) return;
    const was = hot;
    hot = i;
    state(was);
    state(i);
  };
  const onHover = (e: PointerEvent): void => {
    const i = held >= 0 ? held : bandAt(yOf(e));
    setHot(i);
    const cursor = i >= 0 ? "row-resize" : "";
    if (container.style.cursor !== cursor) container.style.cursor = cursor;
  };
  const onDown = (e: PointerEvent): void => {
    const y = yOf(e);
    held = bandAt(y);
    [downX, downY] = [e.clientX, e.clientY];
    state(held);
  };
  const onUp = (e: PointerEvent): void => {
    const i = held;
    if (i < 0) return;
    held = -1;
    const at = bandAt(yOf(e));
    setHot(at); // the band under the pointer now, not the one dragged
    state(i);
    const travel = Math.max(Math.abs(e.clientX - downX), Math.abs(e.clientY - downY));
    // 2.5.7: a click in the band selects the splitter; its arrow keys are the nudge.
    if (e.type === "pointerup" && travel < CLICK_SLOP_PX && at === i)
      separators[i]?.focus({ preventScroll: true });
  };
  container.addEventListener("pointermove", onHover, { passive: true });
  container.addEventListener("pointerdown", onDown, { passive: true });
  container.addEventListener("pointerup", onUp, { passive: true });
  container.addEventListener("pointercancel", onUp, { passive: true });

  return {
    separators,
    update(msg: LayoutMessage): void {
      const prev = rows;
      rows = msg.panes;
      const open = rows.filter((r) => !r.collapsed).length;
      while (chrome.length < rows.length) chrome.push(rowChrome());
      while (chrome.length > rows.length) drop(chrome.pop());
      for (let i = 0; i < rows.length; i += 1) {
        const row = rows[i] as PaneRow;
        paint(chrome[i] as RowChrome, row, labelOf(row.pane), open);
      }
      while (separators.length < rows.length - 1) separators.push(separator(separators.length));
      while (separators.length > Math.max(0, rows.length - 1)) {
        separators.pop()?.remove();
        grips.pop();
        lines.pop();
      }
      for (let i = 0; i < separators.length; i += 1) {
        const [el, grip] = [separators[i] as HTMLElement, grips[i] as HTMLElement];
        aria(el, grip, rows[i] as PaneRow, rows[i + 1] as PaneRow);
      }
      const text = announcement(prev, msg.ack);
      if (text !== null) say(text);
    },
    setTheme(next: Readonly<Record<string, string>>): void {
      theme = next; // repaint now: the grip is the ≥ 3:1 boundary (SC 1.4.11), the stubs too
      const open = rows.filter((r) => !r.collapsed).length;
      for (let i = 0; i < rows.length; i += 1) {
        const row = rows[i] as PaneRow;
        const c = chrome[i];
        if (c !== undefined) paint(c, row, labelOf(row.pane), open);
      }
      for (let i = 0; i < separators.length; i += 1) state(i);
    },
    dispose(): void {
      say.cancel();
      container.removeEventListener("pointermove", onHover);
      container.removeEventListener("pointerdown", onDown);
      container.removeEventListener("pointerup", onUp);
      container.removeEventListener("pointercancel", onUp);
      for (const el of separators) el.remove();
      while (chrome.length > 0) drop(chrome.pop());
      separators.length = 0;
      grips.length = 0;
      lines.length = 0;
    },
  };
}
