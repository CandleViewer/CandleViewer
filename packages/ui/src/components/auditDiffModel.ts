import type { generated } from "@candleviewer/protocol";

type AuditEntry = generated.rest.components["schemas"]["AuditEntry"];

/** What the model reads of an entry: the recorded `detail` and what tells its shape apart (E42-D04 §6). */
export type AuditDiffEntry = Pick<AuditEntry, "action" | "subject_type" | "outcome" | "detail"> & {
  readonly reason?: string | null;
  readonly entry_hash: string | null;
};

/**
 * The server's redaction markers (services/api/candleviewer/audit/redact.py, admin/flags/evidence.py). A marker is
 * the server's words for a value it never stored; the model maps each to its kind and shows none of them raw.
 */
export const AUDIT_MARKERS = {
  secret: "<redacted:secret>",
  credential: "<redacted:credential>",
  /** A prefix: the SHA-256 hex of the value follows. */
  personal: "<hashed:pii>:",
  oversize: "<redacted:oversize-json>",
} as const;

/**
 * A mirror of the redactor's name rules (redact.py's `_SECRET_FIELD_FRAGMENTS`, `_SECRET_EXACT_NAMES`,
 * `_SECRET_SUFFIXES`, `_OTP_MARKERS`, `_ENUM_PASS_THROUGH` and `_METADATA_VERSION_NAMES`), the server's normalised
 * names verbatim. No generated copy exists (CG-27), so test/auditDiffModel.test.ts reads redact.py and fails on any
 * drift (BQ-10). The client uses it for defence in depth only: a value under such a name that the server never writes
 * there is hidden, and its record's raw form withheld (E42-D04 §6, AD-3). Nothing here is hashed. `_PII_FIELD_NAMES`
 * is deliberately not mirrored: the server hashes those values at write, so they arrive as the personal marker.
 */
export const REDACTOR_NAME_RULES = {
  fragments: [
    "passwordhash",
    "password",
    "secret",
    "totpseed",
    "seed",
    "recoverycode",
    "refreshtoken",
    "accesstoken",
    "invitetoken",
    "apikey",
    "privatekey",
    "signature",
    "dek",
    "kek",
    "token",
    "hash",
  ],
  exactNames: [
    "key",
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "bearer",
    "credential",
    "credentials",
    "passphrase",
    "sign",
    "signature",
    "xbapisign",
    "xbapiapikey",
    "otp",
    "totp",
    "otpcode",
    "totpcode",
    "mfacode",
    "session",
    "sid",
    "sessionid",
    "jwt",
    "idtoken",
    "accesstoken",
    "refreshtoken",
    "privatekey",
  ],
  suffixes: ["_key", "_secret", "_token", "_password"],
  otpMarkers: ["otp", "totp", "mfa"],
  passThrough: { bearer: ["matched", "absent"] },
  versionNames: ["kekversion"],
  versionMaxDigits: 9,
} as const;

const FRAGMENTS: readonly string[] = REDACTOR_NAME_RULES.fragments;
const EXACT: ReadonlySet<string> = new Set(REDACTOR_NAME_RULES.exactNames);
const SUFFIXES: readonly string[] = REDACTOR_NAME_RULES.suffixes;
const OTP: readonly string[] = REDACTOR_NAME_RULES.otpMarkers;
const PASS_THROUGH: Readonly<Record<string, readonly string[]>> = REDACTOR_NAME_RULES.passThrough;
const VERSION_NAMES: ReadonlySet<string> = new Set(REDACTOR_NAME_RULES.versionNames);
const VERSION = new RegExp(`^[1-9][0-9]{0,${REDACTOR_NAME_RULES.versionMaxDigits - 1}}$`);
const VERSION_LIMIT = 10 ** REDACTOR_NAME_RULES.versionMaxDigits;

/** redact.py's `_normalise`: lowercased, every non-alphanumeric stripped. */
const normalise = (name: string): string => name.toLowerCase().replace(/[^a-z0-9]/g, "");
/** redact.py's `_snake`: camelCase and kebab-case folded to snake_case. */
const snake = (name: string): string =>
  name
    .replace(/(?<=[a-z0-9])(?=[A-Z])/g, "_")
    .toLowerCase()
    .replace(/-/g, "_");

/** redact.py's `_has_otp_sibling`: a key, or a string value, naming an OTP method. */
const hasOtpSibling = (mapping: Readonly<Record<string, unknown>>): boolean =>
  Object.entries(mapping).some(
    ([key, value]) =>
      OTP.some((marker) => normalise(key).includes(marker)) ||
      (typeof value === "string" && OTP.includes(normalise(value))),
  );

