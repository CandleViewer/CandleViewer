/**
 * SCR-141's words (E16-S03; E16-D03 §2, §5–§9, §14): the model's deck keys and parameters
 * (`retentionModel.ts`) and the estimate's figures (`retentionEstimate.ts`) rendered as the deck's
 * sentences (`retentionCopy.ts`). Pure: no React, no clock, no fetch. A sentence is a deck row
 * filled at its tokens; where the deck holds a fixture and no template, or a frame's words, the
 * row below names its source. Nothing here reads a server `message` or `detail` (E16-D06 §20.3).
 */
import { formatRbacReason } from "@candleviewer/ui";
import { fill } from "../copy";
import { fixed } from "../model/format";
import { PAGE_TEXT } from "../pageCopy";
import type { RefusalRoute } from "../recorderApi";
import { RETENTION_DECK, RETENTION_PROPOSED, STREAM_WORDS } from "./retentionCopy";
import { gigabytes, type Preview, type PreviewRow, type SteadyState } from "./retentionEstimate";
import {
  SEED,
  type BodyCopy,
  type Classification,
  type DaysError,
  type ExemptRow,
  type Line,
  type OfferedAction,
  type ReductionLine,
  type StreamKind,
  type SymbolCode,
  type Timing,
  type TitleCopy,
  type TotalParam,
  type TypedConfirm,
} from "./retentionModel";

const deck = RETENTION_DECK;

/**
 * Words the deck does not key: the frames' column names (D03 §2 anatomy, §5 `SCR-141/preview`,
 * §6), and the PROPOSED sentences (owner E16-D03) for cases its frames leave open.
 */
export const RETENTION_TEXT = {
  /** Region (b)'s column names (D03 §2); the fourth column carries `retention.kept_until` whole. */
  global: ["Stream", deck["retention.field.days"][0], "Action"],
  /** The override grid (D03 §6). */
  grid: ["Symbol", "Stream", deck["retention.field.days"][0], "Action", "Status", "Remove"],
  /** The preview table (D03 §5). */
  preview: ["Symbol", "Stream", "From", "To", "Size"],
  /** PROPOSED (owner E16-D03): the set could not be read; D03 §4 draws only the loading frame. */
  loadFailed: "Retention policy could not be loaded.",
  /**
   * PROPOSED (owner E16-D03; E16-D06 §16.4): the generic T4 for a refused save, as SCR-140's
   * "Not started: the server refused it." and `retention.refused.audit`'s "Not saved: …".
   */
  notSaved: "Not saved: the server refused it.",
  /**
   * PROPOSED (owner E16-D03; E16-D06 §16.4 rows 17, 18): a sweep lost to an API restart (`404
   * job_unknown`); D03 §8 draws no line for it, so this follows `storage.compact.unknown`.
   */
  lost: "Retention run status is no longer available on the server.",
  /**
   * PROPOSED (owner E16-D03; C-2.13): the storage report lists at most 64 symbols, so a reduction
   * can reach a recorded symbol it does not list; the estimate names it rather than size it, as
   * the fallback would ("Nothing recorded before … exists yet"). `{symbols}` as the deck's scope.
   */
  unlisted: "Not in the storage report, so not estimated: {symbols}.",
  /**
   * PROPOSED (owner E16-D03; D06 §20.3 (viii)): the size clause of several symbols that hold nothing
   * before the cut-off, naming them (`{scope}` as the deck's); the deck's ", so the first run
   * deletes nothing." follows only when that holds for every symbol the change reaches.
   */
  nothingFor: "Nothing recorded before {to} exists yet for {scope} (about 0 GB now)",
  /** PROPOSED (owner E16-D03; D03 §5's `{scope}` rule): more than two symbols, the size said once. */
  sizeTotal: "About {size} across {n} symbols goes at the first run.",
  /** PROPOSED (owner E16-D03; D06 §20.3 (viii)): no storage report yet, so how much goes is unknown. */
  noReport: "No storage report yet, so the size is not estimated.",
  /** PROPOSED (owner E16-D03): a per-symbol lengthening's detail in the plain confirm. */
  keeps: "Keeps {symbol} {stream} for {n} days.",
  /** PROPOSED (owner E16-D03; `22` `RetentionSweepResult.skipped_locked`): the sweep swept nothing. */
  sweptNothing: "Nothing was swept: another retention run or a purge held the volume.",
  /** PROPOSED (owner E16-D03; `22` `RetentionSweepResult.failed`): what the sweep left pending. */
  sweepFailed: "Partitions not deleted, still pending: {n}.",
} as const;

