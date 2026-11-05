import type { Page } from "@playwright/test";
import {
  elevate,
  openApiActor,
  openPageActor,
  withChallenge,
  type ApiActor,
  type ApiCall,
  type ApiFacts,
  type PageActor,
} from "../support/real/adminWorld";
import { expect, test, type AuditRow } from "../support/real/failureArtefacts";
import { judgeTiming, timingRecord, untilWithin } from "../support/real/timing";
import {
  flagPushes,
  inOrder,
  listedFlag,
  noticePushes,
  pushedKeys,
  recordToFrameMs,
  rowsOf,
  runUndos,
  stepUpTrail,
  writeAheadRecord,
  writtenVersion,
  type ListedFlag,
  type Undo,
} from "./flagFrames";

// E42-Q02 (#1215) part 2, the API half: feature flags and maintenance mode on the real stack
// (BQ-2), run by the `testnet` job of e2e-admin-real.yml through playwright.admin-stack.config.ts,
// one test at a time. The owner writes through `PUT /admin/feature-flags/{flagKey}` from an API
// actor, with real step-ups (`elevate` for the `flags` grace, `withChallenge` for a `killswitch`
// release); the other sessions are page actors whose sockets are tapped, so every push is read as
// the server sent it (`23` §15.9). Timings are judged from the write's write-ahead `flags.change`
// record to the frame's `ts`, both on the server's wall clock (BQ-4), and kept per run.
// The UI half (SCR-145, SCR-148 and their dialogs' step-up through SCR-006) waits for #1024.
// Every test reads a flag before it writes it and writes back what it read, so none depends on what
// another left; the stack is the run's own. No request here names `trading.live_enabled`
// (E42-Q06 owns that flag's spec), which the file's last hook checks.
// These tests present `cv_refresh` 6 times in all. That is 6 refreshes in this file; the lane's
// 10 are the status file's count.
// A flag a test reads is put back by `test.afterEach` even when the test fails half way (`undo`).

/** The flags these tests write; never `trading.live_enabled`. */
type Written =
  | "rules.graph_editor"
  | "rules.form_editor"
  | "maintenance.keep_recorder"
  | "trading.one_click"
  | "killswitch.order_entry"
  | "maintenance.mode";

/** An all-roles UI flag (FLAG-UI, `QA` §1). */
const UI_FLAG = "rules.graph_editor";
/** The owner-only flag that stops nothing while maintenance is off (`QA` AD-S05-01). */
const OWNER_ONLY = "maintenance.keep_recorder";
const LIVE_GATE = "trading.live_enabled";
const ROUTE = "/terminal/last";
/** The audit lane writes journal-first (ADR-0037): a row may land after its answer. */
const SETTLE_MS = 15_000;
/** Q-21 (BQ-4): a flag change reaches every client within 10 s; `23` §15.9 asks 2 s. */
const FLAG_REACH_MS = 10_000;
/** SCR-148: the maintenance notice reaches every session within 2 s. */
const NOTICE_MS = 2_000;

/** Every API request the file's actors made (URL and body), for the last hook. */
const requested: string[] = [];

/** One API answer as the actor's page saw it: what was asked, and the correlation id it carried. */
interface Answer {
  readonly method: string;
  readonly path: string;
  readonly status: number;
  readonly id: string;
}

/** Records the actor page's API answers in order; `last` is the newest of one method and path. */
function answers(page: Page): {
  readonly all: Answer[];
  last(method: string, path: string): Answer;
} {
  const all: Answer[] = [];
  page.on("request", (r) => {
    // The whole URL and the body: the live gate may be named in a query or a payload, not the path
    if (new URL(r.url()).pathname.startsWith("/api/v1/")) {
      requested.push(`${r.url()} ${r.postData() ?? ""}`);
    }
  });
  page.on("response", (r) => {
    const id = r.headers()["x-correlation-id"];
    if (id === undefined) return;
    const path = new URL(r.url()).pathname.replace(/^\/api\/v1/u, "");
    all.push({ method: r.request().method(), path, status: r.status(), id });
  });
  return {
    all,
    last: (method, path) => {
      const found = all.filter((a) => a.method === method && a.path === path).at(-1);
      if (found === undefined) throw new Error(`no answer to ${method} ${path} was seen`);
      return found;
    },
  };
}

