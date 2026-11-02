/**
 * The amend engine's store (E29-S02 #912, PR3a): the ticket's `pendingMutations`, one entry per
 * order id, additive to the orders store's rows and never written into them, so a cell keeps the
 * confirmed value until the venue answers (D-10). A `useSyncExternalStore` store, the orders
 * store's pattern, run by `model/amend.ts`'s reducers; the positions session holds it (P3-BQ-8),
 * so an answer that lands while another tab shows is never lost.
 *
 * - **press** judges the row the orders store holds at the commit (`current`, N1), never the
 *   caller's object, and runs the commit's last guards: a native stop is never amended (D-13, D01
 *   D7's rule from WS fields alone); a recorded take-profit, and any provenance but `placed`, is
 *   refused before any request when the row's provenance is known, the server enforcing it always;
 *   a reduce-only take-profit whose provenance no read has given is refused too (fail closed); an
 *   order that does not rest takes none, one amend per order at a time, the request as typed, and
 *   the arm read again at the commit (M13): a live risk-increasing amend without a token is not
 *   sent (P3-BQ-5). It then records the entry and sends `amendOrder` once, the token only where
 *   `needsArm` says; the answer settles that press alone (`seq`).
 * - **observe** takes each frame item the orders store accepted, after its late-frame drop, in
 *   arrival order; **expire** runs the stale bound; **prune** drops an entry whose order left the
 *   view; **dismiss** clears a rejected, not-applied or not-sent line, and a new press clears one
 *   silently.
 * - **The sinks** (injected): `announce` says a resolution once (`said`; E29-D05 RT-14 polite,
 *   RT-06 assertive), after the step is stored, so an announcer that throws costs no step (its
 *   error is reported, N2); `performance` takes `pending_mutation_age_seconds` (G-W2) once, when an
 *   entry leaves Amending, as a local `performance.measure`, bounded as the feed's measures are.
 */
import { useSyncExternalStore } from "react";
import type { Politeness } from "../../app-shell/announcer";
import type { PerformanceLike } from "../wsPositions";
import { ordersWrites, type AmendOutcome, type AmendWrites } from "./api";
import {
  announcementOf,
  armToken,
  needsArm,
  NO_ARM,
  onAnswer,
  onItem,
  onTick,
  provenanceBar,
  requestFault,
  valueOf,
  type AmendField,
  type AmendStep,
  type ArmTokenSource,
  type FrameVia,
  type PendingMutation,
  type RequestFault,
} from "./model/amend";
import { orderIdOf, type Figure, type OrderRowModel } from "./model/orderRow";
import { raiseApart } from "./ordersStore";
import { figure as gridFigure } from "./view";

/** G-W2's client metric, a local measure in ms, as the feed's `ws_frame_apply_seconds` is. */
export const AMEND_AGE_MEASURE = "pending_mutation_age_seconds";
/** At most this many age measures stay in the page's timeline (C-2.18); past it they are cleared. */
export const MAX_AGE_MEASURES = 1_000;

export interface AmendsSnapshot {
  /** By order id: every amend still pending, unconfirmed, or awaiting its Dismiss. */
  readonly mutations: ReadonlyMap<string, PendingMutation>;
  readonly version: number;
}

export type PressRefusal =
  "protected" | "not_amendable" | "provenance_unread" | "in_flight" | "arm" | RequestFault;

export type PressResult =
  | { readonly kind: "sent"; readonly seq: number }
  | { readonly kind: "refused"; readonly why: PressRefusal };

export interface AmendStoreOptions {
  readonly writes?: AmendWrites | undefined;
  /** The session's arm token; none by default, so a live risk-increasing amend fails closed. */
  readonly arm?: ArmTokenSource | undefined;
  readonly announce?: ((politeness: Politeness, text: string) => void) | undefined;
  /** Where an announcer's error goes (N2); `raiseApart` by default. */
  readonly report?: ((error: unknown) => void) | undefined;
  /** `null` turns the measure off; defaults to `globalThis.performance`. */
  readonly performance?: PerformanceLike | null | undefined;
  /** Monotonic ms, the feed's clock (the stale bound runs on it); defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  /** How an announcement writes a figure; defaults to the grid's (`view.ts`). */
  readonly figure?: Figure | undefined;
  /**
   * The orders store's current row for an order id (N1): a press judges, records and sends that
   * row, never the caller's object, and sends nothing once the store no longer shows the order.
   * The positions session passes it; a store made without it judges the row it is given.
   */
  readonly current?: ((orderId: string) => OrderRowModel | undefined) | undefined;
}

export interface AmendStore {
  getSnapshot(): AmendsSnapshot;
  subscribe(listener: () => void): () => void;
  /** A commit: judged on `current(row.id)` where the store has `current` (N1), else on `row`. */
  press(row: OrderRowModel, field: AmendField, requested: string): PressResult;
  /** The HTTP answer of press `seq` (a later press's entry is never settled by it). */
  settle(orderId: string, seq: number, outcome: AmendOutcome): void;
  /** One frame item the orders store accepted, in arrival order. */
  observe(item: unknown, via: FrameVia): void;
  /** The stale bound (`AMEND_STALE_MS`): the feed calls it each frame. */
  expire(nowMs: number): void;
  /** Drops the entries of orders no longer in the view. */
  prune(liveIds: ReadonlySet<string>): void;
  dismiss(orderId: string): void;
}

const EMPTY: AmendsSnapshot = Object.freeze({ mutations: new Map(), version: 0 });

