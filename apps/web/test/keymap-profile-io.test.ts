import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditRecord } from "../src/keymap/audit";

/**
 * #305 (E10-S02) PR B: `profileIo.ts`, the profile's JSON out and in (AC7) and the changes that land through the
 * audited rebind (D10): applying an import, a swap and reset-all; and what a stored profile may bring back at load,
 * checked as one profile (CR-305B-05, CR-305B-06, SEC-305B-01). The modules keep their state at module level (the
 * audit sink, the live profile), so each test loads its own copy.
 */
const load = async () => ({
  ...(await import("../src/keymap/profileIo")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/keymap/keymap")),
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

const defaults = (): Map<string, string> => new Map(m.KEYMAP.map((c) => [c.id, c.defaultBinding]));

describe("export and parse (AC7)", () => {
  it("writes every command's binding as JSON in keymap order, an unbound one as an empty string", () => {
    const mine = defaults().set("dom.zoom_in", "J").set("global.symbol_search", "");
    const out = JSON.parse(m.exportProfile(mine)) as Record<string, string>;
    expect(Object.keys(out)).toEqual(m.KEYMAP.map((c) => c.id));
    expect([out["dom.zoom_in"], out["global.symbol_search"], out["global.palette"]]).toEqual([
      "J",
      "",
      "Ctrl+K",
    ]);
  });

  it("parses a JSON object and refuses text that is not JSON with the shipped message", () => {
    expect(m.parseProfile('{"dom.zoom_in":"J"}')).toEqual({
      ok: true,
      profile: { "dom.zoom_in": "J" },
    });
    expect(m.parseProfile("{")).toEqual({ ok: false, reason: "Import failed: not valid JSON" });
  });

  it("DS-305B-04: valid JSON that is not an object has a message of its own", () => {
    for (const text of ["[]", '"J"', "null", "3"]) {
      expect(m.parseProfile(text), text).toEqual({
        ok: false,
        reason: "Import failed: not a JSON object",
      });
    }
  });

  it("AC7: an exported profile imports into a clean one identically, a swap and an unbind included", () => {
    const mine = defaults()
      .set("dom.zoom_in", "-")
      .set("dom.zoom_out", "+")
      .set("global.symbol_search", "")
      .set("ticket.submit", "Ctrl+Alt+Enter");
    const parsed = m.parseProfile(m.exportProfile(mine));
    if (!parsed.ok) throw new Error(parsed.reason);
    const report = m.importProfile(parsed.profile);
    expect(report.rejected).toEqual([]);
    expect([...m.applyImport(defaults(), report)]).toEqual([...mine]);
  });
});

describe("D10: every change goes through the audited rebind", () => {
  it("an import audits each trading binding it changes, and only those", () => {
    const report = m.importProfile({ "ticket.submit": "Ctrl+Alt+Enter", "dom.zoom_in": "J" });
    const next = m.applyImport(defaults(), report);
    expect([next.get("ticket.submit"), next.get("dom.zoom_in")]).toEqual(["Ctrl+Alt+Enter", "J"]);
    expect(audits.map((a) => [a.commandId, a.before, a.after])).toEqual([
      ["ticket.submit", "Ctrl+Enter", "Ctrl+Alt+Enter"],
    ]);
  });

  it("a swap lands both moves in one profile and audits its trading side", () => {
    const next = m.applySwap(defaults(), {
      a: "ticket.submit",
      aTo: "Alt+B",
      b: "ticket.snap_bid",
      bTo: "Ctrl+Enter",
    });
    expect([next.get("ticket.submit"), next.get("ticket.snap_bid")]).toEqual([
      "Alt+B",
      "Ctrl+Enter",
    ]);
    expect(audits.map((a) => [a.commandId, a.after])).toEqual([["ticket.submit", "Alt+B"]]);
  });

  it("a binding made on the acknowledgement is audited outside the dangerous set too (re-check nit b)", () => {
    const next = m.applyRebind(defaults(), "dom.zoom_in", "Ctrl+Alt+J", true);
    expect(next.get("dom.zoom_in")).toBe("Ctrl+Alt+J");
    expect(audits).toEqual([
      {
        action: m.TRADING_BINDING_CHANGED,
        commandId: "dom.zoom_in",
        before: "+",
        after: "Ctrl+Alt+J",
        acknowledgedUnsafe: true,
      },
    ]);
    m.applyRebind(defaults(), "dom.zoom_in", "Ctrl+Alt+J"); // the same rebind, unacknowledged
    expect(audits).toHaveLength(1);
  });

  it("reset-all restores every default and audits each trading binding it restores", () => {
    const next = m.resetAll(defaults().set("dom.arm", "Ctrl+Alt+T").set("dom.zoom_in", "J"));
    expect([...next]).toEqual([...defaults()]);
    expect(audits.map((a) => [a.commandId, a.before, a.after])).toEqual([
      ["dom.arm", "Ctrl+Alt+T", "Ctrl+Shift+T"],
    ]);
  });
});

describe("a stored profile is checked when it loads (CR-305B-05)", () => {
  /**
   * The live profile a fresh load makes of `stored`, under the signed-in user's key as profile.ts persists it (A55:
   * `cv.keymap-profile.v1:<user id>`), once `/me` names that user.
   */
  async function loadWith(
    stored: Readonly<Record<string, string>>,
  ): Promise<ReadonlyMap<string, string>> {
    window.localStorage.setItem("cv.keymap-profile.v1:u-1", JSON.stringify(stored));
    vi.resetModules();
    const profile = await import("../src/keymap/profile");
    const { setShellState } = await import("../src/shell/bootstrap/store");
    setShellState({
      me: {
        accounts: [],
        permissions: [],
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
    return profile.getBindings();
  }

  it("drops a stored reserved key: a legacy zoom on Esc is back on +", async () => {
    expect((await loadWith({ "dom.zoom_in": "Esc" })).get("dom.zoom_in")).toBe("+");
  });

  it("drops a stored single letter on a dangerous command: a legacy acknowledged Q is not shown as bound", async () => {
    expect((await loadWith({ "dom.cancel_all": "Q" })).get("dom.cancel_all")).toBe("Ctrl+Shift+X");
  });

  it("drops a stored key outside the vocabulary", async () => {
    expect((await loadWith({ "dom.zoom_in": "Ctrl+Banana" })).get("dom.zoom_in")).toBe("+");
  });

  it("keeps an acknowledged bare key that is not a letter: cancel-all on Del", async () => {
    expect((await loadWith({ "dom.cancel_all": "Del" })).get("dom.cancel_all")).toBe("Del");
  });

  it("skips a locked command's stored override (CR-305B-06)", async () => {
    expect((await loadWith({ "global.palette": "Ctrl+J" })).get("global.palette")).toBe("Ctrl+K");
  });

  it("restores an unbound command as unbound (CR-305B-06)", async () => {
    expect((await loadWith({ "global.symbol_search": "" })).get("global.symbol_search")).toBe("");
  });

  it("SEC-305B-01: checks the overrides as one profile: a Global stored on a view's chord returns to its default", async () => {
    const loaded = await loadWith({ "global.account_picker": "Ctrl+Shift+X" });
    expect([loaded.get("global.account_picker"), loaded.get("dom.cancel_all")]).toEqual([
      "Ctrl+Shift+A",
      "Ctrl+Shift+X",
    ]);
    // so the view's binding is live: in the DOM view the chord reaches cancel-all, not a Global that took it
    const { buildComboMap } = await import("../src/keymap/registry");
    const hits = buildComboMap(undefined, loaded).resolve(
      "Ctrl+Shift+X",
      new Set(["Global", "DOM"]),
    );
    expect(hits.map((h) => h.command.id)).toEqual(["dom.cancel_all"]);
  });

  it("SEC-305B-01: two stored commands on one key: the first keeps it, the other is back on its default", async () => {
    const loaded = await loadWith({ "dom.zoom_in": "J", "dom.zoom_out": "J" });
    expect([loaded.get("dom.zoom_in"), loaded.get("dom.zoom_out")]).toEqual(["J", "-"]);
  });
});
