// @vitest-environment node
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import type { UserConfig } from "vite";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import stubConfig from "../e2e/playwright.config";
import realConfig from "../e2e/playwright.real.config";
import { expires, same, setCookieNames, tamperOneByte } from "../e2e/support/real/cookies";
import {
  REFRESH_BUDGET,
  SLICE_COLUMNS,
  auditSliceSql,
  keepFailureArtefacts,
  paceRefreshes,
  presentsRefresh,
  recordRefresh,
  refreshesInWindow,
} from "../e2e/support/real/failureArtefacts";
import { completeMfa, submitPassword } from "../e2e/support/real/signIn";
import { claimFrom, parseUsers } from "../e2e/support/real/stack";
import { tapWebSocket } from "../e2e/support/real/wsTap";

/**
 * E09-Q02 (#293) PR 2 (#2490): the real lane's wiring, pinned where a slip would not fail a spec.
 * The two lanes never run each other's specs; the real lane keeps no trace, video or screenshot
 * (they would hold real session values in files the upload's secret check cannot read); the
 * clock-moving specs run alone; the proxy is loopback-only; the helpers never hand out a value.
 */
describe("the real lane's Playwright config", () => {
  it("runs only *.real.ts, which the stub lane's default *.spec.ts pattern never matches", () => {
    expect(realConfig.testMatch).toBe("**/*.real.ts");
    expect(stubConfig.testMatch).toBeUndefined();
  });

  it("keeps no trace, video or screenshot and retries nothing", () => {
    expect(realConfig.use).toMatchObject({ trace: "off", video: "off", screenshot: "off" });
    expect(realConfig.retries).toBe(0);
    expect(realConfig.forbidOnly).toBe(true);
  });

  it("runs sign-in specs on two workers and the @clock specs alone, after them", () => {
    const projects = (realConfig.projects ?? []).map((p) => ({
      name: p.name,
      workers: p.workers,
      grep: String(p.grep),
      grepInvert: String(p.grepInvert),
      dependencies: p.dependencies,
    }));
    expect(projects).toEqual([
      {
        name: "real",
        workers: 2,
        grep: "undefined",
        grepInvert: "/@clock/u",
        dependencies: undefined,
      },
      {
        name: "real-clock",
        workers: 1,
        grep: "/@clock/u",
        grepInvert: "undefined",
        dependencies: ["real"],
      },
    ]);
  });

  it("starts its own preview of dist/ with the proxy config, never another process's", () => {
    const server = realConfig.webServer;
    if (server === undefined || Array.isArray(server)) throw new Error("one webServer");
    expect(server.command).toMatch(/^npx vite preview -c e2e\/vite\.real\.config\.ts /u);
    expect(server.reuseExistingServer).toBe(false);
  });
});

describe("vite.real.config.ts", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("proxies /api/v1 and its WebSocket to the API with the prefix stripped", async () => {
    vi.stubEnv("CV_E2E_REAL_API", "http://127.0.0.1:15800");
    // `mergeConfig` types its result as a plain record: read it as the config it is
    const config = (await import("../e2e/vite.real.config")).default as UserConfig;
    const proxy = config.preview?.proxy?.["/api/v1"];
    if (proxy === undefined || typeof proxy === "string") throw new Error("an options proxy");
    expect(proxy.target).toBe("http://127.0.0.1:15800");
    expect(proxy.ws).toBe(true);
    expect(proxy.rewrite?.("/api/v1/auth/login")).toBe("/auth/login");
    expect(proxy.rewrite?.("/api/v1/ws")).toBe("/ws");
    expect(proxy.rewrite?.("/api/v1")).toBe("/");
    expect(proxy.rewrite?.("/api/v10/x")).toBe("/api/v10/x");
    expect(config.preview?.strictPort).toBe(true);
  });

  it.each(["https://127.0.0.1:8000", "http://10.0.0.5:8000", "http://api.example.test:8000"])(
    "refuses %s: the API is a loopback http origin",
    async (api) => {
      vi.stubEnv("CV_E2E_REAL_API", api);
      await expect(import("../e2e/vite.real.config")).rejects.toThrow(/loopback origin/u);
    },
  );
});