/** Sizes as D03 §14's `{size}`: GB with one decimal, whole GB without one ("0 GB", "2,000 GB"). */
export function sizeText(bytes: number): string {
  const gb = gigabytes(bytes);
  return `${fixed(gb, Number.isInteger(gb) ? 0 : 1)} GB`;
}

/** A growth rate as the formula line has it: "520 MB" under 1 GB, else `sizeText`. */
export const rateText = (bytesPerDay: number): string =>
  bytesPerDay < 1e9 ? `${fixed(bytesPerDay / 1e6, 0)} MB` : sizeText(bytesPerDay);

/** `{Stream}`: the deck's display word ("Order-book deltas"). */
const streamName = (stream: StreamKind): string => STREAM_WORDS[stream];

/** `{stream}` inside a sentence: the display word, its first letter lower ("order-book deltas"). */
export function streamWord(stream: StreamKind): string {
  const name = streamName(stream);
  return name.charAt(0).toLowerCase() + name.slice(1);
}

/**
 * `{scope}`: the symbol list when two or fewer, else "{k} symbols" (D03 §5); with no storage report
 * to list them, the PROPOSED words for the symbols a global rule governs (`RETENTION_PROPOSED`).
 */
export function scopeText(scope: readonly SymbolCode[] | null): string {
  if (scope === null) return RETENTION_PROPOSED["retention.scope.unknown"][0];
  if (scope.length > 2) return `${scope.length} symbols`;
  return scope.join(" and ");
}

/** "{n} days", and "1 day". */
const daysText = (n: number): string => (n === 1 ? "1 day" : `${String(n)} days`);

/** "24 months" when the `21` §7 total set the horizon, else its days (D03 §14 `{total}`). */
const totalText = (total: TotalParam): string => (total.seed ? "24 months" : daysText(total.days));

/** A rule's total horizon as `{total}`; null when it has no end (the four kept streams). */
function horizonText(stream: StreamKind, days: number, action: OfferedAction): string | null {
  const seedTotal = SEED[stream].totalDays;
  if (action === "drop") return daysText(days);
  if (seedTotal === null) return null;
  return totalText({ days: Math.max(days, seedTotal), seed: days <= seedTotal });
}

/** `rbac.view_as`, E09-D09's reason (`@candleviewer/ui`'s `RBAC_REASONS`), with its target. */
export const viewAsNotice = (user: string): string => formatRbacReason("rbac.view_as", { user });

// --- The typed confirm ---------------------------------------------------------------------

/** The confirm's title by kind (D03 §5's reduction-kinds table). */
export function titleText(title: TitleCopy): string {
  const [template] = deck[title.key];
  switch (title.key) {
    case "retention.confirm.title":
      return fill(template, {
        "{stream}": streamWord(title.params.stream),
        "{n}": title.params.n,
      });
    case "retention.confirm.title_symbol":
      return fill(template, {
        "{symbol}": title.params.symbol,
        "{stream}": streamWord(title.params.stream),
        "{n}": title.params.n,
      });
    case "retention.remove.title":
      return fill(template, {
        "{symbol}": title.params.symbol,
        "{stream}": streamWord(title.params.stream),
      });
    case "retention.confirm.title_multi":
      return fill(template, { "{k}": title.params.k });
    default:
      return fill(template, {
        "{stream}": streamWord(title.params.stream),
        "{total}": totalText(title.params.total),
      });
  }
}

