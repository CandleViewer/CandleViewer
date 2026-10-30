// Scenario: The backend swap is invisible to the rest of the engine (E11-T05 S3, README BQ-85).
// Outside the two backends (src/gl, src/canvas2d) no module names `GLBackend`, and the profile
// literal "degraded-2d" appears only where it is a type, the wire value or the ready/frame report.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const BACKENDS = /^src\/(gl|canvas2d)\//;
/** Where the literal may stand: the protocol and §8 types, and the host's forced re-init. */
const PROFILE_FILES = ["src/api/types.ts", "src/worker/host.ts", "src/worker/protocol.ts"];

const sources = (): [string, string][] =>
  (readdirSync(join(PKG, "src"), { recursive: true }) as string[])
    .filter((f) => f.endsWith(".ts"))
    .map((f) => relative(PKG, join(PKG, "src", f)).replaceAll("\\", "/"))
    .filter((f) => !BACKENDS.test(f))
    .map((f) => [f, readFileSync(join(PKG, f), "utf8")]);

describe("Scenario: The backend swap is invisible to the rest of the engine (S3 guard)", () => {
  it("no module outside src/gl and src/canvas2d names GLBackend", () => {
    expect(
      sources()
        .filter(([, text]) => /\bGLBackend\b/.test(text))
        .map(([f]) => f),
    ).toEqual([]);
  });

  it('"degraded-2d" outside the backends: types, the wire value and the ready/frame report only', () => {
    const stray = sources().flatMap(([file, text]) =>
      text
        .split("\n")
        .map((line, i) => [`${file}:${i + 1}`, line] as const)
        .filter(([, line]) => line.includes('"degraded-2d"'))
        .filter(([at, line]) => {
          if (PROFILE_FILES.some((f) => at.startsWith(`${f}:`))) return false;
          return !(at.startsWith("src/worker/runtime.ts:") && /renderProfile/.test(line));
        })
        .map(([at]) => at),
    );
    expect(stray).toEqual([]);
  });
});
