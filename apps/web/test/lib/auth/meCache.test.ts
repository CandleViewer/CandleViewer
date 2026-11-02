import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CLAIMS_MAX_AGE_MS,
  getMeClaims,
  refreshMeClaims,
  resetMeClaims,
  setMeClaims,
  setMeClaimsReader,
  subscribeMeClaims,
} from "../../../src/lib/auth/meCache";
import type { MeClaims } from "../../../src/routes/rbac";

describe("meCache", () => {
  beforeEach(() => {
    resetMeClaims();
  });

  it("defaults to an unauthenticated claims object", () => {
    expect(getMeClaims()).toEqual({
      authenticated: false,
      role: null,
      permissions: [],
    });
  });

  it("returns whatever was last set, synchronously", () => {
    setMeClaims({
      authenticated: true,
      role: "owner",
      permissions: ["rules:author"],
    });
    expect(getMeClaims().role).toBe("owner");
  });

  it("holds no step-up elevation: that is server-side session state (#2725)", () => {
    setMeClaims({ authenticated: true, role: "owner", permissions: [] });
    expect(Object.keys(getMeClaims()).sort()).toEqual(["authenticated", "permissions", "role"]);
    resetMeClaims();
    expect(getMeClaims().authenticated).toBe(false);
  });
});

// #5405: a navigation re-reads `/me` past the staleness bound; within it, no request.
describe("meCache refresh on navigation", () => {
  const owner: MeClaims = { authenticated: true, role: "owner", permissions: [] };
  const viewer: MeClaims = { authenticated: true, role: "viewer", permissions: [] };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-02T00:00:00Z"));
    resetMeClaims();
  });
  afterEach(() => {
    resetMeClaims();
    vi.useRealTimers();
  });

  const age = (ms: number): void => {
    vi.setSystemTime(Date.now() + ms);
  };

  it("is a no-op with no reader registered (before the bootstrap)", async () => {
    await refreshMeClaims();
    expect(getMeClaims().authenticated).toBe(false);
  });

  it("reads nothing within the bound and re-reads once past it", async () => {
    const read = vi.fn(() => Promise.resolve(viewer));
    setMeClaims(owner);
    setMeClaimsReader(read);
    age(CLAIMS_MAX_AGE_MS - 1);
    await refreshMeClaims();
    expect(read).not.toHaveBeenCalled();
    expect(getMeClaims().role).toBe("owner");
    age(1);
    await refreshMeClaims();
    expect(read).toHaveBeenCalledTimes(1);
    expect(getMeClaims().role).toBe("viewer");
    await refreshMeClaims(); // the read restarts the bound
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("shares one request between concurrent loaders", async () => {
    const read = vi.fn(() => Promise.resolve(viewer));
    setMeClaims(owner);
    setMeClaimsReader(read);
    age(CLAIMS_MAX_AGE_MS);
    await Promise.all([refreshMeClaims(), refreshMeClaims(), refreshMeClaims()]);
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("keeps the cached claims when the read fails", async () => {
    setMeClaims(owner);
    setMeClaimsReader(() => Promise.reject(new Error("offline")));
    age(CLAIMS_MAX_AGE_MS);
    await refreshMeClaims();
    expect(getMeClaims()).toEqual(owner);
  });

  it("notifies subscribers on a change only, keeping the object for equal claims", async () => {
    const listener = vi.fn();
    const unsubscribe = subscribeMeClaims(listener);
    setMeClaims(owner);
    const first = getMeClaims();
    setMeClaims({ ...owner, permissions: [] });
    expect(getMeClaims()).toBe(first);
    expect(listener).toHaveBeenCalledTimes(1);
    setMeClaims(viewer);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setMeClaims(owner);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("drops a read that answers after a reset", async () => {
    let answer: (claims: MeClaims) => void = () => undefined;
    setMeClaims(owner);
    setMeClaimsReader(
      () =>
        new Promise<MeClaims>((resolve) => {
          answer = resolve;
        }),
    );
    age(CLAIMS_MAX_AGE_MS);
    const pending = refreshMeClaims();
    resetMeClaims();
    answer(viewer);
    await pending;
    expect(getMeClaims().authenticated).toBe(false);
  });
});
