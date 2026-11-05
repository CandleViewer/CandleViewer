/**
 * E42-S08 (#1137) §3.3: the inspector's store. The page's hold reads the list once per visit; a
 * machine view's open reads its detail and then its chart, once per `kind@hash` per visit. No timer:
 * nothing is read on a schedule (BQ-7). One read in flight per resource, a new filter or machine
 * aborts the older read, the last release aborts and drops everything, and a `403` on any read asks
 * for the area's withdrawal once and stops every read for good (BQ-8).
 */
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  vetDetail,
  vetExport,
  vetList,
  type InspectorOutcome,
  type MachineRef,
} from "../../../../src/features/admin/statecharts/inspectorReads";
import {
  chartKey,
  createInspectorStore,
  useInspectorHold,
  useInspectorSelector,
  useOpenMachine,
  type InspectorDeps,
  type InspectorStore,
} from "../../../../src/features/admin/statecharts/inspectorStore";
import {
  DEGRADED_ORDER_LIST,
  LATCHED_DETAIL,
  LATCHED_KEY,
  ORDER_EXPORT,
  ORDER_HASH,
} from "./fixtures";

type Kind = "list" | "detail" | "export";
interface Call {
  readonly kind: Kind;
  readonly arg: unknown;
  readonly signal: AbortSignal;
  readonly answer: (outcome: InspectorOutcome<unknown>) => void;
}

const LATCHED: MachineRef = { key: LATCHED_KEY, env: "demo" };
const OTHER: MachineRef = { key: "order:0a000000-0000-4000-8000-000000000001", env: "demo" };
const LIST = vetList(DEGRADED_ORDER_LIST);
/** The other filter's page: the same kinds and slices (`22`), every row. */
const ALL = vetList({ ...DEGRADED_ORDER_LIST, items: [...DEGRADED_ORDER_LIST.items].reverse() });
/** `22`'s page as a re-read a few seconds later serves it: only the slices' read time moved. */
const movedList = (at: string) => ({
  ...DEGRADED_ORDER_LIST,
  snapshots: { ...DEGRADED_ORDER_LIST.snapshots, generated_at: at },
  metrics: { ...DEGRADED_ORDER_LIST.metrics, generated_at: at },
});
const DETAIL = vetDetail(LATCHED_DETAIL);
const CHART = vetExport(ORDER_EXPORT, "order");
const ok = (body: unknown): InspectorOutcome<unknown> => ({ kind: "ok", body });
/** The latched order's detail with another hash, as after a redeploy. */
const redeployed = (hash: string) =>
  vetDetail({ ...LATCHED_DETAIL, machine: { ...LATCHED_DETAIL.machine, machine_hash: hash } });

/** A store on fake timers whose reads the test answers one by one. */
function setup() {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 9, 15, 18, 0, 6));
  const calls: Call[] = [];
  const denials: (string | undefined)[] = [];
  const asked =
    (kind: Kind) =>
    (arg: unknown, signal: AbortSignal): Promise<never> =>
      new Promise((resolve) => {
        calls.push({ kind, arg, signal, answer: (o) => resolve(o as never) });
      });
  const deps: InspectorDeps = {
    now: () => Date.now(),
    readList: asked("list"),
    readDetail: asked("detail"),
    readExport: asked("export"),
    deny: (refId) => void denials.push(refId),
  };
  const store = createInspectorStore(deps);
  const kinds = (): Kind[] => calls.map((call) => call.kind);
  /** Answers the newest call of `kind` and lets its promise settle. */
  const answer = async (kind: Kind, outcome: InspectorOutcome<unknown>): Promise<void> => {
    [...calls]
      .reverse()
      .find((call) => call.kind === kind)
      ?.answer(outcome);
    await vi.advanceTimersByTimeAsync(0);
  };
  return { store, calls, denials, kinds, answer };
}

/** Lets queued microtasks (a deferred release or close) run. */
const settle = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};

afterEach(() => {
  vi.useRealTimers();
});