/** The typed field's label (`retention.confirm.typed`): the value is the typed word (D03-D14). */
export const typedLabel = (word: string): string =>
  fill(deck["retention.confirm.typed"][0], { "{word}": word });

/** Apply's validity reason in the typed confirm (`retention.apply.typed`). */
export const typedReason = (word: string): string =>
  fill(deck["retention.apply.typed"][0], { "{word}": word });

/** The destructive button: its object and its timing (`retention.confirm.ok`, `ok_now`). */
export const confirmLabelText = (timing: Timing): string =>
  timing === "now" ? deck["retention.confirm.ok_now"][0] : deck["retention.confirm.ok"][0];

const [MULTI_LINE, NEXT_RUN, UNDO] = deck["retention.confirm.body_multi"];
const [TRADES_EXTRA] = deck["retention.confirm.trades_extra"];
/** body_now's timing clause, read from its template: the deck has no `_now` form of every body. */
const NOW = ((): string => {
  const [template] = deck["retention.confirm.body_now"];
  const start = "{Stream} for {scope} older than {n} days ".length;
  return template.slice(start, template.indexOf(" {size clause}"));
})();
const SIZE_TOKEN = "{size clause}";
const FIRST_RUN = "the first run";
const THIS_SWEEP = "this sweep";
const [SIZE_ABOUT, SIZE_NOTHING] = deck["retention.confirm.size"];
/** The deck's own conclusion when nothing predates the cut-off: ", so the first run deletes nothing.". */
const DELETES_NOTHING = SIZE_NOTHING.slice(SIZE_NOTHING.indexOf(", so "));

/** `retention.confirm.size` for one symbol of the preview: the deck's clause, as it stands. */
function sizeClause(row: PreviewRow): string {
  return row.nothingBefore
    ? fill(SIZE_NOTHING, { "{to}": row.to ?? "—", "{since}": row.since ?? "—" })
    : fill(SIZE_ABOUT, {
        "{size}": sizeText(row.bytes),
        "{symbol}": row.symbol,
        "{from}": row.since ?? "—",
        "{to}": row.to ?? "—",
      });
}

/**
 * Several symbols with nothing before their cut-off, named in one clause (PROPOSED `nothingFor`):
 * the earliest cut-off holds for each of them; "deletes nothing" only when `whole` (it holds for the
 * whole change).
 */
function nothingClause(rows: readonly PreviewRow[], whole: boolean): string {
  const dates = rows.flatMap((row) => (row.to === null ? [] : [row.to])).sort();
  const lead = fill(RETENTION_TEXT.nothingFor, {
    "{to}": dates[0] ?? "—",
    "{scope}": scopeText(rows.map((row) => row.symbol)),
  });
  return `${lead}${whole ? DELETES_NOTHING : "."}`;
}

/**
 * The size clause (D03 §5; D06 §20.3 (viii): what goes, how much). One symbol in scope takes the
 * deck's clause; two take one clause each, those with nothing before the cut-off folded into one
 * that names them; more than two take the size once. "Deletes nothing" is said only when it holds
 * for every symbol the change reaches and none is unsized. The symbols the storage report does not
 * list are named, never sized; with no report at all (a scope nobody lists) the size is said to be
 * unknown. "This sweep" with Apply now.
 */
