import { readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, sep } from "node:path";
import { totp } from "./totp";

// E09-Q02 (#293) for the real-backend lane (#2086 part a): the server test clock. With `CV_TEST_CLOCK` on, the
// API reads its auth time (idle lock, absolute lifetime, step-up, MFA windows, lockouts) as real UTC plus the offset
// in `CV_TEST_CLOCK_FILE` at every decision, so a spec moves it by rewriting the file and waits for nothing
// (`services/api/candleviewer/auth/testnet_clock.py`). The file is written as a temp file and then renamed over the
// target, so the server never reads a half-written offset. The stub specs do not use it: their clock is
// `SessionStore.advance` (`contexts.ts`) and `page.clock`. Forward only: rows written under an earlier offset
// (sessions, lockouts) would otherwise be judged by a clock that ran backwards.

/** The reader's grammar (`_OFFSET_RE`): signed decimal seconds, at most 9 integer digits, microsecond precision. */
export const OFFSET_PATTERN = "[+-]?[0-9]{1,9}(?:\\.[0-9]{1,6})?";
/** The reader refuses a file longer than this (`_MAX_FILE_BYTES`). */
export const MAX_OFFSET_BYTES = 32;
const OFFSET = new RegExp(`^${OFFSET_PATTERN}$`, "u");
const US = 1_000_000;
/** 999 999 999.999 999 s in microseconds: the largest offset the grammar holds, and a safe integer. */
const MAX_US = 999_999_999 * US + 999_999;

/** The file operations the clock uses: injected by its unit test, `node:fs` otherwise. */
export interface ClockFs {
  /** Throws an error with `code: "ENOENT"` when there is no file. */
  readFile(path: string): string;
  /** Creates `path` (it must not exist yet) holding `data`. */
  createFile(path: string, data: string): void;
  rename(from: string, to: string): void;
  remove(path: string): void;
}

const nodeFs: ClockFs = {
  readFile: (path) => readFileSync(path, "ascii"),
  // world-readable: the API may run as another user (a container); the file holds no secret
  createFile: (path, data) => writeFileSync(path, data, { flag: "wx", mode: 0o644 }),
  rename: renameSync,
  remove: (path) => rmSync(path, { force: true }),
};

/** An offset in microseconds as the reader's canonical text: `900`, `-5.5`, `0.000001`. */
export function formatOffset(us: number): string {
  if (!Number.isSafeInteger(us) || Math.abs(us) > MAX_US) {
    throw new RangeError(`an offset of ${us} microseconds is outside the reader's grammar`);
  }
  const whole = Math.trunc(Math.abs(us) / US);
  const fraction = String(Math.abs(us) % US)
    .padStart(6, "0")
    .replace(/0+$/u, "");
  return `${us < 0 ? "-" : ""}${whole}${fraction === "" ? "" : `.${fraction}`}`;
}

/** The microseconds of the reader's text (it strips white space first); anything else is refused, as it does. */
export function parseOffset(text: string): number {
  const trimmed = text.trim();
  if (!OFFSET.test(trimmed))
    throw new SyntaxError("not signed decimal seconds, such as 301 or -5.5");
  const [whole = "", fraction = ""] = trimmed.replace(/^[+-]/u, "").split(".");
  const us = Number(whole) * US + Number(fraction.padEnd(6, "0"));
  return trimmed.startsWith("-") ? -us : us;
}

export interface ServerClock {
  readonly file: string;
  /** The offset in the file, in microseconds; no file is no offset, as the server reads it. */
  offsetMicros(): number;
  /** Moves the server's auth time `seconds` on and returns the new offset in microseconds. Never backwards. */
  advance(seconds: number): number;
  /** The server's auth time in epoch ms: real UTC plus the offset. */
  serverNow(): number;
  /** The TOTP code for `secretBase32` at the server's time, `stepOffset` whole steps on (one use per step: A06). */
  totpAt(secretBase32: string, stepOffset?: number): string;
}

/**
 * The clock of the API whose `CV_TEST_CLOCK_FILE` is `file`: absolute, without `..`, as `Settings` requires. The
 * file is the state, so a second clock on it carries on from the first.
 */
export function serverClock(
  file: string,
  { now = Date.now, fs = nodeFs }: { now?: () => number; fs?: ClockFs } = {},
): ServerClock {
  if (!isAbsolute(file) || file.split(sep).includes("..")) {
    throw new RangeError("CV_TEST_CLOCK_FILE must be an absolute path without `..`");
  }
  let writes = 0;
  const offsetMicros = (): number => {
    try {
      return parseOffset(fs.readFile(file));
    } catch (error) {
      if ((error as { code?: string }).code === "ENOENT") return 0;
      throw error; // anything but a missing file fails closed, as the server does
    }
  };
  const serverNow = (): number => now() + Math.round(offsetMicros() / 1000);
  return {
    file,
    offsetMicros,
    serverNow,
    advance(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0) {
        throw new RangeError("the server clock only moves forward");
      }
      const next = offsetMicros() + Math.round(seconds * US);
      const text = formatOffset(next); // refuses an offset the reader would refuse, before anything is written
      writes += 1;
      const temp = join(dirname(file), `${basename(file)}.${process.pid}.${writes}.tmp`);
      fs.createFile(temp, text);
      try {
        fs.rename(temp, file);
      } catch (error) {
        fs.remove(temp);
        throw error;
      }
      return next;
    },
    totpAt: (secretBase32, stepOffset = 0) => totp(secretBase32, serverNow(), stepOffset),
  };
}