/**
 * Whether the server redacts a field by its name (redact.py's `_classify` as `secret`, and a `code` beside an OTP
 * marker), whatever the value. The exemptions are value-based: see `keptByServer`.
 */
export function isRedactedName(
  name: string,
  siblings?: Readonly<Record<string, unknown>>,
): boolean {
  const normal = normalise(name);
  if (EXACT.has(normal) || SUFFIXES.some((suffix) => snake(name).endsWith(suffix))) return true;
  if (FRAGMENTS.some((fragment) => normal.includes(fragment))) return true;
  return normal === "code" && siblings !== undefined && hasOtpSibling(siblings);
}

/** A value the server keeps under a redacted name: a pass-through word, or a version number (redact.py). */
function keptByServer(name: string, value: unknown): boolean {
  const normal = normalise(name);
  if (VERSION_NAMES.has(normal)) {
    if (typeof value === "number")
      return Number.isInteger(value) && value > 0 && value < VERSION_LIMIT;
    if (typeof value === "string" && VERSION.test(value)) return true;
  }
  const words = Object.hasOwn(PASS_THROUGH, normal) ? PASS_THROUGH[normal] : undefined;
  return typeof value === "string" && words !== undefined && words.includes(value);
}

/**
 * The one personal-data marker rule, for the leaf and the flag alike: the prefix and the 64-hex SHA-256 digest
 * redact.py's `_hash_pii` writes (lower case), nothing else. Any other text is no marker (S-5520-04).
 */
const PERSONAL = /^<hashed:pii>:[0-9a-f]{64}$/;

/**
 * What the server writes under a name it redacts: its secret marker, or a value it keeps there (a pass-through word, a
 * version number). Any other value there, a credential, oversize or personal marker included, it never wrote: the
 * record is flagged and the value hidden.
 */
const writtenUnderRedactedName = (name: string, value: unknown): boolean =>
  value === AUDIT_MARKERS.secret || keptByServer(name, value);

/** redact.py's embedded-JSON bounds (`_MAX_EMBED_DEPTH`, `_MAX_EMBED_BYTES`), pinned by the parity test. */
export const REDACTOR_EMBED_LIMITS = { depth: 4, bytes: 64 * 1024 } as const;

/**
 * How deep the client follows a value. Past it, and past each embedded-JSON bound, it fails closed: the value is
 * hidden and its record flagged, as the server replaces or withholds what lies past its own bounds (S-5520-02).
 */
const MAX_DEPTH = 64;

const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** A string's UTF-8 length, as redact.py counts `_MAX_EMBED_BYTES`. */
const utf8Length = (text: string): number => new TextEncoder().encode(text).length;

/**
 * A string as redact.py's `_redact_embedded_json` reads it: `none` unless it opens with `{` or `[` and parses,
 * `oversize` over `_MAX_EMBED_BYTES` of UTF-8 (which the server replaces whole), else the parsed value.
 */
function embedded(
  value: string,
):
  | { readonly kind: "none" }
  | { readonly kind: "oversize" }
  | { readonly kind: "json"; readonly value: unknown } {
  const text = value.trimStart();
  if (!(text.startsWith("{") || text.startsWith("["))) return { kind: "none" };
  if (
    value.length > REDACTOR_EMBED_LIMITS.bytes ||
    utf8Length(value) > REDACTOR_EMBED_LIMITS.bytes
  ) {
    return { kind: "oversize" };
  }
  try {
    return { kind: "json", value: JSON.parse(value) as unknown };
  } catch {
    return { kind: "none" };
  }
}

/**
 * Whether `value`, or anything inside it (objects, lists, embedded JSON), holds a value under a redacted name that the
 * server never writes there: its presence flags the record (AD-3). Past each bound it follows, it fails closed (true):
 * deeper than `MAX_DEPTH`, an embedded JSON string past `_MAX_EMBED_DEPTH` strings or over `_MAX_EMBED_BYTES`, each of
 * which the server would have replaced, withheld or never served.
 */
function holdsRedactedName(value: unknown, depth = 0, hops = 0): boolean {
  if (depth > MAX_DEPTH) return true;
  if (typeof value === "string") {
    const inner = embedded(value);
    if (inner.kind === "none") return false;
    if (inner.kind === "oversize" || hops >= REDACTOR_EMBED_LIMITS.depth) return true;
    return holdsRedactedName(inner.value, depth + 1, hops + 1);
  }
  if (Array.isArray(value)) return value.some((item) => holdsRedactedName(item, depth + 1, hops));
  if (!isRecord(value)) return false;
  return Object.entries(value).some(
    ([key, inner]) =>
      (isRedactedName(key, value) && !writtenUnderRedactedName(key, inner)) ||
      holdsRedactedName(inner, depth + 1, hops),
  );
}

