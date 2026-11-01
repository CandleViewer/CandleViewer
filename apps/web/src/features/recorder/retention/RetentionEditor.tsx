/**
 * SCR-141 Admin: the retention policy editor (E16-S03; E16-D03; E16-D06 KB-09 to KB-13, FM-08 to FM-12, RG-12,
 * SR-17 to SR-23, T2-06 to T2-08, §20.3 (i), (iii), (iv), (viii); BQ-3, BQ-6 to BQ-15). One CMP-043 dialog over
 * SCR-140, 960 px: the rule banner and, while viewing as, the one notice; the error summary; the eight global rows;
 * the override grid; the pinned list; the preview panel; the estimate and what becomes eligible, with "Preview
 * changes"; then the footer. A reduction must be previewed for the current diff before Apply opens its typed
 * confirm (frozen (iv)); anything else takes the plain confirm. Apply freezes the set the confirm shows, and the
 * confirm sends exactly that set (BQ-10's whole set), its one `Idempotency-Key` held across the step-up's re-send
 * (C-2.10), and `apply_now` when ticked; nothing is re-sent on a failure. A save keeps the dialog open on its outcome
 * line and tracks the sweep it started by its id (BQ-11). Every write is the server's to allow (C-12.4): a refusal
 * shows at the point of action in the summary; an answer that may have applied, unread, says the outcome is pending
 * and reads the set back (`22`'s step-up rule: never "Not sent", never re-sent).
 */
import { useEffect, useId, useRef, useState, type JSX } from "react";
import {
  Button,
  Callout,
  Dialog,
  GatedAnnounceProvider,
  Icon,
  Skeleton,
  Text,
} from "@candleviewer/ui";
import { STEP_UP_NOT_SENT, stepUpOutcomePending } from "../../stepUp/StepUpDialog";
import { TEXT } from "../copy";
import { useRecorderExtensions, type RetentionEditorProps } from "../extensions";
import { sayPolitely } from "../pageAnnouncer";
import { recorderApi, type ApiResult, type RetentionPoliciesSaved } from "../recorderApi";
import { pollRefusalText, useJobPoll } from "../useJobPoll";
import { ErrorSummary, type SummaryLink } from "./ErrorSummary";
import { GlobalDefaults, type WriteGate } from "./GlobalDefaults";
import { OverrideGrid, pendingSymbol, type PendingAdd } from "./OverrideGrid";
import { PinnedList } from "./PinnedList";
import { PreviewPanel } from "./PreviewPanel";
import { previewKind, reportRetention } from "./retentionAnalytics";
import { RetentionConfirm, type ConfirmAttempt } from "./RetentionConfirm";
import { RETENTION_DECK, STREAM_WORDS } from "./retentionCopy";
import {
  previewSource as sharedPreview,
  steadyState,
  type Preview,
  type PreviewSource,
} from "./retentionEstimate";
import { RetentionFooter, jobStateOf } from "./RetentionFooter";
import {
  addOverride,
  classify,
  hasChanges,
  invalidCount,
  isDirty,
  load,
  resetToDefault,
  setAction,
  setDays,
  stageRemoval,
  symbolsOf,
  toRequest,
  undoRemoval,
  validateDays,
  type Draft,
  type OfferedAction,
  type RowKey,
  type StorageUsage,
  type StreamKind,
  type SymbolCode,
} from "./retentionModel";
import {
  RETENTION_TEXT,
  applyReasonText,
  eligibilityText,
  estimateText,
  fieldErrorText,
  formulaText,
  refusalSentence,
  summaryLinkText,
  summaryTitle,
  viewAsNotice,
  type ApplyReason,
} from "./retentionText";

/** A view-as context (E09-D09 §3.1 `rbac.view_as`): its target's name. */
export interface ViewAs {
  readonly user: string;
}

