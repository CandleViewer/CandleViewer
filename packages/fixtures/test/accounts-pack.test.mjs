// E27-Q01 (#833): the accounts fault-injection pack checks. CI runs this suite through the
// package `lint` script (`eslint`, then `scripts/verify.mjs`, then `vitest run`), which the js
// lane's `lint` job schedules whenever a file in this package changes; the js unit-test jobs
// filter to other packages. Planted failures run on a temporary copy; nothing planted is
// committed.
import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import {
  ACCOUNTS_DIR,
  MIXED_CASE_MIN,
  PLAN_SCENARIOS,
  applyMergePatch,
  assertSupportedSchema,
  checkPack,
  findCredentialFields,
  findKeyShapedTokens,
  readPack,
  validateSchema,
} from "../scripts/accounts-pack.mjs";
import { KEY_SHAPE_DIRS, SCAN_DIRS, runVerify, verifyDirectories } from "../scripts/verify.mjs";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const verifyScript = join(packageRoot, "scripts", "verify.mjs");

/**
 * Test plan section 9.3 (#833 PR 1, final at 71435bb4), in table order: an independent pin of
 * `PLAN_SCENARIOS`.
 */
const EXPECTED_SCENARIOS = [
  "compliant",
  "compliant_alt",
  "withdraw_enabled",
  "transfer_enabled",
  "subtransfer_enabled",
  "subtransfer_list_enabled",
  "fiat_p2p_enabled",
  "fiat_bitpay_enabled",
  "fiat_convert_broker_enabled",
  "bitcard_enabled",
  "ip_missing",
  "ip_mismatch",
  "ip_extra_foreign",
  "ip_wildcard",
  "uid_mismatch",
  "non_uta",
  "clock_skew",
  "wallet_probe_error",
  "missing_trade_scope",
  "extra_scope_spot",
  "extra_scope_options",
  "extra_scope_exchange",
  "extra_scope_nft",
  "extra_scope_affiliate",
  "live_key_on_demo",
  "unknown_key",
  "stored_key_rejected",
  "demo_ws_unreachable",
  "expiring_13d",
  "expiring_15d",
  "expired_key",
  "new_key_48h",
  "bybit_5xx",
  "rate_limited_10018",
  "ws_auth_timeout",
  "ws_auth_then_drop",
  "ws_quiet",
  "ws_quiet_rest_fail",
  "ws_drop_rest_fail",
  "ws_blip_20s",
  "rotation_ok",
  "rotation_new_key_withdraw",
  "key_delete_5xx",
  "close_rejected",
  "leverage_ok",
  "leverage_refused_open_position",
  "open_position_btcusdt_5x_sl",
  "working_orders_2",
  "history_round_trip",
];

/** A key-shaped token built at run time, so no key-shaped literal sits in this file. */
const keyLike = (length) => Array.from({ length }, (_, i) => "aB3"[i % 3]).join("");
/** Letters only, alternating case: as many capitals as small letters. */
const lettersLike = (length) => Array.from({ length }, (_, i) => "aB"[i % 2]).join("");
/** Letters only, with exactly `capitals` capitals, then small letters. */
const capitalsThenSmall = (capitals, length) =>
  "Q".repeat(capitals) + "q".repeat(length - capitals);

it("pins the section 9.3 list twice: in the checks and in this file", () => {
  expect([...PLAN_SCENARIOS]).toEqual(EXPECTED_SCENARIOS);
  expect(Object.isFrozen(PLAN_SCENARIOS)).toBe(true);
});

