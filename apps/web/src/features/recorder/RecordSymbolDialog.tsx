/**
 * "Record a symbol" (E16-D02 §6.1; E16-D06 KB-05, T2-02, §16.4 rows 2, 4 and 5): CMP-043 with the
 * Symbol combobox over the instrument list, the Streams (the first four by default), Depth (200 by
 * default, with the estimate as its help) and Retention, or Keep forever. First focus is the
 * combobox, where Enter picks an option and never submits. At the symbol cap, Start recording is T2
 * `recorder.symbol_cap` (2a, its reason under it) for a symbol outside the active rows. The add is
 * pessimistic: Start recording is `loading` until the server answers; a pinned or non-default
 * retention add meets the `recorder` step-up, held and re-sent once; a 422 shows under its field; any
 * other refusal shows above the footer, its code in parentheses, polite once.
 */
import { useId, useState, type JSX, type RefObject } from "react";
import {
  Button,
  Checkbox,
  Combobox,
  Dialog,
  FormField,
  InlineError,
  NumericStepperInput,
  RadioGroup,
  Text,
  Toggle,
} from "@candleviewer/ui";
import { reportRecorder } from "./analytics";
import { DECK, TEXT, fill } from "./copy";
import {
  DEFAULT_DEPTH,
  DEFAULT_RETENTION_DAYS,
  DEFAULT_STREAMS,
  DEPTHS,
  RETENTION_MAX_DAYS,
  RETENTION_MIN_DAYS,
  STREAMS,
  type Depth,
  type StreamKind,
} from "./grid";
import { formatDuration, symbolCapReached, t2Reason, type RecorderRow } from "./model";
import type { RecorderPolicy } from "./model/types";
import { STREAM_LABELS } from "./pageCopy";
import {
  recorderApi,
  type AddRecordedSymbolBody,
  type AddedRecordedSymbol,
  type ApiResult,
} from "./recorderApi";
import { refusalText } from "./refusal";
import { useStepUpHost, type StepUpRoute } from "./stepUpHost";

type Field = "symbol" | "streams" | "depth" | "retention_days";
const FIELDS: readonly string[] = ["symbol", "streams", "depth", "retention_days"];
const isField = (name: string | null): name is Field => name !== null && FIELDS.includes(name);

export interface RecordSymbolDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  /** The page's rows: the cap counts the active ones (`symbolCapReached`). */
  readonly rows: readonly RecorderRow[];
  readonly policy: RecorderPolicy | null;
  /** The Combobox's options: the USDT linear perpetuals the instrument index lists. */
  readonly instruments: readonly string[];
  /** The server's row: added (201, with the planning estimate) or already listed (200). */
  readonly onAdded: (row: AddedRecordedSymbol) => void;
  /** Re-reads the list when a step-up's re-send got no answer ("Outcome pending"). */
  readonly readBack: () => unknown;
  /**
   * Where focus returns when the opener is gone (C-5309-03): the empty state's "Record a symbol" leaves with the
   * first add, so the page's header button takes it, never `<body>`.
   */
  readonly fallbackFocusRef?: RefObject<HTMLElement | null>;
}

interface Refusal {
  readonly field: Field | null;
  readonly text: string;
}

