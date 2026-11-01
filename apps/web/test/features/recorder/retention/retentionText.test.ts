/**
 * E16-S03 (#485): SCR-141's words, rendered from the model's keys (E16-D03 §5, §8, §9, §14). Every
 * expected sentence below is the deck's own fixture (`retentionCopy.ts`, held to
 * `E16-D06-copy.json`), rendered from the `22` examples: the text module reproduces D03's frames
 * word for word. Pure: no React, no clock, no fetch.
 */
import { describe, expect, it } from "vitest";
import type { RefusalRoute } from "../../../../src/features/recorder/recorderApi";
import { RETENTION_DECK } from "../../../../src/features/recorder/retention/retentionCopy";
import {
  fallbackPreview,
  steadyState,
  type Preview,
} from "../../../../src/features/recorder/retention/retentionEstimate";
import {
  addOverride,
  classify,
  load,
  setAction,
  setDays,
  stageRemoval,
  symbolsOf,
  type Classification,
  type Draft,
  type OfferedAction,
  type Reduction,
  type RowKey,
  type StorageUsage,
  type StreamKind,
} from "../../../../src/features/recorder/retention/retentionModel";
import {
  RETENTION_TEXT,
  applyReasonText,
  baselineText,
  confirmLabelText,
  consequenceText,
  eligibilityText,
  estimateText,
  fieldErrorText,
  formulaText,
  growsText,
  helpText,
  jobText,
  keptUntilText,
  noSourceText,
  pinnedLines,
  plainConfirmText,
  previewCells,
  previewExemptCells,
  previewTotalText,
  refusalSentence,
  removeLabel,
  removedStatusText,
  scopeText,
  sizeText,
  rateText,
  streamWord,
  summaryLinkText,
  summaryTitle,
  titleText,
  typedLabel,
  typedReason,
  unlistedText,
  viewAsNotice,
} from "../../../../src/features/recorder/retention/retentionText";
import { POLICIES_DEFAULTS, STORAGE_USAGE, policy } from "./fixtures";

type Step = (draft: Draft) => Draft;
const G = (stream: StreamKind): RowKey => ({ symbol: null, stream });
const O = (symbol: string, stream: StreamKind): RowKey => ({ symbol, stream });
const edit = (draft: Draft, ...steps: Step[]): Draft => steps.reduce((d, step) => step(d), draft);
const days =
  (key: RowKey, n: number): Step =>
  (d) =>
    setDays(d, key, n);
const act =
  (key: RowKey, action: OfferedAction): Step =>
  (d) =>
    setAction(d, key, action);

const BASE = load(POLICIES_DEFAULTS.items);
const K1 = edit(BASE, act(G("trades"), "drop"), days(G("trades"), 7));
const classifyOn = (draft: Draft, applyNow = false, storage: StorageUsage = STORAGE_USAGE) =>
  classify(draft, { ...symbolsOf(storage), applyNow });
const reductionOf = (
  draft: Draft,
  applyNow = false,
  storage: StorageUsage = STORAGE_USAGE,
): Reduction => {
  const result = classifyOn(draft, applyNow, storage);
  if (result.kind !== "reduction") throw new Error(`expected a reduction, got ${result.kind}`);
  return result;
};
/** The confirm's paragraph and the inline one, on the fallback preview of the same report. */
const said = (draft: Draft, applyNow = false, storage: StorageUsage = STORAGE_USAGE) => {
  const reduction = reductionOf(draft, applyNow, storage);
  const preview = fallbackPreview(storage, draft, reduction);
  return {
    title: titleText(reduction.confirm.title),
    full: consequenceText(reduction.confirm, preview, true),
    inline: consequenceText(reduction.confirm, preview, false),
    word: reduction.confirm.word,
  };
};

const [BODY_TEMPLATE, BODY_FIXTURE] = RETENTION_DECK["retention.confirm.body"];
const [, BODY_NOW_FIXTURE] = RETENTION_DECK["retention.confirm.body_now"];
const [, BODY_TOTAL_FIXTURE] = RETENTION_DECK["retention.confirm.body_total"];
const [TRADES_EXTRA] = RETENTION_DECK["retention.confirm.trades_extra"];
const [, , UNDO] = RETENTION_DECK["retention.confirm.body_multi"];
const NEXT = RETENTION_DECK["retention.confirm.body_multi"][1];
/** The worked case's size clause: ETHUSDT holds about 2.3 days, all after the cut-off. */
const NOTHING_BEFORE =
  "Nothing recorded before 2026-09-07 exists yet (about 0 GB now; recording started about 2026-09-12), so the first run deletes nothing.";
