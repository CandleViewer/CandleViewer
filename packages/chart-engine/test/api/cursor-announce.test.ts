// E11-S07 BQ-12 / BQ-13 (AC3 "the keyboard crosshair announces without flooding") and the facade
// half of BQ-3 / BQ-7: the cursor announcer speaks `say(full, short)` on E06-D03 D5's cadence under
// "chart:cursor"; only key-origin `a11y` reaches it; the root's focus and blur go as `setFocus`.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import { ANNOUNCE_EVENT, CURSOR_ANNOUNCE_KEY, createAnnouncer } from "../../src/host/axis-stop.js";
import type { FromWorker, ToWorker } from "../../src/worker/protocol.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import { asHtml, fakeContainer, FakeDocument, FakeElement } from "./fake-dom.js";

interface Heard {
  text: string;
  key: string;
  at: number;
}

const CustomEventStub = class {
  readonly detail: unknown;
  constructor(
    readonly type: string,
    init: { detail: unknown },
  ) {
    this.detail = init.detail;
  }
};

describe("BQ-13: 30 presses 100 ms apart (fake clock)", () => {
  let now: number;
  let timers: { at: number; cb: () => void }[];
  let heard: Heard[];
  let say: (full: string, short?: string) => void;
  const run = (to: number): void => {
    for (;;) {
      const due = timers.filter((t) => t.at <= to).sort((a, b) => a.at - b.at)[0];
      if (due === undefined) break;
      timers.splice(timers.indexOf(due), 1);
      now = due.at;
      due.cb();
    }
    now = to;
  };
  beforeEach(() => {
    now = 0;
    timers = [];
    heard = [];
    const c = fakeContainer(200, 100);
    (c.ownerDocument.defaultView as { CustomEvent?: unknown }).CustomEvent = CustomEventStub;
    c.addEventListener(ANNOUNCE_EVENT, (e) => {
      const d = (e as { detail: { text: string; key: string } }).detail;
      heard.push({ text: d.text, key: d.key, at: now });
    });
    say = createAnnouncer(
      asHtml(c),
      { now: () => now, setTimer: (cb, ms) => void timers.push({ at: now + ms, cb }) },
      CURSOR_ANNOUNCE_KEY,
    );
  });

  it("test_heldKey_atMostSixShortInsideTheHold_thenExactlyOneFullFlushOfBar30", () => {
    for (let bar = 1; bar <= 30; bar += 1) {
      run((bar - 1) * 100);
      say(`full ${bar}`, `short ${bar}`);
    }
    run(10_000);
    // The hold: the lone first press in full, then the short form on D5's 500 ms window cadence.
    const inside = heard.filter((h) => h.at < 3000);
    expect(inside[0]).toEqual({ text: "full 1", key: CURSOR_ANNOUNCE_KEY, at: 0 });
    const held = inside.slice(1);
    expect(held.length).toBeLessThanOrEqual(6);
    expect(held.length).toBeGreaterThan(0); // D5: 2/s while held, never silent
    expect(held.every((h) => h.text.startsWith("short "))).toBe(true);
    for (let i = 1; i < inside.length; i += 1) {
      expect((inside[i]?.at ?? 0) - (inside[i - 1]?.at ?? 0)).toBeGreaterThanOrEqual(500);
    }
    // Then exactly one full-form flush for bar 30, last (C-68: the window end at 3000 may
    // already have said bar 30 short; D5's trailingFlush keeps the full form within 250 ms).
    const fulls = heard.filter((h) => h.at >= 3000 && h.text.startsWith("full "));
    expect(fulls).toEqual([{ text: "full 30", key: CURSOR_ANNOUNCE_KEY, at: 3150 }]);
    expect(heard.at(-1)).toEqual(fulls[0]);
  });

  it("test_lonePresses_speakTheFullForm_once", () => {
    say("full 1", "short 1");
    run(1000);
    say("full 2", "short 2");
    run(5000);
    expect(heard.map((h) => h.text)).toEqual(["full 1", "full 2"]);
  });

  it("test_withoutShort_theAxesCadenceIsUnchanged", () => {
    for (let i = 1; i <= 8; i += 1) {
      run(i * 120);
      say(`range ${i}`);
    }
    run(2000);
    expect(heard.map((h) => h.text)).toEqual(["range 1", "range 5", "range 8"]);
  });
});

