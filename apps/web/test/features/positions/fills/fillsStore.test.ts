/**
 * E29-S04 (#979) the fills store (`fillsStore.ts`) on the goldens: one row per (account, exec id)
 * whatever the source and its order (BQ-9), the dedupe counter, newest first from REST's newest-
 * first pages and WS's oldest-first snapshot, the 5,000 bound, revocation and narrowing (SR-E29-11)
 * and the new-fills pill (D01 D13 g).
 */
import { describe, expect, it } from "vitest";
import { createFillsStore, MAX_FILLS } from "../../../../src/features/positions/fills/fillsStore";
import { sumFills } from "../../../../src/features/positions/fills/model/aggregate";
import { newestFirst } from "../../../../src/features/positions/fills/model/fillRow";
import type { AccountInfo } from "../../../../src/features/positions/model/rowMapping";
import { delta, MAIN, reset, snap, SUB1, SUB2 } from "../support/fakes";
import { deltaBody, ORDER_A3F2, restItems, snapshotBody } from "./support/fills";

const account = (id: string, label: string): AccountInfo => ({
  id,
  label,
  environment: "live",
  positionMode: "one_way",
  marginMode: "isolated",
  mmRate: null,
});
const DIRECTORY = [account(MAIN, "Main"), account(SUB1, "Sub-1"), account(SUB2, "Sub-2")];
const [newFill] = deltaBody().executions;
if (newFill === undefined) throw new Error("golden");

function started() {
  const store = createFillsStore();
  store.setStarted(true);
  store.setAccounts(DIRECTORY);
  return store;
}
const execs = (store: ReturnType<typeof createFillsStore>): string[] =>
  store.getSnapshot().rows.map((r) => r.execId.slice(-4));

describe("No double counting: the same exec_id on the WS stream and again through REST backfill", () => {
  it("WS first, then REST: once in the list, once in the aggregate, the counter reads 1", () => {
    const store = started();
    store.applyFrames([snap({ executions: [] }), delta({ executions: [newFill] })]);
    store.applyRest([restItems().find((i) => i.exec_id === newFill.exec_id)]);
    store.commit();
    const { rows, dedupeHits } = store.getSnapshot();
    expect(rows.map((r) => r.execId)).toEqual([newFill.exec_id]);
    expect(dedupeHits).toBe(1);
    expect(sumFills(rows).fills).toBe(1);
  });

  it("REST first, then WS: the same", () => {
    const store = started();
    store.applyRest([restItems().find((i) => i.exec_id === newFill.exec_id)]);
    store.applyFrames([snap({ executions: [newFill] })]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ dedupeHits: 1 });
    expect(store.getSnapshot().rows).toHaveLength(1);
  });

  it("the whole overlap: the snapshot's 12 fills again in REST's 14, each counted once", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.applyRest(restItems());
    store.commit();
    const { rows, dedupeHits } = store.getSnapshot();
    expect([rows.length, dedupeHits]).toEqual([14, 12]);
    const board02 = rows.filter((r) => r.orderId === ORDER_A3F2);
    expect(sumFills(board02)).toMatchObject({ fills: 4, trades: 4 });
  });

  it("the key is the account and the exec id: two accounts' equal exec ids stay two fills", () => {
    const store = started();
    const twin = {
      ...newFill,
      id: "0e000000-0000-4000-8000-0000000000ff",
      exchange_account_id: SUB1,
    };
    store.applyFrames([snap({ executions: [newFill, twin] })]);
    store.commit();
    expect(
      store
        .getSnapshot()
        .rows.map((r) => r.accountId)
        .sort(),
    ).toEqual([MAIN, SUB1].sort());
    expect(store.getSnapshot().dedupeHits).toBe(0);
  });

  it("a member only the second copy carries is added: REST's trade group to a WS fill", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    const leg = (): unknown =>
      store.getSnapshot().rows.find((r) => r.execId.endsWith("0010"))?.tradeGroupId;
    expect(leg()).toBeUndefined();
    store.applyRest(restItems());
    store.commit();
    expect(leg()).toBe("0c000000-0000-4000-8000-000000007c1e");
  });
});

describe("the order: newest first, whatever arrives first", () => {
  const expected = (): string[] => {
    const store = started();
    store.applyRest(restItems());
    store.commit();
    return [...store.getSnapshot().rows].sort(newestFirst).map((r) => r.execId.slice(-4));
  };

  it("REST's newest-first page and WS's oldest-first snapshot merge into one order", () => {
    for (const first of ["ws", "rest"] as const) {
      const store = started();
      if (first === "ws") store.applyFrames([snap(snapshotBody())]);
      store.applyRest([...restItems()].slice(0, 7));
      store.commit();
      if (first === "rest") store.applyFrames([snap(snapshotBody())]);
      store.applyRest([...restItems()].slice(7));
      store.commit();
      expect(execs(store)).toEqual(expected());
      expect(execs(store).slice(0, 4)).toEqual(["0014", "0013", "0011", "0012"]);
    }
  });

  it("board 02's two fills of one millisecond keep the server's keyset order (id, descending)", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    const at = execs(store);
    expect(at.indexOf("0005")).toBe(at.indexOf("0004") - 1);
  });
});

