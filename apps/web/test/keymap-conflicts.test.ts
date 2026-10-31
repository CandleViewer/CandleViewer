import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DANGEROUS_COMMANDS, KEYMAP, type KeymapCommand } from "../src/keymap/keymap";
import { buildComboMap, commandMeta } from "../src/keymap/registry";
import { createDispatcher } from "../src/keymap/dispatcher";
import { TRADING_BINDING_CHANGED, applyRebind, setAuditSink } from "../src/keymap/audit";
import type { AuditRecord } from "../src/keymap/audit";
import { getBindings, resetBindings, setBindings } from "../src/keymap/profile";
import {
  importProfile,
  normaliseBinding,
  planSwap,
  sharedWith,
  validateBinding,
  validateUnbind,
  type BindingProblem,
} from "../src/keymap/validate";

/**
 * #305 (E10-S02) PR B: the conflict engine of `05` §3.3. Each scout defect PR B fixes is a regression test here: D1 (a
 * view-local command takes `Ctrl+K`), D2 (`Esc` and `Ctrl+K` not reserved, the palette movable), D4 (import checked
 * binding by binding), D9 (an unhandled `Ctrl+K` toasts) and D10 (the audit set and reset-all); AC3 and AC4 too, and
 * the lens's CR-305B-01, -03, -04, -06 and -07 and SEC-305A-01, -02. D3 and AC5 (a dangerous command on a single
 * letter) are PR A's (`DANGEROUS_COMMANDS`, keymap-s07.test.ts).
 */
const defaults = (): Map<string, string> => new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));
const cmd = (
  id: string,
  context: KeymapCommand["context"],
  defaultBinding: string,
  more: Partial<KeymapCommand> = {},
): KeymapCommand => ({
  id,
  label: id,
  context,
  defaultBinding,
  destructive: false,
  validWhen: "always",
  visibleControl: true,
  ...more,
});
const kindOf = (id: string, raw: string): string | undefined =>
  validateBinding(id, raw, defaults())?.kind;
/** The command a conflict names, or the kind of any other refusal. */
const holder = (p: BindingProblem): string => (p.kind === "conflict" ? p.with : p.kind);
const defaultSink = (r: AuditRecord): void =>
  void window.dispatchEvent(new CustomEvent("cv:audit", { detail: r }));
let audits: AuditRecord[];

beforeEach(() => {
  audits = [];
  setAuditSink((r) => audits.push(r));
});

afterEach(() => {
  setAuditSink(defaultSink);
  setBindings(defaults());
});

