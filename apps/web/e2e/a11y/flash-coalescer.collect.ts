import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "@playwright/test";
import { REPORT_DIR } from "./screens";

// Gate 5, calibration (E47-S04 / WCAG 2.3.1): the flash coalescer is driven by the seeded 40 Hz
// burst fixture on a FAKE clock (the schedule is deterministic); the resulting flash starts are then
// replayed on a frame-exact virtual clock on ONE harness element carrying data-flash-audit, whose composited
// luminance is sampled at 60 Hz. A raw, uncoalesced 5 Hz flash is captured as the negative: it MUST
// trip G005 (the job asserts that). Real consumers (price flash, liquidation) are not built here.
const SAMPLE_HZ = 60;
const FRAME_MS = 1000 / SAMPLE_HZ;
// Playwright runs with cwd = apps/web.
const ROOT = resolve(process.cwd(), "../..");
const TICKS = pathToFileURL(resolve(ROOT, "packages/fixtures/src/synthetic-ticks.mjs")).href;
const COALESCER = pathToFileURL(resolve(ROOT, "packages/ui/src/components/flashCoalescer.ts")).href;
// The value-flash recipe runs over motion.duration.fast (100 ms) on motion.easing.accelerate
// (cubic-bezier(0.3, 0, 1, 1)); theme.css cv-flash.
const FLASH_MS = 100;
const EASING = "cubic-bezier(0.3, 0, 1, 1)";
// The recipe's own peak is 0.25 and, composited over a dark surface, moves luminance by well under
// the G005 step (0.1), so the shipped recipe could never register. The audit overlays the worst case:
// opaque peak (1.0), so every start the coalescer lets through is counted and the gate measures the
// START RATE, not the paint.
const AUDIT_PEAK = 1;

interface Start {
  tMs: number;
  direction: "up" | "down";
}
interface Tick {
  tMs: number;
  move: "up" | "down" | "flat";
}
interface Coalescer {
  onTick(id: string, tick: "up" | "down" | "flat", nowMs: number): void;
  frame(nowMs: number): readonly { cellId: string; direction: "up" | "down" }[];
  isSustained(id: string, nowMs: number): boolean;
}

// Fake-time drive: onTick per tick at its tMs, frame() every 1000/60 ms (as a rAF loop would).
function drive(
  makeCoalescer: () => Coalescer,
  ticks: Tick[],
  endMs: number,
  probeAt: number[] = [],
): { starts: Start[]; sustained: Record<string, boolean> } {
  const c = makeCoalescer();
  const starts: Start[] = [];
  const sustained: Record<string, boolean> = {};
  let i = 0;
  for (let f = 0; f * FRAME_MS <= endMs; f++) {
    const now = f * FRAME_MS;
    while (i < ticks.length && (ticks[i]?.tMs ?? Infinity) <= now) {
      const t = ticks[i++] as Tick;
      c.onTick("price", t.move, t.tMs);
    }
    for (const s of c.frame(now)) starts.push({ tMs: now, direction: s.direction });
    for (const p of probeAt)
      if (Math.abs(now - p) < FRAME_MS / 2) sustained[String(p)] = c.isSustained("price", now);
  }
  return { starts, sustained };
}

async function replay(
  page: import("@playwright/test").Page,
  name: string,
  starts: Start[],
  seconds: number,
): Promise<{ lum: number[]; seconds: number }> {
  await page.setContent(
    `<div data-flash-audit="${name}" style="position:relative;width:200px;height:60px;background:#0b0e14">` +
      '<div id="o" style="position:absolute;inset:0;opacity:0"></div></div>',
  );
  return page.evaluate(
    async ({ starts, secs, hz, flashMs, easing, peak }) => {
      const o = document.getElementById("o") as HTMLElement;
      const bg = [0x0b, 0x0e, 0x14];
      const lin = (c: number): number => {
        const v = c / 255;
        return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      };
      // Composited colour = bg * (1 - a) + white * a, with a read from the live computed opacity. White
      // is the audit's worst case, so the luminance step per start is always >= the G005 delta.
      const lumOf = (): number => {
        const a = Number(getComputedStyle(o).opacity);
        const ch = (k: number): number => lin((bg[k] ?? 0) * (1 - a) + 255 * a);
        return 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2);
      };
      o.style.background = "#fff";
      // Frame-exact virtual clock: sample k is taken at k / hz, and each flash is a paused Web
      // Animation seeked to (sample time - its start). The browser still resolves the recipe's
      // easing, but no timer jitter can move a start across a 1 s window edge (G005 counts frames).
      const out: number[] = [];
      let n = 0;
      let current: { anim: Animation; at: number } | undefined;
      for (let k = 0; k <= secs * hz; k++) {
        const now = (k * 1000) / hz;
        while (n < starts.length && (starts[n]?.tMs ?? Infinity) <= now + 1e-6) {
          current?.anim.cancel();
          const anim = o.animate([{ opacity: peak }, { opacity: 0 }], {
            duration: flashMs,
            easing,
          });
          anim.pause();
          current = { anim, at: starts[n]?.tMs ?? now };
          n++;
        }
        if (current) current.anim.currentTime = now - current.at;
        out.push(lumOf());
      }
      return { lum: out, seconds: secs };
    },
    { starts, secs: seconds, hz: SAMPLE_HZ, flashMs: FLASH_MS, easing: EASING, peak: AUDIT_PEAK },
  );
}

