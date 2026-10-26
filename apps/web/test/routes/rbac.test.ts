import { describe, expect, it } from "vitest";
import { evaluateAccess, type MeClaims } from "../../src/routes/rbac";

const base: MeClaims = {
  authenticated: true,
  role: "viewer",
  permissions: [],
};

describe("evaluateAccess", () => {
  it("allows a public route with no session", () => {
    const unauth: MeClaims = {
      authenticated: false,
      role: null,
      permissions: [],
    };
    expect(evaluateAccess({ roles: "public" }, unauth)).toEqual({ kind: "allow" });
  });

  it("redirects to login when unauthenticated on a protected route", () => {
    const unauth: MeClaims = {
      authenticated: false,
      role: null,
      permissions: [],
    };
    expect(evaluateAccess({ roles: ["owner"] }, unauth)).toEqual({ kind: "redirect-login" });
  });

  it("allows a role explicitly listed", () => {
    expect(evaluateAccess({ roles: ["owner", "viewer"] }, base)).toEqual({ kind: "allow" });
  });

  it("denies with 403 by default", () => {
    expect(evaluateAccess({ roles: ["owner"] }, base)).toEqual({ kind: "deny", as: "403" });
  });

  it("denies /admin/** with 404 per the sitemap note, not 403", () => {
    expect(evaluateAccess({ roles: ["owner"], denyAs: "404" }, base)).toEqual({
      kind: "deny",
      as: "404",
    });
  });

  it("lets an owner into an admin route with no client step-up check (#2725)", () => {
    const owner: MeClaims = { ...base, role: "owner" };
    expect(evaluateAccess({ roles: ["owner"], denyAs: "404" }, owner)).toEqual({ kind: "allow" });
  });

  it("still denies a manager an admin route with 404", () => {
    const manager: MeClaims = { ...base, role: "manager" };
    expect(evaluateAccess({ roles: ["owner"], denyAs: "404" }, manager)).toEqual({
      kind: "deny",
      as: "404",
    });
  });

  it("still redirects an unauthenticated session away from an admin route", () => {
    const unauth: MeClaims = { authenticated: false, role: null, permissions: [] };
    expect(evaluateAccess({ roles: ["owner"], denyAs: "404" }, unauth)).toEqual({
      kind: "redirect-login",
    });
  });
});
