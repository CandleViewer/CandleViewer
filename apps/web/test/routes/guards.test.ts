import { describe, expect, it, beforeEach } from "vitest";
import { setMeClaims, resetMeClaims } from "../../src/lib/auth/meCache";
import { guardRoute, ForbiddenError } from "../../src/routes/guards";

const URL_BASE = "https://app.local";

describe("guardRoute", () => {
  beforeEach(() => {
    resetMeClaims();
  });

  it("does not throw for a public route", () => {
    expect(() => guardRoute("R-001", { roles: "public" }, `${URL_BASE}/login`)).not.toThrow();
  });

  it("throws a redirect Response preserving the intended destination when unauthenticated", () => {
    let caught: unknown;
    try {
      guardRoute("R-101", { roles: ["owner"] }, `${URL_BASE}/terminal/abc?tf=15`);
    } catch (thrown) {
      caught = thrown;
    }
    expect(caught).toBeInstanceOf(Response);
    const response = caught as Response;
    expect(response.status).toBe(302);
    const location = response.headers.get("Location") ?? "";
    expect(location).toContain("/login?next=");
    expect(decodeURIComponent(location.split("next=")[1] ?? "")).toBe("/terminal/abc?tf=15");
  });

  it("throws ForbiddenError(403) for a role-denied non-admin route", () => {
    setMeClaims({ authenticated: true, role: "viewer", permissions: [] });
    expect(() => guardRoute("R-160", { roles: ["owner", "manager"] }, `${URL_BASE}/rules`)).toThrow(
      ForbiddenError,
    );
    try {
      guardRoute("R-160", { roles: ["owner", "manager"] }, `${URL_BASE}/rules`);
    } catch (err) {
      expect((err as ForbiddenError).as).toBe("403");
    }
  });

  it("throws ForbiddenError(404) for a viewer hitting an admin route", () => {
    setMeClaims({ authenticated: true, role: "viewer", permissions: [] });
    try {
      guardRoute("R-301", { roles: ["owner"], denyAs: "404" }, `${URL_BASE}/admin/users`);
      throw new Error("expected guardRoute to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ForbiddenError);
      expect((err as ForbiddenError).as).toBe("404");
    }
  });

  it("lets an owner into an admin route with no client step-up pre-emption (#2725)", () => {
    setMeClaims({ authenticated: true, role: "owner", permissions: [] });
    expect(() =>
      guardRoute("R-300", { roles: ["owner"], denyAs: "404" }, `${URL_BASE}/admin`),
    ).not.toThrow();
  });

  it("throws ForbiddenError(404) for a manager hitting an admin route", () => {
    setMeClaims({ authenticated: true, role: "manager", permissions: [] });
    expect(() =>
      guardRoute("R-300", { roles: ["owner"], denyAs: "404" }, `${URL_BASE}/admin`),
    ).toThrow(ForbiddenError);
  });
});