describe("findKeyShapedTokens", () => {
  it.each([18, 19, 20])("flags a bare %i-char key-shaped token", (length) => {
    const hits = findKeyShapedTokens(`{"note": "${keyLike(length)}"}`);
    expect(hits).toEqual([{ index: 10, length, shape: "api-key" }]);
  });

  it("flags a bare 36-char secret-shaped token in prose", () => {
    expect(findKeyShapedTokens(`secret ${keyLike(36)}.`)).toEqual([
      { index: 7, length: 36, shape: "api-secret" },
    ]);
  });

  it.each([18, 20, 36])("flags a letters-only %i-char token that mixes case like a key", (n) => {
    expect(findKeyShapedTokens(`"${lettersLike(n)}"`)).toHaveLength(1);
    expect(findKeyShapedTokens(`"${capitalsThenSmall(MIXED_CASE_MIN, 18)}"`)).toHaveLength(1);
  });

  it.each([
    ["too few capitals", capitalsThenSmall(MIXED_CASE_MIN - 1, 18)],
    ["too few small letters", capitalsThenSmall(18 - MIXED_CASE_MIN + 1, 18)],
    ["a camelCase field name", "unifiedMarginStatus"],
    ["a camelCase field name", "availableToWithdraw"],
    ["a PascalCase permission name", "SubMemberTransferLis"],
    ["all capitals", "Q".repeat(20)],
  ])("passes a letters-only token with %s", (_label, text) => {
    expect(findKeyShapedTokens(`"${text}"`)).toEqual([]);
  });

  it("never echoes the token it found", () => {
    const token = keyLike(20);
    const hits = findKeyShapedTokens(`X ${token} Y`);
    expect(hits).toHaveLength(1);
    expect(JSON.stringify(hits)).not.toContain(token);
  });

  it.each([
    ["a UUID", "00000000-0000-4000-8000-000000000001"],
    ["a sha256 digest", "ab".repeat(32)],
    ["epoch milliseconds", "1792141200000"],
    ["epoch nanoseconds", "1700000000123456789"],
    ["a fixture key id", "fixture-withdraw_enabled-0003"],
    ["a fixture secret", "fixture-withdraw_enabled-secret-not-real"],
    ["a dummy-prefixed id", `DUMMYKEY_${keyLike(18)}`],
    ["a hyphen-joined token", `${keyLike(10)}-${keyLike(9)}`],
    ["digits only, 20 chars", "12345678901234567890"],
    ["17 chars", keyLike(17)],
    ["21 chars", keyLike(21)],
    ["35 chars", keyLike(35)],
    ["37 chars", keyLike(37)],
  ])("passes %s", (_label, text) => {
    expect(findKeyShapedTokens(`"${text}"`)).toEqual([]);
  });
});

describe("findCredentialFields", () => {
  it("accepts redacted credential fields, as the exchange replies carry them", () => {
    expect(findCredentialFields({ result: { apiKey: "***", secret: "", password: null } })).toEqual(
      [],
    );
  });

  it("flags any value under a credential-like name, at any depth", () => {
    const value = { a: [{ api_key: "fixture-x" }], Signature: 1, token: { inner: "x" } };
    expect(findCredentialFields(value)).toEqual(["$.a[0].api_key", "$.Signature", "$.token"]);
  });

  it("ignores names that merely contain a credential word", () => {
    expect(findCredentialFields({ key_id: "fixture-compliant-0001", tokens: 3 })).toEqual([]);
  });
});

describe("applyMergePatch (RFC 7396 appendix A)", () => {
  it.each([
    [{ a: "b" }, { a: "c" }, { a: "c" }],
    [{ a: "b" }, { b: "c" }, { a: "b", b: "c" }],
    [{ a: "b" }, { a: null }, {}],
    [{ a: "b", b: "c" }, { a: null }, { b: "c" }],
    [{ a: ["b"] }, { a: "c" }, { a: "c" }],
    [{ a: "c" }, { a: ["b"] }, { a: ["b"] }],
    [{ a: { b: "c" } }, { a: { b: "d", c: null } }, { a: { b: "d" } }],
    [{ a: [{ b: "c" }] }, { a: [1] }, { a: [1] }],
    [
      ["a", "b"],
      ["c", "d"],
      ["c", "d"],
    ],
    [{ a: "b" }, ["c"], ["c"]],
    [{ a: "foo" }, null, null],
    [{ a: "foo" }, "bar", "bar"],
    [{ e: null }, { a: 1 }, { e: null, a: 1 }],
    [[1, 2], { a: "b", c: null }, { a: "b" }],
    [{}, { a: { bb: { ccc: null } } }, { a: { bb: {} } }],
  ])("%j + %j = %j", (target, patch, result) => {
    expect(applyMergePatch(target, patch)).toEqual(result);
  });

  it("mutates neither input", () => {
    const target = { a: { b: 1 } };
    const patch = { a: { c: 2 } };
    applyMergePatch(target, patch);
    expect(target).toEqual({ a: { b: 1 } });
    expect(patch).toEqual({ a: { c: 2 } });
  });
});

