/**
 * E16-S04, SCR-142's model (E16-D04 §2–§5, §14; E16-D06 §16.2; BQ-5): the stamp and its stale form after two
 * samples, the two meters with their denominators, the headline keyed on `level`, the projection, the formula and
 * the scale, what stops first on every level ≥ 1, the three tier cards with the "all tiers" fallbacks and health as
 * text, the per-symbol rows and the attribution line, and the backlog's warning. Fixture: E16-D04's (`22`'s
 * `getStorageUsage` example and its level states); every expected string is the deck's (`E16-D06-copy.json`).
 */
import { describe, expect, it } from "vitest";
import { diskFacts } from "../../../../src/features/recorder/model";
import {
  LAG_WARN_ROWS,
  STALE_AFTER_MS,
  accelerationWord,
  ageText,
  attributionLine,
  budgetMeter,
  causeLine,
  degradationOf,
  formatRate,
  formatVolume,
  formulaLine,
  headlineOf,
  ingestionLine,
  isBacklogged,
  lagBannerOf,
  lagThresholdLine,
  projectionLine,
  scaleLine,
  stampView,
  symbolRows,
  tierViews,
  volumeMeter,
  type TierRow,
} from "../../../../src/features/recorder/storage/storageModel";
import { STORAGE_DECK } from "../../../../src/features/recorder/storage/storageCopy";
import {
  CLOCK,
  HEALTH,
  LEVEL_1,
  LEVEL_2,
  LEVEL_3,
  POLICY,
  QUESTDB_DOWN,
  REPORT,
  SAMPLED,
  VOLUME_REFUSED,
  frameWith,
  healthWith,
} from "./storageFixtures";

const facts = (report = REPORT) => diskFacts(report, null);
const DETAIL = STORAGE_DECK["storage.degradation.detail"][0];
const FIRST_STOPS = STORAGE_DECK["storage.degradation"][0];

describe("the sample stamp (D04 §2 (a), R-2; `14` §0.5 rule 4)", () => {
  it("test_stamp_fresh_names_the_sample_and_its_cadence", () => {
    expect(stampView(SAMPLED, CLOCK, false)).toEqual({
      text: "Sampled 10:31:03 UTC (every 60 s)",
      stale: false,
    });
    expect(stampView(SAMPLED, CLOCK, false)?.text).toBe(STORAGE_DECK["storage.stamp"][1]);
  });

  it("test_stamp_turns_stale_only_past_two_samples", () => {
    expect(STALE_AFTER_MS).toBe(120_000);
    expect(stampView(SAMPLED, SAMPLED + STALE_AFTER_MS, false)?.stale).toBe(false);
    expect(stampView(SAMPLED, SAMPLED + STALE_AFTER_MS + 1, false)).toEqual({
      text: "Sampled 10:31:03 UTC, stale (2 min old)",
      stale: true,
    });
    expect(stampView(SAMPLED, SAMPLED + 185_000, false)?.text).toBe(
      STORAGE_DECK["storage.stamp.stale"][1],
    );
  });

  it("test_stamp_after_a_failed_read_is_the_last_report_in_its_stale_form_never_the_fresh_one", () => {
    expect(stampView(SAMPLED, SAMPLED + 65_000, true)).toEqual({
      text: "Sampled 10:31:03 UTC, stale (1 min old)",
      stale: true,
    });
  });

  it("test_stamp_before_any_report_is_sampling_and_after_a_failure_nothing", () => {
    expect(stampView(null, CLOCK, false)).toEqual({ text: "Sampling…", stale: false });
    expect(stampView(null, CLOCK, true)).toBeNull();
  });

  it.each([
    [0, "0 s"],
    [59_999, "59 s"],
    [60_000, "1 min"],
    [185_000, "3 min"],
    [3_599_999, "59 min"],
    [3_600_000, "1 h"],
    [3_660_000, "1 h 1 min"],
  ])("test_age_%i_ms_reads_%s", (ms, text) => {
    expect(ageText(ms)).toBe(text);
  });
});