function sizeClauses(
  lines: readonly Line[],
  preview: Preview | null,
  now: boolean,
  unlisted: readonly SymbolCode[],
): string {
  const unsized = unlistedText(unlisted);
  const parts: string[] = [];
  if (preview === null) {
    if (lines.some((line) => line.scope === null)) parts.push(RETENTION_TEXT.noReport);
  } else {
    const reached = new Set(lines.flatMap((line) => line.scope ?? []));
    const rows = preview.rows.filter((row) => reached.has(row.symbol));
    const nothing = rows.filter((row) => row.nothingBefore);
    const whole = nothing.length === rows.length && unlisted.length === 0;
    const [only] = rows;
    if (rows.length + unlisted.length === 1 && only !== undefined) parts.push(sizeClause(only));
    else if (rows.length + unlisted.length <= 2) {
      parts.push(...rows.filter((row) => !row.nothingBefore).map(sizeClause));
      if (nothing.length > 0) parts.push(nothingClause(nothing, whole));
    } else if (rows.length > 0) {
      const total = rows.reduce((sum, row) => sum + row.bytes, 0);
      parts.push(
        total === 0
          ? nothingClause(rows, whole)
          : fill(RETENTION_TEXT.sizeTotal, {
              "{size}": sizeText(total),
              ...(rows.length === 1 ? { "{n} symbols": "1 symbol" } : { "{n}": rows.length }),
            }),
      );
    }
  }
  if (unsized !== null) parts.push(unsized);
  const text = parts.join(" ");
  return now ? text.replaceAll(FIRST_RUN, THIS_SWEEP) : text;
}

/** A template with its size clause filled, or removed with its space when there is none. */
const withSize = (template: string, clauses: string): string =>
  clauses === "" ? template.replace(` ${SIZE_TOKEN}`, "") : template.replace(SIZE_TOKEN, clauses);

/** Cuts the undo line (and what follows it) off a filled body: region (e) and the preview's lead. */
const withoutUndo = (text: string): string => {
  const at = text.indexOf(` ${UNDO}`);
  return at < 0 ? text : text.slice(0, at);
};

/** One line's own sentence: its body key filled (the total body takes body_now's clause when now). */
function lineSentence(body: BodyCopy, now: boolean, clauses: string): string {
  const { stream, scope } = body.params;
  const words = { "{Stream}": streamName(stream), "{scope}": scopeText(scope) };
  if (body.key === "retention.confirm.body_total") {
    const [template] = deck[body.key];
    const timed = now ? template.replace(NEXT_RUN, NOW) : template;
    return withSize(fill(timed, { ...words, "{total}": totalText(body.params.total) }), clauses);
  }
  const [template] = deck[body.key];
  return withSize(fill(template, { ...words, "{n}": body.params.n }), clauses);
}

const isCold = (line: ReductionLine): boolean =>
  line.body.key === "retention.confirm.body_cold" ||
  line.body.key === "retention.confirm.body_cold_now";

/**
 * K5 (`retention.confirm.body_multi`): one fragment per roll-off line, the timing clause once; a
 * line without roll-off keeps its own `body_cold` sentence; one size clause per symbol, then the
 * undo line.
 */
function multiSentence(lines: readonly ReductionLine[], now: boolean, clauses: string): string {
  const fragments = lines
    .filter((line) => !isCold(line))
    .map((line) => {
      const older =
        line.body.key === "retention.confirm.body_total"
          ? MULTI_LINE.replace("{n} days", totalText(line.total))
          : MULTI_LINE;
      return fill(older, {
        "{Stream}": streamName(line.stream),
        "{scope}": scopeText(line.scope),
        "{n}": line.total.days,
      });
    });
  const cold = lines.filter(isCold).map((line) => withoutUndo(lineSentence(line.body, now, "")));
  const parts = [
    ...(fragments.length === 0 ? [] : [`${fragments.join("; ")} ${now ? NOW : NEXT_RUN}`]),
    ...cold,
    ...(clauses === "" ? [] : [clauses]),
    UNDO,
  ];
  return parts.join(" ");
}

/**
 * The consequence (D03 §5): the removed rule's lead (K4), the body with its timing and size
 * clauses and the undo line, and for trades the bars line. `full` false is region (e)'s and the
 * preview's lead: the same sentence up to the undo line. `unlisted` are the symbols the change
 * reaches that the storage report does not list: named inside the sentence, never sized.
 */
