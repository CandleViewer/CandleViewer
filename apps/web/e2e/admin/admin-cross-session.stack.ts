import type { Response } from "@playwright/test";
import { elevate, openApiActor, openPageActor } from "../support/real/adminWorld";
import { expect, test, type AuditRow } from "../support/real/failureArtefacts";
import { judgeTiming, serverDeltaMs, timingRecord, untilWithin } from "../support/real/timing";

// E42-Q02 (#1215) part 1: the cross-session admin specs on the real stack (BQ-2), run by the
// `testnet` job of e2e-admin-real.yml through playwright.admin-stack.config.ts, one at a time.
// Each test claims its own users (`support/real/adminWorld.ts`), so none reads what another left.
// Timings are judged on the server's audit stamps and kept per run (`support/real/timing.ts`,
// BQ-4). These tests present `cv_refresh` 4 times in all.
// Not here: AD-X-01's order and rule bullets, which need an account and an armed rule (the rule
// half is E42-T04's drill); the users-only stack has neither.

const ADMIN_READ = /^\/api\/v1\/admin\//u;
const OVERVIEW = "/api/v1/admin/overview";
const STEP_UP = "/api/v1/auth/step-up";
/** The audit lane writes journal-first (ADR-0037): a row may land after its answer. */
const SETTLE_MS = 15_000;
const SIGN_IN = "Sign in to CandleViewer";

const count = (rows: readonly AuditRow[], match: (row: AuditRow) => boolean): number =>
  rows.filter(match).length;

test("E42-Q02 AD-S01-01 (real half) an owner opens /admin: the band first, the overview read, no step-up asked, each admin read recorded as allowed @regression", async ({
  lane,
}) => {
  await lane.refreshes(1); // the page load
  const reads: Response[] = [];
  const stepUps: string[] = [];
  const pathOf = (url: string): string => new URL(url).pathname;
  const { page } = await openPageActor(lane, "owner", {
    route: "/admin",
    before: (p) => {
      p.on("response", (r) => {
        if (ADMIN_READ.test(pathOf(r.url()))) reads.push(r);
      });
      p.on("request", (r) => {
        if (pathOf(r.url()) === STEP_UP) stepUps.push(r.method());
      });
    },
  });
  const band = page.getByRole("region", { name: "Admin area" });
  await expect(page.getByRole("main").getByRole("region").first()).toHaveAccessibleName(
    "Admin area",
  );
  await expect(band).toHaveText("◆ Admin area · Overview");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Overview");
  await expect
    .poll(() => reads.some((r) => pathOf(r.url()) === OVERVIEW && r.status() === 200))
    .toBe(true);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(stepUps, "entering asks for no step-up").toEqual([]);

  // Each read's own record (QA AD-S01-01): the first answer per path names the request the area
  // guard wrote ahead of (a repeat inside its window is counted, not written: area_coalescer.py)
  const first = new Map<string, string>();
  for (const r of reads) {
    const id = r.headers()["x-correlation-id"];
    if (id !== undefined && !first.has(pathOf(r.url()))) first.set(pathOf(r.url()), id);
  }
  expect(first.size, "the page made admin reads").toBeGreaterThan(0);
  await expect
    .poll(
      async () => {
        const rows = (await lane.auditRows()).filter((r) => r["action"] === "admin.area_entered");
        const recorded = (id: string): boolean =>
          rows.some((r) => r["request_id"] === id && r["outcome"] === "success");
        return {
          unrecorded: [...first].filter(([, id]) => !recorded(id)).map(([path]) => path),
          refused: count(rows, (r) => r["outcome"] !== "success"),
        };
      },
      { timeout: SETTLE_MS },
    )
    .toEqual({ unrecorded: [], refused: 0 });
});