describe("the two meters (D04 §2 (b), D04-D1, R-3)", () => {
  it("test_budget_meter_divides_the_recorded_bytes_by_cap_bytes", () => {
    expect(budgetMeter(facts())).toEqual({
      label: "Recording budget",
      value: 59.4,
      text: "1,188.0 GB of 2,000.0 GB (59.4 %)",
      tone: "default",
    });
    const [label, text] = STORAGE_DECK["storage.meter.budget"][1].split(": ");
    expect([budgetMeter(facts())?.label, budgetMeter(facts())?.text]).toEqual([label, text]);
  });

  it("test_volume_meter_divides_the_used_volume_by_its_total_and_names_the_free_space", () => {
    expect(volumeMeter(REPORT)).toEqual({
      label: "Disk volume",
      value: 30.1,
      text: "1.2 TB of 4.0 TB (30.1 %), 2.8 TB free",
      tone: "default",
    });
    const [label, text] = STORAGE_DECK["storage.meter.volume"][1].split(": ");
    expect([volumeMeter(REPORT)?.label, volumeMeter(REPORT)?.text]).toEqual([label, text]);
  });

  it("test_budget_meter_tone_follows_level_never_the_bytes", () => {
    expect(budgetMeter(facts(LEVEL_1))).toMatchObject({
      text: "1,610.0 GB of 2,000.0 GB (80.5 %)",
      tone: "warning",
    });
    expect(budgetMeter(facts(LEVEL_2))?.tone).toBe("warning");
    expect(budgetMeter(facts(LEVEL_3))).toMatchObject({
      text: "1,900.0 GB of 2,000.0 GB (95.0 %)",
      tone: "danger",
    });
    // The refused volume: level 3 over unchanged bytes (D04 r6's board 03 fix).
    expect(budgetMeter(facts(VOLUME_REFUSED))).toMatchObject({
      text: "1,188.0 GB of 2,000.0 GB (59.4 %)",
      tone: "danger",
    });
  });

  it("test_live_frame_moves_the_budget_meter_while_the_volume_keeps_its_sample", () => {
    const live = diskFacts(REPORT, frameWith({ used_bytes: 1200000000000 }));
    expect(budgetMeter(live)?.text).toBe("1,200.0 GB of 2,000.0 GB (60.0 %)");
    expect(volumeMeter(REPORT)?.text).toBe("1.2 TB of 4.0 TB (30.1 %), 2.8 TB free");
  });

  it("test_meters_without_their_figures_are_absent", () => {
    expect(budgetMeter(diskFacts(null, null))).toBeNull();
    expect(volumeMeter(null)).toBeNull();
    expect(volumeMeter({ ...REPORT, disk_total_bytes: 0 })).toBeNull();
  });

  it.each([
    [4e12, "4.0 TB"],
    [1.204e12, "1.2 TB"],
    [900e9, "900.0 GB"],
    [1.3e6, "1.3 MB"],
  ])("test_volume_%d_bytes_reads_%s", (bytes, text) => {
    expect(formatVolume(bytes)).toBe(text);
  });
});