export interface RetentionEditorOptions {
  /**
   * The view-as context (BQ-8): no client source exists yet, so nothing passes it and the leg is dormant; set, every
   * write is T2 and points at the one notice, while reads and the preview go on.
   */
  readonly viewAs?: ViewAs | null | undefined;
  /** BQ-3's one preview seam (`retentionEstimate.ts`): the estimate until D03-G1's route exists. */
  readonly previewSource?: PreviewSource | undefined;
  /** What a press says, once, politely: the shell's announcer (R-5). */
  readonly say?: ((text: string) => void) | undefined;
  /** CMP-044's clock (its guard), injectable for tests. */
  readonly now?: (() => number) | undefined;
}

type LoadState = "loading" | "failed" | "ready";
type Summary = { readonly kind: "fields" } | { readonly kind: "reason"; readonly text: string };
/** A preview as rendered: the diff it is for (the request's items), the source's answer, and its count. */
interface Shown {
  readonly diff: string;
  readonly data: Preview | null;
  readonly n: number;
}

const newRow = (id: number): PendingAdd => ({
  id,
  symbol: "",
  stream: "trades",
  days: null,
  action: "archive_parquet",
});

/** The dialog's title: where the read-back of an unknown outcome shows (E09-D06 §2 item 4). */
const [TITLE] = RETENTION_DECK["retention.title"];

/** The draft with the add row in it, once its symbol and stream are chosen (D03 §6 `row-add`). */
function withPending(
  draft: Draft,
  pending: PendingAdd | null,
  symbols: readonly SymbolCode[],
): Draft {
  if (pending === null) return draft;
  const overrides = draft.rows.filter((row) => row.symbol !== null);
  const symbol = pendingSymbol(pending, symbols, overrides);
  if (symbol === null) return draft;
  const key: RowKey = { symbol, stream: pending.stream };
  const added = addOverride(draft, symbol, pending.stream);
  const timed = pending.days === null ? added : setDays(added, key, pending.days);
  return setAction(timed, key, pending.action);
}

/** A synchronous source's answer for the inline sentence; an asynchronous one waits for the press. */
function quickPreview(source: PreviewSource, ...args: Parameters<PreviewSource>): Preview | null {
  const answer = source(...args);
  return answer instanceof Promise ? null : answer;
}

/**
 * The classification's symbols: the storage report's (it lists at most 64) widened by SCR-140's recorded symbols,
 * the status's and the live frame's, and by every symbol the set itself holds a rule for. A symbol is exempt only
 * while every source that lists it says it is pinned, so the confirm may overstate what goes, never understate it.
 * Without a report the scope stays unknown (null): a shrinking rule is a reduction over every symbol without its
 * own rule (fail closed).
 */
function recordedSymbols(
  storage: StorageUsage | null,
  status: RetentionEditorProps["status"],
  frame: RetentionEditorProps["frame"],
  draft: Draft | null,
): ReturnType<typeof symbolsOf> {
  const report = symbolsOf(storage);
  const pins = new Map<SymbolCode, boolean>();
  const note = (symbol: SymbolCode, on: boolean): void =>
    void pins.set(symbol, (pins.get(symbol) ?? true) && on);
  for (const s of storage?.symbols ?? []) {
    if (s.symbol !== undefined) note(s.symbol, s.pinned === true);
  }
  for (const s of frame?.symbols ?? []) note(s.symbol, s.pinned === true);
  const pinned = [...pins].flatMap(([symbol, on]) => (on ? [symbol] : [])).sort();
  if (report.symbols === null) return { symbols: null, pinned };
  const recorded = [
    ...(status?.symbols ?? []).flatMap((s) => (s.symbol === undefined ? [] : [s.symbol])),
    ...pins.keys(),
    // A stored override names a symbol with data no source may list: it is in scope, unsized.
    ...[...(draft?.base ?? []), ...(draft?.rows ?? [])].flatMap((row) =>
      row.symbol === null ? [] : [row.symbol],
    ),
  ];
  return { symbols: [...new Set([...report.symbols, ...recorded])].sort(), pinned };
}

/** A preview as shown: the estimate over the symbols the storage report lists, and the ones it cannot size. */
interface Sized {
  readonly preview: Preview | null;
  readonly unlisted: readonly SymbolCode[];
}