export function consequenceText(
  confirm: TypedConfirm,
  preview: Preview | null,
  full: boolean,
  unlisted: readonly SymbolCode[] = [],
): string {
  const now = confirm.timing === "now";
  const clauses = sizeClauses(confirm.lines, preview, now, unlisted);
  const leads = confirm.lines.flatMap((line) =>
    line.lead === null
      ? []
      : [fill(deck[line.lead.key][0], { "{symbol}": line.lead.params.symbol })],
  );
  const [first] = confirm.lines;
  const body =
    confirm.body.key === "retention.confirm.body_multi" || first === undefined
      ? multiSentence(confirm.lines, now, clauses)
      : lineSentence(confirm.body, now, clauses);
  const text = [...leads, body].join(" ");
  if (!full) return withoutUndo(text);
  return confirm.lines.some((line) => line.stream === "trades") ? `${text} ${TRADES_EXTRA}` : text;
}

/** "{symbol} is pinned and is not affected." for each exempt symbol (D03 §4, §5). */
export const pinnedLines = (exempt: readonly ExemptRow[]): readonly string[] =>
  exempt.map((row) => fill(deck["retention.preview.pinned"][0], { "{symbol}": row.symbol }));

// --- The preview panel ---------------------------------------------------------------------

/** A preview row's cells (`retention.preview.row`, in the frame's column order). */
export interface PreviewCells {
  readonly symbol: string;
  readonly stream: string;
  readonly from: string;
  readonly to: string;
  readonly size: string;
}

const streamsText = (streams: readonly StreamKind[]): string => streams.map(streamName).join(", ");

export function previewCells(row: PreviewRow): PreviewCells {
  const stream = streamsText(row.streams);
  if (row.nothingBefore) {
    const [, , , , empty = ""] = deck["retention.preview.row"][1].split(" · ");
    return {
      symbol: row.symbol,
      stream,
      from: "—",
      to: "—",
      size: fill(empty, { "{since}": row.since ?? "—" }),
    };
  }
  return {
    symbol: row.symbol,
    stream,
    from: row.since ?? "—",
    to: row.to ?? "—",
    size: `about ${sizeText(row.bytes)}`,
  };
}

/** An exempt symbol's row: "BTCUSDT · Trades · — · — · Exempt (pinned)" (D03 §5). */
export const previewExemptCells = (row: ExemptRow): PreviewCells => ({
  symbol: row.symbol,
  stream: streamsText(row.streams),
  from: "—",
  to: "—",
  size: deck["retention.exempt"][0],
});

/** The PROPOSED line for the symbols a reduction reaches that the storage report does not list. */
export const unlistedText = (symbols: readonly SymbolCode[]): string | null =>
  symbols.length === 0 ? null : fill(RETENTION_TEXT.unlisted, { "{symbols}": scopeText(symbols) });

/** `retention.preview.total`: "About 0 GB now across 1 symbol" when nothing predates the cut-off. */
export function previewTotalText(preview: Preview): string {
  const [template] = deck["retention.preview.total"];
  const size = preview.totalBytes === 0 ? "0 GB now" : sizeText(preview.totalBytes);
  const count =
    preview.symbolCount === 1 ? { "{n} symbols": "1 symbol" } : { "{n}": preview.symbolCount };
  return fill(template, { "{size}": size, ...count });
}

// --- Region (e), the plain confirms and the estimate ---------------------------------------

/** The tiering sentence of one line (`retention.confirm.tiering`), its total in words. */
function tieringSentence(line: Line): string {
  const [template] = deck["retention.confirm.tiering"];
  const total = horizonText(line.stream, line.after.days, line.after.action);
  const sentence = total === null ? template.replace("for {total}", "with no end date") : template;
  return fill(sentence, {
    "{stream}": streamWord(line.stream),
    "{n}": line.after.hot,
    "{total}": total ?? "",
  });
}

const TIERING_CLOSE = " This change deletes nothing.";

