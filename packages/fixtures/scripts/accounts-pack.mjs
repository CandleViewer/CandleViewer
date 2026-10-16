// E27-Q01 (#833) fault-injection fixture pack checks: the manifest schema subset, RFC 7396
// merge patches, the bare-key shape scan and the pack's structural rules. Pure Node, no
// network, no dependency beyond the standard library (a new dependency needs CODEOWNER
// review). In CI they run through the package `lint` script (`scripts/verify.mjs` calls
// `checkPack`): the js lane's lint job schedules this package whenever it changes, while its
// unit-test jobs never do (no package depends on it). `scripts/check_secrets_hygiene.py` carries
// the same key-shape rule into the security lane. See accounts/README.md, "Checks".
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
export const ACCOUNTS_DIR = join(packageRoot, "accounts");

// ---------------------------------------------------------------------------------------------
// Key-shape scan. A Bybit API key is a bare alphanumeric token of 18-20 characters and a secret
// one of 36. The pack's ids are hyphenated by rule (`fixture-<scenario>-NNNN`), so a token is
// a maximal run of letters, digits, `_` and `-`, and only a run made of letters and digits
// counts. It counts when it holds a digit, or, letters only, when it mixes at least
// MIXED_CASE_MIN capitals and as many small letters: camelCase field and permission names of
// that length carry far fewer capitals, while about 9 in 10 letters-only random keys carry more.
// Hits report position and length only: echoing the token would print a real credential into
// the CI log. `scripts/check_secrets_hygiene.py` (`scan_key_shapes`) implements the same rule.
// A tripwire for accidental pastes, not a complete control: a key split by a JSON escape or
// glued to a hyphen is not a bare token.
const TOKEN = /[A-Za-z0-9_-]+/g;
const ALNUM = /^[A-Za-z0-9]+$/;
const LETTER = /[A-Za-z]/;
const DIGIT = /[0-9]/;
export const MIXED_CASE_MIN = 6;

function keyShape(length) {
  if (length >= 18 && length <= 20) return "api-key";
  if (length === 36) return "api-secret";
  return null;
}

function countOf(token, regex) {
  return token.match(regex)?.length ?? 0;
}

function looksLikeKey(token) {
  if (!ALNUM.test(token) || !LETTER.test(token)) return false;
  if (DIGIT.test(token)) return true;
  return countOf(token, /[A-Z]/g) >= MIXED_CASE_MIN && countOf(token, /[a-z]/g) >= MIXED_CASE_MIN;
}

/** Bare key- or secret-shaped tokens in `text`: `{ index, length, shape }`, never the token. */
export function findKeyShapedTokens(text) {
  const hits = [];
  for (const match of text.matchAll(TOKEN)) {
    const token = match[0];
    const shape = keyShape(token.length);
    if (shape && looksLikeKey(token)) {
      hits.push({ index: match.index, length: token.length, shape });
    }
  }
  return hits;
}

// ---------------------------------------------------------------------------------------------
// Credential-named fields. Exchange replies carry `apiKey` and `secret` fields; the pack keeps
// them redacted (`***` or empty). Any other value under such a name is a finding.
const CREDENTIAL_NAME = /^(api[_-]?key|api[_-]?secret|secret|sign|signature|token|password)$/i;
const REDACTED_VALUES = new Set(["", "***"]);

function isRedacted(value) {
  return value === null || (typeof value === "string" && REDACTED_VALUES.has(value));
}

/** JSON paths whose property name is credential-like and whose value is not redacted. */
export function findCredentialFields(value, path = "$") {
  if (Array.isArray(value)) {
    return value.flatMap((item, i) => findCredentialFields(item, `${path}[${i}]`));
  }
  if (value === null || typeof value !== "object") return [];
  const hits = [];
  for (const [name, inner] of Object.entries(value)) {
    const at = `${path}.${name}`;
    if (CREDENTIAL_NAME.test(name) && !isRedacted(inner)) hits.push(at);
    hits.push(...findCredentialFields(inner, at));
  }
  return hits;
}

// ---------------------------------------------------------------------------------------------
// RFC 7396 JSON merge patch. Returns a new value; never mutates `target` or `patch`.
function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// Pack values are plain JSON, so a JSON round trip is a faithful deep copy.
function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

