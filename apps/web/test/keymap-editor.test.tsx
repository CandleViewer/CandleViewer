import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditRecord } from "../src/keymap/audit";

/**
 * #305 (E10-S02) PR B: SCR-113's editor (R-202) over the conflict engine, in the minimal form BQ-8 rules. A conflict
 * offers a one-click Swap (AC3), Export sits beside Import (AC7), a locked command has no change control (AC4), and
 * every message goes through the shell announcer; the lens's A11Y-305B-01, -02, -04 to -06, CR-305B-02 and -06 and
 * DS-305B-03 and -04 too. A dangerous command on a single letter (D3, AC5) is PR A's. Each test loads its own copy of
 * the keymap modules, which keep their state at module level; queries stay inside one row, since the table has 76.
 */
const load = async () => ({
  ...(await import("../src/keymap/HotkeyEditor")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/features/app-shell/announcer")),
});
let m: Awaited<ReturnType<typeof load>>;
let audits: AuditRecord[];

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
  audits = [];
  m.setAuditSink((r) => audits.push(r));
});

function mount(): void {
  const { HotkeyEditor, ShellAnnouncer } = m;
  render(
    <>
      <HotkeyEditor />
      <ShellAnnouncer />
    </>,
  );
}
const rowOf = (label: string): HTMLElement => {
  const row = screen.getByText(label, { selector: 'th[scope="row"]' }).closest("tr");
  if (row === null) throw new Error(`no row for ${label}`);
  return row;
};
const inRow = (label: string) => within(rowOf(label));
/** A row's Save or Unbind by the visible word that leads its name (`Save Price zoom in`, A11Y-305BD-02). */
const SAVE = /^Save\b/;
const UNBIND = /^Unbind\b/;
const saveOf = (label: string): HTMLElement => inRow(label).getByRole("button", { name: SAVE });
function bind(label: string, key: string, mods: readonly string[] = []): void {
  const row = inRow(label);
  for (const mod of mods)
    fireEvent.click(row.getByRole("checkbox", { name: `${mod} for ${label}` }));
  fireEvent.change(row.getByRole("textbox", { name: `Key for ${label}` }), {
    target: { value: key },
  });
  fireEvent.click(row.getByRole("button", { name: SAVE }));
}
const polite = (): string => document.querySelector('[aria-live="polite"]')?.textContent ?? "";
const bound = (id: string): string | undefined => m.getBindings().get(id);
/** A row's key field, named for its row (A11Y-305B-06). */
const keyOf = (label: string): HTMLElement =>
  inRow(label).getByRole("textbox", { name: `Key for ${label}` });
/** The editor itself: its section, which the shell announcer sits outside. */
const editor = (): HTMLElement =>
  screen.getByText("Hotkeys", { selector: "h1, h2" }).closest("section") as HTMLElement;
/** The next element Tab reaches (jsdom has no Tab traversal): the tabbable elements in document order. */
const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
function nextTabStop(from: HTMLElement): Element | undefined {
  const stops = [...document.querySelectorAll(TABBABLE)];
  return stops[stops.indexOf(from) + 1];
}
/** A page-level button by its text: a role query would compute the names of every row's buttons. */
const button = (name: string): HTMLElement => screen.getByText(name, { selector: "button" });
const importBox = (): HTMLTextAreaElement =>
  screen.getByLabelText("Import keymap JSON") as HTMLTextAreaElement;
function importText(text: string): void {
  fireEvent.change(importBox(), { target: { value: text } });
  fireEvent.click(button("Import"));
}