/**
 * Region (e)'s eligibility lines (D03 §2 (e), §4): nothing eligible, the tiering sentences, or
 * the inline consequence (the symbols it cannot size named inside it) and the pinned lines.
 */
export function eligibilityText(
  classification: Classification,
  preview: Preview | null,
  unlisted: readonly SymbolCode[] = [],
): readonly string[] {
  const [today, longer] = deck["retention.preview.none"];
  switch (classification.kind) {
    case "none":
      return [today];
    case "lengthen":
      return [longer];
    case "tiering":
      return classification.lines.filter((line) => line.effect === "tier").map(tieringSentence);
    default:
      return [
        consequenceText(classification.confirm, preview, false, unlisted),
        ...pinnedLines(classification.exempt),
      ];
  }
}

/** A plain confirm's title and body (D03 §5 `confirm-lengthen`, §6 `row-removed`, §4 tiering). */
export interface PlainConfirm {
  readonly title: string;
  readonly body: string;
}

/**
 * The plain confirm's detail for one line: its tiering sentence, the rule a removal follows, or the
 * symbol a per-symbol lengthening keeps longer (PROPOSED `keeps`).
 */
function plainDetail(line: Line): string | null {
  if (line.effect === "tier") return tieringSentence(line).replace(TIERING_CLOSE, "");
  if (line.cause === "removed" && line.after.action === "archive_parquet") {
    return fill(deck["retention.confirm.removed"][0], {
      "{symbol}": line.symbol,
      "{n}": line.after.days,
    });
  }
  if (line.effect === "lengthen" && line.cause !== "removed" && line.symbol !== null) {
    return fill(RETENTION_TEXT.keeps, {
      "{symbol}": line.symbol,
      "{stream}": streamWord(line.stream),
      "{n}": line.after.days,
    });
  }
  return null;
}

/**
 * The plain CMP-044 (no total horizon shrinks): the lengthening confirm for one edited global line,
 * else "Apply the retention changes?" with each line's detail (a per-symbol lengthening names its
 * symbol there); with Apply now the body says the run that starts still deletes what the current
 * rules make eligible.
 */
export function plainConfirmText(
  classification: Classification,
  steady: SteadyState | null,
  applyNow: boolean,
): PlainConfirm {
  const lines =
    classification.kind === "lengthen" || classification.kind === "tiering"
      ? classification.lines
      : [];
  const [only] = lines;
  if (classification.kind === "lengthen" && lines.length === 1 && only !== undefined) {
    if (only.cause === "edited" && only.symbol === null && steady !== null) {
      const [title] = deck["retention.confirm.lengthen.title"];
      const [unticked, , ticked] = deck["retention.confirm.lengthen.body"];
      return {
        title: fill(title, { "{stream}": streamWord(only.stream), "{n}": only.after.days }),
        body: fill(applyNow ? ticked : unticked, { "{size}": sizeText(steady.bytes) }),
      };
    }
  }
  const details = lines.flatMap((line) => {
    const detail = plainDetail(line);
    return detail === null ? [] : [detail];
  });
  const [template] = applyNow
    ? deck["retention.confirm.plain.body_now"]
    : deck["retention.confirm.plain.body"];
  const body =
    details.length === 0
      ? template.replace(" {detail}", "")
      : fill(template, { "{detail}": details.join(" ") });
  return { title: deck["retention.confirm.plain.title"][0], body };
}

/** `retention.estimate`; without a cap the share is left out (D03 §9). */
export function estimateText(steady: SteadyState): string {
  const [template] = deck["retention.estimate"];
  if (steady.capBytes === null || steady.pct === null) {
    return fill(template.replace(" ({pct} % of {cap})", ""), { "{size}": sizeText(steady.bytes) });
  }
  return fill(template, {
    "{size}": sizeText(steady.bytes),
    "{pct}": steady.pct,
    "{cap}": sizeText(steady.capBytes),
  });
}

