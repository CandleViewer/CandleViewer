/**
 * E29-S04 (#979) the fills store (`fillsStore.ts`) on the goldens: one row per (account, exec id)
 * whatever the source, its order and the commit window (BQ-9), the dedupe counter, newest first
 * from REST's newest-first pages and WS's oldest-first snapshot, the 5,000 bound, the directory,
 * revocation and narrowing (SR-E29-11), a failed read, and the new-fills pill (D01 D13 g).
 */
import { describe, expect, it } from "vitest";
import { createFillsStore, MAX_FILLS } from "../../../../src/features/positions/fills/fillsStore";
import { sumFills } from "../../../../src/features/positions/fills/model/aggregate";
import { newestFirst } from "../../../../src/features/positions/fills/model/fillRow";
import type { AccountInfo } from "../../../../src/features/positions/model/rowMapping";
import { delta, MAIN, reset, snap, SUB1, SUB2 } from "../support/fakes";
import { deltaBody, GROUP_7C1E, ORDER_A3F2, restItems, snapshotBody } from "./support/fills";

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
type Store = ReturnType<typeof createFillsStore>;
const execs = (store: Store): string[] => store.getSnapshot().rows.map((r) => r.execId.slice(-4));
const keys = (store: Store): string[] => store.getSnapshot().rows.map((r) => r.key);
const accountsOf = (store: Store): Set<string> =>
  new Set(store.getSnapshot().rows.map((r) => r.accountId));
const withoutSub2 = DIRECTORY.filter((a) => a.id !== SUB2);

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
    expect(leg()).toBe(GROUP_7C1E);
  });

  it("the merged member shows at the first commit when no commit came between the copies", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.applyRest(restItems());
    store.commit();
    const leg = store.getSnapshot().rows.find((r) => r.execId.endsWith("0010"));
    expect(leg?.tradeGroupId).toBe(GROUP_7C1E);
  });

  it("the counter counts a fill once, when the other source first brings it", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.applyRest(restItems());
    store.applyRest(restItems()); // a second backfill: no fill is new to a source
    store.applyFrames([snap(snapshotBody())]); // nor is a re-snapshot
    store.commit();
    expect(store.getSnapshot().dedupeHits).toBe(12);
  });

  it("a repeat from the same source changes nothing to publish", () => {
    const store = started();
    store.applyRest(restItems());
    store.commit();
    store.applyRest(restItems());
    expect(store.commit()).toBe(false);
  });
});

describe("No double counting inside one commit window (SR-E29-11's drops and their re-reads)", () => {
  /** The 12 snapshot fills committed, then a narrowing, the directory without Sub-2 and REST. */
  function droppedAndBack(): Store {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.applyFrames([reset("narrowed")]);
    store.setAccounts(withoutSub2);
    store.applyRest(restItems());
    store.commit();
    return store;
  }

  it("a fill dropped and re-applied inside one commit window is one row", () => {
    const store = droppedAndBack();
    expect(keys(store)).toHaveLength(12); // Main's 8 and Sub-1's 4
    expect(new Set(keys(store)).size).toBe(12);
    store.setLink(false);
    store.commit();
    store.setLink(true);
    store.commit();
    expect(keys(store)).toHaveLength(12);
  });

  it("after it, board 02's order reads its 4 fills, not 7", () => {
    const rows = droppedAndBack()
      .getSnapshot()
      .rows.filter((r) => r.orderId === ORDER_A3F2);
    expect(sumFills(rows)).toMatchObject({ fills: 4, trades: 4 });
  });

  it("a narrowed snapshot keeps the rows of the accounts it serves, once", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.applyFrames([reset("narrowed")]);
    store.commit();
    const served = snapshotBody().executions.filter((i) => i.exchange_account_id !== SUB2);
    store.applyFrames([snap({ executions: served })]);
    store.commit();
    expect(keys(store)).toHaveLength(11);
    store.setAccounts(withoutSub2);
    store.applyRest(restItems());
    store.commit();
    expect([keys(store).length, new Set(keys(store)).size]).toEqual([12, 12]);
  });

  it("an account set over the cap and back is one row a fill", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.setOverCap([SUB1]);
    store.setOverCap([]);
    store.applyRest(restItems());
    store.commit();
    expect([keys(store).length, new Set(keys(store)).size]).toEqual([14, 14]);
  });

  it("a fill revoked inside the commit window is never published", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.applyFrames([delta(deltaBody())]); // 0007, not committed yet
    store.applyFrames([reset("revoked")]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "revoked", rows: [] });
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

  it("an account whose every fill left by the bound holds none: a revoke names it not", () => {
    const store = started();
    const many = Array.from({ length: MAX_FILLS + 10 }, (_, i) => ({
      ...newFill,
      id: `0e000000-0000-4000-8000-${i.toString(16).padStart(12, "0")}`,
      exchange_account_id: i < 10 ? SUB1 : MAIN, // Sub-1's ten are the oldest
      exec_id: `x${i}`,
      ts_ms: 1_792_000_000_000 + i,
    }));
    store.applyFrames([snap({ executions: many })]);
    store.commit();
    store.applyFrames([reset("revoked")]);
    store.commit();
    expect(store.getSnapshot().withdrawn.map((w) => w.label)).toEqual(["Main"]);
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
});