describe("validateSchema (the subset the manifest schema uses)", () => {
  const schema = {
    type: "object",
    additionalProperties: false,
    required: ["n"],
    properties: {
      n: { type: "integer", minimum: 1 },
      s: { type: "string", pattern: "^x", minLength: 2 },
      e: { enum: ["a", "b"] },
      c: { const: true },
      list: { type: "array", minItems: 1, items: { $ref: "#/$defs/name" } },
      either: { type: ["integer", "null"] },
      num: { type: "number" },
      open: { type: "object", additionalProperties: { type: "boolean" } },
    },
    patternProperties: { "^p_": { type: "string" } },
    $defs: { name: { type: "string", description: "annotations are ignored" } },
  };

  it("accepts a conforming value", () => {
    const value = { n: 2, s: "xy", e: "a", c: true, list: ["q"], either: null, num: 1.5 };
    expect(validateSchema(schema, { ...value, open: { k: true }, p_x: "v" })).toEqual([]);
  });

  it.each([
    [{}, 'missing required property "n"'],
    [{ n: 0 }, "below the minimum 1"],
    [{ n: 1.5 }, "expected integer"],
    [{ n: 1, s: "y" }, "does not match"],
    [{ n: 1, s: "x" }, "shorter than 2"],
    [{ n: 1, e: "z" }, "must be one of"],
    [{ n: 1, c: false }, "must equal true"],
    [{ n: 1, list: [] }, "fewer than 1 items"],
    [{ n: 1, list: [3] }, "$.list[0]: expected string"],
    [{ n: 1, either: "x" }, "expected integer or null"],
    [{ n: 1, open: { k: 1 } }, "$.open.k: expected boolean"],
    [{ n: 1, p_x: 1 }, "$.p_x: expected string"],
    [{ n: 1, extra: 1 }, 'unexpected property "extra"'],
    ["text", "expected object, got string"],
  ])("rejects %j", (value, message) => {
    const errors = validateSchema(schema, value);
    expect(errors.join("\n")).toContain(message);
  });

  it("fails closed on a keyword it does not implement", () => {
    expect(() => validateSchema({ oneOf: [] }, 1)).toThrow(/unsupported JSON Schema keyword/);
  });

  it("fails closed on a dangling or remote $ref", () => {
    expect(() => validateSchema({ $ref: "#/$defs/none" }, 1)).toThrow(/\$ref/);
    expect(() => validateSchema({ $ref: "https://example.invalid/x" }, 1)).toThrow(/\$ref/);
  });

  it.each([
    ["a property no value reaches", { properties: { a: {}, b: { oneOf: [] } } }],
    ["an unused definition", { $defs: { unused: { not: {} } } }],
    ["a pattern property", { patternProperties: { "^x": { anyOf: [] } } }],
    ["additionalProperties", { additionalProperties: { if: {} } }],
    ["items", { items: { prefixItems: [] } }],
  ])("walks the whole schema: an unknown keyword under %s fails", (_label, schema) => {
    expect(() => validateSchema(schema, {})).toThrow(/unsupported JSON Schema keyword/);
  });

  it("fails on a $ref with a sibling keyword the validator would skip", () => {
    const schema = { properties: { a: { $ref: "#/$defs/n", type: "string" } }, $defs: { n: {} } };
    expect(() => validateSchema(schema, {})).toThrow(/\$ref at #\/properties\/a has sibling/);
  });

  it("accepts annotations beside a $ref, as the manifest schema uses them", () => {
    const schema = { properties: { a: { $ref: "#/$defs/n", description: "x" } }, $defs: { n: {} } };
    expect(() => assertSupportedSchema(schema)).not.toThrow();
  });

  it("fails on a schema node that is not an object", () => {
    expect(() => assertSupportedSchema({ properties: { a: true } })).toThrow(/not an object/);
  });
});

describe("the accounts pack", () => {
  it("holds every section 9.3 scenario and passes every pack check", () => {
    expect(checkPack(ACCOUNTS_DIR, { expectedScenarios: EXPECTED_SCENARIOS })).toEqual([]);
  });

  it("passes the gate the package lint script runs (redaction, key shapes, pack checks)", () => {
    const { files, findings, packProblems } = runVerify();
    expect({ findings, packProblems }).toEqual({ findings: [], packProblems: [] });
    expect(files).toContain(join(ACCOUNTS_DIR, "README.md"));
  });

  it("is wired into the package lint script, the step CI's lint job runs, with this suite", () => {
    const { scripts } = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));
    expect(scripts.lint).toBe(
      "eslint . --max-warnings=0 && node ./scripts/verify.mjs && vitest run",
    );
    const turbo = JSON.parse(readFileSync(join(packageRoot, "turbo.json"), "utf8"));
    // The data and these test files are lint inputs, so no cached lint run can skip a change.
    expect(turbo.tasks.lint.inputs).toEqual(
      expect.arrayContaining(["**/*.{ts,tsx,js,mjs,cjs,json}", "accounts/**", "bybit/**"]),
    );
  });

  it.each(EXPECTED_SCENARIOS)("%s/manifest.json matches manifest.schema.json", (name) => {
    const { schema, manifests } = readPack();
    expect(validateSchema(schema, manifests.get(name))).toEqual([]);
  });

  it("is inside the package redaction gate, and the gate passes over the whole package", () => {
    const { files, findings } = verifyDirectories(SCAN_DIRS, KEY_SHAPE_DIRS);
    expect(findings).toEqual([]);
    expect(KEY_SHAPE_DIRS).toEqual([ACCOUNTS_DIR]);
    expect(files).toContain(join(ACCOUNTS_DIR, "compliant", "manifest.json"));
    expect(files).toContain(join(ACCOUNTS_DIR, "_base", "query_api.json"));
  });
});

