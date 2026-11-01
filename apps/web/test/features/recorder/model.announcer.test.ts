// E16-S01 slice 3: the summary region's 10 s batch (E16-D02 §9.3; E16-D06 SR-01, BG-01, BG-05,
// BG-06) on a fake clock: one polite utterance per window, none lost, and an assertive row never
// swallowed — said once per key, after a waiting batch.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  BATCH_WINDOW_MS,
  createBatchAnnouncer,
  type Politeness,
} from "../../../src/features/recorder/model";

type Said = [Politeness, string, number];

function harness() {
  const said: Said[] = [];
  const announcer = createBatchAnnouncer((politeness, text) =>
    said.push([politeness, text, Date.now()]),
  );
  return { said, announcer };
}

/** mulberry32: a small seeded PRNG, so a failing case names its seed and replays exactly. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

describe("recorder batch announcer", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: 0 });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("test_batch_speaks_at_once_then_coalesces_the_window_into_one_utterance", () => {
    const { said, announcer } = harness();
    announcer.push(["ETHUSDT degraded"]);
    vi.advanceTimersByTime(3_000);
    announcer.push(["SOLUSDT stopped recording", "ETHUSDT degraded"]);
    vi.advanceTimersByTime(3_000);
    announcer.push([
      "Auto-record paused · resumes below 85 % of the budget with 20 % of the volume free",
    ]);
    vi.advanceTimersByTime(BATCH_WINDOW_MS);
    expect(said).toEqual([
      ["polite", "ETHUSDT degraded", 0],
      [
        "polite",
        "SOLUSDT stopped recording; ETHUSDT degraded; Auto-record paused · resumes below 85 % of the budget with 20 % of the volume free",
        10_000,
      ],
    ]);
    announcer.push([]);
    vi.advanceTimersByTime(BATCH_WINDOW_MS);
    expect(said).toHaveLength(2);
  });

  it("test_batch_an_alert_waits_for_the_pending_batch_and_is_said_once_per_key", () => {
    const { said, announcer } = harness();
    announcer.alert("level-3", "Recording stopped: …");
    announcer.push(["BTCUSDT gated"]);
    vi.advanceTimersByTime(1_000);
    announcer.push(["ETHUSDT gated"]);
    announcer.alert("incident:ETHUSDT", "Incident: …");
    announcer.alert("level-3", "Recording stopped: …"); // the condition still holds
    vi.advanceTimersByTime(BATCH_WINDOW_MS);
    expect(said).toEqual([
      ["assertive", "Recording stopped: …", 0],
      ["polite", "BTCUSDT gated", 0],
      ["polite", "ETHUSDT gated", 10_000],
      ["assertive", "Incident: …", 10_000],
    ]);
    announcer.release("level-3");
    announcer.alert("level-3", "Recording stopped: …");
    expect(said.at(-1)).toEqual(["assertive", "Recording stopped: …", 11_000]);
  });

  it("test_batch_an_alert_released_while_it_waits_is_never_said_d02", () => {
    const { said, announcer } = harness();
    announcer.push(["BTCUSDT degraded"]);
    vi.advanceTimersByTime(1_000);
    announcer.push(["ETHUSDT degraded"]); // the window's batch is waiting
    announcer.alert("level-3", "Recording stopped: …"); // held behind it
    vi.advanceTimersByTime(1_000);
    announcer.release("level-3"); // its condition ended before the batch was spoken
    vi.advanceTimersByTime(BATCH_WINDOW_MS);
    expect(said).toEqual([
      ["polite", "BTCUSDT degraded", 0],
      ["polite", "ETHUSDT degraded", 10_000],
    ]);
    // A new episode inside a window is held again and said once, after the batch.
    announcer.push(["SOLUSDT degraded"]);
    announcer.alert("level-3", "Recording stopped again: …");
    announcer.release("level-3");
    announcer.alert("level-3", "Recording stopped a third time: …");
    vi.advanceTimersByTime(BATCH_WINDOW_MS);
    expect(said.slice(2)).toEqual([
      ["polite", "SOLUSDT degraded", 20_000],
      ["assertive", "Recording stopped a third time: …", 20_000],
    ]);
  });

  it("test_batch_alerts_held_behind_a_batch_are_one_write_in_their_order_d02", () => {
    const { said, announcer } = harness();
    announcer.push(["BTCUSDT degraded"]);
    vi.advanceTimersByTime(1_000);
    announcer.push(["ETHUSDT degraded"]);
    announcer.alert("level-3", "Recording stopped: A.");
    announcer.alert("incident:ETHUSDT:open", "Incident: B.");
    announcer.alert("incident:SOLUSDT:open", "Incident: C.");
    announcer.release("incident:ETHUSDT:open"); // only its own entry goes
    vi.advanceTimersByTime(BATCH_WINDOW_MS);
    // Two `say`s in one tick would commit only the last, so the held alerts are joined: none is swallowed.
    expect(said.filter(([politeness]) => politeness === "assertive")).toEqual([
      ["assertive", "Recording stopped: A. Incident: C.", 10_000],
    ]);
  });

  it("test_batch_dispose_cancels_the_waiting_batch", () => {
    const { said, announcer } = harness();
    announcer.push(["BTCUSDT degraded"]);
    announcer.push(["ETHUSDT degraded"]);
    announcer.dispose();
    vi.advanceTimersByTime(BATCH_WINDOW_MS * 2);
    expect(said).toEqual([["polite", "BTCUSDT degraded", 0]]);
  });

  it("test_batch_property_one_polite_per_window_nothing_lost_alerts_after_their_batch_seeded", () => {
    // An alert's text is one space-free token, so a write that joins several (d02) can be told apart again.
    const tokens = (text: string): string[] => text.split(" ");
    for (let seed = 1; seed <= 40; seed += 1) {
      vi.setSystemTime(0);
      const rand = mulberry32(seed);
      const { said, announcer } = harness();
      const events: { phrase?: string; alert?: string; at: number }[] = [];
      const spoken = (alert: string): number =>
        said.filter(([p, text]) => p === "assertive" && tokens(text).includes(alert)).length;
      /** The alerts whose condition holds; one that ends before it was spoken is never to be spoken (d02). */
      const holding: string[] = [];
      const withdrawn = new Set<string>();
      for (let step = 0; step < 60; step += 1) {
        vi.advanceTimersByTime(Math.floor(rand() * 4_000));
        const at = Date.now();
        if (holding.length > 0 && rand() < 0.2) {
          const [ended] = holding.splice(Math.floor(rand() * holding.length), 1);
          if (ended !== undefined) {
            if (spoken(ended) === 0) withdrawn.add(ended);
            announcer.release(`k-${ended}`);
          }
        }
        if (rand() < 0.85) {
          events.push({ phrase: `S${step} degraded`, at });
          announcer.push([`S${step} degraded`]);
        } else {
          events.push({ alert: `alert-${step}`, at });
          holding.push(`alert-${step}`);
          announcer.alert(`k-alert-${step}`, `alert-${step}`);
        }
      }
      vi.advanceTimersByTime(BATCH_WINDOW_MS);
      const polite = said.filter(([p]) => p === "polite");
      polite.slice(1).forEach(([, , at], i) => {
        expect(at - (polite[i]?.[2] ?? 0), `seed ${seed}`).toBeGreaterThanOrEqual(BATCH_WINDOW_MS);
      });
      const pushed = events.flatMap((e) => (e.phrase === undefined ? [] : [e.phrase]));
      expect(
        polite.flatMap(([, text]) => text.split("; ")),
        `seed ${seed}`,
      ).toEqual(pushed);
      events.forEach(({ alert, at }, i) => {
        if (alert === undefined) return;
        // Released before it was spoken: gone for good. Otherwise said once, never swallowed.
        expect(spoken(alert), `seed ${seed}: ${alert}`).toBe(withdrawn.has(alert) ? 0 : 1);
        if (withdrawn.has(alert)) return;
        const index = said.findIndex(
          ([p, text]) => p === "assertive" && tokens(text).includes(alert),
        );
        expect(said[index]?.[2], `seed ${seed}`).toBeLessThanOrEqual(at + BATCH_WINDOW_MS);
        // every phrase pushed before the alert was spoken before it: never swallowed, never ahead
        const earlier = said
          .slice(0, index)
          .flatMap(([p, text]) => (p === "polite" ? text.split("; ") : []));
        for (const before of events.slice(0, i))
          if (before.phrase) expect(earlier, `seed ${seed}`).toContain(before.phrase);
      });
      announcer.dispose();
    }
  });
});
