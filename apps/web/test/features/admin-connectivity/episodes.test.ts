import { describe, expect, it } from "vitest";
import {
  REGION_BUDGET_MS,
  createEpisodeCoalescer,
  type Observation,
  type Politeness,
} from "../../../src/features/admin-connectivity/episodes";
import { THRESHOLDS } from "../../../src/features/admin-connectivity/selectState";

interface Said {
  readonly politeness: Politeness;
  readonly text: string;
  readonly key: string;
}

function rig(): {
  said: Said[];
  advance: (ms: number) => void;
  c: ReturnType<typeof createEpisodeCoalescer>;
} {
  let t = 1_000_000;
  const said: Said[] = [];
  const c = createEpisodeCoalescer({
    now: () => t,
    say: (politeness, text, key) => said.push({ politeness, text, key }),
  });
  return { said, c, advance: (ms) => (t += ms) };
}

const held = (state: Observation["state"], subject = "a", region = "rate"): Observation => ({
  region,
  state,
  subject,
});

describe("the episode coalescer (fake clock)", () => {
  it("says an entry once after the join window, then nothing at 1 Hz", () => {
    const { said, c, advance } = rig();
    for (let i = 0; i < 30; i += 1) {
      c.observe([held("S-03")]);
      advance(1_000);
    }
    expect(said).toHaveLength(1);
    expect(said[0]).toMatchObject({ politeness: "polite", text: "Throttled" });
  });

  it("holds the line until the 1 s join window has passed", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-03")]);
    expect(said).toHaveLength(0);
    advance(THRESHOLDS.episodeJoinMs);
    c.flush();
    expect(said).toHaveLength(1);
  });

  it("joins entries for several accounts inside 1 s into one counted line", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-03", "a")]);
    advance(400);
    c.observe([held("S-03", "a"), held("S-03", "b")]);
    advance(700);
    c.flush();
    expect(said.map((s) => s.text)).toEqual(["Throttled: 2 accounts"]);
  });

  it("continues the episode on a re-entry inside 5 s, and starts a new one after", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-04")]);
    advance(1_000);
    c.observe([held("S-04")]); // last seen here; the line goes out
    advance(2_000);
    c.observe([]); // exited
    advance(2_000);
    c.observe([held("S-04")]); // back 4 s after the last sighting: the same episode
    advance(2_000);
    c.flush();
    expect(said).toHaveLength(1);
    c.observe([]);
    advance(THRESHOLDS.episodeCloseMs);
    c.observe([]);
    c.observe([held("S-04")]); // a new episode
    advance(REGION_BUDGET_MS);
    c.flush();
    expect(said).toHaveLength(2);
    expect(said[1]?.key).not.toBe(said[0]?.key);
  });

  it("speaks at most once per 5 s in the shell's polite region; later entries join the next line", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-03")]);
    advance(1_000);
    c.observe([held("S-03")]); // the first line goes out here
    advance(1_000);
    c.observe([held("S-03"), held("S-09", "clock"), held("S-20", "queue")]);
    advance(2_000);
    c.flush();
    expect(said).toHaveLength(1); // inside the 5 s window: nothing more
    advance(REGION_BUDGET_MS);
    c.flush();
    expect(said).toHaveLength(2);
    expect(said[1]?.text).toBe("Dropping updates. Clock drift");
  });

  it("never holds back or drops the assertive Disconnected line", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-03")]);
    advance(1_000);
    c.observe([held("S-03"), held("S-06", "net", "net")]);
    expect(said.filter((s) => s.politeness === "assertive")).toHaveLength(1);
    expect(said.find((s) => s.politeness === "assertive")?.text).toBe("Disconnected");
  });

  it("announces never-states and the healthy state at no time", () => {
    const { said, c, advance } = rig();
    for (const id of ["S-01", "S-13", "S-14", "S-15", "S-19"] as const) {
      c.observe([held(id, "a", id)]);
      advance(10_000);
      c.flush();
    }
    expect(said).toHaveLength(0);
  });

  it("only ever says a state word and a count: no figure, id or time", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-04")]);
    advance(2_000);
    c.flush();
    for (const s of said) expect(s.text).not.toMatch(/\d{2}|[0-9a-f]{8}-/);
  });

  it("reset forgets every episode", () => {
    const { said, c, advance } = rig();
    c.observe([held("S-03")]);
    c.reset();
    advance(1_000);
    c.flush();
    expect(said).toHaveLength(0);
  });
});
