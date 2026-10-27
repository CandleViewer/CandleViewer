/**
 * The shell's local crash log (E10-S04, SR-111, E13): one JSON line per entry the renderer
 * appends through `cv:crashLog:append`, in a file under the app's userData `logs` directory. The
 * entry is re-validated here (never trusted from the preload), the file is capped at `maxBytes`
 * with one rotated copy, and appends run one at a time through a bounded queue so a flooding
 * renderer is refused rather than queued without limit (C-2.18). Failures reject with a fixed
 * message; nothing here throws into the main process. The file is never transmitted anywhere.
 */
import { appendFile, mkdir, rename, stat } from "node:fs/promises";
import path from "node:path";
import { parseCrashEntry } from "../shared/crashEntry.js";

export const CRASH_LOG_FILE = "crash.log";
export const CRASH_LOG_ROTATED_FILE = "crash.log.1";
export const CRASH_LOG_MAX_BYTES = 1024 * 1024;
/** One serialised line: above the schema's bounds plus JSON escaping, far below the file cap. */
export const CRASH_LOG_MAX_LINE_BYTES = 64 * 1024;
export const CRASH_LOG_MAX_PENDING = 32;

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
  const audit = options.audit ?? (() => undefined);
  const file = path.join(options.dir, CRASH_LOG_FILE);
  const rotated = path.join(options.dir, CRASH_LOG_ROTATED_FILE);
  let tail: Promise<void> = Promise.resolve();
  let pending = 0;

  const write = async (line: string): Promise<void> => {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- app-controlled log dir, never renderer input
    await mkdir(options.dir, { recursive: true });
    const bytes = Buffer.byteLength(line, "utf8");
    const size = await sizeOf(file);
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
      const line = `${JSON.stringify(entry)}\n`;
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
