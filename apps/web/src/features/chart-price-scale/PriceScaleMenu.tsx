/**
 * SCR-043's price-scale menu (E11-S05 PR 2; E11-D03 §3, D1–D5): CMP-041 opened by the engine's
 * `candleviewer:pricescalemenu` (a right-click on the price gutter) or by `Shift+F10` / the Menu
 * key while focus is in the chart, until E11-S06's axis stop owns those keys (and the keyboard
 * path picks the pane; today it opens pane 0). The items mirror the pane's live
 * `PriceScale.getState()`: the radio group is the drawn mode (D5: the menu states what is drawn),
 * Lock is auto's off state (C-30). Every activation closes the menu (D1), focus goes back where it
 * was when the menu opened (the chart container for a right-click), and the change is said once
 * in the shell's polite region in D03's "Price scale: …" grammar, with `chart.price_scale_changed`
 * on the app's analytics seam, read back from the engine after the change. A D5 fallback (log
 * drawn, then a value <= 0) is heard from the engine's reported state and said once. A projection
 * change only: nothing here refetches (SCR-043 note).
 * Out of scope (G-18): Move scale to left / right and Scale settings… (E11-S06 / SCR-031).
 */
import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import type { Chart as ChartApi, Pane, PriceScale } from "@candleviewer/chart-engine";
import { Menu, type MenuAnchorRect, type MenuItem } from "@candleviewer/ui";
import { useChartApi, useChartContainer } from "../../chart";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import { announce, forget } from "../app-shell/announcer";
import { logReasonText, PRICE_SCALE_COPY as COPY, type ScaleMode } from "./copy";

type ScaleState = ReturnType<PriceScale["getState"]>;
type Source = "menu" | "fallback";

/** The engine's event name and detail (`src/host/input-router.ts`; not on the §8 surface). */
export const PRICE_SCALE_MENU_EVENT = "candleviewer:pricescalemenu";
/** The engine's price gutter width (`PRICE_GUTTER_PX`): a keyboard open anchors to its top. */
const GUTTER_PX = 64;
const MODES: readonly ScaleMode[] = ["linear", "log", "percent", "indexed"];
const MODE_GROUP = { id: "mode", label: COPY.modeGroup };
const SCALE_GROUP = { id: "scale", label: COPY.scaleGroup };
const RESET_GROUP = { id: "reset" };
/** One key, forgotten before each change, so every change is said and none is kept. */
const SAY_KEY = "chart-price-scale:change";

interface MenuDetail {
  readonly pane: number;
  readonly x: number;
  readonly y: number;
  readonly byKey: boolean;
}

const isDetail = (d: unknown): d is MenuDetail => {
  if (typeof d !== "object" || d === null) return false;
  const r = d as Partial<Record<keyof MenuDetail, unknown>>;
  return (
    Number.isInteger(r.pane) &&
    Number.isFinite(r.x) &&
    Number.isFinite(r.y) &&
    typeof r.byKey === "boolean"
  );
};

const isMenuKey = (e: KeyboardEvent): boolean =>
  !e.ctrlKey &&
  !e.altKey &&
  !e.metaKey &&
  (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey));

function say(text: string): void {
  forget(SAY_KEY);
  announce("polite", text, SAY_KEY);
}

/**
 * D03 §9's closed payload: the full state after the change, "what is the scale now", so `mode` is
 * the drawn mode (D5: Linear after a fallback). No position or merge yet: constants.
 */
function report(s: ScaleState, source: Source): void {
  const detail = {
    name: "chart.price_scale_changed",
    mode: s.mode,
    locked: !s.autoScale,
    inverted: s.inverted,
    merged_scales: false,
    position: "right",
    price_only: s.priceOnly,
    source,
  };
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
}

interface Opened {
  readonly pane: Pane;
  readonly anchor: MenuAnchorRect;
  readonly state: ScaleState;
}

/** The fields the items read: a change in any of them re-renders an open menu. */
const sameItems = (a: ScaleState, b: ScaleState): boolean =>
  a.mode === b.mode &&
  a.requestedMode === b.requestedMode &&
  a.autoScale === b.autoScale &&
  a.inverted === b.inverted &&
  a.priceOnly === b.priceOnly &&
  a.logAvailable === b.logAvailable &&
  a.logReason === b.logReason;

/** The items for one opening, in D03 §3.1's order (G-18's two items omitted). */
function itemsFor(
  { pane, state: s }: Opened,
  act: (change: () => void, text: string) => void,
  close: () => void,
): MenuItem[] {
  const scale = pane.priceScale;
  const logGated = !s.logAvailable && s.mode !== "log" && s.logReason !== null;
  const modes = MODES.map((m): MenuItem => ({
    id: `mode-${m}`,
    label: COPY.modes[m],
    group: MODE_GROUP,
    kind: "radio",
    checked: s.mode === m,
    ...(m === "log" && logGated && s.logReason !== null
      ? { disabledReason: logReasonText(s.logReason, s.requestedMode) }
      : {}),
    onSelect: () => {
      if (s.mode === m && s.requestedMode === m) close();
      else act(() => scale.setMode(m), COPY.said.modes[m]);
    },
  }));
  return [
    ...modes,
    {
      id: "lock",
      label: COPY.lock,
      group: SCALE_GROUP,
      kind: "checkbox",
      checked: !s.autoScale,
      description: COPY.lockDescription,
      onSelect: () =>
        act(
          () => scale.setAutoScale(!s.autoScale),
          s.autoScale ? COPY.said.locked : COPY.said.auto,
        ),
    },
    {
      id: "invert",
      label: COPY.invert,
      group: SCALE_GROUP,
      kind: "checkbox",
      checked: s.inverted,
      onSelect: () =>
        act(
          () => scale.setInverted(!s.inverted),
          s.inverted ? COPY.said.upright : COPY.said.inverted,
        ),
    },
    {
      // Present and gated until E13 brings indicator scales (the ticket's Out of scope).
      id: "merge",
      label: COPY.merge,
      group: SCALE_GROUP,
      kind: "checkbox",
      checked: false,
      disabledReason: COPY.mergeReason,
      onSelect: close,
    },
    {
      id: "price-only",
      label: COPY.priceOnly,
      group: SCALE_GROUP,
      kind: "checkbox",
      checked: s.priceOnly,
      description: COPY.priceOnlyDescription,
      onSelect: () =>
        act(
          () => scale.setOptions({ priceOnly: !s.priceOnly }),
          s.priceOnly ? COPY.said.overlays : COPY.said.priceOnly,
        ),
    },
    {
      // D03's hint column ("Home · double-click") is left out: `Home` on the axis is E11-S06's key
      // and a double-click is not a key for aria-keyshortcuts (a recorded deviation, like G-18).
      id: "reset",
      label: COPY.reset,
      group: RESET_GROUP,
      ...(s.autoScale ? { disabledReason: COPY.resetReason } : {}),
      onSelect: () => act(() => scale.setAutoScale(true), COPY.said.auto),
    },
  ];
}