/** Synthetic, not market data: SOLUSDT holds exactly 10 days at 1 GB a day on 2026-09-14 00:00 UTC. */
const SOL: StorageUsage = {
  generated_at: "2026-09-14T00:00:00.000Z",
  cap_bytes: 2_000_000_000_000,
  symbols: [
    {
      symbol: "SOLUSDT",
      used_bytes: 10_000_000_000,
      daily_growth_bytes: 1_000_000_000,
      pinned: false,
    },
  ],
};
/** Synthetic usage rows on SOL's clock: ADAUSDT and ETHUSDT hold nothing before a 7-day cut-off. */
const usage = (symbol: string, gb: number, perDay: number) => ({
  symbol,
  used_bytes: gb * 1e9,
  daily_growth_bytes: perDay * 1e9,
  pinned: false,
});
const MIXED = (...rows: ReturnType<typeof usage>[]): StorageUsage => ({ ...SOL, symbols: rows });
const ETH = usage("ETHUSDT", 1.2, 0.52);
const ADA = usage("ADAUSDT", 1, 1);
const SOL_10 = usage("SOLUSDT", 10, 1);
const XRP_20 = usage("XRPUSDT", 20, 1);
const LEAD_K1 =
  "older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included.";
const NOW_K1 =
  "older than 7 days are deleted when you apply: a retention sweep starts now, and every daily run repeats it, Parquet included.";
const SOL_3GB =
  "About 3 GB across SOLUSDT's recorded streams, recorded from 2026-09-04 to 2026-09-07, goes at the first run.";

describe("figures and words (D03 §14's variables)", () => {
  it.each([
    [0, "0 GB"],
    [189_800_000_000, "189.8 GB"],
    [812_340_221_100, "812.3 GB"],
    [2_000_000_000_000, "2,000 GB"],
    [1_220_004_410, "1.2 GB"],
  ])("sizeText - %d bytes - %s", (bytes, text) => {
    expect(sizeText(bytes)).toBe(text);
  });

  it.each([
    [520_000_000, "520 MB"],
    [780_000_000, "780 MB"],
    [1_450_000_000, "1.5 GB"],
  ])("rateText - %d bytes a day - %s", (bytes, text) => {
    expect(rateText(bytes)).toBe(text);
  });

  it("streamWord - each kind's display word, its first letter lower in a sentence", () => {
    expect(
      (
        [
          "trades",
          "orderbook_delta",
          "orderbook_snapshot",
          "tickers",
          "klines",
          "liquidations",
          "open_interest",
          "funding",
        ] as const
      ).map(streamWord),
    ).toEqual([
      "trades",
      "order-book deltas",
      "order-book snapshots",
      "tickers",
      "exchange klines",
      "liquidations",
      "open interest",
      "funding rates",
    ]);
  });

  it("scopeText - one or two symbols listed, three or more counted (D03 §5), none known PROPOSED", () => {
    expect(scopeText(["ETHUSDT"])).toBe("ETHUSDT");
    expect(scopeText(["ETHUSDT", "SOLUSDT"])).toBe("ETHUSDT and SOLUSDT");
    expect(scopeText(["ETHUSDT", "SOLUSDT", "XRPUSDT"])).toBe("3 symbols");
    expect(scopeText(null)).toBe("every unpinned symbol without its own rule");
  });

  it("viewAsNotice - E09-D09's reason with the view-as target", () => {
    expect(viewAsNotice("alex")).toBe("Read-only while viewing as alex.");
  });
});

