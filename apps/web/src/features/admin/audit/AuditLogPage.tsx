/**
 * SCR-135 Audit log (E42-S04; E42-D04 §4, D4 to D9, AL-1 to AL-9, AL-15 to AL-17, AL-25 to AL-28), one page
 * for two views: the Owner's raw log at R-360 inside CMP-087, and a Manager's own actions, "My
 * activity", at the same route in the plain shell (`own`, the orchestrator's BQ-8 (a)).
 * - Top to bottom: CMP-088 "Audit log" with `meta.asof` and `audit.marker`; the AL-16 line and its
 *   one notice; CMP-174; the new-entries pill (D5); the CMP-049 grid of CMP-173 rows; the paging
 *   lines and CMP-053; `audit.append_only`. SCR-136 comes with its drawer; the tamper banner, the
 *   footer and the view-as notice with Run tamper check.
 * - The filter set is URL state (D04 §4 Filters): a change pushes a new location, a read follows,
 *   and Environment re-filters the loaded rows and reads nothing (D7). The cursor never is.
 * - Every read is the page store's (`useAuditPage`): this page only renders its state and makes no
 *   request of its own, and only `GET`s on mount (the source scan `noUnchallengedStepUp.test.tsx`
 *   walks R-360 too).
 * - Lines are said once, politely, through the shell's announcer (`usePageVoice`). A T2 press is its
 *   own polite line there (G-T2.3: the shell's gated announcement is a no-op, so the page routes its
 *   atoms' refusals; A-1135P2-02).
 * - One column that never grows past the canvas, so the page reflows at 200 % and 400 % (AL-28),
 *   and its own stacking context, so the grid's sticky header stays under the page's overlays (the
 *   kit-wide `.cv-table { isolation: isolate }` comes with E42-S02's PR A).
 * - An Owner's `403 forbidden` withdraws the area: the page shows CMP-089 withdrawn and reads
 *   nothing more. `onWithdrawn` is the typed hook for the shared store's `deny()` (#1023's, as
 *   ruled), which unmounts the band as an admin read's refusal does; nothing passes it yet.
 * - No control here edits, deletes, corrects, archives or repairs a record (D9).
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
} from "react";
import { useLocation, useNavigate } from "react-router";
import {
  AUDIT_ACTION_LABELS,
  AuditFilterBar,
  Button,
  EmptyState,
  ErrorState,
  GatedAnnounceProvider,
  PageHeader,
  Pagination,
  type AuditActionOption,
  type AuditActorOption,
  type AuditFilterField,
} from "@candleviewer/ui";
import type { Me, ShellState } from "../../../shell/bootstrap/store";
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import { useShellSelector } from "../../../shell/useShellSelector";
import { announce } from "../../app-shell/announcer";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { AdminDenied } from "../shell/AdminDenied";
import { AuditGrid, diffRowId } from "./AuditGrid";
import { filtersKey, isFiltered, parseFilters, searchOf, type AuditFilters } from "./auditFilters";
import { NEW_CAP, pagerOf, useAuditPage, type AuditPageState } from "./auditPageStore";
import type { AuditEntry, AuditView, FieldError } from "./auditReads";
import { AUDIT_COPY as COPY, utc } from "./copy";
import { usePageVoice } from "./pageVoice";
import { useAuditViewAs } from "./viewAs";

/** E42-Q03's measures (CG-25): mount to the first page drawn, and a filter change to its rows. */
export const FIRST_PAGE_MEASURE = "cv_audit_first_page_ms";
export const FILTER_MEASURE = "cv_audit_filter_roundtrip_ms";

const PAGE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr)",
  gap: "var(--space-stack-md)",
  minWidth: 0,
  isolation: "isolate",
};
const LINE: CSSProperties = { margin: 0 };
const NOTICE: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };

const selectUserId = (state: ShellState): string | null => {
  // a /me without `user` (a stub, a malformed answer) has no id: nothing is left out of the count
  const user: Partial<Me["user"]> | undefined = state.me?.user;
  return user?.id ?? null;
};

const report = (detail: Readonly<Record<string, unknown>>): void => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

/** A press's own polite line, never one already said: each press is an occasion of its own. */
let presses = 0;
function sayPress(text: string): void {
  presses += 1;
  announce("polite", text, `audit:press:${presses}`);
}

