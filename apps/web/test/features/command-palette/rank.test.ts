import { describe, expect, it } from "vitest";
import { buildIndex } from "../../../src/features/command-palette/rank";
import type {
  PaletteGroup,
  PaletteRow,
  PaletteSource,
  SourceContext,
} from "../../../src/features/command-palette/sources";

// E10-S05 (#5236): the per-opening row index (pure; E10-Q04 times it).

const CTX: SourceContext = {
  claims: { authenticated: true, role: "owner", permissions: [] },
  bindings: new Map(),
  isValid: () => true,
  viewAs: null,
};
const row = (id: string, group: PaletteGroup): PaletteRow => ({
  id,
  label: id,
  group,
  target: { kind: "command", commandId: id },
});
const source = (id: string, rows: readonly PaletteRow[]): PaletteSource => ({
  id,
  group: rows[0]?.group ?? "Action",
  rows: () => rows,
});

describe("E10-S05 rank.ts: buildIndex", () => {
  it("orders rows Navigate, Panel, Symbol, Action, Setting whatever the source order", () => {
    const index = buildIndex(
      [
        source("settings", [row("s1", "Setting")]),
        source("actions", [row("a1", "Action"), row("a2", "Action")]),
        source("symbols", [row("y1", "Symbol")]),
        source("routes", [row("n1", "Navigate")]),
      ],
      CTX,
    );
    expect(index.map((r) => r.id)).toEqual(["n1", "y1", "a1", "a2", "s1"]);
  });

  it("keeps the source order inside a group and the first of a repeated id", () => {
    const index = buildIndex(
      [source("a", [row("x", "Action"), row("y", "Action")]), source("b", [row("x", "Action")])],
      CTX,
    );
    expect(index.map((r) => r.id)).toEqual(["x", "y"]);
  });

  it("is empty with no rows: an empty group has no header (CMP-059 makes none)", () => {
    expect(buildIndex([source("none", [])], CTX)).toEqual([]);
  });

  it("passes the context to every source", () => {
    const seen: SourceContext[] = [];
    buildIndex([{ id: "spy", group: "Action", rows: (ctx) => (seen.push(ctx), []) }], CTX);
    expect(seen).toEqual([CTX]);
  });
});