/** The value kinds of E42-D04 §6. */
export type AuditValueKind =
  | "value"
  | "fingerprint"
  | "identifier"
  | "secret"
  | "secret_named"
  | "credential"
  | "personal"
  | "oversize"
  | "none"
  | "withheld"
  | "hidden";

/** One value as the diff shows it. No kind carries a redacted value: `secret_named` carries nothing at all. */
export type AuditValue =
  | {
      readonly kind: "value";
      /** The whole value as text: a number with separators, a flag's boolean as ON or OFF, a list as JSON. */
      readonly text: string;
      /** A number: shown in `type.num.sm`. */
      readonly numeric: boolean;
      /** Longer than 120 characters: the first 120 show, then Show full value. */
      readonly cut: boolean;
    }
  | { readonly kind: "fingerprint" | "identifier"; readonly text: string }
  | { readonly kind: "personal"; readonly hex8: string }
  | {
      readonly kind: "secret" | "secret_named" | "credential" | "oversize" | "withheld" | "hidden";
    }
  | {
      readonly kind: "none";
      /** A request's unsent member, a request's kept overrides, or a state with no earlier one. */
      readonly note?: "not_sent" | "overrides_kept" | "no_before";
    };

/** A field that changed (state), was requested (request), or stands beside a withheld or missing state. */
export interface AuditDiffField {
  /** The field's path, its nested keys in order (shown joined by " › "). */
  readonly path: readonly string[];
  /** Added, Removed or Changed: the state shape only, both states served. */
  readonly status?: "added" | "removed" | "changed";
  readonly before?: AuditValue;
  /** The state after, or for the request shape the value requested. */
  readonly after?: AuditValue;
}

/** A field shown as one value: a record fact (`phase`), a request fact, a result's field or an unchanged field. */
export interface AuditDiffFact {
  readonly path: readonly string[];
  readonly value: AuditValue;
}

/** The block's head: a refused request, an intent, a recorded result or a write-ahead one. */
export type AuditDiffHead =
  | { readonly kind: "failed"; readonly reason?: string }
  | { readonly kind: "intent" }
  | { readonly kind: "result" }
  | { readonly kind: "started" };

/** E42-D04 §6's one mapping: `detail` and the record's shape in, the renderer's only input out. */
export interface AuditDiffModel {
  /** `hidden`: a Manager's projection (`detail` `{}`), "Not shown in your view". */
  readonly shape: "state" | "request" | "result" | "hidden";
  readonly head?: AuditDiffHead;
  /** Each state as served, withheld (`elided`) or null. */
  readonly before: "served" | "withheld" | "none";
  readonly after: "served" | "withheld" | "none";
  readonly fields: readonly AuditDiffField[];
  /** The state shape's fields both states hold with one value: the `diff.unchanged_n` disclosure. */
  readonly unchanged: readonly AuditDiffFact[];
  /** The record's facts (`phase`), a request's facts or a result's fields. */
  readonly facts: readonly AuditDiffFact[];
  /**
   * A value under a redacted name that the server never writes there, or one past a bound the client follows: the raw
   * record is withheld (AD-3, `rec.raw_flagged`).
   */
  readonly flagged: boolean;
}

/** Actions whose `detail` records a result, whatever the outcome (CG-30's per-action map, E42-D04 §6). */
const RESULT_ACTIONS: ReadonlySet<string> = new Set(["admin.audit_verify", "api_key.import"]);
/** A request's facts: shown as values, never as requested fields (§6, request shape). */
const REQUEST_FACTS: ReadonlySet<string> = new Set(["reason", "evidence_url", "result", "phase"]);
/** Fields the contract marks safe to show (`key_id_masked`, an export's `sha256`) and the signing key's id. */
const FINGERPRINTS: ReadonlySet<string> = new Set(["key_id_masked", "sha256"]);
const IDENTIFIERS: ReadonlySet<string> = new Set(["key_id"]);
/** A value past this many characters shows its first ones, then Show full value. */
export const AUDIT_VALUE_CUT = 120;

