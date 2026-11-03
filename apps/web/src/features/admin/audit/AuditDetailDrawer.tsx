/**
 * SCR-136 Audit event detail (E42-S04; E42-D04 §5, D1, D14, AD-1 to AD-7): a non-modal CMP-046
 * drawer over the grid, focus on its `h2` "Record {id}" at open. No single-record operation exists,
 * so it renders the page's own `AuditEntry`: it fetches nothing and records nothing on open (CG-5;
 * QA AD-S04-N06), and an entry never changes, so it never goes stale.
 * - [Previous] and [Next] step through the loaded page (D14), T2 `admin.page_edge` at its ends;
 *   the page says the record each step shows (A-1135P2-11).
 * - The summary, then Who, What (the subject linked by the route table; `reason` keyed as AD-1
 *   says), Before / after (§6's full form), Request (`rec.correlation_none`, CG-4), Related (the
 *   three pivots to SCR-135 with that filter set, AD-6, which close the drawer; T2
 *   `admin.rate_limited` under AL-16),
 *   Integrity (the hashes with Copy, `rec.chain`, `recordLine`; `rec.after_break` in the danger
 *   treatment, AD-5) and the raw record, collapsed: CMP-068, its JSON built only when shown, and
 *   withheld with `rec.raw_flagged` when the redactor mirror finds a value under a secret name in
 *   any member it shows (AD-3).
 * - A Manager's projection (AD-7): the hidden fields read `rec.hidden`; Show raw record and the
 *   Copy beside session, IP and both hashes are T2 `rbac.owner_only` behind one notice under the
 *   header; the pivots open My activity's own route; the actor and an `/admin` subject are text.
 * - `rec.immutable` closes it: no control here edits, deletes or corrects anything (D9).
 */
import { useId, useMemo, useState, type CSSProperties, type JSX, type ReactNode } from "react";
import {
  AUDIT_ACTION_LABELS,
  AUDIT_DIFF_COPY,
  AUDIT_GRID_COPY,
  AUDIT_ROW_COPY,
  AuditDiff,
  Button,
  CopyableCodeBlock,
  CopyButton,
  Drawer,
  Icon,
  Link,
  auditDiffModel,
  formatRbacReason,
} from "@candleviewer/ui";
import { routerLink } from "../routerLink";
import type { AuditEntry, AuditView } from "./auditReads";
import { searchOf, type AuditFilters } from "./auditFilters";
import { AUDIT_COPY as COPY, num } from "./copy";
import type { RecordLine } from "./integrity";

/** R-360: SCR-135, and My activity at the same route for a Manager (BQ-8 (a)). */
export const AUDIT_LOG_PATH = "/admin/audit";
/** AD-6 (PROPOSED): "Entries around this time" is the entry's time ± 5 minutes. */
export const AROUND_MS = 5 * 60_000;

/** The link table (D01:462-467; the build plan's §4.3): a subject kind's route, ids encoded. */
const SUBJECT_ROUTES: Readonly<Record<string, (id: string) => string>> = {
  order: (id) => `/positions/order/${encodeURIComponent(id)}`, // R-132
  rule: (id) => `/rules/${encodeURIComponent(id)}`, // R-161
  user: (id) => `/admin/users/${encodeURIComponent(id)}`, // R-302 SCR-122
  exchange_account: (id) => `/admin/accounts/${encodeURIComponent(id)}`, // R-311 SCR-125
  feature_flag: () => "/admin/flags", // R-351 SCR-145
  backup: () => "/admin/backups", // R-355 SCR-146
};
/**
 * Whether the raw record is withheld (AD-3, C-12.6): the redactor mirror reads every member the raw
 * block shows, all of `detail` (`22` lets it carry members besides `before` and `after`) and each
 * served text, as values, whose embedded JSON it follows; the names of the entry's own members are
 * the contract's, never a recorded field (S-1135P2-d01).
 */
function rawRecordFlagged(record: AuditEntry): boolean {
  const shown = { record: Object.values(record) };
  return auditDiffModel({ ...record, detail: { after: shown } }).flagged;
}

/** A read-time pseudonym (CG-33): never a link. */
const DELETED_USER = /^deleted-user-[0-9a-f]{12}$/;

