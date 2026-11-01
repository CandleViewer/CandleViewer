import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// #371 AC2 and DoD: the probe classifies from measured frame time only. No source file of the module may
// read the user agent, the GPU renderer or vendor string, or the memory or core count (BQ-10).
const DIR = resolve(import.meta.dirname, "../../../src/lib/capability");
const FORBIDDEN = [
  /userAgent/i,
  /navigator/,
  /WEBGL_debug_renderer_info/,
  /UNMASKED_(RENDERER|VENDOR)/,
  /\bRENDERER\b/,
  /\bVENDOR\b/,
  /getParameter/,
  /deviceMemory/,
  /hardwareConcurrency/,
  /platform/i,
];

describe("no user-agent or GPU-string branching in the capability probe", () => {
  const files = readdirSync(DIR).filter((f) => f.endsWith(".ts"));

  it("noSniff_the_module_has_source_files", () => {
    expect(files.length).toBeGreaterThanOrEqual(3);
  });

  it.each(files)("noSniff_%s_reads_no_identity_string", (f) => {
    const src = readFileSync(join(DIR, f), "utf8");
    for (const re of FORBIDDEN) expect(src, `${f} matches ${re}`).not.toMatch(re);
  });
});
