/**
 * The crash-log entry schema both sides of `cv:crashLog:append` check (SR-111). It mirrors
 * `CrashEntry` in apps/web's ShellPort by shape only: this app may not import apps/web
 * (`.dependency-cruiser.js` `desktop-not-to-web`). The renderer already redacts and clips to
 * 2048 characters; these bounds sit above that and exist so a compromised renderer cannot write
 * arbitrary keys or unbounded text into a file on the user's disk.
 */
export interface CrashEntry {
  readonly timestampMs: number;
  readonly message: string;
  readonly stack?: string;
  readonly context?: Readonly<Record<string, string>>;
}

export const CRASH_ENTRY_LIMITS = Object.freeze({
  message: 4096,
  stack: 8192,
  contextKeys: 8,
  contextValue: 4096,
});

const ENTRY_KEYS = new Set(["timestampMs", "message", "stack", "context"]);
const CONTEXT_KEY = /^[A-Za-z][A-Za-z0-9_]{0,31}$/;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function isBoundedString(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length <= max;
}

function parseContext(value: unknown): Record<string, string> | undefined {
  if (!isPlainObject(value)) {
    return undefined;
  }
  const entries = Object.entries(value);
  const valid =
    entries.length <= CRASH_ENTRY_LIMITS.contextKeys &&
    entries.every(
      ([key, item]) =>
        CONTEXT_KEY.test(key) && isBoundedString(item, CRASH_ENTRY_LIMITS.contextValue),
    );
  // CONTEXT_KEY admits no "__proto__"-like key; fromEntries defines own properties either way.
  return valid ? Object.fromEntries(entries.map(([key, item]) => [key, String(item)])) : undefined;
}

/**
 * Returns a fresh entry holding only the schema's fields, or undefined if `value` is not exactly a
 * CrashEntry: an unknown key, a wrong type, a string over its bound or a non-plain object is
 * refused whole, never trimmed into shape.
 */
export function parseCrashEntry(value: unknown): CrashEntry | undefined {
  if (!isPlainObject(value) || !Object.keys(value).every((key) => ENTRY_KEYS.has(key))) {
    return undefined;
  }
  const { timestampMs, message, stack, context } = value;
  if (
    typeof timestampMs !== "number" ||
    !Number.isSafeInteger(timestampMs) ||
    timestampMs < 0 ||
    !isBoundedString(message, CRASH_ENTRY_LIMITS.message) ||
    (stack !== undefined && !isBoundedString(stack, CRASH_ENTRY_LIMITS.stack))
  ) {
    return undefined;
  }
  const parsedContext = context === undefined ? undefined : parseContext(context);
  if (context !== undefined && parsedContext === undefined) {
    return undefined;
  }
  return {
    timestampMs,
    message,
    ...(stack === undefined ? {} : { stack }),
    ...(parsedContext === undefined ? {} : { context: parsedContext }),
  };
}
