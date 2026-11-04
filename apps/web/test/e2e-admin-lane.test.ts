// @vitest-environment node
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, matchesGlob, relative, resolve } from "node:path";
import type { generated } from "@candleviewer/protocol";
import type { TestInfo } from "@playwright/test";
import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import adminConfig from "../e2e/playwright.admin-stack.config";
import stubConfig from "../e2e/playwright.config";
import realConfig from "../e2e/playwright.real.config";
import {
  BRIDGE,
  codeMaker,
  openBridge,
  type Bridge,
  type ElevateClass,
  type GraceClass,
} from "../e2e/support/real/adminWorld";
import { claimFrom, parseUsers, roleClaims, type RealStack } from "../e2e/support/real/stack";
import { judgeTiming, serverDeltaMs, timingRecord, untilWithin } from "../e2e/support/real/timing";
import { serverClock } from "../e2e/support/serverClock";
import { OTP_SEED, totp } from "../e2e/support/totp";

/**
 * E42-Q02 (#1215) part 1: the admin lane's wiring, pinned where a slip would not fail a spec, as
 * `e2e-real-lane.test.ts` pins the auth lane's: the config and its suffix, the role-aware users
 * file, the timings, the API actor's page side, the refreshes the specs declare, and that no admin
 * spec or actor logs, attaches or prints a credential.
 */
const WEB = resolve(import.meta.dirname, "..");
const E2E = join(WEB, "e2e");
const files = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
const stackSpecs = (): string[] => files(E2E).filter((f) => f.endsWith(".stack.ts"));

describe("the admin lane's Playwright config", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("runs only *.stack.ts, and no lane matches another's specs", () => {
    expect(adminConfig.testMatch).toBe("**/*.stack.ts");
    expect(stubConfig.testMatch).toBeUndefined(); // Playwright's default, the third glob below
    const lanes = [
      adminConfig.testMatch,
      realConfig.testMatch,
      "**/*.@(spec|test).?(c|m)[jt]s?(x)",
    ];
    // relative to apps/web: `**` skips a dot folder, and a checkout may sit under one
    const samples = ["e2e/admin/a.stack.ts", "e2e/auth/a.real.ts", "e2e/admin/a.spec.ts"];
    const matches = (file: string): boolean[] => lanes.map((g) => matchesGlob(file, String(g)));
    expect(samples.map(matches)).toEqual([
      [true, false, false],
      [false, true, false],
      [false, false, true],
    ]);
    const tree = files(E2E).map((f) => relative(WEB, f));
    expect(tree.filter((f) => matches(f).some(Boolean)).length).toBeGreaterThan(0);
    expect(tree.filter((f) => matches(f).filter(Boolean).length > 1)).toEqual([]);
  });

  it("keeps no trace, video or screenshot, retries nothing and forbids .only", () => {
    expect(adminConfig.use).toMatchObject({ trace: "off", video: "off", screenshot: "off" });
    expect([adminConfig.retries, adminConfig.forbidOnly]).toEqual([0, true]);
    expect(adminConfig.outputDir).toBe("../test-results/admin-stack");
  });

  it("runs one test at a time in one project, and @flaky only in the quarantine run", async () => {
    const shape = (config: typeof adminConfig) =>
      (config.projects ?? []).map((p) => [p.name, String(p.grep), String(p.grepInvert)]);
    expect([adminConfig.workers, adminConfig.fullyParallel]).toEqual([1, false]);
    expect(shape(adminConfig)).toEqual([["admin", "undefined", "/@flaky/u"]]);
    vi.stubEnv("CV_E2E_QUARANTINE", "1");
    vi.resetModules();
    const quarantine = (await import("../e2e/playwright.admin-stack.config")).default;
    expect(shape(quarantine)).toEqual([["flaky-nightly", "/@flaky/u", "undefined"]]);
  });

  it.each([
    ["a non-numeric value", "abc"],
    ["a value with a shell metacharacter", "4173; id"],
    ["an empty value", ""],
    ["zero", "0"],
    ["a port above 65535", "65536"],
    ["six digits", "123456"],
    ["a signed value", "-1"],
  ])("refuses a preview port that is %s, before any command is built", async (_named, port) => {
    vi.stubEnv("CV_E2E_REAL_PREVIEW_PORT", port);
    vi.resetModules();
    await expect(import("../e2e/playwright.admin-stack.config")).rejects.toThrow(
      /CV_E2E_REAL_PREVIEW_PORT is a port number/u,
    );
  });

  it.each(["1", "4173", "65535"])("takes %s as the preview port", async (port) => {
    vi.stubEnv("CV_E2E_REAL_PREVIEW_PORT", port);
    vi.resetModules();
    const config = (await import("../e2e/playwright.admin-stack.config")).default;
    const server = config.webServer;
    if (server === undefined || Array.isArray(server)) throw new Error("one webServer");
    expect(server.command).toMatch(new RegExp(` --port ${port} --host 127\\.0\\.0\\.1$`, "u"));
  });

  it("starts its own preview of dist/ with the loopback proxy config, never another process's", () => {
    const server = adminConfig.webServer;
    if (server === undefined || Array.isArray(server)) throw new Error("one webServer");
    expect(server.command).toMatch(/^npx vite preview -c e2e\/vite\.real\.config\.ts /u);
    expect(server.reuseExistingServer).toBe(false);
  });
});

