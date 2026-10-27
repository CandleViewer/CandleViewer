/**
 * The shell's local crash log (E10-S04, SR-111, E13): one JSON line per entry the renderer
 * appends through `cv:crashLog:append`, in a file under the app's userData `logs` directory. The
 * entry is re-validated and scrubbed here (never trusted from the preload), the file is capped at `maxBytes`
 * with one rotated copy, and appends run one at a time through a bounded queue so a flooding
 * renderer is refused rather than queued without limit (C-2.18). Failures reject with a fixed
 * message; nothing here throws into the main process. The file is never transmitted anywhere.
 */
import { appendFile, mkdir, rename, stat } from "node:fs/promises";
import path from "node:path";
import { CRASH_ENTRY_LIMITS, parseCrashEntry, type CrashEntry } from "../shared/crashEntry.js";

export const CRASH_LOG_FILE = "crash.log";
export const CRASH_LOG_ROTATED_FILE = "crash.log.1";
export const CRASH_LOG_MAX_BYTES = 1024 * 1024;
/**
 * One serialised line: every schema-valid entry fits. Each character costs at most 6 bytes once
 * JSON-escaped (`\uXXXX`), scrubbing grows text by under 3x, plus 1 KiB of keys and punctuation.
 */
export const CRASH_LOG_MAX_LINE_BYTES =
  (CRASH_ENTRY_LIMITS.message +
    CRASH_ENTRY_LIMITS.stack +
    CRASH_ENTRY_LIMITS.contextKeys *
      (CRASH_ENTRY_LIMITS.contextKey + CRASH_ENTRY_LIMITS.contextValue)) *
    6 +
  1024;
export const CRASH_LOG_MAX_PENDING = 32;
/** Audit lines per event and reason per window; the rest are counted into one summary line. */
export const CRASH_LOG_AUDIT_BURST = 5;
export const CRASH_LOG_AUDIT_WINDOW_MS = 60_000;

const REDACTED = "[redacted]";
/** Name endings whose value is a credential: `key` also covers apiKey / api_key / api-key. */
const SENSITIVE_SUFFIX =
  "key|token|secret|pass|passwd|password|pwd|cookie|signature|sign|auth|authorization|credentials?|jwt|totp|csrf|session|recovery_code|kek_handle|sealed_seed|dek_ref|input_value";
const SENSITIVE_NAME = new RegExp(`(?:${SENSITIVE_SUFFIX})$`, "i");
// Every pattern starts only where no word character precedes it (a lookbehind, not `\b`) and its
// classes are disjoint from what follows them, so each runs in linear time.
const HEADER_TO_EOL = /(?<![\w-])(set-cookie|cookie|authorization)(\s*[:=]\s*)[^\r\n]*/gi;
const AUTH_SCHEME = /(?<![\w-])(bearer|basic)\s+[\w.~+/=-]+/gi;
// Only a sensitive name is matched, so a benign name never consumes the text after it (a free-text
// `"message": "… apiKey=K1 …"` is still scanned). The name may be quoted or start with `_`
// (`{"token":"…"}`, `__Host-cv_csrf=…`); a quoted value, escapes included, is redacted whole.
// eslint-disable-next-line security/detect-non-literal-regexp -- built once from the module constant SENSITIVE_SUFFIX, never from input
const NAME_VALUE = new RegExp(
  String.raw`(?<![\w-])(_*(?:[A-Za-z][\w-]*?)?(?:${SENSITIVE_SUFFIX}))(["']?\s*[:=]\s*)("(?:[^"\\\n]|\\[^\n])*"?|'(?:[^'\\\n]|\\[^\n])*'?|[^\s"'&,;]+)`,
  "gi",
);

/**
 * Defence in depth behind the renderer reporter's redaction (#306 slice 5): replaces credential
 * headers, `Bearer`/`Basic` tokens and `name=value` / `name: value` pairs whose name is sensitive
 * (URL query values included) with "[redacted]".
 */
export function scrubCrashText(text: string): string {
  return text
    .replace(HEADER_TO_EOL, `$1$2${REDACTED}`)
    .replace(AUTH_SCHEME, `$1 ${REDACTED}`)
    .replace(NAME_VALUE, (_match, name: string, sep: string, value: string) => {
      const quote = value.startsWith('"') || value.startsWith("'") ? value.charAt(0) : "";
      return `${name}${sep}${quote}${REDACTED}${quote}`;
    });
}

function scrubEntry(entry: CrashEntry): CrashEntry {
  const context =
    entry.context === undefined
      ? undefined
      : Object.fromEntries(
          Object.entries(entry.context).map(([name, value]) => [
            name,
            SENSITIVE_NAME.test(name) ? REDACTED : scrubCrashText(value),
          ]),
        );
  return {
    timestampMs: entry.timestampMs,
    message: scrubCrashText(entry.message),
    ...(entry.stack === undefined ? {} : { stack: scrubCrashText(entry.stack) }),
    ...(context === undefined ? {} : { context }),
  };
}

