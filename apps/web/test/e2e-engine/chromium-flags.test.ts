// E11-Q02 (#444): the e2e config's copy of the engine bench's pinned flags must equal the original.
// report.mjs is read as TEXT (not imported: it is not a declared export of the engine package).
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { PINNED_CHROMIUM_FLAGS } from "../../e2e/engine-harness/chromium-flags";

describe("PINNED_CHROMIUM_FLAGS", () => {
  it("equals the list declared in packages/chart-engine/bench/report.mjs", async () => {
    const text = await readFile(
      resolve(import.meta.dirname, "../../../../packages/chart-engine/bench/report.mjs"),
      "utf8",
    );
    const block = /PINNED_CHROMIUM_FLAGS\s*=\s*Object\.freeze\(\[([^\]]*)\]\)/u.exec(text)?.[1];
    expect(block, "the flag list was not found in report.mjs").toBeDefined();
    const declared = [...(block ?? "").matchAll(/"([^"]+)"/gu)].map((m) => m[1]);
    expect([...PINNED_CHROMIUM_FLAGS]).toEqual(declared);
  });
});
