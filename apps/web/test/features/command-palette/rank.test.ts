import { describe, expect, it } from "vitest";
import {
  SUGGESTED_LIMIT,
  buildIndex,
  emptyQuerySections,
} from "../../../src/features/command-palette/rank";
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

describe("E10-S05 rank.ts: the empty query's sections", () => {
  const index: PaletteRow[] = [
    row("route:R-190", "Navigate"),
    row("route:R-180", "Navigate"),
    ...["a1", "a2", "a3", "a4", "a5", "a6", "a7"].map((id) => row(`command:${id}`, "Action")),
    { ...row("command:gated", "Action"), disabledReason: "Your role can't place orders." },
  ];

  it("Recent: newest first, resolved against this opening's index; an unknown id is dropped silently", () => {
    const { recent } = emptyQuerySections(index, {
      recent: ["command:a3", "route:R-300", "route:R-190"],
      counts: {},
    });
    expect(recent.map((r) => r.id)).toEqual(["command:a3", "route:R-190"]);
  });

  it("Suggested: ungated actions not in Recent, most used first, ties in keymap order", () => {
    const { suggested } = emptyQuerySections(index, {
      recent: ["command:a1"],
      counts: { "command:a6": 4, "command:a4": 4, "command:a7": 1, "command:gated": 9 },
    });
    expect(suggested.map((r) => r.id)).toEqual([
      "command:a4",
      "command:a6",
      "command:a7",
      "command:a2",
      "command:a3",
    ]);
    expect(suggested).toHaveLength(SUGGESTED_LIMIT);
  });

  it("is empty for an empty index", () => {
    expect(emptyQuerySections([], { recent: ["x"], counts: { x: 1 } })).toEqual({
      recent: [],
      suggested: [],
    });
  });
});