describe("conflicts by focus-context set (`05` §3.3 rule 2; AC3)", () => {
  it("D1: a view-local command can no longer take Ctrl+K", () => {
    expect(validateBinding("ticket.side_buy", "Ctrl+K", defaults())).toMatchObject({
      kind: "reserved",
    });
  });

  it("D1: nor a Global key, such as the account picker's Ctrl+Shift+A", () => {
    expect(validateBinding("ticket.side_buy", "Ctrl+Shift+A", defaults())).toEqual({
      kind: "conflict",
      with: "global.account_picker",
      reason: 'Ctrl+Shift+A is already bound to "Account picker" in the Global context',
    });
  });

  it("a Global command takes no key a view holds: the cheatsheet cannot move onto the ticket's B", () => {
    expect(validateBinding("global.cheatsheet", "B", defaults())).toEqual({
      kind: "conflict",
      with: "ticket.side_buy",
      reason: 'B is already bound to "Set side Buy" in the Ticket context',
    });
  });

  it("SEC-305A-02: a Global rebound onto a view's trading chord is a conflict at save time, never a silent shadow", () => {
    expect(validateBinding("global.cheatsheet", "Ctrl+Enter", defaults())).toEqual({
      kind: "conflict",
      with: "ticket.submit",
      reason: 'Ctrl+Enter is already bound to "Submit order" in the Ticket context',
    });
  });

  it("distinct views are exclusive: the ladder may share the ticket's B", () => {
    expect(validateBinding("dom.centre_mark", "B", defaults())).toBeNull();
  });

  it("one view never binds a key twice: Next bookmark cannot take Replay's B", () => {
    expect(validateBinding("replay.bookmark_next", "B", defaults())).toEqual({
      kind: "conflict",
      with: "replay.bookmark",
      reason: 'B is already bound to "Set bookmark" in the Replay context',
    });
  });

  const custom = (): readonly [Map<string, KeymapCommand>, Map<string, string>] => {
    const byId = new Map(
      [
        cmd("global.mark", "Global", "Ctrl+M"),
        cmd("chart.mark", "Chart", "F2", {
          shadows: [
            { command: "global.mark", rationale: "The chart's own mark while it has focus" },
          ],
        }),
        cmd("dom.mark", "DOM", "F3"),
        cmd("ticket.both", "Ticket", "Ctrl+J", { focusContexts: ["Ticket", "Positions"] }),
        cmd("positions.one", "Positions", "F4"),
        cmd("replay.one", "Replay", "F6"),
      ].map((c) => [c.id, c]),
    );
    return [byId, new Map([...byId.values()].map((c) => [c.id, c.defaultBinding]))];
  };

  it("focus-context sets intersect on any shared context", () => {
    const [byId, current] = custom();
    expect(validateBinding("positions.one", "Ctrl+J", current, byId)).toMatchObject({
      kind: "conflict",
      with: "ticket.both",
    });
    expect(validateBinding("replay.one", "Ctrl+J", current, byId)).toBeNull();
  });

  it("a declared Global shadow is no conflict (BQ-4); an undeclared one is", () => {
    const [byId, current] = custom();
    expect(validateBinding("chart.mark", "Ctrl+M", current, byId)).toBeNull();
    expect(validateBinding("dom.mark", "Ctrl+M", current, byId)).toMatchObject({
      kind: "conflict",
      with: "global.mark",
    });
  });

  it("sharedWith names a dual meaning with its declared rationale (`05` §3.3 rule 1)", () => {
    expect(sharedWith("ticket.side_buy", "B", defaults())).toEqual([
      {
        command: expect.objectContaining({ id: "replay.bookmark" }),
        rationale: "Letters scoped to the focused panel; contexts are never co-active",
      },
    ]);
    expect(sharedWith("workspace.fullscreen_panel", "F11", defaults())).toEqual([
      {
        command: expect.objectContaining({ id: "global.fullscreen" }),
        rationale: "Active panel full-screen wins while a panel is focused",
      },
    ]);
  });

  it("sharedWith lists every exclusive view that keeps the key, in keymap order", () => {
    expect(sharedWith("dom.centre_mark", "B", defaults()).map((s) => s.command.id)).toEqual([
      "ticket.side_buy",
      "replay.bookmark",
    ]);
  });
});

describe("the reserved keys (`05` §3.3 rule 3; AC4; D2; BQ-7)", () => {
  it("refuses Esc for every command, as the universal cancel", () => {
    expect(validateBinding("dom.zoom_in", "Esc", defaults())).toEqual({
      kind: "reserved",
      platform: "app (universal cancel)",
      reason: "Esc is reserved by app (universal cancel)",
    });
  });

  it("refuses Ctrl+K for every command, as the command palette's", () => {
    expect(validateBinding("chart.footprint_toggle", "ctrl+k", defaults())).toEqual({
      kind: "reserved",
      platform: "app (command palette)",
      reason: "Ctrl+K is reserved by app (command palette)",
    });
  });

  it("D2: the palette and both Esc commands are the only ones not remappable (AC4)", () => {
    const locked = KEYMAP.filter((c) => commandMeta(c.id)?.remappable === false).map((c) => c.id);
    expect(locked.sort()).toEqual(["chart.cancel_drawing", "global.palette", "ticket.clear"]);
  });

  it("D2: the palette cannot move off Ctrl+K; binding its own key changes nothing", () => {
    expect(validateBinding("global.palette", "Ctrl+J", defaults())).toEqual({
      kind: "not-remappable",
      reason: '"Command palette" is not remappable',
    });
    expect(validateBinding("global.palette", "Ctrl+K", defaults())).toBeNull();
  });

  it("D2: a locked command cannot be unbound; any other can (WCAG 2.1.4)", () => {
    expect(validateUnbind("ticket.clear")).toMatchObject({ kind: "not-remappable" });
    expect(validateUnbind("dom.zoom_in")).toBeNull();
  });

  it("D9: an unhandled Ctrl+K is taken without a notice (the palette's no-op until E15)", () => {
    const notify = vi.fn();
    const execute = vi.fn();
    const d = createDispatcher({ isValid: () => false, execute, notify, now: () => 0 });
    const press = { key: "k", code: "KeyK", ctrlKey: true, metaKey: false, altKey: false };
    expect(d({ ...press, shiftKey: false }, new Set(["Global", "Ticket"]))).toEqual({
      status: "reserved",
      binding: "Ctrl+K",
    });
    expect([notify.mock.calls.length, execute.mock.calls.length]).toEqual([0, 0]);
  });
});