export function applyMergePatch(target, patch) {
  if (!isObject(patch)) return clone(patch);
  const out = isObject(target) ? clone(target) : {};
  for (const [name, value] of Object.entries(patch)) {
    if (value === null) delete out[name];
    else out[name] = applyMergePatch(out[name], value);
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// JSON Schema 2020-12, the subset `accounts/manifest.schema.json` uses. The whole schema is
// walked before any value is checked: an unknown keyword anywhere, or a `$ref` with a sibling
// keyword (2020-12 applies both; this validator follows the `$ref` alone), throws instead of
// being skipped, so the schema can never rely on a rule nothing checks.
const ANNOTATIONS = new Set(["$schema", "$id", "title", "description", "$defs"]);
const KEYWORDS = new Set([
  "type",
  "required",
  "properties",
  "patternProperties",
  "additionalProperties",
  "enum",
  "const",
  "pattern",
  "minLength",
  "minimum",
  "items",
  "minItems",
  "$ref",
]);

function jsonType(value) {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function typeMatches(expected, value) {
  const actual = jsonType(value);
  return expected === actual || (expected === "number" && actual === "integer");
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function resolveRef(root, ref) {
  const prefix = "#/$defs/";
  const target = ref.startsWith(prefix) ? root.$defs?.[ref.slice(prefix.length)] : undefined;
  if (target === undefined) throw new Error(`unsupported or dangling $ref ${ref}`);
  return target;
}

function subschemas(schema, path) {
  const named = (keyword) =>
    Object.entries(schema[keyword] ?? {}).map(([name, sub]) => [`${path}/${keyword}/${name}`, sub]);
  const children = [...named("properties"), ...named("patternProperties"), ...named("$defs")];
  if (isObject(schema.additionalProperties)) {
    children.push([`${path}/additionalProperties`, schema.additionalProperties]);
  }
  if (schema.items !== undefined) children.push([`${path}/items`, schema.items]);
  return children;
}

/**
 * Throws unless every node of `schema` uses only the keywords this validator implements and no
 * `$ref` carries a sibling other than an annotation. Visits every branch, reached or not.
 */
export function assertSupportedSchema(schema, path = "#") {
  if (!isObject(schema)) throw new Error(`schema node at ${path} is not an object`);
  for (const keyword of Object.keys(schema)) {
    if (!KEYWORDS.has(keyword) && !ANNOTATIONS.has(keyword)) {
      throw new Error(`unsupported JSON Schema keyword "${keyword}" at ${path}`);
    }
  }
  if (schema.$ref !== undefined) {
    const siblings = Object.keys(schema).filter((k) => k !== "$ref" && !ANNOTATIONS.has(k));
    if (siblings.length > 0) {
      throw new Error(`$ref at ${path} has sibling keyword(s) ${siblings.join(", ")}`);
    }
  }
  for (const [at, sub] of subschemas(schema, path)) assertSupportedSchema(sub, at);
}

function checkObject(schema, value, root, path) {
  const errors = [];
  for (const name of schema.required ?? []) {
    if (!Object.hasOwn(value, name)) errors.push(`${path}: missing required property "${name}"`);
  }
  const patterns = Object.entries(schema.patternProperties ?? {}).map(([p, s]) => [
    new RegExp(p, "u"),
    s,
  ]);
  for (const [name, inner] of Object.entries(value)) {
    const at = `${path}.${name}`;
    let evaluated = false;
    if (schema.properties && Object.hasOwn(schema.properties, name)) {
      evaluated = true;
      errors.push(...validateNode(schema.properties[name], inner, root, at));
    }
    for (const [regex, sub] of patterns) {
      if (regex.test(name)) {
        evaluated = true;
        errors.push(...validateNode(sub, inner, root, at));
      }
    }
    if (!evaluated && schema.additionalProperties === false) {
      errors.push(`${path}: unexpected property "${name}"`);
    } else if (!evaluated && isObject(schema.additionalProperties)) {
      errors.push(...validateNode(schema.additionalProperties, inner, root, at));
    }
  }
  return errors;
}

/** Errors (strings) for `value` against `schema`; `[]` when it conforms. Throws on a schema
 * the validator cannot fully apply (`assertSupportedSchema`). */
export function validateSchema(schema, value) {
  assertSupportedSchema(schema);
  return validateNode(schema, value, schema, "$");
}

function validateNode(schema, value, root, path) {
  if (schema.$ref !== undefined) {
    return validateNode(resolveRef(root, schema.$ref), value, root, path);
  }
  const errors = [];
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((t) => typeMatches(t, value))) {
      return [`${path}: expected ${types.join(" or ")}, got ${jsonType(value)}`];
    }
  }
  if (Object.hasOwn(schema, "const") && !deepEqual(schema.const, value)) {
    errors.push(`${path}: must equal ${JSON.stringify(schema.const)}`);
  }
  if (schema.enum !== undefined && !schema.enum.some((option) => deepEqual(option, value))) {
    errors.push(`${path}: must be one of ${JSON.stringify(schema.enum)}`);
  }
  if (typeof value === "string") {
    if (schema.pattern !== undefined && !new RegExp(schema.pattern, "u").test(value)) {
      errors.push(`${path}: does not match ${schema.pattern}`);
    }
    if (schema.minLength !== undefined && [...value].length < schema.minLength) {
      errors.push(`${path}: shorter than ${schema.minLength}`);
    }
  }
  if (typeof value === "number" && schema.minimum !== undefined && value < schema.minimum) {
    errors.push(`${path}: below the minimum ${schema.minimum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) {
      errors.push(`${path}: fewer than ${schema.minItems} items`);
    }
    if (schema.items !== undefined) {
      value.forEach((item, i) =>
        errors.push(...validateNode(schema.items, item, root, `${path}[${i}]`)),
      );
    }
  }
  if (isObject(value)) errors.push(...checkObject(schema, value, root, path));
  return errors;
}

// ---------------------------------------------------------------------------------------------
// The pack.

/**
 * The rows of the test plan's section 9.3 (`qa/plans/e27-accounts-test-plan.md`, #833 PR 1, final
 * text at 71435bb4), in table order: 46 scenarios, then the 3 overlays. The pack holds exactly
 * these. `test/accounts-pack.test.mjs` and the Python suite each pin their own copy.
 */
export const PLAN_SCENARIOS = Object.freeze([
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
]);

const BASE_DIR = "_base";
const PACK_DOCS = new Set(["README.md", "manifest.schema.json", "accounts.json"]);
const MANIFEST = "manifest.json";
const OVERLAY = "overlay";
const REACTIONS = ["on_auth", "on_subscribe", "on_ping"];
const WS_FIELDS = ["on_connect", ...REACTIONS, "after_auth", "timeline"];
const CLOCK_FIELDS = ["server_offset_ms", "key_created_offset_ms", "key_expires_offset_ms"];
const INTAKE_CALLS = ["GET /v5/user/query-api", "GET /v5/account/wallet-balance"];
/** What only a key scenario carries: an overlay seeds exchange-side state for any scenario. */
const OVERLAY_NEVER = [
  "extends",
  "switch_to",
  "rotation",
  "tester_inputs",
  "egress_ip",
  "clock",
  "ws",
];
const VERDICT_FIELDS = ["verification", "problem", "health"];

function listFilesUnder(dir) {
  const out = [];
  for (const entry of readdirSync(dir).sort()) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...listFilesUnder(full));
    else out.push(full);
  }
  return out;
}

function readJson(file) {
  return JSON.parse(readFileSync(file, "utf8"));
}

/** `{ schema, manifests }`: each scenario directory's parsed manifest (`undefined` if absent). */
export function readPack(dir = ACCOUNTS_DIR) {
  const schema = readJson(join(dir, "manifest.schema.json"));
  const manifests = new Map();
  for (const entry of readdirSync(dir).sort()) {
    if (entry === BASE_DIR || !statSync(join(dir, entry)).isDirectory()) continue;
    const file = join(dir, entry, MANIFEST);
    manifests.set(entry, statSync(file, { throwIfNoEntry: false }) ? readJson(file) : undefined);
  }
  return { schema, manifests };
}

/** The extends chain from `name` up, or a problem on a cycle or an unknown parent. */
function chainOf(name, manifests) {
  const names = [];
  for (let current = name; current !== undefined; current = manifests.get(current).extends) {
    if (names.includes(current)) return { problem: `extends cycle through "${current}"` };
    if (!isObject(manifests.get(current))) {
      return { problem: `extends unknown scenario "${current}"` };
    }
    names.push(current);
  }
  return { chain: names.map((n) => manifests.get(n)) };
}

/** Field-wise merge of `pick(manifest)` along the chain; the nearest scenario wins. */
function resolvedField(chain, pick) {
  const merged = {};
  for (const manifest of [...chain].reverse()) Object.assign(merged, pick(manifest));
  return merged;
}

/** Whether some scenario in the chain answers `call` at scenario time 0. */
function answersAtStart(chain, call) {
  for (const manifest of chain) {
    for (const key of [call, "*"]) {
      const stub = manifest.rest?.[key];
      if (stub !== undefined && (stub.from_ms ?? 0) === 0) return true;
    }
  }
  return false;
}

function payloadRefs(manifest) {
  const refs = Object.values(manifest.rest ?? {}).map((stub) => [stub.payload, stub.merge_patch]);
  const ws = manifest.ws?.private ?? {};
  for (const field of REACTIONS) {
    if (ws[field]?.payload !== undefined) refs.push([ws[field].payload, undefined]);
  }
  for (const send of ws.after_auth ?? []) refs.push([send.payload, send.merge_patch]);
  return refs;
}

function isOverlay(manifest) {
  return isObject(manifest) && manifest.origin === OVERLAY;
}

/** A manifest that resolves to one key: neither a rotation pair nor an overlay. */
function isKeyScenario(manifest) {
  return isObject(manifest) && manifest.rotation === undefined && !isOverlay(manifest);
}

function checkWindows(name, manifest) {
  const problems = [];
  for (const [call, stub] of Object.entries(manifest.rest ?? {})) {
    if ((stub.from_ms ?? 0) >= (stub.until_ms ?? Infinity)) {
      problems.push(`${name}: rest "${call}" has an empty time window`);
    }
  }
  return problems;
}

function checkRotation(name, manifest, manifests) {
  const problems = [];
  const own = ["extends", "switch_to", "egress_ip", "clock", "rest", "ws"].filter(
    (f) => manifest[f] !== undefined,
  );
  if (own.length > 0) problems.push(`${name}: a rotation pair carries no ${own.join(", ")}`);
  if (manifest.tester_inputs === undefined) {
    problems.push(`${name}: a rotation pair names its account in tester_inputs`);
  } else if (manifest.tester_inputs.key_id !== undefined) {
    problems.push(`${name}: a rotation pair has no key id of its own`);
  }
  const { old_key: oldKey, new_key: newKey } = manifest.rotation;
  if (oldKey === newKey) problems.push(`${name}: rotation old and new key are one scenario`);
  for (const side of [oldKey, newKey]) {
    if (!isKeyScenario(manifests.get(side))) {
      problems.push(`${name}: rotation names "${side}", which is not a key scenario`);
    }
  }
  return problems;
}

function checkOverlay(name, manifest) {
  const problems = [];
  const own = OVERLAY_NEVER.filter((f) => manifest[f] !== undefined);
  if (own.length > 0) problems.push(`${name}: an overlay carries no ${own.join(", ")}`);
  const calls = Object.keys(manifest.rest ?? {});
  if (calls.length === 0) problems.push(`${name}: an overlay stubs at least one call`);
  if (calls.includes("*")) problems.push(`${name}: an overlay never answers "*"`);
  const verdict = VERDICT_FIELDS.filter((f) => manifest.expected[f] !== undefined);
  if (verdict.length > 0) problems.push(`${name}: an overlay records no ${verdict.join(", ")}`);
  return [...problems, ...checkWindows(name, manifest)];
}

function checkSwitch(name, manifest, manifests) {
  const target = manifest.switch_to;
  if (target === undefined) return [];
  const resolved = manifests.get(target);
  if (target === name || !isKeyScenario(resolved) || resolved.switch_to !== undefined) {
    return [`${name}: switch_to names "${target}", not another key scenario without a switch`];
  }
  return [];
}

function checkKeyId(name, manifest, tails) {
  const keyId = manifest.tester_inputs.key_id;
  if (keyId === undefined || !keyId.startsWith(`fixture-${name}-`)) {
    return [`${name}: key_id must be fixture-${name}-NNNN`];
  }
  const tail = keyId.slice(-4);
  if (tails.has(tail)) return [`${name}: key id tail ${tail} repeats ${tails.get(tail)}'s`];
  tails.set(tail, name);
  return [];
}

function checkKeyScenario(name, manifest, manifests, tails) {
  if (manifest.tester_inputs === undefined) return [`${name}: a key scenario has tester_inputs`];
  const problems = checkKeyId(name, manifest, tails);
  const { chain, problem } = chainOf(name, manifests);
  if (problem !== undefined) return [...problems, `${name}: ${problem}`];
  if (chain.some((m) => m.rotation !== undefined))
    problems.push(`${name}: extends a rotation pair`);
  if (chain.some(isOverlay)) problems.push(`${name}: extends an overlay`);
  const clock = resolvedField(chain, (m) => m.clock);
  const noClock = CLOCK_FIELDS.filter((f) => !Object.hasOwn(clock, f));
  if (noClock.length > 0) problems.push(`${name}: clock lacks ${noClock.join(", ")}`);
  if (!chain.some((m) => m.egress_ip !== undefined)) {
    problems.push(`${name}: no egress_ip resolves through extends`);
  }
  const ws = resolvedField(chain, (m) => m.ws?.private);
  const noWs = WS_FIELDS.filter((f) => !Object.hasOwn(ws, f));
  if (noWs.length > 0) problems.push(`${name}: ws.private lacks ${noWs.join(", ")}`);
  for (const call of INTAKE_CALLS) {
    if (!answersAtStart(chain, call)) problems.push(`${name}: nothing answers "${call}" at 0 ms`);
  }
  for (const field of REACTIONS) {
    const reaction = manifest.ws?.private?.[field];
    if (reaction !== undefined && (reaction.do === "reply") !== (reaction.payload !== undefined)) {
      problems.push(`${name}: ws.private.${field} has a payload exactly when it replies`);
    }
  }
  return [...problems, ...checkSwitch(name, manifest, manifests), ...checkWindows(name, manifest)];
}

function checkPayloads(name, manifest, dir, referenced) {
  const problems = [];
  const corpusRoot = resolve(dir, "..", "bybit") + sep;
  for (const [ref, patch] of payloadRefs(manifest)) {
    const file = resolve(dir, ref);
    if (!file.startsWith(dir + sep) && !file.startsWith(corpusRoot)) {
      problems.push(`${name}: payload ${ref} is outside the pack and the shared corpus`);
      continue;
    }
    referenced.add(file);
    let body;
    try {
      body = readJson(file);
    } catch (error) {
      problems.push(`${name}: payload ${ref} is unreadable (${error.code ?? error.name})`);
      continue;
    }
    if (patch !== undefined && !isObject(applyMergePatch(body, patch))) {
      problems.push(`${name}: the merge patch on ${ref} does not yield an object`);
    }
  }
  return problems;
}

function scanFiles(dir, referenced) {
  const problems = [];
  for (const file of listFilesUnder(dir)) {
    const rel = relative(dir, file);
    const text = readFileSync(file, "utf8");
    for (const hit of findKeyShapedTokens(text)) {
      problems.push(`${rel}: bare ${hit.shape}-shaped token, ${hit.length} chars at ${hit.index}`);
    }
    if (rel.endsWith(".json")) {
      try {
        for (const at of findCredentialFields(JSON.parse(text))) {
          problems.push(`${rel}: credential-named field ${at} holds a value`);
        }
      } catch {
        problems.push(`${rel}: not valid JSON`);
      }
    }
    const isDoc = PACK_DOCS.has(rel) || rel.endsWith(`${sep}${MANIFEST}`);
    if (!isDoc && !referenced.has(file)) problems.push(`${rel}: no manifest references it`);
  }
  return problems;
}

/**
 * Every problem in the pack at `dir`, as `<where>: <what>`; `[]` means the pack is sound.
 * `expectedScenarios`, when given, must equal the set of scenario directories.
 */
export function checkPack(dir = ACCOUNTS_DIR, { expectedScenarios } = {}) {
  const root = resolve(dir);
  const { schema, manifests } = readPack(root);
  try {
    assertSupportedSchema(schema);
  } catch (error) {
    return [`manifest.schema.json: ${error.message}`];
  }
  const problems = [];
  const tails = new Map();
  const referenced = new Set();
  for (const [name, manifest] of manifests) {
    if (manifest === undefined) {
      problems.push(`${name}: no ${MANIFEST}`);
      continue;
    }
    const schemaErrors = validateSchema(schema, manifest);
    if (schemaErrors.length > 0) {
      problems.push(...schemaErrors.map((e) => `${name}: ${e}`));
      continue;
    }
    if (manifest.scenario !== name) {
      problems.push(`${name}: scenario "${manifest.scenario}" is not its directory name`);
    }
    let kindProblems;
    if (isOverlay(manifest)) kindProblems = checkOverlay(name, manifest);
    else if (manifest.rotation !== undefined)
      kindProblems = checkRotation(name, manifest, manifests);
    else kindProblems = checkKeyScenario(name, manifest, manifests, tails);
    problems.push(...kindProblems, ...checkPayloads(name, manifest, root, referenced));
  }
  if (expectedScenarios !== undefined) {
    const missing = expectedScenarios.filter((n) => !manifests.has(n));
    const extra = [...manifests.keys()].filter((n) => !expectedScenarios.includes(n));
    if (missing.length > 0) problems.push(`pack: missing scenarios ${missing.join(", ")}`);
    if (extra.length > 0) problems.push(`pack: unexpected scenarios ${extra.join(", ")}`);
  }
  return [...problems, ...scanFiles(root, referenced)];
}
