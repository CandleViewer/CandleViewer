/**
 * Client redaction for crash entries and the diagnostics payload (C-12.6, SR-122, SR-177). The rule set mirrors the
 * backend's E04 filter (`services/api/candleviewer/observability/redaction.py`) so client and server agree on what is
 * never emitted: the same key names (by field and as a `name: value` / `name=value` label in text) and the same value
 * shapes (JWT triple, key-shaped word, URL-safe invite/refresh token, 6-digit code). On top of them the client redacts a
 * bare `Bearer …` credential, PEM key material and the KEK handle by name. A name matches in snake, kebab and camel
 * case alike (`api_key`, `api-key`, `apiKey`). Every scan is linear: text is cut to `MAX_SCAN_LEN` first, and the value
 * shapes are tested per run of `[\w.-]` without backtracking patterns. Nothing here throws on a hostile value: a Proxy
 * with throwing traps or a throwing getter becomes `[redacted:unrenderable]` (M1).
 */

export const KEY_NAMES = [
  "api_key", "api_secret", "secret", "password", "cookie", "set-cookie", "authorization", "x-bapi-sign",
  "x-bapi-api-key", "totp", "recovery_code", "session", "csrf", "access_token", "token", "refresh_token",
  "session_token", "bearer", "x-api-key", "x-auth-token", "x-access-token", "x-csrf-token", "proxy-authorization",
  "arm_token", "x-arm-token", "sign", "signature", "input_value", "sealed_seed", "dek_ref",
  // client additions: the opaque KEK handle never leaves the renderer (SR-119)
  "kek_handle",
  // the CSRF token by its camelCase field and the double-submit cookie's exact name (`auth/csrf.py` CSRF_COOKIE)
  "csrf_token", "__Host-cv_csrf",
] as const; // prettier-ignore

/** One spelling per name: camelCase split at its humps, lower case, `-` read as `_` (`apiKey`, `API-KEY` → `api_key`). */
const keyForm = (key: string): string =>
  key
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/-/g, "_");
const KEY_FORMS: ReadonlySet<string> = new Set(KEY_NAMES.map(keyForm));
export const KEY_MARK = "[redacted:key-name]";
const UNRENDERABLE = "[redacted:unrenderable]";
/**
 * A backstop deny-list of payload-carrying field names (separators and case ignored): request/response bodies, the WS
 * envelope's payload member `p`, frames, call arguments and raw user input are dropped by field, not redacted. It is
 * never the "never the payload" control: that is the structural allow-list in `describe()` (`reportCrash.ts`), which
 * reads an error's name, message and stack only, and the diagnostics' settings-group allow-list.
 */
const PAYLOAD_KEYS: ReadonlySet<string> = new Set([
  "body", "payload", "request", "response", "frame", "raw", "input",
  "p", "data", "params", "args", "rawframe", "wsframe", "userinput", "inputtext",
]); // prettier-ignore
const MAX_SCAN_LEN = 4096;
const MAX_DEPTH = 6;
const MAX_ITEMS = 100;
const TRUNCATED = "...[truncated:oversize]";