describe("commits, the bound and the baseline", () => {
  it("inputs mark the store dirty; one commit publishes them, once", () => {
    const store = started();
    store.commit();
    const before = store.getSnapshot();
    store.applyFrames([snap(snapshotBody())]);
    expect(store.getSnapshot()).toBe(before);
    expect(store.commit()).toBe(true);
    expect(store.commit()).toBe(false);
    expect(store.getSnapshot().version).toBe(before.version + 1);
  });

  it(`holds ${MAX_FILLS} fills at most: the oldest leave first`, () => {
    const store = started();
    const many = Array.from({ length: MAX_FILLS + 10 }, (_, i) => ({
      ...newFill,
      id: `0e000000-0000-4000-8000-${i.toString(16).padStart(12, "0")}`,
      exec_id: `x${i}`,
      ts_ms: 1_792_000_000_000 + i,
    }));
    store.applyFrames([snap({ executions: many })]);
    store.commit();
    const { rows } = store.getSnapshot();
    expect(rows).toHaveLength(MAX_FILLS);
    expect(rows.at(-1)?.execId).toBe("x10");
    store.applyFrames([delta({ executions: [many[0]] })]); // an evicted fill is no repeat
    store.commit();
    expect(store.getSnapshot().dedupeHits).toBe(0);
  });

  it("a delta never extends a void baseline; any reset but revoked or narrowed keeps the fills", () => {
    const store = started();
    store.applyFrames([delta({ executions: [newFill] })]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ rows: [], status: "loading" });
    store.applyFrames([snap(snapshotBody()), reset("gap"), delta({ executions: [newFill] })]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "resyncing" });
    expect(store.getSnapshot().rows).toHaveLength(12);
  });

  it("the status: loading, live, offline, could not load, no accounts, idle", () => {
    const store = started();
    store.commit();
    expect(store.getSnapshot().status).toBe("loading");
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "live", asOfMs: 1_793_455_331_100 });
    store.setLink(false);
    store.commit();
    expect(store.getSnapshot().status).toBe("offline");
    const failed = started();
    failed.markSnapshotFailed();
    failed.commit();
    expect(failed.getSnapshot().status).toBe("snapshot_failed");
    failed.markRetrying();
    failed.setAccounts([]);
    failed.commit();
    expect(failed.getSnapshot().status).toBe("no_accounts");
    store.setStarted(false);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "idle", rows: [] });
  });
});

describe("revocation and narrowing (SR-E29-11, E29-D05 F-02)", () => {
  it("revoked: every fill leaves at once, each account gets its line, and no read brings one back", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.applyFrames([reset("revoked")]);
    store.applyRest(restItems());
    store.commit();
    const s = store.getSnapshot();
    expect(s).toMatchObject({ status: "revoked", rows: [] });
    expect(s.withdrawn.map((w) => w.label).sort()).toEqual(["Main", "Sub-1", "Sub-2"]);
  });

  it("narrowed: every fill leaves; the directory names who left; REST brings back who stayed", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.applyFrames([reset("narrowed")]);
    store.applyRest(restItems()); // set out before the directory: the candidates' fills stay out
    store.commit();
    expect(store.getSnapshot().rows).toEqual([]);
    expect(store.takeNarrowed()).toBe(true);
    expect(store.takeNarrowed()).toBe(false);
    store.setAccounts(DIRECTORY.filter((a) => a.id !== SUB2));
    store.applyRest(restItems());
    store.commit();
    const s = store.getSnapshot();
    expect(s.withdrawn).toEqual([{ accountId: SUB2, label: "Sub-2" }]);
    expect(new Set(s.rows.map((r) => r.accountId))).toEqual(new Set([MAIN, SUB1]));
  });

  it("a narrowed sub_ok drops the account it no longer names; an over-cap account never shows", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.setEffective({ exchange_account_ids: [MAIN, SUB1] });
    store.setOverCap([SUB1]);
    store.applyRest(restItems());
    store.commit();
    const s = store.getSnapshot();
    expect(new Set(s.rows.map((r) => r.accountId))).toEqual(new Set([MAIN]));
    expect(s.withdrawn.map((w) => w.accountId)).toEqual([SUB2]);
    store.dismissWithdrawn(SUB2);
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([]);
  });
});

describe("new fills while the list is scrolled away (D01 D13 g)", () => {
  it("they wait above the top, counted on the pill; nothing moves; back at the top they join", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    const shown = store.getSnapshot().rows;
    store.setAtTop(false);
    store.applyFrames([delta({ executions: [newFill] })]);
    store.applyRest(restItems().filter((i) => i.exec_id !== newFill.exec_id)); // the ADL is newer
    store.commit();
    const away = store.getSnapshot();
    expect(away.newCount).toBe(1); // the ADL fill (14:10) is newer than the top; 0007 is not
    expect(away.rows.some((r) => r.execId.endsWith("0014"))).toBe(false);
    expect(away.rows[0]?.key).toBe(shown[0]?.key);
    store.setAtTop(true);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ newCount: 0 });
    expect(store.getSnapshot().rows[0]?.execId.slice(-4)).toBe("0014");
  });
});
