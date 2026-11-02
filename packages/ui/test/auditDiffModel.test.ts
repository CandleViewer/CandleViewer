import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AUDIT_MARKERS,
  REDACTOR_EMBED_LIMITS,
  REDACTOR_NAME_RULES,
  auditDiffModel,
  isRedactedName,
  type AuditDiffEntry,
} from "../src/components/auditDiffModel.js";

/**
 * The server files the mirror reads, from packages/ui/test. Relative literals, so the turbo-inputs governance test
 * (scripts/tests/test_ui_turbo_test_inputs.py) finds both and holds them in ui's `test` and `test:cov` inputs: a change
 * to either reruns this test (BQ-10).
 */
const REDACTOR = resolve(import.meta.dirname, "../../../services/api/candleviewer/audit/redact.py");
const EVIDENCE = resolve(
  import.meta.dirname,
  "../../../services/api/candleviewer/admin/flags/evidence.py",
);

/**
 * The sha256 of redact.py from `REDACTION_MARKER = ` to the end of the file: the markers, every name set, the
 * exemptions, the embedded-JSON bounds and all the code that applies them. Any edit there may change what the server
 * treats as secret, so it fails here until the mirror in auditDiffModel.ts is re-read against it and this pin is moved
 * in the same PR (CG-27; BQ-10).
 */
const PINNED_REDACTOR_DIGEST = "192099da934103dc9bf351bdc1b5ec33eea9cb4cb677019e714d18be1d85aeb7";

/** The server's source, read-only. A file that moved or cannot be read fails the test: never a skip (BQ-10). */
const source = (path: string): string => {
  expect(existsSync(path), `${path} is gone: re-point the mirror's parity test (CG-27)`).toBe(true);
  return readFileSync(path, "utf-8").replace(/\r\n/g, "\n");
};

/** A literal's body holds string literals, commas and whitespace only: no name, call or operator (S-5520-01). */
const literalOnly = (body: string): boolean =>
  body.replace(/"[^"]*"/g, "").replace(/[\s,]/g, "") === "";

/**
 * The quoted strings of the Python literal `shape` matches in `text` (its first group the literal's body, closed where
 * the statement ends); undefined when the literal is missing, empty, or anything but string literals, such as a set
 * composed with another (`frozenset({...} | _MORE)`), a name inside it, or a tuple added to another. The parity tests
 * fail closed on undefined.
 */
function pythonStrings(text: string, shape: RegExp): string[] | undefined {
  const body = shape.exec(text)?.[1];
  if (body === undefined || !literalOnly(body)) return undefined;
  const words = [...body.matchAll(/"([^"]*)"/g)].map((m) => m[1] ?? "");
  return words.length === 0 ? undefined : words;
}

/** A name set's literal, closed: `NAME: frozenset[str] = frozenset({ "a", "b" })` and nothing after it. */
const setShape = (name: string): RegExp =>
  new RegExp(`^${name}: frozenset\\[str\\] = frozenset\\(\\s*\\{([^}]*)\\}\\s*\\)\\s*$`, "m");
