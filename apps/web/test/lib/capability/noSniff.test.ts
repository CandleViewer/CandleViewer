import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #371 AC2 and DoD: the probe classifies from measured frame time only (BQ-10; the ruling allows no other
// signal). No source file of the module may read the user agent, the GPU renderer or vendor string, the memory
// or core count, the screen or media queries, or reach a global object it could read them from: every input
// is injected (frame times, storage, the analytics seam). Each pattern carries an example it must catch.
const DIR = resolve(import.meta.dirname, "../../../src/lib/capability");
const FORBIDDEN: readonly (readonly [RegExp, string])[] = [
  [/userAgent/i, "navigator.userAgentData"],
  [/navigator/, "navigator.gpu"],
  [/WEBGL_debug_renderer_info/, 'getExtension("WEBGL_debug_renderer_info")'],
  [/UNMASKED_(RENDERER|VENDOR)/, "ext.UNMASKED_RENDERER_WEBGL"],
  [/\bRENDERER\b/, "gl.RENDERER"],
  [/\bVENDOR\b/, "gl.VENDOR"],
  [/getParameter/, "gl.getParameter(x)"],
  [/getContext/, 'canvas.getContext("webgl2")'],
  [/deviceMemory/, "nav.deviceMemory"],
  [/hardwareConcurrency/, "nav.hardwareConcurrency"],
  [/platform/i, "nav.platform"],
  [/\bscreen\b/, "screen.width"],
  [/devicePixelRatio/, "devicePixelRatio > 1"],
  [/matchMedia/, 'matchMedia("(pointer: coarse)")'],
  [/performance\s*\.\s*memory/, "performance.memory.jsHeapSizeLimit"],
  [/measureUserAgentSpecificMemory/, "performance.measureUserAgentSpecificMemory()"],
  [/\.gpu\b/, "nav.gpu.requestAdapter()"],
  [/globalThis/, 'globalThis["nav" + "igator"]'],
  [/\b(window|self|document)\s*[.[]/, 'self["nav"]'],
  [/\b(localStorage|sessionStorage)\b/, "localStorage.getItem(k)"],
];

describe("no user-agent or GPU-string branching in the capability probe", () => {
  const files = readdirSync(DIR).filter((f) => f.endsWith(".ts"));

  it("noSniff_the_module_has_source_files", () => {
    expect(files.length).toBeGreaterThanOrEqual(3);
  });

  it.each(FORBIDDEN.map(([re, example]) => [String(re), re, example] as const))(
    "noSniff_pattern_%s_catches_its_example",
    (_, re, example) => {
      expect(example).toMatch(re);
    },
  );

  it.each(files)("noSniff_%s_reads_no_identity_string", (f) => {
    const src = readFileSync(join(DIR, f), "utf8");
    for (const [re] of FORBIDDEN) expect(src, `${f} matches ${re}`).not.toMatch(re);
  });
});
