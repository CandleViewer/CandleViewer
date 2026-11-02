import type { generated } from "@candleviewer/protocol";
import type { JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";
import type { LinkRoute } from "./Link.js";

type AuditEntry = generated.rest.components["schemas"]["AuditEntry"];

/**
 * The words a compact row reads, keyed as E42-D04 §14 keys them: `labels.word.*` for severity (D2) and
 * outcome (D3), `audit.result_started` and `audit.result_intent` for a write-ahead record, and the "—" of an
 * absent actor. Times read in UTC with "UTC" after them (E42-D03 §1, Clocks).
 */
export const AUDIT_ROW_COPY = {
  outcome: { success: "Success", failure: "Failure", denied: "Denied" },
  severity: {
    critical: "Critical",
    error: "Error",
    warning: "Warning",
    info: "Info",
    debug: "Debug",
  },
  started: "Started",
  intent: "Intent",
  none: "—",
  utc: "UTC",
} as const;

/**
 * E42-D04 §14 `labels.action.*`, paired with their codes as D02 and D04 pair them (D02:191-193, :244-245,
 * :445 "Order submitted" ↔ `orders.submit`; D04:399, :642-643; D03 §14). The registry holds codes, not labels
 * (CG-3), so any other code reads as itself.
 */
export const AUDIT_ACTION_LABELS: Readonly<Record<string, string>> = {
  "admin.area_entered": "Area entered",
  "admin.audit_export": "Audit log exported",
  "admin.audit_read": "Audit log viewed",
  "flags.change": "Flag changed",
  "maintenance.disabled": "Maintenance off",
  "maintenance.enabled": "Maintenance on",
  "orders.submit": "Order submitted",
};

/** The value under `key`, only when it is the table's own (never a prototype member). */
const lookup = (table: Readonly<Record<string, string>>, key: string): string | undefined =>
  Object.hasOwn(table, key) ? table[key] : undefined;

const pad = (n: number): string => String(n).padStart(2, "0");

/** An RFC 3339 date-time: a full date, a time to the second, any fraction, and an offset (`Z` or ±hh:mm). */
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

/**
 * `ts` (UTC, to the microsecond) as an instant to the millisecond, or `undefined` when it is not a full
 * date-time with an offset: the row never guesses a zone.
 */
function parseAuditTime(ts: string): Date | undefined {
  const match = DATE_TIME.exec(ts);
  if (match === null) return undefined;
  // `Date` reads a fraction of exactly three digits: cut or pad it to milliseconds.
  const fraction = match[1] ?? "";
  const ms = Date.parse(fraction === "" ? ts : ts.replace(fraction, `${fraction}00`.slice(0, 4)));
  return Number.isNaN(ms) ? undefined : new Date(ms);
}

/** "yyyy-mm-dd hh:mm:ss UTC" (E42-D03 §1, Clocks). */
function utcText(at: Date): string {
  const year = String(at.getUTCFullYear()).padStart(4, "0");
  const date = `${year}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
  const time = `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}:${pad(at.getUTCSeconds())}`;
  return `${date} ${time} ${AUDIT_ROW_COPY.utc}`;
}

/**
 * `ts` as "yyyy-mm-dd hh:mm:ss UTC", whatever offset it was written with. A value that is not a full
 * date-time with an offset is shown as served.
 */
export function formatAuditTime(ts: string): string {
  const at = parseAuditTime(ts);
  return at === undefined ? ts : utcText(at);
}

/**
 * The row's time: a `time` element whose `datetime` is the instant to the millisecond (HTML allows three
 * fraction digits at most, the server writes microseconds), or the served value as plain text when it is
 * not a date-time.
 */
function AuditTime({ ts }: { readonly ts: string }): JSX.Element {
  const at = parseAuditTime(ts);
  if (at === undefined) return <span className="cv-audit-row__time">{ts}</span>;
  return (
    <time className="cv-audit-row__time" dateTime={at.toISOString()}>
      {utcText(at)}
    </time>
  );
}

/** D3: a write-ahead record reads "Started" or "Intent", never its outcome; a terminal one its outcome word. */
function outcomeWord(entry: AuditEntry): string {
  if (entry.reason === "started") return AUDIT_ROW_COPY.started;
  if (entry.detail.after?.["phase"] === "intent") return AUDIT_ROW_COPY.intent;
  return lookup(AUDIT_ROW_COPY.outcome, entry.outcome) ?? entry.outcome;
}

/**
 * A field boundary, " · " as the copy deck writes it ("All times UTC · as of 14:02:11"): plain text, so the dot
 * is in the link's name too, and the spaces either side let a line break there.
 */
function Sep(): JSX.Element {
  return (
    <>
      {" "}
      <span className="cv-audit-row__sep">·</span>{" "}
    </>
  );
}

export interface AuditRowProps {
  /** One entry, the type generated from `22`; the row shows its fields and derives no value of its own. */
  readonly entry: generated.rest.components["schemas"]["AuditEntry"];
  /** `compact` only for now: a list item that links to SCR-136. The `row` variant ships with E42-S04. */
  readonly variant: "compact";
  /** SCR-136 for this entry: the host builds the route. Developer-built, never user input (CMP-021's rule). */
  readonly href: string;
  /** The app's router link, as CMP-021's `as`: `packages/ui` never imports a router. */
  readonly linkAs?: LinkRoute | undefined;
  /** Action labels by code, default `AUDIT_ACTION_LABELS`; a code without one reads as itself. */
  readonly actionLabels?: Readonly<Record<string, string>> | undefined;
}

/**
 * CMP-173 AuditRow, the compact variant (E42-D03 D9, D17, Appendix A; E42-D04 D2, D3): one entry as a list
 * item whose whole text is one link to SCR-136. It reads, in words and " · " apart: the time (UTC), the actor,
 * the action's label and code, the subject's label, the outcome and the severity; never a hash, an IP, a user
 * agent or the `detail` diff, so an elided or projected entry renders the same way. Error and critical are
 * "high": the octagon, the word in semibold and a `border.thick` rule; warning takes the triangle. Glyphs are
 * `aria-hidden`: the words carry the meaning. Render the rows inside `AuditRowList`.
 */
export function AuditRow({
  entry,
  variant,
  href,
  linkAs: Slot,
  actionLabels = AUDIT_ACTION_LABELS,
}: AuditRowProps): JSX.Element {
  const ring = useFocusRing();
  const label = lookup(actionLabels, entry.action);
  const subject = entry.subject_label ?? entry.subject_id;
  const severity = entry.severity;
  const glyph =
    severity === "critical" || severity === "error"
      ? "danger"
      : severity === "warning"
        ? "warning"
        : undefined;
  const content: ReactNode = (
    <span className="cv-audit-row__text">
      <AuditTime ts={entry.ts} />
      <Sep />
      <span className="cv-audit-row__actor">{entry.actor_username ?? AUDIT_ROW_COPY.none}</span>
      <Sep />
      {/* The brackets sit inside the code's span: an element edge never splits "(code)" in the name. */}
      <span className="cv-audit-row__action">
        {label === undefined ? null : <>{label} </>}
        <span className="cv-audit-row__code">
          {label === undefined ? entry.action : `(${entry.action})`}
        </span>
      </span>
      {subject === null ? null : (
        <>
          <Sep />
          <span className="cv-audit-row__subject">{subject}</span>
        </>
      )}
      <Sep />
      <span className="cv-audit-row__outcome">{outcomeWord(entry)}</span>
      <Sep />
      <span className="cv-audit-row__severity">
        {glyph === undefined ? null : (
          <span className="cv-audit-row__glyph" data-glyph={glyph}>
            <Icon name={glyph} />
          </span>
        )}
        {lookup(AUDIT_ROW_COPY.severity, severity) ?? severity}
      </span>
    </span>
  );
  const className = cx(ring.className, "cv-audit-row__link");
  return (
    <li className="cv-audit-row" data-cmp="CMP-173" data-variant={variant} data-severity={severity}>
      {Slot === undefined ? (
        <a className={className} href={href}>
          {content}
        </a>
      ) : (
        <Slot className={className} to={href}>
          {content}
        </Slot>
      )}
    </li>
  );
}

export interface AuditRowListProps {
  /** `AuditRow`s, newest first as the host read them. */
  readonly children: ReactNode;
  /** Names the list where nothing around it does (a tile's or a fieldset's heading usually does). */
  readonly "aria-label"?: string | undefined;
  readonly "aria-labelledby"?: string | undefined;
}

/** The list compact rows form (CMP-173 A11y): a plain `ul`, unmarked and unpadded, one row under another. */
export function AuditRowList({
  children,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: AuditRowListProps): JSX.Element {
  return (
    <ul className="cv-audit-rows" aria-label={ariaLabel} aria-labelledby={ariaLabelledBy}>
      {children}
    </ul>
  );
}