export function createAmendStore(options: AmendStoreOptions = {}): AmendStore {
  const writes = options.writes ?? ordersWrites;
  const arm = options.arm ?? NO_ARM;
  const announce = options.announce ?? ((): void => undefined);
  const report = options.report ?? raiseApart;
  const perf = options.performance === undefined ? globalThis.performance : options.performance;
  const now = options.now ?? ((): number => performance.now());
  const figure = options.figure ?? gridFigure;
  const current = options.current;
  const listeners = new Set<() => void>();
  const mutations = new Map<string, PendingMutation>();
  let snapshot = EMPTY;
  let seq = 0;
  let measures = 0;

  function publish(): void {
    snapshot = Object.freeze({ mutations: new Map(mutations), version: snapshot.version + 1 });
    for (const listener of [...listeners]) listener();
  }

  function measure(m: PendingMutation, outcome: string, at: number): void {
    if (perf === null || perf === undefined) return;
    try {
      perf.measure(AMEND_AGE_MEASURE, { start: m.sentAt, end: at, detail: { outcome } });
      measures += 1;
      if (measures >= MAX_AGE_MEASURES) {
        perf.clearMeasures?.(AMEND_AGE_MEASURE);
        measures = 0;
      }
    } catch {
      // a measure must never harm the amend (`lib/telemetry`'s rule)
    }
  }

  /**
   * One reducer step on `m`'s entry: kept or dropped, measured once, each resolution said once. The
   * step is stored and published first, then said (N2): an announcer that throws never costs it.
   */
  function apply(m: PendingMutation, step: AmendStep, at: number): void {
    const { resolution } = step;
    if (resolution === null && step.next === m) return;
    const said = resolution === null ? null : announcementOf(m, resolution, figure);
    const saying = said !== null && m.said !== resolution;
    const next = saying && step.next !== null ? { ...step.next, said: resolution } : step.next;
    // it leaves Amending, once
    if (resolution !== null && m.phase === "pending") measure(m, resolution, at);
    if (next === null) mutations.delete(m.orderId);
    else mutations.set(m.orderId, next);
    publish();
    if (!saying) return;
    try {
      announce(said.politeness, said.text);
    } catch (error) {
      report(error);
    }
  }

  const refused = (why: PressRefusal): PressResult => ({ kind: "refused", why });

  const store: AmendStore = {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    press(given, field, requested) {
      // N1: the row as the orders store holds it at the commit, never the caller's object
      const row = current === undefined ? given : current(given.id);
      if (row === undefined) return refused("not_amendable");
      if (row.protective.kind !== null) return refused("protected");
      // `22` takes an amend only while the order rests (`422 order_not_amendable`): none is sent
      if (row.state.lifecycle !== "submitted" && row.state.lifecycle !== "partially_filled")
        return refused("not_amendable");
      // `exits.py` refuses any provenance but `placed`; an unread one may be a recorded take-profit
      const bar = provenanceBar(row);
      if (bar !== null) return refused(bar === "unread" ? "provenance_unread" : "not_amendable");
      const held = mutations.get(row.id);
      if (held !== undefined && (held.phase === "pending" || held.phase === "unconfirmed"))
        return refused("in_flight");
      const fault = requestFault(row, field, requested);
      if (fault !== null) return refused(fault);
      const prior = valueOf(row, field);
      if (prior === null) return refused("absent");
      // the commit's own read of the arm (M13): never one kept from a render
      const armed = needsArm(row, field, requested);
      const token = armed ? armToken(arm, row.accountId) : null;
      if (armed && token === null) return refused("arm");
      seq += 1;
      const mine = seq;
      mutations.set(row.id, {
        orderId: row.id,
        seq: mine,
        field,
        requested,
        prior,
        sentAt: now(),
        phase: "pending",
        sawPending: false,
        http: "none",
        httpAt: null,
        said: null,
        held: null,
        refusal: null,
      });
      publish();
      void writes.amendOrder(row, field, requested, { arm: token }).then(
        (outcome) => store.settle(row.id, mine, outcome),
        () => store.settle(row.id, mine, { kind: "unavailable" }),
      );
      return { kind: "sent", seq: mine };
    },
    settle(orderId, pressed, outcome) {
      const m = mutations.get(orderId);
      if (m === undefined || m.seq !== pressed) return;
      const at = now();
      apply(m, onAnswer(m, outcome, at), at);
    },
    observe(item, via) {
      const id = orderIdOf(item);
      const m = id === null ? undefined : mutations.get(id);
      if (m === undefined) return;
      apply(m, onItem(m, item, via), now());
    },
    expire(nowMs) {
      for (const m of [...mutations.values()]) {
        if (m.phase === "pending") apply(m, onTick(m, nowMs), nowMs);
      }
    },
    prune(liveIds) {
      for (const m of [...mutations.values()]) {
        if (!liveIds.has(m.orderId)) apply(m, { next: null, resolution: "dropped" }, now());
      }
    },
    dismiss(orderId) {
      const m = mutations.get(orderId);
      if (m === undefined || m.phase === "pending" || m.phase === "unconfirmed") return;
      mutations.delete(orderId);
      publish();
    },
  };
  return store;
}

/** One selected value of the store; re-renders when the selection changes (by `Object.is`). */
export function useAmends<T>(store: AmendStore, select: (s: AmendsSnapshot) => T): T {
  const read = (): T => select(store.getSnapshot());
  return useSyncExternalStore(store.subscribe, read, read);
}
