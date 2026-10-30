// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { freezeCell, installProbe, nextFrames, settleCell } from "../../vr/probe.js";

const NOW = Date.parse("2026-10-27T14:02:00Z");
const RULE = { horizonMs: 1000, quietFrames: 2, capMs: 3000 } as const;

/** Whether a promise has settled yet, without waiting for it. */
const watch = <T>(promise: Promise<T>): { readonly done: () => boolean } => {
  let done = false;
  void promise.then(() => {
    done = true;
  });
  return { done: () => done };
};

/** The globals the probe replaces; each test hands the fake timers' own back before they uninstall. */
const PATCHED = [
  "Date",
  "setTimeout",
  "clearTimeout",
  "setInterval",
  "clearInterval",
  "requestAnimationFrame",
  "cancelAnimationFrame",
] as const;
const page = window as unknown as Record<string, unknown>;
let saved: unknown[] = [];

beforeEach(() => {
  // The page's clock, frames included, is fake here: every wait below is a step of fake time.
  vi.useFakeTimers({ toFake: [...PATCHED, "performance"] });
  saved = PATCHED.map((name) => page[name]);
  localStorage.setItem("left", "by the last cell");
  sessionStorage.setItem("left", "by the last cell");
  installProbe({ now: NOW });
});

afterEach(() => {
  PATCHED.forEach((name, index) => (page[name] = saved[index]));
  vi.useRealTimers();
  document.body.replaceChildren();
  delete document.body.dataset["tick"];
});

describe("the capture's page probe", () => {
  it("freezes Date at the capture's instant and leaves explicit dates alone", () => {
    expect([Date.now(), new Date().getTime()]).toEqual([NOW, NOW]);
    expect(Date()).toBe(new Date(NOW).toString());
    expect(new Date(0).toISOString()).toBe("1970-01-01T00:00:00.000Z");
    expect(new Date(2026, 0, 2).getDate()).toBe(2);
    expect(new Date()).toBeInstanceOf(Date);
    vi.advanceTimersByTime(5_000); // time passes; the date shown does not
    expect(Date.now()).toBe(NOW);
  });

  it("starts every document with empty storage", () => {
    expect([localStorage.length, sessionStorage.length]).toEqual([0, 0]);
  });

  it("lets Date move only while a play function runs, as in the storybook job, and holds it otherwise", () => {
    const listeners: ((event: { newPhase: string }) => void)[] = [];
    const channel = {
      on: (event: string, listener: (event: { newPhase: string }) => void): void => {
        if (event === "storyRenderPhaseChanged") listeners.push(listener);
      },
    };
    page["__STORYBOOK_ADDONS_CHANNEL__"] = channel; // what Storybook's setChannel does
    expect(page["__STORYBOOK_ADDONS_CHANNEL__"]).toBe(channel);
    const phase = (newPhase: string): void =>
      listeners.forEach((listener) => listener({ newPhase }));
    phase("rendering");
    vi.advanceTimersByTime(500);
    expect(Date.now()).toBe(NOW); // the story renders the frozen instant
    phase("playing");
    vi.advanceTimersByTime(1_200);
    expect([Date.now(), new Date().getTime()]).toEqual([NOW + 1_200, NOW + 1_200]);
    phase("played");
    vi.advanceTimersByTime(5_000);
    expect(Date.now()).toBe(NOW + 1_200); // still again for the capture
  });

  it("settles once the page holds still for two frames", async () => {
    const settled = settleCell(RULE);
    await vi.advanceTimersByTimeAsync(100);
    await expect(settled).resolves.toEqual({ ok: true, ms: 32, reason: "" });
  });

  it("lets a timer due within the horizon fire first (a tooltip's hover delay) and waits out its change", async () => {
    window.setTimeout(() => document.body.append(document.createElement("div")), 300);
    const settled = settleCell(RULE);
    const state = watch(settled);
    await vi.advanceTimersByTimeAsync(250);
    expect(state.done()).toBe(false);
    await vi.advanceTimersByTimeAsync(200);
    await expect(settled).resolves.toMatchObject({ ok: true });
    expect(document.body.children).toHaveLength(1);
  });

  it("never waits for a timer due past the horizon or an interval that changes nothing", async () => {
    const late = vi.fn();
    window.setTimeout(late, 2_000);
    window.setInterval(() => undefined, 50);
    const settled = settleCell(RULE);
    await vi.advanceTimersByTimeAsync(100);
    await expect(settled).resolves.toEqual({ ok: true, ms: 32, reason: "" });
    expect(late).not.toHaveBeenCalled();
  });

  it("drops a cleared timer from what it waits for", async () => {
    const id = window.setTimeout(() => document.body.append("late"), 300);
    window.clearTimeout(id);
    const settled = settleCell(RULE);
    await vi.advanceTimersByTimeAsync(100);
    await expect(settled).resolves.toEqual({ ok: true, ms: 32, reason: "" });
  });

  it("fails by name when the DOM is still changing at the cap", async () => {
    let tick = 0;
    window.setInterval(() => {
      tick += 1;
      document.body.dataset["tick"] = String(tick);
    }, 10);
    const settled = settleCell(RULE);
    await vi.advanceTimersByTimeAsync(3_100);
    await expect(settled).resolves.toMatchObject({
      ok: false,
      reason: "the DOM was still changing after 3000 ms",
    });
  });

  it("freezes the page: pending and new timers, intervals and frames never run; its own frames do", async () => {
    const fired = vi.fn();
    window.setTimeout(fired, 10);
    window.setInterval(fired, 10);
    window.requestAnimationFrame(fired);
    freezeCell();
    window.setTimeout(fired, 10);
    window.setInterval(fired, 10);
    window.requestAnimationFrame(fired);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fired).not.toHaveBeenCalled();
    const frames = nextFrames(2);
    await vi.advanceTimersByTimeAsync(40);
    await expect(frames).resolves.toBeUndefined();
  });

  it("names a page the probe was not installed in", async () => {
    Reflect.deleteProperty(window, "__cvVr");
    await expect(settleCell(RULE)).resolves.toEqual({
      ok: false,
      ms: 0,
      reason: "the capture's page probe is not installed",
    });
  });
});