describe("the list: read on hold, on a filter and on Re-read, never on a timer", () => {
  it("test_store_hold_reads_the_list_once_per_visit", async () => {
    const { store, calls, kinds, answer } = setup();
    const release = store.hold();
    expect(calls.map((c) => [c.kind, c.arg])).toEqual([["list", { latchedOnly: false }]]);
    expect(store.getState().list).toMatchObject({ phase: "idle", inFlight: true });
    const again = store.hold();
    await answer("list", ok(LIST));
    const third = store.hold();
    expect(kinds()).toEqual(["list"]);
    expect(store.getState().list).toMatchObject({ phase: "ok", inFlight: false, data: LIST });
    [release, again, third].forEach((r) => r());
  });

  it("test_store_no_timer_ten_minutes_pass_and_nothing_is_read", async () => {
    const { store, kinds, answer } = setup();
    const release = store.hold();
    await answer("list", ok(LIST));
    const close = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(kinds()).toEqual(["list", "detail", "export"]);
    close();
    release();
  });

  it("test_store_latched_only_reads_degraded_and_aborts_the_older_read", async () => {
    const { store, calls, answer } = setup();
    const release = store.hold();
    store.setLatchedOnly(true);
    expect(calls.map((c) => c.arg)).toEqual([{ latchedOnly: false }, { latchedOnly: true }]);
    expect(calls[0]?.signal.aborted).toBe(true);
    calls[0]?.answer(ok(LIST)); // the older answer comes late: dropped
    await settle();
    expect(store.getState().list).toMatchObject({
      phase: "idle",
      inFlight: true,
      latchedOnly: true,
    });
    await answer("list", ok(LIST));
    expect(store.getState().list).toMatchObject({ phase: "ok", latchedOnly: true });
    store.setLatchedOnly(true); // no change, no read
    expect(calls).toHaveLength(2);
    // A new filter is a new list: the other filter's page is kept for its kinds and slices only,
    // marked as the other filter's, so none of its rows shows while this one's are read.
    store.setLatchedOnly(false);
    expect(store.getState().list).toMatchObject({
      phase: "idle",
      inFlight: true,
      latchedOnly: false,
      otherFilter: true,
      data: LIST,
    });
    expect(calls.at(-1)?.arg).toEqual({ latchedOnly: false });
    await answer("list", ok(ALL));
    expect(store.getState().list).toMatchObject({ phase: "ok", latchedOnly: false, data: ALL });
    expect(store.getState().list.otherFilter).toBeUndefined();
    release();
  });

  it("test_store_a_new_filters_failed_first_page_keeps_the_other_page_for_its_kinds", async () => {
    const { store, kinds, answer } = setup();
    const release = store.hold();
    await answer("list", ok(ALL));
    store.setLatchedOnly(true);
    await answer("list", { kind: "failed", reason: "timeout" });
    expect(store.getState().list).toMatchObject({
      phase: "failed",
      reason: "timeout",
      otherFilter: true,
      data: ALL,
    });
    store.retry("list");
    await answer("list", ok(LIST));
    expect(store.getState().list).toMatchObject({ phase: "ok", latchedOnly: true, data: LIST });
    expect(store.getState().list.otherFilter).toBeUndefined();
    // The kinds read the same on both filters (`22`): the first page's are kept.
    expect(store.getState().list.data?.kinds).toBe(ALL?.kinds);
    expect(kinds()).toEqual(["list", "list", "list"]);
    release();
  });

  it("test_store_reread_reads_the_list_and_the_open_machine_once_each", async () => {
    const { store, kinds, answer } = setup();
    const release = store.hold();
    const close = store.open(LATCHED);
    store.reread(); // both in flight: nothing repeated
    expect(kinds()).toEqual(["list", "detail"]);
    await answer("list", ok(LIST));
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    store.reread();
    expect(kinds()).toEqual(["list", "detail", "export", "list", "detail"]);
    await answer("detail", ok(DETAIL));
    expect(kinds()).toHaveLength(5); // the chart of this kind and hash is the visit's already
    close();
    release();
  });

  it("test_store_keeps_the_rows_through_a_failed_reread_and_retries_on_request", async () => {
    const { store, kinds, answer } = setup();
    const release = store.hold();
    await answer("list", ok(LIST));
    store.reread();
    await answer("list", { kind: "failed", reason: "status", status: 503 });
    expect(store.getState().list).toMatchObject({
      phase: "failed",
      data: LIST,
      reason: "status",
      status: 503,
    });
    store.retry("list");
    expect(kinds()).toEqual(["list", "list", "list"]);
    release();
  });

  it("test_store_reread_with_the_same_json_keeps_the_same_objects", async () => {
    const { store, answer } = setup();
    const release = store.hold();
    await answer("list", ok(LIST));
    const first = store.getState().list.data;
    store.reread();
    await answer("list", ok(JSON.parse(JSON.stringify(LIST))));
    expect(store.getState().list.data).toBe(first);
    release();
  });

  it("test_store_a_reread_that_moves_only_generated_at_keeps_the_rows_and_kinds", async () => {
    const { store, answer } = setup();
    const release = store.hold();
    await answer("list", ok(LIST));
    const first = store.getState().list.data;
    store.reread();
    await answer("list", ok(vetList(movedList("2026-10-15T18:00:09Z"))));
    const next = store.getState().list.data;
    expect(next?.snapshots.generated_at).toBe("2026-10-15T18:00:09Z"); // "as of" moves
    expect(next?.items).toBe(first?.items);
    expect(next?.kinds).toBe(first?.kinds);
    expect(next?.meta).toBe(first?.meta);
    release();
  });

  it.each([
    ["not_built", { kind: "not_built" }, { phase: "not_built" }],
    ["not_found", { kind: "not_found" }, { phase: "not_built" }],
    ["invalid_cursor", { kind: "invalid_cursor" }, { phase: "failed", status: 400 }],
  ] as const)("test_store_list_answer_%s_reads_as_its_state", async (_name, outcome, expected) => {
    const { store, answer } = setup();
    const release = store.hold();
    await answer("list", outcome);
    expect(store.getState().list).toMatchObject(expected);
    release();
  });
});