describe("the reduction kinds' titles and typed words (D03 §5)", () => {
  const K2 = edit(
    load([policy("trades", 7, "drop"), ...POLICIES_DEFAULTS.items.slice(1)]),
    days(G("trades"), 3),
  );
  const K3 = edit(
    BASE,
    (d) => addOverride(d, "ETHUSDT", "trades"),
    act(O("ETHUSDT", "trades"), "drop"),
    days(O("ETHUSDT", "trades"), 14),
  );
  const K4 = edit(
    load([policy("trades", 7, "drop"), policy("trades", 14, "archive_parquet", "ETHUSDT")]),
    (d) => stageRemoval(d, O("ETHUSDT", "trades")),
  );
  const K5 = edit(
    load([
      policy("trades", 30, "archive_parquet"),
      policy("orderbook_delta", 7, "archive_parquet"),
    ]),
    act(G("trades"), "drop"),
    days(G("trades"), 7),
    act(G("orderbook_delta"), "drop"),
  );
  const K6 = edit(
    load([policy("trades", 1000, "drop")]),
    act(G("trades"), "archive_parquet"),
    days(G("trades"), 30),
  );
  const K6_800 = edit(
    load([policy("trades", 1000, "drop")]),
    act(G("trades"), "archive_parquet"),
    days(G("trades"), 800),
  );
  const K7 = edit(load([policy("trades", 1000, "archive_parquet")]), days(G("trades"), 30));

  it.each([
    ["K1", K1, "Delete trades after 7 days?", "trades"],
    ["K2", K2, "Delete trades after 3 days?", "trades"],
    ["K3", K3, "Delete ETHUSDT trades after 14 days?", "ETHUSDT"],
    ["K4", K4, "Remove the ETHUSDT trades rule?", "ETHUSDT"],
    ["K5", K5, "Shorten retention for 2 streams?", "all streams"],
    ["K6", K6, "Move trades to Parquet and shorten retention to 24 months?", "trades"],
    ["K6 at 800 d", K6_800, "Move trades to Parquet and shorten retention to 800 days?", "trades"],
    ["K7", K7, "Shorten trades retention to 24 months?", "trades"],
  ])("titleText - %s - %s, typed %s", (_kind, draft, title, word) => {
    const { title: shown, word: typed } = said(draft);
    expect(shown).toBe(title);
    expect(typed).toBe(word);
  });

  it("typedLabel and typedReason - the field's label and Apply's validity reason (D03-D14)", () => {
    expect(typedLabel("trades")).toBe("Type trades to confirm");
    expect(typedReason("trades")).toBe("Type trades to confirm.");
    expect(typedLabel("all streams")).toBe("Type all streams to confirm");
  });

  it("confirmLabelText - the destructive button names its object and its timing", () => {
    expect(confirmLabelText("next_run")).toBe("Apply · delete eligible data at the next run");
    expect(confirmLabelText("now")).toBe("Apply · start the retention run");
  });

  it("K4 - the removed rule's lead, then K1's sentence on the fallback", () => {
    expect(said(K4).full).toBe(
      `ETHUSDT then follows the global rule. ${BODY_FIXTURE} ${TRADES_EXTRA}`,
    );
  });

  it("K5 - one fragment per stream, the timing clause once, one size clause per symbol, the undo line", () => {
    expect(said(K5).full).toBe(
      `Trades for ETHUSDT: older than 7 days; Order-book deltas for ETHUSDT: older than 7 days ${NEXT} ${NOTHING_BEFORE} ${UNDO} ${TRADES_EXTRA}`,
    );
  });

  it("K7 - the total horizon in words, as the deck's body_total fixture", () => {
    expect(said(K7).full).toBe(`${BODY_TOTAL_FIXTURE} ${TRADES_EXTRA}`);
  });
});

