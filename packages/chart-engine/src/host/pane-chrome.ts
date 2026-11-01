// The pane chrome (E11-S09, #446 BQ-11, BQ-19, BQ-20; E11-D02 §8, §12; E11-D06 D8, D17, D18): one
// focusable `role="separator"` surrogate per pane boundary, a stub row per collapsed pane and an
// `aria-label`led region per pane in the DOM mirror, all placed from the worker's `layout` message.
// The separator's keys move the boundary (`↑/↓` 2 %, `Shift` 10 %, `Home` equal, `End` maximum)
// and send the whole share vector, summing to exactly 1; each key is announced once through
// `candleviewer:announce` under the `chart:pane` key, never per frame. Every step is instant (the
// reduced-motion path, BQ-20). The separators let pointers through: the worker's splitter drag
// (`splitAt`, mouse and pen) takes the pointer-down inside the 24 px band and hover passes on to
// the crosshair; the chrome only shows the `row-resize` cursor over a band. Values and
// announcements report height shares over the expanded panes. DOM program: it reaches the
// document through the container only.
import { MIN_PANE_PX, SPLITTER_BAND_PX } from "../scene/layout-engine.js";
import { normaliseShares } from "../scene/pane-shares.js";
import type { FromWorker, PaneBox } from "../worker/protocol.js";
import { type AnnounceClock, createAnnouncer } from "./axis-stop.js";

/** The shell announcer's key for the splitters and the stubs (BQ-19). */
export const PANE_ANNOUNCE_KEY = "chart:pane";
/** E11-D02 §8: `↑/↓` move the boundary 2 % of the stack, `Shift` 10 %. */
export const SPLITTER_STEP = 0.02;
export const SPLITTER_STEP_SHIFT = 0.1;

export type LayoutMessage = Extract<FromWorker, { t: "layout" }>;

export interface PaneChromeSink {
  /** A splitter key's outcome: every pane's share, in stack order, summing to exactly 1. */
  shares(shares: readonly (readonly [number, number])[]): void;
  /** A stub's restore button. */
  restore(pane: number): void;
}

export interface PaneChrome {
  /** The separators, top to bottom: the one below pane i is `separators[i]`. */
  readonly separators: readonly HTMLElement[];
  /** Places the chrome from a `layout` message; `labelOf` names a pane by its key. */
  update(msg: LayoutMessage, labelOf: (pane: number) => string): void;
  setTheme(colors: Readonly<Record<string, string>>): void;
  dispose(): void;
}

const pct = (share: number): number => Math.round(share * 100);

