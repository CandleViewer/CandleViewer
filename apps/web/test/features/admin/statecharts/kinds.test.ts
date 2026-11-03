/**
 * E42-S08 (#1137): the catalogue's kinds as the inspector names them. The B-number map is pinned to
 * the committed chart files (`B01.order.machine.json` …), and the kinds with a row plus the four
 * rowless ones (`23-ws-protocol.md` §6.4, W9) are exactly the twenty charts.
 */
import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  B_NUMBERS,
  isRowless,
  kindLabel,
  ROW_KINDS,
  ROWLESS_KINDS,
} from "../../../../src/features/admin/statecharts/kinds";

const MACHINES = resolve(
  import.meta.dirname,
  "../../../../../../services/api/candleviewer/statechart/machines",
);

/** `B07.chase.machine.json` -> ["chase", 7], for every committed chart. */
const COMMITTED = readdirSync(MACHINES)
  .map((name) => /^B(\d{2})\.([a-z_]+)\.machine\.json$/.exec(name))
  .filter((match): match is RegExpExecArray => match !== null)
  .map((match) => [match[2] ?? "", Number(match[1])] as const);

describe("the catalogue's kinds", () => {
  it("test_kinds_b_numbers_equal_the_committed_chart_files", () => {
    expect(COMMITTED).toHaveLength(20);
    expect(Object.entries(B_NUMBERS).sort()).toEqual([...COMMITTED].sort());
  });

  it("test_kinds_row_kinds_and_rowless_kinds_are_the_twenty_charts_once_each", () => {
    const all = [...ROW_KINDS, ...ROWLESS_KINDS];
    expect(new Set(all).size).toBe(all.length);
    expect([...all].sort()).toEqual(COMMITTED.map(([kind]) => kind).sort());
    expect([...ROWLESS_KINDS].map((kind) => B_NUMBERS[kind])).toEqual([8, 9, 13, 15]);
  });

  it("test_kinds_label_reads_the_b_number_and_an_unknown_kind_as_itself", () => {
    expect(kindLabel("order")).toBe("order (B1)");
    expect(kindLabel("kill_switch")).toBe("kill_switch (B18)");
    expect(kindLabel("future_kind")).toBe("future_kind");
    expect(kindLabel("constructor")).toBe("constructor");
  });

  it("test_kinds_rowless_detection_names_b8_b9_b13_b15_only", () => {
    expect(isRowless("position_protection")).toBe(true);
    expect(isRowless("paper_account")).toBe(true);
    expect(isRowless("order")).toBe(false);
    expect(isRowless("toString")).toBe(false);
  });
});
