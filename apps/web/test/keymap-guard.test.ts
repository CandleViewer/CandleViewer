import { describe, expect, it, vi } from "vitest";
import { createDispatcher, isEditableTarget } from "../src/keymap/dispatcher";
import { KEYMAP, eventBinding, isBareBinding, type KeyEventLike } from "../src/keymap/keymap";
import type { ArmPort } from "../src/keymap/registry";
import { bindingAtoms } from "../src/keymap/validate";

/**
 * #305 (E10-S02) PR A: the dispatcher's typing guard and key normalisation (E08-D05 A-D05-2; `05` §3.1, §3.3).
 * Each scout defect PR A fixes is a regression test here, failing before the fix: D5 (layouts), D6 (a typed `b`),
 * D7 (Esc) and D8 (the declared F11 shadow); so are AC6, E10-D04 G-07 and the lens's CR-305A-03, A11Y-305A-01 and
 * A11Y-305A-02. A test named `pin:` guards behaviour the change must keep: shipped behaviour, so it passes before the
 * fix too, or a decision on record (AZERTY `Ctrl+-` in `keymap.ts`'s note; D6's ruled option (c) in the host suite).
 */
const ev = (key: string, init: Partial<Omit<KeyEventLike, "key">> = {}): KeyEventLike => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...init,
});
const field = (): HTMLInputElement => document.createElement("input");
const button = (): HTMLButtonElement => document.createElement("button");
const ctx = (...names: string[]): ReadonlySet<string> => new Set(["Global", ...names]);
/** An order-entry key needs the arm (#305 PR C, BQ-5): a test of the guard or of repeat on one passes it armed. */
const ARMED: ArmPort = { isArmed: () => true };
const dispatcher = (valid: (id: string) => boolean = () => true, arm?: ArmPort) => {
  const execute = vi.fn();
  const notify = vi.fn();
  const armed = arm === undefined ? {} : { arm };
  const d = createDispatcher({
    isValid: (c) => valid(c.id),
    execute,
    notify,
    now: () => 0,
    ...armed,
  });
  return { d, execute, notify };
};
/** The press, then its auto-repeat: what the second one does. */
const heldRepeat = (e: KeyEventLike, active: ReadonlySet<string>, arm?: ArmPort) => {
  const { d, execute } = dispatcher(undefined, arm);
  d(e, active);
  return { result: d({ ...e, repeat: true }, active), runs: execute.mock.calls.length };
};

