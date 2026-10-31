import { describe, expect, it, vi } from "vitest";
import { DANGEROUS_COMMANDS, KEYMAP, getCommand } from "../src/keymap/keymap";
import { createDispatcher } from "../src/keymap/dispatcher";
import { importProfile, normaliseBinding, validateBinding } from "../src/keymap/validate";

const cur = () => new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));
const ev = (key: string, o: Record<string, boolean> = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...o,
});

describe("destructive defaults", () => {
  it("cancel-all and close-all require a modifier", () => {
    for (const id of ["dom.cancel_all", "positions.close_all"]) {
      expect(getCommand(id)?.defaultBinding).toMatch(/\+/);
    }
  });
});

describe("validateBinding", () => {
  it("refuses a same-context collision naming the other command", () => {
    const p = validateBinding("chart.footprint_mode", "Ctrl+Z", cur());
    expect(p?.kind).toBe("conflict");
    expect(p?.reason).toMatch(/Undo drawing/);
  });
  it("refuses a reserved key naming the platform", () => {
    const p = validateBinding("dom.cancel_all", "Ctrl+Shift+I", cur());
    expect(p?.kind).toBe("reserved");
    expect(p?.reason).toMatch(/devtools/);
  });
  it("pin: a bare non-letter key on a destructive command needs E49-S07's acknowledgement", () => {
    expect(validateBinding("dom.cancel_all", "Del", cur())?.kind).toBe("unsafe-destructive");
    expect(
      validateBinding("dom.cancel_all", "Del", cur(), undefined, { acknowledgedUnsafe: true }),
    ).toBeNull();
  });
  it("accepts a clean binding and rejects unknown ids and junk", () => {
    expect(validateBinding("dom.cancel_all", "Ctrl+Alt+X", cur())).toBeNull();
    expect(validateBinding("nope", "Ctrl+Alt+X", cur())?.kind).toBe("unknown-command");
    expect(validateBinding("dom.cancel_all", "Foo+X", cur())?.kind).toBe("invalid-binding");
  });
  it("normalises", () => {
    expect(normaliseBinding("shift+ctrl+x")).toBe("Ctrl+Shift+X");
  });
});

describe("BQ-3 / AC5: a dangerous command never takes a single unmodified letter (D3, CR-305A-02)", () => {
  it("D3: ticket.submit on a bare Y is refused with the accidental-trigger reason", () => {
    expect(validateBinding("ticket.submit", "Y", cur())).toEqual({
      kind: "accidental-trigger",
      reason: expect.stringMatching(/Submit order.*Y.*by accident/),
    });
  });

  it("AC5: no acknowledgement lifts it, on any dangerous command, and Shift+letter counts as a letter", () => {
    for (const id of DANGEROUS_COMMANDS) {
      for (const letter of ["Q", "Shift+Q"]) {
        const problem = validateBinding(id, letter, cur(), undefined, { acknowledgedUnsafe: true });
        expect(problem?.kind, `${id} ${letter}`).toBe("accidental-trigger");
      }
    }
  });

  it("D3: a stored ticket.submit on Y never runs on a bare y", () => {
    const execute = vi.fn();
    const bindings = new Map([["ticket.submit", "Y"]]);
    const d = createDispatcher({
      isValid: () => true,
      execute,
      notify: vi.fn(),
      now: () => 0,
      bindings,
    });
    expect(d(ev("y"), new Set(["Global", "Ticket"]))).toEqual({ status: "unbound" });
    expect(execute).not.toHaveBeenCalled();
  });

  it("AC5: an imported single letter on a dangerous command is reported, and the default kept", () => {
    const r = importProfile({ "ticket.submit": "Y" });
    expect(r.rejected).toEqual([
      {
        commandId: "ticket.submit",
        binding: "Y",
        problem: expect.objectContaining({ kind: "accidental-trigger" }),
      },
    ]);
    expect(r.applied.get("ticket.submit")).toBe("Ctrl+Enter");
  });

  it("pin: a letter on a command outside the dangerous set stays allowed", () => {
    expect(validateBinding("chart.footprint_toggle", "J", cur())).toBeNull();
  });
});

describe("importProfile", () => {
  it("applies safe bindings and lists unsafe ones with reasons", () => {
    const r = importProfile({
      "dom.cancel_all": "Ctrl+Alt+X",
      "chart.delete_drawing": "Ctrl+Z",
      "ticket.snap_bid": "Ctrl+Shift+I",
      "bogus.id": "Ctrl+Alt+Z",
    });
    expect(r.applied.get("dom.cancel_all")).toBe("Ctrl+Alt+X");
    expect(r.applied.get("chart.delete_drawing")).toBe("Del");
    expect(r.rejected.map((x) => x.problem.kind).sort()).toEqual([
      "conflict",
      "reserved",
      "unknown-command",
    ]);
  });
});

describe("dispatcher", () => {
  it("explains an inert press once per 5 s and executes nothing", () => {
    let t = 0;
    const notify = vi.fn();
    const execute = vi.fn();
    const d = createDispatcher({ isValid: () => false, execute, notify, now: () => t });
    const ctx = new Set(["Positions"]);
    const press = () => d(ev("W", { ctrlKey: true, shiftKey: true }), ctx);
    expect(press()).toMatchObject({ status: "inert", notified: true });
    t = 4999;
    expect(press()).toMatchObject({ notified: false });
    t = 5000;
    expect(press()).toMatchObject({ notified: true });
    expect(notify).toHaveBeenCalledTimes(2);
    expect(notify.mock.calls[0]?.[0]).toMatch(/Close all in view.*not available here/);
    expect(execute).not.toHaveBeenCalled();
  });
  it("executes when valid and ignores unbound keys", () => {
    const execute = vi.fn();
    const d = createDispatcher({ isValid: () => true, execute, notify: vi.fn(), now: () => 0 });
    const r = d(ev("W", { ctrlKey: true, shiftKey: true }), new Set(["Positions"]));
    expect(r.status).toBe("executed");
    expect(d(ev("F10"), new Set(["Global"])).status).toBe("unbound");
  });
});
