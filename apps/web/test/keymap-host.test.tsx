import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditRecord } from "../src/keymap/audit";

/**
 * The keymap modules keep state at module level: the audit sink and outbox, the live bindings and
 * their listeners, the registered command handlers, the editor's pending bindings. Every test loads
 * its own copy after a reset, so none sees another's state or depends on the order they run in, and
 * the components under test and the functions the assertions call are the same instance. (A static
 * import is bound once, at file load, so after the reload test below resets the registry it is a
 * different copy from every later import.)
 */
const load = async () => ({
  ...(await import("../src/keymap/KeymapHost")),
  ...(await import("../src/keymap/HotkeyEditor")),
  ...(await import("../src/keymap/Cheatsheet")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/lib/auth/meCache")),
  ...(await import("../src/shell/bootstrap/store")),
});
let mods: Awaited<ReturnType<typeof load>>;

/**
 * An Owner signed in, as the bootstrap applies `/me` (#305, A55): the profile and the audit outbox are keyed by the
 * user, and the audit is sent only for a session holding `settings:write`.
 */
function signIn(m: Pick<typeof mods, "setMeClaims" | "setShellState"> = mods): void {
  const permissions = ["settings:read", "settings:write"];
  m.setMeClaims({ authenticated: true, role: "owner", permissions });
  m.setShellState({
    me: {
      accounts: [],
      permissions,
      role: "owner",
      user: {
        id: "u-1",
        email: "u@example.test",
        username: "u",
        roles: ["owner"],
        status: "active",
      },
    },
  });
}

beforeEach(async () => {
  // The profile and the audit outbox persist in localStorage, and a module reads it when it loads.
  window.localStorage.clear();
  vi.resetModules();
  mods = await load();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("inert press explains itself (wired host)", () => {
  it("toasts once per 5s, executes nothing", () => {
    const { KeymapHost, registerCommand } = mods;
    const run = vi.fn();
    const off = registerCommand("dom.cancel_all", run, () => false);
    render(
      <div data-keymap-context="DOM">
        <input aria-label="f" />
        <KeymapHost />
      </div>,
    );
    screen.getByLabelText("f").focus();
    for (let i = 0; i < 3; i++)
      fireEvent.keyDown(window, { key: "X", ctrlKey: true, shiftKey: true });
    expect(run).not.toHaveBeenCalled();
    const host = screen.getByRole("region", { name: "Notifications" });
    expect(within(host).getAllByRole("group")).toHaveLength(1);
    expect(host.textContent).toMatch(/Cancel all working orders/);
    off();
  });
  it("keeps a toast past 60 s until dismissed, gives each press its own id and caps the queue (#5197)", async () => {
    vi.useFakeTimers();
    const { KeymapHost, registerCommand, KEYMAP_TOAST_MAX } = mods;
    const { ShellAnnouncer, clearAnnouncements } =
      await import("../src/features/app-shell/announcer");
    const off = registerCommand("dom.cancel_all", vi.fn(), () => false);
    render(
      <div data-keymap-context="DOM">
        <input aria-label="f" />
        <ShellAnnouncer />
        <KeymapHost />
      </div>,
    );
    screen.getByLabelText("f").focus();
    const press = () => {
      fireEvent.keyDown(window, { key: "X", ctrlKey: true, shiftKey: true });
    };
    const groups = () =>
      within(screen.getByRole("region", { name: "Notifications" })).queryAllByRole("group");
    press();
    act(() => void vi.advanceTimersByTime(60_000));
    expect(groups()).toHaveLength(1);
    // a second press (past the dispatcher's 5 s window) is a second toast, spoken again
    press();
    expect(groups()).toHaveLength(2);
    const polite = document.querySelector('[aria-live="polite"]');
    expect(polite?.textContent).toMatch(/Cancel all working orders/);
    fireEvent.click(within(groups()[0] as HTMLElement).getByRole("button", { name: /Dismiss/ }));
    expect(groups()).toHaveLength(1);
    fireEvent.click(within(groups()[0] as HTMLElement).getByRole("button", { name: /Dismiss/ }));
    expect(screen.queryByRole("group")).toBeNull();
    for (let i = 0; i < KEYMAP_TOAST_MAX + 2; i++) {
      act(() => void vi.advanceTimersByTime(6000));
      press();
    }
    expect(groups()).toHaveLength(KEYMAP_TOAST_MAX);
    clearAnnouncements();
    off();
  });
  it("executes when valid", () => {
    const { KeymapHost, registerCommand } = mods;
    const run = vi.fn();
    const off = registerCommand("dom.cancel_all", run);
    render(
      <div data-keymap-context="DOM">
        <input aria-label="f" />
        <KeymapHost />
      </div>,
    );
    screen.getByLabelText("f").focus();
    fireEvent.keyDown(window, { key: "X", ctrlKey: true, shiftKey: true });
    expect(run).toHaveBeenCalledTimes(1);
    off();
  });
});

describe("SCR-113 editor", () => {
  // #305 PR B: the Esc commands are locked (BQ-7) and the shell announcer speaks a message, never a role="alert".
  // Queries stay inside one row: the table has 75 (CR-305B-06).
  const inRow = (label: string) => {
    const th = screen.getByText(label, { selector: 'th[scope="row"]' });
    return within(th.closest("tr") as HTMLElement);
  };
  const bind = (label: string, key: string, keys: readonly string[] = []) => {
    const row = inRow(label);
    for (const k of keys) fireEvent.click(row.getByRole("checkbox", { name: `${k} for ${label}` }));
    fireEvent.change(row.getByRole("textbox", { name: `Key for ${label}` }), {
      target: { value: key },
    });
    fireEvent.click(row.getByRole("button", { name: /^Save\b/ })); // `Save <label>` (A11Y-305BD-02)
  };

  it("refuses a reserved key, naming the platform", () => {
    const { HotkeyEditor } = mods;
    render(<HotkeyEditor />);
    bind("Toggle footprint", "I", ["Ctrl", "Shift"]);
    const row = inRow("Toggle footprint");
    expect(row.getByText(/Ctrl\+Shift\+I is reserved by browser\/Electron/)).toBeVisible();
  });

  it("refuses a conflict, naming the other command", () => {
    const { HotkeyEditor } = mods;
    render(<HotkeyEditor />);
    bind("Delete selected drawing", "Z", ["Ctrl"]);
    const row = inRow("Delete selected drawing");
    expect(row.getByText(/already bound to "Undo drawing" in the Chart context/)).toBeVisible();
  });

  it("audits a destructive rebind made on the acknowledgement", () => {
    const { HotkeyEditor, getBindings, setAuditSink } = mods;
    const audits: AuditRecord[] = [];
    setAuditSink((r) => audits.push(r));
    render(<HotkeyEditor />);
    bind("Cancel all working orders for symbol", "Del");
    const row = inRow("Cancel all working orders for symbol");
    expect(row.getByText(/is destructive; a bare key needs an explicit/)).toBeVisible();
    fireEvent.click(row.getByRole("button", { name: "I understand, bind anyway" }));
    expect(getBindings().get("dom.cancel_all")).toBe("Del");
    expect(audits[0]).toMatchObject({ action: "hotkey.trading_binding_changed", after: "Del" });
  });

  it("AC5 (BQ-3): a single letter on a dangerous command is refused, with no acknowledgement to lift it", () => {
    const { HotkeyEditor, getBindings } = mods;
    render(<HotkeyEditor />);
    bind("Cancel all working orders for symbol", "Q");
    expect(screen.getByText(/could trigger it by accident/)).toBeVisible();
    expect(screen.queryByText("I understand, bind anyway")).toBeNull();
    expect(getBindings().get("dom.cancel_all")).toBe("Ctrl+Shift+X");
  });
  it("import applies safe, lists unsafe", () => {
    const { HotkeyEditor, getBindings } = mods;
    render(<HotkeyEditor />);
    const ta = screen.getByLabelText("Import keymap JSON") as HTMLTextAreaElement;
    fireEvent.change(ta, {
      target: { value: JSON.stringify({ "dom.cancel_all": "Ctrl+Shift+I" }) },
    });
    fireEvent.click(screen.getByText("Import", { selector: "button" })); // #305 CR-305B-02: no apply on blur
    expect(screen.getByLabelText("Import report").textContent).toMatch(/reserved/);
    expect(getBindings().get("dom.cancel_all")).not.toBe("Ctrl+Shift+I");
  });
});

describe("SCR-013 cheatsheet", () => {
  it("renders real tables and flags conflicts", () => {
    const { Cheatsheet, getBindings, setBindings } = mods;
    act(() => setBindings(new Map(getBindings()).set("chart.delete_drawing", "Esc")));
    render(<Cheatsheet />);
    expect(screen.getAllByRole("table").length).toBeGreaterThan(3);
    expect(screen.getByRole("link", { name: "Customise" })).toHaveAttribute(
      "href",
      "/settings/hotkeys",
    );
    expect(screen.getAllByLabelText(/conflicting binding/).length).toBeGreaterThan(0);
  });
});

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

describe("SCR-013 cheatsheet is a modal dialog (D-03, A11Y-F-0026)", () => {
  function openFrom(): { opener: HTMLElement; dialog: HTMLElement } {
    const { KeymapHost } = mods;
    render(
      <>
        <button type="button">Open terminal</button>
        <KeymapHost />
      </>,
    );
    const opener = screen.getByRole("button", { name: "Open terminal" });
    opener.focus();
    fireEvent.keyDown(opener, { key: "/", code: "Slash", ctrlKey: true });
    return { opener, dialog: screen.getByRole("dialog", { name: "Keyboard shortcuts" }) };
  }

  it("Ctrl+/ moves focus into the modal dialog; Esc closes it and focus returns to the trigger", async () => {
    const { opener, dialog } = openFrom();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    // jsdom has no layout; contrast is the real-browser collectors'
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape", code: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
    expect(opener).toHaveFocus();
    expect(screen.getByTestId("toast-host")).toBeEmptyDOMElement();
  });

  it("Tab cycles inside the dialog, and Close returns focus to the trigger", () => {
    const { opener, dialog } = openFrom();
    const customise = screen.getByRole("link", { name: "Customise" });
    const close = screen.getByRole("button", { name: "Close" });
    fireEvent.keyDown(dialog, { key: "Tab" }); // Close is the last stop
    expect(customise).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(close).toHaveFocus();
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});

describe("D-19 (#5196): Ctrl+A in a dialog's text field selects its text, no hotkey toast", () => {
  it("leaves the toast host empty and the key unprevented", () => {
    const { KeymapHost } = mods;
    render(
      <div data-keymap-context="Rules">
        <div role="alertdialog" aria-label="Confirm with two-factor">
          <input aria-label="Type sub_002 to confirm" />
        </div>
        <KeymapHost />
      </div>,
    );
    const input = screen.getByLabelText("Type sub_002 to confirm");
    input.focus();
    expect(fireEvent.keyDown(input, { key: "a", code: "KeyA", ctrlKey: true })).toBe(true);
    expect(screen.getByTestId("toast-host")).toBeEmptyDOMElement();
  });
});

describe("wiring (review fixes)", () => {
  it("Ctrl+/ opens the cheatsheet through the registered command", () => {
    const { KeymapHost } = mods;
    render(<KeymapHost />);
    fireEvent.keyDown(window, { key: "/", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });
  it("default audit transport reaches the outbox", async () => {
    const { KeymapHost, applyRebind, auditOutbox, flushAuditOutbox, getBindings, setAuditSink } =
      mods;
    setAuditSink((r) => window.dispatchEvent(new CustomEvent("cv:audit", { detail: r })));
    signIn();
    render(<KeymapHost />);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    const n = auditOutbox().length;
    act(() => void applyRebind(getBindings(), "dom.cancel_all", "Q", true));
    expect(auditOutbox()).toHaveLength(n + 1);
    expect(auditOutbox()[n]).toMatchObject({ action: "hotkey.trading_binding_changed" });
    await flushAuditOutbox();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    await flushAuditOutbox(); // server recovers: durable outbox drains
    expect(auditOutbox()).toHaveLength(0);
    vi.unstubAllGlobals();
  });
});

describe("audit is transmitted server-side", () => {
  it("POSTs hotkey.trading_binding_changed fields to /settings/hotkey-audit", async () => {
    const { applyRebind, auditOutbox, recordAudit, setAuditSink } = mods;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    signIn();
    setAuditSink(recordAudit);
    applyRebind(new Map([["dom.cancel_all", "Ctrl+Shift+X"]]), "dom.cancel_all", "X", true);
    await vi.waitFor(() => expect(auditOutbox()).toHaveLength(0));
    const calls = fetchMock.mock.calls as [string, RequestInit][];
    expect(calls.every(([u]) => u === "/api/v1/settings/hotkey-audit")).toBe(true);
    const bodies = calls.map(([, i]) => JSON.parse(String(i.body)) as unknown);
    expect(bodies).toContainEqual({
      command_id: "dom.cancel_all",
      before: "Ctrl+Shift+X",
      after: "X",
      acknowledged_unsafe: true,
    });
    vi.unstubAllGlobals();
  });
  it("a persisted outbox is read back when the audit module loads", async () => {
    // Key and record shape as audit.ts persists them (STORE_KEY there, per user since A55; it is not exported).
    const record: AuditRecord = {
      action: "hotkey.trading_binding_changed",
      commandId: "dom.cancel_all",
      before: "Ctrl+Shift+X",
      after: "Q",
      acknowledgedUnsafe: true,
    };
    window.localStorage.setItem("cv.hotkey-audit-outbox.v1:u-1", JSON.stringify([record]));
    vi.resetModules();
    const { auditOutbox } = await import("../src/keymap/audit");
    signIn(await load());
    expect(auditOutbox()).toEqual([record]);
  });
});

describe("profile persistence + Rules-context inert explanation", () => {
  it("rebinds survive a module reload (localStorage)", async () => {
    const { getBindings, setBindings } = mods;
    signIn();
    // An acknowledged bare key: a stored single letter on it would be dropped at load (#305, CR-305B-05).
    act(() => setBindings(new Map(getBindings()).set("dom.cancel_all", "Del")));
    vi.resetModules();
    const fresh = await import("../src/keymap/profile");
    signIn(await load()); // the reload's own bootstrap names the same user
    expect(fresh.getBindings().get("dom.cancel_all")).toBe("Del");
    fresh.resetBindings();
    vi.resetModules();
    const again = await import("../src/keymap/profile");
    signIn(await load());
    expect(again.getBindings().get("dom.cancel_all")).toBe("Ctrl+Shift+X");
  });

  it("explains an inert Rules command when the editor context is not valid", () => {
    const { KeymapHost, registerCommand } = mods;
    const off = registerCommand("rules.save_draft", vi.fn(), () => false);
    render(
      <div data-keymap-context="Rules">
        <input aria-label="rule editor" />
        <KeymapHost />
      </div>,
    );
    screen.getByLabelText("rule editor").focus();
    fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
      /Save draft is not available here \(Rules view\)/,
    );
    off();
  });
});

describe("#305 PR A: the typing guard in the wired host (AC6, D6, D7, D8, G-07)", () => {
  it("AC6: `/` opens symbol search from the page; typed in a text field it is neither prevented nor run", () => {
    const { KeymapHost, registerCommand } = mods;
    const open = vi.fn();
    const off = registerCommand("global.symbol_search", open);
    render(
      <>
        <button type="button">Journal row</button>
        <input aria-label="Notes" />
        <KeymapHost />
      </>,
    );
    const row = screen.getByRole("button", { name: "Journal row" });
    row.focus();
    expect(fireEvent.keyDown(row, { key: "/", code: "Slash" })).toBe(false); // the keymap took it
    const notes = screen.getByLabelText("Notes");
    notes.focus();
    expect(fireEvent.keyDown(notes, { key: "/", code: "Slash" })).toBe(true); // typed
    // A key dispatched at the window reads the focused element as its target.
    expect(fireEvent.keyDown(window, { key: "/", code: "Slash" })).toBe(true);
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
    off();
  });

  it("D6, D7: a `b` typed in a field and an Esc post nothing where nothing takes them", () => {
    const { KeymapHost } = mods;
    render(
      <>
        <input aria-label="Search journal" />
        <button type="button">Journal row</button>
        <KeymapHost />
      </>,
    );
    const search = screen.getByLabelText("Search journal");
    search.focus();
    fireEvent.keyDown(search, { key: "b", code: "KeyB" });
    const row = screen.getByRole("button", { name: "Journal row" });
    row.focus();
    for (let i = 0; i < 2; i++) fireEvent.keyDown(row, { key: "Escape", code: "Escape" });
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
  });

  it("D6: in a ticket a typed `b` stays text, and so does a key a control took first or an IME composes", () => {
    const { KeymapHost, registerCommand } = mods;
    const side = vi.fn();
    const off = registerCommand("ticket.side_buy", side);
    render(
      <div data-keymap-context="Ticket">
        <input aria-label="Quantity" />
        <button type="button" onKeyDown={(e) => e.preventDefault()}>
          Buy
        </button>
        <button type="button">Ticket</button>
        <KeymapHost />
      </div>,
    );
    const quantity = screen.getByLabelText("Quantity");
    quantity.focus();
    expect(fireEvent.keyDown(quantity, { key: "b", code: "KeyB" })).toBe(true);
    const buy = screen.getByRole("button", { name: "Buy" });
    buy.focus();
    fireEvent.keyDown(buy, { key: "b", code: "KeyB" });
    const ticket = screen.getByRole("button", { name: "Ticket" });
    ticket.focus();
    fireEvent.keyDown(ticket, { key: "b", code: "KeyB", isComposing: true });
    expect(side).not.toHaveBeenCalled();
    fireEvent.keyDown(ticket, { key: "b", code: "KeyB" }); // the control: the ticket itself takes `b`
    expect(side).toHaveBeenCalledTimes(1);
    off();
  });

  it("CR-305AD-02: through the host, a key an IME took (keyCode 229) runs nothing: Safari's Enter ending a composition", () => {
    const { KeymapHost, registerCommand } = mods;
    const submit = vi.fn();
    const off = registerCommand("global.auth.submit", submit);
    render(
      <div data-keymap-context="Auth">
        <input aria-label="Username" />
        <KeymapHost />
      </div>,
    );
    const username = screen.getByLabelText("Username");
    username.focus();
    fireEvent.keyDown(username, { key: "Enter", code: "Enter", keyCode: 229 });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.keyDown(username, { key: "Enter", code: "Enter", keyCode: 13 }); // the control: a plain Enter submits
    expect(submit).toHaveBeenCalledTimes(1);
    off();
  });

  it("pin: D6, ruled option (c): a focused button's Tab, Enter, Space and arrows post nothing, in any context", () => {
    const { KeymapHost } = mods;
    render(
      <>
        <button type="button">Export</button>
        {/* Views that bind each key, so the button is in their contexts too (A11Y-305A-01). */}
        <div data-keymap-context="Rules">
          <div data-keymap-context="Positions">
            <div data-keymap-context="Replay">
              <button type="button">Bookmark</button>
            </div>
          </div>
        </div>
        <KeymapHost />
      </>,
    );
    for (const name of ["Export", "Bookmark"]) {
      const focused = screen.getByRole("button", { name });
      focused.focus();
      for (const key of ["Tab", "Enter", " ", "ArrowRight", "ArrowDown"]) {
        fireEvent.keyDown(focused, { key });
      }
    }
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
  });

  it("G-07: a held Ctrl+/ opens the cheatsheet once; its auto-repeat is taken, not toggled", () => {
    const { KeymapHost } = mods;
    render(<KeymapHost />);
    fireEvent.keyDown(window, { key: "/", code: "Slash", ctrlKey: true });
    for (let i = 0; i < 3; i++) {
      const held = fireEvent.keyDown(window, {
        key: "/",
        code: "Slash",
        ctrlKey: true,
        repeat: true,
      });
      expect(held).toBe(false);
    }
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });

  it("D8: F11 in a focused panel runs the declared panel full-screen, with no Global handler and no notice", () => {
    const { KeymapHost, registerCommand } = mods;
    const panel = vi.fn();
    const off = registerCommand("workspace.fullscreen_panel", panel);
    render(
      <div data-keymap-context="Workspace">
        <button type="button">Chart 1</button>
        <KeymapHost />
      </div>,
    );
    const chart = screen.getByRole("button", { name: "Chart 1" });
    chart.focus();
    expect(fireEvent.keyDown(chart, { key: "F11", code: "F11" })).toBe(false);
    expect(panel).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
    off();
  });

  it("BQ-4: the cheatsheet shows a declared shadow's rationale beside its key", () => {
    const { Cheatsheet } = mods;
    render(<Cheatsheet />);
    const workspace = screen.getByRole("table", { name: "Workspace" });
    const row = within(workspace).getByRole("row", { name: /^Full-screen active panel/ });
    // after the key, the reviewed override's mark (E10-D04 §15, #305 DS-305B-02), then the rationale
    expect(row).toHaveTextContent(
      "F11 reserved by the browser or OS Active panel full-screen wins while a panel is focused",
    );
    const global = screen.getByRole("table", { name: "Global" });
    const own = within(global).getByRole("row", { name: /^Full-screen workspace/ });
    expect(own).not.toHaveTextContent("wins while");
  });
});