const flagPath = (key: Written): string => {
  if ((key as string) === LIVE_GATE) throw new Error("this file never writes the live gate");
  return `/admin/feature-flags/${key}`;
};

/** A write of `value` on the version `expected`, with a reason that names the case. */
const write = (key: Written, value: boolean, expected: string, scenario: string): ApiCall => ({
  method: "PUT",
  path: flagPath(key),
  body: { value, reason: `E42-Q02 admin lane, case ${scenario}`, expected_updated_at: expected },
});

/** The flag as the owner reads it now (`GET /admin/feature-flags`). */
async function read(owner: ApiActor, key: Written): Promise<ListedFlag> {
  const list = await owner.api({ method: "GET", path: "/admin/feature-flags" });
  expect(list.status, "the owner reads the flag list").toBe(200);
  return listedFlag(list.body, key);
}

const bool = (flag: ListedFlag): boolean => {
  expect(typeof flag.value, "a boolean flag").toBe("boolean");
  return flag.value === true;
};

const written = (facts: ApiFacts, what: string): string => {
  expect({ status: facts.status, code: facts.code }, what).toEqual({ status: 200, code: null });
  return writtenVersion(facts.body);
};

/** A page actor on the terminal with its socket live: `auth_ok` and the `system` snap seen. */
async function connected(
  lane: Parameters<typeof openPageActor>[0],
  role: "owner" | "manager" | "viewer",
): Promise<PageActor> {
  const actor = await openPageActor(lane, role, { route: ROUTE });
  await expect
    .poll(
      () => ({
        authed: actor.tap.frames.some((f) => f["t"] === "auth_ok"),
        snapped: actor.tap.frames.some((f) => f["t"] === "snap" && f["ch"] === "system"),
      }),
      { timeout: 20_000 },
    )
    .toEqual({ authed: true, snapped: true });
  return actor;
}

/** The slice once `ready` holds, read until it does (the audit lane is journal-first). */
async function slice(
  lane: { auditRows(): Promise<AuditRow[]> },
  label: string,
  ready: (rows: readonly AuditRow[]) => boolean,
): Promise<AuditRow[]> {
  return (await untilWithin(label, SETTLE_MS, () => lane.auditRows(), ready)).value;
}

/** What the running test must put back, newest last; `afterEach` runs it newest first. */
const undo: Undo[] = [];

/**
 * Puts `key` back to `original` after the test, whatever happened: re-reads the flag, skips when it
 * is already there, else writes it back with the owner's own step-up answer (`flags` or
 * `killswitch`; no new grace, no new owner).
 */
function restoreAfter(owner: ApiActor, key: Written, original: boolean): void {
  undo.push({
    label: `restore ${key}`,
    run: async () => {
      const now = await read(owner, key);
      if (now.value === original) return;
      const back = await withChallenge(owner, write(key, original, now.updatedAt, "cleanup"));
      const status = back.resent?.status ?? back.first.status;
      if (status !== 200) throw new Error(`the write back answered ${status}`);
    },
  });
}

test.afterEach(async () => {
  for (const failed of await runUndos(undo)) {
    test.info().annotations.push({ type: "cleanup-error", description: failed });
  }
});

test.afterAll(() => {
  expect(requested.length, "the request tap saw the file's API calls").toBeGreaterThan(0);
  expect(
    requested.filter((r) => r.includes(LIVE_GATE)),
    "no request names the live gate",
  ).toEqual([]);
});

