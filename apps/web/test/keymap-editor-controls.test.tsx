import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { KEYMAP } from "../src/keymap/keymap";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * E47-S08 slice 2: SCR-113's search, context filter, record-a-keystroke capture, per-binding reset, trading caution
 * note and printable list. Each test loads its own copy of the keymap modules (module-level state).
 */
const load = async () => ({
  ...(await import("../src/keymap/HotkeyEditor")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/features/app-shell/announcer")),
  ...(await import("../src/shell/bootstrap/themeStore")),
});
let m: Awaited<ReturnType<typeof load>>;
let audits: { action?: string }[];
let events: { name: string }[];
const onEvent = (e: Event): void => {
  events.push((e as CustomEvent<{ name: string }>).detail);
};

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
  audits = [];
  events = [];
  m.setAuditSink((r) => audits.push(r));
  window.addEventListener(m.THEME_ANALYTICS_EVENT, onEvent);
  const { HotkeyEditor, ShellAnnouncer } = m;
  render(
    <>
      <HotkeyEditor />
      <ShellAnnouncer />
    </>,
  );
});
afterEach(() => {
  vi.useRealTimers();
  window.removeEventListener(m.THEME_ANALYTICS_EVENT, onEvent);
});
const bindKey = (label: string, key: string, mods: readonly string[] = []): void => {
  const row = inRow(label);
  for (const mod of mods)
    fireEvent.click(row.getByRole("checkbox", { name: `${mod} for ${label}` }));
  fireEvent.change(row.getByRole("textbox", { name: `Key for ${label}` }), {
    target: { value: key },
  });
  fireEvent.click(row.getByRole("button", { name: /^Save\b/ }));
};

const polite = (): string => document.querySelector('[aria-live="polite"]')?.textContent ?? "";
const rowCount = (): number => document.querySelectorAll("tbody tr").length;
const inRow = (label: string) =>
  within(screen.getByText(label, { selector: 'th[scope="row"]' }).closest("tr") as HTMLElement);

describe("search and context filter", () => {
  it("filters by label and says one debounced count, never one per keystroke", () => {
    vi.useFakeTimers();
    const box = screen.getByLabelText("Search commands");
    const all = rowCount();
    for (const v of ["f", "fl", "flat"]) fireEvent.change(box, { target: { value: v } });
    expect(rowCount()).toBeLessThan(all);
    act(() => vi.advanceTimersByTime(300));
    expect(polite()).toBe("");
    act(() => vi.advanceTimersByTime(400));
    expect(polite()).toMatch(/^\d+ commands? match(es)?\.$/);
    expect(polite()).toBe(
      `${rowCount()} ${rowCount() === 1 ? "command matches" : "commands match"}.`,
    );
  });

  it("an empty result says so, in text", () => {
    vi.useFakeTimers();
    fireEvent.change(screen.getByLabelText("Search commands"), { target: { value: "zzzzqq" } });
    act(() => vi.advanceTimersByTime(700));
    expect(screen.getByText("No command matches.")).toBeVisible();
    expect(polite()).toBe("0 commands match.");
  });

  it("the Context select keeps one context's rows and announces the count", () => {
    vi.useFakeTimers();
    fireEvent.change(screen.getByLabelText("Context"), { target: { value: "DOM" } });
    expect(
      [...document.querySelectorAll("tbody tr")].every(
        (tr) => tr.querySelector("td")?.textContent?.startsWith("DOM") === true,
      ),
    ).toBe(true);
    act(() => vi.advanceTimersByTime(700));
    expect(polite()).toBe(`${rowCount()} commands match.`);
  });
});

describe("record a keystroke", () => {
  it("captures a chord into the row's fields, says so, and Esc cancels", () => {
    const row = inRow("Price zoom in");
    const rec = row.getByRole("button", { name: /^Record\b/ });
    rec.focus();
    fireEvent.click(rec);
    expect(row.getByRole("button", { name: /^Record\b/ })).toHaveAttribute("aria-pressed", "true");
    expect(row.getByText(/Press keys now/)).toBeVisible();
    expect(polite()).toBe("Press the keys now. Esc cancels.");
    fireEvent.keyDown(rec, { key: "F6", ctrlKey: true });
    expect(polite()).toBe("Captured Ctrl+F6. Choose Save to apply it.");
    expect(row.getByRole("checkbox", { name: "Ctrl for Price zoom in" })).toBeChecked();
    expect(row.getByRole("textbox", { name: "Key for Price zoom in" })).toHaveValue("F6");
    fireEvent.click(row.getByRole("button", { name: /^Record\b/ }));
    fireEvent.keyDown(row.getByRole("button", { name: /^Record\b/ }), { key: "Escape" });
    expect(polite()).toBe("Recording cancelled.");
    expect(row.getByRole("textbox", { name: "Key for Price zoom in" })).toHaveValue("F6");
  });
});

describe("reset one binding", () => {
  it("is disabled at the default; after a rebind it restores it and says so", () => {
    const row = inRow("Price zoom in");
    expect(row.getByRole("button", { name: /^Reset\b/ })).toBeDisabled();
    fireEvent.change(row.getByRole("textbox", { name: "Key for Price zoom in" }), {
      target: { value: "F6" },
    });
    fireEvent.click(row.getByRole("button", { name: /^Save\b/ }));
    const reset = row.getByRole("button", { name: /^Reset\b/ });
    expect(reset).toBeEnabled();
    fireEvent.click(reset);
    expect(m.getBindings().get("dom.zoom_in")).toBe(
      KEYMAP.find((c) => c.id === "dom.zoom_in")?.defaultBinding,
    );
    expect(polite()).toMatch(/^Price zoom in: back to its default, /);
    expect(row.getByRole("button", { name: /^Reset\b/ })).toBeDisabled();
  });
});