/** §1's separators: 1,204,118; a fraction keeps its digits; anything else as JavaScript writes it. */
export function groupDigits(value: number): string {
  const text = String(value);
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(text);
  if (match === null) return text;
  const whole = (match[2] ?? "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${match[1] ?? ""}${whole}${match[3] ?? ""}`;
}

interface Leaf {
  readonly path: readonly string[];
  readonly value: AuditValue;
  /** The value as served, to compare states; `null` for a hidden one (never kept). */
  readonly raw: string;
}

interface ReadOptions {
  /** A flag record: its booleans read ON and OFF. */
  readonly flag: boolean;
}

/**
 * One leaf's kind, `depth` its nesting in the state: under a redacted name only what the server writes there (its
 * marker, a kept value) and `secret_named` for anything else; elsewhere a marker's kind, then the value's own.
 */
function kindOf(
  key: string,
  value: unknown,
  siblings: Readonly<Record<string, unknown>>,
  { flag }: ReadOptions,
  depth: number,
): AuditValue {
  if (isRedactedName(key, siblings)) {
    if (value === AUDIT_MARKERS.secret) return { kind: "secret" };
    if (!keptByServer(key, value)) return { kind: "secret_named" };
  } else if (typeof value === "string") {
    if (value === AUDIT_MARKERS.secret) return { kind: "secret" };
    if (value === AUDIT_MARKERS.credential) return { kind: "credential" };
    if (value === AUDIT_MARKERS.oversize) return { kind: "oversize" };
    if (PERSONAL.test(value)) {
      const hex8 = value.slice(AUDIT_MARKERS.personal.length, AUDIT_MARKERS.personal.length + 8);
      return { kind: "personal", hex8 };
    }
  }
  if (value === null || value === undefined) return { kind: "none" };
  if (holdsRedactedName(value, depth)) return { kind: "secret_named" };
  if (typeof value === "string" && FINGERPRINTS.has(key))
    return { kind: "fingerprint", text: value };
  if (typeof value === "string" && IDENTIFIERS.has(key)) return { kind: "identifier", text: value };
  const numeric = typeof value === "number";
  const text =
    typeof value === "boolean"
      ? flag
        ? value
          ? "ON"
          : "OFF"
        : String(value)
      : typeof value === "number"
        ? groupDigits(value)
        : typeof value === "string"
          ? value
          : JSON.stringify(value);
  return { kind: "value", text, numeric, cut: text.length > AUDIT_VALUE_CUT };
}

/** A stable text of a served value, to tell an unchanged field from a changed one. */
const rawOf = (value: unknown): string => JSON.stringify(value) ?? "undefined";

/**
 * A state's leaves, in order: objects are followed (their keys the path), a list or a scalar is one leaf, and a value
 * under a redacted name is one leaf whatever it holds (the server replaces it whole). An object past `MAX_DEPTH` is a
 * leaf too, which fails closed (`secret_named`).
 */
function leavesOf(state: Readonly<Record<string, unknown>>, options: ReadOptions): Leaf[] {
  const leaves: Leaf[] = [];
  const walk = (
    mapping: Readonly<Record<string, unknown>>,
    path: readonly string[],
    depth: number,
  ): void => {
    for (const [key, value] of Object.entries(mapping)) {
      const here = [...path, key];
      const redacted = isRedactedName(key, mapping);
      if (isRecord(value) && !redacted && depth < MAX_DEPTH) {
        walk(value, here, depth + 1);
        continue;
      }
      const kind = kindOf(key, value, mapping, options, depth + 1);
      leaves.push({
        path: here,
        value: kind,
        raw: kind.kind === "secret_named" ? "\u0000" : rawOf(value),
      });
    }
  };
  walk(state, [], 0);
  return leaves;
}

const keyOf = (path: readonly string[]): string => JSON.stringify(path);

type StateRead = {
  readonly status: "served" | "withheld" | "none";
  readonly value?: Readonly<Record<string, unknown>>;
};

function readState(detail: AuditEntry["detail"], name: "before" | "after"): StateRead {
  if (detail.elided?.includes(name) === true) return { status: "withheld" };
  const value = detail[name];
  return isRecord(value) ? { status: "served", value } : { status: "none" };
}

/**
 * E42-D04 §6's one mapping function: an entry's recorded `detail` (`before`, `after`, `elided`), read with its
 * `outcome`, `reason` and action, as the shape (state, request or result) and its fields, each value one of §6's kinds.
 * It is the diff renderer's only input. It derives no value of its own, hashes nothing, and carries no value the
 * server redacted: a value under a redacted name that the server never writes there becomes `secret_named` with no
 * value, and flags the record so its raw form is withheld (AD-3); so does a value past a bound the client follows.
 */
export function auditDiffModel(entry: AuditDiffEntry): AuditDiffModel {
  const detail = entry.detail;
  const before = readState(detail, "before");
  const after = readState(detail, "after");
  const flagged = holdsRedactedName(before.value ?? null) || holdsRedactedName(after.value ?? null);
  const empty = !("before" in detail) && !("after" in detail) && detail.elided === undefined;
  if (empty && entry.entry_hash === null) {
    return {
      shape: "hidden",
      before: "none",
      after: "none",
      fields: [],
      unchanged: [],
      facts: [],
      flagged,
    };
  }
  const options: ReadOptions = { flag: entry.subject_type === "feature_flag" };
  const beforeLeaves = before.value === undefined ? [] : leavesOf(before.value, options);
  const afterLeaves = after.value === undefined ? [] : leavesOf(after.value, options);
  const base = { before: before.status, after: after.status, flagged } as const;

  if (RESULT_ACTIONS.has(entry.action)) {
    return {
      ...base,
      shape: "result",
      head: entry.reason === "started" ? { kind: "started" } : { kind: "result" },
      fields: [],
      unchanged: [],
      facts: afterLeaves.map(({ path, value }) => ({ path, value })),
    };
  }

  const intent = after.value?.["phase"] === "intent";
  if (entry.outcome === "failure" || entry.outcome === "denied" || intent) {
    const stored = new Map(beforeLeaves.map((leaf) => [keyOf(leaf.path), leaf]));
    const fields: AuditDiffField[] = [];
    const facts: AuditDiffFact[] = [];
    for (const leaf of afterLeaves) {
      const top = leaf.path[0] ?? "";
      const unsent =
        leaf.value.kind === "none"
          ? {
              kind: "none" as const,
              note:
                top === "overrides" && leaf.path.length === 1
                  ? ("overrides_kept" as const)
                  : ("not_sent" as const),
            }
          : leaf.value;
      if (REQUEST_FACTS.has(top) && leaf.path.length === 1) {
        facts.push({ path: leaf.path, value: unsent });
        continue;
      }
      const was = stored.get(keyOf(leaf.path));
      fields.push(
        was === undefined
          ? { path: leaf.path, after: unsent }
          : { path: leaf.path, before: was.value, after: unsent },
      );
    }
    const result = after.value?.["result"];
    const reason = entry.reason ?? (typeof result === "string" ? result : undefined);
    const failed = entry.outcome === "failure" || entry.outcome === "denied";
    return {
      ...base,
      shape: "request",
      head: failed
        ? reason === undefined || reason === null
          ? { kind: "failed" }
          : { kind: "failed", reason }
        : { kind: "intent" },
      fields,
      unchanged: [],
      facts,
    };
  }

  // The state shape.
  const isPhase = (leaf: Leaf): boolean => leaf.path.length === 1 && leaf.path[0] === "phase";
  const phase = afterLeaves.find(isPhase) ?? beforeLeaves.find(isPhase);
  const facts: AuditDiffFact[] =
    phase === undefined ? [] : [{ path: phase.path, value: phase.value }];
  const beforeFields = beforeLeaves.filter((leaf) => !isPhase(leaf));
  const afterFields = afterLeaves.filter((leaf) => !isPhase(leaf));

  // A state withheld or missing beside a served one: no status word (§6 rules).
  if (before.status !== "served" || after.status !== "served") {
    const fields: AuditDiffField[] =
      before.status === "none" && after.status === "served"
        ? afterFields.map(({ path, value }) => ({
            path,
            before: { kind: "none", note: "no_before" },
            after: value,
          }))
        : after.status === "served"
          ? afterFields.map(({ path, value }) => ({ path, after: value }))
          : beforeFields.map(({ path, value }) =>
              after.status === "none"
                ? { path, before: value, after: { kind: "none" } }
                : { path, before: value },
            );
    return { ...base, shape: "state", fields, unchanged: [], facts };
  }

  const was = new Map(beforeFields.map((leaf) => [keyOf(leaf.path), leaf]));
  const now = new Set(afterFields.map((leaf) => keyOf(leaf.path)));
  const fields: AuditDiffField[] = [];
  const unchanged: AuditDiffFact[] = [];
  for (const leaf of afterFields) {
    const old = was.get(keyOf(leaf.path));
    if (old === undefined) fields.push({ path: leaf.path, status: "added", after: leaf.value });
    else if (old.raw === leaf.raw) unchanged.push({ path: leaf.path, value: leaf.value });
    else fields.push({ path: leaf.path, status: "changed", before: old.value, after: leaf.value });
  }
  for (const leaf of beforeFields) {
    if (!now.has(keyOf(leaf.path)))
      fields.push({ path: leaf.path, status: "removed", before: leaf.value });
  }
  return { ...base, shape: "state", fields, unchanged, facts };
}