export function RecordSymbolDialog({
  open,
  onClose,
  rows,
  policy,
  instruments,
  onAdded,
  readBack,
  fallbackFocusRef,
}: RecordSymbolDialogProps): JSX.Element {
  const id = useId();
  const [symbol, setSymbol] = useState("");
  const [streams, setStreams] = useState<ReadonlySet<StreamKind>>(new Set(DEFAULT_STREAMS));
  const [depth, setDepth] = useState<Depth>(DEFAULT_DEPTH);
  const [retention, setRetention] = useState(DEFAULT_RETENTION_DAYS);
  const [forever, setForever] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const stepUp = useStepUpHost(readBack, TEXT.add.start);

  // Each opening starts from the defaults (§6.1), in the render that opens it: an effect would run after the first
  // frame had drawn, and focus landed on, the last opening's values, which a screen reader reads out.
  const [opened, setOpened] = useState(open);
  if (open !== opened) {
    setOpened(open);
    if (open) {
      setSymbol("");
      setStreams(new Set(DEFAULT_STREAMS));
      setDepth(DEFAULT_DEPTH);
      setRetention(DEFAULT_RETENTION_DAYS);
      setForever(false);
      setBusy(false);
      setRefusal(null);
      stepUp.clear();
    }
  }

  const grace = policy === null ? "" : formatDuration(policy.autostop_grace_s);
  const wanted = symbol.trim().toUpperCase();
  const capped = symbolCapReached(rows, policy?.max_symbols ?? null, wanted);
  const capReason = capped ? t2Reason("recorder.symbol_cap", grace) : undefined;
  const body: AddRecordedSymbolBody = {
    symbol: wanted,
    streams: STREAMS.filter((kind) => streams.has(kind)),
    depth,
    pinned: forever,
    retention_days: forever ? null : retention,
  };

  function answer(res: ApiResult<AddedRecordedSymbol>): void {
    setBusy(false);
    if (res.ok && res.data !== null) {
      reportRecorder({
        name: "recorder.symbol_added",
        symbol: res.data.symbol,
        depth: body.depth,
        streams: body.streams,
        retentionDays: body.retention_days,
        pinned: body.pinned,
      });
      onAdded(res.data);
      onClose();
      return;
    }
    if (res.route === null) return;
    const field = res.route.kind === "t4" && isField(res.route.field) ? res.route.field : null;
    setRefusal({ field, text: refusalText(res.route, "add") });
  }

  async function submit(route: StepUpRoute): Promise<void> {
    setBusy(true);
    setRefusal(null);
    const res = await recorderApi.add(body);
    // A challenge holds the request: the primary is a control again while SCR-006 is open (§6.4).
    if (res.stepUp !== null) setBusy(false);
    route("addRecordedSymbol", res, answer);
  }

  const errorOf = (name: Field): string | undefined =>
    refusal?.field === name ? refusal.text : undefined;
  const retentionError = errorOf("retention_days");
  const streamsError = errorOf("streams");
  const depthError = errorOf("depth");
  const toggle = (kind: StreamKind, on: boolean): void => {
    const next = new Set(streams);
    if (on) next.add(kind);
    else next.delete(kind);
    setStreams(next);
  };
  const start = (
    <span style={{ display: "inline-grid", justifyItems: "end", gap: "var(--space-stack-xs)" }}>
      <Button
        variant="primary"
        loading={busy}
        {...(capReason === undefined
          ? {}
          : { disabledReason: capReason, disabledReasonId: `${id}-cap` })}
        onClick={() => {
          if (!busy) void stepUp.start(submit);
        }}
      >
        {TEXT.add.start}
      </Button>
      {/* 2a: the reason under the primary, its node in the DOM from the dialog's first paint. */}
      <Text id={`${id}-cap`} variant="caption" tone="secondary">
        {capReason}
      </Text>
    </span>
  );

  return (
    <Dialog
      open={open}
      // Cancel, ✕, the scrim and Esc go through the host: while the add is on the wire the dialog holds (H22), so its
      // answer, a challenge included, is this opening's (S-5347-d01).
      onOpenChange={(next) => {
        if (!next) stepUp.cancel(onClose);
      }}
      title={DECK["d02.8.r07"][0]}
      busy={busy}
      {...(fallbackFocusRef === undefined ? {} : { fallbackFocusRef })}
      footer={
        <>
          <Button variant="secondary" onClick={() => stepUp.cancel(onClose)}>
            {TEXT.add.cancel}
          </Button>
          {start}
        </>
      }
    >
      <FormField
        label={TEXT.add.symbol}
        help={fill(TEXT.add.symbolHelp, { "{grace}": grace })}
        error={errorOf("symbol")}
      >
        <Combobox
          value={symbol}
          onChange={(value) => setSymbol(value)}
          options={instruments.map((name) => ({ value: name, label: name }))}
        />
      </FormField>
      <fieldset style={{ border: 0, margin: 0, padding: 0 }}>
        <legend>
          <Text variant="label">{TEXT.add.streams}</Text>
        </legend>
        {STREAMS.map((kind) => (
          <Checkbox
            key={kind}
            label={STREAM_LABELS[kind]}
            checked={streams.has(kind)}
            onChange={(on) => toggle(kind, on)}
          />
        ))}
        {streamsError === undefined ? null : <InlineError message={streamsError} live="off" />}
      </fieldset>
      {/* CMP-006 names itself through its label; the estimate is the line under the choice (§6.1). */}
      <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
        <Text id={`${id}-depth`} variant="label">
          {TEXT.add.depth}
        </Text>
        <RadioGroup
          aria-labelledby={`${id}-depth`}
          orientation="horizontal"
          options={DEPTHS.map((d) => ({ value: String(d), label: String(d) }))}
          value={String(depth)}
          onChange={(value) => setDepth(Number(value) as Depth)}
        />
        <Text variant="caption" tone="secondary">
          {TEXT.add.depthHelp}
        </Text>
        {depthError === undefined ? null : <InlineError message={depthError} live="off" />}
      </div>
      {forever ? null : (
        <NumericStepperInput
          label={TEXT.add.retention}
          value={retention}
          min={RETENTION_MIN_DAYS}
          max={RETENTION_MAX_DAYS}
          step={1}
          largeStep={10}
          precision={0}
          suffix="d"
          {...(retentionError === undefined ? {} : { invalid: true, errorMessage: retentionError })}
          onChange={setRetention}
        />
      )}
      <Toggle label={TEXT.add.keepForever} checked={forever} onChange={setForever} />
      {/*
        A refusal no field owns (§16.4) shows here, above the footer; one under Streams or Depth, whose groups own no
        polite line, is said here too. The region is there from the start, so each is said once.
      */}
      <div role="status" aria-live="polite" aria-atomic="true">
        {refusal === null ? null : refusal.field === null ? (
          <InlineError message={refusal.text} live="off" />
        ) : refusal.field === "streams" || refusal.field === "depth" ? (
          <span className="cv-visually-hidden">{refusal.text}</span>
        ) : null}
      </div>
      {stepUp.gate}
    </Dialog>
  );
}
