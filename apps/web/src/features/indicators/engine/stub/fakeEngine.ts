// STUB(#425): replace with the real adapter when E13-T01 PR-1 (host and registry) merges; the
// deletion trigger is a line in the PR body and the re-pin checklist (BQ-01 AMEND), not a test.
// E13-S01 (#423) S2: the in-memory `IndicatorEnginePort` the store and its tests run against. It
// keeps what an engine would show (instances per pane, in order) and a log of every call, models
// the server's refusals (`23:779`: at most 8 `server` instances, never two with one key; a lower
// `capacity` stands for "at capacity"), and throws on a call no engine could honour.
import { paramsSignature } from "../../model/params";
import type { Params } from "../../model/types";
import type { EngineAddSpec, EngineKey, IndicatorEnginePort, PortOutcome } from "../port";

/** The `instances` bound of one `indicators` subscription (`23:779`). */
export const SERVER_INSTANCES = 8;

export type FakeCall =
  | { readonly op: "add"; readonly spec: EngineAddSpec; readonly outcome: PortOutcome }
  | {
      readonly op: "setParams";
      readonly key: EngineKey;
      readonly params: Params;
      readonly outcome: PortOutcome;
    }
  | { readonly op: "remove"; readonly key: EngineKey }
  | { readonly op: "setOrder"; readonly pane: string; readonly keys: readonly EngineKey[] };

export interface FakeInstance {
  readonly spec: EngineAddSpec;
}

export interface FakeEngine extends IndicatorEnginePort {
  readonly calls: readonly FakeCall[];
  readonly live: ReadonlyMap<EngineKey, FakeInstance>;
  /** Every key the fake served for a `server` instance, in order (the stand-in `sub_ok` echo). */
  readonly served: readonly EngineKey[];
  /** The pane's keys in render order. */
  order(pane: string): readonly EngineKey[];
  /** How many `server` instances the server accepts now (default 8). */
  capacity: number;
  /** One computed value reaching the engine (BQ-07: it never reaches the store). */
  feed(key: EngineKey, value: number | null): void;
  readonly values: ReadonlyMap<EngineKey, number | null>;
}

/**
 * Stand-in for T01's PROPOSED client key (#425 BQ-8: a hash of the indicator, the canonical params
 * and the source series): a pure function of the three. Never a `server` key.
 */
export const fakeClientKey = (indicator: string, params: Params, series: string): EngineKey =>
  `client:${series}:${paramsSignature(indicator, params)}` as EngineKey;

export function createFakeEngine(options: { readonly series?: string } = {}): FakeEngine {
  const series = options.series ?? "series-1";
  const calls: FakeCall[] = [];
  const live = new Map<EngineKey, FakeInstance>();
  const panes = new Map<string, EngineKey[]>();
  const served: EngineKey[] = [];
  const values = new Map<EngineKey, number | null>();
  const known = (key: EngineKey): FakeInstance => {
    const found = live.get(key);
    if (found === undefined) throw new Error(`fake engine: unknown instance ${key}`);
    return found;
  };
  const unplace = (key: EngineKey, pane: string): void => {
    live.delete(key);
    const rest = (panes.get(pane) ?? []).filter((k) => k !== key);
    if (rest.length === 0) panes.delete(pane);
    else panes.set(pane, rest);
  };
  /** The server's answer for a `server` spec, `except` the instance being re-tuned. */
  const serve = (spec: EngineAddSpec, except: EngineKey | null): PortOutcome => {
    const others = [...live].filter(([k, i]) => k !== except && i.spec.compute === "server");
    const signature = paramsSignature(spec.indicator, spec.params);
    const dup = others.some(
      ([, i]) => paramsSignature(i.spec.indicator, i.spec.params) === signature,
    );
    if (dup || others.length >= SERVER_INSTANCES) return { ok: false, refusal: "invalid_options" };
    if (others.length >= engine.capacity) return { ok: false, refusal: "subscription_limit" };
    const key = `served:${served.length + 1}` as EngineKey;
    served.push(key);
    return { ok: true, key };
  };
  const keyFor = (spec: EngineAddSpec, except: EngineKey | null): PortOutcome => {
    if (spec.compute === "server") return serve(spec, except);
    const key = fakeClientKey(spec.indicator, spec.params, series);
    if (key !== except && live.has(key)) throw new Error(`fake engine: duplicate key ${key}`);
    return { ok: true, key };
  };
  const engine: FakeEngine = {
    calls,
    live,
    served,
    values,
    capacity: SERVER_INSTANCES,
    order: (pane) => panes.get(pane) ?? [],
    add(spec) {
      const outcome = keyFor(spec, null);
      calls.push({ op: "add", spec, outcome });
      if (outcome.ok) {
        live.set(outcome.key, { spec });
        panes.set(spec.pane, [...(panes.get(spec.pane) ?? []), outcome.key]);
      }
      return outcome;
    },
    setParams(key, params) {
      const found = known(key);
      const spec = { ...found.spec, params };
      const outcome = keyFor(spec, key);
      calls.push({ op: "setParams", key, params, outcome });
      if (outcome.ok) {
        live.delete(key);
        live.set(outcome.key, { spec });
        panes.set(
          spec.pane,
          (panes.get(spec.pane) ?? []).map((k) => (k === key ? outcome.key : k)),
        );
      }
      return outcome;
    },
    remove(key) {
      const found = known(key);
      calls.push({ op: "remove", key });
      unplace(key, found.spec.pane);
    },
    setOrder(pane, keys) {
      const current = panes.get(pane) ?? [];
      const same = keys.length === current.length && keys.every((k) => current.includes(k));
      if (!same) throw new Error(`fake engine: order for ${pane} names other instances`);
      calls.push({ op: "setOrder", pane, keys });
      panes.set(pane, [...keys]);
    },
    feed(key, value) {
      known(key);
      values.set(key, value);
    },
  };
  return engine;
}