/**
 * The estimate sizes a symbol from the storage report's usage. A symbol only SCR-140 lists has none, and the
 * fallback would read it as "Nothing recorded before … exists yet": it gets no row, no size clause and no part in
 * the total, and is named instead (C-2.13). A server answer (D03-G1) is taken whole.
 */
function sized(preview: Preview | null, storage: StorageUsage | null): Sized {
  if (preview === null || storage === null || preview.source !== "estimate") {
    return { preview, unlisted: [] };
  }
  const listed = new Set((storage.symbols ?? []).map((s) => s.symbol));
  const rows = preview.rows.filter((row) => listed.has(row.symbol));
  const unlisted = preview.rows.flatMap((row) => (listed.has(row.symbol) ? [] : [row.symbol]));
  if (unlisted.length === 0) return { preview, unlisted };
  const totalBytes = rows.reduce((sum, row) => sum + row.bytes, 0);
  return { preview: { ...preview, rows, totalBytes, symbolCount: rows.length }, unlisted };
}

/**
 * An answer that may have applied without the client knowing it (E09-D06 §2 item 4): none at all, or a `2xx` whose
 * body cannot be read. It is never reported as refused or not sent, and never re-sent.
 */
const unknownOutcome = (res: ApiResult<RetentionPoliciesSaved>): boolean =>
  res.ok ? res.data === null : res.status === 0 || (res.status >= 200 && res.status < 300);