test("E42-Q02 AD-S05-01 (API half) an all-roles flag write reaches the owner, a manager and a viewer within 10 s of its record; an owner-only one reaches the owner alone @regression", async ({
  lane,
}, testInfo) => {
  await lane.refreshes(3); // the three page loads
  const owner = await openApiActor(lane, "owner");
  const log = answers(owner.page);
  const watcher = await connected(lane, "owner");
  const manager = await connected(lane, "manager");
  const viewer = await connected(lane, "viewer");
  const others = [manager, viewer];
  const from = new Map([watcher, manager, viewer].map((a) => [a, a.tap.frames.length] as const));
  const since = (a: PageActor): number => from.get(a) ?? 0;

  expect((await elevate(owner, "flags")).status, "the owner's flags step-up").toBe(200);
  const ui = await read(owner, UI_FLAG);
  const kept = await read(owner, OWNER_ONLY);
  const [ui0, kept0] = [bool(ui), bool(kept)];
  restoreAfter(owner, UI_FLAG, ui0);
  restoreAfter(owner, OWNER_ONLY, kept0);

  // The all-roles write: each role's socket gets the changed key, and only it
  const sent = Date.now();
  const v1 = written(await owner.api(write(UI_FLAG, !ui0, ui.updatedAt, "AD-S05-01")), "write 1");
  const changeId = log.last("PUT", flagPath(UI_FLAG)).id;
  const reached = await untilWithin(
    "flag-push-to-every-role",
    SETTLE_MS,
    () => [watcher, ...others].map((a) => flagPushes(a.tap.frames, UI_FLAG, since(a)).at(-1)),
    (pushes) => pushes.every((p) => p?.value === !ui0),
  );
  const runnerMs = Date.now() - sent;

  // Owner-only, there and back: the owner's socket gets both; then the all-roles write back is
  // the barrier: a socket that has it holds every frame queued before it (one queue per socket)
  const v2 = written(
    await owner.api(write(OWNER_ONLY, !kept0, kept.updatedAt, "AD-S05-01")),
    "write 2",
  );
  written(await owner.api(write(OWNER_ONLY, kept0, v2, "AD-S05-01")), "write 3");
  written(await owner.api(write(UI_FLAG, ui0, v1, "AD-S05-01")), "write 4, the barrier");
  await expect
    .poll(() => flagPushes(watcher.tap.frames, OWNER_ONLY, since(watcher)).map((p) => p.value))
    .toEqual([!kept0, kept0]);
  await expect
    .poll(() => others.map((a) => flagPushes(a.tap.frames, UI_FLAG, since(a)).map((p) => p.value)))
    .toEqual([
      [!ui0, ui0],
      [!ui0, ui0],
    ]);
  expect(
    others.map((a) => pushedKeys(a.tap.frames, since(a))),
    "a manager and a viewer never learn an owner-only key (AC-ADM-11)",
  ).toEqual([[UI_FLAG], [UI_FLAG]]);

  // Q-21's 10 s, on the server's stamps: the write-ahead record to the last socket's frame
  const writes = log.all.filter((a) => a.method === "PUT").map((a) => a.id);
  const rows = await slice(lane, "flag-change-records", (all) =>
    writes.every((id) => rowsOf(all, "flags.change", id).length === 2),
  );
  const record = writeAheadRecord(rows, changeId);
  if (record === undefined) throw new Error("the write's flags.change record went");
  const lags = reached.value.map((p) => recordToFrameMs(record, p?.ts ?? Number.NaN));
  judgeTiming(
    testInfo,
    timingRecord({
      case: "AD-S05-01",
      label: "flag-record-to-last-socket-frame",
      budget_ms: FLAG_REACH_MS,
      observed_ms: Math.max(...lags),
      runner_ms: runnerMs,
      basis: "server-frame-ts",
    }),
  );
  // Each write: its write-ahead record and its outcome, both the owner's, all succeeded
  expect(
    writes.map((id) =>
      rowsOf(rows, "flags.change", id).map((r) => [r["outcome"], r["actor"]].join(" ")),
    ),
  ).toEqual(writes.map(() => Array(2).fill(`success ${owner.user.username}`)));
});