describe("the acknowledgement covers the dangerous set (E49-S07; CR-305B-04, SEC-305A-01)", () => {
  it("a destructive command's own default needs none: Del stays the drawing's and the rule's (D4)", () => {
    for (const id of ["chart.delete_drawing", "rules.delete"]) {
      expect(validateBinding(id, "Del", defaults()), id).toBeNull();
    }
  });

  it("another bare key on a destructive command needs it", () => {
    expect(validateBinding("chart.delete_drawing", "Backspace", defaults())).toEqual({
      kind: "unsafe-destructive",
      reason:
        '"Delete selected drawing" is destructive; a bare key needs an explicit warning acknowledgement',
    });
  });

  it("ticket.submit and the arm toggles need it for a bare digit, Enter, Space or F-key", () => {
    const cases: readonly (readonly [string, string])[] = [
      ["ticket.submit", "5"],
      ["dom.arm", "Enter"],
      ["ticket.arm", "Space"],
      ["ticket.submit", "F2"],
    ];
    for (const [id, key] of cases)
      expect(kindOf(id, key), `${id} ${key}`).toBe("unsafe-destructive");
  });

  it("its reason calls a dangerous command that is not destructive trading-critical", () => {
    expect(validateBinding("ticket.submit", "5", defaults())?.reason).toBe(
      '"Submit order" is trading-critical; a bare key needs an explicit warning acknowledgement',
    );
  });

  it("acknowledged, such a binding is accepted", () => {
    const ack = { acknowledgedUnsafe: true };
    expect(validateBinding("ticket.submit", "5", defaults(), undefined, ack)).toBeNull();
  });

  it("CR-305BD-03: Shift keeps a key bare, as the dispatcher reads it: Shift+Enter on Submit order needs it", () => {
    const cases: readonly (readonly [string, string])[] = [
      ["ticket.submit", "Shift+Enter"],
      ["dom.cancel_all", "Shift+Del"],
      ["dom.arm", "Shift+Space"],
    ];
    for (const [id, key] of cases)
      expect(kindOf(id, key), `${id} ${key}`).toBe("unsafe-destructive");
  });

  it("CR-305BD-03: Ctrl or Alt lifts it", () => {
    expect(kindOf("ticket.submit", "Alt+Enter")).toBeUndefined();
  });
});

describe("the key-name vocabulary (`keymap_lint.py`'s grammar)", () => {
  it("refuses a key outside it: Ctrl+Banana, a modifier as the key, an unknown modifier, Space off a pointer", () => {
    for (const raw of [
      "Ctrl+Banana",
      "Ctrl+Shift",
      "Hyper+K",
      "Space+K",
      "F25",
      "",
      "Alt+click+K",
    ]) {
      expect(normaliseBinding(raw), raw).toBeNull();
    }
  });

  it("reports such a binding as invalid, naming it", () => {
    expect(validateBinding("dom.zoom_in", "Ctrl+Banana", defaults())).toEqual({
      kind: "invalid-binding",
      reason: '"Ctrl+Banana" is not a valid key binding',
    });
  });

  it("CR-305B-01: an Object.prototype name is neither a key nor a modifier, bare or chorded", () => {
    for (const raw of [
      "constructor",
      "__proto__",
      "toString",
      "valueOf",
      "Ctrl+constructor",
      "Ctrl+__proto__",
      "Ctrl+toString",
      "constructor+K",
      "toString+K",
      "hasOwnProperty+drag",
    ]) {
      expect(normaliseBinding(raw), raw).toBeNull();
    }
  });

  it("CR-305B-01: validating one reports an invalid binding instead of throwing", () => {
    for (const raw of ["constructor", "__proto__", "Ctrl+toString"]) {
      expect(kindOf("dom.zoom_in", raw), raw).toBe("invalid-binding");
    }
  });

  it("CR-305B-07: Shift on a digit or a punctuation key is refused, since the press reads the typed character", () => {
    for (const raw of ["Shift+1", "Shift+=", "Ctrl+Shift+/", "Shift+1..9", "Alt+Shift++"]) {
      expect(normaliseBinding(raw), raw).toBeNull();
    }
  });

  it("CR-305B-07: Shift stays on a letter, a named key, a function key and a pointer gesture", () => {
    for (const raw of ["Ctrl+Shift+A", "Shift+Tab", "Shift+←", "Shift+F10", "Shift+wheel"]) {
      expect(normaliseBinding(raw), raw).toBe(raw);
    }
  });

  it("normalises the lint's aliases, named keys, pointer chords, ranges and a modifier alone", () => {
    const cases: readonly (readonly [string, string])[] = [
      ["command+k", "Ctrl+K"],
      ["shift+arrowleft", "Shift+←"],
      ["F13", "F13"],
      ["Ctrl++", "Ctrl++"],
      ["ctrl+", "Ctrl++"], // `_split_binding`: a trailing `+` is the plus key
      ["alt+DRAG", "Alt+drag"],
      ["space+drag", "Space+drag"],
      ["shift", "Shift"],
      ["alt+1..9", "Alt+1..9"],
      ["backspace", "Backspace"],
    ];
    for (const [raw, want] of cases) expect(normaliseBinding(raw), raw).toBe(want);
  });

  it("a key command cannot take a pointer gesture", () => {
    expect(kindOf("chart.footprint_toggle", "Alt+click")).toBe("invalid-binding");
  });

  it("a pointer gesture keeps its gesture and may change its modifier", () => {
    expect(kindOf("workspace.move_panel", "Ctrl+drag")).toBeUndefined();
    expect(kindOf("workspace.move_panel", "Ctrl+M")).toBe("invalid-binding");
  });

  it("a modifier alone stays a modifier alone", () => {
    expect(kindOf("positions.multi_ctrl", "Alt")).toBeUndefined();
  });

  it("a range keeps its digits and may change its modifiers", () => {
    expect(kindOf("global.nav_rail", "Ctrl+Alt+1..9")).toBeUndefined();
    expect(kindOf("global.nav_rail", "Alt+1..4")).toBe("invalid-binding");
    expect(kindOf("global.cheatsheet", "Alt+1..3")).toBe("invalid-binding");
  });
});