export interface PriceScaleMenuHostProps {
  readonly chart: ChartApi;
  /** The chart's container: the engine dispatches the open event there and hears its keys. */
  readonly container: HTMLElement;
}

/** The menu for one mounted chart (`PriceScaleMenu` is the `<Chart>` child that finds both). */
export function PriceScaleMenuHost({
  chart,
  container,
}: PriceScaleMenuHostProps): JSX.Element | null {
  const [opened, setOpened] = useState<Opened | null>(null);
  const openedRef = useRef<Opened | null>(null);
  openedRef.current = opened;
  const suppress = useRef(false);

  const openAt = useCallback(
    (index: number, anchor: MenuAnchorRect): void => {
      const pane = chart.panes[index];
      if (pane === undefined) return;
      // The menu returns focus to what held it as it opens: keep it in the chart (a right-click).
      if (!container.contains(document.activeElement)) container.focus({ preventScroll: true });
      setOpened({ pane, anchor, state: pane.priceScale.getState() });
    },
    [chart, container],
  );

  useEffect(() => {
    const onMenu = (e: Event): void => {
      const detail = (e as CustomEvent<unknown>).detail;
      if (isDetail(detail)) openAt(detail.pane, { x: detail.x, y: detail.y, width: 0, height: 0 });
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.defaultPrevented || !isMenuKey(e)) return;
      e.preventDefault();
      suppress.current = true; // the browser's own `contextmenu` follows the key
      const r = container.getBoundingClientRect();
      openAt(0, { x: Math.max(r.left, r.right - GUTTER_PX), y: r.top, width: 0, height: 0 });
    };
    // Capture on the document: the key's `contextmenu` lands where focus went (the menu), and the
    // engine must not read it as a gutter right-click.
    const onContext = (e: MouseEvent): void => {
      if (!suppress.current) return;
      suppress.current = false;
      e.preventDefault();
      e.stopPropagation();
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onKeyUp = (e: KeyboardEvent): void => {
      if (!suppress.current || (e.key !== "ContextMenu" && e.key !== "F10")) return;
      clearTimeout(timer); // no `contextmenu` followed (a platform without one): stop waiting
      timer = setTimeout(() => {
        suppress.current = false;
      }, 0);
    };
    container.addEventListener(PRICE_SCALE_MENU_EVENT, onMenu);
    container.addEventListener("keydown", onKey);
    document.addEventListener("contextmenu", onContext, true);
    document.addEventListener("keyup", onKeyUp);
    return () => {
      clearTimeout(timer);
      container.removeEventListener(PRICE_SCALE_MENU_EVENT, onMenu);
      container.removeEventListener("keydown", onKey);
      document.removeEventListener("contextmenu", onContext, true);
      document.removeEventListener("keyup", onKeyUp);
    };
  }, [container, openAt]);

  // D5: the engine falls back to linear on its own; the app hears it from the reported state. An
  // open menu follows it too, re-rendered only when a field its items read changed.
  useEffect(() => {
    const drawn = new WeakMap<Pane, ScaleMode>();
    const watch = (): void => {
      for (const pane of chart.panes) {
        const s = pane.priceScale.getState();
        const was = drawn.get(pane);
        drawn.set(pane, s.mode);
        const fellBack = was === "log" && s.mode === "linear" && s.requestedMode === "log";
        if (fellBack && s.logReason === "non-positive") {
          say(COPY.said.fallback);
          report(s, "fallback");
        }
      }
      const o = openedRef.current;
      if (o === null) return;
      const now = o.pane.priceScale.getState();
      if (!sameItems(o.state, now)) setOpened({ ...o, state: now });
    };
    watch();
    return chart.subscribe("viewportChanged", watch);
  }, [chart]);

  if (opened === null) return null;
  const close = (): void => setOpened(null);
  const pane = opened.pane;
  const act = (change: () => void, text: string): void => {
    change();
    say(text);
    report(pane.priceScale.getState(), "menu"); // what the engine now holds, not a guess at it
    close(); // D1: a checkable item's Space closes too
  };
  return (
    <Menu
      anchor={opened.anchor}
      open
      aria-label={COPY.menu}
      items={itemsFor(opened, act, close)}
      announceReason={say}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    />
  );
}

/** SCR-043 inside a `<Chart>`: renders nothing until the menu opens. */
export function PriceScaleMenu(): JSX.Element | null {
  const chart = useChartApi();
  const container = useChartContainer();
  return chart === null || container === null ? null : (
    <PriceScaleMenuHost chart={chart} container={container} />
  );
}
