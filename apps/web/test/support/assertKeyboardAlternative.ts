import { act, fireEvent } from "@testing-library/react";
import { expect } from "vitest";

/**
 * Parity helper for WCAG 2.2 SC 2.5.7 (Dragging Movements, AA) and `05-accessibility-standard.md` §3.1 rule 6 and
 * §3.4 rule 8 (E47-S05, #1319). Every drag surface registered in `docs/qa/a11y/e47-drag-alternative-register.md` has a
 * test that calls this with its own surface, so the keyboard path is proven to reach the same state as the drag.
 */
export interface KeyboardAlternativeCase<T> {
  /** The element that is dragged; it must be reachable and named without a pointer. */
  readonly target: HTMLElement;
  /** The drag: the surface's own pointer sequence, ending where the user would let go. */
  readonly drag: () => void | Promise<void>;
  /** Keys that reach the same end state from the same start, as `KeyboardEvent.key` values, in order. */
  readonly keys: readonly string[];
  /** The value both paths must reach: what the surface commits (a price, a rect, a node position). */
  readonly read: () => T;
  /** Puts the surface back to its start between the two paths. */
  readonly reset: () => void;
  /** Equality of two committed values; `Object.is` by default (a `toEqual` for objects is passed in). */
  readonly same?: (a: T, b: T) => boolean;
}

const NATIVE_FOCUSABLE = /^(A|BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY)$/u;

/** Reachable: a native control, or an element with a tab index that is not -1 and is not disabled. */
export function isKeyboardReachable(el: HTMLElement): boolean {
  if (el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true") return false;
  if (el.tabIndex < 0) return false;
  return NATIVE_FOCUSABLE.test(el.tagName) || el.hasAttribute("tabindex");
}

/** Named without a pointer: an `aria-label`, an `aria-labelledby` that resolves, or text content. */
export function hasAccessibleName(el: HTMLElement): boolean {
  const label = el.getAttribute("aria-label")?.trim();
  if (label) return true;
  const ids = el.getAttribute("aria-labelledby")?.split(/\s+/u) ?? [];
  const named = ids.some(
    (id) => (el.ownerDocument.getElementById(id)?.textContent ?? "").trim() !== "",
  );
  return named || (el.textContent ?? "").trim() !== "";
}

/**
 * Fails unless the target is reachable and named, the drag changes the value, and the keys reach the same value from
 * the same start. A surface whose keys do nothing, or land elsewhere, fails with both values in the message.
 */
export async function assertKeyboardAlternative<T>(c: KeyboardAlternativeCase<T>): Promise<void> {
  const same = c.same ?? ((a: T, b: T): boolean => Object.is(a, b));
  expect(isKeyboardReachable(c.target), "the drag target cannot take keyboard focus").toBe(true);
  expect(hasAccessibleName(c.target), "the drag target has no accessible name").toBe(true);

  const start = c.read();
  await act(async () => {
    await c.drag();
  });
  const dragged = c.read();
  expect(same(start, dragged), "the drag did not change the value").toBe(false);

  c.reset();
  expect(same(c.read(), start), "reset did not restore the start").toBe(true);

  act(() => c.target.focus());
  expect(c.target.ownerDocument.activeElement, "the target did not take focus").toBe(c.target);
  for (const key of c.keys) act(() => void fireEvent.keyDown(c.target, { key }));
  const keyed = c.read();
  expect(
    same(keyed, dragged),
    `keys ${JSON.stringify(c.keys)} reached ${JSON.stringify(keyed)}, the drag reached ${JSON.stringify(dragged)}`,
  ).toBe(true);
}