/** What the renderer sees for a refused entry: a fixed message, never the entry or a path. */
export class CrashLogRefusedError extends Error {
  constructor() {
    super("Crash log entry refused");
    this.name = "CrashLogRefusedError";
  }
}

/** What the renderer sees when the file cannot be written: a fixed message, never the fs error. */
export class CrashLogUnavailableError extends Error {
  constructor() {
    super("Crash log unavailable");
    this.name = "CrashLogUnavailableError";
  }
}

export interface CrashLogOptions {
  /** The directory the log lives in, e.g. `<userData>/logs`; created on first append. */
  readonly dir: string;
  readonly maxBytes?: number;
  /** Audit sink for refusals and write failures: a reason or an error code, never entry text. */
  readonly audit?: (event: string, detail: Record<string, unknown>) => void;
  /** Main's clock (ms): stamps `receivedAt` and windows the audit rate limit. */
  readonly now?: () => number;
}

type Audit = (event: string, detail: Record<string, string>) => void;

/**
 * At most CRASH_LOG_AUDIT_BURST lines per event and detail per window, so a flooding renderer
 * cannot turn refusals into unbounded audit writes; the first audit after a window with
 * suppressed lines first writes one `crash-log-audit-suppressed` line carrying the count.
 */
function rateLimitedAudit(audit: NonNullable<CrashLogOptions["audit"]>, now: () => number): Audit {
  const windows = new Map<string, { start: number; written: number; suppressed: number }>();
  return (event, detail) => {
    const key = `${event}\u0000${JSON.stringify(detail)}`;
    const at = now();
    let window = windows.get(key);
    if (window === undefined || at - window.start >= CRASH_LOG_AUDIT_WINDOW_MS) {
      if (window !== undefined && window.suppressed > 0) {
        audit("crash-log-audit-suppressed", { event, ...detail, suppressed: window.suppressed });
      }
      window = { start: at, written: 0, suppressed: 0 };
      windows.set(key, window);
    }
    if (window.written < CRASH_LOG_AUDIT_BURST) {
      window.written += 1;
      audit(event, detail);
    } else {
      window.suppressed += 1;
    }
  };
}

export interface CrashLog {
  append(entry: unknown): Promise<void>;
}

async function sizeOf(file: string): Promise<number> {
  try {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- app-controlled log dir + fixed file name, never renderer input
    return (await stat(file)).size;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return 0;
    }
    throw error;
  }
}

export function createCrashLog(options: CrashLogOptions): CrashLog {
  const maxBytes = options.maxBytes ?? CRASH_LOG_MAX_BYTES;
  const now = options.now ?? Date.now;
  const audit = rateLimitedAudit(options.audit ?? (() => undefined), now);
  const file = path.join(options.dir, CRASH_LOG_FILE);
  const rotated = path.join(options.dir, CRASH_LOG_ROTATED_FILE);
  let tail: Promise<void> = Promise.resolve();
  let pending = 0;

  const write = async (line: string): Promise<void> => {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- app-controlled log dir, never renderer input
    await mkdir(options.dir, { recursive: true, mode: 0o700 });
    const bytes = Buffer.byteLength(line, "utf8");
    const size = await sizeOf(file);
    // Rotation overwrites crash.log.1. If the append below then fails, crash.log is simply absent
    // and the next call starts it afresh: nothing is left half-rotated.
    if (size > 0 && size + bytes > maxBytes) {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- fixed file names in the app-controlled log dir
      await rename(file, rotated);
    }
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- fixed file name in the app-controlled log dir
    await appendFile(file, line, { encoding: "utf8", mode: 0o600 });
  };

  return {
    async append(value: unknown): Promise<void> {
      const entry = parseCrashEntry(value);
      if (entry === undefined) {
        audit("crash-log-entry-refused", { reason: "schema" });
        throw new CrashLogRefusedError();
      }
      const receivedAt = new Date(now()).toISOString();
      const line = `${JSON.stringify({ ...scrubEntry(entry), receivedAt })}\n`;
      if (Buffer.byteLength(line, "utf8") > Math.min(CRASH_LOG_MAX_LINE_BYTES, maxBytes)) {
        audit("crash-log-entry-refused", { reason: "too-large" });
        throw new CrashLogRefusedError();
      }
      if (pending >= CRASH_LOG_MAX_PENDING) {
        audit("crash-log-entry-refused", { reason: "queue-full" });
        throw new CrashLogRefusedError();
      }
      pending += 1;
      const run = tail.then(() => write(line));
      tail = run.catch(() => undefined);
      try {
        await run;
      } catch (error) {
        audit("crash-log-write-failed", {
          code: (error as NodeJS.ErrnoException).code ?? "unknown",
        });
        throw new CrashLogUnavailableError();
      } finally {
        pending -= 1;
      }
    },
  };
}