describe("D5: key normalisation across layouts (punctuation on `event.key`, Shift folded; digits on `event.code`)", () => {
  it("US: `+` is Shift+= and `?` is Shift+/, each its own character; a letter keeps its Shift", () => {
    expect(eventBinding(ev("+", { code: "Equal", shiftKey: true }))).toBe("+");
    expect(eventBinding(ev("+", { code: "NumpadAdd" }))).toBe("+");
    expect(eventBinding(ev("?", { code: "Slash", shiftKey: true }))).toBe("?");
    expect(eventBinding(ev("/", { code: "Slash", ctrlKey: true }))).toBe("Ctrl+/");
    expect(eventBinding(ev("1", { code: "Digit1", altKey: true }))).toBe("Alt+1");
    expect(eventBinding(ev("B", { code: "KeyB", shiftKey: true }))).toBe("Shift+B");
    expect(eventBinding(ev("Tab", { code: "Tab", shiftKey: true }))).toBe("Shift+Tab");
  });

  it("German: `/` is Shift+7, alone or under Ctrl; `+` and `-` have keys of their own", () => {
    expect(eventBinding(ev("/", { code: "Digit7", shiftKey: true }))).toBe("/");
    expect(eventBinding(ev("/", { code: "Digit7", shiftKey: true, ctrlKey: true }))).toBe("Ctrl+/");
    expect(eventBinding(ev("+", { code: "BracketRight" }))).toBe("+");
    expect(eventBinding(ev("-", { code: "Slash" }))).toBe("-");
    expect(eventBinding(ev("z", { code: "KeyY", ctrlKey: true }))).toBe("Ctrl+Z");
  });

  it("AZERTY: a digit-row chord is its digit (`Alt+&` is Alt+1); a digit typed with Shift is the digit; `-` stays", () => {
    expect(eventBinding(ev("&", { code: "Digit1", altKey: true }))).toBe("Alt+1");
    expect(eventBinding(ev("&", { code: "Digit1", ctrlKey: true }))).toBe("Ctrl+1");
    expect(eventBinding(ev("à", { code: "Digit0", metaKey: true }))).toBe("Ctrl+0");
    expect(eventBinding(ev("1", { code: "Digit1", shiftKey: true }))).toBe("1");
    expect(eventBinding(ev("1", { code: "Digit1", shiftKey: true, altKey: true }))).toBe("Alt+1");
    expect(eventBinding(ev("-", { code: "Digit6" }))).toBe("-");
    expect(eventBinding(ev("z", { code: "KeyW", ctrlKey: true }))).toBe("Ctrl+Z");
  });

  it("pin: AZERTY Ctrl+- (the 6 key) reads Ctrl+6, the digit row's chord, as keymap.ts's note decides (CR-305AD-04)", () => {
    expect(eventBinding(ev("-", { code: "Digit6", ctrlKey: true }))).toBe("Ctrl+6");
  });

  it("CR-305A-03: a macOS Option chord reads its key: Option+F (`ƒ`) is Alt+F, Option+7 (`|`) is Alt+7", () => {
    expect(eventBinding(ev("ƒ", { code: "KeyF", altKey: true }))).toBe("Alt+F");
    expect(eventBinding(ev("Ï", { code: "KeyF", altKey: true, shiftKey: true }))).toBe(
      "Alt+Shift+F",
    );
    expect(eventBinding(ev("|", { code: "Digit7", altKey: true }))).toBe("Alt+7");
  });

  it("a chord on a non-Latin layout reads its key: Russian Ctrl+С is Ctrl+C", () => {
    expect(eventBinding(ev("с", { code: "KeyC", ctrlKey: true }))).toBe("Ctrl+C");
  });

  it("each layout reaches its command: US `+` zooms the ladder, AZERTY Alt+& opens rail item 1, German Shift+7 `/`", () => {
    const { d, execute } = dispatcher();
    expect(d(ev("+", { code: "Equal", shiftKey: true }), ctx("DOM"))).toEqual({
      status: "executed",
      commandId: "dom.zoom_in",
    });
    expect(d(ev("&", { code: "Digit1", altKey: true }), ctx())).toEqual({
      status: "executed",
      commandId: "global.nav_rail",
    });
    expect(execute.mock.calls[1]?.[1]).toBe(1);
    expect(d(ev("/", { code: "Digit7", shiftKey: true }), ctx())).toEqual({
      status: "executed",
      commandId: "global.symbol_search",
    });
    // `?` is neither `/` nor the cheatsheet, which is `Ctrl+/` (E30-D02 A-12, the owner's OQ-1 call).
    expect(d(ev("?", { code: "Slash", shiftKey: true }), ctx()).status).toBe("unbound");
    expect(execute).toHaveBeenCalledTimes(3);
  });

  it("pin: parity with keymap_lint.py's grammar: each default key binding is what its own press reads as", () => {
    const keyOf: Readonly<Record<string, string>> = {
      Esc: "Escape",
      Del: "Delete",
      Space: " ",
      "←": "ArrowLeft",
      "→": "ArrowRight",
      "↑": "ArrowUp",
      "↓": "ArrowDown",
    };
    const pointerOrModifier = /(?:click|drag|wheel)$|^(?:Ctrl|Shift)$/;
    const atoms = KEYMAP.flatMap((c) =>
      bindingAtoms(c.defaultBinding).map((a) => [c.id, a] as const),
    );
    for (const [id, atom] of atoms.filter(([, a]) => !pointerOrModifier.test(a))) {
      // `+` and `Ctrl++` end in the plus key itself (`keymap_lint.py`'s `_split_binding`).
      const plus = atom === "+" || atom.endsWith("++");
      const mods = plus ? [...atom.slice(0, -1).split("+").filter(Boolean), "+"] : atom.split("+");
      const key = mods.pop() ?? "";
      const press = ev(keyOf[key] ?? (key.length === 1 ? key.toLowerCase() : key), {
        ctrlKey: mods.includes("Ctrl"),
        altKey: mods.includes("Alt"),
        shiftKey: mods.includes("Shift"),
      });
      expect(eventBinding(press), id).toBe(atom);
    }
  });

  it("a bare binding has no Ctrl, Alt or function key (A-D05-2); Shift alone keeps it bare", () => {
    for (const b of ["/", "B", "Shift+B", "Esc", "Enter", "Space", "Shift+←", "1", "+"]) {
      expect(isBareBinding(b), b).toBe(true);
    }
    for (const b of ["Ctrl+/", "Alt+1", "Ctrl+Alt+←", "F11", "Shift+F10", "F2", "Ctrl++"]) {
      expect(isBareBinding(b), b).toBe(false);
    }
  });
});