describe("the users file's roles", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "cv-admin-lane-"));
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));
  const file = (rows: readonly Record<string, unknown>[]): string =>
    JSON.stringify(rows.map((row, i) => ({ totp_file: `/run/cv/${i}.totp`, ...row })));

  it("reads a role, and an entry without one as E09's lane writes it", () => {
    expect(parseUsers(file([{ username: "a" }, { username: "b", role: "manager" }]))).toEqual([
      { username: "a", totpFile: "/run/cv/0.totp" },
      { username: "b", totpFile: "/run/cv/1.totp", role: "manager" },
    ]);
  });

  it.each(["admin", "Owner", 7])("refuses the role %s, which the seeder does not make", (role) => {
    expect(() => parseUsers(file([{ username: "a", role }]))).toThrow(
      /role is not one of owner, manager, viewer/u,
    );
  });

  it("claims each role from a pool of its own, the owners where E09's lane claims", () => {
    const roles = ["owner", "manager", "owner", "viewer"];
    const users = parseUsers(file(roles.map((role, i) => ({ username: `u${i}`, role }))));
    const claims = join(dir, "claims");
    const pick = (role: "owner" | "manager" | "viewer"): string => {
      const pool = roleClaims(users, role, claims);
      return claimFrom(pool.users, pool.claims).username;
    };
    expect([pick("manager"), pick("owner"), pick("owner"), pick("viewer")]).toEqual([
      "u1",
      "u0",
      "u2",
      "u3",
    ]);
    expect(readdirSync(dir).sort()).toEqual(["claims", "claims-manager", "claims-viewer"]);
    expect(() => pick("manager")).toThrow(/all 1 fixture users are claimed/u);
    expect(() => roleClaims(parseUsers(file([{ username: "a" }])), "viewer", claims)).toThrow(
      /the users file has no viewer/u,
    );
  });
});

