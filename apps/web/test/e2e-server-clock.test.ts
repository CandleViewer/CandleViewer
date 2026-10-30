// @vitest-environment node
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  MAX_OFFSET_BYTES,
  OFFSET_PATTERN,
  formatOffset,
  parseOffset,
  serverClock,
  type ClockFs,
} from "../e2e/support/serverClock";
import { OTP_SEED, totp } from "../e2e/support/totp";

/**
 * E09-Q02 (#293): the server-clock helper of the real lane writes the offset file the API reads
 * (`auth/testnet_clock.py`, #2086): its grammar, the temp-then-rename write, forward-only moves, and the codes it
 * derives at the server's time. The Python reader is the source of the grammar, so one test reads its source.
 */
const NOW = Date.UTC(2026, 9, 30, 10, 0, 0);
const READER = resolve(
  import.meta.dirname,
  "../../../services/api/candleviewer/auth/testnet_clock.py",
);

let dir: string;
let file: string;
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "cv-server-clock-"));
  file = join(dir, "clock-offset");
});
afterEach(() => rmSync(dir, { recursive: true, force: true }));

const clock = (fs?: ClockFs) => serverClock(file, { now: () => NOW, ...(fs && { fs }) });
const stored = (): string => readFileSync(file, "ascii");

/** What the reader's source says `name` is, or a failure that says where to look when the source was reshaped. */
function readerConstant(source: string, name: string, shape: RegExp): string {
  const value = shape.exec(source)?.[1];
  if (value === undefined) {
    throw new Error(
      `could not find \`${name}\` in ${READER}: the reader was reshaped, so re-point this test`,
    );
  }
  return value;
}

