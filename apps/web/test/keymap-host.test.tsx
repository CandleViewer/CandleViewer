import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditRecord } from "../src/keymap/audit";

/**
 * The keymap modules keep state at module level: the audit sink and outbox, the live bindings and
 * their listeners, the registered command handlers, the editor's pending bindings. Every test loads
 * its own copy after a reset, so none sees another's state or depends on the order they run in, and
 * the components under test and the functions the assertions call are the same instance. (A static
 * import is a second copy once the reload test below has reset the registry.)
 */
const load = async () => ({
  ...(await import("../src/keymap/KeymapHost")),
  ...(await import("../src/keymap/HotkeyEditor")),
  ...(await import("../src/keymap/Cheatsheet")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/keymap/profile")),
});
let mods: Awaited<ReturnType<typeof load>>;

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
    const host = screen.getByTestId("toast-host");
    expect(host).toHaveAttribute("role", "status");
    expect(host.querySelectorAll("p")).toHaveLength(1);
    expect(host.textContent).toMatch(/Cancel all working orders/);
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
  it("refuses conflict naming both, refuses reserved with platform, audits destructive rebind", () => {
    const { HotkeyEditor, getBindings, setAuditSink } = mods;
    const audits: AuditRecord[] = [];
    setAuditSink((r) => audits.push(r));
    render(<HotkeyEditor />);
    const row = (label: string) => screen.getByText(label).closest("tr") as HTMLElement;
    const bind = (label: string, key: string, ctrlShift = false) => {
      const r = row(label);
      const inp = r.querySelector("input[type=text], input:not([type])") as HTMLInputElement;
      fireEvent.change(inp, { target: { value: key } });
      if (ctrlShift) {
        r.querySelectorAll("input[type=checkbox]").forEach((c, i) => i !== 1 && fireEvent.click(c));
      }
      fireEvent.click(r.querySelector("button") as HTMLElement);
    };
    bind("Cancel in-progress drawing", "I", true);
    expect(screen.getByRole("alert").textContent).toMatch(/reserved by/);
    bind("Delete selected drawing", "Esc");
    expect(screen.getByRole("alert").textContent).toMatch(/Cancel in-progress drawing/);
    bind("Cancel all working orders for symbol", "Q");
    expect(screen.getByRole("alert").textContent).toMatch(/destructive/);
    fireEvent.click(screen.getByText("I understand, bind anyway"));
    expect(getBindings().get("dom.cancel_all")).toBe("Q");
    expect(audits[0]).toMatchObject({ action: "hotkey.trading_binding_changed", after: "Q" });
  });
  it("import applies safe, lists unsafe", () => {
    const { HotkeyEditor, getBindings } = mods;
    render(<HotkeyEditor />);
    const ta = screen.getByLabelText("Import keymap JSON") as HTMLTextAreaElement;
    fireEvent.change(ta, {
      target: { value: JSON.stringify({ "dom.cancel_all": "Ctrl+Shift+I" }) },
    });
    fireEvent.blur(ta);
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
    // Key and record shape as audit.ts persists them (STORE_KEY there; it is not exported).
    const record: AuditRecord = {
      action: "hotkey.trading_binding_changed",
      commandId: "dom.cancel_all",
      before: "Ctrl+Shift+X",
      after: "Q",
      acknowledgedUnsafe: true,
    };
    window.localStorage.setItem("cv.hotkey-audit-outbox.v1", JSON.stringify([record]));
    vi.resetModules();
    const { auditOutbox } = await import("../src/keymap/audit");
    expect(auditOutbox()).toEqual([record]);
  });
});

describe("profile persistence + Rules-context inert explanation", () => {
  it("rebinds survive a module reload (localStorage)", async () => {
    const { getBindings, setBindings } = mods;
    act(() => setBindings(new Map(getBindings()).set("dom.cancel_all", "Q")));
    vi.resetModules();
    const fresh = await import("../src/keymap/profile");
    expect(fresh.getBindings().get("dom.cancel_all")).toBe("Q");
    fresh.resetBindings();
    vi.resetModules();
    expect((await import("../src/keymap/profile")).getBindings().get("dom.cancel_all")).toBe(
      "Ctrl+Shift+X",
    );
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
    expect(screen.getByTestId("toast-host")).toHaveTextContent(
      /Save draft is not available here \(Rules view\)/,
    );
    off();
  });
});