describe("the fixture users", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "cv-real-lane-"));
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it("reads the users file the lane writes", () => {
    const text = JSON.stringify([{ username: "e2e-1a2b3c4d-1", totp_file: "/run/cv/e2e-1.totp" }]);
    expect(parseUsers(text)).toEqual([
      { username: "e2e-1a2b3c4d-1", totpFile: "/run/cv/e2e-1.totp" },
    ]);
  });

  it.each([
    ["an empty list", "[]", /non-empty JSON array/u],
    ["a name outside the grammar", '[{"username":"Ann O\'Neil","totp_file":"/x"}]', /username/u],
    ["a relative seed path", '[{"username":"ann","totp_file":"x.totp"}]', /absolute/u],
  ])("refuses %s", (_what, text, message) => {
    expect(() => parseUsers(text)).toThrow(message);
  });

  it("gives each claim a user no earlier claim got, and refuses once all are claimed", () => {
    const claims = join(dir, "claims");
    expect([claimFrom(["a", "b"], claims), claimFrom(["a", "b"], claims)]).toEqual(["a", "b"]);
    expect(readdirSync(claims).sort()).toEqual(["0", "1"]);
    expect(() => claimFrom(["a", "b"], claims)).toThrow(/all 2 fixture users are claimed/u);
    expect(existsSync(join(claims, "2"))).toBe(false);
  });
});

describe("the cookie helpers", () => {
  const headers = [
    { name: "content-type", value: "application/json" },
    {
      name: "set-cookie",
      value:
        'cv_refresh=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Max-Age=0; Path=/api/v1/auth; SameSite=strict; Secure\n__Host-cv_csrf=x; Max-Age=2592000; Path=/; SameSite=strict; Secure',
    },
  ];

  it("names what Set-Cookie sets, and tells an expiry from a set", () => {
    expect(setCookieNames(headers)).toEqual(["cv_refresh", "__Host-cv_csrf"]);
    expect(expires(headers, "cv_refresh")).toBe(true);
    expect(expires(headers, "__Host-cv_csrf")).toBe(false);
    expect(expires(headers, "cv_session")).toBe(false);
  });

  it("tampers exactly one character, and compares without handing a value out", () => {
    for (const value of ["abcdef0123456789", "AAAA", "x"]) {
      const tampered = tamperOneByte(value);
      expect(tampered).toHaveLength(value.length);
      expect([...tampered].filter((c, i) => c !== value[i])).toHaveLength(1);
    }
    expect(same("a", "a")).toBe(true);
    expect(same("a", "b")).toBe(false);
    expect(same(undefined, undefined)).toBe(false);
  });
});

describe("the audit slice", () => {
  const since = new Date("2026-10-30T16:00:00.000Z");
  const id = "18bc2887-37b0-42e9-9c6a-7a01419e5ac4";

  it("reads the test's users and correlation ids since it began, no state columns", () => {
    const sql = auditSliceSql(since, ["e2e-1a2b3c4d-1"], [id]);
    expect(sql).toContain("a.event_ts >= '2026-10-30T16:00:00.000Z'::timestamptz");
    expect(sql).toContain("ARRAY['e2e-1a2b3c4d-1']::text[]");
    expect(sql).toContain(`ARRAY['${id}']::uuid[]`);
    expect(sql).not.toMatch(/before_state|after_state|actor_ip/u);
    expect(auditSliceSql(since, [], [])).toContain("ARRAY[]::uuid[]");
  });

  it.each([
    ["a quote in a name", ["x' OR '1'='1"], []],
    ["a name outside the grammar", ["Ann"], []],
    ["an id that is not a UUID", [], ["1; DROP TABLE users"]],
  ])("refuses %s before building any SQL", (_what, users, ids) => {
    expect(() => auditSliceSql(since, users, ids)).toThrow();
  });

  it("selects exactly the columns a row is checked against", () => {
    const sql = auditSliceSql(since, [], []);
    const select = sql.slice(sql.indexOf("SELECT a."), sql.indexOf(" FROM audit_log"));
    const names = [...select.matchAll(/(?:a\.(\w+)|AS (\w+))(?=,|$)/gu)].map((m) => m[1] ?? m[2]);
    expect(names).toEqual([...SLICE_COLUMNS]);
  });
});