/** The subject's route, or none: an unmapped kind, and for a Manager an `/admin` screen, is text. */
export function subjectHref(entry: AuditEntry, view: AuditView): string | null {
  const { subject_type: kind, subject_id: id } = entry;
  if (kind === null || id === null || !Object.hasOwn(SUBJECT_ROUTES, kind)) return null;
  const route = SUBJECT_ROUTES[kind];
  const href = route === undefined ? null : route(id);
  if (href === null) return null;
  return view === "own" && href.startsWith("/admin") ? null : href;
}

/** The actor's SCR-122 link: the Owner's, for a live user id; a pseudonym or a system actor is text. */
export function actorHref(entry: AuditEntry, view: AuditView): string | null {
  if (view === "own" || entry.actor_user_id === null) return null;
  if (DELETED_USER.test(entry.actor_username ?? "")) return null;
  return `/admin/users/${encodeURIComponent(entry.actor_user_id)}`;
}

/** AD-1 (CG-29): a reason a person gave, rather than a code the server set. */
function reasonGiven(entry: AuditEntry): boolean {
  if (entry.action === "flags.change") return entry.detail.after?.["phase"] === "intent";
  if (entry.action.startsWith("maintenance.")) return true;
  return entry.action === "retention.purge" && entry.detail.before !== null;
}

/** The three pivots of AD-6, each the filter set it opens; a Manager's has no actor pivot (AD-7). */
export function relatedPivots(
  entry: AuditEntry,
  view: AuditView,
): readonly { readonly label: string; readonly filters: AuditFilters }[] {
  const pivots: { label: string; filters: AuditFilters }[] = [];
  if (view === "raw" && entry.actor_user_id !== null) {
    pivots.push({ label: COPY.rec.relatedActor, filters: { actor_user_id: entry.actor_user_id } });
  }
  if (entry.subject_id !== null) {
    const subject: AuditFilters = { subject_id: entry.subject_id };
    if (entry.subject_type !== null) subject.subject_type = entry.subject_type;
    pivots.push({ label: COPY.rec.relatedSubject, filters: subject });
  }
  const at = Date.parse(entry.ts);
  if (Number.isFinite(at)) {
    const iso = (ms: number): string => new Date(ms).toISOString().replace(".000Z", "Z");
    pivots.push({
      label: COPY.rec.relatedTime,
      filters: { from: iso(at - AROUND_MS), to: iso(at + AROUND_MS) },
    });
  }
  return pivots;
}

const two = (n: number): string => String(n).padStart(2, "0");

/** "yyyy-mm-dd hh:mm:ss.mmm UTC", or the served text when it is no date-time (§5 summary). */
function summaryTime(ts: string): string {
  const ms = Date.parse(ts);
  if (!Number.isFinite(ms)) return ts;
  const d = new Date(ms);
  const time = `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`;
  return `${d.toISOString().slice(0, 10)} ${time}.${String(d.getUTCMilliseconds()).padStart(3, "0")} UTC`;
}

/** D3: a write-ahead record reads Started or Intent, never its outcome. */
function resultWord(entry: AuditEntry): string {
  if (entry.reason === "started") return COPY.audit.resultStarted;
  if (entry.detail.after?.["phase"] === "intent") return COPY.audit.resultIntent;
  return AUDIT_ROW_COPY.outcome[entry.outcome];
}

/** The summary (§5): "Order submitted (orders.submit) · Success · Info · {time} UTC · LIVE". */
export function summaryLine(entry: AuditEntry): string {
  const label = Object.hasOwn(AUDIT_ACTION_LABELS, entry.action)
    ? AUDIT_ACTION_LABELS[entry.action]
    : undefined;
  const action = label === undefined ? entry.action : `${label} (${entry.action})`;
  const env =
    entry.environment === null || entry.environment === undefined
      ? COPY.labels.word.none
      : AUDIT_GRID_COPY.environments[entry.environment];
  return [
    action,
    resultWord(entry),
    AUDIT_ROW_COPY.severity[entry.severity],
    summaryTime(entry.ts),
    env,
  ].join(" · ");
}