describe("a machine: its detail, then its chart once per kind and hash", () => {
  it("test_store_open_reads_the_detail_then_the_chart_by_its_bare_kind", async () => {
    const { store, calls, answer } = setup();
    const close = store.open(LATCHED);
    expect(calls.map((c) => [c.kind, c.arg])).toEqual([["detail", LATCHED]]);
    expect(store.getState().machine).toMatchObject({ ref: LATCHED, phase: "idle", inFlight: true });
    await answer("detail", ok(DETAIL));
    expect(calls.map((c) => [c.kind, c.arg])).toEqual([
      ["detail", LATCHED],
      ["export", "order"],
    ]);
    expect(store.getState().machine.chart).toMatchObject({
      kind: "order",
      hash: ORDER_HASH,
      phase: "idle",
      inFlight: true,
    });
    await answer("export", ok(CHART));
    expect(store.getState().machine).toMatchObject({
      phase: "ok",
      detail: DETAIL,
      chart: { phase: "ok", inFlight: false, chart: CHART },
    });
    close();
  });

  it("test_store_reads_a_chart_once_per_kind_and_hash_in_a_visit", async () => {
    const { store, kinds, answer } = setup();
    const release = store.hold();
    await answer("list", ok(LIST));
    const first = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    first();
    await settle(); // closed: the visit, held by the page, keeps its chart
    const close = store.open(OTHER);
    await answer("detail", ok(DETAIL));
    expect(kinds()).toEqual(["list", "detail", "export", "detail"]);
    expect(store.getState().machine.chart).toMatchObject({ phase: "ok", chart: CHART });
    expect(chartKey("order", ORDER_HASH)).toBe(`order@${ORDER_HASH}`);
    // A redeployed chart has another hash: it is read again.
    store.reread();
    await answer("list", ok(LIST));
    await answer("detail", ok(redeployed("c".repeat(64))));
    expect(kinds().at(-1)).toBe("export");
    close();
    release();
  });

  it("test_store_a_new_machine_aborts_the_older_reads_and_drops_their_answers", async () => {
    const { store, calls, answer } = setup();
    store.open(LATCHED);
    const close = store.open(OTHER);
    expect(calls[0]?.signal.aborted).toBe(true);
    calls[0]?.answer(ok(DETAIL)); // late: dropped
    await settle();
    expect(store.getState().machine).toMatchObject({ ref: OTHER, phase: "idle", inFlight: true });
    await answer("detail", { kind: "not_found" });
    expect(store.getState().machine).toMatchObject({ ref: OTHER, phase: "not_found", chart: null });
    close();
  });

  it("test_store_a_view_that_closes_and_opens_in_one_commit_keeps_its_read", async () => {
    const { store, calls } = setup();
    const first = store.open(LATCHED);
    first();
    first(); // a second call changes nothing
    const again = store.open(LATCHED);
    await settle();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.signal.aborted).toBe(false);
    again();
    await settle();
    expect(calls[0]?.signal.aborted).toBe(true);
    expect(store.getState().machine).toMatchObject({ ref: null, phase: "idle" });
  });

  it("test_store_a_detail_without_a_served_machine_reads_no_chart", async () => {
    const { store, kinds, answer } = setup();
    const close = store.open(LATCHED);
    const sealed = vetDetail({
      snapshots: { status: "error", detail: "snapshot seal did not verify" },
    });
    await answer("detail", ok(sealed));
    expect(kinds()).toEqual(["detail"]);
    expect(store.getState().machine).toMatchObject({ phase: "ok", detail: sealed, chart: null });
    close();
  });

  it("test_store_a_machine_beside_a_snapshot_not_read_ok_reads_no_chart", async () => {
    const { store, kinds, answer } = setup();
    const close = store.open(LATCHED);
    const odd = vetDetail({ ...LATCHED_DETAIL, snapshots: { status: "error", detail: "x" } });
    await answer("detail", ok(odd));
    expect(kinds()).toEqual(["detail"]);
    expect(store.getState().machine.chart).toBeNull();
    close();
  });

  it("test_store_an_unusable_chart_says_why_and_its_retry_reads_it_again", async () => {
    const { store, kinds, answer } = setup();
    const close = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    await answer("export", { kind: "failed", reason: "timeout" });
    expect(store.getState().machine.chart).toMatchObject({ phase: "unusable", reason: "timeout" });
    store.retry("chart");
    await answer("export", { kind: "not_found" });
    expect(store.getState().machine.chart).toMatchObject({
      phase: "unusable",
      reason: "not_found",
    });
    store.reread(); // a Re-read reads an unusable chart again too
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    expect(store.getState().machine.chart).toMatchObject({ phase: "ok", chart: CHART });
    store.retry("chart"); // read: nothing to retry
    expect(kinds()).toEqual(["detail", "export", "export", "detail", "export"]);
    close();
  });

  it("test_store_a_reread_detail_that_moves_only_generated_at_keeps_what_it_shows", async () => {
    const { store, answer } = setup();
    const close = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    const first = store.getState().machine.detail;
    store.reread();
    const at = "2026-10-15T18:00:09Z";
    const moved = vetDetail({
      ...LATCHED_DETAIL,
      snapshots: { ...LATCHED_DETAIL.snapshots, generated_at: at },
      events: { ...LATCHED_DETAIL.events, generated_at: at },
    });
    await answer("detail", ok(moved));
    const next = store.getState().machine.detail;
    expect(next?.snapshots.generated_at).toBe(at);
    expect(next?.machine).toBe(first?.machine);
    expect(next?.configuration).toBe(first?.configuration);
    expect(next?.recent_events).toBe(first?.recent_events);
    close();
  });

  it("test_store_a_failed_detail_keeps_the_last_one_and_retries_on_request", async () => {
    const { store, kinds, answer } = setup();
    const close = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    store.retry("machine");
    await answer("detail", { kind: "failed", reason: "network" });
    expect(store.getState().machine).toMatchObject({
      phase: "failed",
      reason: "network",
      detail: DETAIL,
      chart: { phase: "ok" },
    });
    expect(kinds()).toEqual(["detail", "export", "detail"]);
    close();
  });
});