describe("the editable target (A-D05-2: input, textarea, select, contenteditable; combobox, searchbox, textbox)", () => {
  const el = (tag: string, attrs: Readonly<Record<string, string>> = {}): HTMLElement => {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
    return node;
  };

  it("counts the text-entry elements and roles, and what sits inside a contenteditable host", () => {
    const host = el("div", { contenteditable: "true" });
    const inside = el("span");
    host.append(inside);
    const editable = [
      el("input"),
      el("input", { type: "checkbox" }),
      el("textarea"),
      el("select"),
      el("div", { contenteditable: "" }),
      el("div", { contenteditable: "plaintext-only" }),
      inside,
      el("div", { role: "combobox" }),
      el("div", { role: "searchbox" }),
      el("span", { role: "textbox" }),
    ];
    for (const node of editable) expect(isEditableTarget(node), node.outerHTML).toBe(true);
  });

  it("does not count a button, a link, a non-editable region or anything that is not an element", () => {
    const off = el("div", { contenteditable: "true" });
    const closed = el("p", { contenteditable: "false" });
    off.append(closed);
    for (const node of [
      el("button"),
      el("a", { href: "#x" }),
      el("div", { role: "listbox" }),
      closed,
    ]) {
      expect(isEditableTarget(node), node.outerHTML).toBe(false);
    }
    for (const target of [null, undefined, window, document])
      expect(isEditableTarget(target)).toBe(false);
  });
});

