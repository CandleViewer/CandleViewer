/**
 * The signed export, as this session runs it (E42-S04; E42-D04 §8, D12, D13, X1 to X12, AL-18 to
 * AL-24; the orchestrator's BQ-7). Module-level, like the integrity: a page leaving keeps the job,
 * whose id lives in memory only, never in storage, so a reload holds none (a second start then
 * meets `409`, X3).
 * - Start: one `Idempotency-Key` per export, kept with its window, so [Check again] after no answer
 *   re-sends under the same key and at most one export starts (X11). A `403 step_up_required`
 *   comes back held for the shipped gate (`features/stepUp/`), which re-sends it once.
 * - The job is polled while a page holds it and is visible: 2 s, then 1 s longer each time up to
 *   5 s (`jobPollDelay`, BQ-7, PROPOSED), until a terminal state. Each poll writes an
 *   `admin.area_entered` row (D13). A failed poll keeps the last % with `export.poll_failed`,
 *   silent, and never reports the job failed (X12); after ten in a row the polls back off to one
 *   every 30 s until one answers (C-1135P2-16); `404 job_unknown` is the job lost (X9).
 * - The download (X10): the bytes, held whole in memory (at most `audit_export_max_bytes`, 1 GiB),
 *   saved under the served name; `403 step_up_required` is the gate with one re-send; `404` lost,
 *   `410` expired, `429` limited until `Retry-After`, `503` or no answer `export.download_failed`.
 *   Under view-as a download answers the target's `403 forbidden` (BQ-9): `inflight.not_sent`;
 *   the holding page passes its view-as source (C-1135P2-07).
 * - An Owner's `403 forbidden` on any of these calls withdraws the area, as the page's reads do.
 * - Every answer settles, the gate's re-sends included: a body that breaks off is a failed
 *   download, never a rejection (C-1135P2-01).
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import {
  downloadAuditExport,
  exportAuditLog,
  forbiddenMeaning,
  getJob,
  jobPollDelay,
  readDownloadAnswer,
  readExportAnswer,
  type AuditAnswer,
  type AuditExportResult,
  type AuditRefusal,
  type AuditTimers,
  type ExportAccepted,
  type ExportBody,
  type ExportFile,
  type Job,
  type StepUpHold,
} from "./auditReads";

/** The window one export covers (D12): RFC 3339 instants, UTC, and the gzip choice. */
export type ExportWindow = ExportBody;

/** Why a start was refused (X3, AL-24), as the dialog says it. */
export type StartRefusal =
  | { readonly kind: "range"; readonly days: string }
  | { readonly kind: "busy" }
  | { readonly kind: "rate"; readonly until: number }
  | { readonly kind: "signing" }
  | { readonly kind: "store" }
  | { readonly kind: "read_only" }
  | { readonly kind: "view_as" }
  | { readonly kind: "other" };

export type DownloadState =
  | { readonly kind: "idle" }
  | { readonly kind: "downloading" }
  | { readonly kind: "step_up"; readonly hold: StepUpHold; readonly retried: boolean }
  | { readonly kind: "saved" }
  | { readonly kind: "limited"; readonly until: number }
  | { readonly kind: "failed" }
  | { readonly kind: "not_sent" };

export type ExportPhase =
  | { readonly kind: "idle" }
  | { readonly kind: "starting" }
  | { readonly kind: "step_up"; readonly hold: StepUpHold; readonly retried: boolean }
  | { readonly kind: "refused"; readonly refusal: StartRefusal }
  | { readonly kind: "unknown" }
  | { readonly kind: "not_built" }
  | {
      readonly kind: "running";
      readonly jobId: string;
      readonly pct: number | null;
      readonly pollFailed: boolean;
    }
  | {
      readonly kind: "succeeded";
      readonly jobId: string;
      readonly result: AuditExportResult;
      readonly download: DownloadState;
    }
  | { readonly kind: "failed"; readonly jobId: string; readonly error: string | null }
  | { readonly kind: "cancelled"; readonly jobId: string }
  | { readonly kind: "lost" }
  | { readonly kind: "expired"; readonly at: string };

