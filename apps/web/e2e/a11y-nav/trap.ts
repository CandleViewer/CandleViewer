import type { Page } from "@playwright/test";

/** One Tab stop as the trap helper sees it. */
export interface FocusStop {
  /** Stable identity of the focused element within the page (not its name). */
  readonly key: string;
  /** Accessible name as the browser computes it (from the ARIA snapshot); "" when it has none. */
  readonly name: string;
  readonly visible: boolean;
}

export interface TrapVerdict {
  readonly ok: boolean;
  /** Tab presses it took to come back to the first stop (or to leave the document). */
  readonly stops: number;
  readonly failures: readonly string[];
}

/** The stand-in key for "focus left the document / landed on body": the end of a full loop. */
export const WRAPPED = "<wrap>";

/**
 * Judge a recorded Tab sequence (05 s9.4, E47-Q03): it must come back to its first stop (or wrap past the
 * last one) within `maxStops`, never stall on one element, and every stop must be visibly focused and named.
 * Pure: the page-driving half is {@link collectStops}.
 */
export function judgeFocusSequence(stops: readonly FocusStop[], maxStops: number): TrapVerdict {
  const failures: string[] = [];
  const first = stops[0];
  if (first === undefined) {
    return {
      ok: false,
      stops: 0,
      failures: ["A11Y-K010 no tab stop: nothing on the screen takes focus"],
    };
  }
  let closedAt = -1;
  for (let i = 0; i < stops.length; i++) {
    const s = stops[i] as FocusStop;
    if (s.key === WRAPPED) {
      closedAt = i;
      break;
    }
    if (i > 0 && s.key === first.key) {
      closedAt = i;
      break;
    }
    if (i > 0 && s.key === (stops[i - 1] as FocusStop).key) {
      failures.push(`A11Y-K011 keyboard trap: focus stuck on "${s.name || s.key}" at stop ${i}`);
      break;
    }
    if (s.name.trim() === "")
      failures.push(`A11Y-K012 stop ${i} (${s.key}) has no accessible name`);
    if (!s.visible) failures.push(`A11Y-K013 stop ${i} ("${s.name}") shows no focus indicator`);
  }
  if (failures.length === 0 && closedAt < 0) {
    failures.push(`A11Y-K014 focus did not return to the start within ${maxStops} stops`);
  }
  return { ok: failures.length === 0, stops: closedAt < 0 ? stops.length : closedAt, failures };
}

interface Probe {
  key: string;
  visible: boolean;
  body: boolean;
}

interface TrapWindow {
  __focusKeys?: WeakMap<Element, number>;
  __focusSeq?: number;
}

/** The accessible name from the first line of a Playwright ARIA snapshot: `- button "Sign in"`. */
export function nameFromAriaLine(snapshot: string): string {
  const m = /^\s*-\s+[\w-]+\s+"((?:[^"\\]|\\.)*)"/.exec(snapshot);
  return m?.[1]?.replace(/\\(.)/g, "$1") ?? "";
}

/**
 * Press Tab up to `maxStops` times from the document start and record each stop. Stops recording once the
 * loop closes, so a healthy screen costs its own stop count and a trap costs `maxStops`.
 */
export async function collectStops(page: Page, maxStops: number): Promise<FocusStop[]> {
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
  });
  const stops: FocusStop[] = [];
  for (let i = 0; i < maxStops; i++) {
    await page.keyboard.press("Tab");
    const probe = await page.evaluate((): Probe => {
      const w = window as unknown as TrapWindow;
      w.__focusKeys ??= new WeakMap();
      w.__focusSeq ??= 0;
      const el = document.activeElement;
      if (!el || el === document.body) return { key: "", visible: true, body: true };
      let id = w.__focusKeys.get(el);
      if (id === undefined) {
        id = ++w.__focusSeq;
        w.__focusKeys.set(el, id);
      }
      const cs = getComputedStyle(el);
      const visible =
        (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== "none";
      return { key: `${el.tagName.toLowerCase()}#${id}`, visible, body: false };
    });
    if (probe.body) {
      stops.push({ key: WRAPPED, name: "", visible: true });
      break;
    }
    const snap = await page.locator(":focus").ariaSnapshot({ timeout: 2_000 });
    stops.push({ key: probe.key, name: nameFromAriaLine(snap), visible: probe.visible });
    if (stops.length > 1 && probe.key === (stops[0] as FocusStop).key) break;
  }
  return stops;
}

/** Drive the whole screen and return the verdict; the journey asserts `ok` and prints `failures`. */
export async function checkNoTrap(page: Page, maxStops: number): Promise<TrapVerdict> {
  return judgeFocusSequence(await collectStops(page, maxStops), maxStops);
}
