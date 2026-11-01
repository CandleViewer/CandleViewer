/**
 * A purge this client started, on SCR-140 (E16-D02 §3, §3.2, §6.5; E16-D06 RG-11, SR-09 to SR-12, BG-02, BG-05;
 * F-08; G-02; §16.4 row 10; #5309's lens D-5309-11): its running line with a CMP-023 bar named "Purge of {symbol}",
 * in the banner slot or, while level 3 or an incident holds the slot, the disk card; a poll the server refused shows
 * its T4 under the line; then the outcome. Failed is CMP-028 danger with "Open {symbol}"; cancelled and unknown are
 * info; succeeded is the card's line. Nothing drawn here speaks (`live="off"`): `usePurge` says each line once
 * through the shell's announcer, whose regions stay live under the row detail's modal drawer (A-5347-04), so a line
 * that moves between the banner and the card is never said again (BG-05).
 */
import type { JSX } from "react";
import { Callout, InlineError, ProgressBar, Text } from "@candleviewer/ui";
import { DECK, TEXT, fill } from "./copy";
import { PURGE_TEXT } from "./detailCopy";
import { sizeText } from "./estimate";
import { formatDate } from "./model";
import { PAGE_TEXT } from "./pageCopy";
import type { Job } from "./recorderApi";

export type PurgeViewState =
  | {
      readonly phase: "running";
      readonly symbol: string;
      readonly beforeMs: number;
      readonly pct: number;
      /** §16.4 row 10: the last poll was refused, its T4 with the code token; the next answer clears it. */
      readonly pollRefused: string | null;
    }
  | { readonly phase: "failed"; readonly symbol: string; readonly code: string }
  | { readonly phase: "cancelled" | "unknown"; readonly symbol: string }
  | { readonly phase: "succeeded"; readonly symbol: string; readonly freedBytes: number | null };

export interface PurgeResult {
  /** The bytes freed; null when absent. */
  readonly freedBytes: number | null;
  /** The partitions the job could not delete (0 when absent). */
  readonly failed: number;
}

const count = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;

/**
 * A finished purge's `Job.result`, read defensively (the open `result` object, `22` `Job`; its schema is #485/#486's
 * contract commit, BQ-4): `freed_bytes`, and `failed`, the partitions it could not delete, which the purge job serves
 * while the job itself still reads `succeeded` (C-5347-04; a C-row for the contract).
 */
export function purgeResult(job: Job | null): PurgeResult {
  const result: unknown = job?.result;
  const fields = (typeof result === "object" && result !== null ? result : {}) as Readonly<
    Record<string, unknown>
  >;
  return { freedBytes: count(fields["freed_bytes"]), failed: count(fields["failed"]) ?? 0 };
}

/** The state's sentence (D02 §3, §3.2): the running line with its percentage, or the outcome's. */
export function purgeLine(state: PurgeViewState): string {
  const symbol = { "{symbol}": state.symbol };
  switch (state.phase) {
    case "running":
      return fill(TEXT.purgeRunning, {
        ...symbol,
        "{date}": formatDate(state.beforeMs),
        "{pct}": Math.round(state.pct),
      });
    case "failed":
      return fill(DECK["storage.purge.failed"][0], { ...symbol, "`<code>`": state.code });
    case "cancelled":
      return fill(DECK["storage.purge.cancelled"][0], symbol);
    case "unknown":
      return fill(DECK["storage.purge.unknown"][0], symbol);
    case "succeeded":
      return state.freedBytes === null
        ? fill(PURGE_TEXT.finished, symbol)
        : fill(DECK["storage.purge.succeeded"][0], {
            ...symbol,
            "{size}": sizeText(state.freedBytes),
          });
  }
}

/**
 * What the shell says for the state, once (A-5347-04): the running line at its arrival without its percentage (no
 * start string, G-02; BG-02), a polite outcome (F-08), a failure assertively (BG-05).
 */
export function purgeSpeech(state: PurgeViewState): {
  readonly politeness: "polite" | "assertive";
  readonly text: string;
} {
  if (state.phase === "failed") return { politeness: "assertive", text: purgeLine(state) };
  if (state.phase === "running") {
    return { politeness: "polite", text: purgeLine(state).replace(/: \d+ %/u, "") };
  }
  return { politeness: "polite", text: purgeLine(state) };
}

/** "Recording stopped." and the rest: CMP-028 sets a sentence's first full stop as its title. */
function split(sentence: string): readonly [string, string] {
  const end = sentence.indexOf(". ");
  return end < 0 ? [sentence, ""] : [sentence.slice(0, end + 1), sentence.slice(end + 2)];
}

/** The running line's bar: CMP-023 named "Purge of {symbol}", its value text the percentage (never announced). */
function Bar({ symbol, pct }: { readonly symbol: string; readonly pct: number }): JSX.Element {
  const value = Math.round(pct);
  return (
    <ProgressBar
      label={fill(PAGE_TEXT.purgeBar, { "{symbol}": symbol })}
      value={value}
      valueText={`${value} %`}
    />
  );
}

/** The running line's bar and, while a poll is refused, its T4 (§16.4 row 10). */
function Running({ state }: { readonly state: PurgeViewState }): JSX.Element | null {
  if (state.phase !== "running") return null;
  return (
    <>
      <Bar symbol={state.symbol} pct={state.pct} />
      {state.pollRefused === null ? null : <InlineError message={state.pollRefused} live="off" />}
    </>
  );
}

export interface PurgeViewProps {
  readonly state: PurgeViewState;
  /** The banner slot, or the disk card while level 3 or an incident holds the slot (D02 §3). */
  readonly placement: "banner" | "card";
  /** "Open {symbol}": the failed purge's action, the symbol's row detail (D02 §3.2). */
  readonly onOpen: (symbol: string) => void;
}

export function PurgeView({ state, placement, onOpen }: PurgeViewProps): JSX.Element | null {
  const line = purgeLine(state);
  if (state.phase === "failed") {
    const [title, body] = split(line);
    return (
      <Callout
        tone="danger"
        live="off"
        title={title}
        actions={[
          {
            label: fill(TEXT.openSymbol, { "{symbol}": state.symbol }),
            onClick: () => onOpen(state.symbol),
          },
        ]}
      >
        {body}
      </Callout>
    );
  }
  if (state.phase === "succeeded") {
    return placement === "card" ? <Text tone="secondary">{line}</Text> : null;
  }
  if (placement === "card") {
    return (
      <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
        <Text tone="secondary">{line}</Text>
        <Running state={state} />
      </div>
    );
  }
  const [title, body] = split(line);
  return (
    <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
      <Callout tone="info" live="off" title={title}>
        {body}
      </Callout>
      <Running state={state} />
    </div>
  );
}
