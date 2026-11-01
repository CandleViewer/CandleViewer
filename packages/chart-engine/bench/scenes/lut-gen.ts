// `lut-gen` scene (E11-T04 PR-3, BQ-T04-09): the CPU cost of one theme switch's colour LUTs —
// three 256-entry RGBA8 rows (bid and ask intensity, delta) interpolated in OkLab into one
// caller-owned buffer, cycling over three seeded themes and both conventions so no switch is a
// repeat. Gated per LUT at <= 2 ms in `lut-gen.perf.test.ts`; nothing here allocates per step.
import { mulberry32 } from "../fixtures/rng.mjs";
import { ColorLutWriter, LUT_BYTES, LUT_ROW_BYTES } from "../../src/theme/ColorLut.js";
import { ingestTheme, type EngineTheme } from "../../src/theme/ThemeIngest.js";
import { THEME_SLOTS } from "../../src/theme/slots.js";

/** Seeded, complete stand-in themes (the engine copies no token value). */
export function benchThemes(seed = 0x7404): EngineTheme[] {
  const rng = mulberry32(seed);
  const hex = (): string =>
    `#${Math.floor(rng() * 0x1000000)
      .toString(16)
      .padStart(6, "0")}`;
  const out: EngineTheme[] = [];
  for (const name of ["dark", "light", "high-contrast"] as const) {
    const colors = Object.fromEntries(THEME_SLOTS.map((s) => [s, hex()]));
    for (const convention of ["standard", "inverted"] as const) {
      out.push(ingestTheme({ name, palette: "default", convention, colors }));
    }
  }
  return out;
}

export class LutGenBench {
  readonly pixels = new Uint8Array(LUT_BYTES);
  readonly #writer = new ColorLutWriter();
  readonly #themes: readonly EngineTheme[];
  #next = 0;
  /** Theme switches generated so far. */
  switches = 0;

  constructor(themes: readonly EngineTheme[] = benchThemes()) {
    this.#themes = themes;
  }

  #theme(): EngineTheme {
    const t = this.#themes[this.#next] as EngineTheme;
    this.#next = (this.#next + 1) % this.#themes.length;
    return t;
  }

  /** One theme switch: every LUT row into `pixels`. */
  step(): Uint8Array {
    this.switches += 1;
    return this.#writer.writeAll(this.#theme(), this.pixels);
  }

  /** One LUT alone (the per-LUT budget): `bid` / `ask` intensity or `delta`. */
  stepOne(lut: "bid" | "ask" | "delta"): Uint8Array {
    const theme = this.#theme();
    if (lut === "delta") return this.#writer.writeDelta(theme, this.pixels, 2 * LUT_ROW_BYTES);
    return this.#writer.writeIntensity(theme, lut, this.pixels, lut === "ask" ? LUT_ROW_BYTES : 0);
  }
}