describe("the dispatcher rule (A-D05-2 (a)–(c); AC6: typing is never hijacked)", () => {
  it("AC6: `/` typed in a text field is neither run nor reported; outside one it opens symbol search", () => {
    const { d, execute, notify } = dispatcher();
    expect(d(ev("/", { code: "Slash", target: field() }), ctx())).toEqual({
      status: "ignored",
      reason: "editable",
    });
    expect([execute.mock.calls.length, notify.mock.calls.length]).toEqual([0, 0]);
    expect(d(ev("/", { code: "Slash", target: document.body }), ctx())).toEqual({
      status: "executed",
      commandId: "global.symbol_search",
    });
  });

  it("D6: a `b` typed in a field never sets a ticket's side, and with only Global active it explains nothing", () => {
    const { d, execute } = dispatcher();
    expect(d(ev("b", { code: "KeyB", target: field() }), ctx("Ticket"))).toEqual({
      status: "ignored",
      reason: "editable",
    });
    expect(execute).not.toHaveBeenCalled();
    const inert = dispatcher(() => false);
    expect(inert.d(ev("b", { code: "KeyB", target: field() }), ctx())).toEqual({
      status: "ignored",
      reason: "editable",
    });
    expect(inert.notify).not.toHaveBeenCalled();
  });

  it("CR-305A-03: an Option or AltGr character typed in a field is text: Option+7 types `|` and runs nothing", () => {
    const { d, execute } = dispatcher();
    const typed = { status: "ignored", reason: "editable" };
    expect(d(ev("|", { code: "Digit7", altKey: true, target: field() }), ctx())).toEqual(typed);
    expect(
      d(ev("{", { code: "Digit7", ctrlKey: true, altKey: true, target: field() }), ctx()),
    ).toEqual(typed);
    expect(d(ev("ƒ", { code: "KeyF", altKey: true, target: field() }), ctx("Chart"))).toEqual(
      typed,
    );
    expect(execute).not.toHaveBeenCalled();
  });

  it("CR-305A-03: outside a field the same Option chord is the shortcut: Option+7 opens rail item 7", () => {
    const { d, execute } = dispatcher();
    expect(d(ev("|", { code: "Digit7", altKey: true }), ctx())).toEqual({
      status: "executed",
      commandId: "global.nav_rail",
    });
    expect(execute.mock.calls[0]?.[1]).toBe(7);
  });

  it("pin: an Alt chord that types no character of its own still runs in a field: Alt+B snaps to the bid", () => {
    expect(
      dispatcher().d(ev("b", { code: "KeyB", altKey: true, target: field() }), ctx("Ticket")),
    ).toEqual({
      status: "executed",
      commandId: "ticket.snap_bid",
    });
  });

  it("D7: Esc is never reported where nothing takes it", () => {
    const { d, notify } = dispatcher(() => false);
    expect(d(ev("Escape"), ctx())).toEqual({ status: "unbound" });
    expect(notify).not.toHaveBeenCalled();
  });

  it("D7: Esc is never reported where its command cannot run", () => {
    const { d, notify } = dispatcher(() => false);
    expect(d(ev("Escape"), ctx("Chart"))).toEqual({ status: "unbound" });
    expect(notify).not.toHaveBeenCalled();
  });

  it("pin: Esc runs its command where it can", () => {
    expect(dispatcher().d(ev("Escape"), ctx("Chart"))).toEqual({
      status: "executed",
      commandId: "chart.cancel_drawing",
    });
  });

  it("(b) a command that opts in runs its bare key in a field: `ticket.clear` Esc, `global.auth.submit` Enter", () => {
    const { d } = dispatcher();
    expect(d(ev("Escape", { target: field() }), ctx("Ticket"))).toEqual({
      status: "executed",
      commandId: "ticket.clear",
    });
    expect(d(ev("Enter", { target: field() }), ctx("Auth"))).toEqual({
      status: "executed",
      commandId: "global.auth.submit",
    });
    expect(d(ev("Enter", { target: field() }), ctx("Positions"))).toEqual({
      status: "ignored",
      reason: "editable",
    });
  });

  it("(a) a bare key someone already handled (`defaultPrevented`) is neither run nor reported; a chord still runs", () => {
    const { d, execute, notify } = dispatcher(undefined, ARMED);
    expect(d(ev("b", { code: "KeyB", defaultPrevented: true }), ctx("Ticket"))).toEqual({
      status: "ignored",
      reason: "prevented",
    });
    expect(d(ev("Enter", { ctrlKey: true, defaultPrevented: true }), ctx("Ticket"))).toEqual({
      status: "executed",
      commandId: "ticket.submit",
    });
    expect(execute).toHaveBeenCalledTimes(1);
    expect(notify).not.toHaveBeenCalled();
  });

  it("(c) a key that belongs to an IME composition never fires, chord or not", () => {
    const { d, execute } = dispatcher();
    expect(d(ev("b", { isComposing: true }), ctx("Ticket"))).toEqual({
      status: "ignored",
      reason: "composing",
    });
    expect(d(ev("k", { ctrlKey: true, isComposing: true }), ctx()).status).toBe("ignored");
    expect(execute).not.toHaveBeenCalled();
  });

  it("(c) CR-305A-03: Safari's Enter that ends a composition (keyCode 229) never submits", () => {
    const { d, execute } = dispatcher();
    expect(d(ev("Enter", { keyCode: 229, target: field() }), ctx("Auth"))).toEqual({
      status: "ignored",
      reason: "composing",
    });
    expect(execute).not.toHaveBeenCalled();
  });
});