describe("the consequence sentence (D03 §4 editing-dirty-reduce, §5 confirm-reduce; frozen (viii))", () => {
  it("the worked K1 - the confirm's paragraph is the deck's body fixture, then the trades line", () => {
    expect(said(K1).full).toBe(`${BODY_FIXTURE} ${TRADES_EXTRA}`);
  });

  it("the worked K1 - region (e) and the preview's lead stop before the undo line", () => {
    expect(said(K1).inline).toBe(
      "Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. " +
        NOTHING_BEFORE,
    );
  });

  it("the worked K1 with Apply now - the deck's body_now fixture: 'this sweep deletes nothing'", () => {
    expect(said(K1, true).full).toBe(`${BODY_NOW_FIXTURE} ${TRADES_EXTRA}`);
  });

  it("a symbol with data before the cut-off - about {size}, its recorded range and the first run", () => {
    expect(said(K1, false, SOL).full).toBe(
      "Trades for SOLUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. About 3 GB across SOLUSDT's recorded streams, recorded from 2026-09-04 to 2026-09-07, goes at the first run. " +
        `${UNDO} ${TRADES_EXTRA}`,
    );
    expect(said(K1, true, SOL).full).toContain(
      "About 3 GB across SOLUSDT's recorded streams, recorded from 2026-09-04 to 2026-09-07, goes at this sweep.",
    );
  });

  it("a stream without roll-off - the cold body: the Parquet copy goes, the fast store keeps its rows", () => {
    const snapshots = edit(
      BASE,
      act(G("orderbook_snapshot"), "drop"),
      days(G("orderbook_snapshot"), 7),
    );
    expect(said(snapshots).full).toBe(
      `Order-book snapshots for ETHUSDT: the Parquet copy older than 7 days becomes eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it; the fast store keeps its rows. ${NOTHING_BEFORE} ${UNDO}`,
    );
  });

  it("a total kind with Apply now - body_total's timing clause swapped for body_now's", () => {
    const k7 = edit(load([policy("trades", 1000, "archive_parquet")]), days(G("trades"), 30));
    expect(said(k7, true).full).toBe(
      "Trades for ETHUSDT older than 24 months are deleted when you apply: a retention sweep starts now, and every daily run repeats it, Parquet included. Nothing recorded before 2024-09-14 exists yet (about 0 GB now; recording started about 2026-09-12), so this sweep deletes nothing. " +
        `${UNDO} ${TRADES_EXTRA}`,
    );
  });

  it("without a preview - the sentence keeps its timing and undo line, with no size clause", () => {
    const reduction = reductionOf(K1);
    expect(consequenceText(reduction.confirm, null, true)).toBe(
      `Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. ${UNDO} ${TRADES_EXTRA}`,
    );
  });

  it("every body template says what, how much and that it cannot be undone (frozen (viii))", () => {
    expect(BODY_TEMPLATE).toContain("{size clause}");
    for (const draft of [K1, edit(load([policy("trades", 1000, "drop")]), days(G("trades"), 7))]) {
      const { full } = said(draft);
      expect(full).toMatch(/^Trades for ETHUSDT older than/);
      expect(full).toContain("about 0 GB now");
      expect(full).toContain("It cannot be undone.");
    }
  });

  it("no storage report: a shrinking global rule still reads as a reduction, over the unknown scope, its size unknown", () => {
    const result = classify(K1, { ...symbolsOf(null), applyNow: false });
    if (result.kind !== "reduction") throw new Error(`expected a reduction, got ${result.kind}`);
    expect(consequenceText(result.confirm, null, true)).toBe(
      `Trades for every unpinned symbol without its own rule older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. No storage report yet, so the size is not estimated. ${UNDO} ${TRADES_EXTRA}`,
    );
  });

  it("pinnedLines - each exempt symbol, once (D03 §4, §5)", () => {
    expect(pinnedLines(reductionOf(K1).exempt)).toEqual(["BTCUSDT is pinned and is not affected."]);
  });
});