describe("the headline, the projection, the formula and the scale (D04 §2 (b); E16-D02 §8.3)", () => {
  it.each([
    [REPORT, "Growing · auto-record pauses in about 422 days"],
    [LEVEL_1, "Near limit · auto-record pauses in about 131 days · clears below 75 %"],
    [LEVEL_2, "Auto-record paused · resumes below 85 % of the budget with 20 % of the volume free"],
    [LEVEL_3, "Recording stopped · resumes below 90 % with 10 % of the volume free"],
    [VOLUME_REFUSED, "Recording stopped"],
  ])("test_headline_is_e16_d02s_by_level_%#", (report, text) => {
    expect(headlineOf(facts(report), POLICY, false, CLOCK, null)).toBe(text);
  });

  describe("C-486P3-02: growth 0 reads by the page's history, as SCR-140's card does (A-5309-03)", () => {
    const flat = facts({ ...REPORT, daily_growth_bytes: 0, projected_full_at: null });
    const DAY_MS = 86_400_000;

    it("test_growth_0_after_days_of_history_is_steady_never_too_early", () => {
      expect(headlineOf(flat, POLICY, false, CLOCK, CLOCK - 3 * DAY_MS)).toBe(
        "Steady · usage is not growing",
      );
    });

    it("test_growth_0_under_an_hour_or_with_no_history_is_too_early", () => {
      expect(headlineOf(flat, POLICY, false, CLOCK, CLOCK - 30 * 60_000)).toBe(
        "Too early to project",
      );
      expect(headlineOf(flat, POLICY, false, CLOCK, null)).toBe("Too early to project");
    });
  });

  it("test_projection_names_the_nearer_wall_and_the_other_ones_runway", () => {
    expect(projectionLine(facts(), CLOCK)).toBe(STORAGE_DECK["storage.projection"][1]);
    const volume = facts({
      ...REPORT,
      disk_free_bytes: 500000000000,
      projected_full_at: "2027-08-25T10:31:03Z",
    });
    expect(projectionLine(volume, CLOCK)).toBe(
      "Full in about 345 days (2027-08-25) at 1.45 GB/day: the volume is the nearer wall (the budget about 560 days)",
    );
  });

  it("test_projection_without_a_date_or_growth_is_absent", () => {
    expect(projectionLine(facts({ ...REPORT, projected_full_at: null }), CLOCK)).toBeNull();
    expect(projectionLine(facts({ ...REPORT, daily_growth_bytes: 0 }), CLOCK)).toBeNull();
  });

  it("test_formula_is_the_autostop_runway_below_the_pause", () => {
    expect(formulaLine(facts(), POLICY)).toBe(STORAGE_DECK["storage.formula"][1]);
    expect(formulaLine(facts(LEVEL_1), POLICY)).toBe(
      "(90 % × 2,000.0 GB − 1,610.0 GB) ÷ 1.45 GB/day ≈ 131 days",
    );
    expect(formulaLine(facts(LEVEL_2), POLICY)).toBeNull();
    expect(formulaLine(facts(), null)).toBeNull();
    expect(formulaLine(facts({ ...REPORT, daily_growth_bytes: 0 }), POLICY)).toBeNull();
  });

  it("test_scale_reads_the_policy_thresholds", () => {
    expect(scaleLine(POLICY)).toBe(STORAGE_DECK["storage.scale"][0]);
    expect(scaleLine(null)).toBeNull();
  });
});

describe("what stops first (AC 2/3; D04 §1.4, §5; R-5)", () => {
  it("test_level_0_states_nothing", () => {
    expect(degradationOf(facts(), POLICY)).toBeNull();
  });

  it("test_level_1_states_that_recording_pauses_before_trading_with_the_detail", () => {
    expect(degradationOf(facts(LEVEL_1), POLICY)).toEqual({ title: FIRST_STOPS, lines: [DETAIL] });
    expect(FIRST_STOPS).toBe("Recording pauses before trading is affected.");
  });

  it("test_level_2_adds_when_recording_stops", () => {
    expect(degradationOf(facts(LEVEL_2), POLICY)).toEqual({
      title: FIRST_STOPS,
      lines: [DETAIL, "Recording stops at 95 % in about 69 days"],
    });
  });

  it("test_level_3_adds_that_open_positions_keep_recording", () => {
    const fact = STORAGE_DECK["storage.level3.fact"][0];
    expect(degradationOf(facts(LEVEL_3), POLICY)).toEqual({
      title: FIRST_STOPS,
      lines: [DETAIL, fact],
    });
    expect(degradationOf(facts(VOLUME_REFUSED), POLICY)?.lines).toEqual([DETAIL, fact]);
  });

  it("test_detail_names_the_servers_thresholds", () => {
    const policy = { ...POLICY, warn_pct: 75, autostop_pct: 85, halt_pct: 92 };
    expect(degradationOf(facts(LEVEL_1), policy)?.lines[0]).toBe(
      "At 85 % of the recording budget auto-record pauses; at 92 % recording stops for symbols without an open position; orders and positions are never gated by the disk.",
    );
    expect(degradationOf(facts(LEVEL_1), null)?.lines[0]).toBe(DETAIL);
  });

  it("test_refused_volume_names_its_cause_and_acceleration_its_word", () => {
    expect(causeLine(facts(VOLUME_REFUSED))).toBe(STORAGE_DECK["storage.volume_refused"][0]);
    expect(causeLine(facts(LEVEL_3))).toBeNull();
    expect(accelerationWord(facts(LEVEL_2))).toBe("Retention accelerated");
    expect(accelerationWord(facts())).toBeNull();
  });
});

