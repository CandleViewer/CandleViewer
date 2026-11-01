// @vitest-environment node
// E10-Q04 (#303) BQ-Q04-06 B: the render counter compiles out of production builds. The probe is built
// the way the app is (production mode, the switch as `vite.config.ts` defines it) and every chunk is
// searched for the counter; the build with the switch on holds it, so the absence is not vacuous.
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build, loadConfigFromFile, type Rollup } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../..");
const PROBE = resolve(ROOT, "src/features/app-shell/perfProbe.tsx");
/** What the counter leaves in a chunk: its window key and the Profiler that feeds it. */
const COUNTER = ["__cvPerfProbe", "Profiler"];

afterEach(() => vi.unstubAllEnvs());

async function codeOf(flag: boolean): Promise<string> {
  vi.stubEnv("NODE_ENV", "production"); // vite reads `NODE_ENV` first: under vitest it is `test`
  const result = await build({
    root: ROOT,
    configFile: false,
    logLevel: "silent",
    mode: "production",
    define: { __CV_PERF_PROBE__: JSON.stringify(flag) },
    build: {
      write: false,
      minify: false,
      lib: { entry: PROBE, formats: ["es"], fileName: "probe" },
      rollupOptions: { external: (id) => /^react(-dom)?(\/|$)/u.test(id) },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as Rollup.RollupOutput[];
  return outputs
    .flatMap((o) => o.output)
    .flatMap((o) => (o.type === "chunk" ? [o.code] : []))
    .join("\n");
}

const PROFILING = { timeout: 180_000 };
const ENTRY = "\0cv-react-dom-client";

/** `react-dom/client`, built in production mode with the app's own `vite.config.ts` aliases. */
async function reactDomOf(): Promise<string> {
  const loaded = await loadConfigFromFile(
    { command: "build", mode: "production" },
    resolve(ROOT, "vite.config.ts"),
  );
  vi.stubEnv("NODE_ENV", "production");
  const result = await build({
    root: ROOT,
    configFile: false,
    logLevel: "silent",
    mode: "production",
    resolve: { alias: loaded?.config.resolve?.alias ?? [] },
    define: { "process.env.NODE_ENV": '"production"' }, // lib mode keeps it; the app build sets it
    plugins: [
      {
        name: "cv-react-dom-client-entry",
        enforce: "pre", // lib mode hands the entry over as a path under the root
        resolveId: (id) => (id.endsWith("cv-react-dom-client") ? ENTRY : null),
        load: (id) => (id === ENTRY ? 'export { createRoot } from "react-dom/client";' : null),
      },
    ],
    build: {
      write: false,
      minify: false,
      lib: { entry: "cv-react-dom-client", formats: ["es"], fileName: "dom" },
      rollupOptions: { external: (id) => /^(react|scheduler)(\/|$)/u.test(id) },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as Rollup.RollupOutput[];
  return outputs
    .flatMap((o) => o.output)
    .flatMap((o) => (o.type === "chunk" ? [o.code] : []))
    .join("\n");
}

describe("the E10-Q04 render counter in a build", () => {
  it("perfProbe_productionBuild_holdsNoCounter", { timeout: 120_000 }, async () => {
    const code = await codeOf(false);
    expect(code).toContain("probeCommits"); // the module is there: the absence below proves something
    expect(COUNTER.filter((text) => code.includes(text))).toEqual([]);
  });

  it("perfProbe_probeBuild_holdsTheCounter", { timeout: 120_000 }, async () => {
    const code = await codeOf(true);
    expect(COUNTER.filter((text) => code.includes(text))).toEqual(COUNTER);
  });

  it.each([
    ["1", true],
    [undefined, false],
  ])("perfProbe_viteConfig_withCV_PERF_PROBE_%s_profilingReactDom_%s", PROFILING, async (v, on) => {
    vi.stubEnv("CV_PERF_PROBE", v);
    const code = await reactDomOf();
    expect(code).toContain("createRoot"); // react-dom was bundled: the check below is not vacuous
    // react-dom's Profiler `onRender` read: only its profiling build has it among the production ones.
    expect(code.includes(".onRender")).toBe(on);
  });

  it.each([
    ["vite.config.ts", "1", "true"],
    ["vite.config.ts", undefined, "false"],
    ["vite.config.ts", "true", "false"],
    ["vitest.config.mjs", "1", "false"],
  ])("perfProbe_%s_withCV_PERF_PROBE_%s_defines_%s", { timeout: 60_000 }, async (file, v, out) => {
    vi.stubEnv("CV_PERF_PROBE", v);
    const loaded = await loadConfigFromFile(
      { command: "build", mode: "production" },
      resolve(ROOT, file),
    );
    const define = loaded?.config.define as Record<string, unknown> | undefined;
    expect(define?.["__CV_PERF_PROBE__"]).toBe(out);
  });
});
