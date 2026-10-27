import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, readFile, rm, stat, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  CRASH_LOG_AUDIT_BURST,
  CRASH_LOG_AUDIT_WINDOW_MS,
  CRASH_LOG_MAX_LINE_BYTES,
  CRASH_LOG_MAX_PENDING,
  CrashLogRefusedError,
  CrashLogUnavailableError,
  createCrashLog,
  scrubCrashText,
} from "../src/main/crashLog";
import { CRASH_ENTRY_LIMITS, parseCrashEntry } from "../src/shared/crashEntry";

const AT = 1_700_000_100_000;
const AT_ISO = new Date(AT).toISOString();
const now = (): number => AT;

/** Every field at its bound, in characters JSON must escape to six bytes each. */
const MAX_ENTRY = {
  timestampMs: Number.MAX_SAFE_INTEGER,
  message: "\u0001".repeat(CRASH_ENTRY_LIMITS.message),
  stack: "\u0001".repeat(CRASH_ENTRY_LIMITS.stack),
  context: Object.fromEntries(
    Array.from({ length: CRASH_ENTRY_LIMITS.contextKeys }, (_, i) => [
      `k${i}`.padEnd(CRASH_ENTRY_LIMITS.contextKey, "k"),
      "\u0001".repeat(CRASH_ENTRY_LIMITS.contextValue),
    ]),
  ),
};

const ENTRY = {
  timestampMs: 1_700_000_000_000,
  message: "TypeError: x is undefined",
  stack: "at Panel (panel.tsx:1:1)",
  context: { correlationId: "c-1", boundary: "panel" },
};

describe("parseCrashEntry (SR-111 schema, both sides)", () => {
  it("returns a fresh copy of a valid entry, with and without the optional fields", () => {
    const parsed = parseCrashEntry(ENTRY);
    expect(parsed).toEqual(ENTRY);
    expect(parsed).not.toBe(ENTRY);
    expect(parsed?.context).not.toBe(ENTRY.context);
    expect(parseCrashEntry({ timestampMs: 0, message: "" })).toEqual({
      timestampMs: 0,
      message: "",
    });
    expect(
      parseCrashEntry(Object.assign(Object.create(null), { timestampMs: 1, message: "m" })),
    ).toEqual({
      timestampMs: 1,
      message: "m",
    });
  });

  it("accepts every field at its bound, and letter-first keys with dots and hyphens", () => {
    expect(parseCrashEntry(MAX_ENTRY)).toEqual(MAX_ENTRY);
    const context = { "trace-id": "t", "react.component": "Panel" };
    expect(parseCrashEntry({ ...ENTRY, context })).toEqual({ ...ENTRY, context });
  });

  it.each([
    ["null", null],
    ["a string", "boom"],
    ["an array", [ENTRY]],
    ["a class instance", new (class Entry {})()],
    ["an unknown key", { ...ENTRY, token: "secret" }],
    ["no message", { timestampMs: 1 }],
    ["no timestamp", { message: "m" }],
    ["a string timestamp", { ...ENTRY, timestampMs: "1" }],
    ["a fractional timestamp", { ...ENTRY, timestampMs: 1.5 }],
    ["a negative timestamp", { ...ENTRY, timestampMs: -1 }],
    ["a NaN timestamp", { ...ENTRY, timestampMs: Number.NaN }],
    ["a number message", { ...ENTRY, message: 1 }],
    ["an oversized message", { ...ENTRY, message: "m".repeat(CRASH_ENTRY_LIMITS.message + 1) }],
    ["an oversized stack", { ...ENTRY, stack: "s".repeat(CRASH_ENTRY_LIMITS.stack + 1) }],
    ["a null stack", { ...ENTRY, stack: null }],
    ["an array context", { ...ENTRY, context: ["a"] }],
    ["a number context value", { ...ENTRY, context: { correlationId: 1 } }],
    ["a nested context value", { ...ENTRY, context: { correlationId: { a: "b" } } }],
    ["a __proto__ context key", { ...ENTRY, context: JSON.parse('{"__proto__":"v"}') as unknown }],
    ["an empty context key", { ...ENTRY, context: { "": "v" } }],
    ["a 65-character context key", { ...ENTRY, context: { ["k".repeat(65)]: "v" } }],
    ["a context key with a space", { ...ENTRY, context: { "a b": "v" } }],
    ["an oversized context value", { ...ENTRY, context: { k: "v".repeat(4097) } }],
    [
      "too many context keys",
      {
        ...ENTRY,
        context: Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`k${i}`, "v"])),
      },
    ],
  ])("refuses %s whole", (_label, value) => {
    expect(parseCrashEntry(value)).toBeUndefined();
  });
});

