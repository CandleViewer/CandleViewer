/**
 * The visual-regression job's summary (E05-T04): the matrix's cell count, this run's, its diffs by cell key,
 * the cells it could not capture with their reasons, the cells that failed otherwise, the faces Chromium drew
 * for the token families, the stories left out and why. Printed, and appended to the GitHub job summary when
 * there is one.
 */
import { appendFileSync } from "node:fs";
import type { FullConfig } from "playwright/test";
import { DENSITIES, THEMES } from "../src/theme/store.js";
import { readMatrix, readShard, type Matrix } from "./matrix.js";
import { NOT_CAPTURED } from "./page.js";
import { TOLERANCE } from "./settings.js";

/**
 * What the summary reads of Playwright's reporter objects. The reporter API's own types sit behind a
 * types-only export (`playwright/types/testReporter`) that dependency-cruiser cannot resolve, so the few
 * members used are declared here; Playwright passes its full objects.
 */
interface SuiteLike {
  allTests(): readonly unknown[];
}
interface CaseLike {
  readonly title: string;
}
interface ResultLike {
  readonly status: "passed" | "failed" | "timedOut" | "skipped" | "interrupted";
  readonly annotations: readonly { readonly type: string; readonly description?: string }[];
  readonly error?: { readonly message?: string };
}

export interface SummaryOptions {
  /** The built Storybook's index.json: the matrix this run is a part of. */
  readonly index: string;
  /** Where each line goes; stdout and `$GITHUB_STEP_SUMMARY` by default. */
  readonly write?: (line: string) => void;
  /** Where `VR_SHARD` is read; the process's environment by default. */
  readonly env?: Readonly<Record<string, string | undefined>>;
}

/** Names past this many are counted, not listed. */
const LISTED = 50;

/** A failed comparison, as Playwright words it: a screenshot that differs, or no baseline to compare with. */
const COMPARISON = /toHaveScreenshot|A snapshot doesn't exist at/;

const print = (line: string): void => {
  process.stdout.write(`${line}\n`);
  const summary = process.env["GITHUB_STEP_SUMMARY"];
  if (summary) appendFileSync(summary, `${line}\n`);
};

const firstLine = (text: string): string => text.split("\n")[0] ?? text;

/** The first names of a list, then a count of the rest. */
const some = (names: readonly string[]): string =>
  names.slice(0, LISTED).join(", ") +
  (names.length > LISTED ? ` and ${names.length - LISTED} more` : "");

export default class SummaryReporter {
  private readonly index: string;
  private readonly write: (line: string) => void;
  private readonly env: Readonly<Record<string, string | undefined>>;
  private matrix: Matrix | undefined;
  private keys = new Set<string>();
  private shard = "";
  private ran = 0;
  private ownGlobals = 0;
  private fonts = "";
  private readonly diffs: string[] = [];
  /** `key (reason)` of each cell that failed before its capture (a failed play, an unsettled page). */
  private readonly uncaptured: string[] = [];
  /** `key (error)` of each cell that failed outside the comparison (a timeout, an error in a step). */
  private readonly broken: string[] = [];
  private readonly failed: string[] = [];

  constructor(options: SummaryOptions) {
    this.index = options.index;
    this.write = options.write ?? print;
    this.env = options.env ?? process.env;
  }

  printsToStdio(): boolean {
    return true;
  }

  onBegin(config: FullConfig, suite: SuiteLike): void {
    this.matrix = readMatrix(this.index);
    this.keys = new Set(this.matrix.cells.map(({ key }) => key));
    // The vr job's own shard (`VR_SHARD`, matrix.ts), else one Playwright's `--shard` cut.
    const shard = readShard(this.env["VR_SHARD"]) ?? config.shard;
    this.shard = shard ? ` (shard ${shard.current} of ${shard.total})` : "";
    this.ran = suite.allTests().length;
  }

  onTestEnd(test: CaseLike, result: ResultLike): void {
    const note = (type: string): string | undefined =>
      result.annotations.find((annotation) => annotation.type === type)?.description;
    if (note("own-globals") !== undefined) this.ownGlobals += 1;
    this.fonts = note("fonts") ?? this.fonts;
    if (result.status === "passed" || result.status === "skipped") return;
    if (!this.keys.has(test.title)) {
      this.failed.push(test.title);
      return;
    }
    const reason = note(NOT_CAPTURED);
    const error = result.error?.message ?? "";
    if (reason !== undefined) this.uncaptured.push(`${test.title} (${firstLine(reason)})`);
    else if (COMPARISON.test(error)) this.diffs.push(test.title);
    else this.broken.push(`${test.title} (${firstLine(error) || result.status})`);
  }

  onEnd(): void {
    const { cells = [], stories = [], excluded = [] } = this.matrix ?? {};
    const left = excluded.map(({ id, reason }) => `${id} (${reason})`).join(", ") || "none";
    this.write(
      `- VR matrix: ${cells.length} cells (${stories.length} stories x ${THEMES.length} themes x ` +
        `${DENSITIES.length} densities); stories left out: ${left}`,
    );
    this.write(
      `- This run: ${this.ran} tests${this.shard}; cells showing a theme or density their story ` +
        `sets itself: ${this.ownGlobals}`,
    );
    if (this.fonts !== "") this.write(`- Fonts drawn: ${this.fonts}`);
    this.write(
      `- VR diffs: ${this.diffs.length} (a missing baseline, or more pixels changed than ` +
        `${TOLERANCE.maxDiffPixelRatio * 100}% of the capture, at most ${TOLERANCE.maxDiffPixels})` +
        (this.diffs.length > 0 ? `: ${some(this.diffs)}` : ""),
    );
    if (this.uncaptured.length > 0) {
      this.write(
        `- Cells not captured: ${this.uncaptured.length} (a play function failed, Storybook errored, ` +
          `or the page never held still): ${some(this.uncaptured)}`,
      );
    }
    if (this.broken.length > 0) {
      this.write(
        `- Cells that failed otherwise: ${this.broken.length} (a timeout or an error outside the ` +
          `comparison): ${some(this.broken)}`,
      );
    }
    if (this.failed.length > 0) this.write(`- Other failures: ${this.failed.join(", ")}`);
  }
}