test("E42-Q02 AD-S05-02 (API half) with no flags grace a write is challenged and not made until the step-up; an engage passes in the grace; the release needs a fresh code @regression", async ({
  lane,
}) => {
  await lane.refreshes(0); // the API actor presents no refresh
  const owner = await openApiActor(lane, "owner");
  const log = answers(owner.page);
  const oneClick = await read(owner, "trading.one_click");
  const kill = await read(owner, "killswitch.order_entry");
  const one0 = bool(oneClick);
  restoreAfter(owner, "trading.one_click", one0);
  restoreAfter(owner, "killswitch.order_entry", bool(kill));
  expect(bool(kill), "the order-entry kill switch starts released").toBe(false);

  // No grace: refused for a step-up, and nothing is written
  const change = write("trading.one_click", !one0, oneClick.updatedAt, "AD-S05-02");
  const refused = await owner.api(change);
  expect({ status: refused.status, code: refused.code, body: refused.body }).toMatchObject({
    status: 403,
    code: "step_up_required",
    body: { action_class: "flags" },
  });
  const refusedId = log.last("PUT", flagPath("trading.one_click")).id;
  expect((await read(owner, "trading.one_click")).value, "nothing was written").toBe(one0);
  expect((await elevate(owner, "flags")).status, "the owner's flags step-up").toBe(200);
  const v1 = written(await owner.api(change), "the one re-send");
  const resentId = log.last("PUT", flagPath("trading.one_click")).id;

  // The engage needs only `flags`: inside the grace, no new challenge
  const engage = write("killswitch.order_entry", true, kill.updatedAt, "AD-S05-02");
  const engaged = written(await owner.api(engage), "the engage");
  const engageId = log.last("PUT", flagPath("killswitch.order_entry")).id;

  // The release is `killswitch`, no grace: challenged, answered with a fresh code, re-sent once
  const release = write("killswitch.order_entry", false, engaged, "AD-S05-02");
  const released = await withChallenge(owner, release);
  expect({
    first: [released.first.status, released.first.code],
    cls: released.first.body,
    stepUp: released.stepUp?.status,
    resent: released.resent?.status,
  }).toMatchObject({
    first: [403, "step_up_required"],
    cls: { action_class: "killswitch" },
    stepUp: 200,
    resent: 200,
  });
  const releases = log.all.filter(
    (a) => a.method === "PUT" && a.path === flagPath("killswitch.order_entry"),
  );
  const [challengedId, releaseId] = releases.slice(-2).map((a) => a.id);
  if (challengedId === undefined || releaseId === undefined) throw new Error("two releases sent");
  expect((await read(owner, "killswitch.order_entry")).value, "released").toBe(false);

  // QA AD-S05-02's records: no flags.change for either challenged request; one write each else
  const made = [resentId, engageId, releaseId];
  const rows = await slice(lane, "safety-flag-records", (all) =>
    made.every((id) => rowsOf(all, "flags.change", id).length === 2),
  );
  expect(
    [refusedId, challengedId, ...made].map((id) => rowsOf(rows, "flags.change", id).length),
  ).toEqual([0, 0, 2, 2, 2]);
  const trail = stepUpTrail(rows);
  expect(trail.filter((t) => t.startsWith("auth.step_up_required:"))).toEqual([
    "auth.step_up_required:flags",
    "auth.step_up_required:killswitch",
  ]);
  expect(
    inOrder(trail, [
      "auth.step_up_required:flags",
      "auth.step_up_granted:flags",
      "auth.step_up_grace_used:flags",
      "auth.step_up_required:killswitch",
      "auth.step_up_granted:killswitch",
    ]),
    `the step-up records in order (${trail.join(", ")})`,
  ).toBe(true);

  // Leave the flag as it was read; the grace may have lapsed, so a challenge is answered
  const back = await withChallenge(owner, write("trading.one_click", one0, v1, "AD-S05-02"));
  expect(back.resent?.status ?? back.first.status, "the flag written back").toBe(200);
});

