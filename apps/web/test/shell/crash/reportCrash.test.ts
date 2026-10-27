import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  resetShellState,
  setShellState,
  type Settings,
} from "../../../src/shell/bootstrap/store.js";
import * as C from "../../../src/shell/crash/reportCrash.js";
import { startShell } from "../../../src/shell/startShell.js";
import { FakePort } from "../../lib/ws/support/fakePort";

const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const secret = ["zq", "r".repeat(9), "7".repeat(9)].join(""); // key-shaped, built at run time
const BODY = ["never", "the", "payload"].join("-"); // shapeless: only the field rule keeps it out
const idAt = (i: number): string => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
let n = 0;
const newId = (): string => idAt((n += 1));
const port = (crashLog = true) => ({
  capabilities: { crashLog } as never,
  crashLog: { append: vi.fn(async () => undefined) },
});

beforeEach(() => {
  n = 0;
  resetShellState();
});
afterEach(() => C.installCrashReporter({ version: "x", target: undefined })());

describe("createCrashReporter", () => {
  it("assigns a UUIDv4 by default, and one id to one error object reported twice", () => {
    const reporter = C.createCrashReporter();
    const error = new Error("boom");
    const id = reporter.report(error, "panel");
    expect(id).toMatch(UUID4);
    expect(reporter.report(error, "window")).toBe(id);
    expect(reporter.counts()).toEqual({ panel: 1, route: 0, app: 0, window: 0 });
  });

  it("keeps the newest entries up to its capacity", () => {
    const reporter = C.createCrashReporter({ capacity: 3, newId });
    for (let i = 0; i < 4; i += 1) reporter.report(`crash ${i}`, "route");
    expect(reporter.entries().map((e) => e.message)).toEqual(["crash 1", "crash 2", "crash 3"]);
    expect(reporter.counts().route).toBe(4);
  });

  it("stores and persists only the allow-listed fields, redacted, and never a payload", () => {
    const p = port();
    const reporter = C.createCrashReporter({ port: p, newId, now: () => 7 });
    const error = Object.assign(new Error(`token=${secret}`), { body: BODY, payload: BODY });
    error.stack = `Error: x\n    at load (${secret}.js:1:1)`;
    reporter.report(error, "panel", `Chart ${secret}`);
    reporter.report({ body: BODY, request: { payload: BODY } }, "window");
    reporter.report({ message: `bad ${secret}`, payload: BODY }, "app");
    const entries = reporter.entries();
    expect(JSON.stringify(entries)).not.toMatch(new RegExp(`${secret}|${BODY}`));
    expect(entries.map((e) => Object.keys(e).sort().join())).toEqual([
      "context,message,stack,timestampMs",
      "context,message,timestampMs",
      "context,message,timestampMs",
    ]);
    expect(entries.map((e) => e.message)).toEqual([
      "Error: token=[redacted:key-name]",
      "Non-Error thrown (object)",
      "bad [redacted:key-shape]",
    ]);
    expect(entries[0]?.context).toEqual({
      correlationId: idAt(1),
      boundary: "panel",
      component: "Chart [redacted:key-shape]",
    });
    expect(p.crashLog.append).toHaveBeenCalledWith(entries[0]);
  });

  it("persists only where the shell has a crash log, and never throws when the shell fails", () => {
    const off = port(false);
    C.createCrashReporter({ port: off }).report("x", "app");
    expect(off.crashLog.append).not.toHaveBeenCalled();
    const fail = (append: () => Promise<void>) =>
      C.createCrashReporter({
        port: { capabilities: { crashLog: true } as never, crashLog: { append } },
      });
    const thrown = (): Promise<void> => {
      throw new TypeError("no bridge");
    };
    expect(() => fail(thrown).report("x", "app")).not.toThrow();
    expect(() => fail(() => Promise.reject(new Error("io"))).report("x", "app")).not.toThrow();
  });

  it("builds the diagnostics payload from allow-listed parts, redacted at assembly", () => {
    const reporter = C.createCrashReporter({ newId, now: () => Date.UTC(2026, 9, 27) });
    reporter.report(new Error("first"), "panel");
    reporter.report("second", "window");
    const settings = { theme: "dark", api_key: secret, note: `pasted ${secret}`, body: BODY };
    const payload = reporter.diagnostics({ version: "0.1.0", buildHash: "abc1234", settings });
    expect(payload).toEqual({
      version: "0.1.0",
      buildHash: "abc1234",
      settings: {
        theme: "dark",
        api_key: "[redacted:key-name]",
        note: "pasted [redacted:key-shape]",
      },
      generatedAtMs: Date.UTC(2026, 9, 27),
      correlationIds: [idAt(1), idAt(2)],
      recentLogLines: [
        `2026-10-27T00:00:00.000Z crash panel ${idAt(1)} Error: first`,
        `2026-10-27T00:00:00.000Z crash window ${idAt(2)} second`,
      ],
      metrics: { shell_crash_total: { panel: 1, route: 0, app: 0, window: 1 } },
    });
  });
});

