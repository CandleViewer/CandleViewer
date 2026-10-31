import { afterEach, describe, expect, it, vi } from "vitest";
import { KEYMAP, type KeymapCommand } from "../src/keymap/keymap";
import {
  KeymapRegistryError,
  buildComboMap,
  commandMeta,
  createCommandRegistry,
} from "../src/keymap/registry";

/**
 * #305 (E10-S02) PR A: the command registry. `registerCommand`'s developer-facing guard (AC1: refused at
 * registration), the precomputed combo map with Global first and declared shadows only (BQ-4), and the metadata the
 * editor and the cheatsheet read (BQ-3's dangerous set; G-07; A-D05-2's opt-ins).
 */
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
const PALETTE = cmd("global.palette", "Global", "Ctrl+K");
const ids = (hits: readonly { readonly command: KeymapCommand }[]): string[] =>
  hits.map((h) => h.command.id);

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("registerCommand's guard (AC1: a developer-facing error at registration time)", () => {
  it("refuses an unknown id and a second handler for one id; an unregister frees the id", () => {
    const registry = createCommandRegistry([PALETTE]);
    expect(() => registry.register("global.nope", vi.fn())).toThrow(KeymapRegistryError);
    expect(() => registry.register("global.nope", vi.fn())).toThrow(
      /unknown keymap command "global\.nope"/,
    );
    const off = registry.register("global.palette", vi.fn());
    expect(() => registry.register("global.palette", vi.fn())).toThrow(/already has a handler/);
    off();
    expect(() => registry.register("global.palette", vi.fn())).not.toThrow();
  });

  it("refuses a view-local command on a Global key unless it declares the shadow with a rationale", () => {
    const taken = cmd("ticket.palette", "Ticket", "Ctrl+K");
    const blank = cmd("dom.palette", "DOM", "Ctrl+K", {
      shadows: [{ command: "global.palette", rationale: " " }],
    });
    const declared = cmd("chart.palette", "Chart", "Ctrl+K", {
      shadows: [
        { command: "global.palette", rationale: "The chart's own list while it has focus" },
      ],
    });
    const viaFocus = cmd("rules.find", "Rules", "Ctrl+K", {
      focusContexts: ["Rules", "Positions"],
    });
    const registry = createCommandRegistry([PALETTE, taken, blank, declared, viaFocus]);
    expect(() => registry.register("ticket.palette", vi.fn())).toThrow(
      /ticket\.palette \(Ticket\) binds Ctrl\+K, which Global global\.palette holds/,
    );
    expect(() => registry.register("dom.palette", vi.fn())).toThrow(KeymapRegistryError);
    expect(() => registry.register("rules.find", vi.fn())).toThrow(KeymapRegistryError);
    expect(() => registry.register("chart.palette", vi.fn())).not.toThrow();
  });

  it("a range is checked atom by atom against the Global keys", () => {
    const ranged = cmd("chart.presets", "Chart", "Ctrl+1..3");
    const registry = createCommandRegistry([cmd("global.two", "Global", "Ctrl+2"), ranged]);
    expect(() => registry.register("chart.presets", vi.fn())).toThrow(/binds Ctrl\+2/);
  });

  it("in production it logs the refusal and registers nothing; the handler already there stays", () => {
    vi.stubEnv("DEV", false);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const registry = createCommandRegistry([PALETTE]);
    const off = registry.register("global.nope", vi.fn());
    expect(error).toHaveBeenCalledWith(
      expect.stringMatching(/unknown keymap command "global\.nope"/),
    );
    expect(registry.isValid("global.nope")).toBe(false);
    off();
    const first = vi.fn();
    registry.register("global.palette", first);
    registry.register("global.palette", vi.fn());
    registry.run("global.palette");
    expect([first.mock.calls.length, error.mock.calls.length]).toEqual([1, 2]);
  });

  it("every shipped command registers under the guard, and runs only while its predicate holds", () => {
    const registry = createCommandRegistry();
    const offs = KEYMAP.map((c) => registry.register(c.id, vi.fn()));
    expect(KEYMAP.every((c) => registry.isValid(c.id))).toBe(true);
    offs.forEach((off) => off());
    const run = vi.fn();
    let ready = false;
    registry.register("global.cheatsheet", run, () => ready);
    expect(registry.isValid("global.cheatsheet")).toBe(false);
    ready = true;
    registry.run("global.cheatsheet", 4);
    expect([registry.isValid("global.cheatsheet"), run.mock.calls]).toEqual([true, [[4]]]);
  });

  it("a stale unregister never drops a newer handler", () => {
    const registry = createCommandRegistry([PALETTE]);
    const off = registry.register("global.palette", vi.fn());
    off();
    const next = vi.fn();
    registry.register("global.palette", next);
    off();
    registry.run("global.palette");
    expect(next).toHaveBeenCalledTimes(1);
  });
});