describe("the visit's end and a withdrawn area", () => {
  it("test_store_last_release_aborts_every_read_and_drops_every_answer", async () => {
    const { store, calls, kinds, answer } = setup();
    const release = store.hold();
    const close = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    await answer("export", ok(CHART));
    release();
    close();
    await settle();
    await settle();
    expect(calls.find((c) => c.kind === "list")?.signal.aborted).toBe(true);
    expect(store.getState().list).toEqual({ phase: "idle", inFlight: false, latchedOnly: false });
    expect(store.getState().machine).toEqual({
      ref: null,
      phase: "idle",
      inFlight: false,
      chart: null,
    });
    calls[0]?.answer(ok(LIST)); // a read that answers after it was stopped changes nothing
    await settle();
    expect(store.getState().list.phase).toBe("idle");
    // The next visit starts cold: its list and its chart are read again.
    const again = store.hold();
    const reopen = store.open(LATCHED);
    await answer("detail", ok(DETAIL));
    expect(kinds()).toEqual(["list", "detail", "export", "list", "detail", "export"]);
    reopen();
    again();
  });

  it("test_store_a_release_and_hold_in_one_commit_keep_the_visit", async () => {
    const { store, calls } = setup();
    const release = store.hold();
    release();
    release(); // a second call changes nothing
    const again = store.hold();
    await settle();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.signal.aborted).toBe(false);
    again();
  });

  it.each(["list", "detail", "export"] as const)(
    "test_store_a_403_on_the_%s_read_denies_once_and_asks_nothing_more",
    async (kind) => {
      const { store, calls, denials, kinds, answer } = setup();
      const release = store.hold();
      const close = store.open(LATCHED);
      if (kind === "export") await answer("detail", ok(DETAIL));
      await answer(kind, { kind: "denied", refId: "urn:cv:req:7" });
      expect(denials).toEqual(["urn:cv:req:7"]);
      // Every read still in flight is aborted: the denied one and an answered detail are done.
      const pending = calls.filter(
        (c) => c.kind !== kind && !(kind === "export" && c.kind === "detail"),
      );
      expect(pending.length > 0 && pending.every((c) => c.signal.aborted)).toBe(true);
      expect(store.getState()).toEqual({
        list: { phase: "idle", inFlight: false, latchedOnly: false },
        machine: { ref: null, phase: "idle", inFlight: false, chart: null },
        denied: { refId: "urn:cv:req:7" },
      });
      const asked = kinds().length;
      store.reread();
      store.retry("list");
      store.retry("machine");
      store.retry("chart");
      store.setLatchedOnly(true);
      store.open(OTHER)();
      store.hold()();
      await settle();
      expect(kinds()).toHaveLength(asked);
      close();
      release();
      await settle();
      expect(store.getState().denied).toEqual({ refId: "urn:cv:req:7" });
      expect(denials).toHaveLength(1);
    },
  );

  it("test_store_notifies_listeners_and_resets_for_tests", async () => {
    const { store, answer } = setup();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    const release = store.hold();
    await answer("list", { kind: "failed", reason: "network" });
    expect(listener).toHaveBeenCalled();
    unsubscribe();
    listener.mockClear();
    store.reset();
    expect(listener).not.toHaveBeenCalled();
    expect(store.getState().list.phase).toBe("idle");
    release();
  });
});

