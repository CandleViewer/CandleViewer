/**
 * C-6.2 consumer contract (E42-S04, #1135): the audit log's read layer reads the examples
 * `docs/plan/22-api-openapi.yaml` serves for `queryAuditLog` (`orderPlaced`) and
 * `verifyAuditChain` (`ok`, `broken`) through the generated `packages/protocol` types, each vetted
 * as served, and asks for the contract's paths.
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