// Literal patterns (no `RegExp` built from strings). Each refuses a value already redacted, after any whitespace or an
// opening quote (`(?![ \t]*["']?\[redacted:)`), so a second pass changes nothing.
/** A cookie or authorization header's value is the rest of its line (`Cookie: a=…; b=…`, `Authorization: Basic …`). */
const HEADER_LINE =
  /\b((?:set[-_]cookie|cookie|(?:proxy[-_])?authorization)["']?\s*[:=][ \t]*)(?![ \t]*["']?\[redacted:)[^\n]+/gi;
/** A bare `Bearer …` credential; it runs before `LABELLED`, so `token: Bearer …` loses the credential too. */
const BEARER = /\b(bearer[ \t]+)(?![ \t]*["']?\[redacted:)[^\s"',}\]]+/gi;
/**
 * A value labelled with a key name: `KEY_NAMES` longest first, case-insensitive, each multi-word name both with a `-`/`_`
 * between its words and with none, so `api_key`, `API-KEY`, `apikey` and `apiKey` alike (the two forms, not `[-_]?`, keep
 * the pattern under the safe-regex quantifier limit). A name with a leading `__` (a cookie prefix) starts at a run of
 * separators instead of `\b`. Kept literal (no `RegExp` from strings); a test rebuilds it from `KEY_NAMES`.
 */
export const LABELLED =
  /((?:\bproxy[-_]authorization|\bproxyauthorization|(?<![\w-])[-_]+host[-_]cv[-_]csrf|(?<![\w-])[-_]+hostcvcsrf|\bx[-_]access[-_]token|\bxaccesstoken|\bx[-_]bapi[-_]api[-_]key|\bxbapiapikey|\bauthorization|\brecovery[-_]code|\brecoverycode|\brefresh[-_]token|\brefreshtoken|\bsession[-_]token|\bsessiontoken|\baccess[-_]token|\baccesstoken|\bx[-_]auth[-_]token|\bxauthtoken|\bx[-_]csrf[-_]token|\bxcsrftoken|\binput[-_]value|\binputvalue|\bsealed[-_]seed|\bsealedseed|\bx[-_]arm[-_]token|\bxarmtoken|\bx[-_]bapi[-_]sign|\bxbapisign|\bapi[-_]secret|\bapisecret|\bcsrf[-_]token|\bcsrftoken|\bkek[-_]handle|\bkekhandle|\bset[-_]cookie|\bsetcookie|\barm[-_]token|\barmtoken|\bsignature|\bx[-_]api[-_]key|\bxapikey|\bpassword|\bapi[-_]key|\bapikey|\bdek[-_]ref|\bdekref|\bsession|\bbearer|\bcookie|\bsecret|\btoken|\bcsrf|\bsign|\btotp)["']?\s*[:=]\s*)(?![ \t]*["']?\[redacted:)("[^"\n]*"?|'[^'\n]*'?|[^\s"',}\]]+)/gi;
/** A backup download path, as the server's `_DOWNLOAD_PATH_RE` (#415): the whole path becomes one marker. */
const DOWNLOAD_PATH = /\/admin\/backups\/[^/\s]*\/download\/[^/\s]+/g;
const RUN = /[\w.-]+/g;
const RUN_CHAR = /[\w.-]/;

/** A body or payload field by name (`body`, `request_body`, `responseBody`, `framePayload`, …). */
export function isPayloadKey(key: string): boolean {
  const name = key.toLowerCase();
  return PAYLOAD_KEYS.has(name.replace(/[-_]/g, "")) || /(?:body|payload)$/.test(name);
}

export function isRedactKey(key: string): boolean {
  return KEY_FORMS.has(keyForm(key));
}

/** The server's value shapes, tested on one run of `[\w.-]` (a match of each lies inside one run). */
export function shapeOf(run: string): string | null {
  const dotted = run.split(".");
  for (let i = 0; i + 2 < dotted.length; i += 1) {
    if (dotted.slice(i, i + 3).every((part) => part.length >= 10)) return "jwt-shape";
  }
  for (const part of dotted) {
    // a URL-safe run: 42–44 characters (invite/access token) or 64 (refresh token), never a snake_case identifier
    // or a 64-digit lowercase hex digest
    if (/^[a-z0-9]*_[a-z0-9_]*$/.test(part)) continue;
    if (part.length >= 42 && part.length <= 44) return "invite-token-shape";
    if (part.length === 64 && !/^[0-9a-f]{64}$/.test(part)) return "refresh-token-shape";
  }
  for (const word of run.split(/[.-]/)) {
    if (/^[A-Za-z0-9]{18,36}$/.test(word)) return "key-shape";
    if (/^\d{6}$/.test(word)) return "totp-shape";
  }
  return null;
}

/** Cut a long text before the run the cut would split, so no partial value survives below a shape's length. */
function cut(text: string): string {
  if (text.length <= MAX_SCAN_LEN) return text;
  let end = MAX_SCAN_LEN;
  if (RUN_CHAR.test(text.charAt(end))) {
    while (end > 0 && RUN_CHAR.test(text.charAt(end - 1))) end -= 1;
  }
  return text.slice(0, end) + TRUNCATED;
}

/** PEM blocks (and an unterminated one, to the end) become one marker. Linear: `indexOf` only. */
function redactPem(text: string): string {
  let out = "";
  let from = 0;
  for (let at = text.indexOf("-----BEGIN", from); at >= 0; at = text.indexOf("-----BEGIN", from)) {
    const end = text.indexOf("-----END", at);
    const close = end < 0 ? -1 : text.indexOf("-----", end + 8);
    out += text.slice(from, at) + "[redacted:key-material]";
    from = close < 0 ? text.length : close + 5;
  }
  return out + text.slice(from);
}

export function redactText(text: string): string {
  const scanned = redactPem(cut(text))
    .replace(DOWNLOAD_PATH, "[redacted:download-path]")
    .replace(HEADER_LINE, (_m, label: string) => label + KEY_MARK)
    .replace(BEARER, (_m, scheme: string) => scheme + KEY_MARK)
    .replace(LABELLED, (_m, label: string, value: string) => {
      const quote = /^["']/.test(value) ? value.charAt(0) : "";
      return label + quote + KEY_MARK + quote; // a quoted value keeps both quotes: the text stays well-formed
    });
  return scanned.replace(RUN, (run) => {
    const shape = shapeOf(run);
    return shape === null ? run : `[redacted:${shape}]`;
  });
}

/** A string read through a getter that may throw or return anything; `undefined` when it is not a string. */
export function readString(get: () => unknown): string | undefined {
  try {
    const value = get();
    return typeof value === "string" ? value : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Redact any JSON-like value: key names by field, text by `redactText`; deep or cyclic structures are cut off. Never
 * throws: a value whose traps or getters throw becomes `[redacted:unrenderable]` where it stands.
 */
export function redactValue(value: unknown, depth = 0): unknown {
  try {
    return redactAny(value, depth);
  } catch {
    return UNRENDERABLE;
  }
}

/** A buffer from another realm (an iframe, a worker's transfer) fails `instanceof`; its tag does not. */
const isBufferTag = (value: object): boolean =>
  /^\[object (?:Shared)?ArrayBuffer\]$/.test(Object.prototype.toString.call(value));

function redactAny(value: unknown, depth: number): unknown {
  if (depth > MAX_DEPTH) return "[redacted:depth]";
  if (typeof value === "string") return redactText(value);
  if (value == null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value !== "object") return `[${typeof value}]`; // a function's source or a symbol's description is never rendered
  if (Array.isArray(value)) return value.slice(0, MAX_ITEMS).map((v) => redactValue(v, depth + 1));
  if (ArrayBuffer.isView(value) || value instanceof ArrayBuffer || isBufferTag(value))
    return "[redacted:bytes]";
  if (value instanceof String) return redactText(String(value));
  if (value instanceof Map) return "[map]";
  if (value instanceof Set) return "[set]";
  if (value instanceof Error) {
    const name = readString(() => value.name) ?? UNRENDERABLE;
    return redactText(`${name}: ${readString(() => value.message) ?? UNRENDERABLE}`);
  }
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value)) {
    if (isPayloadKey(key)) continue;
    let item: unknown;
    try {
      item = Reflect.get(value, key);
    } catch {
      item = UNRENDERABLE; // a throwing getter
    }
    out[redactText(key)] = isRedactKey(key) ? KEY_MARK : redactValue(item, depth + 1);
  }
  return out;
}