describe("caution note and print", () => {
  it("states the trading caution and marks trading commands in text", () => {
    expect(screen.getByText(/Trading commands .* rebinding one is audited\./)).toBeVisible();
    expect(screen.getAllByText("(trading)").length).toBeGreaterThan(0);
  });

  it("Print list calls window.print; controls carry the print-hidden class", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Print list" }));
    expect(print).toHaveBeenCalledOnce();
    expect(screen.getByRole("columnheader", { name: "Change" })).toHaveClass("hk-noprint");
    const row = inRow("Price zoom in");
    expect(row.getByRole("textbox", { name: /^Key\b/ }).closest("td")).toHaveClass("hk-noprint");
    expect(row.getByRole("button", { name: /^Unbind\b/ })).toHaveClass("hk-noprint");
    expect(row.getByRole("button", { name: /^Reset\b/ })).toHaveClass("hk-noprint");
  });
});

describe("review folds", () => {
  it("Reset onto a default another command took is refused, offers Swap, and audits nothing", () => {
    const cancel = KEYMAP.find((c) => c.id === "dom.cancel_all")?.label ?? "";
    bindKey(cancel, "X", ["Ctrl", "Alt"]);
    bindKey("Price zoom in", "X", ["Ctrl", "Shift"]); // cancel-all's default, now free
    expect(m.getBindings().get("dom.zoom_in")).toBe("Ctrl+Shift+X");
    audits.length = 0;
    events.length = 0;
    const before = new Map(m.getBindings());
    const row = inRow(cancel);
    fireEvent.click(row.getByRole("button", { name: /^Reset\b/ }));
    expect(row.getByText(/already bound to/)).toBeVisible();
    expect(row.getByRole("button", { name: "Swap" })).toBeVisible();
    expect(m.getBindings()).toEqual(before);
    expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Alt+X");
    expect(audits.filter((a) => a.action === "hotkey.trading_binding_changed")).toHaveLength(0);
    expect(events.map((e) => e.name)).toContain("hotkey.conflict_blocked");
    expect(events.map((e) => e.name)).not.toContain("hotkey.reset");
  });

  it("a successful Reset also emits hotkey.reset, and a trading command audits exactly once", () => {
    const label = KEYMAP.find((c) => c.id === "ticket.submit")?.label ?? "";
    bindKey(label, "Enter", ["Ctrl", "Alt"]);
    audits.length = 0;
    events.length = 0;
    fireEvent.click(inRow(label).getByRole("button", { name: /^Reset\b/ }));
    expect(audits.filter((a) => a.action === "hotkey.trading_binding_changed")).toHaveLength(1);
    expect(events.map((e) => e.name)).toContain("hotkey.reset");
  });

  it("Tab is not captured and cancels the recording; a blur says so", () => {
    const row = inRow("Price zoom in");
    const rec = row.getByRole("button", { name: /^Record\b/ });
    fireEvent.click(rec);
    expect(fireEvent.keyDown(rec, { key: "Tab" })).toBe(true); // not prevented
    expect(rec).toHaveAttribute("aria-pressed", "false");
    expect(polite()).toBe("Recording cancelled.");
    expect(row.getByRole("textbox", { name: "Key for Price zoom in" })).toHaveValue("");
    fireEvent.click(rec);
    rec.focus();
    fireEvent.blur(rec);
    expect(rec).toHaveAttribute("aria-pressed", "false");
    expect(polite()).toBe("Recording cancelled.");
  });

  it("the row being edited stays listed under a search; another row's focus releases it", () => {
    const row = inRow("Price zoom in");
    fireEvent.focus(row.getByRole("textbox", { name: "Key for Price zoom in" }));
    const search = screen.getByLabelText("Search commands");
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: "cancel all" } });
    expect(screen.getByText("Price zoom in", { selector: "th" })).toBeVisible();
    const rows = [...document.querySelectorAll("tbody tr")].filter(
      (tr) => tr.querySelector("th")?.textContent !== "Price zoom in",
    );
    const other = rows[0]?.querySelector("input:not([type=checkbox])");
    fireEvent.focus(other as Element);
    expect(screen.queryByText("Price zoom in", { selector: "th" })).toBeNull();
  });

  it("a stale message does not pin its row under a later filter, and a click off says cancelled", () => {
    bindKey("Price zoom in", "-"); // refused: Price zoom out holds it
    expect(inRow("Price zoom in").getByText(/already bound to/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Context"), { target: { value: "Chart" } });
    expect(screen.queryByText("Price zoom in", { selector: "th" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Context"), { target: { value: "*" } });
    const rec = inRow("Price zoom in").getByRole("button", { name: /^Record\b/ });
    fireEvent.click(rec);
    fireEvent.click(rec);
    expect(polite()).toBe("Recording cancelled.");
  });

  it("the context select's first option is a labelled sentinel, not a context", () => {
    const all = screen.getByRole("option", { name: "All contexts" }) as HTMLOptionElement;
    expect(all.value).toBe("*");
  });
});