/**
 * `retention.estimate.formula`: the deck holds the fixture only, so this template is the
 * fixture's four figures as tokens (a test renders the fixture back from the `22` example).
 */
const FORMULA =
  "Non-pinned growth {growth}/day × the longest window {n} days ≈ {size}. Pinned symbols are never deleted by retention: about {pinned}/day today. Parquet keeps archived streams until their horizon; a per-stream figure needs the storage report to split by stream.";

export const formulaText = (steady: SteadyState): string =>
  fill(FORMULA, {
    "{growth}": rateText(steady.growthPerDay),
    "{n}": steady.windowDays,
    "{size}": sizeText(steady.bytes),
    "{pinned}": rateText(steady.pinnedGrowthPerDay),
  });

// --- The rows -----------------------------------------------------------------------------

/** `retention.kept_until`: the total horizon, or "with no end date" (D03 §2 (b)). */
export function keptUntilText(stream: StreamKind, days: number, action: OfferedAction): string {
  const [until, forever] = deck["retention.kept_until"];
  const total = horizonText(stream, days, action);
  return total === null ? forever : fill(until, { "{total}": total });
}

/**
 * The field help, switching on the action (D03-D3): `retention.help.archive` with its total
 * (its first sentence alone when the total has no end), `help.drop`, or `help.drop_cold` on the
 * four streams without roll-off (D03-C9).
 */
export function helpText(stream: StreamKind, days: number, action: OfferedAction): string {
  if (action === "drop") {
    return SEED[stream].rollsOff
      ? deck["retention.help.drop"][0]
      : deck["retention.help.drop_cold"][0];
  }
  const [template] = deck["retention.help.archive"];
  const total = horizonText(stream, days, action);
  return total === null
    ? template.slice(0, template.indexOf(" Parquet keeps"))
    : fill(template, { "{total}": total });
}

/** `retention.help.derived`: the derived-stream rule stated in advance on the trades row (D03 §7). */
export const DERIVED_HELP = deck["retention.help.derived"][0];

/** `retention.no_source`: a Delete-after row on a stream kept with no end date (D03 §2 (b)). */
export function noSourceText(stream: StreamKind, action: OfferedAction): string | null {
  if (action !== "drop" || SEED[stream].totalDays !== null) return null;
  const [other, irreplaceable] = deck["retention.no_source"];
  return stream === "liquidations" ? irreplaceable : other;
}

/** "Default {n} d" (`retention.baseline`): the stream's seed days. */
export const baselineText = (stream: StreamKind): string =>
  fill(deck["retention.baseline"][0], { "{n}": SEED[stream].hotDays });

/** The staged removal's Status (`retention.removed.status`). */
export const removedStatusText = (n: number): string =>
  fill(deck["retention.removed.status"][0], { "{n}": n });

/** Remove names its object (`retention.remove`; E30-D03 N7). */
export const removeLabel = (symbol: SymbolCode, stream: StreamKind): string =>
  fill(deck["retention.remove"][0], { "{symbol}": symbol, "{stream}": streamWord(stream) });

/** The pinned list's growth (D03 §9 `SCR-141/pinned-list`'s frame words; the deck keys none). */
export const growsText = (bytesPerDay: number): string =>
  `grows about ${rateText(bytesPerDay)}/day`;

const FIELD_ERRORS: Readonly<Record<DaysError, string>> = {
  min: deck["retention.err.min"][0],
  max: deck["retention.err.max"][0],
  int: deck["retention.err.int"][0],
};
export const fieldErrorText = (error: DaysError): string => FIELD_ERRORS[error];

/** "{n} fields" says "1 field" (copy.ts's literal-token form). */
const fields = (n: number): Readonly<Record<string, string | number>> =>
  n === 1 ? { "{n} fields": "1 field" } : { "{n}": n };