describe("a conflict names both actions and offers a one-click swap (`05` §3.3 rule 2; AC3)", () => {
  const conflict =
    'Price zoom in: - is already bound to "Price zoom out" in the DOM context - reassign it or choose another key.';

  it("says it in the conflicting row, and through the shell announcer that a swap is available", () => {
    mount();
    bind("Price zoom in", "-");
    expect(inRow("Price zoom in").getByText(conflict)).toBeVisible();
    expect(polite()).toBe(`${conflict} Swap is available after Save.`);
    expect(document.querySelector('[role="alert"]')).toBeNull(); // the announcer speaks, never a region of its own
  });

  it("A11Y-305B-01: Swap follows Save in that row, so Tab reaches it next", () => {
    mount();
    bind("Price zoom in", "-");
    const swap = inRow("Price zoom in").getByRole("button", { name: "Swap" });
    expect(nextTabStop(saveOf("Price zoom in"))).toBe(swap);
  });

  it("Swap moves both keys in one step", () => {
    mount();
    bind("Price zoom in", "-");
    fireEvent.click(inRow("Price zoom in").getByRole("button", { name: "Swap" }));
    expect([bound("dom.zoom_in"), bound("dom.zoom_out")]).toEqual(["-", "+"]);
    expect(polite()).toBe("Price zoom in: -; Price zoom out: +");
  });

  it("after Swap the row's Save has focus again and Swap is gone", () => {
    mount();
    bind("Price zoom in", "-");
    fireEvent.click(inRow("Price zoom in").getByRole("button", { name: "Swap" }));
    expect(document.activeElement).toBe(saveOf("Price zoom in"));
    expect(screen.queryByText("Swap", { selector: "button" })).toBeNull();
  });

  it("offers no swap when the other command cannot take the key: Submit order on a bare S", () => {
    mount();
    bind("Set side Sell", "Enter", ["Ctrl"]);
    const row = inRow("Set side Sell");
    expect(row.getByText(/already bound to "Submit order" in the Ticket context/)).toBeVisible();
    expect(row.queryByRole("button", { name: "Swap" })).toBeNull();
    expect(bound("ticket.side_sell")).toBe("S");
  });

  it("a saved key that also serves an exclusive view names the other meaning (`05` §3.3 rule 1)", () => {
    mount();
    bind("Centre on mark", "B");
    expect(bound("dom.centre_mark")).toBe("B");
    expect(polite()).toBe(
      'Centre on mark: B; also bound to "Set side Buy" (Ticket), "Set bookmark" (Replay)',
    );
  });
});

describe("the locked rows and the acknowledgement (AC4)", () => {
  it("AC4: the palette and both Esc commands read 'not remappable' and have no change control", () => {
    mount();
    for (const label of ["Command palette", "Cancel in-progress drawing", "Clear ticket"]) {
      const row = inRow(label);
      expect(row.getByText("not remappable"), label).toBeVisible();
      expect(row.queryAllByRole("button"), label).toEqual([]);
    }
  });

  it("A11Y-305B-01: 'I understand, bind anyway' follows Save in the refused row", () => {
    mount();
    bind("Cancel all working orders for symbol", "Del");
    const ack = inRow("Cancel all working orders for symbol").getByRole("button", {
      name: "I understand, bind anyway",
    });
    expect(nextTabStop(saveOf("Cancel all working orders for symbol"))).toBe(ack);
  });

  it("acknowledged, a destructive command's other bare key is saved and audited", () => {
    mount();
    bind("Cancel all working orders for symbol", "Del");
    fireEvent.click(button("I understand, bind anyway"));
    expect(bound("dom.cancel_all")).toBe("Del");
    expect(audits).toEqual([
      expect.objectContaining({
        commandId: "dom.cancel_all",
        after: "Del",
        acknowledgedUnsafe: true,
      }),
    ]);
  });

  it("after the acknowledgement the row's Save has focus again", () => {
    mount();
    bind("Cancel all working orders for symbol", "Del");
    fireEvent.click(button("I understand, bind anyway"));
    expect(document.activeElement).toBe(saveOf("Cancel all working orders for symbol"));
  });

  it("A11Y-305B-05: the refusal says where the acknowledgement is, and names its command once (DS-305B-04)", () => {
    mount();
    bind("Cancel all working orders for symbol", "Del");
    const refusal =
      '"Cancel all working orders for symbol" is destructive; a bare key needs an explicit warning acknowledgement';
    expect(inRow("Cancel all working orders for symbol").getByText(refusal)).toBeVisible();
    expect(polite()).toBe(`${refusal}. The acknowledgement is after Save.`);
  });

  it("DS-305B-04: a dangerous single letter's refusal names its command once", () => {
    mount();
    bind("Submit order", "Y");
    expect(polite()).toBe(
      '"Submit order" needs Ctrl or Alt with a letter: Y alone could trigger it by accident',
    );
  });
});

