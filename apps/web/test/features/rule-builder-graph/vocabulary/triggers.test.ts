import { describe, expect, it } from "vitest";
import {
  parameterOf,
  triggerOptions,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/triggers.js";
import { extended, served } from "./fixtures.js";

describe("trigger options over the server-written vocabulary (E37-S02)", () => {
  it("Gherkin 'The whole vocabulary is reachable on canvas': every served trigger is an option with its description, clause and parameters; a new one shows with no client change", () => {
    const vocabulary = served("manager");
    const options = triggerOptions(vocabulary);
    expect(options.map((o) => o.id)).toEqual(vocabulary.triggers?.map((t) => t.id));
    expect(options).toHaveLength(13);
    expect(options.find((o) => o.id === "on_bar_close")).toEqual({
      id: "on_bar_close",
      clause: "When a {timeframe} bar closes",
      description: "When a bar closes",
      parameters: [{ field: "timeframe", kind: "timeframe" }],
    });
    expect(
      ["on_timer", "on_schedule", "on_metric_change", "on_order_fill"].map(
        (id) => options.find((o) => o.id === id)?.parameters,
      ),
    ).toEqual([
      [{ field: "interval_ms", kind: "duration" }],
      [{ field: "cron", kind: "cron" }],
      [{ field: "metric", kind: "metric" }],
      [],
    ]);
    expect(triggerOptions(extended()).at(-1)).toEqual({
      id: "zz_new_trigger",
      clause: "zz_new_trigger",
      description: "When a new thing happens",
      parameters: [{ field: "zz_window", kind: "text" }],
    });
  });

  it("serves on_metric_change where the ticket's list says on_indicator, which no vocabulary serves", () => {
    const ids = triggerOptions(served("owner")).map((o) => o.id);
    expect([ids.includes("on_metric_change"), ids.includes("on_indicator")]).toEqual([true, false]);
  });

  it("writes an E36-D01 §5.6 clause for every served trigger", () => {
    const unwritten = triggerOptions(served("owner")).filter((o) => o.clause === o.id);
    expect(unwritten).toEqual([]);
  });

  it("an entry the generated shape leaves bare is skipped without an id, else read with no parameter", () => {
    expect(triggerOptions({ ...served("manager"), triggers: [{}, { id: "x" }] })).toEqual([
      { id: "x", clause: "x", description: "", parameters: [] },
    ]);
    const withoutTriggers = served("manager");
    delete withoutTriggers.triggers;
    expect(triggerOptions(withoutTriggers)).toEqual([]);
    expect(parameterOf("cron")).toEqual({ field: "cron", kind: "cron" });
  });
});
