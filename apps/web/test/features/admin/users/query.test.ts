/**
 * E42-S02 (#1023) BQ-7: the users list's query lives in the URL, so a filtered list is a deep link (E42-D03 §7):
 * `role` and `status` take one listed value each and `q` (case-insensitive, ≤120, `22`) is trimmed; anything else is
 * dropped, never sent. The list reads pages of 50 by cursor. Analytics learn whether a search is set, never its
 * words.
 */
import { describe, expect, it } from "vitest";
import {
  analyticsFilters,
  listPath,
  PAGE_SIZE,
  Q_MAX,
  usersQueryOf,
  usersSearch,
} from "../../../../src/features/admin/users/query";

describe("the users list's query", () => {
  it("reads role, status and q from the URL", () => {
    expect(usersQueryOf(new URLSearchParams("role=manager&status=locked&q=%20al%20"))).toEqual({
      role: "manager",
      status: "locked",
      q: "al",
    });
  });

  it("drops a value the contract does not list, a repeated one and an empty search", () => {
    expect(
      usersQueryOf(new URLSearchParams("role=admin&status=deleted&q=%20%20&cursor=c1&x=1")),
    ).toEqual({});
    expect(usersQueryOf(new URLSearchParams("role=viewer&role=owner"))).toEqual({});
    expect(usersQueryOf(new URLSearchParams("role=constructor&status=toString"))).toEqual({});
  });

  it("cuts a longer search to 120 characters", () => {
    const long = "a".repeat(Q_MAX + 30);
    expect(usersQueryOf(new URLSearchParams({ q: long })).q).toHaveLength(120);
  });

  it("writes the query back to the URL, keeping its other parameters", () => {
    const next = usersSearch(
      { role: "owner", q: "carol" },
      new URLSearchParams("tab=x&status=active"),
    );
    expect(next.toString()).toBe("tab=x&role=owner&q=carol");
    expect(usersSearch({}, new URLSearchParams("role=owner&q=al")).toString()).toBe("");
  });

  it("reads 50 users a page, by cursor", () => {
    expect(PAGE_SIZE).toBe(50);
    expect(listPath({})).toBe("/api/v1/users?limit=50");
    expect(listPath({ role: "viewer", status: "invited", q: "a&b=c" }, "next/1")).toBe(
      "/api/v1/users?limit=50&role=viewer&status=invited&q=a%26b%3Dc&cursor=next%2F1",
    );
  });

  it("tells analytics whether a search is set, never its words", () => {
    expect(analyticsFilters({ role: "manager", q: "alex@example.com" })).toEqual({
      role: "manager",
      status: null,
      q: true,
    });
    expect(analyticsFilters({})).toEqual({ role: null, status: null, q: false });
    expect(JSON.stringify(analyticsFilters({ q: "alex" }))).not.toContain("alex");
  });
});