test("E42-Q02 AD-S05-N01 a flag written twice inside a second: two records in order, and every client ends on the second value within 10 s @regression", async ({
  lane,
}, testInfo) => {
  await lane.refreshes(2); // the two page loads
  const owner = await openApiActor(lane, "owner");
  const log = answers(owner.page);
  const clients = [await connected(lane, "manager"), await connected(lane, "viewer")];
  const from = new Map(clients.map((a) => [a, a.tap.frames.length] as const));
  const since = (a: PageActor): number => from.get(a) ?? 0;
  expect((await elevate(owner, "flags")).status, "the owner's flags step-up").toBe(200);
  const flag = await read(owner, "rules.form_editor");
  const v0 = bool(flag);
  restoreAfter(owner, "rules.form_editor", v0);

  // The second write names the first's `updated_at`; it ends on the value read, so it restores it
  const sent = Date.now();
  const v1 = written(
    await owner.api(write("rules.form_editor", !v0, flag.updatedAt, "AD-S05-N01")),
    "the first write",
  );
  written(await owner.api(write("rules.form_editor", v0, v1, "AD-S05-N01")), "the second write");
  const [firstId, secondId] = log.all.filter((a) => a.method === "PUT").map((a) => a.id);
  if (firstId === undefined || secondId === undefined) throw new Error("two writes sent");
  const ended = await untilWithin(
    "every-client-on-the-second-value",
    SETTLE_MS,
    () => clients.map((a) => flagPushes(a.tap.frames, "rules.form_editor", since(a)).at(-1)),
    (last) => last.every((p) => p?.value === v0),
  );
  const runnerMs = Date.now() - sent;

  const rows = await slice(lane, "two-flag-change-records", (all) =>
    [firstId, secondId].every((id) => rowsOf(all, "flags.change", id).length === 2),
  );
  // Two writes, in order: each one's records before the next one's
  const order = rows
    .filter((r) => r["action"] === "flags.change")
    .map((r) => r["request_id"])
    .filter((id) => id === firstId || id === secondId);
  expect(order).toEqual([firstId, firstId, secondId, secondId]);
  const [first, second] = [writeAheadRecord(rows, firstId), writeAheadRecord(rows, secondId)];
  if (first === undefined || second === undefined) throw new Error("a write's record went");
  // The gap between the two write-ahead records is trend data (its own record file): sequential
  // round trips on a loaded runner may pass a second with no product defect, so the gate is the
  // order above. `judgeTiming` keeps the record and its annotation before it judges; a miss is
  // annotated, not failed.
  const gap = timingRecord({
    case: "AD-S05-N01-GAP",
    label: "two-writes-record-gap",
    budget_ms: 1_000,
    observed_ms: recordToFrameMs(first, Date.parse(String(second["event_ts"]))),
    runner_ms: runnerMs,
    basis: "server-record",
  });
  try {
    judgeTiming(testInfo, gap);
  } catch {
    testInfo.annotations.push({
      type: "trend",
      description: "AD-S05-N01-GAP: the two write-ahead records were over 1000 ms apart",
    });
  }
  const lags = ended.value.map((p) => recordToFrameMs(second, p?.ts ?? Number.NaN));
  judgeTiming(
    testInfo,
    timingRecord({
      case: "AD-S05-N01",
      label: "second-record-to-last-client-frame",
      budget_ms: FLAG_REACH_MS,
      observed_ms: Math.max(...lags),
      runner_ms: runnerMs,
      basis: "server-frame-ts",
    }),
  );
});