function measure(name: string, start: number): void {
  try {
    performance.measure(name, { start, end: performance.now() });
  } catch {
    // a runtime without User Timing Level 3 records nothing
  }
}

/** A `422`'s field errors as CMP-174 shows them (AL-17): `to` and `ip` by §14, the rest PROPOSED. */
export function fieldErrorsOf(
  errors: readonly FieldError[],
): Readonly<Partial<Record<AuditFilterField, string>>> | undefined {
  const out: Partial<Record<AuditFilterField, string>> = {};
  for (const { field } of errors) {
    if (field === "to" || field === "from") out[field] ??= COPY.audit.errRange;
    else if (field === "ip") out.ip ??= COPY.audit.errIp;
    else if (isFilterField(field)) out[field] ??= COPY.audit.errValue;
  }
  return Object.keys(out).length === 0 ? undefined : out;
}

const FILTER_FIELDS: readonly string[] = [
  "actor_user_id",
  "ip",
  "action",
  "subject_type",
  "subject_id",
  "outcome",
  "severity",
  "from",
  "to",
  "q",
  "environment",
];
const isFilterField = (field: string): field is AuditFilterField => FILTER_FIELDS.includes(field);

/** The actors the loaded page holds (no user list is served, BQ-3), each once. */
function actorsOf(rows: readonly AuditEntry[]): readonly AuditActorOption[] {
  const seen = new Map<string, string>();
  for (const e of rows) {
    if (e.actor_user_id !== null && !seen.has(e.actor_user_id)) {
      seen.set(e.actor_user_id, e.actor_username ?? e.actor_user_id);
    }
  }
  return [...seen].map(([id, label]) => ({ id, label }));
}

/** The labelled codes and the codes the page holds (CG-3), each once. */
function actionsOf(rows: readonly AuditEntry[]): readonly AuditActionOption[] {
  const codes = new Set([...Object.keys(AUDIT_ACTION_LABELS), ...rows.map((e) => e.action)]);
  return [...codes].sort().map((code) => {
    const label = Object.hasOwn(AUDIT_ACTION_LABELS, code) ? AUDIT_ACTION_LABELS[code] : undefined;
    return label === undefined ? { code } : { code, label };
  });
}

/** The seconds left until `until`, ticking once a second: shown, never announced (§12). */
function useSecondsLeft(until: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (until === null) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(id);
  }, [until]);
  return until === null ? 0 : Math.max(0, Math.ceil((until - now) / 1_000));
}

/** A read's `Retry-After` as the absolute time `audit.error` names, from when it was refused. */
function retryAt(state: AuditPageState, at: number): number | null {
  const error = state.error;
  if (error === null || error.kind !== "refused" || error.retryAfterS === undefined) return null;
  return at + error.retryAfterS * 1_000;
}

export interface AuditLogPageProps {
  /** `raw`: the Owner's log in CMP-087; `own`: a Manager's My activity, the plain shell. */
  readonly view: AuditView;
  /** Called once when an Owner's `403 forbidden` withdraws the area (the shared store's seam). */
  readonly onWithdrawn?: ((refId: string | undefined) => void) | undefined;
}

/**
 * SCR-135 inside its own gated announcement: the shell's is a no-op (the surfaces own it, G-T2.3),
 * so a T2 press anywhere on the page or in SCR-136 says its reason here, once per press.
 */
export function AuditLogPage(props: AuditLogPageProps): JSX.Element {
  return (
    <GatedAnnounceProvider announce={sayPress}>
      <AuditLogScreen {...props} />
    </GatedAnnounceProvider>
  );
}