describe("A11Y-305A-01, D6 (ruled option (c)): a bare navigation key is never reported; other inert keys are", () => {
  it("A11Y-305A-01: Tab, Enter, Space and → on a button explain no other view's command", () => {
    const { d, notify } = dispatcher(() => false);
    const at = button();
    for (const key of ["Tab", "Enter", " ", "ArrowRight"]) {
      expect(d(ev(key, { target: at }), ctx()), key).toEqual({ status: "unbound" });
    }
    expect(d(ev("Tab", { shiftKey: true, target: at }), ctx())).toEqual({ status: "unbound" });
    expect(notify).not.toHaveBeenCalled();
  });

  it("pin: Delete and a letter on a button still say where they work (E49-S07's e2e)", () => {
    const { d, notify } = dispatcher(() => false);
    expect(d(ev("Delete", { target: button() }), ctx())).toMatchObject({
      status: "inert",
      commandId: "chart.delete_drawing",
    });
    expect(d(ev("f", { code: "KeyF", target: button() }), ctx())).toMatchObject({
      status: "inert",
      commandId: "chart.footprint_toggle",
    });
    expect(notify).toHaveBeenCalledTimes(2);
  });

  it("D6 (ruled option (c)): a bare Tab, Enter, Space or arrow is never reported, even where its own view binds it", () => {
    const countInert = vi.fn();
    const notify = vi.fn();
    const d = createDispatcher({
      isValid: () => false,
      execute: vi.fn(),
      notify,
      now: () => 0,
      countInert,
    });
    const own: readonly (readonly [string, Partial<KeyEventLike>, string])[] = [
      ["Tab", {}, "Rules"],
      ["Enter", {}, "Positions"],
      [" ", {}, "DOM"],
      ["ArrowRight", {}, "Replay"],
      ["ArrowLeft", { shiftKey: true }, "Replay"],
    ];
    for (const [key, mods, view] of own) {
      expect(d(ev(key, mods), ctx(view)), `${key} in ${view}`).toEqual({ status: "unbound" });
    }
    expect([notify.mock.calls.length, countInert.mock.calls.length]).toEqual([0, 0]);
  });

  it("pin: a chord explains itself from any context", () => {
    const { d } = dispatcher(() => false);
    expect(d(ev("W", { ctrlKey: true, shiftKey: true }), ctx())).toMatchObject({
      status: "inert",
      commandId: "positions.close_all",
      notified: true,
    });
  });
});

