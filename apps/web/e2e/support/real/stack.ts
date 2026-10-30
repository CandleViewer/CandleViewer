import { closeSync, mkdirSync, openSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { serverClock, type ServerClock } from "../serverClock";

// E09-Q02 (#293) PR 2 (#2490): what the real lane hands its specs, through the environment only
// (`.github/workflows/e2e-auth-real.yml` makes each value per run; nothing is committed):
// - `CV_E2E_REAL_USERS_FILE`: the fixture users `seed_fixture_user.py` seeded, a JSON array of
//   `{ "username", "totp_file" }`; each `totp_file` is the mode-0600 file `--totp-secret-out` wrote;
// - `CV_E2E_REAL_PASSWORD`: their password, generated per run;
// - `CV_TEST_CLOCK_FILE`: the API's clock offset file (`serverClock.ts`), so codes are made at the
//   server's time.
// No value leaves this module except through a function a spec calls when it needs it: no object
// here prints a password, seed or code if a spec logs it.

/** A seeded fixture user: one per test, so no two tests share a lockout counter or a TOTP step. */
export interface FixtureUser {
  readonly username: string;
  /** The base32 TOTP seed, read from its file when a code is made. */
  readonly seed: () => string;
}

export interface RealStack {
  /** The fixture users' password. */
  readonly password: () => string;
  /** The API's test clock: `totpAt` makes a code at the server's time. */
  readonly clock: ServerClock;
  /** A fixture user no other test of this run has claimed, across workers. */
  readonly claimUser: () => FixtureUser;
}

const USERNAME = /^[a-z0-9][a-z0-9-]{0,62}$/u;
/** The shortest password the lane makes (it makes 64 hex digits): a shorter one is a wiring fault. */
const MIN_PASSWORD = 16;

function required(name: string): string {
  const value = process.env[name] ?? "";
  if (value === "") throw new Error(`${name} is not set: run the lane through e2e-auth-real.yml`);
  return value;
}

/** The users file's entries, refused whole if one is malformed (the message names no value). */
export function parseUsers(text: string): readonly { username: string; totpFile: string }[] {
  const parsed: unknown = JSON.parse(text);
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("the users file must be a non-empty JSON array");
  }
  return parsed.map((entry: unknown, index) => {
    const { username, totp_file: totpFile } = (entry ?? {}) as Record<string, unknown>;
    if (typeof username !== "string" || !USERNAME.test(username)) {
      throw new Error(`users file entry ${index}: username is not a seeded fixture name`);
    }
    if (typeof totpFile !== "string" || !isAbsolute(totpFile)) {
      throw new Error(`users file entry ${index}: totp_file is not an absolute path`);
    }
    return { username, totpFile };
  });
}

/**
 * The first user whose claim file this call creates. A claim is a file created with `O_EXCL` in
 * `claims`, so two workers never get one user, and a user is never reused within the run.
 */
export function claimFrom<T>(users: readonly T[], claims: string): T {
  mkdirSync(claims, { recursive: true, mode: 0o700 });
  for (const [index, user] of users.entries()) {
    try {
      closeSync(openSync(join(claims, String(index)), "wx"));
      return user;
    } catch (error) {
      if ((error as { code?: string }).code !== "EEXIST") throw error;
    }
  }
  throw new Error(`all ${users.length} fixture users are claimed: the lane must seed more`);
}

let cached: RealStack | undefined;

/** The lane's stack, read from the environment once per worker. */
export function realStack(): RealStack {
  if (cached !== undefined) return cached;
  const usersFile = required("CV_E2E_REAL_USERS_FILE");
  if (!isAbsolute(usersFile)) throw new Error("CV_E2E_REAL_USERS_FILE must be an absolute path");
  const users = parseUsers(readFileSync(usersFile, "utf8"));
  const password = required("CV_E2E_REAL_PASSWORD");
  if (password.length < MIN_PASSWORD) throw new Error("CV_E2E_REAL_PASSWORD is too short");
  const claims = join(dirname(usersFile), "claims");
  cached = {
    password: () => password,
    clock: serverClock(required("CV_TEST_CLOCK_FILE")),
    claimUser: () => {
      const { username, totpFile } = claimFrom(users, claims);
      return { username, seed: () => readFileSync(totpFile, "ascii").trim() };
    },
  };
  return cached;
}
