/**
 * E42-S04 (#1135): the filter set as URL state and as a query (E42-D04 §4 Filters, D4, D7; BQ-3).
 * The URL carries the contract's names, never a cursor; a request leaves Environment out (it
 * filters the loaded page only), sorts and dedupes the action codes and asks for 200 rows; the
 * client checks no value, and the server's `422` decides. For a Manager
 * ("My activity") the model drops Actor, and `q`, `ip` and Environment are T2 `rbac.owner_only`:
 * none of them is ever sent (the orchestrator's BQ-3).
 */
import { describe, expect, it } from "vitest";
import {
  FILTER_NAMES,
  PAGE_LIMIT,
  filtersKey,
  isFiltered,
  parseFilters,
  queryOf,
  rowsFor,
  searchOf,
  type AuditFilters,
} from "../../../../src/features/admin/audit/auditFilters";
import { OWNER_ID, entry } from "./fixtures";

const FROM = "2026-10-22T13:00:00Z";
const TO = "2026-10-22T14:00:00Z";

describe("parseFilters: URL state to the filter set", () => {
  it("test_parseFilters_reads_every_contract_name_and_repeated_action", () => {
    const search =
      `?actor_user_id=${OWNER_ID}&action=orders.submit&action=flags.change` +
      "&subject_type=order&subject_id=0a01&outcome=failure&severity=error&ip=100.84.12.9" +
      `&from=${FROM}&to=${TO}&q=BTC+usdt&environment=live`;
    expect(parseFilters(search)).toEqual({
      filters: {
        actor_user_id: OWNER_ID,
        action: ["orders.submit", "flags.change"],
        subject_type: "order",
        subject_id: "0a01",
        outcome: "failure",
        severity: "error",
        ip: "100.84.12.9",
        from: FROM,
        to: TO,
        q: "BTC usdt",
        environment: "live",
      },
      dropped: [],
    });
  });

  it("test_parseFilters_never_takes_a_cursor_or_a_limit_from_the_url", () => {
    expect(parseFilters("?cursor=eyJ2IjoxfQ&limit=5&q=x").filters).toEqual({ q: "x" });
  });

  it("test_parseFilters_drops_an_enum_value_the_contract_lacks_and_names_it", () => {
    expect(parseFilters("severity=fatal&outcome=ok&environment=staging&q=x")).toEqual({
      filters: { q: "x" },
      dropped: ["outcome", "severity", "environment"],
    });
  });

  it("test_parseFilters_own_view_drops_actor_q_ip_and_environment_and_names_them", () => {
    // AL-25, AL-26 as ruled (BQ-3): a crafted link's Owner-only filters are dropped, never sent,
    // and named so the bar can say `audit.own_filter`
    expect(
      parseFilters(
        `actor_user_id=${OWNER_ID}&environment=live&q=x&ip=100.84.12.9&severity=error`,
        "own",
      ),
    ).toEqual({
      filters: { severity: "error" },
      dropped: ["actor_user_id", "ip", "q", "environment"],
    });
  });

  it("test_parseFilters_trims_drops_blanks_and_repeated_codes", () => {
    expect(
      parseFilters("q=%20%20&subject_id=%20a%20&action=a.b&action=+a.b+&action=").filters,
    ).toEqual({ subject_id: "a", action: ["a.b"] });
  });
});

describe("searchOf and queryOf", () => {
  const filters: AuditFilters = {
    q: "BTC usdt",
    environment: "demo",
    action: ["orders.submit", "flags.change"],
    severity: "error",
    from: FROM,
  };

  it("test_searchOf_writes_contract_names_in_order_and_round_trips", () => {
    const search = searchOf(filters);
    expect(search).toBe(
      "action=orders.submit&action=flags.change&severity=error" +
        "&from=2026-10-22T13%3A00%3A00Z&q=BTC+usdt&environment=demo",
    );
    expect(parseFilters(search).filters).toEqual(filters);
    expect(searchOf({})).toBe("");
  });

  it("test_searchOf_never_writes_a_cursor_or_limit", () => {
    const withPaging = { ...filters, cursor: "c1", limit: 200 } as AuditFilters;
    expect(new URLSearchParams(searchOf(withPaging)).has("cursor")).toBe(false);
    expect(new URLSearchParams(searchOf(withPaging)).has("limit")).toBe(false);
  });

  it("test_queryOf_leaves_environment_out_sorts_codes_and_asks_200", () => {
    expect(PAGE_LIMIT).toBe(200);
    expect(queryOf({ ...filters, action: ["b.c", "a.b", "b.c"], q: "  " }, "c1")).toEqual({
      action: ["a.b", "b.c"],
      severity: "error",
      from: FROM,
      limit: 200,
      cursor: "c1",
    });
    expect(queryOf({ environment: "live" })).toEqual({ limit: 200 });
  });

  it("test_queryOf_never_sends_a_managers_actor_q_or_ip", () => {
    const crafted: AuditFilters = {
      actor_user_id: OWNER_ID,
      q: "BTC",
      ip: "100.84.12.9",
      severity: "error",
    };
    expect(queryOf(crafted, null, "own")).toEqual({ severity: "error", limit: 200 });
    expect(filtersKey({ q: "a" }, "own")).toBe(filtersKey({}, "own"));
    expect(filtersKey({ q: "a" }, "raw")).not.toBe(filtersKey({}, "raw"));
  });

  it("test_filters_read_set_is_blind_to_environment_and_code_order", () => {
    expect(filtersKey({ environment: "live" })).toBe(filtersKey({}));
    expect(filtersKey({ action: ["a.b", "c.d"] })).toBe(filtersKey({ action: ["c.d", "a.b"] }));
    expect(filtersKey({ q: "x" })).not.toBe(filtersKey({ q: "y" }));
    expect(filtersKey({ q: " x " })).toBe(filtersKey({ q: "x" }));
  });

  it("test_isFiltered_counts_any_filter_environment_included", () => {
    expect(isFiltered({})).toBe(false);
    expect(isFiltered({ q: "  " })).toBe(false);
    expect(isFiltered({ environment: "live" })).toBe(true);
    expect(isFiltered({ action: ["a.b"] })).toBe(true);
  });
});

describe("rowsFor: Environment filters the loaded page only (D7)", () => {
  it("test_rowsFor_keeps_one_environments_rows_and_all_without_one", () => {
    const items = [
      entry({ id: 3, environment: "live" }),
      entry({ id: 2, environment: "demo" }),
      entry({ id: 1, environment: null }),
    ];
    expect(rowsFor(items, "demo").map((e) => e.id)).toEqual([2]);
    expect(rowsFor(items, undefined)).toBe(items);
  });
});

describe("the filter names", () => {
  it("test_the_filter_names_are_exported_for_the_contract_test", () => {
    expect(FILTER_NAMES).toEqual([
      "actor_user_id",
      "action",
      "subject_type",
      "subject_id",
      "outcome",
      "severity",
      "ip",
      "from",
      "to",
      "q",
      "environment",
    ]);
  });
});