describe("the size clause over several symbols (C-5353-01; D06 §20.3 (viii))", () => {
  /** The confirm's paragraph over `storage`, the editor's unsized symbols dropped from its rows. */
  const over = (draft: Draft, storage: StorageUsage, applyNow = false, unlisted: string[] = []) => {
    const symbols = [...(storage.symbols ?? []).map((s) => s.symbol ?? ""), ...unlisted];
    const result = classify(draft, { symbols, pinned: [], applyNow });
    if (result.kind !== "reduction") throw new Error(`expected a reduction, got ${result.kind}`);
    const preview = fallbackPreview(storage, draft, result);
    const listed = { ...preview, rows: preview.rows.filter((r) => !unlisted.includes(r.symbol)) };
    return consequenceText(result.confirm, listed, true, unlisted);
  };
  const END = `${UNDO} ${TRADES_EXTRA}`;

  it("nothing + sized: each clause names its symbol; 'deletes nothing' is never said", () => {
    const text = over(K1, MIXED(ETH, SOL_10));
    expect(text).toBe(
      `Trades for ETHUSDT and SOLUSDT ${LEAD_K1} ${SOL_3GB} Nothing recorded before 2026-09-07 exists yet for ETHUSDT (about 0 GB now). ${END}`,
    );
    expect(text).not.toContain("deletes nothing");
  });

  it("nothing + sized with Apply now: 'this sweep', and still never 'deletes nothing'", () => {
    const text = over(K1, MIXED(ETH, SOL_10), true);
    expect(text).toBe(
      `Trades for ETHUSDT and SOLUSDT ${NOW_K1} ${SOL_3GB.replace("the first run", "this sweep")} Nothing recorded before 2026-09-07 exists yet for ETHUSDT (about 0 GB now). ${END}`,
    );
    expect(text).not.toContain("deletes nothing");
  });

  it("two with nothing before the cut-off: one clause names both, and then the first run deletes nothing", () => {
    expect(over(K1, MIXED(ADA, ETH))).toBe(
      `Trades for ADAUSDT and ETHUSDT ${LEAD_K1} Nothing recorded before 2026-09-07 exists yet for ADAUSDT and ETHUSDT (about 0 GB now), so the first run deletes nothing. ${END}`,
    );
    expect(over(K1, MIXED(ADA, ETH), true)).toContain(
      "for ADAUSDT and ETHUSDT (about 0 GB now), so this sweep deletes nothing.",
    );
  });

  it("nothing + a symbol the report does not list: named inside the sentence, unsized, no 'deletes nothing'", () => {
    const text = over(K1, MIXED(ETH), false, ["XRPUSDT"]);
    expect(text).toBe(
      `Trades for ETHUSDT and XRPUSDT ${LEAD_K1} Nothing recorded before 2026-09-07 exists yet for ETHUSDT (about 0 GB now). Not in the storage report, so not estimated: XRPUSDT. ${END}`,
    );
  });

  it("more than two symbols: the size said once, never a clause per symbol", () => {
    const text = over(K1, MIXED(ETH, SOL_10, XRP_20));
    expect(text).toBe(
      `Trades for 3 symbols ${LEAD_K1} About 16 GB across 3 symbols goes at the first run. ${END}`,
    );
    expect(over(K1, MIXED(ADA, ETH, usage("XRPUSDT", 2, 1)))).toContain(
      "Nothing recorded before 2026-09-07 exists yet for 3 symbols (about 0 GB now), so the first run deletes nothing.",
    );
    expect(over(K1, MIXED(ETH, SOL_10), false, ["XRPUSDT"])).toContain(
      "About 3 GB across 2 symbols goes at the first run. Not in the storage report, so not estimated: XRPUSDT.",
    );
  });

  it("K6 over two symbols with nothing before the cut-off: one clause, said once", () => {
    const k6 = edit(
      load([policy("trades", 1000, "drop")]),
      act(G("trades"), "archive_parquet"),
      days(G("trades"), 30),
    );
    const text = over(k6, MIXED(ETH, SOL_10));
    expect(text).toBe(
      `Trades for ETHUSDT and SOLUSDT older than 24 months become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. Nothing recorded before 2024-09-14 exists yet for ETHUSDT and SOLUSDT (about 0 GB now), so the first run deletes nothing. ${END}`,
    );
    expect(text.match(/Nothing recorded/g)).toHaveLength(1);
  });

  it("a stream without roll-off over two symbols: the cold body, one clause", () => {
    const cold = edit(BASE, act(G("orderbook_snapshot"), "drop"), days(G("orderbook_snapshot"), 7));
    expect(over(cold, MIXED(ADA, ETH)).match(/Nothing recorded/g)).toHaveLength(1);
  });
});