function AuditLogScreen({ view, onWithdrawn }: AuditLogPageProps): JSX.Element {
  const own = view === "own";
  const location = useLocation();
  const navigate = useNavigate();
  const say = usePageVoice();
  const ownUserId = useShellSelector(selectUserId);
  const viewAs = useAuditViewAs();
  const parsed = useMemo(() => parseFilters(location.search, view), [location.search, view]);
  const { state, store } = useAuditPage(parsed.filters, {
    view,
    ownUserId,
    viewAs: viewAs !== null,
  });
  const denied = state.denied;

  const prefix = useId();
  const limitedNoticeId = useId();
  const endLineId = useId();
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set());

  const filtered = isFiltered(parsed.filters);
  const pager = pagerOf(state);
  const limited = state.phase === "limited";
  const rateLimited = limited ? COPY.admin.rateLimited : undefined;

  // The shown page's set, which the stable callbacks read.
  const shownKey = useRef(state.page?.key ?? null);
  useEffect(() => {
    shownKey.current = state.page?.key ?? null;
  });
  const onExpandedChange = useCallback((id: number, open: boolean): void => {
    setExpanded((now) => {
      const next = new Set(now);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  // Focus moves to row 1 once a pager press, the pill or Clear filters has landed its
  // page; a read that fails or is refused leaves it where it was (§4 Keys). `landed: -1` is a set
  // whose rows are shown already (only Environment cleared, D7): row 1 as soon as the bar clears.
  const pendingFocus = useRef<{ readonly key: string; readonly landed: number } | null>(null);
  const focusRow = useCallback(
    (id: number): void => {
      document.getElementById(`${diffRowId(prefix, id)}-toggle`)?.focus();
    },
    [prefix],
  );
  useEffect(() => {
    const want = pendingFocus.current;
    if (want === null || state.key !== want.key || state.reading !== null) return;
    if (want.landed < 0 && isFiltered(state.filters)) return; // the bar has not cleared yet
    pendingFocus.current = null;
    const first = state.rows[0];
    if (state.landed > want.landed && first !== undefined) focusRow(first.id);
  }, [state.key, state.reading, state.landed, state.rows, state.filters, focusRow]);
  useEffect(() => {
    // another set took over before the wanted one landed: nothing waits for it (C-1135P2-14)
    if (pendingFocus.current !== null && pendingFocus.current.key !== state.key) {
      pendingFocus.current = null;
    }
  }, [state.key]);
  const press = (send: () => boolean): void => {
    const at = { key: state.key, landed: state.landed };
    if (send()) pendingFocus.current = at;
  };
  const newAtPress = useRef(0);
  const onPill = (): void => {
    newAtPress.current = state.newCount;
    press(store.newest);
  };

  const applyFilters = (next: AuditFilters): void => {
    const search = searchOf(next);
    if (`?${search}` === location.search || (search === "" && location.search === "")) return;
    void navigate({ pathname: location.pathname, search: search === "" ? "" : `?${search}` });
  };
  const landedRef = useRef(state.landed);
  useEffect(() => {
    landedRef.current = state.landed;
  });
  const { pathname, search } = location;
  const clearFilters = useCallback((): void => {
    if (search === "") return;
    const cleared = filtersKey({}, view);
    // only Environment set: no read follows (D7), the rows are there (C-1135P2-10)
    const landed = shownKey.current === cleared ? -1 : landedRef.current;
    pendingFocus.current = { key: cleared, landed };
    void navigate({ pathname, search: "" });
  }, [pathname, search, navigate, view]);

  // E42-Q03's two measures: the first page drawn, and each filter change's rows.
  const mountedAt = useRef<number | null>(null);
  const filterAt = useRef<number | null>(null);
  const lastKey = useRef(state.key);
  useEffect(() => {
    mountedAt.current ??= performance.now();
  }, []);
  useEffect(() => {
    if (state.key === lastKey.current) return;
    lastKey.current = state.key;
    filterAt.current = performance.now();
  }, [state.key]);

  // The page's lines, said once each (§12), and its measures, as a page lands.
  const landedSaid = useRef(0);
  useEffect(() => {
    const { landed, landedBy, page, rows } = state;
    if (landed === 0 || landed === landedSaid.current || page === null) return;
    landedSaid.current = landed;
    if (landed === 1 && mountedAt.current !== null) measure(FIRST_PAGE_MEASURE, mountedAt.current);
    if (landedBy === "filter" && filterAt.current !== null) {
      measure(FILTER_MEASURE, filterAt.current);
      filterAt.current = null;
    }
    if (landedBy === "newest" && newAtPress.current > 0) {
      say(COPY.audit.newLoaded(newAtPress.current), `audit:new-loaded:${landed}`);
      newAtPress.current = 0;
    }
    if (landedBy === "older" && !page.body.meta.has_more && rows.length > 0) {
      say(COPY.audit.end(filtered), `audit:end:${landed}`);
    }
    if (rows.length === 0) {
      say(own ? COPY.audit.ownNoMatch : COPY.audit.noMatch, `audit:empty:${landed}`);
      if (filtered) report({ name: "empty_state_shown", surface: "SCR-135", reason: "filtered" });
    } else if (landedBy === "filter" || (landedBy === "first" && filtered)) {
      say(COPY.audit.count(rows.length), `audit:count:${landed}`);
    }
  }, [state, filtered, own, say]);
  // Environment re-filters the loaded rows (D7): the rows shown, said once, never a total.
  const environment = state.filters.environment;
  const lastEnvironment = useRef(environment);
  useEffect(() => {
    if (environment === lastEnvironment.current) return;
    lastEnvironment.current = environment;
    if (state.page !== null && state.reading === null) {
      say(COPY.audit.count(state.rows.length), `audit:count:${state.landed}:${environment ?? ""}`);
    }
  }, [environment, state.page, state.reading, state.rows, state.landed, say]);
  // The pill appears: its words once per head (AL-8).
  useEffect(() => {
    if (state.newCount > 0) {
      say(COPY.audit.newN(state.newCount, state.newCount >= NEW_CAP), `audit:new:${state.landed}`);
    }
  }, [state.newCount, state.landed, say]);
  // A read that failed (AL-15), was limited (AL-16) or lost its cursor (AL-17): its line, once.
  const [errorAt, setErrorAt] = useState(() => Date.now());
  const error = state.error;
  const lastError = useRef<AuditPageState["error"]>(null);
  useEffect(() => {
    // once per error, by its identity (§12): a later change to the page says nothing more
    if (error === null || error === lastError.current) return;
    lastError.current = error;
    newAtPress.current = 0; // a failed pill read loaded nothing new (C-1135P2-14)
    const at = Date.now();
    setErrorAt(at);
    if (state.phase === "failed" && state.denied === null) {
      const retry = retryAt(state, at);
      say(COPY.audit.error(retry === null ? null : utc.hms(retry)), `audit:error:${at}`);
    }
  }, [error, state, say]);
  const limitedUntil = state.limitedUntil;
  const secondsLeft = useSecondsLeft(limited ? limitedUntil : null);
  useEffect(() => {
    if (limitedUntil === null) return;
    const seconds = Math.max(0, Math.ceil((limitedUntil - Date.now()) / 1_000));
    say(COPY.audit.limited(utc.hms(limitedUntil), seconds), `audit:limited:${limitedUntil}`);
  }, [limitedUntil, say]);
  useEffect(() => {
    if (state.cursorLost) say(COPY.audit.cursorLost, `audit:cursor-lost:${state.landed}`);
  }, [state.cursorLost, state.landed, say]);
  // AL-16's window ended on a refused first or filter read: nothing was loaded, and [Retry]
  // sends it (C-1135P2-04). Said once per window.
  const limitEnded = state.phase === "failed" && error?.kind === "refused" && error.status === 429;
  const lastWindow = useRef(0);
  useEffect(() => {
    if (limitedUntil !== null) lastWindow.current = limitedUntil;
  }, [limitedUntil]);
  useEffect(() => {
    if (limitEnded) say(COPY.audit.limitEnded, `audit:limit-ended:${lastWindow.current}`);
  }, [limitEnded, say]);
  // A crafted link's dropped filter (AL-26): its line, said once.
  const droppedOwn = own && parsed.dropped.length > 0;
  useEffect(() => {
    if (droppedOwn) say(COPY.audit.ownFilter, `audit:own-filter:${location.search}`);
  }, [droppedOwn, location.search, say]);

  // The withdrawn area (SCR-154 N-2): the shared store's seam, called once.
  const reported = useRef(false);
  useEffect(() => {
    if (denied === null || reported.current) return;
    reported.current = true;
    onWithdrawn?.(denied.refId);
  }, [denied, onWithdrawn]);

  const pageRows = state.rows;
  const actorOptions = useMemo(() => actorsOf(pageRows), [pageRows]);
  const actionOptions = useMemo(() => actionsOf(pageRows), [pageRows]);
  const errors = useMemo(() => fieldErrorsOf(state.fieldErrors), [state.fieldErrors]);

  const noPage = state.page === null;
  const firstFailed = noPage && state.phase === "failed" && error !== null;
  const errorLine =
    state.phase === "failed" && error !== null ? (
      <ErrorState
        form="inline"
        live="off"
        message={
          limitEnded
            ? COPY.audit.limitEnded
            : COPY.audit.error(
                retryAt(state, errorAt) === null ? null : utc.hms(retryAt(state, errorAt) ?? 0),
              )
        }
        retry={{ label: COPY.labels.act.retry, onClick: () => press(store.retry) }}
      />
    ) : null;
  const emptyState = useMemo(() => {
    if (state.page === null || state.rows.length > 0) return null;
    return (
      <EmptyState
        variant="filtered-empty"
        headingLevel={2}
        title={own ? COPY.audit.ownNoMatch : COPY.audit.noMatch}
        {...(filtered
          ? {
              actions: [
                { label: COPY.labels.filter.clear, onClick: clearFilters, variant: "secondary" },
              ] as const,
            }
          : {})}
      />
    );
  }, [state.page, state.rows, own, filtered, clearFilters]);
  // No page read yet (limited, refused): no rows and no claim of none, never an empty list (AL-15)
  const gridEmpty = firstFailed ? errorLine : noPage ? <></> : emptyState;

  if (denied !== null) return <AdminDenied refId={denied.refId} />;

  return (
    <ScreenRoot>
      <div style={PAGE} data-view={view}>
        <PageHeader
          title={own ? COPY.labels.h.myActivity : COPY.labels.h.auditLog}
          meta={noPage ? COPY.meta.none : COPY.meta.asOf(utc.hms(state.page?.at ?? 0))}
          marker={COPY.audit.marker}
        />
        {own ? <p style={LINE}>{COPY.audit.ownOnly}</p> : null}
        {limited && limitedUntil !== null ? (
          <div>
            <p style={LINE}>{COPY.audit.limited(utc.hms(limitedUntil), secondsLeft)}</p>
            <p id={limitedNoticeId} style={NOTICE}>
              {COPY.admin.rateLimited}
            </p>
          </div>
        ) : null}
        <AuditFilterBar
          filters={parsed.filters}
          onChange={applyFilters}
          actorOptions={actorOptions}
          actionOptions={actionOptions}
          view={view}
          environmentScope="page"
          {...(rateLimited === undefined
            ? {}
            : { blockedReason: rateLimited, blockedReasonId: limitedNoticeId })}
          {...(errors === undefined ? {} : { errors })}
        />
        {own && parsed.dropped.length > 0 ? <p style={LINE}>{COPY.audit.ownFilter}</p> : null}
        {state.newCount > 0 && !noPage ? (
          <div>
            <Button
              variant="secondary"
              onKeyDown={(event) => {
                if (event.repeat && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                }
              }}
              {...(rateLimited === undefined
                ? { onClick: onPill }
                : { disabledReason: rateLimited, disabledReasonId: limitedNoticeId })}
            >
              {COPY.audit.newN(state.newCount, state.newCount >= NEW_CAP)}
            </Button>
          </div>
        ) : null}
        {state.slow && state.reading !== null ? <p style={LINE}>{COPY.audit.slow}</p> : null}
        <AuditGrid
          rows={pageRows}
          expanded={expanded}
          view={view}
          idPrefix={prefix}
          onExpandedChange={onExpandedChange}
          loading={noPage && (state.phase === "loading" || state.phase === "idle")}
          emptyState={gridEmpty}
        />
        {state.cursorLost ? (
          <div>
            <p style={LINE}>{COPY.audit.cursorLost}</p>
            <Button variant="secondary" onClick={() => press(store.newest)}>
              {COPY.labels.page.newest}
            </Button>
          </div>
        ) : null}
        {!noPage && pager.atOldest && pageRows.length > 0 ? (
          <p id={endLineId} style={LINE}>
            {COPY.audit.end(filtered)}
          </p>
        ) : null}
        {!noPage && !firstFailed ? errorLine : null}
        {noPage ? null : (
          <Pagination
            onNewest={() => press(store.newest)}
            onNewer={() => press(store.newer)}
            onOlder={() => press(store.older)}
            {...(pager.atNewest ? { newerReason: COPY.admin.newest } : {})}
            {...(pager.atOldest
              ? {
                  olderReason: COPY.admin.oldest(filtered),
                  ...(pageRows.length > 0 ? { olderReasonId: endLineId } : {}),
                }
              : {})}
            {...(rateLimited === undefined
              ? {}
              : { blockedReason: rateLimited, blockedReasonId: limitedNoticeId })}
            labels={{
              newest: COPY.labels.page.newest,
              newer: COPY.labels.page.newer,
              older: COPY.labels.page.older,
            }}
          />
        )}
        <p style={LINE}>{COPY.audit.appendOnly}</p>
      </div>
    </ScreenRoot>
  );
}