describe("a one-click swap (`05` §3.3 rule 2; AC3)", () => {
  it("plans both moves when one command holds the key and can take the other's", () => {
    expect(planSwap("dom.zoom_in", "-", defaults())).toEqual({
      a: "dom.zoom_in",
      aTo: "-",
      b: "dom.zoom_out",
      bTo: "+",
    });
  });

  it("offers none when the holder cannot take the other key: Submit order on a bare S", () => {
    expect(planSwap("ticket.side_sell", "Ctrl+Enter", defaults())).toBeNull();
  });

  it("offers none when several commands hold the key: the ticket's and replay's B", () => {
    expect(planSwap("global.cheatsheet", "B", defaults())).toBeNull();
  });

  it("offers none when nothing holds it", () => {
    expect(planSwap("dom.zoom_in", "Ctrl+Alt+J", defaults())).toBeNull();
  });
});

describe("D4: an import is checked as one profile", () => {
  it("the full default profile imports with no reject: pointer chords, modifier-only keys, ranges, overrides, Del", () => {
    const r = importProfile(Object.fromEntries(KEYMAP.map((c) => [c.id, c.defaultBinding])));
    expect(r.rejected).toEqual([]);
    expect([...r.applied]).toEqual([...defaults()]);
  });

  it("a valid swap imports: each key's new owner is checked against the profile it lands in", () => {
    const r = importProfile({ "dom.zoom_in": "-", "dom.zoom_out": "+" });
    expect(r.rejected).toEqual([]);
    expect([r.applied.get("dom.zoom_in"), r.applied.get("dom.zoom_out")]).toEqual(["-", "+"]);
  });

  it("reports Ctrl+Banana, an unknown id and a value that is not a string, and keeps their defaults", () => {
    const r = importProfile({
      "dom.zoom_in": "Ctrl+Banana",
      "global.nope": "Ctrl+J",
      "dom.zoom_out": 5,
    });
    expect(r.rejected.map((x) => [x.commandId, x.binding, x.problem.kind])).toEqual([
      ["dom.zoom_in", "Ctrl+Banana", "invalid-binding"],
      ["global.nope", "Ctrl+J", "unknown-command"],
      ["dom.zoom_out", "5", "invalid-binding"],
    ]);
    expect([r.applied.get("dom.zoom_in"), r.applied.get("dom.zoom_out")]).toEqual(["+", "-"]);
  });

  it("CR-305B-01: an Object.prototype name is reported, entry by entry, and the rest still applies", () => {
    const r = importProfile(
      JSON.parse(
        '{"dom.zoom_in":"constructor","dom.zoom_out":"Ctrl+toString","__proto__":"Ctrl+J","dom.centre_mark":"J"}',
      ) as Record<string, unknown>,
    );
    expect(r.rejected.map((x) => [x.commandId, x.problem.kind])).toEqual([
      ["dom.zoom_in", "invalid-binding"],
      ["dom.zoom_out", "invalid-binding"],
      ["__proto__", "unknown-command"],
    ]);
    expect(r.applied.get("dom.centre_mark")).toBe("J");
  });

  it("a key two entries claim stays with the first", () => {
    const r = importProfile({ "dom.zoom_in": "J", "dom.centre_mark": "J" });
    expect(r.rejected.map((x) => [x.commandId, x.problem.kind])).toEqual([
      ["dom.centre_mark", "conflict"],
    ]);
    expect([r.applied.get("dom.zoom_in"), r.applied.get("dom.centre_mark")]).toEqual(["J", "C"]);
  });

  it("CR-305B-07: it stays with the first when it is the second's default too, which leaves the second unbound", () => {
    const r = importProfile({ "dom.zoom_in": "-", "dom.zoom_out": "-" });
    expect(r.rejected.map((x) => [x.commandId, holder(x.problem)])).toEqual([
      ["dom.zoom_out", "dom.zoom_in"],
    ]);
    expect([r.applied.get("dom.zoom_in"), r.applied.get("dom.zoom_out")]).toEqual(["-", ""]);
  });

  it("an entry on a key the profile keeps is refused, and keeps its default", () => {
    const r = importProfile({ "dom.recentre": "-" });
    expect(r.rejected.map((x) => [x.commandId, holder(x.problem)])).toEqual([
      ["dom.recentre", "dom.zoom_out"],
    ]);
    expect(r.applied.get("dom.recentre")).toBe("Space");
  });

  it("SEC-305A-02: a Global entry on a view's trading chord is refused", () => {
    const r = importProfile({ "global.cheatsheet": "Ctrl+Enter" });
    expect(r.rejected.map((x) => [x.commandId, holder(x.problem)])).toEqual([
      ["global.cheatsheet", "ticket.submit"],
    ]);
  });

  it("an empty binding unbinds (WCAG 2.1.4)", () => {
    const r = importProfile({ "global.symbol_search": "" });
    expect([r.rejected, r.applied.get("global.symbol_search")]).toEqual([[], ""]);
  });

  it("a locked command's entry is refused, and the command keeps its key", () => {
    const r = importProfile({ "global.palette": "Ctrl+J" });
    expect(r.rejected).toEqual([
      {
        commandId: "global.palette",
        binding: "Ctrl+J",
        problem: { kind: "not-remappable", reason: '"Command palette" is not remappable' },
      },
    ]);
    expect(r.applied.get("global.palette")).toBe("Ctrl+K");
  });
});