describe("the offset grammar", () => {
  it("is the reader's: the same pattern and the same byte cap, read from testnet_clock.py", () => {
    const source = readFileSync(READER, "utf8");
    expect(readerConstant(source, "_OFFSET_RE", /_OFFSET_RE = re\.compile\(r"(.*)"\)/u)).toBe(
      OFFSET_PATTERN,
    );
    expect(Number(readerConstant(source, "_MAX_FILE_BYTES", /_MAX_FILE_BYTES = (\d+)/u))).toBe(
      MAX_OFFSET_BYTES,
    );
  });

  it("names the constant it could not find when the reader's source was reshaped", () => {
    expect(() => readerConstant("no such line", "_OFFSET_RE", /_OFFSET_RE = (.*)/u)).toThrow(
      "could not find `_OFFSET_RE`",
    );
  });

  it.each([
    [0, "0"],
    [900 * 1e6, "900"],
    [301.5 * 1e6, "301.5"],
    [-5.5 * 1e6, "-5.5"],
    [1, "0.000001"],
    [43_200 * 1e6 + 60_000_000, "43260"],
    [999_999_999 * 1e6 + 999_999, "999999999.999999"],
    [-(999_999_999 * 1e6 + 999_999), "-999999999.999999"],
  ])("formats %d microseconds as %s, which the reader accepts", (us, text) => {
    expect(formatOffset(us)).toBe(text);
    expect(text).toMatch(new RegExp(`^${OFFSET_PATTERN}$`, "u"));
    expect(Buffer.byteLength(text)).toBeLessThanOrEqual(MAX_OFFSET_BYTES);
    expect(parseOffset(text)).toBe(us);
  });

  it.each([1e15, -1e15, 0.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "refuses to format %d microseconds, which the reader would refuse",
    (us) => {
      expect(() => formatOffset(us)).toThrow(RangeError);
    },
  );

  it.each(["", " ", "1e3", "0x10", "1.", ".5", "--1", "1.1234567", "1234567890", "12 3", "NaN"])(
    "refuses %j, as the reader does",
    (text) => {
      expect(() => parseOffset(text)).toThrow(SyntaxError);
    },
  );

  it("strips white space around the text, as the reader does", () => {
    expect(parseOffset(" 301\n")).toBe(301 * 1e6);
  });
});

describe("serverClock.advance", () => {
  it("writes a temp file in the same directory, then renames it over the offset file", () => {
    const steps: string[] = [];
    const spy: ClockFs = {
      readFile: (path) => readFileSync(path, "ascii"),
      createFile: (path, data) => (steps.push(`create ${path} ${data}`), writeFileSync(path, data)),
      rename: (from, to) => (steps.push(`rename ${from} ${to}`), renameSync(from, to)),
      remove: (path) => (steps.push(`remove ${path}`), rmSync(path, { force: true })),
    };
    expect(clock(spy).advance(901)).toBe(901 * 1e6);
    expect(steps).toHaveLength(2);
    const [create, rename] = steps.map((step) => step.split(" "));
    const temp = create?.[1] ?? "";
    expect(create?.[0]).toBe("create");
    expect(create?.[2]).toBe("901");
    expect(rename).toEqual(["rename", temp, file]); // the target is only ever the rename's destination
    expect(temp).not.toBe(file);
    expect(join(temp, "..")).toBe(dir);
    expect(readdirSync(dir)).toEqual(["clock-offset"]); // no temp file is left behind
    expect(stored()).toBe("901");
  });

  it("leaves the file world-readable whatever the umask, for an API that runs as another user", () => {
    const umask = process.umask(0o077); // a strict umask would make the file's `mode` 0600
    try {
      clock().advance(60);
    } finally {
      process.umask(umask);
    }
    expect(statSync(file).mode & 0o777).toBe(0o644);
  });

  it("carries on from the file: its own calls add up, and so does a second clock on it", () => {
    clock().advance(900);
    clock().advance(60.5);
    expect(stored()).toBe("960.5");
    expect(clock().offsetMicros()).toBe(960.5 * 1e6);
  });

  it("moves forward only: a negative or non-finite step changes nothing", () => {
    clock().advance(30);
    for (const step of [-1, Number.NaN, Number.NEGATIVE_INFINITY]) {
      expect(() => clock().advance(step)).toThrow(RangeError);
    }
    expect(stored()).toBe("30");
  });

  it("refuses a step past the grammar before it writes anything", () => {
    clock().advance(999_999_000);
    expect(() => clock().advance(1_000)).toThrow(RangeError);
    expect(stored()).toBe("999999000");
    expect(readdirSync(dir)).toEqual(["clock-offset"]);
  });

  it("keeps the old offset and removes the temp file when the rename fails", () => {
    clock().advance(60);
    const failing: ClockFs = {
      readFile: (path) => readFileSync(path, "ascii"),
      createFile: (path, data) => writeFileSync(path, data, { flag: "wx" }),
      rename: () => {
        throw new Error("rename refused");
      },
      remove: (path) => rmSync(path, { force: true }),
    };
    expect(() => clock(failing).advance(60)).toThrow("rename refused");
    expect(stored()).toBe("60");
    expect(readdirSync(dir)).toEqual(["clock-offset"]);
  });

  it("keeps the old offset and removes what a failed create left of the temp file", () => {
    clock().advance(60);
    const failing: ClockFs = {
      readFile: (path) => readFileSync(path, "ascii"),
      createFile: (path, data) => {
        writeFileSync(path, data.slice(0, 1)); // part of the text reached the disk, then the write failed
        throw new Error("disk full");
      },
      rename: () => {
        throw new Error("rename must not run after a failed create");
      },
      remove: (path) => rmSync(path, { force: true }),
    };
    expect(() => clock(failing).advance(60)).toThrow("disk full");
    expect(stored()).toBe("60");
    expect(readdirSync(dir)).toEqual(["clock-offset"]);
  });

  it("fails closed on a file the reader would refuse, instead of writing over it", () => {
    writeFileSync(file, "not a number");
    expect(() => clock().advance(1)).toThrow(SyntaxError);
    expect(stored()).toBe("not a number");
  });

  it("takes only an absolute path without `..`, the first two of the four rules Settings applies", () => {
    expect(() => serverClock("clock-offset")).toThrow(RangeError);
    expect(() => serverClock(`${dir}${sep}..${sep}clock-offset`)).toThrow(RangeError); // join() would fold it away
    mkdirSync(join(dir, "sub"));
    expect(() => serverClock(join(dir, "sub", "clock-offset"))).not.toThrow();
  });
});

describe("serverClock.serverNow and totpAt", () => {
  it("reads real UTC with no offset while there is no file", () => {
    expect(existsSync(file)).toBe(false);
    expect(clock().serverNow()).toBe(NOW);
  });

  it("is real UTC plus the offset in the file", () => {
    const c = clock();
    c.advance(15 * 60 + 1);
    expect(c.serverNow()).toBe(NOW + 901_000);
  });

  it("derives the TOTP code at the server's time, not the wall clock's", () => {
    const c = clock();
    const before = c.totpAt(OTP_SEED);
    expect(before).toBe(totp(OTP_SEED, NOW));
    c.advance(30 * 4);
    expect(c.totpAt(OTP_SEED)).toBe(totp(OTP_SEED, NOW + 120_000));
    expect(c.totpAt(OTP_SEED)).not.toBe(before);
  });

  it("gives the next step's code for a step offset, which a +30 s clock hop reaches too (A06)", () => {
    const c = clock();
    const next = c.totpAt(OTP_SEED, 1);
    expect(next).toBe(totp(OTP_SEED, NOW + 30_000));
    c.advance(30);
    expect(c.totpAt(OTP_SEED)).toBe(next);
  });
});