describe("focus never goes to a disabled Save (A11Y-305B-05)", () => {
  it("Swap with the key field emptied hands focus to the row's key field", () => {
    mount();
    bind("Price zoom in", "-");
    fireEvent.change(keyOf("Price zoom in"), { target: { value: "" } });
    const swap = inRow("Price zoom in").getByRole("button", { name: "Swap" });
    swap.focus();
    fireEvent.click(swap);
    expect(bound("dom.zoom_in")).toBe("-");
    expect(document.activeElement).toBe(keyOf("Price zoom in"));
  });

  it("the acknowledgement with the key field emptied hands focus to the row's key field", () => {
    mount();
    bind("Cancel all working orders for symbol", "Del");
    fireEvent.change(keyOf("Cancel all working orders for symbol"), { target: { value: "" } });
    const ack = button("I understand, bind anyway");
    ack.focus();
    fireEvent.click(ack);
    expect(bound("dom.cancel_all")).toBe("Del");
    expect(document.activeElement).toBe(keyOf("Cancel all working orders for symbol"));
  });

  it("a Swap re-planned into a plain bind (the profile moved) hands focus back to the row's Save", () => {
    mount();
    bind("Price zoom in", "-");
    act(() => m.setBindings(new Map(m.getBindings()).set("dom.zoom_out", "Ctrl+Alt+J")));
    const swap = inRow("Price zoom in").getByRole("button", { name: "Swap" });
    swap.focus();
    fireEvent.click(swap);
    expect(bound("dom.zoom_in")).toBe("-");
    expect(document.activeElement).toBe(saveOf("Price zoom in"));
  });
});

describe("Unbind (WCAG 2.1.4; A11Y-305B-02)", () => {
  it("unbinds a command, says so, and audits a trading action", () => {
    mount();
    fireEvent.click(inRow("Submit order").getByRole("button", { name: UNBIND }));
    expect(bound("ticket.submit")).toBe("");
    expect(polite()).toBe("Submit order: unbound");
    expect(audits).toEqual([
      expect.objectContaining({ commandId: "ticket.submit", before: "Ctrl+Enter", after: "" }),
    ]);
  });

  it("then focus is on the row's key field, and its Unbind is disabled", () => {
    mount();
    fireEvent.click(inRow("Submit order").getByRole("button", { name: UNBIND }));
    const row = inRow("Submit order");
    expect(document.activeElement).toBe(row.getByRole("textbox", { name: "Key for Submit order" }));
    expect(row.getByRole("button", { name: UNBIND })).toBeDisabled();
  });
});

describe("names and states a reader gets (A11Y-305BD-02)", () => {
  it("an unbound command reads 'unbound' where its key was", () => {
    mount();
    fireEvent.click(inRow("Submit order").getByRole("button", { name: UNBIND }));
    expect(rowOf("Submit order").querySelectorAll("td")[1]).toHaveTextContent(/^unbound/);
  });

  it("each row's Save and Unbind have a name of their own that starts with the visible word (WCAG 2.5.3)", () => {
    mount();
    const buttons = [...document.querySelectorAll("tbody button")].filter((b) =>
      /^(?:Save|Unbind)$/.test(b.textContent ?? ""),
    );
    const names = buttons.map((b) => b.getAttribute("aria-label") ?? "");
    expect(new Set(names).size).toBe(buttons.length);
    buttons.forEach((b, i) => expect(names[i]).toMatch(new RegExp(`^${b.textContent ?? ""} `)));
    expect(inRow("Submit order").getByRole("button", { name: "Save Submit order" })).toBeVisible();
    expect(
      inRow("Submit order").getByRole("button", { name: "Unbind Submit order" }),
    ).toBeVisible();
  });

  it("A11Y-305B-06: each row's key field and modifier boxes have names of their own", () => {
    mount();
    const fields = [...document.querySelectorAll("tbody input")];
    const names = fields.map((f) => f.getAttribute("aria-label") ?? "");
    expect(new Set(names).size).toBe(fields.length);
    for (const view of ["DOM", "Ticket"]) {
      const arm = `Arm/disarm one-click (${view})`;
      expect(screen.getByLabelText(`Key for ${arm}`), view).toBeInTheDocument();
      expect(screen.getByLabelText(`Ctrl for ${arm}`), view).toBeInTheDocument();
    }
  });

  it("A11Y-305B-04: 'Hotkeys' is the page's h1", () => {
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Hotkeys" })).toBeVisible();
  });
});