describe("the facade: a11y and focus (BQ-3, BQ-7)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWorker.created = [];
    setHostEnvFactory(() => fakeEnv());
  });
  afterEach(() => {
    setHostEnvFactory(null);
    vi.useRealTimers();
  });

  function mount(): { c: FakeElement; w: FakeWorker; heard: unknown[]; chart: unknown } {
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    (doc.defaultView as { CustomEvent?: unknown }).CustomEvent = CustomEventStub;
    const c = new FakeElement("div", doc);
    c.clientWidth = 200;
    c.clientHeight = 100;
    const heard: unknown[] = [];
    c.addEventListener(ANNOUNCE_EVENT, (e) => heard.push((e as { detail: unknown }).detail));
    const theme = { palette: "default", convention: "standard", colors: {} } as const;
    const chart = createChart({ container: asHtml(c), theme });
    vi.advanceTimersByTime(32);
    return { c, w: FakeWorker.created.at(-1) as FakeWorker, heard, chart };
  }
  const a11y = (w: FakeWorker, m: Partial<Extract<FromWorker, { t: "a11y" }>>): void =>
    w.onmessage?.({ data: { t: "a11y", id: 1, cursorSummary: "14:05, close 1", ...m } });

  it("test_a11y_keyOrigin_isAnnouncedUnderChartCursor_otherOriginsAreNot", () => {
    const { w, heard } = mount();
    a11y(w, {}); // no origin (the retired pointer-hover summary): never spoken
    expect(heard).toEqual([]);
    a11y(w, { short: "14:05, 1", origin: "key" });
    expect(heard).toEqual([
      { politeness: "polite", text: "14:05, close 1", key: CURSOR_ANNOUNCE_KEY },
    ]);
  });

  it("test_rootFocusAndBlur_sendSetFocus_andAChildStopTakingFocusIsABlur", () => {
    const { c, w } = mount();
    c.dispatch("focus", {});
    c.dispatch("blur", {});
    vi.advanceTimersByTime(32);
    const sent = (w.inbox as ToWorker[]).flatMap((m) =>
      m.t === "command" && m.cmd.k === "setFocus" ? [m.cmd.focused] : [],
    );
    expect(sent).toEqual([true, false]);
  });

  // The worker posts one `a11y { cleared }` for both triggers (runtime-cursor-keys.test.ts).
  it("test_heldKey_clearedNoticeMidHold_nothingIsSpokenAfterwards (fake clock; the worker posts the notice on Esc or a bars replace)", () => {
    const { w, heard } = mount();
    let t = 0;
    for (let bar = 1; bar <= 12; bar += 1) {
      a11y(w, { cursorSummary: `full ${bar}`, short: `short ${bar}`, origin: "key" });
      vi.advanceTimersByTime(100); // a key repeat
      t += 100;
    }
    // Mid-hold, a bar is pending in the window (the last one went out at 1000 ms).
    const before = heard.length;
    expect(before).toBeGreaterThan(0);
    a11y(w, { cursorSummary: "", origin: "key", cleared: true });
    vi.advanceTimersByTime(5000); // past every window and trailing timer
    expect(heard.slice(before)).toEqual([]);
    expect(t).toBe(1200);
  });

  it("test_cursorCancel_leavesTheAxesAnnouncerAlone", () => {
    const c = fakeContainer(200, 100);
    (c.ownerDocument.defaultView as { CustomEvent?: unknown }).CustomEvent = CustomEventStub;
    const texts: string[] = [];
    c.addEventListener(ANNOUNCE_EVENT, (e) =>
      texts.push((e as { detail: { text: string } }).detail.text),
    );
    let now = 0; // a manual clock: no wall time in the unit project
    const timers: { at: number; cb: () => void }[] = [];
    const clock = {
      now: () => now,
      setTimer: (cb: () => void, ms: number): void => void timers.push({ at: now + ms, cb }),
    };
    const run = (to: number): void => {
      for (;;) {
        const due = timers.filter((t) => t.at <= to).sort((x, y) => x.at - y.at)[0];
        if (due === undefined) break;
        timers.splice(timers.indexOf(due), 1);
        now = due.at;
        due.cb();
      }
      now = to;
    };
    const axes = createAnnouncer(asHtml(c), clock);
    const cursor = createAnnouncer(asHtml(c), clock, CURSOR_ANNOUNCE_KEY);
    axes("range 1");
    cursor("bar 1");
    run(100);
    axes("range 2"); // pending in the axes' window
    cursor("bar 2"); // pending in the cursor's
    cursor.cancel();
    run(2000);
    expect(texts).toEqual(["range 1", "bar 1", "range 2"]);
  });

  it("test_escapeOnTheRoot_sendsClearCursor_andIsNotConsumed", () => {
    const { c, w } = mount();
    let prevented = 0;
    const key = (k: string, mods: object = {}): void =>
      void c.dispatch("keydown", {
        key: k,
        code: k,
        shiftKey: false,
        ctrlKey: false,
        altKey: false,
        metaKey: false,
        timeStamp: 1,
        preventDefault: () => (prevented += 1),
        ...mods,
      });
    key("Escape");
    key("Escape", { shiftKey: true }); // a modified Esc is left to the page: nothing sent
    vi.advanceTimersByTime(32);
    const sent = (w.inbox as ToWorker[]).filter(
      (m) => m.t === "command" && m.cmd.k === "clearCursor",
    );
    expect(sent).toHaveLength(1);
    expect(prevented).toBe(0); // the universal cancel propagates (E06-D03 D6, 05 §3.3)
  });
});
