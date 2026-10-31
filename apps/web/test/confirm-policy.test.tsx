import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  CONFIRM_ACTIONS,
  MODE_STRENGTH,
  clampHoldMs,
  createConfirmPolicyStore,
  resolveConfirm,
  useConfirmPolicy,
} from "../src/features/confirm-policy";
import type { ConfirmMode, Resolution, UserPolicy } from "../src/features/confirm-policy";
import { parsePolicy } from "../src/features/confirm-policy/store";

const MODES: readonly ConfirmMode[] = ["dialog", "hold", "immediate"];
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

/** Every policy shape: unset, and each mode x hold length, for one action. */
const entries = [
  undefined,
  ...MODES.flatMap((mode) => HOLDS.map((holdMs) => ({ mode, holdMs }))),
] as const;
const policies: UserPolicy[] = entries.map((entry) =>
  entry === undefined
    ? {}
    : Object.fromEntries(
        CONFIRM_ACTIONS.map((a) => [a, entry.holdMs === undefined ? { mode: entry.mode } : entry]),
      ),
);

/** Strength with the hold length as the tie-break inside `hold`. */
const rank = (r: Resolution): number => MODE_STRENGTH[r.mode] * 10_000 + r.holdMs;

describe("resolveConfirm", () => {
  it("never lets Live be weaker than Demo, over every action x policy", () => {
    for (const action of CONFIRM_ACTIONS)
      for (const policy of policies)
        expect(rank(resolveConfirm(action, "live", policy))).toBeGreaterThanOrEqual(
          rank(resolveConfirm(action, "demo", policy)),
        );
  });

  it("never selects immediate (BQ-2): it fails closed to a dialog in both environments", () => {
    for (const action of CONFIRM_ACTIONS)
      for (const policy of policies)
        for (const env of ["live", "demo"] as const)
          expect(resolveConfirm(action, env, policy).mode).not.toBe("immediate");
    expect(resolveConfirm("flatten", "demo", { flatten: { mode: "immediate" } }).mode).toBe(
      "dialog",
    );
  });

  it("clamps holdMs to 300-2000 for hold and reports 0 otherwise", () => {
    for (const action of CONFIRM_ACTIONS)
      for (const policy of policies)
        for (const env of ["live", "demo"] as const) {
          const r = resolveConfirm(action, env, policy);
          if (r.mode === "hold") {
            expect(r.holdMs).toBeGreaterThanOrEqual(300);
            expect(r.holdMs).toBeLessThanOrEqual(2000);
          } else expect(r.holdMs).toBe(0);
        }
    expect([100, 300, 5000, Number.NaN, undefined].map(clampHoldMs)).toEqual([
      300, 300, 2000, 800, 800,
    ]);
  });

  it("defaults: Demo holds, Live uses a dialog", () => {
    expect(resolveConfirm("flatten", "demo", {})).toEqual({ mode: "hold", holdMs: 800 });
    expect(resolveConfirm("flatten", "live", {})).toEqual({ mode: "dialog", holdMs: 0 });
  });

  it("Live keeps a user's hold choice, never below the floor, and never a shorter hold than Demo", () => {
    expect(resolveConfirm("flatten", "live", { flatten: { mode: "hold", holdMs: 1200 } })).toEqual({
      mode: "hold",
      holdMs: 1200,
    });
    expect(resolveConfirm("flatten", "live", { flatten: { mode: "dialog" } }).mode).toBe("dialog");
  });

  it("fails closed on an unknown mode or environment, and on a prototype-named action", () => {
    const bad = { flatten: { mode: "skip" } } as unknown as UserPolicy;
    expect(resolveConfirm("flatten", "demo", bad).mode).toBe("dialog");
    expect(resolveConfirm("flatten", "paper" as "live", {}).mode).toBe("dialog");
    expect(
      resolveConfirm("flatten", "live", JSON.parse('{"__proto__":{"mode":"hold"}}')).mode,
    ).toBe("dialog");
  });

  it("takes no accessibility input: the signature is exactly (action, env, policy)", () => {
    expect(resolveConfirm.length).toBe(3);
    const a11y = {
      ...{ flatten: { mode: "hold" as const } },
      reduceMotion: true,
      highContrast: true,
    };
    expect(resolveConfirm("flatten", "live", a11y)).toEqual(
      resolveConfirm("flatten", "live", { flatten: { mode: "hold" } }),
    );
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

  it("persists, reloads and validates stored policy", () => {
    const storage = memory();
    createConfirmPolicyStore(storage).set("flatten", { mode: "hold", holdMs: 1000 });
    expect(createConfirmPolicyStore(storage).get()).toEqual({
      flatten: { mode: "hold", holdMs: 1000 },
    });
    expect(
      parsePolicy({ flatten: { mode: "nope" }, other: { mode: "hold" }, "cancel-all": 3 }),
    ).toEqual({});
    expect(parsePolicy("x")).toEqual({});
    const broken = memory();
    broken.data.set("cv.confirmPolicy.v1", "{not json");
    expect(createConfirmPolicyStore(broken).get()).toEqual({});
  });

  it("the hook follows the store, takes env as input, and unsubscribes on unmount", () => {
    const store = createConfirmPolicyStore();
    const { result, rerender, unmount } = renderHook(
      ({ env }: { env: "live" | "demo" }) => useConfirmPolicy("flatten", env, store),
      { initialProps: { env: "demo" as "live" | "demo" } },
    );
    expect(result.current).toEqual({ mode: "hold", holdMs: 800 });
    act(() => store.set("flatten", { mode: "hold", holdMs: 500 }));
    expect(result.current).toEqual({ mode: "hold", holdMs: 500 });
    rerender({ env: "live" });
    expect(result.current.mode).toBe("hold");
    act(() => store.set("flatten", undefined));
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