/** The suffix tuple's literal, closed: nothing added to it on its line. */
const SUFFIX_SHAPE = /^_SECRET_SUFFIXES: tuple\[str, \.\.\.\] = \(([^)]*)\)\s*$/m;
/** The pass-through table: one `MappingProxyType({...})`, a comment allowed after the dict. */
const PASS_THROUGH_SHAPE =
  /^_ENUM_PASS_THROUGH: [^\n]*= MappingProxyType\(\s*\{([\s\S]*?)\}\s*(?:#[^\n]*)?\n\)\s*$/m;
const PASS_THROUGH_ENTRY = /"(\w+)":\s*frozenset\(\{([^}]*)\}\)/g;

/** The pass-through table's entries, sorted; undefined unless the body is literal entries alone (no `**`, no name). */
function passThroughEntries(text: string): [string, string[]][] | undefined {
  const body = PASS_THROUGH_SHAPE.exec(text)?.[1];
  if (body === undefined || body.replace(PASS_THROUGH_ENTRY, "").replace(/[\s,]/g, "") !== "") {
    return undefined;
  }
  const entries = [...body.matchAll(PASS_THROUGH_ENTRY)].map((m): [string, string[]] | undefined =>
    literalOnly(m[2] ?? "")
      ? [m[1] ?? "", sorted([...(m[2] ?? "").matchAll(/"([^"]*)"/g)].map((w) => w[1] ?? ""))]
      : undefined,
  );
  return entries.length === 0 || entries.includes(undefined)
    ? undefined
    : (entries as [string, string[]][]);
}

/** A string constant's literal, closed: `NAME = "..."` (an annotation allowed) and nothing after it. */
const literal = (text: string, name: string): string | undefined =>
  new RegExp(`^${name}(?::[^=]*)? = "([^"]+)"\\s*$`, "m").exec(text)?.[1];

const sorted = (values: Iterable<string>): string[] => [...values].sort();

describe("the parity parser fails closed on a literal it cannot read whole (S-5520-01)", () => {
  const set = (body: string): string =>
    `_SECRET_EXACT_NAMES: frozenset[str] = frozenset(\n    {\n        ${body}\n    }\n)\n`;

  it("reads a closed literal", () => {
    expect(pythonStrings(set('"key",\n        "sid",'), setShape("_SECRET_EXACT_NAMES"))).toEqual([
      "key",
      "sid",
    ]);
  });

  it.each([
    [
      "a set composed around its literal",
      '_SECRET_EXACT_NAMES: frozenset[str] = frozenset(\n    {"key", "sid"} | _ADAPTER_HEADER_NAMES\n)\n',
    ],
    ["a bare name inside the literal", set('"key",\n        _EXTRA_NAME,')],
    ["a call inside the literal", set('"key",\n        str("sid"),')],
    ["no literal at all", "_SECRET_EXACT_NAMES: frozenset[str] = _load_names()\n"],
  ])("%s", (_name, text) => {
    expect(pythonStrings(text, setShape("_SECRET_EXACT_NAMES"))).toBeUndefined();
  });

  it("a suffix tuple added to another, and a marker built from parts", () => {
    const tuple = '_SECRET_SUFFIXES: tuple[str, ...] = ("_key", "_secret") + _MORE\n';
    expect(pythonStrings(tuple, SUFFIX_SHAPE)).toBeUndefined();
    expect(literal('REDACTION_MARKER = "<redacted:" + "secret>"\n', "REDACTION_MARKER")).toBe(
      undefined,
    );
  });

  it("a pass-through table spread from another, or with a name for its words", () => {
    const spread =
      '_ENUM_PASS_THROUGH: Mapping[str, frozenset[str]] = MappingProxyType(\n    {"bearer": frozenset({"matched"}), **_MORE}\n)\n';
    const named =
      '_ENUM_PASS_THROUGH: Mapping[str, frozenset[str]] = MappingProxyType(\n    {"bearer": frozenset({"matched", _WORD})}\n)\n';
    expect(passThroughEntries(spread)).toBeUndefined();
    expect(passThroughEntries(named)).toBeUndefined();
  });
});

describe("the redactor's name rules, mirrored (CG-27; BQ-10: read-only, fail closed)", () => {
  // Read inside each test: a moved file fails each parity test, and the model's own tests still run.
  let read: string | undefined;
  const redactorText = (): string => (read ??= source(REDACTOR));

  it.each([
    ["_SECRET_FIELD_FRAGMENTS", REDACTOR_NAME_RULES.fragments],
    ["_SECRET_EXACT_NAMES", REDACTOR_NAME_RULES.exactNames],
    ["_OTP_MARKERS", REDACTOR_NAME_RULES.otpMarkers],
    ["_METADATA_VERSION_NAMES", REDACTOR_NAME_RULES.versionNames],
  ] as const)("%s holds the same names", (name, mirror) => {
    const words = pythonStrings(redactorText(), setShape(name));
    expect(words, `${name} could not be read whole out of redact.py`).toBeDefined();
    expect(sorted(mirror)).toEqual(sorted(words ?? []));
  });

  it("_SECRET_SUFFIXES holds the same suffixes", () => {
    const words = pythonStrings(redactorText(), SUFFIX_SHAPE);
    expect(words, "_SECRET_SUFFIXES could not be read whole out of redact.py").toBeDefined();
    expect(sorted(REDACTOR_NAME_RULES.suffixes)).toEqual(sorted(words ?? []));
  });

  it("_ENUM_PASS_THROUGH holds the same names and words", () => {
    const entries = passThroughEntries(redactorText());
    expect(entries, "_ENUM_PASS_THROUGH could not be read whole out of redact.py").toBeDefined();
    const mirror = Object.entries(REDACTOR_NAME_RULES.passThrough).map(([key, words]) => [
      key,
      sorted(words),
    ]);
    expect(mirror).toEqual(entries);
  });

  it("the version exemption's digit limit and the normalisation are the same", () => {
    const digits = /^_VERSION_MAX_DIGITS = (\d+)$/m.exec(redactorText());
    expect(digits, "_VERSION_MAX_DIGITS could not be parsed").not.toBeNull();
    expect(REDACTOR_NAME_RULES.versionMaxDigits).toBe(Number(digits?.[1]));
    expect(redactorText()).toContain('_NORMALISE_RE = re.compile(r"[^a-z0-9]")');
    expect(redactorText()).toContain('_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")');
  });

  it("the embedded-JSON bounds are the same: _MAX_EMBED_DEPTH and _MAX_EMBED_BYTES", () => {
    const depth = /^_MAX_EMBED_DEPTH = (\d+)$/m.exec(redactorText());
    const bytes = /^_MAX_EMBED_BYTES = (\d+)(?: \* (\d+))?$/m.exec(redactorText());
    expect(depth, "_MAX_EMBED_DEPTH could not be parsed").not.toBeNull();
    expect(bytes, "_MAX_EMBED_BYTES could not be parsed").not.toBeNull();
    expect(REDACTOR_EMBED_LIMITS.depth).toBe(Number(depth?.[1]));
    expect(REDACTOR_EMBED_LIMITS.bytes).toBe(Number(bytes?.[1]) * Number(bytes?.[2] ?? 1));
  });

  it("the four markers are the server's", () => {
    expect(literal(redactorText(), "REDACTION_MARKER")).toBe(AUDIT_MARKERS.secret);
    expect(literal(redactorText(), "PII_HASH_PREFIX")).toBe(AUDIT_MARKERS.personal);
    expect(literal(redactorText(), "OVERSIZE_MARKER")).toBe(AUDIT_MARKERS.oversize);
    expect(literal(source(EVIDENCE), "REDACTED_CREDENTIAL")).toBe(AUDIT_MARKERS.credential);
  });

  it("redact.py is the one the mirror was read against, constants to end (re-read the mirror, then move the pin)", () => {
    const start = redactorText().indexOf("REDACTION_MARKER = ");
    expect(start, "REDACTION_MARKER = is gone").toBeGreaterThan(0);
    const digest = createHash("sha256").update(redactorText().slice(start), "utf8").digest("hex");
    expect(digest).toBe(PINNED_REDACTOR_DIGEST);
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

describe("auditDiffModel: past each bound it follows, the client fails closed (S-5520-02)", () => {
  const model = (value: Record<string, unknown>) =>
    auditDiffModel(
      entry({
        action: "orders.submit",
        subject_type: "order",
        detail: { before: null, after: value },
      }),
    );
  /** `inner` under `levels` nested lists. */
  const lists = (levels: number, inner: unknown): unknown =>
    Array.from({ length: levels }).reduce<unknown>((value) => [value], inner);
  /** `inner` as JSON inside `hops` nested JSON strings, each under a `body` key. */
  const strings = (hops: number, inner: Record<string, unknown>): string =>
    Array.from({ length: hops - 1 }).reduce<string>(
      (text) => JSON.stringify({ body: text }),
      JSON.stringify(inner),
    );
  const legs = (m: ReturnType<typeof model>) => m.fields.find((f) => f.path[0] === "legs")?.after;
  const body = (m: ReturnType<typeof model>) => m.fields.find((f) => f.path[0] === "body")?.after;

  it("within the depth it follows, a list's values read as a value", () => {
    const m = model({ legs: lists(50, { note: "plain" }) });
    expect(legs(m)?.kind).toBe("value");
    expect(m.flagged).toBe(false);
  });

  it("past it, a value is hidden and its record flagged, a secret-named one included", () => {
    for (const inner of [{ note: "plain" }, { password: "plain" }]) {
      const m = model({ legs: lists(70, inner) });
      expect(legs(m)).toEqual({ kind: "secret_named" });
      expect(m.flagged).toBe(true);
      expect(JSON.stringify(m)).not.toContain("plain");
    }
  });

  it("embedded JSON is followed four strings deep, as the server does", () => {
    const m = model({ body: strings(4, { note: "plain" }) });
    expect(body(m)?.kind).toBe("value");
    expect(m.flagged).toBe(false);
    expect(body(model({ body: strings(4, { sessionId: "plain" }) }))).toEqual({
      kind: "secret_named",
    });
  });

  it("a fifth string, which the server replaces, is hidden and flags the record, a secret in it or not", () => {
    for (const inner of [{ note: "plain" }, { sessionId: "plain" }]) {
      const m = model({ body: strings(5, inner) });
      expect(body(m)).toEqual({ kind: "secret_named" });
      expect(m.flagged).toBe(true);
      expect(JSON.stringify(m)).not.toContain("plain");
    }
  });

  it("an embedded JSON string over 64 KiB of UTF-8, which the server replaces, is hidden and flags the record", () => {
    const ascii = JSON.stringify({ note: "x".repeat(66_000) });
    // 40,000 two-byte characters: under 64 Ki UTF-16 units, over 64 KiB as the server counts them.
    const wide = JSON.stringify({ note: "é".repeat(40_000) });
    for (const text of [ascii, wide]) {
      const m = model({ body: text });
      expect(body(m)).toEqual({ kind: "secret_named" });
      expect(m.flagged).toBe(true);
    }
    // At the bound itself the string is still read.
    const at = JSON.stringify({ note: "x".repeat(64 * 1024 - 11) });
    expect(at.length).toBe(64 * 1024);
    expect(body(model({ body: at }))?.kind).toBe("value");
  });
});

describe("auditDiffModel: one strict marker rule for the leaf and the flag (S-5520-04, C-5520-03)", () => {
  const model = (value: Record<string, unknown>) =>
    auditDiffModel(
      entry({
        action: "orders.submit",
        subject_type: "order",
        detail: { before: null, after: value },
      }),
    );
  const kindOf = (value: Record<string, unknown>) =>
    model(value).fields.find((f) => f.path.join("/") === Object.keys(value)[0])?.after;

  it("a personal marker is the prefix and a 64-hex digest, nothing else", () => {
    expect(kindOf({ note: `${AUDIT_MARKERS.personal}${HEX}` })).toEqual({
      kind: "personal",
      hex8: "a3f1c2d4",
    });
    for (const text of [
      `${AUDIT_MARKERS.personal}not-a-hex-digest`,
      `${AUDIT_MARKERS.personal}${HEX.slice(0, 63)}`,
      `${AUDIT_MARKERS.personal}${HEX.toUpperCase()}`,
    ]) {
      // No marker the server writes: under a plain name it is the value as served, and flags nothing.
      expect(kindOf({ note: text })).toMatchObject({ kind: "value", text });
      expect(model({ note: text }).flagged).toBe(false);
    }
  });

  it.each([
    ["a malformed personal marker", `${AUDIT_MARKERS.personal}hunter2`],
    ["a well-formed personal marker", `${AUDIT_MARKERS.personal}${HEX}`],
    ["the credential marker", AUDIT_MARKERS.credential],
    ["the oversize marker", AUDIT_MARKERS.oversize],
  ])(
    "under a secret name, %s is not what the server writes there: hidden, the record flagged",
    (_n, text) => {
      expect(kindOf({ password: text })).toEqual({ kind: "secret_named" });
      expect(model({ password: text }).flagged).toBe(true);
    },
  );

  it("under a secret name the server's own marker reads as the secret it replaced", () => {
    expect(kindOf({ password: AUDIT_MARKERS.secret })).toEqual({ kind: "secret" });
    expect(model({ password: AUDIT_MARKERS.secret }).flagged).toBe(false);
  });

  it("kek_version keeps a version under 10^9 only (redact.py's _VERSION_INT_LIMIT)", () => {
    expect(kindOf({ kek_version: 999_999_999 })).toMatchObject({ kind: "value", numeric: true });
    expect(kindOf({ kek_version: "999999999" })).toMatchObject({ kind: "value" });
    for (const value of [1_000_000_000, "1000000000", 0, -3, 2.5]) {
      expect(kindOf({ kek_version: value }), String(value)).toEqual({ kind: "secret_named" });
      expect(model({ kek_version: value }).flagged).toBe(true);
    }
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