test("E42-Q02 AD-S05-05 (API half) and AD-X-03 (notice half) maintenance on is a flags write, off a killswitch release; a manager gets each notice, its role's fields only, within 2 s @regression", async ({
  lane,
}, testInfo) => {
  await lane.refreshes(1); // the manager's page load
  const owner = await openApiActor(lane, "owner");
  const log = answers(owner.page);
  const manager = await connected(lane, "manager");
  const from = manager.tap.frames.length;
  expect((await elevate(owner, "flags")).status, "the owner's flags step-up").toBe(200);
  const mode = await read(owner, "maintenance.mode");
  restoreAfter(owner, "maintenance.mode", bool(mode));
  expect(bool(mode), "maintenance starts off").toBe(false);

  // On: rung 2, `flags`, inside the grace
  const sent = Date.now();
  const on = written(
    await owner.api(write("maintenance.mode", true, mode.updatedAt, "AD-S05-05")),
    "maintenance on",
  );
  const onId = log.last("PUT", flagPath("maintenance.mode")).id;
  const enabled = await untilWithin(
    "maintenance-notice-to-manager",
    SETTLE_MS,
    () => noticePushes(manager.tap.frames, "maintenance.enabled", from),
    (pushes) => pushes.length > 0,
  );
  const runnerMs = Date.now() - sent;
  // A manager's notice is `kind`, `severity`, `message` and `reason` alone (23 §15.9, AC-ADM-35)
  expect(enabled.value.map((p) => [p.severity, p.members])).toEqual([
    ["warning", ["kind", "message", "reason", "severity"]],
  ]);

  // Off: rung 4, `killswitch`, no grace: a fresh code even inside the `flags` grace
  const off = await withChallenge(owner, write("maintenance.mode", false, on, "AD-S05-05"));
  expect({
    first: [off.first.status, off.first.code],
    cls: off.first.body,
    stepUp: off.stepUp?.status,
    resent: off.resent?.status,
  }).toMatchObject({
    first: [403, "step_up_required"],
    cls: { action_class: "killswitch" },
    stepUp: 200,
    resent: 200,
  });
  const [challengedId, offId] = log.all
    .filter((a) => a.method === "PUT")
    .slice(-2)
    .map((a) => a.id);
  if (challengedId === undefined || offId === undefined) throw new Error("two offs sent");
  await expect
    .poll(() =>
      noticePushes(manager.tap.frames, "maintenance.disabled", from).map((p) => [
        p.severity,
        p.members,
      ]),
    )
    .toEqual([["info", ["kind", "message", "reason", "severity"]]]);

  // The records: a write and `maintenance.enabled`, then a write and `maintenance.disabled`;
  // nothing written for the challenged request; one challenge in all, the release's
  const action = (r: AuditRow): unknown => r["action"];
  const rows = await slice(
    lane,
    "maintenance-records",
    (all) =>
      [onId, offId].every((id) => rowsOf(all, "flags.change", id).length === 2) &&
      all.some((r) => action(r) === "maintenance.disabled"),
  );
  expect([onId, challengedId, offId].map((id) => rowsOf(rows, "flags.change", id).length)).toEqual([
    2, 0, 2,
  ]);
  expect(
    rows.map(action).filter((a) => a === "maintenance.enabled" || a === "maintenance.disabled"),
  ).toEqual(["maintenance.enabled", "maintenance.disabled"]);
  expect(stepUpTrail(rows).filter((t) => t.startsWith("auth.step_up_required:"))).toEqual([
    "auth.step_up_required:killswitch",
  ]);

  // The 2 s from the write's write-ahead record: `maintenance.enabled` is written after the push
  // (writes.py: commit, push, outcome, then the maintenance record), so it cannot start the bound
  const record = writeAheadRecord(rows, onId);
  const notice = enabled.value[0];
  if (record === undefined || notice === undefined) throw new Error("the on write's record went");
  judgeTiming(
    testInfo,
    timingRecord({
      case: "AD-X-03",
      label: "maintenance-record-to-manager-notice",
      budget_ms: NOTICE_MS,
      observed_ms: recordToFrameMs(record, notice.ts),
      runner_ms: runnerMs,
      basis: "server-frame-ts",
    }),
  );
});
