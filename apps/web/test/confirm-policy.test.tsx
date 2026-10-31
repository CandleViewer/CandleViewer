import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  CONFIRM_ACTIONS,
  MODE_STRENGTH,
  clampHoldMs,
  createConfirmPolicyStore,
  resolveConfirm,
  useConfirmPolicy,
} from "../src/features/confirm-policy";
import type {
  ActionPolicy,
  ConfirmAction,
  Resolution,
  UserPolicy,
} from "../src/features/confirm-policy";
import { HOLD_DEFAULT_MS, HOLD_MAX_MS, HOLD_MIN_MS } from "../src/features/confirm-policy/resolve";
import { confirmPolicyStorageKey, parsePolicy } from "../src/features/confirm-policy/store";

const HOLDS: readonly (number | undefined)[] = [
  undefined,
  -5,
  0,
  100,
  300,
  800,
  2000,
  9999,
  Number.NaN,
  Number.POSITIVE_INFINITY,
];
const entries = [
  undefined,
  ...(["dialog", "hold", "immediate", "skip"] as const).flatMap((mode) =>
    HOLDS.map((holdMs) => ({ mode, holdMs })),
  ),
];
const entryFor = (e: (typeof entries)[number]): unknown =>
  e === undefined ? undefined : e.holdMs === undefined ? { mode: e.mode } : e;
/** Uniform policies, plus mixed ones where each action gets a different entry (rotated). */
const policies: UserPolicy[] = [
  ...entries.map((e) => Object.fromEntries(CONFIRM_ACTIONS.map((a) => [a, entryFor(e)]))),
  ...entries.map((_, shift) =>
    Object.fromEntries(
      CONFIRM_ACTIONS.map((a, i) => [a, entryFor(entries[(shift + i * 7) % entries.length])]),
    ),
  ),
] as UserPolicy[];
const ENVS = ["live", "demo", "testnet", "unknown"] as const;
const R = (mode: Resolution["mode"], holdMs: number, typed: boolean): Resolution => ({
  mode,
  holdMs,
  typed,
});
const hold = (mode: "hold", holdMs?: number): ActionPolicy =>
  holdMs === undefined ? { mode } : { mode, holdMs };

describe("resolveConfirm: the per-(action, env) floors", () => {
  // flatten Demo: free, dialog default (E30-D03 §7 :308; US-SET-003 :5101).
  it("flatten / demo: dialog by default, a hold is selectable (E30-D03 §7 :308)", () => {
    expect(resolveConfirm("flatten", "demo", {})).toEqual(R("dialog", 0, false));
    expect(resolveConfirm("flatten", "demo", { flatten: hold("hold", 1200) })).toEqual(
      R("hold", 1200, false),
    );
  });
  // flatten Live: hold >= 800 ms plus typed (14 SCR-010 :300).
  it("flatten / live: hold 800 ms plus typed, never shorter, typed even on a dialog (14 SCR-010 :300)", () => {
    expect(resolveConfirm("flatten", "live", {})).toEqual(R("dialog", 0, true));
    expect(resolveConfirm("flatten", "live", { flatten: hold("hold") })).toEqual(
      R("hold", 800, true),
    );
    expect(resolveConfirm("flatten", "live", { flatten: hold("hold", 400) })).toEqual(
      R("hold", 800, true),
    );
    expect(resolveConfirm("flatten", "live", { flatten: hold("hold", 1500) })).toEqual(
      R("hold", 1500, true),
    );
  });
  it("cancel-all / demo: dialog by default, hold 300-2,000 selectable (E30-D03 §7 :308)", () => {
    expect(resolveConfirm("cancel-all", "demo", {})).toEqual(R("dialog", 0, false));
    expect(resolveConfirm("cancel-all", "demo", { "cancel-all": hold("hold", 100) })).toEqual(
      R("hold", 300, false),
    );
  });
  it("cancel-all / live: never below hold, no typed word (SC-3; F19 (b); E30-D03 §7 :308)", () => {
    expect(resolveConfirm("cancel-all", "live", {})).toEqual(R("dialog", 0, false));
    expect(resolveConfirm("cancel-all", "live", { "cancel-all": hold("hold", 500) })).toEqual(
      R("hold", 500, false),
    );
  });
  it.each(["demo", "live"] as const)(
    "reverse / %s: dialog only; hold and immediate are T2 (F19; E30-D03 §7 :308; US-ORD-011 :3113)",
    (env) => {
      for (const mode of ["hold", "immediate", "dialog"] as const)
        expect(resolveConfirm("reverse", env, { reverse: { mode, holdMs: 500 } })).toEqual(
          R("dialog", 0, false),
        );
    },
  );
  it.each(["demo", "live"] as const)(
    "freeze / %s: dialog only, no typed word, no hold (14 SCR-072 alertdialog; E30-D03 §7 :308)",
    (env) => {
      for (const mode of ["hold", "immediate", "dialog"] as const)
        expect(resolveConfirm("freeze", env, { freeze: { mode } })).toEqual(R("dialog", 0, false));
    },
  );
});