// #5103's code look m7: the failure branch, with its reader and test info stood in for.
describe("the failure artefacts", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "cv-real-artefacts-"));
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  const id = "18bc2887-37b0-42e9-9c6a-7a01419e5ac4";
  const failed = {
    since: new Date("2026-10-30T16:00:00.000Z"),
    users: ["e2e-1a2b3c4d-1"],
    seen: [
      {
        at: "2026-10-30T16:00:01.000Z",
        method: "GET",
        path: "/me",
        status: 200,
        correlationId: id,
      },
    ],
  };
  const row = Object.fromEntries(
    SLICE_COLUMNS.map((c) => [c, c === "action" ? "auth.login" : null]),
  );
  const settle = { timeout: 200, intervals: [5] };
  const sink = () => {
    const attached: string[] = [];
    const outputPath = (name: string): string => join(dir, name);
    const attach = async (name: string): Promise<void> => void attached.push(name);
    return { attached, outputPath, attach };
  };
  const slice = (): Record<string, unknown> =>
    JSON.parse(readFileSync(join(dir, "audit-log-slice.json"), "utf8")) as Record<string, unknown>;

  it("keeps the correlation ids, then the slice once two reads agree", async () => {
    const info = sink();
    const reads: string[] = [];
    const read = async (sql: string): Promise<unknown[]> => {
      reads.push(sql);
      return [row];
    };
    await keepFailureArtefacts(info, failed, read, settle);
    expect(info.attached).toEqual(["correlation-ids.json", "audit-log-slice.json"]);
    expect(slice()).toMatchObject({ note: "settled", rows: [row] });
    expect(reads.length).toBeGreaterThanOrEqual(2);
    expect(reads[0]).toContain(`ARRAY['${id}']::uuid[]`);
  });

  it("keeps an empty slice with a note when no row lands in time", async () => {
    await keepFailureArtefacts(sink(), failed, async () => [], settle);
    expect(slice()).toMatchObject({ rows: [] });
    expect(String(slice()["note"])).toMatch(/^not settled: /u);
  });

  it("fails loudly when a renamed column fails the query, once, after keeping what it has", async () => {
    const info = sink();
    let reads = 0;
    const psql = Object.assign(new Error("Command failed: docker compose exec -T postgres psql"), {
      stderr: "ERROR:  column a.reason does not exist\nLINE 1: SELECT a.id",
    });
    const read = async (): Promise<unknown[]> => {
      reads += 1;
      throw psql;
    };
    await expect(keepFailureArtefacts(info, failed, read, settle)).rejects.toThrow(
      "the audit slice could not be read: ERROR:  column a.reason does not exist",
    );
    expect(reads).toBe(1); // a query that failed is not read again
    expect(info.attached).toEqual(["correlation-ids.json", "audit-log-slice.json"]);
    expect(slice()).toMatchObject({ note: "read failed: ERROR:  column a.reason does not exist" });
  });

  it("fails loudly on a row whose columns are not the slice's, a renamed one", async () => {
    const { reason, ...rest } = row;
    const read = async (): Promise<unknown[]> => [{ ...rest, reason_code: reason }];
    await expect(keepFailureArtefacts(sink(), failed, read, settle)).rejects.toThrow(
      /could not be read: audit slice row 0 has the columns \[.*reason_code/u,
    );
  });
});

// #5103's code look m6: every request comes from the proxy's 127.0.0.1: the run shares one budget.
describe("the refresh ledger", () => {
  let ledger: string;
  beforeEach(() => {
    ledger = join(mkdtempSync(join(tmpdir(), "cv-real-ledger-")), "refresh-ledger");
  });
  afterEach(() => rmSync(join(ledger, ".."), { recursive: true, force: true }));
  const timing = (): { timeout: number; setTimeout: (ms: number) => void } => {
    const info = { timeout: 60_000, setTimeout: (ms: number) => void (info.timeout = ms) };
    return info;
  };

  it("counts what the server may still count: the last minute and a second of slack", () => {
    expect(refreshesInWindow(ledger, 100_000)).toBe(0); // no ledger yet
    for (const at of [10_000, 38_999, 39_000, 99_000]) recordRefresh(ledger, at);
    expect(refreshesInWindow(ledger, 100_000)).toBe(2);
  });

  it("knows a cookie-presenting refresh by the cookie's name", () => {
    expect(presentsRefresh("a=1; cv_refresh=xyz; __Host-cv_csrf=q")).toBe(true);
    expect(presentsRefresh("__Host-cv_csrf=q; cv_refresh_x=1")).toBe(false);
    expect(presentsRefresh(undefined)).toBe(false);
  });

  it("waits, on top of the test's own timeout, until the window has room under the budget", async () => {
    for (let i = 0; i < REFRESH_BUDGET - 1; i += 1) recordRefresh(ledger, 1_000);
    let now = 50_000; // the window holds 7: no room for 2 more under 8 until they leave it
    const info = timing();
    await paceRefreshes(ledger, 2, info, { now: () => (now += 5_000), intervalMs: 1 });
    expect(now).toBeGreaterThanOrEqual(62_001); // 1_000 + the window + the slack
    expect(info.timeout).toBe(135_000);
  });

  it("waits for nothing when none are declared, and refuses more than the budget", async () => {
    const info = timing();
    await paceRefreshes(ledger, 0, info);
    expect(info.timeout).toBe(60_000);
    await expect(paceRefreshes(ledger, REFRESH_BUDGET + 1, info)).rejects.toThrow(RangeError);
  });
});

