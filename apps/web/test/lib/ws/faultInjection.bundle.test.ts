// @vitest-environment node
// E17-T04 S5e (23 4.4; C7, C12): the fault-injection channel is a dev tool and must not ship. The shared worker loads it behind
// `import.meta.env.DEV || __CV_ALLOW_FAULT_INJECTION__`; here the worker is built the way the app is (production mode, the flag
// the way `vite.config.ts` defines it) and every chunk is searched for the channel's sentinel. The proof is not vacuous: the
// same build holds the worker's own code (`cv.v1.json` is the WebSocket subprotocol it opens), and the same worker built for
// development, or with the flag on, does hold the sentinel.
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build, loadConfigFromFile, type Rollup } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FAULT_INJECTION_SENTINEL } from "../../../src/lib/ws/worker/faultChannel";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../..");
const WORKER = resolve(ROOT, "src/lib/ws/worker/wsWorker.ts");

afterEach(() => vi.unstubAllEnvs());

/** Every chunk of the worker, built with a given mode and flag; nothing is written to disk. */
async function chunksOf(
  mode: "production" | "development",
  flag: boolean,
): Promise<Rollup.OutputChunk[]> {
  // vite reads `NODE_ENV` first: under vitest it is `test`, which would make `import.meta.env.DEV` true in a production build
  vi.stubEnv("NODE_ENV", mode);
  const result = await build({
    root: ROOT,
    configFile: false,
    logLevel: "silent",
    mode,
    define: { __CV_ALLOW_FAULT_INJECTION__: JSON.stringify(flag) },
    build: {
      write: false,
      minify: false,
      lib: { entry: WORKER, formats: ["es"], fileName: "worker" },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as Rollup.RollupOutput[];
  return outputs
    .flatMap((o) => o.output)
    .filter((o): o is Rollup.OutputChunk => o.type === "chunk");
}

const holds = (chunks: readonly Rollup.OutputChunk[], text: string) =>
  chunks.some((c) => c.code.includes(text));

describe("the fault channel in a build (E17-T04 S5e)", () => {
  it(
    "is in no chunk of a production build, which holds the worker all the same",
    { timeout: 120_000 },
    async () => {
      expect(FAULT_INJECTION_SENTINEL).toBe("cv-ws-fault-injection");
      const chunks = await chunksOf("production", false);
      expect(holds(chunks, "cv.v1.json")).toBe(true); // the worker is there: the absence below proves something
      expect(holds(chunks, FAULT_INJECTION_SENTINEL)).toBe(false);
      expect(holds(chunks, "installFaultChannel")).toBe(false);
      expect(chunks.map((c) => c.fileName).filter((name) => /fault/i.test(name))).toEqual([]);
    },
  );

  it("is in a development build", { timeout: 120_000 }, async () => {
    const chunks = await chunksOf("development", false);
    expect(holds(chunks, "cv.v1.json")).toBe(true);
    expect(holds(chunks, FAULT_INJECTION_SENTINEL)).toBe(true);
  });

  it(
    "is in a production build made with the flag on, and only then",
    { timeout: 120_000 },
    async () => {
      const chunks = await chunksOf("production", true);
      expect(holds(chunks, "cv.v1.json")).toBe(true);
      expect(holds(chunks, FAULT_INJECTION_SENTINEL)).toBe(true);
    },
  );
});

describe("the flag in the configs (E17-T04 S5e)", () => {
  /** What a config defines for the flag when `CV_ALLOW_FAULT_INJECTION` is `value`; the file is evaluated afresh each time. */
  async function flagOf(file: string, value: string | undefined): Promise<unknown> {
    vi.stubEnv("CV_ALLOW_FAULT_INJECTION", value);
    const loaded = await loadConfigFromFile(
      { command: "build", mode: "production" },
      resolve(ROOT, file),
    );
    return (loaded?.config.define as Record<string, unknown> | undefined)?.[
      "__CV_ALLOW_FAULT_INJECTION__"
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

  it(
    "builds the worker as an ES module, so it can load the channel as a chunk of its own",
    { timeout: 60_000 },
    async () => {
      const loaded = await loadConfigFromFile(
        { command: "build", mode: "production" },
        resolve(ROOT, "vite.config.ts"),
      );
      expect(loaded?.config.worker?.format).toBe("es");
    },
  );
});

/** Every file a build of the whole app emitted, as text: chunks, and the assets a worker is emitted as. */
async function appFiles(flag: boolean): Promise<{ name: string; text: string }[]> {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("CV_ALLOW_FAULT_INJECTION", flag ? "1" : "");
  const result = await build({
    root: ROOT,
    mode: "production",
    logLevel: "silent",
    build: { write: false },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as Rollup.RollupOutput[];
  return outputs
    .flatMap((o) => o.output)
    .map((o) => ({
      name: o.fileName,
      text: o.type === "chunk" ? o.code : typeof o.source === "string" ? o.source : "",
    }));
}

describe("the whole app (E17-T04 S5g)", () => {
  it(
    "holds the worker, and no chunk or asset of it has the fault channel",
    { timeout: 300_000 },
    async () => {
      const files = await appFiles(false);
      // a source map carries the source of wsWorker.ts, which names the channel it does not load: that is no way to reach it
      const code = files.filter((f) => !f.name.endsWith(".map"));
      // the worker is in the app, so the absence below proves something
      const worker = code.filter((f) => /^assets\/wsWorker-.*\.js$/.test(f.name));
      expect(worker.filter((f) => f.text.includes("cv.v1.json")).length).toBeGreaterThan(0);
      expect(files.filter((f) => f.text.includes(FAULT_INJECTION_SENTINEL))).toEqual([]); // not even as source
      expect(code.filter((f) => f.text.includes("installFaultChannel"))).toEqual([]);
    },
  );

  it("has it in the worker of an app built with the flag", { timeout: 300_000 }, async () => {
    const files = await appFiles(true);
    expect(files.filter((f) => f.text.includes(FAULT_INJECTION_SENTINEL)).length).toBeGreaterThan(
      0,
    );
  });
});
