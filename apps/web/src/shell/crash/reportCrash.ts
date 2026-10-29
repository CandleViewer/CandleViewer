/**
 * The one crash reporter (E10-S04, #306): `reportCrash()` assigns a correlation id (a UUIDv4, the server's form),
 * appends a redacted entry to a bounded in-memory crash log (the browser's crash log, and the diagnostics' source in
 * both shells), hands it to `ShellPort.crashLog` where the shell keeps a local log file, and increments
 * `shell_crash_total` by boundary level. `buildDiagnostics()` assembles the copy-diagnostics payload and redacts it
 * again at assembly time (SR-177). Nothing here transmits anything.
 */
import { getShellState, type Settings } from "../bootstrap/store.js";
import type { CrashEntry, ShellPort } from "../ShellPort.js";
import { readString, redactText, redactValue } from "./redact.js";

export type CrashBoundary = "panel" | "route" | "app" | "window";
export type CrashCounts = Readonly<Record<CrashBoundary, number>>;
export const CRASH_LOG_CAPACITY = 50;

export interface CrashReporterDeps {
  /** `crashLog.append` is called only where `capabilities.crashLog` holds. */
  readonly port?: Pick<ShellPort, "capabilities" | "crashLog"> | undefined;
  readonly now?: () => number;
  readonly newId?: () => string;
  readonly capacity?: number;
}
export interface DiagnosticsMeta {
  readonly version: string;
  readonly buildHash: string;
  readonly settings: unknown;
}
export interface DiagnosticsPayload extends DiagnosticsMeta {
  readonly generatedAtMs: number;
  readonly correlationIds: readonly string[];
  readonly recentLogLines: readonly string[];
  readonly metrics: { readonly shell_crash_total: CrashCounts };
}
export interface CrashReporter {
  report(error: unknown, boundary: CrashBoundary, component?: string): string;
  diagnostics(meta: DiagnosticsMeta): DiagnosticsPayload;
  entries(): readonly CrashEntry[];
  counts(): CrashCounts;
  /** Settles once the crash-log appends in flight now have, failed ones too. */
  settled(): Promise<void>;
  /** How many crash-log appends are in flight: a settled one leaves the count. */
  pending(): number;
}

const clip = (text: string): string => redactText(text).slice(0, 2048);
/** The settings groups a diagnostics payload carries (allow-list): never `notifications` (a webhook URL, free-form quiet hours). */
const SETTINGS_ALLOWED: ReadonlySet<string> = new Set(["appearance", "accessibility", "chart", "orderflow", "trading", "data"] satisfies (keyof Settings)[]); // prettier-ignore

const UNRENDERABLE = "<unrenderable>";

/**
 * Allow-list: an error's name, message and stack only; a thrown non-Error gives its `message` or its type, never its
 * fields. This structural allow-list, not `redactValue`'s payload deny-list, is what keeps a payload out of the log.
 * Each field is read in its own try and kept only as a string, so a throwing getter costs that field, not the report.
 */
function describe(error: unknown): { message: string; stack?: string | undefined } {
  if (error instanceof Error) {
    const name = readString(() => error.name) ?? UNRENDERABLE;
    const message = readString(() => error.message) ?? UNRENDERABLE;
    let stack: string | undefined;
    try {
      const raw: unknown = error.stack;
      stack = raw === undefined ? undefined : typeof raw === "string" ? raw : UNRENDERABLE;
    } catch {
      stack = UNRENDERABLE;
    }
    return { message: `${name}: ${message}`, stack };
  }
  if (typeof error === "string") return { message: error };
  const message = readString(() =>
    typeof error === "object" && error !== null && "message" in error ? error.message : undefined,
  );
  return { message: message ?? `Non-Error thrown (${typeof error})` };
}

/**
 * The settings, redacted one level down. An allow-listed group is kept by its name even where the payload backstop
 * would drop that name (`data`): the group allow-list is the structural control; its contents are still redacted.
 */
function redactSettings(settings: unknown): unknown {
  const out = redactValue(settings, 1);
  if (typeof settings !== "object" || settings === null || typeof out !== "object" || out === null)
    return out;
  for (const group of SETTINGS_ALLOWED) {
    try {
      if (Object.hasOwn(settings, group)) {
        Reflect.set(out, group, redactValue(Reflect.get(settings, group), 2));
      }
    } catch {
      // a hostile settings object: the backstop's result stands
    }
  }
  return out;
}