describe("Import and Export (AC7; CR-305B-02; A11Y-305B-02)", () => {
  it("CR-305B-02: leaving the import box applies nothing", () => {
    mount();
    fireEvent.change(importBox(), { target: { value: '{"dom.zoom_in":"J"}' } });
    fireEvent.blur(importBox());
    expect(bound("dom.zoom_in")).toBe("+");
  });

  it("Import is disabled while the box is empty", () => {
    mount();
    expect(button("Import")).toBeDisabled();
  });

  it("Import applies the box and empties it", () => {
    mount();
    importText('{"dom.zoom_in":"J"}');
    expect([bound("dom.zoom_in"), importBox().value]).toEqual(["J", ""]);
  });

  it("A11Y-305BD-01: after a good import, focus is back in the emptied box, not on the disabled button", () => {
    mount();
    fireEvent.change(importBox(), { target: { value: '{"dom.zoom_in":"J"}' } });
    const go = button("Import");
    go.focus();
    fireEvent.click(go);
    expect(document.activeElement).toBe(importBox());
  });

  it("an import says how many entries it imported and refused, and that the rest are defaults (DS-305B-03)", () => {
    mount();
    importText('{"dom.zoom_in":"J","dom.zoom_out":"Ctrl+Banana"}');
    expect(polite()).toBe("Imported 1, 1 refused. Every other binding is at its default.");
  });

  it("DS-305B-03: an import replaces the profile: a remap the file does not list is back on its default", () => {
    act(() => m.setBindings(new Map(m.getBindings()).set("dom.zoom_out", "Ctrl+Alt+J")));
    mount();
    importText('{"dom.zoom_in":"Ctrl+Alt+K"}');
    expect([bound("dom.zoom_in"), bound("dom.zoom_out")]).toEqual(["Ctrl+Alt+K", "-"]);
  });

  it("an import lists each binding it refused", () => {
    mount();
    importText('{"dom.zoom_in":"Ctrl+Banana"}');
    const line = 'dom.zoom_in -> Ctrl+Banana: "Ctrl+Banana" is not a valid key binding';
    expect(within(screen.getByLabelText("Import report")).getByText(line)).toBeVisible();
  });

  it("text that is not JSON is said and shown once, and stays in the box (CR-305B-06, DS-305B-04)", () => {
    mount();
    importText('{"dom.zoom_in":"Ctrl+Banana"}'); // a report from an earlier import goes with the failure
    importText("{");
    expect(within(editor()).getAllByText("Import failed: not valid JSON")).toHaveLength(1);
    expect([polite(), importBox().value]).toEqual(["Import failed: not valid JSON", "{"]);
    expect(screen.queryByLabelText("Import report")).toBeNull();
  });

  it("DS-305B-04: valid JSON that is not an object is told apart from text that is not JSON", () => {
    mount();
    importText("[]");
    expect(polite()).toBe("Import failed: not a JSON object");
    expect(within(editor()).getAllByText("Import failed: not a JSON object")).toHaveLength(1);
  });

  it("Export puts the profile beside Import, focused, read-only and named by its label alone", () => {
    act(() => m.setBindings(new Map(m.getBindings()).set("dom.zoom_in", "J")));
    mount();
    fireEvent.click(button("Export"));
    const out = screen.getByLabelText("Export keymap (JSON)");
    expect([out.getAttribute("aria-label"), out.hasAttribute("readonly")]).toEqual([null, true]);
    expect(document.activeElement).toBe(out);
    expect(JSON.parse((out as HTMLTextAreaElement).value)).toMatchObject({ "dom.zoom_in": "J" });
  });

  it("AC7: an exported profile imports back after Reset all", () => {
    act(() => m.setBindings(new Map(m.getBindings()).set("dom.zoom_in", "J")));
    mount();
    fireEvent.click(button("Export"));
    const json = (screen.getByLabelText("Export keymap (JSON)") as HTMLTextAreaElement).value;
    fireEvent.click(button("Reset all"));
    expect(bound("dom.zoom_in")).toBe("+");
    importText(json);
    expect(bound("dom.zoom_in")).toBe("J");
    expect(screen.queryByLabelText("Import report")).toBeNull();
  });
});

describe("Reset all (D10; A11Y-305B-02)", () => {
  it("restores a trading binding through the audited rebind", () => {
    act(() => m.setBindings(new Map(m.getBindings()).set("ticket.submit", "Ctrl+Alt+Enter")));
    mount();
    fireEvent.click(button("Reset all"));
    expect(bound("ticket.submit")).toBe("Ctrl+Enter");
    expect(audits.map((a) => [a.commandId, a.before, a.after])).toEqual([
      ["ticket.submit", "Ctrl+Alt+Enter", "Ctrl+Enter"],
    ]);
  });

  it("says it reset", () => {
    mount();
    fireEvent.click(button("Reset all"));
    expect(polite()).toBe("Every binding is back to its default.");
  });
});
