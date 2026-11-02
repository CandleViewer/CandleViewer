import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AUDIT_MARKERS,
  REDACTOR_NAME_RULES,
  auditDiffModel,
  isRedactedName,
  type AuditDiffEntry,
} from "../src/components/auditDiffModel.js";

/** The repository's root, from packages/ui/test. */
const ROOT = resolve(import.meta.dirname, "../../..");
const REDACTOR = resolve(ROOT, "services/api/candleviewer/audit/redact.py");
const EVIDENCE = resolve(ROOT, "services/api/candleviewer/admin/flags/evidence.py");

/**
 * The sha256 of redact.py's decision code, `def _normalise(` up to `def _redact_sequence(`: the name normalisation,
 * the classifier, the OTP context, the version exemption and the mapping walk. Any edit there may change which names
 * the server treats as secret, so it fails here until the mirror in auditDiffModel.ts is re-read against it and this
 * pin is moved in the same PR (CG-27; BQ-10).
 */
const PINNED_LOGIC_DIGEST = "c6b630456d760b811d3b83628a3b7c6409eb1a3e1c5b1683551b4d001d8c35a5";

/** The server's source, read-only. A file that moved or cannot be read fails the test: never a skip (BQ-10). */
const source = (path: string): string => {
  expect(existsSync(path), `${path} is gone: re-point the mirror's parity test (CG-27)`).toBe(true);
  return readFileSync(path, "utf-8").replace(/\r\n/g, "\n");
};

/** The quoted strings of the Python literal assigned to `name`, failing closed when it cannot be found. */
function pythonStrings(text: string, name: string, shape: RegExp): string[] {
  const found = shape.exec(text);
  expect(found, `${name} could not be parsed out of redact.py`).not.toBeNull();
  const body = found?.[1] ?? "";
  const words = [...body.matchAll(/"([^"]*)"/g)].map((m) => m[1] ?? "");
  expect(words.length, `${name} parsed to nothing`).toBeGreaterThan(0);
  return words;
}

const sorted = (values: Iterable<string>): string[] => [...values].sort();

