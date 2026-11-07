/* eslint-disable @typescript-eslint/no-explicit-any */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const gate = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/no-hue-alone.mjs" as string
)) as any;
const data = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/data-ink-lib.mjs" as string
)) as any;
const registry = JSON.parse(
  readFileSync(new URL("../../../../tools/contrast/encodings.json", import.meta.url), "utf-8"),
);
const matrix = JSON.parse(
  readFileSync(new URL("../../contrast/data-ink-matrix.json", import.meta.url), "utf-8"),
);

describe("no-hue-alone registry", () => {
  it("covers every required encoding with a surface and a channel", () => {
    expect(gate.validate(registry)).toEqual([]);
    for (const n of gate.REQUIRED_ENCODINGS) expect(registry.encodings[n]).toBeDefined();
  });
  it("requires the rule graph's four encodings (E37-D03 §9.4, EN-1 to EN-4)", () => {
    const graph = ["node-type", "port-type", "edge-validity", "graph-diagnostic"];
    expect(gate.REQUIRED_ENCODINGS).toEqual(expect.arrayContaining(graph));
  });
  it("a surface declaring no channel fails naming surface and encoding", () => {
    const bad = structuredClone(registry);
    bad.encodings.pnl.surfaces["positions table"] = [];
    const errs: string[] = gate.validate(bad);
    expect(errs).toHaveLength(1);
    expect(errs[0]).toMatch(/positions table.*pnl/);
  });
  it("an encoding with no surfaces fails", () => {
    const bad = structuredClone(registry);
    bad.encodings["bid-ask"].surfaces = {};
    expect(gate.validate(bad)[0]).toMatch(/bid-ask/);
  });
  it("demo/live must carry a text channel on every surface", () => {
    const bad = structuredClone(registry);
    bad.encodings["demo-live"].surfaces["order ticket"] = ["glyph"];
    expect(gate.validate(bad)[0]).toMatch(/demo-live.*text/);
  });
});

describe("regenerated matrix (S06)", () => {
  it("has zero failing checks in every theme, both densities, both palettes", () => {
    expect(matrix.summary.failingPerTheme).toEqual({ dark: 0, light: 0, "high-contrast": 0 });
    const palettes = new Set(
      matrix.rows.filter((r: any) => r.kind === "cvd").map((r: any) => r.palette),
    );
    expect(palettes).toEqual(new Set(data.PALETTES.map((p: { id: string }) => p.id)));
    const dens = new Set(
      matrix.rows.filter((r: any) => r.kind === "text").map((r: any) => r.density),
    );
    expect(dens).toEqual(new Set(["comfortable", "compact"]));
  });
  it("high-contrast body text meets 7:1", () => {
    const rows = matrix.rows.filter(
      (r: any) =>
        r.kind === "text" && r.theme === "high-contrast" && r.id.startsWith("color.text."),
    );
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) expect(r.ratio).toBeGreaterThanOrEqual(7);
  });
});