/** Why Apply has the validity look (D03 §1.3, T2-07): the order the dialog checks them in. */
export type ApplyReason =
  | { readonly kind: "invalid"; readonly n: number }
  | { readonly kind: "empty" }
  | { readonly kind: "preview" };

export function applyReasonText(reason: ApplyReason): string {
  if (reason.kind === "invalid") return fill(deck["retention.apply.invalid"][0], fields(reason.n));
  return reason.kind === "empty"
    ? deck["retention.apply.no_changes"][0]
    : deck["retention.apply.preview_first"][0];
}

/** The error summary's heading (`retention.err.summary`). */
export const summaryTitle = (n: number): string =>
  fill(deck["retention.err.summary"][0], fields(n));

/** One summary link (D03 §7 `SCR-141/error-summary`): "{row} · Retention (days): {message}". */
export const summaryLinkText = (row: string, message: string): string =>
  `${row} · ${deck["retention.field.days"][0]}: ${message}`;

// --- The job footer and refusals ----------------------------------------------------------

/** The footer's state (D03 §8): at rest, or this client's sweep by `Job.status`. */
export type JobState =
  | { readonly kind: "rest" }
  | { readonly kind: "queued" }
  | { readonly kind: "running"; readonly pct: number }
  | {
      readonly kind: "succeeded";
      readonly freedBytes: number | null;
      /** `skipped_locked`: another pass or a purge held the volume, so nothing was swept. */
      readonly locked?: boolean;
      /** `failed`: partitions whose delete failed; each stays pending. */
      readonly failed?: number;
    }
  | { readonly kind: "failed"; readonly code: string }
  | { readonly kind: "cancelled" }
  /** This client's sweep is no longer known to the server (its poll answered `404`). */
  | { readonly kind: "lost"; readonly code: string | null };

/**
 * The footer's words: one line, or two — the failure and what to check (D03 §8), a sweep that swept
 * nothing, or the partitions it left pending (PROPOSED); "about {size} freed" only when a pass ran.
 */
export function jobText(state: JobState): readonly string[] {
  switch (state.kind) {
    case "rest":
      return [deck["retention.next_run"][0]];
    case "queued":
      return [deck["retention.job.queued"][0]];
    case "running":
      return [fill(deck["retention.job.running"][0], { "{pct}": Math.round(state.pct) })];
    case "succeeded": {
      const [plain, freed] = deck["retention.job.succeeded"];
      if (state.locked === true) return [plain, RETENTION_TEXT.sweptNothing];
      const line =
        state.freedBytes === null ? plain : fill(freed, { "{size}": sizeText(state.freedBytes) });
      const failed = state.failed ?? 0;
      return failed > 0 ? [line, fill(RETENTION_TEXT.sweepFailed, { "{n}": failed })] : [line];
    }
    case "failed": {
      const [line, check] = deck["retention.job.failed"];
      return [fill(line, { "{code}": state.code }), check];
    }
    case "lost":
      return [state.code === null ? RETENTION_TEXT.lost : `${RETENTION_TEXT.lost} (${state.code})`];
    default:
      return [deck["retention.job.cancelled"][0]];
  }
}

/**
 * A refused save's words (D03 §7, §8; E16-D06 §16.4): the deck's sentence as D03 draws it; a code
 * with no sentence is the generic T4 with its code token; no answer is the app's words. The
 * derived-stream rule is the only `retention_invalid_policy` this form can cause (no rule token
 * comes back), so the first sentence of `retention.refused.invalid` is the one shown.
 */
export function refusalSentence(route: RefusalRoute): string {
  if (route.kind === "deck" && Object.hasOwn(deck, route.key)) {
    return deck[route.key as keyof typeof deck][0];
  }
  if (route.kind === "t4" && route.status === 0) return PAGE_TEXT.unreachable;
  const code = route.kind === "t4" ? route.code : route.kind === "step_up" ? null : route.code;
  return code === null ? RETENTION_TEXT.notSaved : `${RETENTION_TEXT.notSaved} (${code})`;
}