describe("resolveConfirm: invariants over actions x envs x uniform and mixed policies", () => {
  const all = function* (): Generator<[ConfirmAction, UserPolicy]> {
    for (const a of CONFIRM_ACTIONS) for (const p of policies) yield [a, p];
  };
  it("covers more than the uniform entries (mixed per-action policies and an unknown mode)", () => {
    expect(policies.length).toBe(entries.length * 2);
    expect(entries.some((e) => e?.mode === "skip")).toBe(true);
  });

  it("Live is never weaker than Demo: mode, typed word, and hold length", () => {
    for (const [a, p] of all())
      for (const server of [{}, { confirmFlatten: true }]) {
        const live = resolveConfirm(a, "live", p, server);
        const demo = resolveConfirm(a, "demo", p, server);
        expect(MODE_STRENGTH[live.mode]).toBeGreaterThanOrEqual(MODE_STRENGTH[demo.mode]);
        expect(live.typed || !demo.typed).toBe(true);
        if (live.mode === "hold" && demo.mode === "hold")
          expect(live.holdMs).toBeGreaterThanOrEqual(demo.holdMs);
      }
  });

  it("never resolves immediate (BQ-2), and holdMs is 300-2,000 for hold, 0 otherwise", () => {
    for (const [a, p] of all())
      for (const env of ENVS) {
        const r = resolveConfirm(a, env, p);
        expect(r.mode).not.toBe("immediate");
        if (r.mode === "hold") {
          expect(r.holdMs).toBeGreaterThanOrEqual(300);
          expect(r.holdMs).toBeLessThanOrEqual(2000);
        } else expect(r.holdMs).toBe(0);
      }
  });

  it("only demo gets Demo rules: live, testnet and unknown resolve identically", () => {
    for (const [a, p] of all()) {
      const live = resolveConfirm(a, "live", p);
      expect(resolveConfirm(a, "testnet", p)).toEqual(live);
      expect(resolveConfirm(a, "unknown", p)).toEqual(live);
    }
    const weak = { flatten: hold("hold", 300) };
    expect(resolveConfirm("flatten", "testnet", weak).typed).toBe(true);
    expect(resolveConfirm("flatten", "unknown", weak).holdMs).toBe(800);
  });

  it("the default is a dialog everywhere; the Demo-weaker precondition is set explicitly", () => {
    for (const a of CONFIRM_ACTIONS)
      for (const env of ENVS) expect(resolveConfirm(a, env, {}).mode).toBe("dialog");
    const demoWeaker: UserPolicy = { flatten: hold("hold", 300) };
    expect(resolveConfirm("flatten", "demo", demoWeaker)).toEqual(R("hold", 300, false));
    expect(resolveConfirm("flatten", "live", demoWeaker)).toEqual(R("hold", 800, true));
  });

  it("a server floor (confirm_flatten = true) lifts flatten to a dialog in both envs, only flatten", () => {
    const p: UserPolicy = { flatten: hold("hold"), "cancel-all": hold("hold") };
    const server = { confirmFlatten: true };
    expect(resolveConfirm("flatten", "demo", p, server)).toEqual(R("dialog", 0, false));
    expect(resolveConfirm("flatten", "live", p, server)).toEqual(R("dialog", 0, true));
    expect(resolveConfirm("cancel-all", "demo", p, server).mode).toBe("hold");
    expect(resolveConfirm("flatten", "demo", p, { confirmFlatten: false }).mode).toBe("hold");
  });

  it("fails closed on an unknown mode and on a prototype-named policy key", () => {
    const bad = { flatten: { mode: "skip" } } as unknown as UserPolicy;
    expect(resolveConfirm("flatten", "demo", bad).mode).toBe("dialog");
    const proto = JSON.parse('{"__proto__":{"mode":"hold"}}') as UserPolicy;
    expect(resolveConfirm("flatten", "demo", proto).mode).toBe("dialog");
  });

  it("takes no accessibility input: extra fields on the policy change nothing", () => {
    const base: UserPolicy = { flatten: hold("hold") };
    const a11y = { ...base, reduceMotion: true, highContrast: true } as UserPolicy;
    for (const env of ENVS)
      expect(resolveConfirm("flatten", env, a11y)).toEqual(resolveConfirm("flatten", env, base));
  });
});