export interface ExportState {
  readonly phase: ExportPhase;
  /** The window of the export being started or run, kept for the dialog and [Check again]. */
  readonly window: ExportWindow | null;
  /** On the client's clock: a `429` blocks a new start until then (AL-24). */
  readonly limitedUntil: number | null;
  /** An Owner's `403 forbidden`: the area is withdrawn (SCR-154 N-2). */
  readonly denied: { readonly refId: string | undefined } | null;
}

export interface ExportDeps extends AuditTimers {
  readonly now: () => number;
  readonly document: Document | null;
  readonly newKey: () => string;
  readonly start: (body: ExportWindow, key: string) => Promise<AuditAnswer<ExportAccepted>>;
  readonly poll: (jobId: string, signal: AbortSignal) => Promise<AuditAnswer<Job>>;
  readonly download: (jobId: string, signal: AbortSignal) => Promise<AuditAnswer<ExportFile>>;
  readonly save: (file: ExportFile) => void;
  /** The session views as another user (BQ-9). */
  readonly viewAs?: (() => boolean) | undefined;
}

export interface ExportStore {
  readonly getState: () => ExportState;
  readonly subscribe: (listener: () => void) => () => void;
  /** Keeps a running job polled while held; `viewAs` is the holding page's view-as source. */
  readonly hold: (viewAs?: () => boolean) => () => void;
  /** Starts an export of `window` under a new key; false while one runs or is starting. */
  readonly start: (window: ExportWindow) => boolean;
  /** [Check again] (X11): the same window under the same key. */
  readonly checkAgain: () => boolean;
  /** The gate re-sent the held start once: its answer. */
  readonly resentStart: (response: Response) => Promise<void>;
  /** The gate's re-send got no answer: the start's outcome is unknown (X11). */
  readonly lostStart: () => void;
  /** The dialog closed with nothing running: a refusal or an unknown start is cleared. */
  readonly dismiss: () => void;
  readonly download: () => boolean;
  /** The gate re-sent the held download once: its answer. */
  readonly resentDownload: (response: Response) => Promise<void>;
  /** Tests only: back to the first state, every call and timer stopped. */
  readonly reset: () => void;
}

/** PROPOSED: a `429` that names no `Retry-After` waits out an hour's window's last minute. */
const LIMIT_FALLBACK_S = 60;
const INITIAL: ExportState = Object.freeze<ExportState>({
  phase: { kind: "idle" },
  window: null,
  limitedUntil: null,
  denied: null,
});

/**
 * `{days}` of `export.refused.range`: the limit a `422 max_export_range` names in its `detail`,
 * "{n} days" or the server's "…_days ({n})" (`api/audit.py`), else 31.
 */
export function rangeDays(detail: string | undefined): string {
  const text = detail ?? "";
  return /(\d{1,4})\s*days?\b/i.exec(text)?.[1] ?? /days?\s*\((\d{1,4})\)/i.exec(text)?.[1] ?? "31";
}

/** At most one gate after the first: a server that keeps challenging never loops the user. */
const MAX_GATES = 2;

