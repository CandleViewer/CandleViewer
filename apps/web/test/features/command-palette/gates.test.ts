import { describe, expect, it } from "vitest";
import { KEYMAP } from "../../../src/keymap/keymap";
import { commandMeta, type CommandMeta } from "../../../src/keymap/registry";
import type { MeClaims } from "../../../src/routes/rbac";
import {
  COMMAND_GATES,
  PERMISSION_VERBS,
  gateReason,
  missingGates,
  needsGate,
  type CommandGate,
} from "../../../src/features/command-palette/gates";
import { actionRows } from "../../../src/features/command-palette/sources";

// E10-S05 (#5236): the action rows' T2 gates, E09-D09 §3's keys only (view-as first, then permission, owner-only).

const viewer: MeClaims = { authenticated: true, role: "viewer", permissions: ["positions:read"] };
const owner: MeClaims = {
  authenticated: true,
  role: "owner",
  permissions: ["positions:write", "killswitch:write"],
};
const CLOSE: CommandGate = { permission: "positions:write", write: true, protective: true };
const RELEASE: CommandGate = {
  permission: "killswitch:release",
  verb: "release the kill switch",
  ownerOnly: true,
  write: true,
};
const SUBMIT: CommandGate = { permission: "orders:write", write: true };

const meta = (id: string): CommandMeta => {
  const m = commandMeta(id);
  if (m === undefined) throw new Error(id);
  return m;
};

describe("E10-S05 gates.ts: the T2 reason", () => {
  it("is none without a row, or when the session holds the permission", () => {
    expect(gateReason(undefined, { claims: viewer, viewAs: null })).toBeUndefined();
    expect(gateReason(CLOSE, { claims: owner, viewAs: null })).toBeUndefined();
    expect(gateReason({}, { claims: viewer, viewAs: null })).toBeUndefined();
  });

  it("says rbac.permission with E09-D09 §3.2's verb", () => {
    expect(gateReason(CLOSE, { claims: viewer, viewAs: null })).toBe(
      "Your role can't change positions.",
    );
    expect(gateReason(SUBMIT, { claims: viewer, viewAs: null })).toBe(
      "Your role can't place orders.",
    );
  });

  it("says rbac.owner_only with the action's own verb", () => {
    expect(gateReason(RELEASE, { claims: owner, viewAs: null })).toBe(
      "Only the owner can release the kill switch.",
    );
  });

  it("puts view-as first on a write, but never on a protective command (C-2.6)", () => {
    const viewAs = { user: "alice" };
    expect(gateReason(SUBMIT, { claims: owner, viewAs })).toBe("Read-only while viewing as alice.");
    expect(gateReason(SUBMIT, { claims: viewer, viewAs })).toBe(
      "Read-only while viewing as alice.",
    );
    expect(gateReason(CLOSE, { claims: owner, viewAs })).toBeUndefined();
    expect(gateReason(CLOSE, { claims: viewer, viewAs })).toBe("Your role can't change positions.");
  });

  it("refuses a permission with no E09-D09 verb rather than invent one", () => {
    expect(() => gateReason({ permission: "made:up" }, { claims: viewer, viewAs: null })).toThrow(
      /no E09-D09 verb/,
    );
  });

  it("copies §3.2's verbs and renders no admin-domain code", () => {
    expect(PERMISSION_VERBS["positions:write"]).toBe("change positions");
    for (const code of ["admin:read", "admin:write", "flags:read", "backups:write"])
      expect(PERMISSION_VERBS).not.toHaveProperty(code);
  });

  it("feeds the action row's disabledReason; the row stays listed (T2, never hidden)", () => {
    const ids = ["positions.close", "global.cheatsheet"];
    const rows = actionRows(
      {
        claims: viewer,
        bindings: new Map(),
        isValid: (id) => ids.includes(id),
        viewAs: null,
      },
      KEYMAP,
      { "positions.close": CLOSE },
    );
    expect(rows.map((r) => [r.label, r.disabledReason ?? null, r.destructive === true])).toEqual([
      ["Hotkey cheatsheet", null, false],
      ["Close selected position (confirm)", "Your role can't change positions.", true],
    ]);
  });
});

describe("E10-S05 gates.ts: completeness (E47-D09's rule, PROPOSED)", () => {
  const entry = (id: string) => ({
    meta: meta(id),
    destructive: KEYMAP.find((c) => c.id === id)?.destructive === true,
  });

  it("flags every destructive, requiresArm or confirm command and nothing else", () => {
    const flagged = KEYMAP.filter((c) => needsGate(meta(c.id), c.destructive)).map((c) => c.id);
    expect(flagged).toEqual(
      expect.arrayContaining(["positions.close", "ticket.submit", "chart.market_order", "dom.arm"]),
    );
    expect(flagged).not.toContain("global.cheatsheet");
  });

  it("fails a registered dangerous command that has no row", () => {
    const registered = ["global.cheatsheet", "positions.close", "chart.market_order"].map(entry);
    expect(missingGates(registered, {})).toEqual(["positions.close", "chart.market_order"]);
    expect(
      missingGates(registered, { "positions.close": CLOSE, "chart.market_order": SUBMIT }),
    ).toEqual([]);
  });

  it("ships its table empty: no registered command is a write command yet", () => {
    expect(COMMAND_GATES).toEqual({});
  });
});