test("collect flash-coalescer luminance (40 Hz fixture + injected 5 Hz negative)", async ({
  page,
}) => {
  const ticksMod = (await import(TICKS)) as {
    generateTicks: (o: { seed: number; rateHz: number; durationMs: number }) => Tick[];
  };
  const coMod = (await import(COALESCER)) as { createFlashCoalescer: () => Coalescer };
  const burst = ticksMod.generateTicks({ seed: 1, rateHz: 40, durationMs: 5000 });
  const { starts } = drive(coMod.createFlashCoalescer, burst, 5000);
  if (starts.length < 5) throw new Error(`A11Y-INFRA coalescer produced ${starts.length} starts`);

  // Sustained: 60 s at 40 Hz. After 10 s the cell is sustained and no further start happens.
  const steady = ticksMod.generateTicks({ seed: 1, rateHz: 40, durationMs: 60_000 });
  const long = drive(coMod.createFlashCoalescer, steady, 60_000, [9000, 11_000, 30_000, 59_000]);
  const late = long.starts.filter((s) => s.tMs >= 10_000 + FRAME_MS).length;
  const sustained = { sustainedAt11s: long.sustained["11000"], startsAfter10s: late };
  if (!long.sustained["11000"] || !long.sustained["59000"] || long.sustained["9000"] || late > 0)
    throw new Error(`A11Y-INFRA sustained behaviour not as documented: ${JSON.stringify(long)}`);

  const good = await replay(page, "price-flash-harness", starts, 5);
  // The pass capture must not pass vacuously: every start has to move luminance by the G005 step.
  // Frame 0 is measured against the dark field (a start can land on it).
  const dark = Math.min(...good.lum);
  const rises = good.lum.filter((v, k) => v - (k === 0 ? dark : (good.lum[k - 1] ?? v)) >= 0.1);
  if (rises.length < starts.length)
    throw new Error(
      `A11Y-INFRA harness registered ${rises.length} of ${starts.length} flash starts`,
    );
  // Upper bound, independent of paint: a coalescer that restarts every frame would hold the overlay
  // bright and read as 0 flashes, so no half-open 1 s window may hold more than 2 starts (HS-1).
  const crowded = starts.findIndex((s, k) => (starts[k + 2]?.tMs ?? Infinity) - s.tMs < 1000);
  if (crowded >= 0)
    throw new Error(
      `A11Y-INFRA coalescer started 3 flashes within 1 s at ${starts[crowded]?.tMs} ms`,
    );
  // Negative: raw 5 Hz flash, no coalescer (what a liquidation flash must never do).
  const raw: Start[] = Array.from({ length: 25 }, (_, k) => ({ tMs: k * 200, direction: "up" }));
  const bad = await replay(page, "liquidation-flash-injected", raw, 5);

  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(
    `${REPORT_DIR}/flash-coalescer.json`,
    JSON.stringify({
      fps: good.lum.length / good.seconds,
      components: { "component:price-flash-harness": good.lum },
      starts: starts.length,
      sustained,
    }),
  );
  writeFileSync(
    `${REPORT_DIR}/flash-injected.json`,
    JSON.stringify({
      fps: bad.lum.length / bad.seconds,
      components: { "component:liquidation-flash-injected": bad.lum },
    }),
  );
});