/** A page that holds the store and a view that opens a machine, as the inspector mounts them. */
function Page({ store, open }: { readonly store: InspectorStore; readonly open: boolean }) {
  useInspectorHold(store);
  const phase = useInspectorSelector((s) => s.list.phase, store);
  return (
    <p>
      {phase}
      {open ? <View store={store} /> : null}
    </p>
  );
}
function View({ store }: { readonly store: InspectorStore }) {
  useOpenMachine(LATCHED, store);
  const machine = useInspectorSelector((s) => s.machine.phase, store);
  return <span>{` ${machine}`}</span>;
}

describe("the hooks: held while mounted", () => {
  it("test_store_hooks_hold_while_mounted_and_release_on_unmount", async () => {
    const { store, calls, answer } = setup();
    const view = render(<Page store={store} open />);
    expect(calls.map((c) => c.kind).sort()).toEqual(["detail", "list"]);
    await act(async () => {
      await answer("list", ok(LIST));
      await answer("detail", { kind: "not_found" });
    });
    expect(view.container.textContent).toBe("ok not_found");
    view.rerender(<Page store={store} open={false} />);
    await act(settle);
    expect(store.getState().machine.ref).toBeNull();
    view.unmount();
    await act(settle);
    expect(store.getState().list.phase).toBe("idle");
  });
});
