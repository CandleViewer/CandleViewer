/**
 * C-6.2 consumer contract (E42-S04, #1135): the audit log's read layer reads the examples
 * `docs/plan/22-api-openapi.yaml` serves for `queryAuditLog` (`orderPlaced`) and
 * `verifyAuditChain` (`ok`, `broken`) through the generated `packages/protocol` types, each vetted
 * as served, and asks for the contract's paths. The filters' names and the page size are
 * `queryAuditLog`'s parameters.
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  AUDIT_PATHS,
  vetAuditPage,
  vetVerifyResult,
  type AuditEntry,
  type AuditQuery,
  type VerifyResult,
} from "../../src/features/admin/audit/auditReads";
import { FILTER_NAMES, PAGE_LIMIT } from "../../src/features/admin/audit/auditFilters";
import { example, pathBlock, specText } from "../features/admin/audit/specExamples";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;

describe("audit log consumer contract (C-6.2): the read layer", () => {
  it("test_contract_types_are_the_generated_ones", () => {
    expectTypeOf<AuditEntry>().toEqualTypeOf<Schemas["AuditEntry"]>();
    expectTypeOf<AuditQuery>().toEqualTypeOf<
      NonNullable<Ops["queryAuditLog"]["parameters"]["query"]>
    >();
    expectTypeOf<VerifyResult>().toEqualTypeOf<
      Ops["verifyAuditChain"]["responses"][200]["content"]["application/json"]
    >();
  });

  it("test_contract_paths_are_the_operations_under_the_api_v1_base", () => {
    expect(specText()).toContain("- url: http://127.0.0.1:8000/api/v1\n");
    const op = (path: string, verb: string, id: string): void => {
      expect(pathBlock(path).join("\n"), `${verb} ${path}`).toMatch(
        new RegExp(`\\n {4}${verb}:\\n(?: {6}.*\\n)*? {6}operationId: ${id}\\n`),
      );
    };
    op("/admin/audit", "get", "queryAuditLog");
    op("/admin/audit/verify", "post", "verifyAuditChain");
    expect(AUDIT_PATHS.query).toBe("/api/v1/admin/audit");
    expect(AUDIT_PATHS.verify).toBe("/api/v1/admin/audit/verify");
  });

  it("test_contract_orderPlaced_example_vets_as_served", () => {
    const raw = example("/admin/audit", "orderPlaced");
    const page = vetAuditPage(raw);
    expect(page).toEqual(raw);
    expect(page?.items[0]).toMatchObject({
      id: 88120441,
      action: "trade_group.submit",
      environment: "live",
      detail: { before: null, after: { symbol: "BTCUSDT", legs: 3 } },
    });
    expect(page?.meta).toMatchObject({ has_more: true, count: 1 });
  });

  it.each(["ok", "broken"])("test_contract_verify_%s_example_vets_as_served", (name) => {
    const raw = example("/admin/audit/verify", name);
    expect(vetVerifyResult(raw)).toEqual(raw);
  });
});

/** The `/admin/audit` GET's parameters, each with its text, `$ref`s resolved to their names. */
function queryParameters(): Map<string, string> {
  const block = pathBlock("/admin/audit").join("\n");
  const start = block.indexOf("\n      parameters:\n");
  const end = block.indexOf("\n      x-rbac:", start);
  const chunks = block
    .slice(start, end)
    .split(/\n {8}- /)
    .slice(1);
  const out = new Map<string, string>();
  for (const chunk of chunks) {
    const named = /^name: (\w+)/.exec(chunk)?.[1];
    const ref = /^\$ref: "#\/components\/parameters\/(\w+)"/.exec(chunk)?.[1];
    if (named !== undefined) {
      out.set(named, chunk);
    } else if (ref !== undefined) {
      const rest = specText().slice(specText().indexOf(`\n    ${ref}:\n      name: `) + 1);
      const next = rest.search(/\n {4}\S/);
      const text = next < 0 ? rest : rest.slice(0, next);
      out.set(/\n {6}name: (\w+)/.exec(text)?.[1] ?? ref, text);
    }
  }
  return out;
}

describe("audit log consumer contract (C-6.2): the filters", () => {
  it("test_contract_query_parameters_are_the_filter_names_plus_cursor_and_limit", () => {
    const names = [...queryParameters().keys()];
    expect(names.slice(0, 2)).toEqual(["cursor", "limit"]);
    expect(names.slice(2)).toEqual(FILTER_NAMES.filter((name) => name !== "environment"));
  });

  it("test_contract_query_limit_bounds_the_page_size", () => {
    const limit = /minimum: (\d+), maximum: (\d+)/.exec(queryParameters().get("limit") ?? "");
    expect(PAGE_LIMIT).toBeGreaterThanOrEqual(Number(limit?.[1]));
    expect(PAGE_LIMIT).toBeLessThanOrEqual(Number(limit?.[2]));
  });
});
