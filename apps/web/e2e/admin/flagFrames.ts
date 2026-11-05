// E42-Q02 (#1215) part 2: what admin-flags.stack.ts reads from a tapped socket, the flag list and
// the audit slice. Pure, so `test/e2e-admin-flags.test.ts` pins each reading on synthetic frames
// and rows. A `system` push is a delta on the `system` topic (`23` §3.1, §15.9): `t` "d", `ch`
// "system", the server's send time in `ts` (epoch ms) and the body in `p`; the topic's snap at
// `auth_ok` is never one of the frames read here.

/** A frame as the tap keeps it (`support/real/wsTap.ts`). */
export type Frame = Readonly<Record<string, unknown>>;

/** An audit row as the slice reads it (`support/real/failureArtefacts.ts`). */
export type Row = Readonly<Record<string, unknown>>;

/** A `feature_flags` push's value for one key, with the frame's server send time. */
export interface FlagPush {
  readonly ts: number;
  readonly value: unknown;
}

/** A `notice` push, with the frame's server send time and the members its body carries. */
export interface NoticePush {
  readonly ts: number;
  readonly severity: unknown;
  readonly members: readonly string[];
}

const record = (value: unknown): Readonly<Record<string, unknown>> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Readonly<Record<string, unknown>>)
    : null;

/** The `system` deltas from `from` on (an index into `frames`), each with its `ts` and body. */
export function systemDeltas(
  frames: readonly Frame[],
  from = 0,
): { readonly ts: number; readonly body: Readonly<Record<string, unknown>> }[] {
  return frames.slice(from).flatMap((frame) => {
    const body = record(frame["p"]);
    const ts = frame["ts"];
    if (frame["t"] !== "d" || frame["ch"] !== "system" || body === null) return [];
    if (typeof ts !== "number" || !Number.isFinite(ts)) return [];
    return [{ ts, body }];
  });
}

/** Each `feature_flags` push of `key` from `from` on, in the order the socket got them. */
export function flagPushes(frames: readonly Frame[], key: string, from = 0): FlagPush[] {
  return systemDeltas(frames, from).flatMap(({ ts, body }) => {
    const flags = record(body["feature_flags"]);
    if (body["kind"] !== "feature_flags" || flags === null || !Object.hasOwn(flags, key)) {
      return [];
    }
    return [{ ts, value: flags[key] }];
  });
}

/** Every flag key a `feature_flags` push named from `from` on, once each, sorted. */
export function pushedKeys(frames: readonly Frame[], from = 0): string[] {
  const keys = systemDeltas(frames, from).flatMap(({ body }) => {
    const flags = record(body["feature_flags"]);
    return body["kind"] === "feature_flags" && flags !== null ? Object.keys(flags) : [];
  });
  return [...new Set(keys)].sort();
}

/** Each `notice` push with `reason` from `from` on, with the members its body carries, sorted. */
export function noticePushes(frames: readonly Frame[], reason: string, from = 0): NoticePush[] {
  return systemDeltas(frames, from).flatMap(({ ts, body }) =>
    body["kind"] === "notice" && body["reason"] === reason
      ? [{ ts, severity: body["severity"], members: Object.keys(body).sort() }]
      : [],
  );
}

/** A flag as `GET /admin/feature-flags` lists it: its value and the version a write names. */
export interface ListedFlag {
  readonly value: unknown;
  readonly updatedAt: string;
}

/** `key`'s entry in a `GET /admin/feature-flags` body; throws when it is missing or unversioned. */
export function listedFlag(body: unknown, key: string): ListedFlag {
  const items = record(body)?.["items"];
  const found = (Array.isArray(items) ? items : []).map(record).find((i) => i?.["key"] === key);
  const updatedAt = found?.["updated_at"];
  if (found === undefined || found === null || typeof updatedAt !== "string") {
    throw new Error(`the flag list has no versioned ${key}`);
  }
  return { value: found["value"], updatedAt };
}

/** The `updated_at` a `PUT /admin/feature-flags/{key}` answer carries: the next write's version. */
export function writtenVersion(body: unknown): string {
  const updatedAt = record(body)?.["updated_at"];
  if (typeof updatedAt !== "string") throw new Error("the flag write answered no updated_at");
  return updatedAt;
}

/** Rows of `action` the request `requestId` wrote, in the slice's order. */
export function rowsOf(rows: readonly Row[], action: string, requestId: string): Row[] {
  return rows.filter((r) => r["action"] === action && r["request_id"] === requestId);
}

/**
 * The write-ahead `flags.change` record of the write `requestId` made: its first successful
 * `flags.change`, written before the flag commits and so before any push (`writes.py`: intent,
 * commit, push, outcome). A timing measured from it is never shorter than one from the commit.
 */
export function writeAheadRecord(rows: readonly Row[], requestId: string): Row | undefined {
  return rowsOf(rows, "flags.change", requestId).find((r) => r["outcome"] === "success");
}

/** Milliseconds from an audit row's `event_ts` to a frame's `ts`: both the server's wall clock. */
export function recordToFrameMs(row: Row, frameTs: number): number {
  const at = Date.parse(String(row["event_ts"]));
  if (!Number.isFinite(at) || !Number.isFinite(frameTs)) {
    throw new Error("a record without a readable event_ts, or a frame without a ts");
  }
  return frameTs - at;
}

/** The step-up records as `action:class` (`b16_session.py` records the class as the reason). */
export function stepUpTrail(rows: readonly Row[]): string[] {
  return rows
    .filter((r) => typeof r["action"] === "string" && r["action"].startsWith("auth.step_up_"))
    .map((r) => `${String(r["action"])}:${String(r["reason"])}`);
}

/** Whether `expected` occurs in `actual` in order, other entries allowed between. */
export function inOrder(actual: readonly string[], expected: readonly string[]): boolean {
  let at = 0;
  for (const entry of actual) if (at < expected.length && entry === expected[at]) at += 1;
  return at === expected.length;
}

/** One thing to put back after a test: what it restores, and how. */
export interface Undo {
  readonly label: string;
  run(): Promise<void>;
}

/**
 * Runs `stack` newest first and empties it, so the next test starts clean. A step that throws is
 * reported as `label: message` and the rest still run: a cleanup failure never hides the test's own.
 */
export async function runUndos(stack: Undo[]): Promise<string[]> {
  const failed: string[] = [];
  for (let step = stack.pop(); step !== undefined; step = stack.pop()) {
    try {
      await step.run();
    } catch (error) {
      failed.push(`${step.label}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  return failed;
}