describe("the redactor's name rules, mirrored (CG-27; BQ-10: read-only, fail closed)", () => {
  const redactor = source(REDACTOR);

  it.each([
    ["_SECRET_FIELD_FRAGMENTS", REDACTOR_NAME_RULES.fragments],
    ["_SECRET_EXACT_NAMES", REDACTOR_NAME_RULES.exactNames],
    ["_OTP_MARKERS", REDACTOR_NAME_RULES.otpMarkers],
    ["_METADATA_VERSION_NAMES", REDACTOR_NAME_RULES.versionNames],
  ] as const)("%s holds the same names", (name, mirror) => {
    const shape = new RegExp(`^${name}: frozenset\\[str\\] = frozenset\\(\\s*\\{([^}]*)\\}`, "m");
    expect(sorted(mirror)).toEqual(sorted(pythonStrings(redactor, name, shape)));
  });

  it("_SECRET_SUFFIXES holds the same suffixes", () => {
    const shape = /^_SECRET_SUFFIXES: tuple\[str, \.\.\.\] = \(([^)]*)\)/m;
    expect(sorted(REDACTOR_NAME_RULES.suffixes)).toEqual(
      sorted(pythonStrings(redactor, "_SECRET_SUFFIXES", shape)),
    );
  });

  it("_ENUM_PASS_THROUGH holds the same names and words", () => {
    const shape =
      /^_ENUM_PASS_THROUGH: [^\n]*= MappingProxyType\(\s*\{([\s\S]*?)\}\s*(?:#[^\n]*)?\n\)/m;
    const found = shape.exec(redactor);
    expect(found, "_ENUM_PASS_THROUGH could not be parsed out of redact.py").not.toBeNull();
    const entries = [...(found?.[1] ?? "").matchAll(/"(\w+)":\s*frozenset\(\{([^}]*)\}\)/g)].map(
      (m) => [m[1] ?? "", sorted([...(m[2] ?? "").matchAll(/"([^"]*)"/g)].map((w) => w[1] ?? ""))],
    );
    expect(entries.length).toBeGreaterThan(0);
    const mirror = Object.entries(REDACTOR_NAME_RULES.passThrough).map(([key, words]) => [
      key,
      sorted(words),
    ]);
    expect(mirror).toEqual(entries);
  });

  it("the version exemption's digit limit and the normalisation are the same", () => {
    const digits = /^_VERSION_MAX_DIGITS = (\d+)$/m.exec(redactor);
    expect(digits, "_VERSION_MAX_DIGITS could not be parsed").not.toBeNull();
    expect(REDACTOR_NAME_RULES.versionMaxDigits).toBe(Number(digits?.[1]));
    expect(redactor).toContain('_NORMALISE_RE = re.compile(r"[^a-z0-9]")');
    expect(redactor).toContain('_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")');
  });

  it("the four markers are the server's", () => {
    const literal = (text: string, name: string): string | undefined =>
      new RegExp(`^${name}(?::[^=]*)? = "([^"]+)"`, "m").exec(text)?.[1];
    expect(literal(redactor, "REDACTION_MARKER")).toBe(AUDIT_MARKERS.secret);
    expect(literal(redactor, "PII_HASH_PREFIX")).toBe(AUDIT_MARKERS.personal);
    expect(literal(redactor, "OVERSIZE_MARKER")).toBe(AUDIT_MARKERS.oversize);
    expect(literal(source(EVIDENCE), "REDACTED_CREDENTIAL")).toBe(AUDIT_MARKERS.credential);
  });

  it("the decision code is the one the mirror was read against (re-read the mirror, then move the pin)", () => {
    const start = redactor.indexOf("def _normalise(");
    const end = redactor.indexOf("def _redact_sequence(");
    expect(start, "def _normalise( is gone").toBeGreaterThan(0);
    expect(end, "def _redact_sequence( is gone").toBeGreaterThan(start);
    const digest = createHash("sha256").update(redactor.slice(start, end), "utf8").digest("hex");
    expect(digest).toBe(PINNED_LOGIC_DIGEST);
  });
});

describe("isRedactedName: the server's classification of a field name", () => {
  it.each([
    "password",
    "passwordHash",
    "api_key",
    "apiKey",
    "secret_key",
    "csrf-token",
    "refresh_token",
    "totp_seed",
    "authorization",
    "private_key",
    "sessionId",
    "bearer",
    "webhookSecret",
    "PASSWORD-HASH",
    "kek_version",
    "credentials",
  ])("%s is redacted by name", (name) => {
    expect(isRedactedName(name)).toBe(true);
  });

  it.each([
    "description",
    "recipient",
    "design",
    "assign",
    "key_id",
    "key_id_masked",
    "sha256",
    "recv_window",
    "first_bad_id",
    "symbol",
    "code",
  ])("%s is not", (name) => {
    expect(isRedactedName(name)).toBe(false);
  });

  it("a field named code is a one-time code next to an OTP marker, by key or by value", () => {
    expect(isRedactedName("code", { method: "totp", code: "x" })).toBe(true);
    expect(isRedactedName("code", { mfa_channel: "app", code: "x" })).toBe(true);
    expect(isRedactedName("code", { kind: "order", code: "x" })).toBe(false);
  });
});

const ENTRY: AuditDiffEntry = {
  action: "flags.change",
  subject_type: "feature_flag",
  outcome: "success",
  reason: null,
  entry_hash: "3c9a5e2f1b",
  detail: {},
};
const entry = (fields: Partial<AuditDiffEntry>): AuditDiffEntry => ({ ...ENTRY, ...fields });
const UUID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
const HEX = "a3f1c2d4e5b60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90";

describe("auditDiffModel: values (E42-D04 §6's kinds)", () => {
  const after = (value: Record<string, unknown>) =>
    auditDiffModel(
      entry({
        action: "orders.submit",
        subject_type: "order",
        detail: { before: null, after: value },
      }),
    );
  const kindOf = (value: Record<string, unknown>, path = Object.keys(value)[0] ?? "") =>
    after(value).fields.find((f) => f.path.join("/") === path)?.after;

  it.each([
    ["the secret marker", { note: AUDIT_MARKERS.secret }, { kind: "secret" }],
    ["the credential marker", { reason: AUDIT_MARKERS.credential }, { kind: "credential" }],
    ["the oversize marker", { body: AUDIT_MARKERS.oversize }, { kind: "oversize" }],
    [
      "a hashed personal value",
      { email: `${AUDIT_MARKERS.personal}${HEX}` },
      { kind: "personal", hex8: "a3f1c2d4" },
    ],
    ["a stored null", { note: null }, { kind: "none" }],
    ["a safe fingerprint", { key_id_masked: "ab12…9f" }, { kind: "fingerprint", text: "ab12…9f" }],
    ["an export digest", { sha256: HEX }, { kind: "fingerprint", text: HEX }],
    [
      "a signing key id",
      { key_id: "cv-audit-export-v2:0011223344556677" },
      { kind: "identifier", text: "cv-audit-export-v2:0011223344556677" },
    ],
    [
      "a number, with separators",
      { first_bad_id: 1204118 },
      { kind: "value", text: "1,204,118", numeric: true, cut: false },
    ],
    [
      "a fraction keeps its digits",
      { price: 64010.5 },
      { kind: "value", text: "64,010.5", numeric: true, cut: false },
    ],
    [
      "a boolean outside a flag",
      { verified: false },
      { kind: "value", text: "false", numeric: false, cut: false },
    ],
    [
      "a list, whole",
      { legs: ["a", "b"] },
      { kind: "value", text: '["a","b"]', numeric: false, cut: false },
    ],
    [
      "a pass-through word",
      { bearer: "matched" },
      { kind: "value", text: "matched", numeric: false, cut: false },
    ],
    [
      "a version number under kek_version",
      { kek_version: 3 },
      { kind: "value", text: "3", numeric: true, cut: false },
    ],
  ])("%s", (_name, value, kind) => {
    expect(kindOf(value)).toEqual(kind);
    expect(after(value).flagged).toBe(false);
  });

  it("cuts a value past 120 characters, keeping it whole for Show full value", () => {
    const long = "x".repeat(121);
    expect(kindOf({ note: long })).toEqual({
      kind: "value",
      text: long,
      numeric: false,
      cut: true,
    });
    expect(kindOf({ note: "x".repeat(120) })).toMatchObject({ cut: false });
  });

  it("reads a flag record's booleans as ON and OFF", () => {
    const model = auditDiffModel(
      entry({ detail: { before: { value: false }, after: { value: true } } }),
    );
    expect(model.fields[0]).toEqual({
      path: ["value"],
      status: "changed",
      before: { kind: "value", text: "OFF", numeric: false, cut: false },
      after: { kind: "value", text: "ON", numeric: false, cut: false },
    });
  });
});

describe("auditDiffModel: a value under a redacted name that is no marker (secret_named, AD-3)", () => {
  const model = (value: Record<string, unknown>) =>
    auditDiffModel(
      entry({
        action: "orders.submit",
        subject_type: "order",
        detail: { before: null, after: value },
      }),
    );

  it.each([
    ["a plain value", { password: "unredacted" }, "password"],
    ["a number", { apiKey: 1234 }, "apiKey"],
    ["a stored null", { refresh_token: null }, "refresh_token"],
    ["an object", { credentials: { user: "alex" } }, "credentials"],
    ["a word outside the pass-through set", { bearer: "yes" }, "bearer"],
    ["a version outside the limit", { kek_version: "abc" }, "kek_version"],
    ["a one-time code", { method: "totp", code: "plain" }, "code"],
  ])("%s is hidden and the record flagged; no value is carried", (_name, value, path) => {
    const m = model(value);
    expect(m.fields.find((f) => f.path.join("/") === path)?.after).toEqual({
      kind: "secret_named",
    });
    expect(m.flagged).toBe(true);
    expect(JSON.stringify(m)).not.toContain("unredacted");
    expect(JSON.stringify(m)).not.toContain("1234");
  });

  it("finds one nested in an object, in a list or in embedded JSON, and hides the whole value", () => {
    const nested = model({ request: { headers: { authorization: "plain" } } });
    expect(nested.fields.map((f) => [f.path.join(" › "), f.after?.kind])).toEqual([
      ["request › headers › authorization", "secret_named"],
    ]);
    const listed = model({ legs: [{ id: 1, private_key: "plain" }] });
    expect(listed.fields[0]?.after).toEqual({ kind: "secret_named" });
    expect(listed.flagged).toBe(true);
    const embedded = model({ body: '{"symbol":"BTCUSDT","sessionId":"plain"}' });
    expect(embedded.fields[0]?.after).toEqual({ kind: "secret_named" });
    expect(JSON.stringify(embedded)).not.toContain("plain");
  });

  it("flags the record for one in a state the diff does not list (the raw record is withheld)", () => {
    const m = auditDiffModel(
      entry({
        outcome: "failure",
        reason: "credential_in_reason",
        detail: { before: { value: false, token: "plain" }, after: { value: true } },
      }),
    );
    expect(m.shape).toBe("request");
    expect(m.flagged).toBe(true);
  });
});

describe("auditDiffModel: the three shapes", () => {
  it("state: changed, added and removed fields, nested paths, the phase as a fact, unchanged folded", () => {
    const m = auditDiffModel(
      entry({
        detail: {
          before: { value: false, overrides: {}, description: "One-click", rollout: 5 },
          after: {
            value: true,
            overrides: { [UUID]: true },
            description: "One-click",
            phase: "outcome",
          },
        },
      }),
    );
    expect(m.shape).toBe("state");
    expect([m.before, m.after]).toEqual(["served", "served"]);
    expect(m.fields).toEqual([
      {
        path: ["value"],
        status: "changed",
        before: { kind: "value", text: "OFF", numeric: false, cut: false },
        after: { kind: "value", text: "ON", numeric: false, cut: false },
      },
      {
        path: ["overrides", UUID],
        status: "added",
        after: { kind: "value", text: "ON", numeric: false, cut: false },
      },
      {
        path: ["rollout"],
        status: "removed",
        before: { kind: "value", text: "5", numeric: true, cut: false },
      },
    ]);
    expect(m.unchanged).toEqual([
      {
        path: ["description"],
        value: { kind: "value", text: "One-click", numeric: false, cut: false },
      },
    ]);
    expect(m.facts).toEqual([
      { path: ["phase"], value: { kind: "value", text: "outcome", numeric: false, cut: false } },
    ]);
    expect(m.head).toBeUndefined();
  });

  it("state with no earlier state: every After field paired with no_before, no status word", () => {
    const m = auditDiffModel(
      entry({
        action: "rule.create",
        subject_type: "rule",
        detail: { before: null, after: { name: "breakout" } },
      }),
    );
    expect(m.before).toBe("none");
    expect(m.fields).toEqual([
      {
        path: ["name"],
        before: { kind: "none", note: "no_before" },
        after: { kind: "value", text: "breakout", numeric: false, cut: false },
      },
    ]);
  });

  it("state with a withheld before beside a served after: Withheld once, After's fields, no status word", () => {
    const m = auditDiffModel(
      entry({ detail: { before: null, after: { value: true }, elided: ["before"] } }),
    );
    expect([m.before, m.after]).toEqual(["withheld", "served"]);
    expect(m.fields).toEqual([
      { path: ["value"], after: { kind: "value", text: "ON", numeric: false, cut: false } },
    ]);
  });

  it("a Manager's projection (detail {}, no hashes) is hidden; an Owner's empty detail is none", () => {
    expect(auditDiffModel(entry({ detail: {}, entry_hash: null })).shape).toBe("hidden");
    const own = auditDiffModel(entry({ detail: {} }));
    expect([own.shape, own.before, own.after, own.fields]).toEqual(["state", "none", "none", []]);
  });

  it("request, refused: the head names the reason, Requested fields, the request's facts", () => {
    const m = auditDiffModel(
      entry({
        outcome: "failure",
        reason: "credential_in_reason",
        detail: {
          before: { value: false },
          after: {
            value: true,
            overrides: null,
            reason: AUDIT_MARKERS.credential,
            evidence_url: null,
            result: "credential_in_reason",
          },
        },
      }),
    );
    expect(m.shape).toBe("request");
    expect(m.head).toEqual({ kind: "failed", reason: "credential_in_reason" });
    expect(m.fields).toEqual([
      {
        path: ["value"],
        before: { kind: "value", text: "OFF", numeric: false, cut: false },
        after: { kind: "value", text: "ON", numeric: false, cut: false },
      },
      { path: ["overrides"], after: { kind: "none", note: "overrides_kept" } },
    ]);
    expect(m.facts).toEqual([
      { path: ["reason"], value: { kind: "credential" } },
      { path: ["evidence_url"], value: { kind: "none", note: "not_sent" } },
      {
        path: ["result"],
        value: { kind: "value", text: "credential_in_reason", numeric: false, cut: false },
      },
    ]);
    expect(m.flagged).toBe(false);
  });

  it("request, a denial reads as refused too; an intent heads intent and keeps its phase as a fact", () => {
    expect(
      auditDiffModel(entry({ outcome: "denied", detail: { before: null, after: { value: true } } }))
        .head,
    ).toEqual({
      kind: "failed",
    });
    const intent = auditDiffModel(
      entry({ detail: { before: { value: false }, after: { value: true, phase: "intent" } } }),
    );
    expect(intent.shape).toBe("request");
    expect(intent.head).toEqual({ kind: "intent" });
    expect(intent.facts).toEqual([
      { path: ["phase"], value: { kind: "value", text: "intent", numeric: false, cut: false } },
    ]);
  });

  it("result: a tamper check's recorded result, its fields as values; a write-ahead one heads Started", () => {
    const after = { from_id: 204119, to_id: 1204118, verified: false, first_bad_id: 1204118 };
    const done = auditDiffModel(
      entry({
        action: "admin.audit_verify",
        subject_type: null,
        outcome: "failure",
        detail: { before: null, after },
      }),
    );
    expect(done.shape).toBe("result");
    expect(done.head).toEqual({ kind: "result" });
    expect(done.before).toBe("none");
    expect(done.facts.map((f) => [f.path.join(""), f.value])).toEqual([
      ["from_id", { kind: "value", text: "204,119", numeric: true, cut: false }],
      ["to_id", { kind: "value", text: "1,204,118", numeric: true, cut: false }],
      ["verified", { kind: "value", text: "false", numeric: false, cut: false }],
      ["first_bad_id", { kind: "value", text: "1,204,118", numeric: true, cut: false }],
    ]);
    const started = auditDiffModel(
      entry({
        action: "admin.audit_verify",
        subject_type: null,
        reason: "started",
        detail: { before: null, after: { from_id: 1, to_id: 1204114 } },
      }),
    );
    expect(started.head).toEqual({ kind: "started" });
  });
});