describe("report() on hostile errors (M1)", () => {
  const thrower = (): never => {
    throw new Error(secret);
  };
  const hostile: [string, () => unknown, string][] = [
    ["an Error whose message getter throws", () => Object.defineProperty(new Error("x"), "message", { get: thrower }), "Error: <unrenderable>"],
    ["an Error whose stack getter throws", () => Object.defineProperty(new Error("x"), "stack", { get: thrower }), "Error: x"],
    ["an Error whose name's toString throws", () => Object.assign(new Error("x"), { name: { toString: thrower } }), "<unrenderable>: x"],
    ["a plain object whose message getter throws", () => Object.defineProperty({}, "message", { get: thrower }), "Non-Error thrown (object)"],
    ["a Proxy whose has / ownKeys traps throw", () => new Proxy({}, { has: thrower, ownKeys: thrower }), "Non-Error thrown (object)"],
    ["a Proxy whose getPrototypeOf trap throws", () => new Proxy({}, { getPrototypeOf: thrower }), "Crash report failed: object"],
    ["an Error with a non-string stack", () => Object.assign(new Error("x"), { stack: { frames: [secret] } }), "Error: x"],
  ]; // prettier-ignore

  it.each(hostile)("%s: returns an id, counts it and keeps an entry", (_name, make, message) => {
    const reporter = C.createCrashReporter({ newId, now: () => 1 });
    let id = "";
    expect(() => {
      id = reporter.report(make(), "panel");
    }).not.toThrow();
    expect(id).toBe(idAt(1));
    expect(reporter.counts().panel).toBe(1);
    expect(reporter.entries()).toHaveLength(1);
    expect(reporter.entries()[0]?.message).toBe(message);
    expect(reporter.entries()[0]?.context).toMatchObject({ correlationId: id, boundary: "panel" });
    expect(JSON.stringify(reporter.entries())).not.toContain(secret);
  });

  it("marks a stack that throws or is not a string", () => {
    const reporter = C.createCrashReporter({ newId });
    reporter.report(Object.defineProperty(new Error("x"), "stack", { get: thrower }), "app");
    reporter.report(Object.assign(new Error("y"), { stack: 42 }), "app");
    expect(reporter.entries().map((e) => e.stack)).toEqual(["<unrenderable>", "<unrenderable>"]);
  });
});

describe("the installed reporter", () => {
  it("reports window errors and unhandled rejections until torn down", () => {
    const target = new EventTarget(); // not `window`: the runner reports an unheard `error` as uncaught
    const uninstall = C.installCrashReporter({ version: "0.1.0", newId, target });
    target.dispatchEvent(new ErrorEvent("error", { error: new Error("a") }));
    target.dispatchEvent(Object.assign(new Event("unhandledrejection"), { reason: "b" }));
    uninstall();
    target.dispatchEvent(new ErrorEvent("error", { error: new Error("c") }));
    expect(C.buildDiagnostics().recentLogLines.map((l) => l.split(" ").slice(4).join(" "))).toEqual(
      ["Error: a", "b"],
    );
  });

  it("puts only the allow-listed settings groups into the diagnostics", () => {
    C.installCrashReporter({ version: "0.1.0", buildHash: "abc1234", target: undefined });
    const preferences = {
      appearance: { theme: "dark" },
      notifications: { webhook_url: `https://hooks.example/${secret}` },
      _meta: { overridden: [] },
    } as unknown as Settings;
    setShellState({ preferences });
    expect(C.buildDiagnostics()).toMatchObject({
      version: "0.1.0",
      buildHash: "abc1234",
      settings: { appearance: { theme: "dark" } },
    });
    expect(Object.keys(C.buildDiagnostics().settings as object)).toEqual(["appearance"]);
  });

  it("is installed by startShell and removed by its stop()", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 401 })),
    );
    const added = vi.spyOn(window, "addEventListener");
    const removed = vi.spyOn(window, "removeEventListener");
    const handle = startShell({ wsUrl: "wss://localhost/api/v1/ws", port: new FakePort() });
    const onError = added.mock.calls.find(([type]) => type === "error")?.[1];
    window.dispatchEvent(new ErrorEvent("error", { error: new Error("live") }));
    handle.stop();
    expect(removed).toHaveBeenCalledWith("error", onError);
    expect(removed).toHaveBeenCalledWith("unhandledrejection", expect.any(Function));
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    expect(C.buildDiagnostics().metrics.shell_crash_total.window).toBe(1);
    expect(C.reportCrash(new Error("direct"), "route")).toMatch(UUID4);
  });
});