describe("the combo map (Technical notes: one precomputed map, rebuilt on a profile change)", () => {
  it("resolves Global first, a declared shadow before it while its context is active, innermost first", () => {
    const map = buildComboMap();
    expect(ids(map.resolve("F11", new Set(["Global"])))).toEqual(["global.fullscreen"]);
    expect(ids(map.resolve("F11", new Set(["Global", "Workspace"])))).toEqual([
      "workspace.fullscreen_panel",
      "global.fullscreen",
    ]);
    expect(ids(map.resolve("B", new Set(["Global", "Ticket", "Replay"])))).toEqual([
      "ticket.side_buy",
      "replay.bookmark",
    ]);
    const [rail] = map.resolve("Alt+3", new Set(["Global"]));
    expect([rail?.command.id, rail?.digit]).toEqual(["global.nav_rail", 3]);
  });

  it("drops a profile binding that would silently override a Global key: the Global keeps it", () => {
    const map = buildComboMap(KEYMAP, new Map([["ticket.side_buy", "Ctrl+K"]]));
    expect(ids(map.resolve("Ctrl+K", new Set(["Global", "Ticket"])))).toEqual(["global.palette"]);
    expect(ids(map.resolve("B", new Set(["Global", "Ticket"])))).toEqual([]);
  });

  it("binds a command in each of its focus contexts (default: its own context)", () => {
    const map = buildComboMap([
      cmd("chart.mark", "Chart", "Ctrl+M", { focusContexts: ["Chart", "DOM"] }),
    ]);
    expect(ids(map.resolve("Ctrl+M", new Set(["DOM"])))).toEqual(["chart.mark"]);
    expect(ids(map.resolve("Ctrl+M", new Set(["Ticket"])))).toEqual([]);
  });

  it("an exact binding beats a range on one key; only an exact binding explains an inert chord", () => {
    const map = buildComboMap(KEYMAP, new Map([["global.cheatsheet", "Alt+3"]]));
    expect(ids(map.resolve("Alt+3", new Set(["Global"])))).toEqual(["global.cheatsheet"]);
    expect(map.anywhere("Alt+4")).toBeUndefined();
    expect(map.anywhere("Ctrl+Shift+W")?.id).toBe("positions.close_all");
  });
});

describe("the metadata the editor and the cheatsheet read", () => {
  it("labels, groups, default keys, focus contexts and remappability come from keymap.json", () => {
    expect(commandMeta("global.symbol_search")).toMatchObject({
      label: "Symbol search",
      group: "Global",
      defaultBinding: "/",
      focusContexts: ["Global"],
      remappable: true,
      dangerous: false,
    });
    expect(commandMeta("global.nope")).toBeUndefined();
  });

  it("BQ-3's dangerous set: the destructive commands, ticket.submit and the arm toggles, each ignoring key repeat", () => {
    const dangerous = KEYMAP.filter((c) => commandMeta(c.id)?.dangerous).map((c) => c.id);
    expect(dangerous.sort()).toEqual([
      "chart.delete_drawing",
      "dom.arm",
      "dom.cancel_all",
      "positions.close",
      "positions.close_all",
      "rules.delete",
      "ticket.arm",
      "ticket.submit",
    ]);
    for (const id of dangerous) expect(commandMeta(id)?.ignoreRepeat, id).toBe(true);
  });

  it("A11Y-305A-02: only a stepper repeats on a held key; every toggle (G-07's included) runs once", () => {
    const steppers = KEYMAP.filter((c) => commandMeta(c.id)?.ignoreRepeat === false).map(
      (c) => c.id,
    );
    expect(steppers.sort()).toEqual([
      "chart.redo",
      "chart.undo",
      "dom.zoom_in",
      "dom.zoom_out",
      "replay.bookmark_next",
      "replay.bookmark_prev",
      "replay.jump_back",
      "replay.jump_fwd",
      "replay.step_bar_back",
      "replay.step_bar_fwd",
      "replay.step_tick_back",
      "replay.step_tick_fwd",
      "rules.cycle_nodes",
      "rules.move_down",
      "rules.move_up",
      "workspace.panel_next",
      "workspace.panel_prev",
    ]);
    expect(commandMeta("global.cheatsheet")).toMatchObject({
      ignoreRepeat: true,
      dangerous: false,
    });
  });

  it("A-D05-2's opt-ins are the only commands that run a bare key in a field", () => {
    const optIn = KEYMAP.filter((c) => commandMeta(c.id)?.allowInEditable).map((c) => c.id);
    expect(optIn.sort()).toEqual(["global.auth.submit", "ticket.clear"]);
  });

  it("no dangerous command's default is a single letter (the combo map would drop it, AC5)", () => {
    const letters = KEYMAP.filter(
      (c) => commandMeta(c.id)?.dangerous && /^(?:Shift\+)?\p{L}$/u.test(c.defaultBinding),
    );
    expect(letters).toEqual([]);
  });

  it("lists a command's declared shadows with their rationale", () => {
    expect(commandMeta("workspace.fullscreen_panel")?.shadows).toEqual([
      {
        command: "global.fullscreen",
        rationale: "Active panel full-screen wins while a panel is focused",
      },
    ]);
  });
});