const BODY: CSSProperties = { display: "grid", gap: "var(--space-stack-md)" };
const ROW: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-stack-sm)",
};
const H3: CSSProperties = {
  margin: 0,
  font: "var(--type-ui-heading-sm-font-weight) var(--type-ui-heading-sm-font-size) / var(--type-ui-heading-sm-line-height) var(--type-ui-heading-sm-font-family)",
};
const DL: CSSProperties = { margin: 0, display: "grid", gap: "var(--space-stack-sm)" };
const DD: CSSProperties = { margin: 0, ...ROW };
const LINE: CSSProperties = { margin: 0 };
const MONO: CSSProperties = {
  font: "var(--type-num-sm-font-weight) var(--type-num-sm-font-size) / var(--type-num-sm-line-height) var(--type-num-sm-font-family)",
  overflowWrap: "anywhere",
};
const DANGER: CSSProperties = { ...LINE, ...ROW, color: "var(--color-status-danger-strong)" };

export interface AuditDetailDrawerProps {
  /** The record shown; null closes the drawer. */
  readonly entry: AuditEntry | null;
  readonly view: AuditView;
  readonly onClose: () => void;
  /** The newer record in the loaded page; absent at its first row (T2 `admin.page_edge`). */
  readonly onPrevious?: (() => void) | undefined;
  /** The older record in the loaded page; absent at its last row. */
  readonly onNext?: (() => void) | undefined;
  /** The integrity line for this record (`recordLine`, AD-1, AD-5). */
  readonly integrity: RecordLine;
  /** AL-16: the pivots are T2 `admin.rate_limited`, described by the page's one notice. */
  readonly pivotsBlocked?: { readonly reason: string; readonly reasonId: string } | undefined;
  /** A T2 pivot was pressed: the page re-shows its notice's reason, once, politely. */
  readonly onBlockedPivot?: (() => void) | undefined;
  /** A pivot is followed: the page closes the drawer, its record not in the new set (C-1135P2-13). */
  readonly onPivot?: ((filters: AuditFilters) => void) | undefined;
}

/** A term and its value, a `dt` / `dd` pair. */
function Field({ term, children }: { term: string; children: ReactNode }): JSX.Element {
  return (
    <div>
      <dt>{term}</dt>
      <dd style={DD}>{children}</dd>
    </div>
  );
}

/** A term inside a name ("Copy session"): its first letter lowered, an acronym ("IP") kept. */
const termInLine = (term: string): string =>
  term === term.toUpperCase() ? term : `${term.charAt(0).toLowerCase()}${term.slice(1)}`;

/** A value with its Copy, or for a Manager `rec.hidden` and a T2 Copy (AD-7). */
function Copyable({
  value,
  term,
  hidden,
  gate,
}: {
  readonly value: string | null | undefined;
  readonly term: string;
  readonly hidden: boolean;
  readonly gate: { readonly reason: string; readonly reasonId: string } | null;
}): JSX.Element {
  const copyLabel = `${COPY.labels.act.copy} ${termInLine(term)}`;
  if (hidden) {
    return (
      <>
        <span>{COPY.rec.hidden}</span>
        {gate === null ? null : (
          <Button variant="ghost" disabledReason={gate.reason} disabledReasonId={gate.reasonId}>
            {copyLabel}
          </Button>
        )}
      </>
    );
  }
  if (value === null || value === undefined || value === "") {
    return <span>{AUDIT_DIFF_COPY.none}</span>;
  }
  return (
    <>
      <span style={MONO}>{value}</span>
      <CopyButton value={value} label={copyLabel} />
    </>
  );
}

/** A pivot to SCR-135 with its filter set (AD-6); under AL-16 a T2 link that opens nothing. */
function Pivot({
  label,
  filters,
  blocked,
  onBlocked,
  onFollow,
}: {
  readonly label: string;
  readonly filters: AuditFilters;
  readonly blocked: { readonly reason: string; readonly reasonId: string } | undefined;
  readonly onBlocked: (() => void) | undefined;
  readonly onFollow: ((filters: AuditFilters) => void) | undefined;
}): JSX.Element {
  const to = `${AUDIT_LOG_PATH}?${searchOf(filters)}`;
  if (blocked === undefined) {
    return (
      <Link to={to} as={routerLink} onClick={() => onFollow?.(filters)}>
        {label}
      </Link>
    );
  }
  // T2 (§12.1): the link keeps its role, its full label and its Tab stop, with the `lock` first
  const RouterAnchor = routerLink;
  return (
    <RouterAnchor
      to={to}
      className="cv-link"
      aria-disabled="true"
      aria-describedby={blocked.reasonId}
      onClick={(event) => {
        event.preventDefault();
        onBlocked?.();
      }}
    >
      <Icon name="lock" decorative={false} label="Not available" /> {label}
    </RouterAnchor>
  );
}