describe("the status", () => {
  const live = (): Store => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    return store;
  };

  it("loading before the first snapshot", () => {
    const store = started();
    store.commit();
    expect(store.getSnapshot().status).toBe("loading");
  });

  it("live from the snapshot, as of its time", () => {
    expect(live().getSnapshot()).toMatchObject({ status: "live", asOfMs: 1_793_455_331_100 });
  });

  it("offline while the link is down", () => {
    const store = live();
    store.setLink(false);
    store.commit();
    expect(store.getSnapshot().status).toBe("offline");
  });

  it("could not load past the budget", () => {
    const store = started();
    store.markSnapshotFailed();
    store.commit();
    expect(store.getSnapshot().status).toBe("snapshot_failed");
  });

  it("Retry takes could not load back to loading", () => {
    const store = started();
    store.markSnapshotFailed();
    store.markRetrying();
    store.commit();
    expect(store.getSnapshot().status).toBe("loading");
  });

  it("no accounts for an empty directory", () => {
    const store = started();
    store.setAccounts([]);
    store.commit();
    expect(store.getSnapshot().status).toBe("no_accounts");
  });

  it("idle once stopped, holding nothing", () => {
    const store = live();
    store.setStarted(false);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "idle", rows: [], all: [] });
  });

  it("a failed read is readFailed beside the status: the rows shown stay (D03:191)", () => {
    const store = live();
    store.setReadFailed(true);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "live", readFailed: true });
    expect(store.getSnapshot().rows).toHaveLength(12);
  });

  it("Retry clears readFailed", () => {
    const store = live();
    store.setReadFailed(true);
    store.markRetrying();
    store.commit();
    expect(store.getSnapshot().readFailed).toBe(false);
  });
});

describe("a security reset waits for no commit window (SR-E29-11)", () => {
  it("commit(true) publishes a revocation at once", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.applyFrames([reset("revoked")]);
    expect(store.commit(true)).toBe(true);
    expect(store.getSnapshot().rows).toEqual([]);
  });

  it("commit(true) publishes a fill that is no reset only at the window's end", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    expect(store.commit(true)).toBe(false);
    expect(store.commit()).toBe(true);
  });
});

describe("the directory (SR-E29-11, in depth)", () => {
  it("a fill of an account the directory does not list is refused", () => {
    const store = createFillsStore();
    store.setStarted(true);
    store.setAccounts(withoutSub2);
    store.applyRest(restItems());
    store.commit();
    expect(accountsOf(store)).toEqual(new Set([MAIN, SUB1]));
  });

  it("the first directory drops a first-paint read's fills of an account it does not list", () => {
    const store = createFillsStore();
    store.setStarted(true);
    store.applyRest(restItems());
    store.commit();
    expect(accountsOf(store).has(SUB2)).toBe(true);
    store.setAccounts(withoutSub2);
    store.commit();
    expect(accountsOf(store)).toEqual(new Set([MAIN, SUB1]));
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
    store.setAccounts(withoutSub2);
    store.applyRest(restItems());
    store.commit();
    const s = store.getSnapshot();
    expect(s.withdrawn).toEqual([{ accountId: SUB2, label: "Sub-2" }]);
    expect(new Set(s.rows.map((r) => r.accountId))).toEqual(new Set([MAIN, SUB1]));
  });

  it("the directory settling a narrowing is taken once: the feed's cue to read REST", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody()), reset("narrowed")]);
    expect(store.takeSettled()).toBe(false);
    store.setAccounts(withoutSub2);
    expect(store.takeSettled()).toBe(true);
    expect(store.takeSettled()).toBe(false);
  });

  it("a snapshot serving every candidate settles the narrowing too", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody()), reset("narrowed"), snap(snapshotBody())]);
    expect(store.takeSettled()).toBe(true);
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

  it("all keeps the held-back fills meanwhile, for the export (D02 D-21)", () => {
    const store = started();
    store.applyFrames([snap(snapshotBody())]);
    store.commit();
    store.setAtTop(false);
    store.applyRest(restItems());
    store.commit();
    const { rows, all, newCount } = store.getSnapshot();
    expect([newCount, all.length, rows.length]).toEqual([1, 14, 13]);
    expect(all[0]?.execId.slice(-4)).toBe("0014");
  });
});
