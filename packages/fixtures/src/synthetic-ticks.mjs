// Seeded synthetic price-tick generator: a rate harness for the flash-rate work (E47-S04 / G005).
// Not a venue payload (C-13.5 is not engaged). Pure and deterministic: no wall clock, no
// Math.random. Timestamps come from a fake clock (`startMs` + index / rate); prices are integer
// ticks plus a decimal string built with integer arithmetic, never floats.

export const SYNTHETIC_TICK_DEFAULTS = Object.freeze({
  seed: 1,
  rateHz: 40,
  durationMs: 5000,
  startMs: 0,
  startPriceTicks: 6_500_000,
  tickDecimals: 2,
});

export const SYNTHETIC_TICK_PRESETS = Object.freeze({
  burst: Object.freeze({ rateHz: 40, durationMs: 5000 }),
  idle: Object.freeze({ rateHz: 0.2, durationMs: 60_000 }),
  "steady-40hz": Object.freeze({ rateHz: 40, durationMs: 60_000 }),
});

// mulberry32: fixed 32-bit PRNG, returns a function yielding floats in [0, 1).
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Integer ticks to a decimal string ("6500000" with 2 decimals is "65000.00").
export function formatTicks(ticks, decimals) {
  const scale = 10 ** decimals;
  const sign = ticks < 0 ? "-" : "";
  const abs = Math.abs(ticks);
  const whole = Math.floor(abs / scale);
  if (decimals === 0) return `${sign}${whole}`;
  return `${sign}${whole}.${String(abs % scale).padStart(decimals, "0")}`;
}

// Returns [{ tMs, priceTicks, price, move }] with move in {"up","down","flat"}.
export function generateTicks(options = {}) {
  const o = { ...SYNTHETIC_TICK_DEFAULTS, ...options };
  if (!(o.rateHz > 0) || !(o.durationMs >= 0)) {
    throw new RangeError("rateHz must be > 0 and durationMs >= 0");
  }
  const rand = mulberry32(o.seed);
  const count = Math.floor((o.durationMs * o.rateHz) / 1000);
  const ticks = [];
  let priceTicks = o.startPriceTicks;
  for (let i = 0; i < count; i += 1) {
    const r = rand();
    let move = "flat";
    if (r < 0.4) move = "up";
    else if (r < 0.8) move = "down";
    if (move === "up") priceTicks += 1;
    else if (move === "down") priceTicks -= 1;
    ticks.push({
      tMs: o.startMs + Math.round((i * 1000) / o.rateHz),
      priceTicks,
      price: formatTicks(priceTicks, o.tickDecimals),
      move,
    });
  }
  return ticks;
}

export function generatePresetTicks(name, options = {}) {
  const preset = SYNTHETIC_TICK_PRESETS[name];
  if (!preset) throw new RangeError(`unknown preset: ${name}`);
  return generateTicks({ ...preset, ...options });
}