export function AuditDetailDrawer({
  entry,
  view,
  onClose,
  onPrevious,
  onNext,
  integrity,
  pivotsBlocked,
  onBlockedPivot,
  onPivot,
}: AuditDetailDrawerProps): JSX.Element {
  const own = view === "own";
  const ownNoticeId = useId();
  const edgeId = useId();
  const rawId = useId();
  const [rawOpen, setRawOpen] = useState<number | null>(null);
  // The record stays drawn while the drawer slides out, and CMP-046 returns focus to its opener.
  const [shown, setShown] = useState<AuditEntry | null>(entry);
  if (entry !== null && entry !== shown) setShown(entry);
  const record = entry ?? shown;
  const model = useMemo(() => (record === null ? null : auditDiffModel(record)), [record]);
  const rawFlagged = useMemo(() => record !== null && rawRecordFlagged(record), [record]);
  const showRaw = record !== null && rawOpen === record.id;
  // built only while shown, once per record: the page re-renders every second under a `429`
  const rawJson = useMemo(
    () => (showRaw && record !== null ? JSON.stringify(record, null, 2) : ""),
    [showRaw, record],
  );
  if (record === null || model === null) {
    return <Drawer open={false} onOpenChange={onClose} title="" modal={false} />;
  }
  const gate = own
    ? {
        reason: formatRbacReason("rbac.owner_only", { verb: COPY.ownerOnlyVerbs.raw }),
        reasonId: ownNoticeId,
      }
    : null;
  const atEdge = onPrevious === undefined || onNext === undefined;
  const step = (go: (() => void) | undefined) =>
    go === undefined
      ? { disabledReason: COPY.admin.pageEdge, disabledReasonId: edgeId }
      : {
          onKeyDown: (event: { repeat: boolean; key: string; preventDefault: () => void }) => {
            if (event.repeat && (event.key === "Enter" || event.key === " "))
              event.preventDefault();
          },
          onClick: go,
        };
  const subject = [
    record.subject_type,
    own ? record.subject_id : (record.subject_label ?? record.subject_id),
  ]
    .filter((part): part is string => part !== null && part !== undefined)
    .join(" · ");
  const subjectLink = subjectHref(record, view);
  const actorLink = actorHref(record, view);
  const reasonTerm = reasonGiven(record) ? COPY.rec.reasonGiven : COPY.rec.reasonCode;
  return (
    <Drawer
      open={entry !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={COPY.labels.h.record(num(record.id))}
      modal={false}
    >
      <div style={BODY} data-record={record.id}>
        <div style={ROW}>
          <Button variant="secondary" {...step(onPrevious)}>
            {COPY.labels.page.previous}
          </Button>
          <Button variant="secondary" {...step(onNext)}>
            {COPY.labels.page.next}
          </Button>
        </div>
        {atEdge ? (
          <p id={edgeId} style={LINE}>
            {COPY.admin.pageEdge}
          </p>
        ) : null}
        {gate === null ? null : (
          <p id={ownNoticeId} style={LINE}>
            {gate.reason}
          </p>
        )}
        <p style={LINE}>{summaryLine(record)}</p>
        <section>
          <h3 style={H3}>{COPY.labels.h.who}</h3>
          <dl style={DL}>
            <Field term={COPY.labels.col.actor}>
              {actorLink === null ? (
                <span>{record.actor_username ?? COPY.labels.word.none}</span>
              ) : (
                <Link to={actorLink} as={routerLink}>
                  {record.actor_username ?? record.actor_user_id ?? ""}
                </Link>
              )}
            </Field>
            <Field term={COPY.labels.col.role}>
              <span>{COPY.rec.role}</span>
            </Field>
            <Field term={COPY.labels.term.session}>
              <Copyable
                value={record.session_id}
                term={COPY.labels.term.session}
                hidden={own}
                gate={gate}
              />
            </Field>
            <Field term={COPY.labels.col.ip}>
              <Copyable value={record.ip} term={COPY.labels.col.ip} hidden={own} gate={gate} />
            </Field>
            <Field term={COPY.labels.term.userAgent}>
              <span>{own ? COPY.rec.hidden : (record.user_agent ?? COPY.rec.agentNone)}</span>
            </Field>
          </dl>
        </section>
        <section>
          <h3 style={H3}>{COPY.labels.h.what}</h3>
          <dl style={DL}>
            <Field term={COPY.labels.filter.subject}>
              {subject === "" ? (
                <span>{COPY.labels.word.none}</span>
              ) : subjectLink === null ? (
                <span>{subject}</span>
              ) : (
                <Link to={subjectLink} as={routerLink}>
                  {subject}
                </Link>
              )}
            </Field>
            <Field term={reasonTerm}>
              <span>{own ? COPY.rec.hidden : (record.reason ?? AUDIT_DIFF_COPY.none)}</span>
            </Field>
          </dl>
        </section>
        <section>
          <h3 style={H3}>{COPY.labels.h.beforeAfter}</h3>
          <AuditDiff model={model} form="full" />
        </section>
        <section>
          <h3 style={H3}>{COPY.labels.h.request}</h3>
          <dl style={DL}>
            <Field term={COPY.labels.term.requestId}>
              <Copyable
                value={record.request_id}
                term={COPY.labels.term.requestId}
                hidden={false}
                gate={null}
              />
            </Field>
          </dl>
          <p style={LINE}>{COPY.rec.correlationNone}</p>
        </section>
        <section>
          <h3 style={H3}>{COPY.labels.h.related}</h3>
          <ul style={{ ...DL, listStyle: "none", padding: 0 }}>
            {relatedPivots(record, view).map((pivot) => (
              <li key={pivot.label}>
                <Pivot
                  label={pivot.label}
                  filters={pivot.filters}
                  blocked={pivotsBlocked}
                  onBlocked={onBlockedPivot}
                  onFollow={onPivot}
                />
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3 style={H3}>{COPY.labels.h.integrity}</h3>
          <dl style={DL}>
            <Field term={COPY.labels.term.entryHash}>
              <Copyable
                value={record.entry_hash}
                term={COPY.labels.term.entryHash}
                hidden={own}
                gate={gate}
              />
            </Field>
            <Field term={COPY.labels.term.prevHash}>
              <Copyable
                value={record.prev_hash}
                term={COPY.labels.term.prevHash}
                hidden={own}
                gate={gate}
              />
            </Field>
          </dl>
          <p style={LINE}>{COPY.rec.chain}</p>
          {integrity.tone === "danger" ? (
            <p style={DANGER} data-line={integrity.key}>
              <Icon name="danger" />
              {integrity.text}
            </p>
          ) : (
            <p style={LINE} data-line={integrity.key}>
              {integrity.text}
            </p>
          )}
        </section>
        <section>
          <h3 style={H3}>{COPY.labels.h.raw}</h3>
          {!own && rawFlagged ? (
            <p style={LINE} data-line="rec.raw_flagged">
              {COPY.rec.rawFlagged}
            </p>
          ) : (
            <>
              <Button
                variant="secondary"
                aria-expanded={showRaw}
                aria-controls={showRaw ? rawId : undefined}
                {...(gate === null
                  ? { onClick: () => setRawOpen(showRaw ? null : record.id) }
                  : { disabledReason: gate.reason, disabledReasonId: gate.reasonId })}
              >
                {COPY.rec.rawShow}
              </Button>
              {showRaw && gate === null ? (
                <CopyableCodeBlock
                  id={rawId}
                  code={rawJson}
                  language="json"
                  label={COPY.labels.h.raw}
                  maxHeight="20rem"
                />
              ) : null}
            </>
          )}
        </section>
        <p style={LINE}>{COPY.rec.immutable}</p>
      </div>
    </Drawer>
  );
}
