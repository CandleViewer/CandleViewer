// E11-Q02 (#444): the pure parts of the engine E2E suite: the bundle check, the feed codec and the
// seeded fixtures (they are the specs' ground truth, so they are pinned here, not in a browser).
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { decodeBarsFrame } from "../../e2e/engine-harness/barsFrame";
import { FIXTURE_NAMES, buildFixture } from "../../e2e/support/engine/fixtures";
import { encodeFrame, encodeHeader } from "../../e2e/support/engine/frame";
import { findHarnessLeaks } from "../../scripts/check-engine-harness-excluded.mjs";

describe("findHarnessLeaks", () => {
  it("flags an __engine* marker in served code but not in source maps or clean files", () => {
    const leaks = findHarnessLeaks([
      { name: "assets/a.js", text: "window.__engineEvents={}" },
      { name: "index.html", text: "<p>__engine-feed</p>" },
      { name: "assets/a.js.map", text: "__engineEvents" },
      { name: "assets/c.js", text: "console.log(1)" },
    ]);
    expect(leaks.map((l) => l.split(":")[0])).toEqual(["assets/a.js", "index.html"]);
  });
});

describe("feed codec", () => {
  it("round-trips a fixture through the encoder and the page's decoder", () => {
    const b = buildFixture("btcusdt-1m-100k");
    const frame = encodeFrame(b);
    expect(frame.byteLength).toBe(100_000 * 28);
    const buf = frame.buffer.slice(
      frame.byteOffset,
      frame.byteOffset + frame.byteLength,
    ) as ArrayBuffer;
    const d = decodeBarsFrame(encodeHeader(b), buf);
    expect([...d.time.slice(0, 3)]).toEqual([...b.time.slice(0, 3)]);
    expect([...d.close.slice(-3)]).toEqual([...b.close.slice(-3)]);
    expect(() => decodeBarsFrame(encodeHeader(b), new ArrayBuffer(10))).toThrow(RangeError);
  });
});

describe("e2e fixtures", () => {
  it.each(FIXTURE_NAMES)("%s is byte-reproducible and keeps low <= open, close <= high", (name) => {
    const digest = (): string =>
      createHash("sha256")
        .update(encodeFrame(buildFixture(name)))
        .digest("hex");
    expect(digest()).toBe(digest());
    const b = buildFixture(name);
    for (let i = 0; i < b.time.length; i++) {
      expect(b.low[i]).toBeLessThanOrEqual(Math.min(b.open[i]!, b.close[i]!));
      expect(b.high[i]).toBeGreaterThanOrEqual(Math.max(b.open[i]!, b.close[i]!));
    }
  });

  it("100k holds 100k ordered one-minute bars", () => {
    const k = buildFixture("btcusdt-1m-100k");
    expect(k.time).toHaveLength(100_000);
    expect(k.time.every((t, i) => i === 0 || t - k.time[i - 1]! === 60e6)).toBe(true);
  });
});
