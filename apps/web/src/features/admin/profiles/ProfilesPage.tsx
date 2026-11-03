/**
 * SCR-130 Account profiles at R-330 (E28-S01, #971; E28-D02 §5.1, E28-D03 §3, E28-D06 §4.1): one row
 * per profile, each account's default first and its alternates after it, every value served. The row
 * menu edits (R-331), duplicates as a new alternate (R-331 `new`, BQ-02 (a)) or deletes behind the
 * confirm naming the account and the profile; the delete is Owner-only behind the `risk_caps` step-up,
 * which the server demands and this screen answers (SR-025). A refusal shows the served blockers.
 */
import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import { useNavigate } from "react-router";
import {
  ConfirmDialog,
  EmptyState,
  PageHeader,
  Table,
  type MenuItem,
  type TableColumn,
} from "@candleviewer/ui";
import { announce } from "../../app-shell/announcer";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { StepUpChallengeGate } from "../../stepUp/StepUpChallengeGate";
import { stepUpOutcomePending } from "../../stepUp/StepUpDialog";
import { noopProfilesAnalytics, type ProfilesAnalytics } from "./analytics";
import {
  profilesApi,
  type AccountProfile,
  type ProfilesApi,
  type Refusal,
  type StepUpHold,
  type WriteOutcome,
} from "./api";
import { PROFILES_COPY as C } from "./copy";
import { buildRows, type ProfileRow } from "./listModel";
import { editorPath, newProfilePath } from "./paths";

export const HEADING_ID = "scr-130-title";

type Load =
  | { readonly kind: "loading" }
  | { readonly kind: "failed" }
  | {
      readonly kind: "ready";
      readonly rows: readonly ProfileRow[];
      /** Accounts whose profiles were read, and accounts listed (a `404` read is skipped). */
      readonly accounts: number;
      readonly listed: number;
    };

type Removal =
  | {
      readonly stage: "confirm";
      readonly row: ProfileRow;
      readonly busy: boolean;
      readonly failure: string | null;
    }
  /** The step-up replaces the confirm under the same scrim (E28-D06 hand-off §G, CMP-044 M-2). */
  | {
      readonly stage: "step_up";
      readonly row: ProfileRow;
      readonly hold: StepUpHold;
      readonly retried: boolean;
    };

/** A `412`: the row's `If-Match` is stale, so the list is read again before another try. */
const isVersionConflict = (refusal: Refusal): boolean =>
  refusal.status === 412 || refusal.code === "version_conflict";

/**
 * A refused delete's words: the deck's per served code; the served `detail` where the deck says. A
 * `409` with no readable `detail` names its code, never a guessed blocker (an armed rule may be one).
 */
export function deleteRefusalText(refusal: Refusal): string {
  if (refusal.status === 409) {
    return refusal.detail === null ? C.notDeleted(refusal.code) : C.cannotDelete(refusal.detail);
  }
  if (isVersionConflict(refusal)) return C.versionConflict;
  if (refusal.code === "audit_unavailable") return C.auditUnavailable;
  return C.notDeleted(refusal.code);
}

/**
 * The columns' minimums (em) sum to 58 with the actions column, so the table keeps its columns in the
 * admin content panel at 1280 px and stacks only at 200 % text (CMP-049's reflow); their widths fit
 * the served words, and the region scrolls sideways where the panel is narrower. A cell longer than its
 * column is cut with CMP-049's echo; its whole text stays in the DOM, so its name is never cut.
 */
const COLUMNS: readonly TableColumn<ProfileRow>[] = [
  {
    id: "account",
    header: C.columns.account,
    minWidthEm: 6,
    widthEm: 9,
    cell: (r) => `${r.accountLabel} · ${r.environment}`,
  },
  {
    id: "profile",
    header: C.columns.profile,
    minWidthEm: 9,
    widthEm: 15,
    cell: (r) => r.profileText,
  },
  { id: "trading", header: C.columns.trading, minWidthEm: 3, widthEm: 4, cell: (r) => r.trading },
  { id: "symbols", header: C.columns.symbols, minWidthEm: 7, widthEm: 10, cell: (r) => r.symbols },
  {
    id: "leverage",
    header: C.columns.leverage,
    minWidthEm: 3,
    widthEm: 5,
    align: "end",
    cell: (r) => r.leverage,
  },
  { id: "sizing", header: C.columns.sizing, minWidthEm: 7, widthEm: 10, cell: (r) => r.sizing },
  {
    id: "daily",
    header: C.columns.dailyLoss,
    minWidthEm: 4,
    widthEm: 6,
    align: "end",
    cell: (r) => r.dailyLoss,
  },
  {
    id: "position",
    header: C.columns.maxPosition,
    minWidthEm: 5,
    widthEm: 8,
    align: "end",
    cell: (r) => r.maxPosition,
  },
  { id: "changed", header: C.columns.changed, minWidthEm: 6, widthEm: 13, cell: (r) => r.changed },
  {
    id: "notes",
    header: C.columns.notes,
    minWidthEm: 5,
    widthEm: 24,
    cell: (r) => r.notes.join(" "),
  },
];

