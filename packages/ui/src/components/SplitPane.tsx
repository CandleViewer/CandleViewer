import { useRef, type JSX, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { cx } from "./internal/cx.js";

/** CMP-083 keyboard steps: arrows 2 %, `Shift`+arrows 10 % of the split. */
export const SPLIT_STEP = 0.02;
export const SPLIT_STEP_LARGE = 0.1;

export interface SplitPaneCell {
  /** Stable key: a cell keeps its subtree across re-renders and reorders. */
  readonly key: string;
  readonly content: ReactNode;
}

export interface SplitPaneProps {
  /** `row` lays cells left to right, `column` top to bottom. */
  direction: "row" | "column";
  cells: readonly SplitPaneCell[];
  /** One share per cell, summing to 1. */
  sizes: readonly number[];
  /** Each cell's minimum share (the neighbours' minimums give `aria-valuemin` / `aria-valuemax`). */
  minSizes?: readonly number[];
  /** Separator `i`'s name, "{Left panel} and {Right panel} splitter" (one per gap). */
  labels: readonly string[];
  /** Commits a move of separator `index` by `delta` (a share; + grows the cell before it). */
  onResize: (index: number, delta: number) => void;
  /** `Home` on any separator: equal sizes for every cell (E15-D04 §6); without it, the pair. */
  onEqualise?: () => void;
  /** Says "Minimum size." once per stop (SR-08), into the app's one polite region. */
  onAnnounce?: (text: string) => void;
  className?: string;
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi);

/**
 * CMP-083: the n-ary split with its k-1 separators. Each separator is a `role="separator"` Tab stop
 * (`aria-valuenow` its position in %), resized by arrows / `Shift`+arrows, `Home` (equal) and `End`
 * (maximum), or dragged: a drag writes the two cells' flex once per animation frame and commits once,
 * on release, so a resize re-renders nothing per pointer move.
 */
export function SplitPane({
  direction,
  cells,
  sizes,
  minSizes,
  labels,
  onResize,
  onEqualise,
  onAnnounce,
  className,
}: SplitPaneProps): JSX.Element {
  const root = useRef<HTMLDivElement>(null);
  const atStop = useRef<number | null>(null);
  const share = (i: number): number => sizes[i] ?? 0;
  const min = (i: number): number => minSizes?.[i] ?? 0;
  const before = (i: number): number => sizes.slice(0, i + 1).reduce((a, b) => a + b, 0);

  /** The allowed move of separator `i`, and a "Minimum size." once when it reaches a stop. */
  const commit = (i: number, wanted: number): void => {
    const delta = clamp(wanted, min(i) - share(i), share(i + 1) - min(i + 1));
    const stopped = delta !== wanted;
    if (stopped && atStop.current !== i) onAnnounce?.("Minimum size.");
    atStop.current = stopped ? i : null;
    if (delta !== 0) onResize(i, delta);
  };

  const onKeyDown = (i: number, event: KeyboardEvent<HTMLDivElement>): void => {
    const step = event.shiftKey ? SPLIT_STEP_LARGE : SPLIT_STEP;
    const back = direction === "row" ? "ArrowLeft" : "ArrowUp";
    const forward = direction === "row" ? "ArrowRight" : "ArrowDown";
    const pair = share(i) + share(i + 1);
    const delta =
      event.key === back
        ? -step
        : event.key === forward
          ? step
          : event.key === "Home"
            ? pair / 2 - share(i)
            : event.key === "End"
              ? Infinity
              : null;
    if (delta === null) return;
    event.preventDefault();
    if (event.key === "Home" && onEqualise !== undefined) return onEqualise();
    commit(i, delta === Infinity ? share(i + 1) - min(i + 1) : delta);
  };

  const onPointerDown = (i: number, event: PointerEvent<HTMLDivElement>): void => {
    const host = root.current;
    const a = host?.children[i * 2] as HTMLElement | undefined;
    const b = host?.children[i * 2 + 2] as HTMLElement | undefined;
    if (host === null || a === undefined || b === undefined) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const extent = direction === "row" ? host.clientWidth : host.clientHeight;
    const start = direction === "row" ? event.clientX : event.clientY;
    const lo = min(i) - share(i);
    const hi = share(i + 1) - min(i + 1);
    let delta = 0;
    let frame = 0;
    const target = event.currentTarget;
    const move = (e: globalThis.PointerEvent): void => {
      const at = direction === "row" ? e.clientX : e.clientY;
      delta = extent > 0 ? clamp((at - start) / extent, lo, hi) : 0;
      if (frame !== 0) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        a.style.flexGrow = String(share(i) + delta);
        b.style.flexGrow = String(share(i + 1) - delta);
      });
    };
    const up = (): void => {
      cancelAnimationFrame(frame);
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      if (delta !== 0) onResize(i, delta);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };

  // A focusable, value-bearing separator is a widget (the WAI-ARIA window-splitter pattern), which
  // jsx-a11y reads as a static element: its two rules are off for this element alone.
  /* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- the APG window splitter */
  return (
    <div
      ref={root}
      className={cx("cv-splitpane", className)}
      data-cmp="CMP-083"
      data-direction={direction}
    >
      {cells.flatMap((cell, i) => {
        const node = (
          <div key={cell.key} className="cv-splitpane__cell" style={{ flexGrow: share(i) }}>
            {cell.content}
          </div>
        );
        if (i === cells.length - 1) return [node];
        return [
          node,
          <div
            key={`${cell.key}/separator`}
            className="cv-splitpane__separator"
            role="separator"
            tabIndex={0}
            aria-label={labels[i]}
            aria-orientation={direction === "row" ? "vertical" : "horizontal"}
            aria-valuenow={Math.round(before(i) * 100)}
            aria-valuemin={Math.round((before(i) - share(i) + min(i)) * 100)}
            aria-valuemax={Math.round((before(i + 1) - min(i + 1)) * 100)}
            onKeyDown={(event) => onKeyDown(i, event)}
            onPointerDown={(event) => onPointerDown(i, event)}
          />,
        ];
      })}
    </div>
  );
  /* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */
}