describe("hold bounds", () => {
  it("clamps like CMP-044 and pins the packages/ui constants", () => {
    expect([100, 300, 5000, Number.NaN, undefined].map(clampHoldMs)).toEqual([
      300, 300, 2000, 800, 800,
    ]);
    // The ui constants are not exported (no deep import): read their source and compare.
    const src = readFileSync(
      resolve(import.meta.dirname, "../../../packages/ui/src/components/internal/holdGate.ts"),
      "utf8",
    );
    const read = (name: string): number =>
      Number(new RegExp(`export const ${name} = (\\d+);`).exec(src)?.[1]);
    expect([read("HOLD_MIN_MS"), read("HOLD_DEFAULT_MS"), read("HOLD_MAX_MS")]).toEqual([
      HOLD_MIN_MS,
      HOLD_DEFAULT_MS,
      HOLD_MAX_MS,
    ]);
    expect([HOLD_MIN_MS, HOLD_DEFAULT_MS, HOLD_MAX_MS]).toEqual([300, 800, 2000]);
  });
});

describe("policy store and useConfirmPolicy", () => {
  const memory = (): Pick<Storage, "getItem" | "setItem"> & { data: Map<string, string> } => {
    const data = new Map<string, string>();
    return {
      data,
      getItem: (k) => data.get(k) ?? null,
      setItem: (k, v) => void data.set(k, v),
    };
  };

  it("persists per user, reloads and validates stored policy", () => {
    const storage = memory();
    createConfirmPolicyStore(storage, "u1").set("flatten", { mode: "hold", holdMs: 1000 });
    expect([...storage.data.keys()]).toEqual(["cv.confirmPolicy.v1.u1"]);
    expect(createConfirmPolicyStore(storage, "u1").get()).toEqual({
      flatten: { mode: "hold", holdMs: 1000 },
    });
    // Another user never sees it.
    expect(createConfirmPolicyStore(storage, "u2").get()).toEqual({});
    expect(
      parsePolicy({ flatten: { mode: "nope" }, other: { mode: "hold" }, "cancel-all": 3 }),
    ).toEqual({});
    expect(parsePolicy("x")).toEqual({});
    const broken = memory();
    broken.data.set(confirmPolicyStorageKey("u1"), "{not json");
    expect(createConfirmPolicyStore(broken, "u1").get()).toEqual({});
  });

  it("refuses immediate at persistence: a stored one is dropped, set() ignores it", () => {
    const storage = memory();
    storage.data.set(
      confirmPolicyStorageKey("u1"),
      JSON.stringify({ flatten: { mode: "immediate" }, "cancel-all": { mode: "hold" } }),
    );
    const store = createConfirmPolicyStore(storage, "u1");
    expect(store.get()).toEqual({ "cancel-all": { mode: "hold" } });
    store.set("flatten", { mode: "immediate" });
    expect(JSON.stringify(store.get())).not.toContain("immediate");
    store.set("freeze", { mode: "dialog" });
    expect(JSON.stringify([...storage.data.values()])).not.toContain("immediate");
  });

  it("the hook follows the store, takes env and server floor, and unsubscribes on unmount", () => {
    const store = createConfirmPolicyStore(undefined, "u1");
    const { result, rerender, unmount } = renderHook(
      ({ env, floor }: { env: "live" | "demo"; floor: boolean }) =>
        useConfirmPolicy("flatten", env, "u1", { store, serverFloor: { confirmFlatten: floor } }),
      { initialProps: { env: "demo" as "live" | "demo", floor: false } },
    );
    expect(result.current).toEqual(R("dialog", 0, false));
    act(() => store.set("flatten", { mode: "hold", holdMs: 500 }));
    expect(result.current).toEqual(R("hold", 500, false));
    rerender({ env: "live", floor: false });
    expect(result.current).toEqual(R("hold", 800, true));
    rerender({ env: "demo", floor: true });
    expect(result.current.mode).toBe("dialog");
    unmount();
    let calls = 0;
    const off = store.subscribe(() => (calls += 1));
    store.set("flatten", { mode: "dialog" });
    off();
    store.set("flatten", { mode: "hold" });
    expect(calls).toBe(1);
  });
});