describe("the allowed settings groups (L5)", () => {
  // Pinned against the generated `Settings` schema (`@candleviewer/protocol`): a group or a key added to, or removed
  // from, the schema fails `tsc` (the typecheck gate) here, so each change to what diagnostics carries is reviewed.
  const GROUP_KEYS = {
    accessibility: ["always_show_tables", "announce_prices", "disable_canvas_animation", "increased_contrast", "keyboard_only", "reduced_motion", "thick_focus_ring", "verbosity"],
    appearance: ["density", "font_scale", "high_contrast", "reduce_motion", "theme"],
    chart: ["bar_close_countdown", "crosshair_sync", "default_bar_type", "default_param", "price_scale_mode"],
    data: ["default_depth", "max_history_bars", "stale_badge_after_ms"],
    orderflow: ["big_trade_k", "big_trade_threshold_mode", "heatmap_ask_colour", "heatmap_bid_colour", "imbalance_ratio", "min_stack", "value_area_pct"],
    trading: ["arm_timeout_seconds", "confirm_flatten", "confirm_market_orders", "default_environment", "default_qty_presets", "one_click_armed"],
  } as const; // prettier-ignore
  type Pinned = typeof GROUP_KEYS;
  type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
  type SchemaKeys<K> = K extends keyof Settings ? keyof NonNullable<Settings[K]> : never;
  const groupsPinned: Same<keyof Pinned, Exclude<keyof Settings, "notifications" | "_meta">> = true;
  const keysPinned: { [K in keyof Pinned]: Same<Pinned[K][number], SchemaKeys<K>> } = {
    accessibility: true,
    appearance: true,
    chart: true,
    data: true,
    orderflow: true,
    trading: true,
  };

  it("carries exactly the pinned groups and keys, the `data` group included", () => {
    expect([groupsPinned, ...Object.values(keysPinned)].every(Boolean)).toBe(true);
    C.installCrashReporter({ version: "0.1.0", target: undefined });
    const group = (keys: readonly string[]) => Object.fromEntries(keys.map((k) => [k, 1]));
    const preferences = Object.fromEntries(
      Object.entries(GROUP_KEYS).map(([name, keys]) => [name, group(keys)]),
    );
    setShellState({
      preferences: { ...preferences, notifications: { webhook_url: "x" } } as unknown as Settings,
    });
    const settings = C.buildDiagnostics().settings as Record<string, Record<string, unknown>>;
    expect(Object.keys(settings).sort()).toEqual(Object.keys(GROUP_KEYS).sort());
    for (const [name, keys] of Object.entries(GROUP_KEYS)) {
      expect(Object.keys(settings[name] ?? {}).sort()).toEqual([...keys].sort());
    }
  });

  it("still redacts inside an allowed group and drops a payload-named field within it", () => {
    const reporter = C.createCrashReporter({ newId });
    const settings = { data: { default_depth: 50, apiKey: secret, body: BODY }, p: { x: BODY } };
    expect(reporter.diagnostics({ version: "v", buildHash: "h", settings }).settings).toEqual({
      data: { default_depth: 50, apiKey: "[redacted:key-name]" },
    });
  });
});
