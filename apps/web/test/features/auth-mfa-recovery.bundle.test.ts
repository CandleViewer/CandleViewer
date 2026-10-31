// @vitest-environment node
// #2711 BQ-08 (a), security lens L-1: SCR-002's recovery-code form is behind `__CV_MFA_RECOVERY_UI__` and must be absent
// from a production build made with the switch off, the way the fault channel is (`faultInjection.bundle.test.ts`). The step
// is built the way the app is (production mode, the switch as `vite.config.ts` defines it) and every chunk is searched for
// the form. The proof is not vacuous: the same build holds the step itself, and the step built with the switch on holds it.
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build, loadConfigFromFile, type Rollup } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../..");
const STEP = resolve(ROOT, "src/features/auth/TwoFactorStep.tsx");

afterEach(() => vi.unstubAllEnvs());

/** Every chunk of the step, built in production mode with the switch set; nothing is written to disk. */
async function chunksOf(flag: boolean): Promise<Rollup.OutputChunk[]> {
  // vite reads `NODE_ENV` first: under vitest it is `test`
  vi.stubEnv("NODE_ENV", "production");
  const result = await build({
    root: ROOT,
    configFile: false,
    logLevel: "silent",
    mode: "production",
    define: { __CV_MFA_RECOVERY_UI__: JSON.stringify(flag) },
    build: {
      write: false,
      minify: false,
      lib: { entry: STEP, formats: ["es"], fileName: "step" },
      rollupOptions: { external: (id) => /^react(-dom)?(\/|$)/.test(id) },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as Rollup.RollupOutput[];
  return outputs
    .flatMap((o) => o.output)
    .filter((o): o is Rollup.OutputChunk => o.type === "chunk");
}

const holds = (chunks: readonly Rollup.OutputChunk[], text: string): boolean =>
  chunks.some((c) => c.code.includes(text));

/** What the form leaves in a chunk: its field id, its label, its copy and its route call. */
const FORM = ["mfa-recovery", "Recovery code", "Use a recovery code instead", "verifyRecovery"];

describe("the recovery form in a build (#2711 BQ-08 a)", () => {
  it(
    "is in no chunk of a production build, which holds the step all the same",
    { timeout: 120_000 },
    async () => {
      const chunks = await chunksOf(false);
      expect(holds(chunks, "Two-factor code")).toBe(true); // the step is there: the absence below proves something
      expect(FORM.filter((text) => holds(chunks, text))).toEqual([]);
    },
  );

  it("is in a production build made with the switch on", { timeout: 120_000 }, async () => {
    const chunks = await chunksOf(true);
    expect(FORM.filter((text) => holds(chunks, text))).toEqual(FORM);
  });
});

describe("the switch in the configs (#2711 BQ-08 a)", () => {
  /** What a config defines for the switch when `CV_MFA_RECOVERY_UI` is `value`. */
  async function flagOf(file: string, value: string | undefined): Promise<unknown> {
    vi.stubEnv("CV_MFA_RECOVERY_UI", value);
    const loaded = await loadConfigFromFile(
      { command: "build", mode: "production" },
      resolve(ROOT, file),
    );
    return (loaded?.config.define as Record<string, unknown> | undefined)?.[
      "__CV_MFA_RECOVERY_UI__"
    ];
  }

  it.each(["vite.config.ts", "vitest.config.mjs"])(
    "%s turns it on for `1` and for nothing else",
    { timeout: 60_000 },
    async (file) => {
      expect(await flagOf(file, "1")).toBe("true");
      for (const other of [undefined, "", "0", "true", "yes", " 1"])
        expect(await flagOf(file, other)).toBe("false");
    },
  );
});