export function createPaneChrome(
  container: HTMLElement,
  mirrorRoot: HTMLElement,
  sink: PaneChromeSink,
  colors: Readonly<Record<string, string>>,
  clock: AnnounceClock,
): PaneChrome {
  const doc = container.ownerDocument;
  let theme = colors;
  let disposed = false;
  let cursorSet = false;
  const say = createAnnouncer(container, clock, PANE_ANNOUNCE_KEY);
  const separators: HTMLElement[] = [];
  const stubs = new Map<number, HTMLElement>();
  const regions = new Map<number, HTMLElement>();
  const wasCollapsed = new Map<number, boolean>();
  /** The last layout's boxes with the shares a key has moved since. */
  let boxes: PaneBox[] = [];
  let shares: number[] = [];
  let labels: string[] = [];

  /** The minimum share: 48 px of the stack (E11-D02 §8; BQ-11). */
  const minShare = (): number => {
    let stack = 0;
    for (const b of boxes) stack += b.height;
    return stack > 0 ? Math.min(0.5, MIN_PANE_PX / stack) : 0;
  };

  /**
   * What the user sees: a share over the expanded panes only (a stub's remembered share is not
   * height), so the expanded panes' percents sum to 100 while stubs exist.
   */
  function shown(w: number): number {
    let open = 0;
    for (let j = 0; j < shares.length; j += 1)
      if (boxes[j]?.collapsed !== true) open += shares[j] ?? 0;
    return open > 0 ? w / open : 0;
  }
  const said = (j: number): string =>
    boxes[j]?.collapsed === true
      ? `${labels[j] ?? ""} collapsed`
      : `${labels[j] ?? ""} ${pct(shown(shares[j] ?? 0))} percent`;

  function describe(i: number): void {
    const el = separators[i];
    const [a, b] = [shares[i] ?? 0, shares[i + 1] ?? 0];
    const [la, lb] = [labels[i] ?? "", labels[i + 1] ?? ""];
    if (el === undefined) return;
    const min = minShare();
    const above = boxes[i]?.collapsed === true ? 0 : shown(a);
    el.setAttribute("aria-label", `Resize ${la} and ${lb}`);
    el.setAttribute("aria-valuenow", String(pct(above)));
    el.setAttribute("aria-valuemin", String(Math.min(pct(above), pct(shown(min)))));
    el.setAttribute("aria-valuemax", String(Math.max(pct(above), pct(shown(a + b - min)))));
    el.setAttribute("aria-valuetext", `${said(i)}, ${said(i + 1)}`);
  }

  function separator(i: number): HTMLElement {
    const el = doc.createElement("div");
    el.setAttribute("role", "separator");
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-orientation", "horizontal");
    el.setAttribute("data-cv-splitter", "");
    const s = el.style;
    s.position = "absolute";
    s.left = "0px";
    s.right = "0px";
    s.height = `${SPLITTER_BAND_PX}px`;
    s.pointerEvents = "none"; // the worker's splitter drag (`splitAt`) takes the press; hover passes
    s.outlineOffset = "-2px";
    const grip = doc.createElement("div"); // E11-D02 §8: the 24 x 4 grip, the >= 3:1 boundary
    grip.setAttribute("aria-hidden", "true");
    Object.assign(grip.style, {
      position: "absolute",
      left: "50%",
      top: "10px",
      width: "24px",
      height: "4px",
      marginLeft: "-12px",
      borderRadius: "2px",
    });
    el.appendChild(grip);
    el.addEventListener(
      "focus",
      () => (s.outline = `2px solid ${theme["color.focus.ring"] ?? ""}`),
    );
    el.addEventListener("blur", () => (s.outline = "none"));
    el.addEventListener("keydown", (e) => onKey(e, i));
    container.appendChild(el);
    return el;
  }

  /** Sends the moved shares, normalised so they sum to exactly 1, and re-describes. */
  function commit(weights: number[], text: string | (() => string)): void {
    normaliseShares(weights, weights.length, shares);
    for (let i = 0; i < separators.length; i += 1) describe(i);
    sink.shares(boxes.map((b, i) => [b.pane, shares[i] ?? 0] as const));
    say(typeof text === "string" ? text : text()); // after the shares moved
  }

  function onKey(e: KeyboardEvent, i: number): void {
    const a = shares[i] ?? 0;
    const b = shares[i + 1] ?? 0;
    const min = minShare();
    const stubbed = (j: number): boolean => boxes[j]?.collapsed === true;
    const w = [...shares];
    let text: string;
    if (e.key === "Escape") {
      container.focus({ preventScroll: true });
      e.preventDefault();
      return;
    }
    const arrow = e.key === "ArrowUp" || e.key === "ArrowDown";
    if (!arrow && e.key !== "Home" && e.key !== "End") return; // Tab and the page's keys pass
    e.preventDefault();
    e.stopPropagation(); // the chart's plot keys never see a splitter key
    // A stub beside the boundary has no height to give or take: say so, move nothing (BQ-11).
    const stub = arrow
      ? stubbed(i)
        ? i
        : stubbed(i + 1)
          ? i + 1
          : -1
      : e.key === "End" && stubbed(i)
        ? i
        : -1;
    if (stub >= 0) {
      say(`${labels[stub] ?? ""} collapsed`);
      return;
    }
    if (arrow) {
      const step = e.shiftKey ? SPLITTER_STEP_SHIFT : SPLITTER_STEP;
      const next = Math.min(Math.max(a + (e.key === "ArrowUp" ? step : -step), min), a + b - min);
      if (Math.abs(next - a) < 1e-9) return; // at the limit: nothing moves and nothing is said
      w[i] = next;
      w[i + 1] = a + b - next;
      text = ""; // E11-D02 §8's wording, said after the commit: the pane below's shown share
    } else {
      // Stubs keep their remembered shares; the expanded panes share the rest.
      let kept = 0;
      let open = 0;
      for (let j = 0; j < w.length; j += 1) {
        if (stubbed(j)) kept += w[j] ?? 0;
        else open += 1;
      }
      if (e.key === "Home") {
        for (let j = 0; j < w.length; j += 1) if (!stubbed(j)) w[j] = (1 - kept) / open;
        text = "Panes equal";
      } else {
        for (let j = 0; j < w.length; j += 1) if (!stubbed(j)) w[j] = min;
        w[i] = Math.max(min, 1 - kept - min * (open - 1));
        text = "";
      }
    }
    commit(w, text !== "" ? text : () => said(arrow ? i + 1 : i));
  }

  function stub(box: PaneBox, label: string): void {
    let row = stubs.get(box.pane);
    if (row === undefined) {
      row = doc.createElement("div");
      row.setAttribute("data-cv-pane-stub", "");
      Object.assign(row.style, {
        position: "absolute",
        left: "0px",
        right: "0px",
        display: "flex",
        alignItems: "center",
        gap: "8px",
        paddingLeft: "8px",
      });
      row.appendChild(doc.createElement("span")); // the label
      const word = row.appendChild(doc.createElement("span"));
      word.textContent = "collapsed";
      const button = row.appendChild(doc.createElement("button"));
      button.type = "button";
      Object.assign(button.style, { width: "24px", height: "24px", padding: "0px" });
      const chevron = button.appendChild(doc.createElement("span"));
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = "⌄";
      const key = box.pane;
      button.addEventListener("click", () => sink.restore(key));
      container.appendChild(row);
      stubs.set(key, row);
    }
    const [name, word, button] = Array.from(row.children) as HTMLElement[];
    if (name !== undefined && name.textContent !== label) name.textContent = label;
    button?.setAttribute("aria-label", `Restore ${label}`);
    row.style.top = `${box.top}px`;
    row.style.height = `${box.height}px`;
    row.style.background = theme["color.surface.raised"] ?? "";
    row.style.color = theme["color.text.primary"] ?? "";
    if (word !== undefined) word.style.color = theme["color.text.secondary"] ?? "";
  }

  function region(pane: number, label: string): void {
    let el = regions.get(pane);
    if (el === undefined) {
      el = doc.createElement("div");
      el.setAttribute("role", "region");
      mirrorRoot.appendChild(el);
      regions.set(pane, el);
    }
    el.setAttribute("aria-label", label);
  }

  /** The `row-resize` cursor over a band only; the press itself goes to the canvas. */
  function onPointerMove(e: PointerEvent): void {
    const top = container.getBoundingClientRect?.().top ?? 0;
    const y = e.clientY - top;
    let over = false;
    for (let i = 0; i < boxes.length - 1; i += 1) {
      const edge = (boxes[i] as PaneBox).top + (boxes[i] as PaneBox).height;
      if (y >= edge - SPLITTER_BAND_PX / 2 && y < edge + SPLITTER_BAND_PX / 2) over = true;
    }
    if (over === cursorSet) return;
    cursorSet = over;
    container.style.cursor = over ? "row-resize" : "";
  }
  container.addEventListener("pointermove", onPointerMove, { passive: true });

  return {
    separators,
    update(msg: LayoutMessage, labelOf: (pane: number) => string): void {
      if (disposed) return;
      boxes = [...msg.panes];
      shares = boxes.map((b) => b.share);
      labels = boxes.map((b) => labelOf(b.pane));
      while (separators.length < boxes.length - 1) separators.push(separator(separators.length));
      while (separators.length > Math.max(0, boxes.length - 1)) separators.pop()?.remove();
      for (let i = 0; i < separators.length; i += 1) {
        const b = boxes[i] as PaneBox;
        const el = separators[i] as HTMLElement;
        el.style.top = `${b.top + b.height - SPLITTER_BAND_PX / 2}px`;
        const grip = el.children[0] as HTMLElement | undefined;
        if (grip !== undefined) grip.style.background = theme["color.text.tertiary"] ?? "";
        describe(i);
      }
      const live = new Set<number>();
      for (let i = 0; i < boxes.length; i += 1) {
        const b = boxes[i] as PaneBox;
        const label = labels[i] ?? "";
        live.add(b.pane);
        region(b.pane, label);
        if (b.collapsed) stub(b, label);
        else {
          stubs.get(b.pane)?.remove();
          stubs.delete(b.pane);
        }
        // E11-D02 §8: "Volume pane collapsed" / "restored", once per change, whatever caused it.
        const was = wasCollapsed.get(b.pane);
        if (was !== undefined && was !== b.collapsed) {
          say(`${label} ${b.collapsed ? "collapsed" : "restored"}`);
        }
        wasCollapsed.set(b.pane, b.collapsed);
      }
      for (const map of [stubs, regions]) {
        for (const [pane, el] of map) {
          if (live.has(pane)) continue;
          el.remove();
          map.delete(pane);
        }
      }
      for (const pane of [...wasCollapsed.keys()]) if (!live.has(pane)) wasCollapsed.delete(pane);
    },
    setTheme(next: Readonly<Record<string, string>>): void {
      theme = next;
    },
    dispose(): void {
      if (disposed) return;
      disposed = true;
      container.removeEventListener("pointermove", onPointerMove);
      if (cursorSet) container.style.cursor = "";
      for (const el of separators) el.remove();
      for (const el of stubs.values()) el.remove();
      for (const el of regions.values()) el.remove();
      separators.length = 0;
      stubs.clear();
      regions.clear();
    },
  };
}
