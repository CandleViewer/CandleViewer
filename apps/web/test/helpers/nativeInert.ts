import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

/**
 * Chromium's `inert`, emulated in jsdom (25 has none): the IDL attribute reflects the content attribute, so
 * CMP-043 takes its native branch (`supportsInert()` in `inertOutside.ts`) and marks the page `inert`, not
 * `aria-hidden`; `focus()` on an element under `[inert]` does nothing, as in the browser; and the focused
 * element that turns inert loses the focus a beat after the change, as Chromium's focus fixup does (here at
 * the next microtask). Returns the restore.
 */
export function emulateNativeInert(): () => void {
  const proto = HTMLElement.prototype;
  const before = Object.getOwnPropertyDescriptor(proto, "inert");
  const focus = proto.focus;
  Object.defineProperty(proto, "inert", {
    configurable: true,
    get(this: HTMLElement): boolean {
      return this.hasAttribute("inert");
    },
    set(this: HTMLElement, value: boolean) {
      this.toggleAttribute("inert", value);
    },
  });
  proto.focus = function focusUnlessInert(this: HTMLElement, options?: FocusOptions): void {
    if (this.closest("[inert]") === null) focus.call(this, options);
  };
  const fixup = new MutationObserver(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement && active.closest("[inert]") !== null) active.blur();
  });
  fixup.observe(document, { subtree: true, attributeFilter: ["inert"] });
  return () => {
    fixup.disconnect();
    proto.focus = focus;
    if (before === undefined) Reflect.deleteProperty(proto, "inert");
    else Object.defineProperty(proto, "inert", before);
  };
}

/** Runs the calling block with native `inert` emulated when `native`; each test unmounts before it goes. */
export function inertMode(native: boolean): void {
  let restore: (() => void) | undefined;
  beforeEach(() => {
    restore = native ? emulateNativeInert() : undefined;
  });
  afterEach(() => {
    cleanup();
    restore?.();
  });
}