export function createExportStore(deps: ExportDeps): ExportStore {
  /** The holding page's view-as source, else the deps' (BQ-9). */
  let holderViewAs: (() => boolean) | null = null;
  const viewAs = (): boolean => (holderViewAs ?? deps.viewAs)?.() === true;
  let state: ExportState = INITIAL;
  const listeners = new Set<() => void>();
  let holds = 0;
  let watching = false;
  /** The started export's `Idempotency-Key` (X11). */
  let key: string | null = null;
  /** Gates opened for the start, and for the download, so far. */
  let startGates = 0;
  let downloadGates = 0;
  /** The current job's polls so far, and its failed polls in a row: `jobPollDelay`'s inputs. */
  let polls = 0;
  let pollFailures = 0;
  let timer: unknown = null;
  let limitTimer: unknown = null;
  let downloadTimer: unknown = null;
  let pollCall: AbortController | null = null;
  let downloadCall: AbortController | null = null;

  const visible = (): boolean => deps.document?.visibilityState !== "hidden";
  const clear = (handle: unknown): null => {
    if (handle !== null) deps.clearTimeout(handle);
    return null;
  };
  function patch(next: Partial<ExportState>): void {
    state = { ...state, ...next };
    for (const listener of [...listeners]) listener();
  }
  const setPhase = (phase: ExportPhase): void => patch({ phase });
  function setDownload(download: DownloadState): void {
    const phase = state.phase;
    if (phase.kind === "succeeded") setPhase({ ...phase, download });
  }
  const meaning = (answer: AuditRefusal): ReturnType<typeof forbiddenMeaning> =>
    forbiddenMeaning(answer, { viewAs: viewAs() });

  function stopPolling(): void {
    timer = clear(timer);
    pollCall?.abort();
    pollCall = null;
  }
  function withdraw(answer: AuditRefusal): void {
    stopPolling();
    downloadCall?.abort();
    downloadCall = null;
    patch({ denied: { refId: answer.refId }, phase: { kind: "idle" } });
  }

  function schedule(): void {
    timer = clear(timer);
    if (holds === 0 || !visible() || state.phase.kind !== "running" || pollCall !== null) return;
    timer = deps.setTimeout(
      () => {
        timer = null;
        poll();
      },
      jobPollDelay(polls, pollFailures),
    );
  }

  function poll(): void {
    const phase = state.phase;
    if (phase.kind !== "running" || state.denied !== null) return;
    const call = new AbortController();
    pollCall = call;
    polls += 1;
    const land = (answer: AuditAnswer<Job>): void => {
      if (pollCall !== call) return; // stopped meanwhile: its answer is dropped
      pollCall = null;
      settlePoll(phase.jobId, answer);
    };
    void deps
      .poll(phase.jobId, call.signal)
      .then(land, () => land({ kind: "failed", reason: "network" }));
  }

  function settlePoll(jobId: string, answer: AuditAnswer<Job>): void {
    const phase = state.phase;
    if (phase.kind !== "running" || phase.jobId !== jobId) return;
    if (answer.kind === "ok") {
      const job = answer.body;
      if (job.status === "failed")
        return setPhase({ kind: "failed", jobId, error: job.error ?? null });
      if (job.status === "cancelled") return setPhase({ kind: "cancelled", jobId });
      if (job.status === "succeeded") {
        // `vetJob` read a succeeded `audit_export` job's whole `AuditExportResult`
        const result =
          job.kind === "audit_export" ? (job.result as AuditExportResult | null) : null;
        if (result !== null && result !== undefined) {
          return setPhase({ kind: "succeeded", jobId, result, download: { kind: "idle" } });
        }
        pollFailures += 1;
        setPhase({ ...phase, pollFailed: true });
      } else {
        pollFailures = 0;
        setPhase({ ...phase, pct: job.progress_pct ?? phase.pct, pollFailed: false });
      }
    } else if (answer.kind === "refused" && answer.status === 404) {
      return setPhase({ kind: "lost" }); // a restart loses every job (X9)
    } else if (
      answer.kind === "refused" &&
      answer.status === 403 &&
      meaning(answer) === "withdrawn"
    ) {
      return withdraw(answer);
    } else {
      pollFailures += 1;
      setPhase({ ...phase, pollFailed: true }); // never the job failed (X12)
    }
    schedule();
  }

  function armStartLimit(until: number): void {
    limitTimer = clear(limitTimer);
    patch({ limitedUntil: until });
    limitTimer = deps.setTimeout(
      () => {
        limitTimer = null;
        patch({ limitedUntil: null });
      },
      Math.max(0, until - deps.now()),
    );
  }

  function refusalOf(answer: AuditRefusal): StartRefusal {
    switch (answer.status) {
      case 422:
        return { kind: "range", days: rangeDays(answer.detail) };
      case 409:
        // a reused key cannot come from [Check again], which re-sends the same body (X11)
        return answer.code === "idempotency_key_reuse" ? { kind: "other" } : { kind: "busy" };
      case 429:
        return {
          kind: "rate",
          until: deps.now() + (answer.retryAfterS ?? LIMIT_FALLBACK_S) * 1_000,
        };
      case 503:
        return answer.code === "signing_unavailable" ? { kind: "signing" } : { kind: "store" };
      default: {
        const why = answer.status === 403 ? meaning(answer) : null;
        if (why === "read_only") return { kind: "read_only" };
        if (why === "view_as") return { kind: "view_as" };
        return { kind: "other" };
      }
    }
  }

  function settleStart(answer: AuditAnswer<ExportAccepted>): void {
    if (state.phase.kind !== "starting") return;
    if (answer.kind === "ok") {
      polls = 0;
      pollFailures = 0;
      setPhase({ kind: "running", jobId: answer.body.job_id, pct: null, pollFailed: false });
      schedule();
      return;
    }
    if (answer.kind !== "refused") return setPhase({ kind: "unknown" }); // it may have started
    if (answer.stepUp !== undefined && startGates < MAX_GATES) {
      startGates += 1;
      return setPhase({ kind: "step_up", hold: answer.stepUp, retried: startGates > 1 });
    }
    if (answer.status === 501) return setPhase({ kind: "not_built" });
    if (answer.status === 403 && meaning(answer) === "withdrawn") return withdraw(answer);
    const refusal = refusalOf(answer);
    setPhase({ kind: "refused", refusal });
    if (refusal.kind === "rate") armStartLimit(refusal.until);
  }

  function send(window: ExportWindow): boolean {
    const sending = key;
    if (sending === null) return false;
    patch({ window, phase: { kind: "starting" } });
    void deps.start(window, sending).then(settleStart, () => settleStart({ kind: "unknown" }));
    return true;
  }

  function settleDownload(answer: AuditAnswer<ExportFile>): void {
    const phase = state.phase;
    if (phase.kind !== "succeeded") return;
    if (answer.kind === "ok") {
      deps.save(answer.body);
      return setDownload({ kind: "saved" });
    }
    if (answer.kind !== "refused") return setDownload({ kind: "failed" });
    if (answer.stepUp !== undefined && downloadGates < MAX_GATES) {
      downloadGates += 1;
      return setDownload({ kind: "step_up", hold: answer.stepUp, retried: downloadGates > 1 });
    }
    switch (answer.status) {
      case 404:
        return setPhase({ kind: "lost" });
      case 410:
        return setPhase({ kind: "expired", at: phase.result.expires_at });
      case 429: {
        const until = deps.now() + (answer.retryAfterS ?? LIMIT_FALLBACK_S) * 1_000;
        setDownload({ kind: "limited", until });
        downloadTimer = clear(downloadTimer);
        downloadTimer = deps.setTimeout(
          () => {
            downloadTimer = null;
            const now = state.phase;
            if (now.kind === "succeeded" && now.download.kind === "limited") {
              setDownload({ kind: "idle" });
            }
          },
          Math.max(0, until - deps.now()),
        );
        return;
      }
      case 403:
        if (meaning(answer) === "withdrawn") return withdraw(answer);
        return setDownload({ kind: "not_sent" });
      default:
        return setDownload({ kind: "failed" });
    }
  }

  function onVisibility(): void {
    if (visible()) schedule();
    else timer = clear(timer);
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    hold: (source) => {
      holds += 1;
      if (source !== undefined) holderViewAs = source;
      if (!watching && deps.document !== null) {
        deps.document.addEventListener("visibilitychange", onVisibility);
        watching = true;
      }
      schedule();
      let released = false;
      return () => {
        if (released) return;
        released = true;
        holds -= 1;
        queueMicrotask(() => {
          if (holds > 0) return;
          stopPolling();
          if (watching) deps.document?.removeEventListener("visibilitychange", onVisibility);
          watching = false;
          holderViewAs = null;
        });
      };
    },
    start: (window) => {
      const kind = state.phase.kind;
      if (state.denied !== null || kind === "starting" || kind === "running") return false;
      if (state.limitedUntil !== null && deps.now() < state.limitedUntil) return false;
      key = deps.newKey();
      startGates = 0;
      return send(window);
    },
    checkAgain: () => {
      if (state.phase.kind !== "unknown" || state.window === null) return false;
      return send(state.window); // the same key: at most one export starts (X11)
    },
    resentStart: async (response) => {
      const phase = state.phase;
      if (phase.kind !== "step_up") return;
      setPhase({ kind: "starting" });
      let answer: AuditAnswer<ExportAccepted>;
      try {
        answer = await readExportAnswer(response, phase.hold.held, deps.now());
      } catch {
        answer = { kind: "unknown" }; // it may have started: [Check again] (X11)
      }
      settleStart(answer);
    },
    lostStart: () => {
      const kind = state.phase.kind;
      if (kind === "step_up" || kind === "starting") setPhase({ kind: "unknown" });
    },
    dismiss: () => {
      const kind = state.phase.kind;
      if (kind === "refused" || kind === "unknown" || kind === "step_up") {
        setPhase({ kind: "idle" });
      }
    },
    download: () => {
      const phase = state.phase;
      if (phase.kind !== "succeeded" || state.denied !== null) return false;
      const { download } = phase;
      if (download.kind === "downloading") return false;
      if (download.kind === "limited" && deps.now() < download.until) return false;
      downloadGates = 0;
      const call = new AbortController();
      downloadCall = call;
      setDownload({ kind: "downloading" });
      const land = (answer: AuditAnswer<ExportFile>): void => {
        if (downloadCall !== call) return;
        downloadCall = null;
        settleDownload(answer);
      };
      void deps
        .download(phase.jobId, call.signal)
        .then(land, () => land({ kind: "failed", reason: "network" }));
      return true;
    },
    resentDownload: async (response) => {
      const phase = state.phase;
      if (phase.kind !== "succeeded" || phase.download.kind !== "step_up") return;
      const { hold } = phase.download;
      setDownload({ kind: "downloading" });
      let answer: AuditAnswer<ExportFile>;
      try {
        answer = await readDownloadAnswer(response, hold.held, phase.jobId, deps.now());
      } catch {
        answer = { kind: "failed", reason: "network" };
      }
      settleDownload(answer);
    },
    reset: () => {
      stopPolling();
      downloadCall?.abort();
      downloadCall = null;
      limitTimer = clear(limitTimer);
      downloadTimer = clear(downloadTimer);
      if (watching) deps.document?.removeEventListener("visibilitychange", onVisibility);
      watching = false;
      holds = 0;
      key = null;
      polls = 0;
      pollFailures = 0;
      holderViewAs = null;
      state = INITIAL;
      for (const listener of [...listeners]) listener();
    },
  };
}

