import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CHROMIUM_FLAGSETS,
  DONE_GRACE_MS,
  cellsComplete,
  chromiumFlagSet,
} from "../../../bench/matrix/matrix-lib.mjs";
import { PINNED_CHROMIUM_FLAGS } from "../../../bench/report.mjs";

describe("cellsComplete", () => {
  const cell = (scenario: string) => ({ kind: "cell", scenario });

  it("is true once every requested scenario has a cell", () => {
    expect(cellsComplete([cell("B1"), cell("B9")], ["B1", "B9"])).toBe(true);
  });

  it("is false while a requested scenario is missing", () => {
    expect(cellsComplete([cell("B1")], ["B1", "B9"])).toBe(false);
  });

  it("ignores results that are not cells", () => {
    const results = [cell("B1"), { kind: "gl-unavailable", scenario: "B9" }];
    expect(cellsComplete(results, ["B1", "B9"])).toBe(false);
  });

  it("is false for an empty request", () => {
    expect(cellsComplete([cell("B1")], [])).toBe(false);
  });

  it("waits a bounded grace for the page's own /done", () => {
    expect(DONE_GRACE_MS).toBe(30_000);
  });
});

describe("E11-T06: the Chromium flag sets", () => {
  it("keeps the K01 software-GL set when no flag set is named", () => {
    const set = chromiumFlagSet(undefined);
    expect(set.flags).toEqual([...PINNED_CHROMIUM_FLAGS]);
    expect(set.flags).toContain("--use-angle=swiftshader");
    expect(set.name).toBe(CHROMIUM_FLAGSETS["pinned-k01"].name);
  });

  it("swaps SwiftShader for the host GL driver and GPU rasterization in hardware-gl", () => {
    const { flags } = chromiumFlagSet("hardware-gl");
    expect(flags).toContain("--use-angle=gl");
    expect(flags).toContain("--enable-gpu-rasterization");
    expect(flags.some((f) => f.includes("swiftshader"))).toBe(false);
    expect(flags).not.toContain("--ignore-gpu-blocklist");
  });

  it("appends the page's extra flags and names the set in the manifest", () => {
    const set = chromiumFlagSet("hardware-gl", ["--enable-precise-memory-info"]);
    expect(set.flags.at(-1)).toBe("--enable-precise-memory-info");
    expect(set.name).not.toBe(CHROMIUM_FLAGSETS["pinned-k01"].name);
  });

  it("rejects an unknown flag set", () => {
    expect(() => chromiumFlagSet("tuned")).toThrow(/unknown chromium --flagset tuned/);
    expect(() => chromiumFlagSet("toString")).toThrow(/unknown chromium --flagset/);
  });

  describe("the engine-bench lane picks the set from BENCH_MODE", () => {
    const LANE = readFileSync(
      fileURLToPath(
        new URL("../../../../../.github/workflows/_job-engine-bench.yml", import.meta.url),
      ),
      "utf8",
    );
    const choose =
      /flagset=pinned-k01\n\s*if \[ "\$BENCH_MODE" = "gpu" \]; then flagset=hardware-gl; fi\n\s*echo "CHROMIUM_FLAGSET=\$flagset" >> "\$GITHUB_ENV"/;

    it("selects hardware-gl on the gpu route and keeps pinned-k01 on the fallback", () => {
      expect(LANE).toMatch(choose);
      const pick = (mode: string): string => (mode === "gpu" ? "hardware-gl" : "pinned-k01");
      expect(chromiumFlagSet(pick("gpu")).flags).toContain("--use-angle=gl");
      expect(chromiumFlagSet(pick("fallback")).flags).toContain("--use-angle=swiftshader");
    });

    it("passes the chosen set to every Chromium matrix run", () => {
      // Every invocation's arguments sit on its own line and the next one.
      const runs = LANE.split("run-matrix.mjs").slice(1);
      expect(runs).toHaveLength(3);
      for (const r of runs)
        expect(r.split("\n").slice(0, 2).join("\n")).toContain('--flagset "$CHROMIUM_FLAGSET"');
    });
  });
});