describe("the preview panel (D03 §5 SCR-141/preview; BQ-3's fallback)", () => {
  const preview = (draft: Draft, storage: StorageUsage = STORAGE_USAGE): Preview =>
    fallbackPreview(storage, draft, reductionOf(draft, false, storage));

  it("the worked K1 - ETHUSDT's row, the exempt row and the total are the deck's fixtures", () => {
    const shown = preview(K1);
    const [row] = shown.rows;
    expect(row === undefined ? "" : Object.values(previewCells(row)).join(" · ")).toBe(
      RETENTION_DECK["retention.preview.row"][2],
    );
    const [exempt] = shown.exempt;
    expect(exempt === undefined ? "" : Object.values(previewExemptCells(exempt)).join(" · ")).toBe(
      "BTCUSDT · Trades · — · — · Exempt (pinned)",
    );
    expect(previewTotalText(shown)).toBe(RETENTION_DECK["retention.preview.total"][1]);
  });

  it("data before the cut-off - its recorded range and about {size}; the total counts symbols", () => {
    const shown = preview(K1, SOL);
    const [row] = shown.rows;
    expect(row === undefined ? null : previewCells(row)).toEqual({
      symbol: "SOLUSDT",
      stream: "Trades",
      from: "2026-09-04",
      to: "2026-09-07",
      size: "about 3 GB",
    });
    expect(previewTotalText(shown)).toBe("About 3 GB across 1 symbol");
    expect(previewTotalText({ ...shown, totalBytes: 4e9, symbolCount: 2 })).toBe(
      "About 4 GB across 2 symbols",
    );
  });

  it("unlistedText - the symbols the report does not list are named, not sized (PROPOSED, C-2.13)", () => {
    expect(unlistedText([])).toBeNull();
    expect(unlistedText(["SOLUSDT", "XRPUSDT"])).toBe(
      "Not in the storage report, so not estimated: SOLUSDT and XRPUSDT.",
    );
    expect(unlistedText(["ADAUSDT", "SOLUSDT", "XRPUSDT"])).toBe(
      "Not in the storage report, so not estimated: 3 symbols.",
    );
  });

  it("the column names are the frame's (D03 §5)", () => {
    expect(RETENTION_TEXT.preview).toEqual(["Symbol", "Stream", "From", "To", "Size"]);
  });
});

describe("region (e) and the plain confirms (D03 §4, §5 confirm-lengthen, §6 row-removed)", () => {
  const steady = (draft: Draft) => steadyState(STORAGE_USAGE, draft);
  const tiering = edit(BASE, days(G("trades"), 7));
  const lengthen = edit(BASE, days(G("trades"), 90));
  const removal = edit(BASE, (d) => stageRemoval(d, O("ETHUSDT", "orderbook_delta")));
  const text = (draft: Draft, applyNow = false) => {
    const result: Classification = classifyOn(draft, applyNow);
    return {
      eligible: eligibilityText(result, null),
      confirm: plainConfirmText(result, steady(draft), applyNow),
    };
  };

  it("editing-clean - nothing becomes eligible", () => {
    expect(text(BASE).eligible).toEqual([
      "Nothing becomes eligible: this policy keeps data as long as today.",
    ]);
  });

  it("editing-dirty-tiering - the tiering sentence; the plain confirm drops its closing sentence", () => {
    const { eligible, confirm } = text(tiering);
    expect(eligible).toEqual([RETENTION_DECK["retention.confirm.tiering"][1]]);
    expect(confirm).toEqual({
      title: "Apply the retention changes?",
      body: "Nothing is deleted. Moves trades older than 7 days to Parquet sooner; it is still kept for 24 months.",
    });
    expect(text(tiering, true).confirm.body).toBe(
      "This change deletes nothing more. The retention run that starts now still deletes what the current rules already make eligible. Moves trades older than 7 days to Parquet sooner; it is still kept for 24 months.",
    );
  });

  it("editing-dirty-lengthen - 'this change keeps data longer'; the lengthening confirm", () => {
    const { eligible, confirm } = text(lengthen);
    expect(eligible).toEqual(["Nothing becomes eligible: this change keeps data longer."]);
    expect(confirm).toEqual({
      title: "Keep trades for 90 days?",
      body: RETENTION_DECK["retention.confirm.lengthen.body"][1],
    });
    expect(text(lengthen, true).confirm.body).toBe(
      "This change deletes nothing more. The retention run that starts now still deletes what the current rules already make eligible. The fast store settles at most about 189.8 GB, plus pinned data.",
    );
  });

  it("row-removed - the plain confirm names the rule the symbol follows", () => {
    expect(text(removal).confirm).toEqual({
      title: "Apply the retention changes?",
      body: "Nothing is deleted. ETHUSDT follows the global rule: 7 days, then Parquet.",
    });
  });

  it("a change only pinned symbols feel - nothing is deleted, the plain confirm with no detail", () => {
    const pinnedOnly = edit(
      BASE,
      (d) => addOverride(d, "BTCUSDT", "trades"),
      act(O("BTCUSDT", "trades"), "drop"),
      days(O("BTCUSDT", "trades"), 3),
    );
    expect(text(pinnedOnly).confirm).toEqual({
      title: "Apply the retention changes?",
      body: "Nothing is deleted.",
    });
  });

  it("editing-dirty-reduce - the inline consequence, then the pinned line", () => {
    const result = classifyOn(K1);
    const reduction = reductionOf(K1);
    const shown = eligibilityText(result, fallbackPreview(STORAGE_USAGE, K1, reduction));
    expect(shown).toEqual([
      `Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. ${NOTHING_BEFORE}`,
      "BTCUSDT is pinned and is not affected.",
    ]);
    expect(eligibilityText(result, null, ["SOLUSDT"])).toEqual([
      "Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. Not in the storage report, so not estimated: SOLUSDT.",
      "BTCUSDT is pinned and is not affected.",
    ]);
  });

  it("a per-symbol lengthening - the generic title, its detail naming the symbol (C-5353-08)", () => {
    const added = edit(
      BASE,
      (d) => addOverride(d, "ETHUSDT", "trades"),
      days(O("ETHUSDT", "trades"), 90),
    );
    expect(text(added).confirm).toEqual({
      title: "Apply the retention changes?",
      body: "Nothing is deleted. Keeps ETHUSDT trades for 90 days.",
    });
    expect(text(added, true).confirm.body).toBe(
      "This change deletes nothing more. The retention run that starts now still deletes what the current rules already make eligible. Keeps ETHUSDT trades for 90 days.",
    );
  });

  it("estimateText and formulaText - the deck's fixtures on the 22 storage example (D03 §9)", () => {
    const estimate = steady(BASE);
    expect(estimateText(estimate)).toBe(RETENTION_DECK["retention.estimate"][1]);
    expect(formulaText(estimate)).toBe(RETENTION_DECK["retention.estimate.formula"][0]);
    expect(estimateText({ ...estimate, capBytes: null, pct: null })).toBe(
      "Under this policy the fast store settles at most about 189.8 GB, plus pinned data.",
    );
  });
});