export function RetentionEditor({
  open,
  onClose,
  status,
  frame,
  storage: givenStorage,
  viewAs = null,
  previewSource = sharedPreview,
  say = sayPolitely,
  now,
}: RetentionEditorProps & RetentionEditorOptions): JSX.Element {
  const id = useId();
  const extensions = useRecorderExtensions();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pending, setPending] = useState<PendingAdd | null>(null);
  const [readStorage, setReadStorage] = useState<StorageUsage | null>(null);
  const [applyNow, setApplyNow] = useState(false);
  const [preview, setPreview] = useState<Shown | null>(null);
  /** The form drifted off an open confirm: Apply asks for a preview of the current diff, whatever it is. */
  const [previewAsked, setPreviewAsked] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summarySeq, setSummarySeq] = useState(0);
  /** The confirm as Apply froze it (kept through its exit), and whether it is open. */
  const [attempt, setAttempt] = useState<ConfirmAttempt | null>(null);
  const [confirming, setConfirming] = useState(false);
  /** The attempt whose PUT is in flight: only its own answer ends it. */
  const [inFlight, setInFlight] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const [savedSeq, setSavedSeq] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  /** A preview was seen in this opening and nothing was applied since (the cancelled-after-preview count). */
  const previewed = useRef(false);
  /** The opening a read belongs to: an answer from an earlier one is dropped. */
  const opening = useRef(0);
  const opened = useRef(false);
  const firstFocus = useRef(false);
  /** The attempts so far, and the one whose confirm is open (null when none is). */
  const attempts = useRef(0);
  const liveAttempt = useRef<number | null>(null);
  /** Retry was pressed: if the read fails again, focus goes back to the new Retry. */
  const retried = useRef(false);
  const summaryRef = useRef<HTMLHeadingElement>(null);
  const previewRef = useRef<HTMLHeadingElement>(null);
  const outcomeRef = useRef<HTMLParagraphElement>(null);
  const failedRef = useRef<HTMLDivElement>(null);
  const [focusField, setFocusField] = useState<string | null>(null);
  const storage = givenStorage ?? readStorage;
  const saving = inFlight !== null;
  const noticeId = `${id}-notice`;
  const fieldId = (key: RowKey): string => `${id}-field-${key.symbol ?? ""}-${key.stream}`;
  const gate: WriteGate | null =
    viewAs === null ? null : { reason: viewAsNotice(viewAs.user), noticeId };

  async function read(at: number): Promise<void> {
    const res = await recorderApi.retention();
    if (at !== opening.current) return;
    if (res.ok && res.data !== null) {
      setDraft(load(res.data.items ?? []));
      setLoadState("ready");
    } else setLoadState("failed");
  }

  async function readReport(at: number): Promise<void> {
    const res = await recorderApi.storage();
    if (at === opening.current && res.ok && res.data !== null) setReadStorage(res.data);
  }

  const poll = useJobPoll(jobId, "retention");
  const job = jobStateOf(poll);
  const sweeping = job.kind === "queued" || job.kind === "running";
  // §16.4 row 10: a poll the server refused shows its T4 under the line; the sweep is still followed.
  const pollRefused = poll?.pollRefusal == null ? null : pollRefusalText(poll.pollRefusal);

  // Each opening starts from the server's set (D03 §4 `SCR-141/loading`); StrictMode's second run is the same one.
  useEffect(() => {
    if (!open) {
      opened.current = false;
      return;
    }
    if (opened.current) return;
    opened.current = true;
    opening.current += 1;
    const at = opening.current;
    setLoadState("loading");
    setDraft(null);
    setPending(null);
    setApplyNow(false);
    setPreview(null);
    setPreviewAsked(false);
    setSummary(null);
    setConfirming(false);
    setAttempt(null);
    liveAttempt.current = null;
    setInFlight(null);
    setSaved(false);
    // A sweep this client started is followed while it runs (BQ-11); a finished one's line was the last opening's.
    if (!sweeping) setJobId(null);
    previewed.current = false;
    firstFocus.current = false;
    retried.current = false;
    reportRetention({ name: "retention.editor_opened" });
    void read(at);
    if (givenStorage === null) void readReport(at);
    // One read per opening: the report SCR-140 holds is read at the opening only.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  }, [open]);

  // KB-09: once the set has drawn, the first field takes focus, unless the user has already moved it.
  useEffect(() => {
    if (loadState !== "ready" || firstFocus.current) return;
    firstFocus.current = true;
    const active = document.activeElement;
    if (active === null || active === document.body || active instanceof HTMLHeadingElement) {
      document.getElementById(fieldId({ symbol: null, stream: "trades" }))?.focus();
    }
  });
  // A Retry whose read fails again hands focus to the new Retry (its press unmounted the old one).
  useEffect(() => {
    if (loadState !== "failed" || !retried.current) return;
    retried.current = false;
    failedRef.current?.querySelector("button")?.focus();
  }, [loadState]);
  useEffect(() => {
    if (summarySeq > 0) summaryRef.current?.focus();
  }, [summarySeq]);
  useEffect(() => {
    if (savedSeq > 0) outcomeRef.current?.focus();
  }, [savedSeq]);
  const previewSeq = preview?.n ?? 0;
  useEffect(() => {
    if (previewSeq === 0) return;
    const heading = previewRef.current;
    heading?.focus();
    // The heading is in view; so is the panel's end when it fits (the table, the total and the caption).
    heading?.closest("section")?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [previewSeq]);
  useEffect(() => {
    if (focusField === null) return;
    document.getElementById(focusField)?.focus();
    setFocusField(null);
  }, [focusField]);

  const reports = recordedSymbols(storage, status, frame, draft);
  const symbols = reports.symbols ?? [];
  const effective = draft === null ? null : withPending(draft, pending, symbols);
  const classification = effective === null ? null : classify(effective, { ...reports, applyNow });
  const invalid = effective === null ? 0 : invalidCount(effective);
  const changed = effective !== null && hasChanges(effective);
  const diff = effective === null ? "" : JSON.stringify(toRequest(effective).items);
  const shown = preview !== null && preview.diff === diff ? preview : null;
  const needsPreview = classification?.kind === "reduction" || previewAsked;
  const reason: ApplyReason | null =
    invalid > 0
      ? { kind: "invalid", n: invalid }
      : !changed
        ? { kind: "empty" }
        : needsPreview && shown === null
          ? { kind: "preview" }
          : null;
  const dirty = effective !== null && (isDirty(effective) || pending !== null);
  const steady = storage === null || effective === null ? null : steadyState(storage, effective);
  const estimate = sized(shown?.data ?? null, storage);
  const inline =
    shown !== null
      ? estimate
      : sized(
          classification?.kind === "reduction" && storage !== null && effective !== null
            ? quickPreview(previewSource, storage, effective, classification)
            : null,
          storage,
        );
  // What the confirm would say: its kind, scope, exempt symbols and words, as the classification has them.
  const shape = classification === null ? "" : JSON.stringify(classification);
  // The open confirm no longer matches the form: another diff, other words (a scope SCR-140 widened or a pin it
  // dropped), a reason on Apply, or a write gated meanwhile.
  const drifted =
    attempt !== null &&
    (attempt.diff !== diff || attempt.shape !== shape || reason !== null || gate !== null);

  /** Every edit: a summary of field errors stays (it follows the fields), any other one goes. */
  function edit(change: (d: Draft) => Draft): void {
    setDraft((d) => (d === null ? d : change(d)));
    setSummary((s) => (s?.kind === "fields" ? s : null));
    setSaved(false);
  }

  function close(): void {
    // A save in flight keeps the dialog: its answer is shown here (D03 §10).
    if (saving) return;
    if (previewed.current) reportRetention({ name: "retention.change_cancelled_after_preview" });
    previewed.current = false;
    onClose();
  }

  /** The summary at the point of action: its heading takes focus (F-10). */
  function tell(text: string): void {
    setSummary({ kind: "reason", text });
    setSummarySeq((n) => n + 1);
  }

  function refuse(): void {
    if (reason === null) return;
    if (reason.kind === "invalid") {
      setSummary({ kind: "fields" });
      setSummarySeq((n) => n + 1);
    } else tell(applyReasonText(reason));
  }

  async function runPreview(): Promise<void> {
    if (effective === null || classification === null) return;
    // No report to estimate from: the panel says what becomes eligible, without sizes, and the
    // report is asked for again.
    if (storage === null) void readReport(opening.current);
    reportRetention({ name: "retention.preview_requested", kind: previewKind(classification) });
    const data =
      classification.kind === "reduction" && storage !== null
        ? await Promise.resolve(previewSource(storage, effective, classification))
        : null;
    previewed.current = true;
    setPreviewAsked(false);
    setSummary(null);
    setPreview((p) => ({ diff, data, n: (p?.n ?? 0) + 1 }));
  }

  /** Apply (a ready form): the confirm opens on the set as it stands, frozen (S-5353-02). */
  function openConfirm(): void {
    if (effective === null || classification === null || reason !== null || gate !== null) return;
    attempts.current += 1;
    const n = attempts.current;
    liveAttempt.current = n;
    setAttempt({
      n,
      body: toRequest(effective),
      query: applyNow ? { apply_now: true } : {},
      diff,
      shape,
      classification,
      preview: estimate.preview,
      unlisted: estimate.unlisted,
      steady,
      applyNow,
      pendingSent: effective !== draft,
    });
    setConfirming(true);
  }

  function closeConfirm(): void {
    liveAttempt.current = null;
    setConfirming(false);
  }

  /** Ends `n`'s flight, and only its own (a closed confirm's late answer leaves another's in flight). */
  const land = (n: number): void => setInFlight((f) => (f === n ? null : f));

  async function send(at: ConfirmAttempt): Promise<ApiResult<RetentionPoliciesSaved>> {
    setInFlight(at.n);
    const res = await recorderApi.setRetention(at.body, at.query);
    // A challenge holds the request: the confirm is a control again while SCR-006 is open (D02 §6.4).
    if (res.stepUp !== null) land(at.n);
    return res;
  }

  /** The answer may have applied: never "Not sent", never re-sent; the set is read back (`22`). */
  async function outcomeUnknown(at: ConfirmAttempt): Promise<void> {
    land(at.n);
    if (liveAttempt.current === at.n) closeConfirm();
    setPreview(null);
    if (at.pendingSent) setPending(null);
    tell(stepUpOutcomePending(TITLE));
    await read(opening.current);
  }

  function answer(at: ConfirmAttempt, res: ApiResult<RetentionPoliciesSaved>): void {
    land(at.n);
    if (res.ok && res.data !== null) {
      // Saved: the server's set, whichever confirm asked for it.
      setDraft(load(res.data.items));
      // An add row that was not complete when the confirm opened was not sent: it stays, as typed.
      if (at.pendingSent) setPending(null);
      setPreview(null);
      setSummary(null);
      closeConfirm();
      setApplyNow(false);
      previewed.current = false;
      setSaved(true);
      setSavedSeq((n) => n + 1);
      if (res.data.job_id !== null) setJobId(res.data.job_id);
      return;
    }
    if (unknownOutcome(res)) {
      void outcomeUnknown(at);
      return;
    }
    // Nothing was stored. Another confirm open since: this one's words would only confuse it.
    if (res.route === null || (liveAttempt.current !== null && liveAttempt.current !== at.n))
      return;
    // A refusal stores nothing (`22`): the confirm closes and the summary says why, at the point of action.
    closeConfirm();
    tell(refusalSentence(res.route));
  }

  /** A challenge answered a confirm no longer open: dropped unsent (S-5353-01), said where the action was. */
  function notSent(at: ConfirmAttempt): void {
    land(at.n);
    tell(STEP_UP_NOT_SENT);
  }

  /** The form drifted off the open confirm: it closes, nothing is sent, and Apply asks for a preview again. */
  function drift(): void {
    closeConfirm();
    setPreviewAsked(true);
    tell(applyReasonText({ kind: "preview" }));
  }

  const links: SummaryLink[] =
    effective === null
      ? []
      : effective.rows.flatMap((row) => {
          const error = row.removed ? null : validateDays(row.days);
          if (error === null) return [];
          const name = STREAM_WORDS[row.stream];
          const label = row.symbol === null ? name : `${row.symbol} · ${name}`;
          return [{ label: summaryLinkText(label, fieldErrorText(error)), targetId: fieldId(row) }];
        });
  const summaryShown =
    summary === null
      ? null
      : summary.kind === "fields"
        ? links.length === 0
          ? null
          : { title: summaryTitle(links.length), links }
        : { title: summary.text, links: [] };

  const globals = new Map<StreamKind, Draft["rows"][number]>(
    (draft?.rows ?? []).filter((row) => row.symbol === null).map((row) => [row.stream, row]),
  );
  const { openRowDetail } = extensions;
  const manage =
    openRowDetail === undefined
      ? undefined
      : (symbol: string) => {
          close();
          openRowDetail(symbol);
        };

  return (
    <GatedAnnounceProvider announce={say}>
      <Dialog
        open={open}
        onOpenChange={(next, why) => {
          // A scrim press is no discard: only Cancel and Esc, which the caption names, drop unsaved edits.
          if (!next && !(why === "scrim" && dirty)) close();
        }}
        title={TITLE}
        size="lg"
        busy={loadState === "loading" || saving}
        footer={
          <RetentionFooter
            loading={loadState !== "ready"}
            jobId={jobId}
            job={job}
            pollRefused={pollRefused}
            saved={saved}
            outcomeRef={outcomeRef}
            applyNow={applyNow}
            onApplyNow={setApplyNow}
            dirty={dirty}
            onCancel={close}
            reason={reason === null ? undefined : applyReasonText(reason)}
            onApply={openConfirm}
            onRefused={refuse}
            saving={saving}
            gate={gate}
          />
        }
      >
        {gate === null ? null : (
          <p
            id={noticeId}
            style={{
              margin: 0,
              display: "flex",
              gap: "var(--space-inset-xs)",
              alignItems: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            <Icon name="lock" />
            {gate.reason}
          </p>
        )}
        <Callout tone="info" live="off" title={RETENTION_DECK["retention.rule"][0]} />
        {summaryShown === null ? null : (
          <ErrorSummary
            title={summaryShown.title}
            links={summaryShown.links}
            headingRef={summaryRef}
          />
        )}
        {loadState === "loading" ? (
          <div aria-busy="true" style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
            <Text as="p" tone="secondary">
              {RETENTION_DECK["retention.loading"][0]}
            </Text>
            <Skeleton shape="row" count={8} />
          </div>
        ) : null}
        {loadState === "failed" ? (
          <div ref={failedRef}>
            <Callout
              tone="danger"
              live="polite"
              title={RETENTION_TEXT.loadFailed}
              retry={{
                label: TEXT.retry,
                onClick: () => {
                  retried.current = true;
                  setLoadState("loading");
                  void read(opening.current);
                },
              }}
            />
          </div>
        ) : null}
        {loadState === "ready" && draft !== null ? (
          <>
            <GlobalDefaults
              rows={draft.rows.filter((row) => row.symbol === null)}
              fieldId={(stream) => fieldId({ symbol: null, stream })}
              gate={gate}
              onDays={(stream, n) => edit((d) => setDays(d, { symbol: null, stream }, n))}
              onAction={(stream, action: OfferedAction) =>
                edit((d) => setAction(d, { symbol: null, stream }, action))
              }
              onReset={(stream) => {
                edit((d) => resetToDefault(d, stream));
                setFocusField(fieldId({ symbol: null, stream }));
              }}
            />
            <OverrideGrid
              rows={draft.rows.filter((row) => row.symbol !== null)}
              pending={pending}
              globals={globals}
              pinned={new Set(reports.pinned)}
              symbols={symbols}
              fieldId={fieldId}
              gate={gate}
              onDays={(key, n) => edit((d) => setDays(d, key, n))}
              onAction={(key, action) => edit((d) => setAction(d, key, action))}
              onRemove={(key) => edit((d) => stageRemoval(d, key))}
              onUndo={(key) => edit((d) => undoRemoval(d, key))}
              onAdd={() => {
                if (pending === null) setPending(newRow(1));
                else if (effective !== null && effective !== draft) {
                  // A complete add row joins the draft; a new one is appended.
                  edit(() => effective);
                  setPending(newRow(pending.id + 1));
                } else setPending({ ...pending, id: pending.id + 1 });
              }}
              onPending={(next) => {
                setPending(next);
                setSummary((s) => (s?.kind === "fields" ? s : null));
                setSaved(false);
              }}
              say={say}
            />
            <PinnedList storage={storage} pinned={reports.pinned} onManage={manage} />
            {shown === null || classification === null ? null : (
              <PreviewPanel
                classification={classification}
                preview={estimate.preview}
                unlisted={estimate.unlisted}
                headingRef={previewRef}
              />
            )}
            <div style={{ display: "grid", gap: "var(--space-stack-xs)", justifyItems: "start" }}>
              {steady === null ? null : (
                <>
                  <Text as="p">{estimateText(steady)}</Text>
                  <Text as="p" variant="caption" tone="secondary">
                    {formulaText(steady)}
                  </Text>
                </>
              )}
              {classification === null
                ? null
                : eligibilityText(classification, inline.preview, inline.unlisted).map((line) => (
                    <Text key={line} as="p">
                      {line}
                    </Text>
                  ))}
              <Button variant="secondary" onClick={() => void runPreview()}>
                {RETENTION_DECK["retention.preview.button"][0]}
              </Button>
            </div>
          </>
        ) : null}
        {attempt === null ? null : (
          <RetentionConfirm
            key={attempt.n}
            open={confirming}
            attempt={attempt}
            busy={inFlight === attempt.n}
            drifted={drifted}
            send={() => send(attempt)}
            onAnswer={(res) => answer(attempt, res)}
            onNotSent={() => notSent(attempt)}
            onOutcomeUnknown={() => outcomeUnknown(attempt)}
            onDrift={drift}
            onCancel={closeConfirm}
            now={now}
          />
        )}
      </Dialog>
    </GatedAnnounceProvider>
  );
}