describe("the admin lane's timings", () => {
  it("reads to the first value that holds, and says how long and how many reads it took", async () => {
    let reads = 0;
    let at = 0;
    const seen = await untilWithin(
      "three-reads",
      5_000,
      () => ++reads,
      (n) => n >= 3,
      {
        intervalMs: 1,
        now: () => (at += 40),
      },
    );
    expect({ value: seen.value, polls: seen.polls }).toEqual({ value: 3, polls: 3 });
    expect(seen.observedMs).toBeGreaterThan(0);
  });

  it("fails naming the label, the deadline and the last read as its summariser shows it", async () => {
    const read = (): { status: number } => ({ status: 200 });
    await expect(
      untilWithin("next-request-refused", 50, read, (s) => s.status === 401, {
        intervalMs: 5,
        show: (s) => `status ${s.status}`,
      }),
    ).rejects.toThrow(
      /^next-request-refused: not within 50 ms, after \d+ reads \(last: status 200\)$/u,
    );
  });

  it("names only the last read's kind by default, never its body", async () => {
    const read = (): { actor: string } => ({ actor: "fixture-owner-1" });
    const failed = untilWithin("audit-row", 50, read, () => false, { intervalMs: 5 });
    await expect(failed).rejects.toThrow(/\(last: an object, not shown\)$/u);
    await expect(failed).rejects.not.toThrow(/fixture-owner-1/u);
  });

  it("keeps the record and a measured note, then judges the budget", () => {
    const dir = mkdtempSync(join(tmpdir(), "cv-admin-timings-"));
    try {
      const info: Pick<TestInfo, "annotations"> = { annotations: [] };
      const env = { GITHUB_SHA: "0123abc", GITHUB_RUN_ID: "42" };
      const fields = { case: "AD-X-01", label: "revoked", budget_ms: 5_000, runner_ms: 5_200 };
      const late = timingRecord({ ...fields, observed_ms: 5_001, basis: "server-record" }, env);
      expect(() => judgeTiming(info, late, dir)).toThrow(/AD-X-01 revoked \(server-record\)/u);
      expect(JSON.parse(readFileSync(join(dir, "AD-X-01.json"), "utf8"))).toEqual({
        ...fields,
        observed_ms: 5_001,
        basis: "server-record",
        build_sha: "0123abc",
        run_id: "42",
      });
      expect(info.annotations).toEqual([
        {
          type: "measured",
          description: "AD-X-01 revoked: 5001 ms of 5000 ms (server-record); runner 5200 ms",
        },
      ]);
      expect(() => judgeTiming(info, { ...late, observed_ms: 5_000 }, dir)).not.toThrow();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it.each([
    ["an address", "owner@example.test"],
    ["whitespace", "the manager's next request"],
    ["an empty string", ""],
    ["a leading separator", "-revoked"],
    ["capitals", "Revoked"],
    ["a long string", "a".repeat(65)],
    ["a JWT-shaped value", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"],
  ])("refuses a label that is %s, at every entry point", async (_named, label) => {
    const refused = /a timing's label is a short slug/u;
    await expect(
      untilWithin(
        label,
        50,
        () => 1,
        () => true,
      ),
    ).rejects.toThrow(refused);
    const fields = { case: "AD-X-01", budget_ms: 1, observed_ms: 0, runner_ms: 0 } as const;
    expect(() => timingRecord({ ...fields, label, basis: "runner" }, {})).toThrow(refused);
    const dir = mkdtempSync(join(tmpdir(), "cv-admin-timings-"));
    try {
      const record = {
        ...fields,
        label,
        basis: "runner",
        build_sha: "local",
        run_id: "local",
      } as const;
      const info: Pick<TestInfo, "annotations"> = { annotations: [] };
      expect(() => judgeTiming(info, record, dir)).toThrow(refused);
      expect([readdirSync(dir), info.annotations]).toEqual([[], []]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("takes a slug of the longest length", async () => {
    const label = `a${"b".repeat(63)}`;
    expect(
      (
        await untilWithin(
          label,
          50,
          () => 1,
          () => true,
        )
      ).value,
    ).toBe(1);
  });

  it("stamps a local run as local, and names a case only by its id", () => {
    const fields = {
      label: "x",
      budget_ms: 1,
      observed_ms: 0,
      runner_ms: 0,
      basis: "runner",
    } as const;
    expect(timingRecord({ ...fields, case: "AD-X-01" }, {})).toMatchObject({
      build_sha: "local",
      run_id: "local",
    });
    expect(() => timingRecord({ ...fields, case: "../x" }, {})).toThrow(/case id/u);
  });

  it("measures between two audit rows on the server's clock", () => {
    const from = { event_ts: "2026-11-03T08:00:00.250000+00:00" };
    expect(serverDeltaMs(from, { event_ts: "2026-11-03T08:00:04.750123+00:00" })).toBe(4_500);
    expect(() => serverDeltaMs({}, from)).toThrow(/event_ts/u);
  });
});

describe("the API actor's page side", () => {
  let page: Record<string, unknown>;
  let sent: { url: string; method: string; headers: Record<string, string>; body: unknown }[];
  let answers: Response[];
  beforeEach(() => {
    page = {};
    sent = [];
    answers = [];
    vi.stubGlobal("window", page);
    vi.stubGlobal("document", { cookie: "theme=dark; __Host-cv_csrf=mark-1" });
    vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
      const body = typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : null;
      const headers = { ...(init.headers as Record<string, string>) };
      sent.push({ url, method: String(init.method), headers, body });
      const next = answers.shift();
      if (next === undefined) throw new Error("no answer queued");
      return next;
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  const answer = (status: number, body?: unknown, headers: Record<string, string> = {}): void =>
    void answers.push(
      new Response(body === undefined ? null : JSON.stringify(body), { status, headers }),
    );
  const open = async (): Promise<Bridge> => {
    answer(200, {
      status: "authenticated",
      tokens: { access_token: "first", token_type: "Bearer" },
    });
    const verified = await openBridge({ name: BRIDGE, handle: "handle-1", code: "123456" });
    expect(verified).toEqual({
      status: 200,
      code: null,
      body: { status: "authenticated" },
      etag: null,
    });
    return page[BRIDGE] as Bridge;
  };

  it("completes MFA, then sends the bearer it issued with the CSRF mark and If-Match", async () => {
    const bridge = await open();
    answer(200, { id: "u1", status: "disabled" }, { etag: 'W/"2"' });
    const call = {
      method: "PATCH",
      path: "/users/u1",
      ifMatch: 'W/"1"',
      body: { status: "x" },
    } as const;
    expect(await bridge.call(call)).toEqual({
      status: 200,
      code: null,
      body: { id: "u1", status: "disabled" },
      etag: 'W/"2"',
    });
    expect(sent.map((s) => [s.method, s.url, s.body])).toEqual([
      [
        "POST",
        "/api/v1/auth/mfa/verify",
        { mfa_token: "handle-1", method: "totp", code: "123456" },
      ],
      ["PATCH", "/api/v1/users/u1", { status: "x" }],
    ]);
    expect(sent[1]?.headers).toMatchObject({
      Authorization: "Bearer first",
      "X-CSRF-Token": "mark-1",
      "If-Match": 'W/"1"',
    });
  });

  it("asks for a grace class by name, then sends the bearer the step-up rotated in", async () => {
    const bridge = await open();
    answer(200, { action_class: "users", single_use: false, tokens: { access_token: "second" } });
    answer(204);
    const up = await bridge.elevate("pw-1", "654321", "users");
    expect(up.body).toEqual({ action_class: "users", single_use: false });
    expect((await bridge.call({ method: "GET", path: "/auth/session" })).body).toBeNull();
    expect(sent[1]?.body).toEqual({ password: "pw-1", code: "654321", action_class: "users" });
    expect(sent[2]?.headers["Authorization"]).toBe("Bearer second");
  });

  it("drops every member named like a credential, at any depth", async () => {
    const bridge = await open();
    const inner = { invite_url: "/invite/x", csrf: "m", refresh_token: null, kept: 1 };
    answer(403, {
      code: "step_up_required",
      challenge_id: "c-1",
      action_class: "users",
      items: [inner],
    });
    expect((await bridge.call({ method: "POST", path: "/users", body: {} })).body).toEqual({
      code: "step_up_required",
      action_class: "users",
      items: [{ kept: 1 }],
    });
  });

  it("answers a challenge with its id, once, then re-sends the request unchanged", async () => {
    const bridge = await open();
    const call = {
      method: "POST",
      path: "/admin/x",
      body: { on: true },
      idempotencyKey: "i-1",
    } as const;
    answer(403, { code: "step_up_required", challenge_id: "c-7", action_class: "killswitch" });
    answer(200, { action_class: "killswitch", tokens: { access_token: "third" } });
    answer(200, { on: true });
    const facts = await bridge.challenged(call, "pw-1", "111111");
    expect([facts.first.status, facts.stepUp?.status, facts.resent?.status]).toEqual([
      403, 200, 200,
    ]);
    expect(sent[2]?.body).toEqual({ password: "pw-1", code: "111111", challenge_id: "c-7" });
    const request = (i: number) => [
      sent[i]?.url,
      sent[i]?.body,
      sent[i]?.headers["Idempotency-Key"],
    ];
    expect(request(3)).toEqual(request(1));
    expect(sent[3]?.headers["Authorization"]).toBe("Bearer third");
  });

  it.each([
    ["no action class", {}],
    ["an action class that is not a string", { action_class: 7 }],
    ["an empty action class", { action_class: "" }],
    ["an action class this suite never answers", { action_class: "sl_loosen" }],
  ])("never answers a challenge with %s", async (_named, extra) => {
    const bridge = await open();
    answer(403, { code: "step_up_required", challenge_id: "c-9", ...extra });
    const facts = await bridge.challenged({ method: "POST", path: "/admin/x" }, "pw-1", "333333");
    expect([facts.first.status, facts.stepUp, facts.resent, sent.length]).toEqual([
      403,
      null,
      null,
      2,
    ]);
  });

  it("drops members named like a key, a signature or a bearer", async () => {
    const bridge = await open();
    answer(200, {
      api_key: "k",
      signature: "s",
      hmac: "h",
      bearer: "b",
      passphrase: "p",
      kek_id: "e",
      dek: "d",
      key: "x",
      key_id: "kept-1",
      monkey: "kept-2",
    });
    expect((await bridge.call({ method: "GET", path: "/admin/overview" })).body).toEqual({
      key_id: "kept-1",
      monkey: "kept-2",
    });
  });

  it("drops a provisioning URI and every member named secret or seed from its facts", async () => {
    const bridge = await open();
    // obvious placeholders, no real enrolment's values
    const FAKE_SECRET = "AAAAAAAAAAAAAAAA";
    const FAKE_SEED = "BBBBBBBBBBBBBBBB";
    const FAKE_URI = `otpauth://totp/Example:nobody?secret=${FAKE_SECRET}&issuer=Example`;
    answer(201, {
      method_id: "m-1",
      otpauth_uri: FAKE_URI,
      OtpAuthUri: FAKE_URI,
      secret: FAKE_SECRET,
      Secret_Base32: FAKE_SECRET,
      totp_secret: FAKE_SECRET,
      seed: FAKE_SEED,
      enrolment: { SEED: FAKE_SEED, backupSeed: FAKE_SEED, list: [{ shared_secret: FAKE_SECRET }] },
    });
    const facts = await bridge.call({ method: "POST", path: "/auth/mfa/enroll", body: {} });
    expect(facts.body).toEqual({ method_id: "m-1", enrolment: { list: [{}] } });
    const written = JSON.stringify(facts);
    for (const literal of ["otpauth", FAKE_SECRET, FAKE_SEED]) {
      expect(written).not.toContain(literal);
    }
  });

  it("types elevate's class as the contract's step-up classes, never live_enablement", () => {
    type Contracted = NonNullable<
      generated.rest.operations["authStepUp"]["requestBody"]["content"]["application/json"]["action_class"]
    >;
    expectTypeOf<ElevateClass>().toEqualTypeOf<Exclude<Contracted, "live_enablement">>();
    expectTypeOf<GraceClass>().toMatchTypeOf<ElevateClass>();
    expectTypeOf<Bridge["elevate"]>().parameter(2).toEqualTypeOf<ElevateClass>();
    expectTypeOf<"live_enablement">().not.toMatchTypeOf<ElevateClass>();
    expectTypeOf<string>().not.toMatchTypeOf<ElevateClass>();
  });

  it("elevates every class the contract defines, each by name", async () => {
    // a Record over the union: a class the contract adds or drops fails tsc here
    const every: Record<ElevateClass, true> = {
      keys: true,
      users: true,
      killswitch: true,
      risk_caps: true,
      recorder: true,
      flags: true,
      audit: true,
      backups: true,
      sl_loosen: true,
      accounts: true,
      recorder_purge: true,
      instruments: true,
    };
    const bridge = await open();
    const classes = Object.keys(every) as ElevateClass[];
    for (const cls of classes) {
      answer(200, { action_class: cls, single_use: false });
      expect((await bridge.elevate("pw-1", "654321", cls)).status).toBe(200);
    }
    expect(sent.slice(1).map((s) => (s.body as { action_class?: unknown }).action_class)).toEqual(
      classes,
    );
  });

  it.each([
    ["live_enablement", "live_enablement"],
    ["a class the contract does not define", "sl_widen"],
    ["an empty class", ""],
    ["a class that is not a string", 7],
  ])("refuses to elevate %s, sending nothing", async (_named, cls) => {
    const bridge = await open();
    const unknownClass = cls as unknown as ElevateClass; // what a caller past the type could send
    await expect(bridge.elevate("pw-1", "654321", unknownClass)).rejects.toThrow(
      /a step-up class the contract defines/u,
    );
    expect(sent).toHaveLength(1); // the MFA verify alone
  });

  it("never answers a live-enablement challenge", async () => {
    const bridge = await open();
    answer(403, { code: "step_up_required", challenge_id: "c-8", action_class: "live_enablement" });
    const facts = await bridge.challenged({ method: "POST", path: "/admin/x" }, "pw-1", "222222");
    expect([facts.first.status, facts.stepUp, facts.resent, sent.length]).toEqual([
      403,
      null,
      null,
      2,
    ]);
  });

  it("is not enumerable on the page, and cannot be replaced", async () => {
    await open();
    expect(Object.keys(page)).toEqual([]);
    expect(() => {
      page[BRIDGE] = {};
    }).toThrow(TypeError);
  });
});

describe("the codes an API actor sends", () => {
  it("never makes two in one 30 s step: a spent step moves the server clock one step on", () => {
    const dir = mkdtempSync(join(tmpdir(), "cv-admin-clock-"));
    try {
      let now = 1_800_000_001_000; // one second into a step
      const clock = serverClock(join(dir, "offset"), { now: () => now });
      const code = codeMaker({ clock } as unknown as RealStack, {
        username: "a",
        seed: () => OTP_SEED,
      });
      expect([code(), code()]).toEqual([totp(OTP_SEED, now), totp(OTP_SEED, now + 30_000)]);
      expect(clock.offsetMicros()).toBe(30_000_000);
      now += 31_000; // the step after: unspent, so the clock stays
      expect(code()).toBe(totp(OTP_SEED, now + 30_000));
      expect(clock.offsetMicros()).toBe(30_000_000);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("the admin specs and their actors", () => {
  const NAMED = /password|seed|cookie|bearer|authorization|csrf/iu;
  const guarded = (): string[] => [
    ...stackSpecs(),
    join(E2E, "support", "real", "adminWorld.ts"),
    join(E2E, "support", "real", "timing.ts"),
  ];

  it("log, attach and print no credential", () => {
    for (const file of guarded()) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(/\bconsole\.|\.attach\(/u);
      const named = [...text.matchAll(/\$\{([^}]*)\}/gu)].map((m) => m[1] ?? "");
      // the one interpolation of a credential: adminWorld.ts's Authorization header
      const allowed = file.endsWith("adminWorld.ts") ? ["bearer"] : [];
      expect(
        named.filter((e) => NAMED.test(e)),
        file,
      ).toEqual(allowed);
      expect(text, file).not.toMatch(
        /\bexpect(?:\.soft)?\(\s*[\w.]*(?:password|seed|bearer|cookie|csrf)\w*(?:\(\))?\s*[,)]/iu,
      );
    }
  });
});