describe("the rows' words (D03 §2, §6, §7)", () => {
  it.each([
    ["trades", 30, "archive_parquet", "Kept in Parquet until 24 months"],
    ["trades", 800, "archive_parquet", "Kept in Parquet until 800 days"],
    ["klines", 90, "archive_parquet", "Kept in Parquet with no end date"],
    ["trades", 7, "drop", "Kept in Parquet until 7 days"],
    ["trades", 1, "drop", "Kept in Parquet until 1 day"],
  ] as const)("keptUntilText - %s %d d %s - %s", (stream, n, action, text) => {
    expect(keptUntilText(stream, n, action)).toBe(text);
  });

  it.each([
    ["trades", 30, "archive_parquet", RETENTION_DECK["retention.help.archive"][1]],
    ["trades", 7, "drop", RETENTION_DECK["retention.help.drop"][0]],
    ["orderbook_snapshot", 7, "drop", RETENTION_DECK["retention.help.drop_cold"][0]],
    ["klines", 90, "archive_parquet", "Days in the fast store before the nightly move to Parquet."],
  ] as const)("helpText - %s %d d %s", (stream, n, action, text) => {
    expect(helpText(stream, n, action)).toBe(text);
  });

  it("noSourceText - a Delete-after row on a stream with no end date warns; liquidations its own", () => {
    expect(noSourceText("klines", "drop")).toBe("This stream has no other source.");
    expect(noSourceText("funding", "drop")).toBe("This stream has no other source.");
    expect(noSourceText("liquidations", "drop")).toBe(
      "Irreplaceable: there is no history to fetch again.",
    );
    expect(noSourceText("trades", "drop")).toBeNull();
    expect(noSourceText("klines", "archive_parquet")).toBeNull();
  });

  it("the baseline chip, the staged removal and the Remove button name their object", () => {
    expect(baselineText("trades")).toBe("Default 30 d");
    expect(baselineText("funding")).toBe("Default 365 d");
    expect(removedStatusText(7)).toBe("Removed: follows the global rule (7 d)");
    expect(removeLabel("ETHUSDT", "orderbook_delta")).toBe("Remove ETHUSDT order-book deltas rule");
    expect(growsText(780_000_000)).toBe("grows about 780 MB/day");
  });

  it("the field messages, Apply's four reasons and the summary (D03 §7)", () => {
    expect([fieldErrorText("min"), fieldErrorText("max"), fieldErrorText("int")]).toEqual([
      "Keep at least 1 day.",
      "At most 3650 days (10 years).",
      "Whole days only.",
    ]);
    expect(applyReasonText({ kind: "invalid", n: 1 })).toBe("Fix 1 field.");
    expect(applyReasonText({ kind: "invalid", n: 2 })).toBe("Fix 2 fields.");
    expect(applyReasonText({ kind: "empty" })).toBe("No changes to apply.");
    expect(applyReasonText({ kind: "preview" })).toBe("Preview the change first.");
    expect(summaryTitle(2)).toBe("Fix 2 fields before applying.");
    expect(summaryTitle(1)).toBe("Fix 1 field before applying.");
    expect(summaryLinkText("Trades", "Keep at least 1 day.")).toBe(
      "Trades · Retention (days): Keep at least 1 day.",
    );
  });
});

