/**
 * E29-S02 (#912) the sections (E29-D02 §6.2, S-35): "Working · 3" and "Conditional — not
 * triggered · 2" from the goldens, each grouped by account and sorted environment → account →
 * time created, oldest first; the account group row's PROPOSED words (BQ-9).
 */
import { describe, expect, it } from "vitest";
import {
  constantsOf,
  mapOrder,
  NO_CONSTANTS,
  type OrderRowModel,
} from "../../../../src/features/positions/orders/model/orderRow";
import {
  compareOrders,
  groupLabel,
  sectionOf,
  sectionsOf,
  sortOrders,
} from "../../../../src/features/positions/orders/model/sections";
import {
  COND,
  directory,
  ENTRY,
  ETH,
  MAIN,
  restOpen,
  snapshotBody,
  STOP,
  SUB1,
  SUB2,
  TP,
} from "./support/orders";

const dir = directory();
const rest = new Map(restOpen().map((o) => [o.id, o]));
const rows = (): OrderRowModel[] =>
  snapshotBody()
    .orders.map((item) => {
      const kept = rest.get(item.id);
      return mapOrder(item, "ws", dir, kept === undefined ? NO_CONSTANTS : constantsOf(kept));
    })
    .filter((r): r is OrderRowModel => r !== null);

describe("Conditional orders are separated", () => {
  it("untriggered conditional orders appear in a distinct section, after Working", () => {
    const sections = sectionsOf(rows());
    expect(sections.map((s) => s.label)).toEqual([
      "Working · 3",
      "Conditional — not triggered · 2",
    ]);
    const ids = (i: number) => sections[i]?.groups.flatMap((g) => g.rows.map((r) => r.id));
    expect(ids(0)).toEqual([TP, ENTRY, ETH]);
    expect(ids(1)).toEqual([COND, STOP]);
  });

  it("each section groups by account: Main, Sub-1, Sub-2", () => {
    const [working, conditional] = sectionsOf(rows());
    expect(working?.groups.map((g) => [g.accountId, g.label, g.rows.length])).toEqual([
      [MAIN, "Main", 1],
      [SUB1, "Sub-1", 1],
      [SUB2, "Sub-2", 1],
    ]);
    expect(conditional?.groups.map((g) => g.accountId)).toEqual([SUB1, SUB2]);
    expect(working?.groups.map(groupLabel)).toEqual([
      "Main · LIVE · 1 order",
      "Sub-1 · LIVE · 1 order",
      "Sub-2 · LIVE · 1 order",
    ]);
  });

  it("an empty section draws no row, and hidden (validated) orders are left out", () => {
    const working = rows().filter((r) => !r.conditional);
    expect(sectionsOf(working).map((s) => s.id)).toEqual(["working"]);
    const hidden = {
      ...working[0],
      state: { ...working[0]?.state, hidden: true },
    } as OrderRowModel;
    expect(sectionsOf([hidden]).length).toBe(0);
    expect(sectionsOf([]).length).toBe(0);
  });

  it("sectionOf follows the row's `conditional`", () => {
    const all = rows();
    expect(all.filter((r) => sectionOf(r) === "conditional").map((r) => r.id)).toEqual([
      COND,
      STOP,
    ]);
  });
});

describe("the default order (D01 D13 a)", () => {
  it("environment, then account label and id, then time created, oldest first, then id", () => {
    const base = rows()[0] as OrderRowModel;
    const make = (over: Partial<OrderRowModel>): OrderRowModel => ({ ...base, ...over });
    const a = make({ id: "a", createdAtMs: 2 });
    const b = make({ id: "b", createdAtMs: 1 });
    const c = make({ id: "c", createdAtMs: null });
    const d = make({ id: "d", environment: "demo", createdAtMs: 0 });
    const e = make({ id: "e", accountLabel: "Alpha", accountId: "z", createdAtMs: 9 });
    expect(sortOrders([d, c, a, e, b]).map((r) => r.id)).toEqual(["e", "b", "a", "c", "d"]);
    expect(compareOrders(a, a)).toBe(0);
  });

  it("a new order joins the end of its account's group, so nothing above it moves", () => {
    const all = rows();
    const newest = { ...(all[0] as OrderRowModel), id: "zz", createdAtMs: Date.now() };
    const sorted = sortOrders([...all, newest]);
    const mainRows = sorted.filter((r) => r.accountId === MAIN && !r.conditional);
    expect(mainRows.at(-1)?.id).toBe("zz");
  });

  it("several orders in a group read the plural group row", () => {
    const base = rows()[0] as OrderRowModel;
    const many = [base, { ...base, id: "x" }, { ...base, id: "y" }];
    const [working] = sectionsOf(many);
    expect(working?.groups.map(groupLabel)).toEqual(["Main · LIVE · 3 orders"]);
    // an account the directory does not name shows its id (the positions grid's rule)
    const unnamed = groupLabel({ accountId: "acct", label: null, environment: "demo", rows: many });
    expect(unnamed).toBe("acct · DEMO · 3 orders");
  });

  it("a group whose environment is not known drops the segment, never leaving it empty", () => {
    const base = rows()[0] as OrderRowModel;
    const many = [base, { ...base, id: "x" }, { ...base, id: "y" }];
    const group = { accountId: MAIN, label: "Main", environment: null, rows: many };
    expect(groupLabel(group)).toBe("Main · 3 orders");
    expect(groupLabel({ ...group, rows: [base] })).toBe("Main · 1 order");
    for (const label of [groupLabel(group), groupLabel({ ...group, rows: [base] })])
      expect(label).not.toMatch(/·\s+·/);
  });

  it("the environment words are D02's LIVE and DEMO, and the PROPOSED TESTNET", () => {
    const base = rows()[0] as OrderRowModel;
    const group = { accountId: MAIN, label: "Main", rows: [base] };
    expect(groupLabel({ ...group, environment: "live" })).toBe("Main · LIVE · 1 order");
    expect(groupLabel({ ...group, environment: "demo" })).toBe("Main · DEMO · 1 order");
    expect(groupLabel({ ...group, environment: "testnet" })).toBe("Main · TESTNET · 1 order");
  });
});
