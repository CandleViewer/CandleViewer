import { describe, expect, it, beforeEach } from "vitest";
import { getMeClaims, setMeClaims, resetMeClaims } from "../../../src/lib/auth/meCache";

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