describe("the tier cards (AC 1; D04 §4; D04-G1, G4, G6, G7 fallbacks; R-1, R-4)", () => {
  const pressure = { rate: 18400, backlog: 0 };
  const views = tierViews(REPORT, HEALTH, facts(), pressure);
  const rows = (tier: number) =>
    Object.fromEntries((views[tier]?.rows ?? []).map((r) => [r.label, [r.value, r.fallback]]));

  it("test_tiers_are_the_three_in_order_named_by_the_deck", () => {
    expect(views.map((v) => [v.tier, v.title, v.name])).toEqual([
      ["questdb", "QuestDB · hot", "QuestDB"],
      ["parquet", "Parquet/DuckDB · cold", "Parquet/DuckDB"],
      ["postgres", "Postgres · relational", "Postgres"],
    ]);
  });

  it("test_every_figure_carries_its_unit_and_postgres_is_not_counted", () => {
    expect(rows(0)).toMatchObject({
      Size: ["640.0 GB", undefined],
      "Share of budget": ["32.0 %", undefined],
      Retention: ["7 d", undefined],
    });
    expect(rows(1)).toMatchObject({
      Size: ["548.0 GB", undefined],
      "Share of budget": ["27.4 %", undefined],
      Retention: ["30 d", undefined],
    });
    expect(rows(2)).toMatchObject({
      Size: ["16.0 GB", undefined],
      "Share of budget": ["not counted", undefined],
      Retention: [null, undefined],
    });
  });

  it("test_growth_and_projection_read_the_all_tiers_fallback_per_tier", () => {
    for (const tier of [0, 1, 2]) {
      expect(rows(tier)).toMatchObject({
        "Growth/day": [null, "all tiers 1.45 GB/day"],
        "Projected full": [null, "all tiers 2028-03-27"],
      });
    }
    const flat = tierViews(
      { ...REPORT, daily_growth_bytes: 0, projected_full_at: null },
      HEALTH,
      facts({ ...REPORT, daily_growth_bytes: 0, projected_full_at: null }),
      pressure,
    );
    expect(flat[0]?.rows.find((r) => r.label === "Growth/day")).toEqual({
      label: "Growth/day",
      value: null,
      fallback: "all tiers 0.00 GB/day",
    });
    expect(flat[0]?.rows.find((r) => r.label === "Projected full")).toEqual({
      label: "Projected full",
      value: null,
    });
  });

  it("test_each_tier_carries_its_own_rows_with_their_fallbacks", () => {
    expect(rows(0)["Ingestion"]).toEqual(["Ingest 18,400 msg/s, backlog 0 rows, lag —", undefined]);
    expect(rows(1)["Last compaction"]).toEqual([null, "weekly, Sundays 03:00 UTC"]);
    expect(rows(2)["Last vacuum"]).toEqual([null, undefined]);
    expect(rows(2)["Migration"]).toEqual(["1.0.0", undefined]);
    expect(Object.keys(rows(0))).not.toContain("Last compaction");
    expect(Object.keys(rows(2))).not.toContain("Ingestion");
  });

  it("test_ingestion_without_the_pressure_numbers_reads_no_value", () => {
    const quiet = tierViews(REPORT, HEALTH, facts(), { rate: null, backlog: null });
    expect(quiet[0]?.rows.find((r) => r.label === "Ingestion")?.value).toBeNull();
  });

  it("test_health_is_the_component_state_word_with_its_glyph", () => {
    expect(views.map((v) => [v.health.word, v.health.icon])).toEqual([
      ["healthy", "success"],
      ["healthy", "success"],
      ["healthy", "success"],
    ]);
    const states = ["degraded", "warning", "down", "not_deployed"] as const;
    const words = states.map((state) => {
      const one = tierViews(
        REPORT,
        healthWith("postgres", { name: "postgres", state }),
        facts(),
        pressure,
      );
      return [one[2]?.health.word, one[2]?.health.icon];
    });
    expect(words).toEqual([
      ["degraded", "warning"],
      ["warning", "warning"],
      ["down", "error"],
      ["not deployed", null],
    ]);
  });

  it("test_a_missing_component_or_report_reads_not_reported", () => {
    const missing = {
      ...HEALTH,
      components: (HEALTH.components ?? []).filter((c) => c.name !== "parquet_store"),
    };
    expect(tierViews(REPORT, missing, facts(), pressure)[1]?.health).toMatchObject({
      word: "not reported",
      icon: null,
      down: false,
    });
    expect(tierViews(REPORT, null, facts(), pressure).map((v) => v.health.word)).toEqual([
      "not reported",
      "not reported",
      "not reported",
    ]);
  });

  it("test_a_tier_down_names_since_when_and_leaves_the_others", () => {
    const down = tierViews(REPORT, QUESTDB_DOWN, facts(), pressure);
    expect(down[0]?.health).toMatchObject({ word: "down", down: true });
    expect(down[0]?.unreachable).toBe(STORAGE_DECK["storage.tier.unreachable"][1]);
    expect(down[1]?.unreachable).toBeNull();
    expect(down[2]?.unreachable).toBeNull();
    const noTime = healthWith("parquet_store", {
      name: "parquet_store",
      state: "down",
      last_good_at: null,
    });
    expect(tierViews(REPORT, noTime, facts(), pressure)[1]?.unreachable).toBe(
      "Parquet/DuckDB unreachable",
    );
  });

  const healthRow = (views: readonly { readonly rows: readonly TierRow[] }[], tier: number) =>
    views[tier]?.rows.find((r) => r.label === "Health");

  it("test_a_backlog_warning_reads_warning_on_the_questdb_card_c04", () => {
    // D04 `SCR-142/lag-warning`: the QuestDB card's word "warning" with its glyph; the other cards as served.
    const lagging = tierViews(REPORT, HEALTH, facts(), pressure, { lagging: true });
    expect(healthRow(lagging, 0)).toEqual({ label: "Health", value: "warning", icon: "warning" });
    expect(healthRow(lagging, 1)).toEqual({ label: "Health", value: "healthy", icon: "success" });
    expect(lagging[0]?.health).toMatchObject({ word: "healthy", down: false });
    // The backlog never hides a worse served word: a down QuestDB stays down, with its error.
    const down = tierViews(REPORT, QUESTDB_DOWN, facts(), pressure, { lagging: true });
    expect(healthRow(down, 0)).toEqual({ label: "Health", value: "down", icon: "error" });
    expect(down[0]?.unreachable).toBe(STORAGE_DECK["storage.tier.unreachable"][1]);
  });

  it("test_a_failed_health_read_tags_the_last_health_stale_c07", () => {
    const stale = tierViews(REPORT, HEALTH, facts(), pressure, { healthStale: true });
    for (const tier of [0, 1, 2]) {
      expect(healthRow(stale, tier)).toEqual({
        label: "Health",
        value: "healthy",
        icon: "success",
        stale: true,
      });
    }
    // No report yet: "not reported" is no figure to tag.
    expect(healthRow(tierViews(REPORT, null, facts(), pressure, { healthStale: true }), 0)).toEqual(
      { label: "Health", value: "not reported" },
    );
  });

  it("test_the_ingestion_numbers_of_a_stale_topic_are_tagged_stale_c08", () => {
    const stale = tierViews(REPORT, HEALTH, facts(), pressure, { pressureStale: true });
    expect(stale[0]?.rows.find((r) => r.label === "Ingestion")).toEqual({
      label: "Ingestion",
      value: "Ingest 18,400 msg/s, backlog 0 rows, lag —",
      stale: true,
    });
    expect(rows(0)["Ingestion"]).toEqual(["Ingest 18,400 msg/s, backlog 0 rows, lag —", undefined]);
  });

  it("test_a_tier_the_report_lacks_reads_no_size", () => {
    const partial = { ...REPORT, tiers: REPORT.tiers?.filter((t) => t.tier !== "postgres") ?? [] };
    expect(tierViews(partial, HEALTH, facts(partial), pressure)[2]?.rows[0]).toEqual({
      label: "Size",
      value: null,
    });
  });
});