describe("D10: what is audited, and that every change goes through the audited rebind", () => {
  it("the dangerous set is audited, the deletes included (SEC-305A-01, CR-305BD-02; CR-305B-03)", () => {
    const ids = [...DANGEROUS_COMMANDS];
    for (const id of ids) applyRebind(defaults(), id, "Ctrl+Alt+J");
    expect(audits.map((a) => [a.commandId, a.acknowledgedUnsafe])).toEqual(
      ids.map((id) => [id, false]),
    );
  });

  it("keymap.json's audited commands are the dangerous set, no more and no fewer", () => {
    const audited = KEYMAP.filter((c) => c.audited === true).map((c) => c.id);
    expect(audited.sort()).toEqual([...DANGEROUS_COMMANDS].sort());
  });

  it("a view command outside the set is not audited", () => {
    applyRebind(defaults(), "dom.zoom_in", "Ctrl+Alt+J");
    expect(audits).toEqual([]);
  });

  it("reset-all no longer bypasses it: restoring a trading binding is audited", () => {
    setBindings(applyRebind(getBindings(), "ticket.submit", "Ctrl+Alt+Enter"));
    audits = [];
    resetBindings();
    expect(audits).toEqual([
      {
        action: TRADING_BINDING_CHANGED,
        commandId: "ticket.submit",
        before: "Ctrl+Alt+Enter",
        after: "Ctrl+Enter",
        acknowledgedUnsafe: false,
      },
    ]);
    expect(getBindings().get("ticket.submit")).toBe("Ctrl+Enter");
  });
});

describe("the combo map and an unbound command (CR-305B-06)", () => {
  it("an unbound command takes no key", () => {
    const map = buildComboMap(KEYMAP, new Map([["dom.zoom_in", ""]]));
    expect(map.resolve("+", new Set(["Global", "DOM"]))).toEqual([]);
    expect(map.anywhere("")).toBeUndefined();
  });
});