test("E42-Q02 AD-X-01 the owner disables a signed-in manager: its records show every session revoked within 5 s, bye user_disabled then 4403, the next call refused, then SCR-001 @regression", async ({
  lane,
}, testInfo) => {
  await lane.refreshes(3); // the manager's page load, its refused call, its SCR-001 page load
  const owner = await openApiActor(lane, "owner");
  const manager = await openPageActor(lane, "manager", { route: "/terminal/last" });
  await expect(manager.page.getByRole("button", { name: /^Connection: Live/u })).toBeVisible({
    timeout: 20_000,
  });
  expect(
    manager.tap.frames.some((f) => f["t"] === "auth_ok"),
    "its socket is live",
  ).toBe(true);
  const signedIn = await manager.session();
  expect({ status: signedIn.status, roles: signedIn.roles }).toEqual({
    status: 200,
    roles: ["manager"],
  });
  const target = `/users/${signedIn.userId ?? "unknown"}`;

  const elevated = await elevate(owner, "users");
  expect({ status: elevated.status, body: elevated.body }).toMatchObject({
    status: 200,
    body: { action_class: "users" },
  });
  const read = await owner.api({ method: "GET", path: target });
  expect({ status: read.status, versioned: read.etag !== null }).toEqual({
    status: 200,
    versioned: true,
  });
  // Every disable on this main carries the acknowledgement: no open-position source is wired
  const disable = {
    method: "PATCH",
    path: `${target}?acknowledge_unknown_positions=true`,
    ifMatch: read.etag ?? "",
    body: { status: "disabled" },
  } as const;
  const sent = Date.now();
  expect((await owner.api(disable)).status, "the disable").toBe(200);

  // The manager's next request is refused: read until it is, never after a fixed wait
  const next = await untilWithin(
    "manager-next-request-refused",
    SETTLE_MS,
    () => manager.session(),
    (s) => s.status !== 200,
    { show: (s) => `${s.status} ${s.code ?? "no code"}` },
  );
  // The runner's figure is trend data beside the server's: the refusal is bounded by SETTLE_MS
  const runnerMs = Date.now() - sent;
  expect(next.value).toEqual({ status: 401, code: "unauthenticated", userId: null, roles: [] });
  // Its socket: `bye user_disabled`, then the 4403 close (23 §9.5)
  await expect.poll(() => manager.tap.closes.map((c) => c.code)).toEqual([4403]);
  expect(manager.tap.frames.at(-1)).toMatchObject({
    t: "bye",
    p: { code: 4403, reason: "user_disabled" },
  });
  // Its next call goes to SCR-001, with no second socket (sign-out-everywhere.real.ts's path)
  await manager.page.getByRole("link", { name: "Settings" }).click();
  await expect(manager.page).toHaveURL(/\/login\?next=%2Fsettings%2Fprofile$/u);
  await expect(manager.page.getByRole("heading", { name: SIGN_IN })).toBeVisible();
  expect(manager.tap.connections(), "no second socket").toBe(1);

  // The 5 s is judged on the server basis (the plan's section 5): the `users.disable` record
  // (written ahead of its commit, so the interval starts before the change) to the last of the
  // manager's sessions revoked
  const isDisable = (r: AuditRow): boolean =>
    r["action"] === "users.disable" && r["outcome"] === "success";
  const isRevoked = (r: AuditRow): boolean =>
    r["action"] === "auth.session_revoked" &&
    r["reason"] === "user_disabled" &&
    r["actor"] === manager.user.username;
  const rows = await untilWithin(
    "disable-records",
    SETTLE_MS,
    () => lane.auditRows(),
    (all) => count(all, isDisable) > 0 && count(all, isRevoked) > 0,
  );
  const [record] = rows.value.filter(isDisable);
  const last = rows.value.filter(isRevoked).at(-1);
  if (record === undefined || last === undefined) throw new Error("the disable's records went");
  const label = "disable-to-last-session-revoked";
  const observed = serverDeltaMs(record, last);
  judgeTiming(
    testInfo,
    timingRecord({
      case: "AD-X-01",
      label,
      budget_ms: 5_000,
      observed_ms: observed,
      runner_ms: runnerMs,
      basis: "server-record",
    }),
  );

  // The spent `ETag` is refused and writes nothing: one record of each, no rule disarmed
  const stale = await owner.api(disable);
  expect({ status: stale.status, code: stale.code }).toEqual({
    status: 412,
    code: "version_conflict",
  });
  await expect
    .poll(
      async () => {
        const all = await lane.auditRows();
        return {
          disabled: count(all, isDisable),
          revoked: count(all, isRevoked),
          disarmed: count(all, (r) => r["action"] === "rules.disarm"),
        };
      },
      { timeout: SETTLE_MS },
    )
    .toEqual({ disabled: 1, revoked: 1, disarmed: 0 }); // the manager held one live session
});