export function createCrashReporter(deps: CrashReporterDeps = {}): CrashReporter {
  const { port, now = Date.now, newId = () => crypto.randomUUID() } = deps;
  const capacity = Math.max(1, deps.capacity ?? CRASH_LOG_CAPACITY);
  const log: CrashEntry[] = [];
  const counts = new Map<CrashBoundary, number>();
  const countsOf = (): CrashCounts => ({
    panel: counts.get("panel") ?? 0,
    route: counts.get("route") ?? 0,
    app: counts.get("app") ?? 0,
    window: counts.get("window") ?? 0,
  });
  // one error object seen twice (a boundary, then the window `error` event) is one crash with one id
  const seen = new WeakMap<object, string>();
  const inFlight = new Set<Promise<void>>();

  const report = (error: unknown, boundary: CrashBoundary, component?: string): string => {
    const key = typeof error === "object" && error !== null ? error : null;
    const known = key === null ? undefined : seen.get(key);
    if (known !== undefined) return known;
    const correlationId = newId();
    if (key !== null) seen.set(key, correlationId);
    let entry: CrashEntry;
    try {
      const { message, stack } = describe(error);
      entry = {
        timestampMs: now(),
        message: clip(message),
        ...(stack === undefined ? {} : { stack: clip(stack) }),
        context: {
          correlationId,
          boundary,
          ...(component === undefined ? {} : { component: clip(component) }),
        },
      };
    } catch {
      // a hostile error (a Proxy whose `getPrototypeOf` throws, …) still gets its id, its entry and its count
      entry = {
        timestampMs: now(),
        message: `Crash report failed: ${typeof error}`,
        context: { correlationId, boundary },
      };
    }
    log.push(entry);
    if (log.length > capacity) log.splice(0, log.length - capacity);
    counts.set(boundary, (counts.get(boundary) ?? 0) + 1);
    if (port?.capabilities.crashLog) {
      try {
        const append = port.crashLog.append(entry).catch(() => undefined);
        inFlight.add(append);
        void append.then(() => inFlight.delete(append));
      } catch {
        // a crash report never throws; the in-memory entry stands
      }
    }
    return correlationId;
  };

  const diagnostics = (meta: DiagnosticsMeta): DiagnosticsPayload => {
    const idOf = (e: CrashEntry): string => e.context?.["correlationId"] ?? "";
    const line = (e: CrashEntry): string =>
      `${new Date(e.timestampMs).toISOString()} crash ${e.context?.["boundary"] ?? ""} ${idOf(e)} ${e.message}`;
    const { settings, ...rest } = meta;
    const payload: Omit<DiagnosticsPayload, "settings"> = {
      ...rest,
      generatedAtMs: now(),
      correlationIds: log.map(idOf),
      recentLogLines: log.map(line),
      metrics: { shell_crash_total: countsOf() },
    };
    // SR-177: redacted at assembly, whatever passed before
    const redacted = redactValue(payload) as Omit<DiagnosticsPayload, "settings">;
    return { ...redacted, settings: redactSettings(settings) };
  };

  const settled = async (): Promise<void> => {
    await Promise.all(inFlight);
  };
  const pending = (): number => inFlight.size;
  return { report, diagnostics, entries: () => [...log], counts: countsOf, settled, pending };
}

let active = createCrashReporter();
let activeMeta = { version: "unknown", buildHash: "unknown" };

/** Reports one crash through the installed reporter and returns its correlation id. Never throws. */
export function reportCrash(error: unknown, boundary: CrashBoundary, component?: string): string {
  return active.report(error, boundary, component);
}

/** The installed reporter's appends in flight, settled: a GPU retry's relaunch (`app.exit(0)`) drops one still open. */
export function crashLogSettled(): Promise<void> {
  return active.settled();
}

/** The copy-diagnostics payload: version, build hash, correlation ids, recent log lines and settings, redacted. */
export function buildDiagnostics(): DiagnosticsPayload {
  const settings = Object.entries(getShellState().preferences ?? {}).filter(([k]) =>
    SETTINGS_ALLOWED.has(k),
  );
  return active.diagnostics({ ...activeMeta, settings: Object.fromEntries(settings) });
}

/** Installs a fresh reporter plus the window `error` / `unhandledrejection` handlers; returns the teardown. */
export function installCrashReporter(
  options: CrashReporterDeps & {
    version: string;
    buildHash?: string;
    target?: EventTarget | undefined;
  },
): () => void {
  const reporter = createCrashReporter(options);
  active = reporter;
  activeMeta = { version: options.version, buildHash: options.buildHash ?? "unknown" };
  const target =
    "target" in options ? options.target : typeof window === "undefined" ? undefined : window;
  const onError = (event: Event): void => {
    const { error, message } = event as ErrorEvent;
    reporter.report(error ?? message, "window");
  };
  const onRejection = (event: Event): void => {
    reporter.report((event as PromiseRejectionEvent).reason, "window");
  };
  target?.addEventListener("error", onError);
  target?.addEventListener("unhandledrejection", onRejection);
  return () => {
    target?.removeEventListener("error", onError);
    target?.removeEventListener("unhandledrejection", onRejection);
  };
}