// #5103's security look N4: no `toEqual(step)` can print the single-use MFA handle.
describe("the password step's MFA handle", () => {
  it("is not on the record: printed whole, the step shows no handle", async () => {
    const handle = `mfa-handle-${"7".repeat(32)}`;
    const answer = {
      json: async () => ({ status: "mfa_required", methods: ["totp"], mfa_token: handle }),
      status: () => 200,
      headersArray: async () => [],
    };
    const page = {
      waitForResponse: async () => answer,
      getByLabel: () => ({ fill: async () => undefined }),
      getByRole: () => ({ click: async () => undefined }),
    } as unknown as Page;
    const step = await submitPassword(page, { username: "e2e-1a2b3c4d-1", seed: () => "" }, "pw");
    expect(step.mfaToken()).toBe(handle);
    expect(JSON.stringify(step)).not.toContain(handle);
    expect(Object.values(step)).not.toContain(handle);
    const printed = (() => {
      try {
        expect(step).toEqual({});
        return "";
      } catch (error) {
        return String(error);
      }
    })();
    expect(printed).toContain("mfaRequired"); // the record was printed whole
    expect(printed).not.toContain(handle);
  });
});

describe("the socket tap", () => {
  it("records the server's frames and closes, forwards them untouched, and keeps no client frame", async () => {
    type Handler = (route: unknown) => void;
    let route: Handler = () => undefined;
    const scripts: unknown[] = [];
    const page = {
      routeWebSocket: async (_url: string, handler: Handler) => void (route = handler),
      addInitScript: async (...args: unknown[]) => void scripts.push(args),
    } as unknown as Page;
    const tap = await tapWebSocket(page);
    const toPage: unknown[] = [];
    const pageCloses: unknown[] = [];
    let fromServer: (message: string | Buffer) => void = () => undefined;
    let serverClosed: (code: number | undefined, reason: string | undefined) => void = () =>
      undefined;
    const server = {
      onMessage: (h: typeof fromServer) => void (fromServer = h),
      onClose: (h: typeof serverClosed) => void (serverClosed = h),
    };
    // no `onMessage` on the page's side: the tap must leave the client's frames to Playwright
    route({
      connectToServer: () => server,
      send: (m: unknown) => toPage.push(m),
      close: async (o: unknown) => void pageCloses.push(o),
    });
    const binary = Buffer.from([1, 2]);
    for (const message of ['{"t":"bye","p":{"code":4401}}', binary, "not json"])
      fromServer(message);
    serverClosed(4401, "");
    expect(tap.frames).toEqual([{ t: "bye", p: { code: 4401 } }]);
    expect(toPage).toEqual(['{"t":"bye","p":{"code":4401}}', binary, "not json"]);
    expect([tap.closes, pageCloses]).toEqual([
      [{ code: 4401, reason: "" }],
      [{ code: 4401, reason: "" }],
    ]);
    expect([tap.connections(), scripts.length]).toEqual([1, 1]);
  });
});

describe("the sign-in helpers' waits for an answer", () => {
  // A `waitForResponse` nobody awaits rejects, unhandled, when the page closes (the runner sets no
  // action timeout): that error would bury the failure that left it pending.
  const unhandled: unknown[] = [];
  const record = (reason: unknown): void => {
    unhandled.push(reason);
  };
  beforeEach(() => {
    unhandled.length = 0;
    process.on("unhandledRejection", record);
  });
  afterEach(() => {
    process.off("unhandledRejection", record);
  });

  /** A response wait that settles only when the test closes the "page", as a closing page does. */
  function pendingWait(): { wait: Promise<never>; closePage: () => void } {
    let reject: (reason: Error) => void = () => undefined;
    const wait = new Promise<never>((_resolve, rejectWith) => {
      reject = rejectWith;
    });
    return { wait, closePage: () => reject(new Error("the page closed")) };
  }

  /** One turn of the event loop: Node reports an unhandled rejection before it ends. */
  const turn = (): Promise<void> => new Promise((resolve) => setImmediate(resolve));

  it("completeMfa fails with the in-page fetch's error and leaves no wait unhandled", async () => {
    const { wait, closePage } = pendingWait();
    const page = {
      waitForResponse: () => wait,
      evaluate: () => Promise.reject(new Error("the fetch failed")),
    } as unknown as Page;
    await expect(completeMfa(page, "handle", "123456")).rejects.toThrow("the fetch failed");
    closePage();
    await turn();
    expect(unhandled).toEqual([]);
  });

  it("submitPassword fails with the form's error and leaves no wait unhandled", async () => {
    const { wait, closePage } = pendingWait();
    const field = { fill: () => Promise.reject(new Error("the field is gone")) };
    const page = {
      waitForResponse: () => wait,
      getByLabel: () => field,
      getByRole: () => ({ click: () => Promise.resolve() }),
    } as unknown as Page;
    const user = { username: "e2e-1a2b3c4d-1", seed: () => "" };
    await expect(submitPassword(page, user, "a-password")).rejects.toThrow("the field is gone");
    closePage();
    await turn();
    expect(unhandled).toEqual([]);
  });
});