describe("the per-symbol table (D04 §4 `TIER/per-symbol`; D04-CG3)", () => {
  it("test_symbol_rows_carry_size_growth_share_and_pin", () => {
    expect(symbolRows(REPORT)).toEqual([
      { symbol: "BTCUSDT", size: "812.3 GB", growth: "780 MB/day", share: "40.6 %", pinned: true },
      { symbol: "ETHUSDT", size: "1.2 GB", growth: "520 MB/day", share: "0.1 %", pinned: false },
    ]);
  });

  it("test_attribution_line_states_how_much_the_symbols_account_for", () => {
    expect(attributionLine(REPORT)).toBe(STORAGE_DECK["storage.symbols.attributed"][1]);
    expect(attributionLine({ ...REPORT, symbols: [] })).toBeNull();
    expect(attributionLine(null)).toBeNull();
  });

  it.each([
    [1450000000, "1.45 GB/day"],
    [780000000, "780 MB/day"],
    [0, "0 MB/day"],
    [999_490_000, "999 MB/day"],
    // C-486P3-14: a rate that rounds to 1,000 MB reads in GB, as the sizes do (A-5309-10).
    [999_500_000, "1.00 GB/day"],
    [999_990_000, "1.00 GB/day"],
  ])("test_rate_%d_reads_%s", (bytes, text) => {
    expect(formatRate(bytes)).toBe(text);
  });
});

