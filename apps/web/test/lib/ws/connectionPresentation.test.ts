// E10-S01 (#304) S10, BQ-02 / BQ-03 (E04-D02-F08, F09, F18, F23): one connection vocabulary. For every
// link kind × cause × close code (4403 included), the CMP-076 chip, the CMP-208 / 210 status-bar word
// and the CMP-077 region split the link the same way.
import { describe, expect, it } from "vitest";
import { connectionPresentation } from "../../../src/lib/ws/state/connectionPresentation";
import { connectionRegion } from "../../../src/lib/ws/state/connectionRegion";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import { OFF, authOk, connecting, stream } from "./support/engineEvents";

const T0 = Date.UTC(2026, 9, 27, 13, 42, 5);
const LOST = { sinceMs: T0, lastDataMs: T0 - 12_000 };
const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);
const UP = run(connecting, authOk(OFF), stream("live"));
const after = (event: EngineEvent): WsState => reduce(UP, event);

type Row = readonly [
  name: string,
  state: WsState,
  chip: string,
  word: string,
  region: string | null,
  lastGoodTs: number | null,
];
const ROWS: readonly Row[] = [
  ["live", UP, "live", "live", null, null],
  ["a first connect", INITIAL_WS_STATE, "reconnecting+first", "connecting", null, null],
  [
    "a first connect's retry",
    run({ type: "reconnecting", attempt: 1, nextAttemptAtMs: T0 }),
    "reconnecting(1)",
    "reconnecting",
    null,
    null,
  ],
  [
    "a running retry",
    after({ type: "reconnecting", attempt: 2, nextAttemptAtMs: T0 + 4e3, lost: LOST }),
    "reconnecting(2)",
    "reconnecting",
    "disconnected",
    LOST.lastDataMs,
  ],
  [
    "a retry's socket opening",
    reduce(
      after({ type: "reconnecting", attempt: 1, nextAttemptAtMs: T0, lost: LOST }),
      connecting,
    ),
    "reconnecting",
    "reconnecting",
    "disconnected",
    LOST.lastDataMs,
  ],
  ...(["offline", "tailnet_unreachable", "backend_unreachable"] as const).map((cause): Row => [
    `a shell cause (${cause})`,
    after({ type: "offline", cause, lost: LOST }),
    "reconnecting",
    "reconnecting",
    "disconnected",
    LOST.lastDataMs,
  ]),
  ...([1002, 1009, 4400, undefined] as const).map((closeCode): Row => [
    `a fatal close (${String(closeCode)})`,
    after({ type: "offline", cause: "fatal", closeCode, lost: LOST }),
    "offline",
    "offline",
    "fatal",
    LOST.lastDataMs,
  ]),
  [
    "a session end (4403)",
    after({ type: "offline", cause: "fatal", closeCode: 4403, lost: LOST }),
    "offline",
    "offline",
    "session",
    LOST.lastDataMs,
  ],
];

const chipKey = ({ chip }: ReturnType<typeof connectionPresentation>): string =>
  `${chip.status}${chip.firstConnect === true ? "+first" : ""}${chip.attempt === undefined ? "" : `(${chip.attempt})`}`;

describe("connectionPresentation: one vocabulary across the chip, the status bar and the region", () => {
  it.each(ROWS)("%s", (_name, state, chip, word, region, lastGoodTs) => {
    const shown = connectionPresentation(state);
    expect(chipKey(shown)).toBe(chip);
    expect(shown.word).toBe(word);
    expect(shown.lastGoodTs).toBe(lastGoodTs);
    expect(connectionRegion(state, T0 + 1_000)?.reason ?? null).toBe(region);
    // the split agrees: "offline" only once the retry stopped, on all three surfaces
    expect(shown.chip.status === "offline").toBe(region === "fatal" || region === "session");
    expect(shown.word === "offline").toBe(shown.chip.status === "offline");
  });

  it("feeds no Delayed or Stale from `quality` (BQ-03: no guessed mapping)", () => {
    for (const quality of ["lagging", "saturated"] as const) {
      const state: WsState = { ...UP, quality };
      expect(connectionPresentation(state).chip.status).toBe("live");
    }
  });
});
