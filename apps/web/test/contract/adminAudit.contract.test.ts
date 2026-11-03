/**
 * C-6.2 consumer contract (E42-S04, #1135): the audit log's read layer reads the examples
 * `docs/plan/22-api-openapi.yaml` serves for `queryAuditLog` (`orderPlaced`), `verifyAuditChain`
 * (`ok`, `broken`), `getJob` (`running`, `done`), `downloadAuditExport` (`410 expired`) and
 * `listIncidents` (`grouped`) through the generated `packages/protocol` types, each vetted as
 * served, and asks for the contract's paths. The filters' names and limits are `queryAuditLog`'s
 * parameters, and the `orderPlaced` and verify examples land in the page and integrity models.
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  AUDIT_PATHS,
  readDownloadAnswer,
  vetAuditPage,
  vetExportAccepted,
  vetIncidentPage,
  vetJob,
  vetVerifyResult,
  type AuditEntry,
  type AuditQuery,
  type ExportAccepted,
  type ExportBody,
  type Incident,
  type Job,
  type VerifyResult,
} from "../../src/features/admin/audit/auditReads";
import { FILTER_NAMES, PAGE_LIMIT } from "../../src/features/admin/audit/auditFilters";
import { createAuditPageStore, pagerOf } from "../../src/features/admin/audit/auditPageStore";
import {
  bannerModel,
  createIntegrityStore,
  footerModel,
} from "../../src/features/admin/audit/integrity";
import { example, pathBlock, specText } from "../features/admin/audit/specExamples";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;
const JOB = "19000000-0000-4000-8000-000000000001";

describe("audit log consumer contract (C-6.2): the read layer", () => {
  it("test_contract_types_are_the_generated_ones", () => {
    expectTypeOf<AuditEntry>().toEqualTypeOf<Schemas["AuditEntry"]>();
    expectTypeOf<Job>().toEqualTypeOf<Schemas["Job"]>();
    expectTypeOf<Incident>().toEqualTypeOf<Schemas["Incident"]>();
    expectTypeOf<AuditQuery>().toEqualTypeOf<
      NonNullable<Ops["queryAuditLog"]["parameters"]["query"]>
    >();
    expectTypeOf<VerifyResult>().toEqualTypeOf<
      Ops["verifyAuditChain"]["responses"][200]["content"]["application/json"]
    >();
    expectTypeOf<ExportBody>().toEqualTypeOf<
      Ops["exportAuditLog"]["requestBody"]["content"]["application/json"]
    >();
    expectTypeOf<ExportAccepted>().toEqualTypeOf<
      Ops["exportAuditLog"]["responses"][202]["content"]["application/json"]
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
    op("/admin/audit/export", "post", "exportAuditLog");
    op("/admin/jobs/{jobId}", "get", "getJob");
    op("/admin/audit/exports/{jobId}", "get", "downloadAuditExport");
    op("/admin/incidents", "get", "listIncidents");
    expect(AUDIT_PATHS.query).toBe("/api/v1/admin/audit");
    expect(AUDIT_PATHS.verify).toBe("/api/v1/admin/audit/verify");
    expect(AUDIT_PATHS.export).toBe("/api/v1/admin/audit/export");
    expect(AUDIT_PATHS.job(JOB)).toBe(`/api/v1/admin/jobs/${JOB}`);
    expect(AUDIT_PATHS.download(JOB)).toBe(`/api/v1/admin/audit/exports/${JOB}`);
    expect(AUDIT_PATHS.incidents).toBe("/api/v1/admin/incidents");
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

  it.each(["running", "done"])("test_contract_job_%s_example_vets_as_served", (name) => {
    const raw = example("/admin/jobs/{jobId}", name);
    expect(vetJob(raw)).toEqual(raw);
  });

  it("test_contract_export_202_has_the_generated_shape", () => {
    const accepted: ExportAccepted = { job_id: JOB, download_url: null };
    expect(vetExportAccepted(accepted)).toEqual(accepted);
  });

  it("test_contract_download_410_expired_example_is_refused_gone_with_its_ref", async () => {
    const raw = example("/admin/audit/exports/{jobId}", "expired") as Record<string, unknown>;
    const response = new Response(JSON.stringify(raw), {
      status: 410,
      headers: { "Content-Type": "application/problem+json" },
    });
    const held = { method: "GET", url: AUDIT_PATHS.download(JOB), headers: [], body: null };
    expect(await readDownloadAnswer(response, held, JOB)).toMatchObject({
      kind: "refused",
      status: 410,
      code: "gone",
      refId: raw["instance"],
    });
  });

  it("test_contract_incidents_grouped_example_vets_as_served", () => {
    const raw = example("/admin/incidents", "grouped");
    expect(vetIncidentPage(raw)).toEqual(raw);
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

describe("audit log consumer contract (C-6.2): the filters, the page and the integrity", () => {
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

  it("test_contract_orderPlaced_example_lands_in_the_page_model", async () => {
    const body = vetAuditPage(example("/admin/audit", "orderPlaced"));
    if (body === null) throw new Error("the example did not vet");
    const store = createAuditPageStore({
      now: () => 0,
      setTimeout: () => 0,
      clearTimeout: () => undefined,
      document: null,
      view: "raw",
      ownUserId: () => null,
      read: async () => ({ kind: "ok", body }),
    });
    const release = store.hold();
    await Promise.resolve();
    await Promise.resolve();
    const state = store.getState();
    expect(state).toMatchObject({ phase: "ok", rows: body.items, newCount: 0 });
    expect(pagerOf(state)).toEqual({ atNewest: true, atOldest: false, page: 1 });
    expect(footerModel(auditIntegrityAt(), body, { view: "raw" }).line?.key).toBe(
      "tamper.page_passed",
    );
    release();
  });

  it("test_contract_verify_examples_land_in_the_integrity_model", async () => {
    let next: unknown = null;
    const store = createIntegrityStore({
      now: () => 0,
      setTimeout: () => 0,
      clearTimeout: () => undefined,
      document: null,
      readIncidents: async () => ({ kind: "failed", reason: "network" }),
      verify: async () => {
        const body = vetVerifyResult(next);
        return body === null ? { kind: "failed", reason: "unreadable" } : { kind: "ok", body };
      },
    });
    const settle = async (): Promise<void> => {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
    };
    // held, as SCR-135 holds it: a run's break waits for its incident read (A-1135P2-09)
    const release = store.hold();
    next = example("/admin/audit/verify", "ok");
    store.runCheck();
    await settle();
    expect(store.getState().passes).toEqual([
      { fromId: 87120442, toId: 88120441, checkedAt: "2026-09-14T10:37:00Z" },
    ]);
    next = example("/admin/audit/verify", "broken");
    store.runCheck();
    await settle();
    expect(bannerModel(store.getState())).toMatchObject({
      voice: "break:41207",
      title: "Tamper check FAILED at entry 41,207 — treat this as a security incident",
      facts: "Found at 10:37:05 UTC on 2026-09-14 in a check of entries 1–1,000,000.",
    });
    release();
  });
});

/** A fresh integrity state with nothing found, for the footer's page lines. */
function auditIntegrityAt(): ReturnType<ReturnType<typeof createIntegrityStore>["getState"]> {
  return createIntegrityStore({
    now: () => 0,
    setTimeout: () => 0,
    clearTimeout: () => undefined,
    document: null,
    readIncidents: async () => ({ kind: "failed", reason: "network" }),
    verify: async () => ({ kind: "unknown" }),
  }).getState();
}
