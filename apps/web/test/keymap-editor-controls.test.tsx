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
});
let m: Awaited<ReturnType<typeof load>>;

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
  m.setAuditSink(() => undefined);
  const { HotkeyEditor, ShellAnnouncer } = m;
  render(
    <>
      <HotkeyEditor />
      <ShellAnnouncer />
    </>,
  );
});
afterEach(() => vi.useRealTimers());

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
    expect(row.getByRole("button", { name: /^Press keys now/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(polite()).toBe("Press the keys now. Esc cancels.");
    fireEvent.keyDown(rec, { key: "F6", ctrlKey: true });
    expect(polite()).toBe("Captured Ctrl+F6. Choose Save to apply it.");
    expect(row.getByRole("checkbox", { name: "Ctrl for Price zoom in" })).toBeChecked();
    expect(row.getByRole("textbox", { name: "Key for Price zoom in" })).toHaveValue("F6");
    fireEvent.click(row.getByRole("button", { name: /^Record\b/ }));
    fireEvent.keyDown(row.getByRole("button", { name: /^Press keys now/ }), { key: "Escape" });
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
    expect(document.querySelectorAll(".hk-noprint").length).toBeGreaterThan(3);
  });
});