describe("createCrashLog (the cv:crashLog:append writer)", () => {
  let dir: string;
  const audit = vi.fn();

  beforeEach(async () => {
    dir = await mkdtemp(path.join(tmpdir(), "cv-crashlog-"));
    audit.mockClear();
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  const lines = async (file = "crash.log"): Promise<unknown[]> =>
    (await readFile(path.join(dir, file), "utf8"))
      .split("\n")
      .filter((line) => line !== "")
      .map((line) => {
        const { receivedAt, ...entry } = JSON.parse(line) as Record<string, unknown>;
        expect(receivedAt).toBe(AT_ISO);
        return entry;
      });

  it("appends one JSON line per valid entry, creating the logs dir, owner-only", async () => {
    const logDir = path.join(dir, "logs");
    const log = createCrashLog({ now, dir: logDir, audit });
    await log.append(ENTRY);
    await log.append({ timestampMs: 2, message: "second\nline" });
    dir = logDir;
    expect(await lines()).toEqual([ENTRY, { timestampMs: 2, message: "second\nline" }]);
    if (process.platform !== "win32") {
      expect((await stat(path.join(logDir, "crash.log"))).mode & 0o777).toBe(0o600);
      expect((await stat(logDir)).mode & 0o777).toBe(0o700);
    }
    expect(audit).not.toHaveBeenCalled();
  });

  it.each([
    ["an unknown key", { ...ENTRY, cookie: "session=abc" }],
    ["a wrong type", { ...ENTRY, message: 42 }],
    ["an oversized stack", { ...ENTRY, stack: "s".repeat(CRASH_ENTRY_LIMITS.stack + 1) }],
  ])("refuses %s with a fixed error and writes nothing", async (_label, value) => {
    const log = createCrashLog({ now, dir, audit });
    const result = log.append(value);
    await expect(result).rejects.toThrow(CrashLogRefusedError);
    await expect(result).rejects.toThrow(/^Crash log entry refused$/);
    await expect(stat(path.join(dir, "crash.log"))).rejects.toMatchObject({ code: "ENOENT" });
    expect(audit.mock.calls).toEqual([["crash-log-entry-refused", { reason: "schema" }]]);
  });

  it("refuses a valid entry whose line is over the per-entry cap", async () => {
    const log = createCrashLog({ now, dir, audit, maxBytes: 200 });
    await expect(log.append({ ...ENTRY, message: "m".repeat(300) })).rejects.toThrow(
      CrashLogRefusedError,
    );
    expect(audit.mock.calls).toEqual([["crash-log-entry-refused", { reason: "too-large" }]]);
  });

  it("rotates to crash.log.1 at the cap, keeping one rotated copy", async () => {
    const one = { timestampMs: 1, message: "a".repeat(60) };
    const lineBytes = Buffer.byteLength(`${JSON.stringify({ ...one, receivedAt: AT_ISO })}\n`);
    const log = createCrashLog({ now, dir, audit, maxBytes: lineBytes * 2 });
    await log.append(one);
    await log.append({ ...one, timestampMs: 2 });
    expect(await lines()).toHaveLength(2);
    await log.append({ ...one, timestampMs: 3 });
    expect(await lines()).toEqual([{ ...one, timestampMs: 3 }]);
    expect(await lines("crash.log.1")).toEqual([one, { ...one, timestampMs: 2 }]);
    await log.append({ ...one, timestampMs: 4 });
    await log.append({ ...one, timestampMs: 5 });
    expect(await lines()).toEqual([{ ...one, timestampMs: 5 }]);
    expect(await lines("crash.log.1")).toEqual([
      { ...one, timestampMs: 3 },
      { ...one, timestampMs: 4 },
    ]);
    expect((await stat(path.join(dir, "crash.log"))).size).toBeLessThanOrEqual(lineBytes * 2);
  });

  it("serialises concurrent appends and refuses beyond the pending bound", async () => {
    const log = createCrashLog({ now, dir, audit });
    const results = await Promise.allSettled(
      Array.from({ length: CRASH_LOG_MAX_PENDING + 3 }, (_, i) =>
        log.append({ timestampMs: i, message: `m${i}` }),
      ),
    );
    expect(results.filter((r) => r.status === "fulfilled")).toHaveLength(CRASH_LOG_MAX_PENDING);
    expect(results.filter((r) => r.status === "rejected")).toHaveLength(3);
    const written = (await lines()) as Array<{ timestampMs: number }>;
    expect(written.map((e) => e.timestampMs)).toEqual(
      Array.from({ length: CRASH_LOG_MAX_PENDING }, (_, i) => i),
    );
    expect(audit).toHaveBeenCalledWith("crash-log-entry-refused", { reason: "queue-full" });
    await log.append(ENTRY);
  });

  it("fails closed with a fixed error when the file cannot be written, and keeps working", async () => {
    const blocked = path.join(dir, "not-a-dir");
    await writeFile(blocked, "");
    const log = createCrashLog({ now, dir: blocked, audit });
    const result = log.append(ENTRY);
    await expect(result).rejects.toThrow(CrashLogUnavailableError);
    await expect(result).rejects.toThrow(/^Crash log unavailable$/);
    expect(audit.mock.calls).toEqual([["crash-log-write-failed", { code: "EEXIST" }]]);
    await expect(log.append(ENTRY)).rejects.toThrow(CrashLogUnavailableError);
  });

  it("fails closed when the existing log cannot be stat'ed (not ENOENT)", async () => {
    await symlink("crash.log", path.join(dir, "crash.log"));
    const log = createCrashLog({ now, dir, audit });
    await expect(log.append(ENTRY)).rejects.toThrow(CrashLogUnavailableError);
    expect(audit.mock.calls).toEqual([["crash-log-write-failed", { code: "ELOOP" }]]);
  });

  it("writes a schema-valid entry at every bound (the line cap derives from the schema)", async () => {
    const log = createCrashLog({ now, dir, audit });
    await log.append(MAX_ENTRY);
    const line = await readFile(path.join(dir, "crash.log"), "utf8");
    expect(Buffer.byteLength(line)).toBeGreaterThan(256 * 1024);
    expect(Buffer.byteLength(line)).toBeLessThanOrEqual(CRASH_LOG_MAX_LINE_BYTES);
    expect(await lines()).toEqual([MAX_ENTRY]);
  });

  it("scrubs message, stack and context values at the sink", async () => {
    const log = createCrashLog({ now, dir, audit });
    await log.append({
      timestampMs: 1,
      message: "fetch /v1/me?token=abc failed",
      stack: "Authorization: Bearer abc.def",
      context: { authToken: "abc", note: "password=hunter2", boundary: "panel" },
    });
    expect(await lines()).toEqual([
      {
        timestampMs: 1,
        message: "fetch /v1/me?token=[redacted] failed",
        stack: "Authorization: [redacted]",
        context: { authToken: "[redacted]", note: "password=[redacted]", boundary: "panel" },
      },
    ]);
  });

  it("bounds refusal audits per reason per window, then writes one summary with the count", async () => {
    let clock = 0;
    const log = createCrashLog({ now: () => clock, dir, audit });
    const flood = 200;
    await Promise.allSettled(
      Array.from({ length: flood }, () => log.append({ timestampMs: 1, message: "m", x: 1 })),
    );
    const refused = ["crash-log-entry-refused", { reason: "schema" }];
    expect(audit.mock.calls).toEqual(Array.from({ length: CRASH_LOG_AUDIT_BURST }, () => refused));
    clock = CRASH_LOG_AUDIT_WINDOW_MS;
    await expect(log.append("boom")).rejects.toThrow(CrashLogRefusedError);
    expect(audit.mock.calls.slice(CRASH_LOG_AUDIT_BURST)).toEqual([
      [
        "crash-log-audit-suppressed",
        {
          event: "crash-log-entry-refused",
          reason: "schema",
          suppressed: flood - CRASH_LOG_AUDIT_BURST,
        },
      ],
      refused,
    ]);
  });
});

describe("scrubCrashText (defence in depth behind the renderer's redaction)", () => {
  it.each([
    ["Cookie: session=abc; csrf=def\nnext", "Cookie: [redacted]\nnext"],
    ["header Authorization=Basic dXNlcjpwYXNz", "header Authorization=[redacted]"],
    ["got bearer eyJhbGciOi.x-y_z from cache", "got bearer [redacted] from cache"],
    [
      'apiKey=K1 api_key: "K2" X-Api-Key=K3 X-BAPI-SIGN=K4',
      'apiKey=[redacted] api_key: "[redacted]" X-Api-Key=[redacted] X-BAPI-SIGN=[redacted]',
    ],
    [
      "GET /x?access_token=abc&page=2&signature=f0",
      "GET /x?access_token=[redacted]&page=2&signature=[redacted]",
    ],
    [
      "secret: s passwd=p sessionToken=t",
      "secret: [redacted] passwd=[redacted] sessionToken=[redacted]",
    ],
    [
      `Error: 401 {"apiKey":"K1","ok":true} token='t 2' "csrf": "c"`,
      `Error: 401 {"apiKey":"[redacted]","ok":true} token='[redacted]' "csrf": "[redacted]"`,
    ],
    [
      "pwd=a auth=b credential=c jwt=d totp=e recovery_code=f kek_handle=g sealed_seed=h dek_ref=i",
      "pwd=[redacted] auth=[redacted] credential=[redacted] jwt=[redacted] totp=[redacted] recovery_code=[redacted] kek_handle=[redacted] sealed_seed=[redacted] dek_ref=[redacted]",
    ],
    [
      `{"message":"Request failed apiKey=K1 password=P1 for user","code":401}`,
      `{"message":"Request failed apiKey=[redacted] password=[redacted] for user","code":401}`,
    ],
    [
      `Error: apiKey=K1 url: https://h/x?access_token=abc {"password":"p\\"q"} __Host-cv_csrf=c`,
      `Error: apiKey=[redacted] url: https://h/x?access_token=[redacted] {"password":"[redacted]"} __Host-cv_csrf=[redacted]`,
    ],
  ])("redacts %j", (input, expected) => {
    expect(scrubCrashText(input)).toBe(expected);
  });

  it("leaves benign text untouched", () => {
    const text =
      "TypeError: x is undefined\n    at Panel (panel.tsx:12:3) id=3 page=2 boundary: panel";
    expect(scrubCrashText(text)).toBe(text);
  });
});