describe("the job footer (D03 §8; BQ-18's five words)", () => {
  it.each([
    [{ kind: "rest" }, ["Next retention run: daily at 03:00 UTC"]],
    [{ kind: "queued" }, ["Retention run queued"]],
    [{ kind: "running", pct: 42 }, ["Retention run running · 42 %"]],
    [{ kind: "running", pct: 41.6 }, ["Retention run running · 42 %"]],
    [{ kind: "succeeded", freedBytes: null }, ["Retention run succeeded"]],
    [
      { kind: "succeeded", freedBytes: 1_200_000_000 },
      ["Retention run succeeded · about 1.2 GB freed"],
    ],
    [
      { kind: "succeeded", freedBytes: 0, locked: true },
      [
        "Retention run succeeded",
        "Nothing was swept: another retention run or a purge held the volume.",
      ],
    ],
    [
      { kind: "succeeded", freedBytes: 1_200_000_000, failed: 2 },
      ["Retention run succeeded · about 1.2 GB freed", "Partitions not deleted, still pending: 2."],
    ],
    [
      { kind: "failed", code: "io_error" },
      [
        "Retention run failed (io_error)",
        "Some data may already be deleted: check the storage report.",
      ],
    ],
    [{ kind: "cancelled" }, ["Retention run cancelled"]],
    [
      { kind: "lost", code: "job_unknown" },
      ["Retention run status is no longer available on the server. (job_unknown)"],
    ],
    [{ kind: "lost", code: null }, ["Retention run status is no longer available on the server."]],
  ] as const)("jobText - %j", (state, lines) => {
    expect(jobText(state)).toEqual(lines);
  });
});

describe("refusals (D03 §7, §8; E16-D06 §16.4): a deck sentence, else the T4 with its code", () => {
  const deck = (
    key: Extract<RefusalRoute, { kind: "deck" }>["key"],
    code: string,
  ): RefusalRoute => ({
    kind: "deck",
    key,
    code,
    serverTime: null,
  });
  it.each([
    [
      deck("retention.refused.invalid", "retention_invalid_policy"),
      "Bars can't be deleted before the ticks they came from are kept — adjust the tiers.",
    ],
    [
      deck("retention.refused.unknown", "validation_failed"),
      "Something in this form is not accepted by the server.",
    ],
    [deck("retention.refused.job_running", "job_running"), "A retention run is already running."],
    [deck("retention.refused.scheduler_off", "conflict"), "Retention runs are off on this server."],
    [
      deck("retention.refused.audit", "audit_unavailable"),
      "Not saved: the audit record could not be written.",
    ],
    [
      { kind: "t4", code: "forbidden", field: null, status: 403 },
      "Not saved: the server refused it. (forbidden)",
    ],
    [{ kind: "t4", code: null, field: null, status: 500 }, "Not saved: the server refused it."],
    [{ kind: "t4", code: null, field: null, status: 0 }, "Cannot reach the server. Try again."],
  ] as const)("refusalSentence - %j", (route, text) => {
    expect(refusalSentence(route)).toBe(text);
  });

  it("never renders a problem's message: the words come from the route alone", () => {
    const route: RefusalRoute = { kind: "t4", code: "rate_limited", field: "items", status: 429 };
    expect(refusalSentence(route)).not.toMatch(/items|message|detail/);
  });
});
