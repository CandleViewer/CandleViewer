// @vitest-environment jsdom
/**
 * The modal Tab trap (`trapTab`, conventions 32; APG Dialog (Modal)): Tab and Shift+Tab cycle inside the container in
 * DOM order. #5335 A-5335-03: focus on an element inside that is no tab stop (a preview's heading a step focused)
 * moves to the next or previous stop after it in document order, and wraps only past the ends.
 */
import { afterEach, describe, expect, it } from "vitest";
import { trapTab } from "../src/components/internal/focusTrap.js";

afterEach(() => document.body.replaceChildren());

/** One element built node by node: its attributes, then its text or its children. */
const el = (
  tag: string,
  attributes: Readonly<Record<string, string>> = {},
  content: string | readonly HTMLElement[] = [],
): HTMLElement => {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (typeof content === "string") element.textContent = content;
  else element.append(...content);
  return element;
};

/** A dialog: Close, a field, a preview whose heading takes focus, its Add button, Cancel. */
function dialog() {
  const close = el("button", {}, "Close");
  const field = el("textarea");
  const heading = el("h4", { tabindex: "-1" }, "Preview");
  const add = el("button", {}, "Add 3 symbols");
  const cancel = el("button", {}, "Cancel");
  const container = el("div", { role: "dialog", tabindex: "-1" }, [
    close,
    field,
    el("section", {}, [heading, el("p", {}, "To add BTCUSDT"), add]),
    cancel,
  ]);
  document.body.append(el("button", {}, "Outside"), container);
  return { container, close, field, heading, add, cancel };
}

/** Presses Tab (or Shift+Tab) on the focused element, as the container's handler sees it: `true` if prevented. */
function tab(container: HTMLElement, shift = false): boolean {
  const event = new KeyboardEvent("keydown", { key: "Tab", shiftKey: shift, cancelable: true });
  trapTab(event, container);
  return event.defaultPrevented;
}

describe("trapTab", () => {
  it("from a focused heading inside (no tab stop): Tab goes to the next stop after it, Shift+Tab to the one before", () => {
    const d = dialog();
    d.heading.focus();
    expect(tab(d.container)).toBe(true);
    expect(document.activeElement).toBe(d.add);
    d.heading.focus();
    expect(tab(d.container, true)).toBe(true);
    expect(document.activeElement).toBe(d.field);
  });

  it("wraps only past the ends: the last stop's Tab goes to the first, the first's Shift+Tab to the last", () => {
    const d = dialog();
    d.cancel.focus();
    expect(tab(d.container)).toBe(true);
    expect(document.activeElement).toBe(d.close);
    expect(tab(d.container, true)).toBe(true);
    expect(document.activeElement).toBe(d.cancel);
  });

  it("between stops it lets the browser move focus (no default prevented)", () => {
    const d = dialog();
    d.field.focus();
    expect(tab(d.container)).toBe(false);
    expect(document.activeElement).toBe(d.field);
  });

  it("an element off the order after the last stop wraps to the first; one before the first, back to the last", () => {
    const d = dialog();
    const tail = el("p", { tabindex: "-1" }, "a note after Cancel");
    const head = el("p", { tabindex: "-1" }, "a note before Close");
    d.container.append(tail);
    d.container.prepend(head);
    tail.focus();
    tab(d.container);
    expect(document.activeElement).toBe(d.close);
    head.focus();
    tab(d.container, true);
    expect(document.activeElement).toBe(d.cancel);
  });

  it("focus on the container itself, or outside it: Tab to the first stop, Shift+Tab to the last", () => {
    const d = dialog();
    d.container.focus();
    tab(d.container);
    expect(document.activeElement).toBe(d.close);
    d.container.focus();
    tab(d.container, true);
    expect(document.activeElement).toBe(d.cancel);
    (document.body.firstElementChild as HTMLElement).focus();
    tab(d.container);
    expect(document.activeElement).toBe(d.close);
  });
});