export interface ProfilesPageProps {
  readonly api?: ProfilesApi;
  readonly analytics?: ProfilesAnalytics;
}

export function ProfilesPage({
  api = profilesApi,
  analytics = noopProfilesAnalytics,
}: ProfilesPageProps): JSX.Element {
  const navigate = useNavigate();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [removal, setRemoval] = useState<Removal | null>(null);
  /** Invalid step-up codes counted so far, carried into a renewed challenge's gate (A11Y-F-0010). */
  const [priorFailures, setPriorFailures] = useState(0);
  /** The rows last read: a delete sends the current row's version, never the one the menu opened. */
  const latest = useRef<readonly ProfileRow[]>([]);
  const pendingSeq = useRef(0);
  const viewed = useRef(false);
  const heading = useRef<HTMLElement | null>(null);
  const abort = useRef<AbortController | null>(null);
  // The analytics port is read at emit time, so a host passing a fresh object never re-reads the list.
  const sink = useRef(analytics);
  sink.current = analytics;

  const refresh = useCallback(async (): Promise<void> => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setLoad({ kind: "loading" });
    const accounts = await api.listAccounts(controller.signal);
    if (controller.signal.aborted) return;
    if (accounts.kind !== "ok") return setLoad({ kind: "failed" });
    const reads = await Promise.all(
      accounts.value.map((a) => api.listProfiles(a.id, controller.signal)),
    );
    if (controller.signal.aborted) return;
    const profiles = new Map<string, readonly AccountProfile[]>();
    for (const [i, read] of reads.entries()) {
      const account = accounts.value[i];
      if (account === undefined || read.kind === "not_found") continue;
      if (read.kind !== "ok") return setLoad({ kind: "failed" });
      profiles.set(account.id, read.value);
    }
    const rows = buildRows(accounts.value, profiles);
    latest.current = rows;
    setLoad({ kind: "ready", rows, accounts: profiles.size, listed: accounts.value.length });
    if (!viewed.current) {
      viewed.current = true;
      sink.current.emit({
        name: "profile.list_viewed",
        accounts: profiles.size,
        profiles: rows.length,
      });
    }
  }, [api]);

  useEffect(() => {
    heading.current = document.getElementById(HEADING_ID);
    // the confirm's fallback and a vanished row's focus land here, so it takes focus (never a tab stop)
    heading.current?.setAttribute("tabindex", "-1");
    void refresh();
    return () => abort.current?.abort();
  }, [refresh]);

  /** The deleted row's menu button is gone after the read-back: focus goes to the page, not `body`. */
  const keepFocus = useCallback((): void => {
    const active = document.activeElement;
    if (active === null || active === document.body) heading.current?.focus();
  }, []);

  const settle = useCallback(
    (row: ProfileRow, outcome: WriteOutcome, retried: boolean): void => {
      if (outcome.kind === "ok") {
        setRemoval(null);
        announce("polite", C.deleted(row.name, row.accountLabel), `profiles:deleted:${row.key}`);
        void refresh().then(keepFocus);
        return;
      }
      if (outcome.kind === "step_up" && !retried) {
        setRemoval({ stage: "step_up", row, hold: outcome.hold, retried });
        return;
      }
      if (outcome.kind === "unknown") {
        // No answer: the delete may have happened. Read the list back rather than guess (E09-D06 §2.4),
        // and say where the outcome shows, as the step-up's own no-answer path does.
        setRemoval(null);
        pendingSeq.current += 1;
        announce(
          "polite",
          stepUpOutcomePending(C.title),
          `profiles:pending:${row.key}:${pendingSeq.current}`,
        );
        void refresh().then(keepFocus);
        return;
      }
      const code = outcome.kind === "refused" ? outcome.refusal.code : "step_up_required";
      sink.current.emit({ name: "profile.write_refused", operation: "delete", code });
      const failure =
        outcome.kind === "refused" ? deleteRefusalText(outcome.refusal) : C.notDeleted(code);
      if (outcome.kind !== "refused" || !isVersionConflict(outcome.refusal)) {
        setRemoval({ stage: "confirm", row, busy: false, failure });
        return;
      }
      // "reload to see the new version": Delete waits for the list read again, so the next press
      // sends the new version's tag, never the stale one
      setRemoval({ stage: "confirm", row, busy: true, failure });
      void refresh().then(() =>
        setRemoval((now) =>
          now?.stage === "confirm" && now.row.key === row.key ? { ...now, busy: false } : now,
        ),
      );
    },
    [refresh, keepFocus],
  );

  const confirmDelete = useCallback(
    async (opened: ProfileRow): Promise<void> => {
      const row = latest.current.find((r) => r.key === opened.key) ?? opened;
      setPriorFailures(0);
      setRemoval({ stage: "confirm", row, busy: true, failure: null });
      settle(row, await api.deleteProfile(row.profile), false);
    },
    [api, settle],
  );

  /**
   * A fresh challenge (A11Y-F-0010): the delete is submitted again as a new request (a new
   * `Idempotency-Key`); its `403 step_up_required` opens the new gate with the failures carried.
   * The one-cycle cap is kept: a renewal never resets `retried`.
   */
  const renew = useCallback(
    async (row: ProfileRow, retried: boolean, failures: number): Promise<void> => {
      setPriorFailures(failures);
      settle(row, await api.deleteProfile(row.profile), retried);
    },
    [api, settle],
  );

  const actions = useCallback(
    (row: ProfileRow): readonly MenuItem[] => [
      { id: "edit", label: C.edit, onSelect: () => void navigate(editorPath(row.profile)) },
      {
        id: "duplicate",
        label: C.duplicate,
        onSelect: () => void navigate(newProfilePath(row.accountId, row.key)),
      },
      {
        id: "delete",
        label: C.delete,
        danger: true,
        opensConfirm: true,
        onSelect: () => setRemoval({ stage: "confirm", row, busy: false, failure: null }),
      },
    ],
    [navigate],
  );

  const rows = load.kind === "ready" ? load.rows : [];
  return (
    <ScreenRoot>
      <PageHeader title={C.title} headingId={HEADING_ID} meta={C.defaultCeiling} />
      <Table
        caption={C.title}
        captionHidden
        columns={COLUMNS}
        rows={rows}
        rowKey={(r) => r.key}
        rowLabel={(r) => `${r.accountLabel} ${r.name}`}
        rowActions={actions}
        stickyFirstColumn
        stickyLastColumn
        loading={load.kind === "loading"}
        {...(load.kind === "failed" && {
          error: { message: C.loadFailed, onRetry: () => void refresh().then(keepFocus) },
        })}
        emptyState={
          // Accounts listed but none of their profiles readable: not "no accounts" (D06 open question)
          <EmptyState title={load.kind === "ready" && load.listed > 0 ? C.loadFailed : C.empty} />
        }
      />
      {removal?.stage === "confirm" ? (
        <ConfirmDialog
          open
          title={C.confirmDelete(removal.row.accountLabel, removal.row.name)}
          // labels are not unique (`22`): the served environment tells two "Main" accounts apart
          message={`${removal.row.accountLabel} · ${removal.row.environment}`}
          confirmLabel={C.delete}
          cancelLabel={C.cancel}
          confirmVariant="danger"
          busy={removal.busy}
          {...(removal.failure !== null && { failure: { message: removal.failure } })}
          fallbackFocusRef={heading}
          onConfirm={() => void confirmDelete(removal.row)}
          onCancel={() => setRemoval(null)}
        />
      ) : null}
      {removal?.stage === "step_up" ? (
        <StepUpChallengeGate
          key={removal.hold.challenge.challengeId}
          challenge={removal.hold.challenge}
          held={removal.hold.held}
          onResent={(response) => {
            const { row, hold } = removal;
            void api.readWrite(response, hold.held).then((outcome) => settle(row, outcome, true));
          }}
          readBack={refresh}
          outcomeWhere={C.title}
          onRenew={(failures) => void renew(removal.row, removal.retried, failures)}
          priorFailures={priorFailures}
        />
      ) : null}
    </ScreenRoot>
  );
}