/** The browser's save: the bytes as an object URL, a hidden `<a download>` click, then revoked. */
export function saveInBrowser(file: ExportFile): void {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.fileName;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

const browserDeps: ExportDeps = {
  now: () => Date.now(),
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
  document: typeof document === "undefined" ? null : document,
  newKey: () => crypto.randomUUID(),
  start: (body, idempotencyKey) => exportAuditLog(body, idempotencyKey),
  poll: (jobId, signal) => getJob(jobId, { signal }),
  download: (jobId, signal) => downloadAuditExport(jobId, { signal }),
  save: saveInBrowser,
};

/** The session's one export. */
export const auditExport: ExportStore = createExportStore(browserDeps);

/**
 * Holds the running job's polls while the calling page is mounted and `active`, with the page's
 * view-as state, so a `403 forbidden` under view-as is the target's refusal (BQ-9).
 */
export function useExportHold(
  active: boolean,
  viewAs = false,
  store: ExportStore = auditExport,
): void {
  const viewing = useRef(viewAs);
  useEffect(() => {
    viewing.current = viewAs;
  }, [viewAs]);
  useEffect(() => {
    if (!active) return undefined;
    return store.hold(() => viewing.current);
  }, [active, store]);
}

/** The export's state; the page re-renders on each change. */
export function useExportState(store: ExportStore = auditExport): ExportState {
  return useSyncExternalStore(store.subscribe, store.getState, store.getState);
}
