/**
 * Alerts by id (E40-S01). A module-free factory in the shell store's `useSyncExternalStore`
 * pub/sub pattern (no new state dependency, `AGENTS.md` 5.1): the screen reads through
 * `useAlerts`, tests and the WS bridge use the store object directly. The REST list is the source
 * of records; WS deliveries only advance fire facts on records already known. State is replaced,
 * never mutated, so snapshots are stable between writes.
 */
import { useSyncExternalStore } from "react";
import type { Alert } from "./types.js";

export interface AlertsState {
  readonly byId: ReadonlyMap<string, Alert>;
  /** Unacked delivery count last reported by the `alerts` topic; null until one arrives. */
  readonly unackedCount: number | null;
}

export interface FireFact {
  readonly alertId: string;
  readonly firedAtMs: number;
  /** Firings folded into this fact (coalesced frames); at least 1. */
  readonly count: number;
}

export interface AlertsStore {
  readonly getState: () => AlertsState;
  readonly subscribe: (listener: () => void) => () => void;
  /** Replaces the whole set (a fresh REST list). Records without an id are dropped. */
  readonly replaceAll: (alerts: readonly Alert[]) => void;
  readonly upsert: (alert: Alert) => void;
  readonly remove: (id: string) => void;
  /** Advances `last_fired_at` (never backwards) and `fire_count`. Unknown ids are ignored. */
  readonly recordFires: (facts: readonly FireFact[]) => void;
  readonly setUnackedCount: (count: number) => void;
  /** The alerts in insertion order; the same array until the set changes. */
  readonly list: () => readonly Alert[];
}

export function createAlertsStore(): AlertsStore {
  let state: AlertsState = { byId: new Map(), unackedCount: null };
  const listeners = new Set<() => void>();
  let cachedFor: ReadonlyMap<string, Alert> | undefined;
  let cachedList: readonly Alert[] = [];

  const commit = (next: AlertsState): void => {
    state = next;
    for (const listener of [...listeners]) listener();
  };

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    replaceAll: (alerts) => {
      const byId = new Map<string, Alert>();
      for (const alert of alerts) if (alert.id !== undefined) byId.set(alert.id, alert);
      commit({ ...state, byId });
    },
    upsert: (alert) => {
      if (alert.id === undefined) return;
      const byId = new Map(state.byId);
      byId.set(alert.id, alert);
      commit({ ...state, byId });
    },
    remove: (id) => {
      if (!state.byId.has(id)) return;
      const byId = new Map(state.byId);
      byId.delete(id);
      commit({ ...state, byId });
    },
    recordFires: (facts) => {
      let byId: Map<string, Alert> | undefined;
      for (const fact of facts) {
        const current = (byId ?? state.byId).get(fact.alertId);
        if (current === undefined || !Number.isFinite(fact.firedAtMs)) continue;
        const previous =
          current.last_fired_at === null || current.last_fired_at === undefined
            ? Number.NEGATIVE_INFINITY
            : Date.parse(current.last_fired_at);
        const newest = Math.max(
          Number.isNaN(previous) ? Number.NEGATIVE_INFINITY : previous,
          fact.firedAtMs,
        );
        byId ??= new Map(state.byId);
        byId.set(fact.alertId, {
          ...current,
          last_fired_at: new Date(newest).toISOString(),
          fire_count: (current.fire_count ?? 0) + Math.max(1, Math.floor(fact.count)),
        });
      }
      if (byId !== undefined) commit({ ...state, byId });
    },
    setUnackedCount: (count) => {
      if (state.unackedCount === count) return;
      commit({ ...state, unackedCount: count });
    },
    list: () => {
      if (cachedFor !== state.byId) {
        cachedFor = state.byId;
        cachedList = [...state.byId.values()];
      }
      return cachedList;
    },
  };
}

/** The screen's shared store. */
export const alertsStore: AlertsStore = createAlertsStore();

export function useAlerts(store: AlertsStore = alertsStore): readonly Alert[] {
  return useSyncExternalStore(store.subscribe, store.list, store.list);
}