describe("key auto-repeat: only a stepper repeats (G-07, A11Y-305A-02 / WCAG 2.3.1, BQ-3)", () => {
  it("G-07: a held Ctrl+/ toggles the cheatsheet once", () => {
    expect(heldRepeat(ev("/", { code: "Slash", ctrlKey: true }), ctx())).toEqual({
      result: { status: "repeat", commandId: "global.cheatsheet" },
      runs: 1,
    });
  });

  it("A11Y-305A-02: a held F11 toggles full screen once", () => {
    expect(heldRepeat(ev("F11", { code: "F11" }), ctx())).toEqual({
      result: { status: "repeat", commandId: "global.fullscreen" },
      runs: 1,
    });
  });

  it("A11Y-305A-02: a held F11 in a panel toggles the panel's full screen once", () => {
    expect(heldRepeat(ev("F11", { code: "F11" }), ctx("Workspace")).runs).toBe(1);
  });

  it("A11Y-305A-02: a held F toggles the footprint once", () => {
    expect(heldRepeat(ev("f", { code: "KeyF" }), ctx("Chart"))).toEqual({
      result: { status: "repeat", commandId: "chart.footprint_toggle" },
      runs: 1,
    });
  });

  it("A11Y-305A-02: a held Alt+G switches the rule editor's mode once", () => {
    expect(heldRepeat(ev("g", { code: "KeyG", altKey: true }), ctx("Rules"))).toEqual({
      result: { status: "repeat", commandId: "rules.graph_mode" },
      runs: 1,
    });
  });

  it("BQ-3: a held Ctrl+Enter submits once", () => {
    expect(heldRepeat(ev("Enter", { ctrlKey: true }), ctx("Ticket"), ARMED)).toEqual({
      result: { status: "repeat", commandId: "ticket.submit" },
      runs: 1,
    });
  });

  it("BQ-3: a held Ctrl+Shift+X cancels all once", () => {
    expect(heldRepeat(ev("X", { ctrlKey: true, shiftKey: true }), ctx("DOM"))).toEqual({
      result: { status: "repeat", commandId: "dom.cancel_all" },
      runs: 1,
    });
  });

  it("BQ-3: a held Ctrl+Shift+T arms once", () => {
    expect(heldRepeat(ev("T", { ctrlKey: true, shiftKey: true }), ctx("Ticket"))).toEqual({
      result: { status: "repeat", commandId: "ticket.arm" },
      runs: 1,
    });
  });

  it("pin: a held `+` zooms the ladder on every repeat (a stepper)", () => {
    expect(heldRepeat(ev("+", { code: "NumpadAdd" }), ctx("DOM"))).toEqual({
      result: { status: "executed", commandId: "dom.zoom_in" },
      runs: 2,
    });
  });

  it("pin: a held → steps the replay on every repeat (a stepper)", () => {
    expect(heldRepeat(ev("ArrowRight", { code: "ArrowRight" }), ctx("Replay"))).toEqual({
      result: { status: "executed", commandId: "replay.step_bar_fwd" },
      runs: 2,
    });
  });

  it("a held inert key explains itself once, on the press", () => {
    let t = 0;
    const notify = vi.fn();
    const d = createDispatcher({ isValid: () => false, execute: vi.fn(), notify, now: () => t });
    const press = ev("W", { ctrlKey: true, shiftKey: true });
    expect(d(press, ctx("Positions"))).toMatchObject({ status: "inert", notified: true });
    t = 6000;
    expect(d({ ...press, repeat: true }, ctx("Positions"))).toMatchObject({
      status: "inert",
      notified: false,
    });
    expect(notify).toHaveBeenCalledTimes(1);
  });
});

describe("one layer: Global first, a declared shadow while its context is active (AC1, BQ-4, D8)", () => {
  it("D8: F11 in a focused panel runs the declared panel full-screen, though the Global has no handler", () => {
    const { d } = dispatcher((id) => id !== "global.fullscreen");
    expect(d(ev("F11", { code: "F11" }), ctx("Workspace"))).toEqual({
      status: "executed",
      commandId: "workspace.fullscreen_panel",
    });
  });

  it("BQ-4: the declared shadow wins F11 while both it and the Global can run", () => {
    expect(dispatcher().d(ev("F11"), ctx("Workspace"))).toEqual({
      status: "executed",
      commandId: "workspace.fullscreen_panel",
    });
  });

  it("pin: outside the shadow's context F11 is the Global's", () => {
    expect(dispatcher().d(ev("F11"), ctx())).toEqual({
      status: "executed",
      commandId: "global.fullscreen",
    });
  });

  it("pin: where the shadow cannot run, F11 is the Global's", () => {
    const { d } = dispatcher((id) => id !== "workspace.fullscreen_panel");
    expect(d(ev("F11"), ctx("Workspace"))).toEqual({
      status: "executed",
      commandId: "global.fullscreen",
    });
  });

  it("pin: AC1: a profile that puts a view-local command on a Global key never overrides the Global", () => {
    const execute = vi.fn();
    const bindings = new Map([["ticket.side_buy", "Ctrl+K"]]);
    const d = createDispatcher({
      isValid: () => true,
      execute,
      notify: vi.fn(),
      now: () => 0,
      bindings,
    });
    expect(d(ev("k", { ctrlKey: true }), ctx("Ticket"))).toEqual({
      status: "executed",
      commandId: "global.palette",
    });
  });

  it("two views that share a key: the innermost active one takes it", () => {
    const { d } = dispatcher();
    expect(d(ev("b"), ctx("Ticket", "Replay"))).toMatchObject({ commandId: "ticket.side_buy" });
    expect(d(ev("b"), ctx("Replay", "Ticket"))).toMatchObject({ commandId: "replay.bookmark" });
  });
});