describe("planted failures on a copy of the pack", () => {
  let sandbox;
  const pack = () => join(sandbox, "accounts");
  const at = (...parts) => join(pack(), ...parts);
  const read = (...parts) => JSON.parse(readFileSync(at(...parts), "utf8"));
  const write = (value, ...parts) => writeFileSync(at(...parts), JSON.stringify(value, null, 2));
  const edit = (name, change) => {
    const manifest = read(name, "manifest.json");
    change(manifest);
    write(manifest, name, "manifest.json");
  };
  const problems = () => checkPack(pack(), { expectedScenarios: EXPECTED_SCENARIOS }).join("\n");
  /** Runs the CLI over the sandbox as the lint script would: `{ status, stderr }`. */
  const cli = () => {
    try {
      execFileSync("node", [verifyScript, sandbox], { stdio: "pipe" });
      return { status: 0, stderr: "" };
    } catch (error) {
      return { status: error.status, stderr: error.stderr.toString() };
    }
  };

  const copyPack = () => {
    sandbox = mkdtempSync(join(tmpdir(), "accounts-pack-"));
    cpSync(ACCOUNTS_DIR, pack(), { recursive: true });
    const corpus = join("bybit", "2026-10-05", "rest");
    cpSync(join(packageRoot, corpus), join(sandbox, corpus), { recursive: true });
  };

  afterEach(() => rmSync(sandbox, { recursive: true, force: true }));

  it("the unmodified copy is sound, so each plant below is what fails", () => {
    copyPack();
    expect(problems()).toBe("");
    expect(runVerify(sandbox).packProblems).toEqual([]);
    expect(cli().status).toBe(0);
  });

  it("makes the lint gate (verify.mjs) exit 1 on a planted bad manifest", () => {
    copyPack();
    edit("withdraw_enabled", (m) => (m.extra = 1));
    const { status, stderr } = cli();
    expect(status).toBe(1);
    expect(stderr).toContain('accounts/withdraw_enabled: $: unexpected property "extra"');
  });

  it("makes the lint gate (verify.mjs) exit 1 on a planted key, without printing it", () => {
    copyPack();
    const token = keyLike(20);
    edit("compliant", (m) => (m.description = `pasted ${token} by mistake`));
    const { status, stderr } = cli();
    expect(status).toBe(1);
    expect(stderr).toContain("accounts/compliant/manifest.json: matched");
    expect(stderr).not.toContain(token);
  });

  it("makes the lint gate fail closed when the pack is missing", () => {
    copyPack();
    rmSync(pack(), { recursive: true });
    expect(runVerify(sandbox).packProblems).toEqual(["the pack cannot be read (ENOENT)"]);
  });

  it("fails on a schema the validator cannot fully apply, before any manifest", () => {
    copyPack();
    const schema = read("manifest.schema.json");
    schema.$defs.unused = { oneOf: [] };
    write(schema, "manifest.schema.json");
    expect(problems()).toMatch(/^manifest\.schema\.json: unsupported JSON Schema keyword "oneOf"/);
  });

  it.each([
    ["an unknown manifest property", (m) => (m.extra = 1), 'unexpected property "extra"'],
    ["a scenario name unlike its directory", (m) => (m.scenario = "other"), "is not its directory"],
    ["a key id of another scenario", (m) => (m.tester_inputs.key_id = "fixture-x-0099"), "key_id"],
    [
      "a repeated key id tail",
      (m) => (m.tester_inputs.key_id = "fixture-ip_missing-0001"),
      "repeats",
    ],
    [
      "a credential-named merge-patch value",
      (m) => (m.rest["GET /v5/user/query-api"].merge_patch.result.apiKey = "fixture-not-a-key"),
      "credential-named field",
    ],
    [
      "a missing payload file",
      (m) => (m.rest["GET /v5/user/query-api"].payload = "_base/missing.json"),
      "unreadable",
    ],
    ["an extends cycle", (m) => (m.extends = "ip_missing"), "extends cycle"],
    ["an unknown parent", (m) => (m.extends = "no_such_scenario"), "extends unknown scenario"],
    [
      "a reply without a payload",
      (m) => (m.ws = { private: { on_auth: { do: "reply" } } }),
      "payload exactly when it replies",
    ],
    [
      "an empty REST window",
      (m) => (m.rest["*"] = { payload: "_base/error_10003.json", from_ms: 5, until_ms: 5 }),
      "empty time window",
    ],
  ])("fails on %s", (_label, change, message) => {
    copyPack();
    edit("ip_missing", change);
    expect(problems()).toContain(message);
  });

  it("fails on a bare key-shaped token anywhere in the pack, in both gates", () => {
    copyPack();
    const body = read("_base", "fee_rate.json");
    body.result.list[0].note = keyLike(20);
    write(body, "_base", "fee_rate.json");
    expect(problems()).toContain("_base/fee_rate.json: bare api-key-shaped token");
    const { findings } = verifyDirectories([pack()], [pack()]);
    expect(findings).toHaveLength(1);
    expect(findings[0].pattern).toMatch(/^bare api-key-shaped token at offset \d+$/);
  });

  it("fails on a credential-shaped field that the generic redaction gate also flags", () => {
    copyPack();
    const body = read("_base", "query_api.json");
    body.result.apiKey = "fixture-compliant-0001";
    write(body, "_base", "query_api.json");
    expect(problems()).toContain("credential-named field $.result.apiKey holds a value");
    const { findings } = verifyDirectories([pack()]);
    expect(findings.map((f) => f.pattern)).toContain("Bybit-style api key/secret field");
  });

  it("fails when a section 9.3 scenario is missing", () => {
    copyPack();
    rmSync(at("ws_blip_20s"), { recursive: true });
    expect(problems()).toContain("pack: missing scenarios ws_blip_20s");
  });

  it("fails on a scenario directory without a manifest, and on an extra scenario", () => {
    copyPack();
    cpSync(at("_base"), at("stray"), { recursive: true });
    expect(problems()).toContain("stray: no manifest.json");
    expect(problems()).toContain("pack: unexpected scenarios stray");
  });

  it("fails on a payload no manifest references", () => {
    copyPack();
    write({ retCode: 0 }, "_base", "orphan.json");
    expect(problems()).toContain("_base/orphan.json: no manifest references it");
  });

  it("fails on a file that is not valid JSON", () => {
    copyPack();
    writeFileSync(at("_base", "fee_rate.json"), "{ not json");
    expect(problems()).toContain("_base/fee_rate.json: not valid JSON");
    expect(problems()).toContain("payload _base/fee_rate.json is unreadable (SyntaxError)");
  });

  it("fails when the base scenario stops answering intake or loses a WS reaction", () => {
    copyPack();
    edit("compliant", (m) => {
      delete m.rest["GET /v5/user/query-api"];
      delete m.ws.private.on_ping;
      delete m.clock.server_offset_ms;
    });
    expect(problems()).toContain('expiring_13d: nothing answers "GET /v5/user/query-api" at 0 ms');
    expect(problems()).toContain("ws_quiet: ws.private lacks on_ping");
    expect(problems()).toContain("non_uta: clock lacks server_offset_ms");
  });

  it("fails on a rotation pair that carries stubs, a key id or names a rotation pair", () => {
    copyPack();
    edit("rotation_ok", (m) => {
      m.rotation.new_key = "rotation_new_key_withdraw";
      m.tester_inputs.key_id = "fixture-rotation_ok-0099";
      m.clock = { server_offset_ms: 0 };
    });
    edit("rotation_new_key_withdraw", (m) => (m.rotation.new_key = "compliant"));
    const found = problems();
    expect(found).toContain("rotation_ok: a rotation pair carries no clock");
    expect(found).toContain("rotation_ok: a rotation pair has no key id of its own");
    expect(found).toContain('"rotation_new_key_withdraw", which is not a key scenario');
    expect(found).toContain("rotation_new_key_withdraw: rotation old and new key are one scenario");
  });

  it("fails on a scenario that extends a rotation pair", () => {
    copyPack();
    edit("ip_missing", (m) => (m.extends = "rotation_ok"));
    expect(problems()).toContain("ip_missing: extends a rotation pair");
  });

  it("fails on an overlay that carries key fields, answers '*' or records a verdict", () => {
    copyPack();
    edit("working_orders_2", (m) => {
      m.extends = "compliant";
      m.tester_inputs = { account_uid: "90000001" };
      m.rest["*"] = { payload: "_base/order_ack.json" };
      m.expected.verification = "passed";
    });
    const found = problems();
    expect(found).toContain("working_orders_2: an overlay carries no extends, tester_inputs");
    expect(found).toContain('working_orders_2: an overlay never answers "*"');
    expect(found).toContain("working_orders_2: an overlay records no verification");
  });

  it("fails on an overlay that stubs nothing", () => {
    copyPack();
    edit("history_round_trip", (m) => (m.rest = {}));
    expect(problems()).toContain("history_round_trip: an overlay stubs at least one call");
  });

  it("fails on a key scenario that extends an overlay, or a rotation that names one", () => {
    copyPack();
    edit("ip_missing", (m) => (m.extends = "working_orders_2"));
    edit("rotation_ok", (m) => (m.rotation.new_key = "history_round_trip"));
    const found = problems();
    expect(found).toContain("ip_missing: extends an overlay");
    expect(found).toContain('"history_round_trip", which is not a key scenario');
  });

  it("fails on a key scenario or a rotation pair without tester_inputs", () => {
    copyPack();
    edit("ip_missing", (m) => delete m.tester_inputs);
    edit("rotation_ok", (m) => delete m.tester_inputs);
    const found = problems();
    expect(found).toContain("ip_missing: a key scenario has tester_inputs");
    expect(found).toContain("rotation_ok: a rotation pair names its account in tester_inputs");
  });

  it.each([
    ["itself", "stored_key_rejected"],
    ["an overlay", "working_orders_2"],
    ["a rotation pair", "rotation_ok"],
    ["an unknown scenario", "no_such_scenario"],
  ])("fails on a switch_to that names %s", (_label, target) => {
    copyPack();
    edit("stored_key_rejected", (m) => (m.switch_to = target));
    expect(problems()).toContain(`stored_key_rejected: switch_to names "${target}"`);
  });

  it("fails on a switch to a scenario that switches again", () => {
    copyPack();
    edit("live_key_on_demo", (m) => (m.switch_to = "compliant"));
    expect(problems()).toContain('switch_to names "live_key_on_demo"');
  });

  it("fails when no egress IP resolves, and on an egress outside RFC 5737", () => {
    copyPack();
    edit("compliant", (m) => delete m.egress_ip);
    expect(problems()).toContain("non_uta: no egress_ip resolves through extends");
    edit("compliant", (m) => (m.egress_ip = "100.64.0.7"));
    expect(problems()).toContain("compliant: $.egress_ip: does not match");
  });

  it("accepts a lettered case id and refuses any other suffix", () => {
    copyPack();
    edit("ip_wildcard", (m) => (m.expected.cases = ["E27-TC-106b"]));
    expect(problems()).toBe("");
    edit("ip_wildcard", (m) => (m.expected.cases = ["E27-TC-106B"]));
    expect(problems()).toContain("ip_wildcard: $.expected.cases[0]: does not match");
  });

  it("fails on a payload path that leaves the pack, even if the schema were loosened", () => {
    copyPack();
    const schema = read("manifest.schema.json");
    schema.$defs.payloadPath.pattern = "^.+$";
    write(schema, "manifest.schema.json");
    edit("ip_missing", (m) => (m.rest["GET /v5/user/query-api"].payload = "../../outside.json"));
    expect(problems()).toContain("is outside the pack and the shared corpus");
  });

  it("fails on a merge patch that is not an object, even if the schema were loosened", () => {
    copyPack();
    const schema = read("manifest.schema.json");
    schema.$defs.restStub.properties.merge_patch = { description: "loosened for the plant" };
    write(schema, "manifest.schema.json");
    edit(
      "ip_missing",
      (m) => (m.rest["GET /v5/user/query-api"].merge_patch = ["not", "an object"]),
    );
    expect(problems()).toContain(
      "the merge patch on _base/query_api.json does not yield an object",
    );
  });

  it("fails on a manifest that is not even an object", () => {
    copyPack();
    unlinkSync(at("ip_missing", "manifest.json"));
    writeFileSync(at("ip_missing", "manifest.json"), "null");
    expect(problems()).toContain("ip_missing: $: expected object, got null");
  });
});