describe("the ingestion backlog (D04 §5 `SCR-142/lag-warning`; D04-Q4, D04-D8)", () => {
  it("test_ingestion_line_is_the_two_produced_numbers_and_a_dash_for_lag", () => {
    expect(ingestionLine(18400, 25000)).toBe(
      STORAGE_DECK["storage.ingestion"][0].replace("{rate}", "18,400").replace("{rows}", "25,000"),
    );
    expect(ingestionLine(18400, 25000)).toBe("Ingest 18,400 msg/s, backlog 25,000 rows, lag —");
  });

  it("test_backlog_warns_at_five_ilp_batches", () => {
    expect(LAG_WARN_ROWS).toBe(25_000);
    expect([isBacklogged(24_999), isBacklogged(25_000), isBacklogged(null)]).toEqual([
      false,
      true,
      false,
    ]);
    expect(lagBannerOf(25000)).toBe(STORAGE_DECK["storage.lag.banner"][1]);
  });

  it("test_the_threshold_beside_the_banner_is_the_warning_rule_c04", () => {
    // D04 `SCR-142/lag-warning`: "the threshold stated beside the banner, 5 batches" (PROPOSED, D04-G4, D04-Q4).
    expect(lagThresholdLine()).toBe("Threshold: 5 batches of 5,000 rows for two samples");
  });
});
