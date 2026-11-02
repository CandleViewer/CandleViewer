import { cloneElement, useId, type JSX, type ReactElement, type ReactNode } from "react";
import {
  Button,
  Callout,
  ConfirmDialog,
  GatedAnnounceProvider,
  KeyValueRow,
  ProgressBar,
  RbacGate,
  Skeleton,
  Sparkline,
  SystemHealthTile,
  Table,
} from "@candleviewer/ui";
import "./connectivity.css";
import { AuditMarker, type AuditAction } from "./AuditMarker";
import { politeOnce } from "./announce";
import { COPY, SAVE_BUDGET } from "./copy";
import { NOT_CONNECTED, formatFigure } from "./format";
import type { RateBudgetRow } from "./rateBudget";
import { THRESHOLDS } from "./selectState";
import { STATES, toneOf, wordOf, type StateId } from "./states";
import { fill, parts, printable } from "./text";

type Slots = Readonly<Record<string, string | number>>;

const REQUESTS_PER_MINUTE = "requests per minute";

/** The summary strip's tile for one state: origin, word and sentences from the deck, glyph and tone from the register. */
const CLOCK_SLOT = /\{\d{1,2}:\d{2}:\d{2}\}/;

export function StateTile({
  id,
  label,
  slots,
  asOf,
  lastGoodAt,
}: {
  readonly id: StateId;
  readonly label: string;
  readonly slots?: Slots;
  readonly asOf?: number;
  readonly lastGoodAt?: number;
}): JSX.Element {
  const spec = STATES[id];
  const key = spec.copy;
  // S-17: the tile itself prints "last good {time}" from `lastGoodAt`, so the deck line that carries the clock
  // slot (found by its slot shape, not its words) is left out of the sentences.
  const sentences =
    key === null
      ? []
      : parts(key)
          .slice(1)
          .filter((l) => id !== "S-17" || !CLOCK_SLOT.test(l))
          .flatMap((l) => {
            const text = fill(l, slots);
            return text === null ? [] : [text];
          });
  const down = id === "S-17" ? "error" : id === "S-18" ? "unavailable" : null;
  return (
    <SystemHealthTile
      label={label}
      href="#connectivity"
      state={id === "S-13" ? "loading" : (down ?? "ready")}
      tone={toneOf(id)}
      {...(down === null
        ? { stateWord: spec.origin === null ? wordOf(id) : `${spec.origin} · ${wordOf(id)}` }
        : {})}
      {...(sentences.length === 0 ? {} : { detail: sentences.join(" ") })}
      {...(asOf === undefined ? {} : { asOf })}
      {...(lastGoodAt === undefined ? {} : { lastGoodAt })}
    />
  );
}

/** CMP-023 `meter`: stepped per sample, never animated; not drawn while the source is not served (§3.2). */
export function RateMeter({ row }: { readonly row: RateBudgetRow }): JSX.Element {
  const pct = row.utilisationPct;
  // Deliberate deviation (R-4): D09:226 asks for Headroom in the value text, but the reserve is not separable from a
  // served peak, so the text names peak and limit only; Headroom reads "Not connected yet" in the grid.
  if (pct === null) return <span>{NOT_CONNECTED}</span>;
  const text = `${formatFigure(row.peakUsedPerMinute, REQUESTS_PER_MINUTE)} of ${formatFigure(
    row.limitPerMinute,
    REQUESTS_PER_MINUTE,
  )}, peak`;
  return (
    <ProgressBar
      kind="meter"
      label={`${row.label}: ${COPY["W-10"]}`}
      value={pct}
      valueText={text}
      tone={pct >= THRESHOLDS.nearLimitPct ? "warning" : "default"}
    />
  );
}

/**
 * The per-account grid (CMP-049): the served rows only, one line per account (D09 §3.3). A figure not served reads
 * "Not connected yet", never 0; Headroom has no figure, the reserve not being separable from a peak (R-4).
 */
export function BudgetGrid({ rows }: { readonly rows: readonly RateBudgetRow[] }): JSX.Element {
  const head = parts("W-08");
  return (
    <div className="cv-connectivity__grid">
      <Table
        caption={COPY["W-07"]}
        captionHidden
        rows={rows}
        rowKey={(r) => r.key}
        density="comfortable"
        columns={[
          {
            id: "account",
            header: head[1] ?? "Account",
            cell: (r) => (
              <>
                {r.label} <span className="cv-connectivity__sub">{COPY["W-10"]}</span>
              </>
            ),
          },
          {
            id: "limit",
            header: head[2] ?? "Limit",
            align: "end",
            cell: (r) => formatFigure(r.limitPerMinute, REQUESTS_PER_MINUTE),
          },
          {
            id: "used",
            header: head[3] ?? "Used now",
            align: "end",
            cell: (r) => formatFigure(r.peakUsedPerMinute, REQUESTS_PER_MINUTE),
          },
          {
            id: "headroom",
            header: head[5] ?? "Headroom",
            align: "end",
            cell: () => NOT_CONNECTED,
          },
          { id: "meter", header: "Meter", cell: (r) => <RateMeter row={r} /> },
        ]}
      />
    </div>
  );
}

/** The reserve band, one row per account: "Not connected yet" until a figure is served (W-06a, W-06b). */
export function ReserveRow({ reserve }: { readonly reserve?: number | null }): JSX.Element {
  const [label = "", missing = NOT_CONNECTED] = parts("W-06a");
  const served = typeof reserve === "number" && Number.isFinite(reserve);
  const text = served ? fill(parts("W-06b")[1] ?? "", { "30": reserve }) : null;
  return (
    <dl className="cv-connectivity__reserve">
      <KeyValueRow label={label} value={text ?? missing} />
    </dl>
  );
}

/** A section whose source is not served: its title, S-19's word and sentence, layout kept (simulator, inspector). */
export function NotServedBlock({ title }: { readonly title: string }): JSX.Element {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} data-state="S-19">
      <h3 id={headingId}>{title}</h3>
      <p>{printable("W-05").join(" ")}</p>
    </section>
  );
}

export interface UsagePoint {
  readonly at: string;
  readonly used: number;
}

/** CMP-024 with its "View as table" alternative (D09 §14); the series is the caller's, never typed here. */
export function UsageHistory({
  points,
  trend,
}: {
  readonly points: readonly UsagePoint[];
  /** The W-72 line, filled by the caller from served values. */
  readonly trend: string;
}): JSX.Element {
  const [title = "", , , viewAsTable = ""] = [...parts("W-70"), ...parts("W-71")];
  return (
    <details data-cmp="usage-history">
      <summary>{title}</summary>
      {points.length === 0 ? (
        <p>{COPY["W-73"]}</p>
      ) : (
        <>
          <p>{trend}</p>
          <Sparkline data={points.map((p) => p.used)} width={160} height={32} />
          <details>
            <summary>{viewAsTable}</summary>
            <Table
              caption={trend}
              captionHidden
              rows={points}
              rowKey={(p) => p.at}
              density="comfortable"
              columns={[
                { id: "at", header: "Time", cell: (p) => p.at },
                { id: "used", header: "Used", align: "end", cell: (p) => String(p.used) },
              ]}
            />
          </details>
        </>
      )}
    </details>
  );
}

/** A section that is loading its first read: CMP-015 and nothing else (S-13). */
export function LoadingBlock(): JSX.Element {
  return (
    <div aria-busy="true" data-state="S-13">
      <Skeleton shape="row" count={2} />
    </div>
  );
}

const STEP_UP_LINE = COPY["W-54"];

interface DialogBase {
  readonly open: boolean;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
}

function Consequences({ lines }: { readonly lines: readonly string[] }): JSX.Element {
  return (
    <ul>
      {lines.map((l) => (
        <li key={l}>{l}</li>
      ))}
    </ul>
  );
}

function Footer({ action }: { readonly action: AuditAction }): ReactNode {
  return (
    <>
      <p>{STEP_UP_LINE}</p>
      <AuditMarker action={action} />
    </>
  );
}

/** Force reconnect of the public market-data socket: rung 2, an alertdialog, never a typed word (D09 §11). */
export function ReconnectDialog({
  connections,
  topics,
  ...base
}: DialogBase & {
  /** The blast radius, fetched before render; `null` keeps Confirm disabled while it loads. */
  readonly connections: number | null;
  readonly topics: number | null;
}): JSX.Element {
  const loaded = connections !== null && topics !== null;
  const radius = loaded
    ? parts("W-52").map((l) => fill(l, { "3": connections, "120": topics }) ?? "")
    : [];
  return (
    <ConfirmDialog
      {...base}
      title={COPY["W-50"]}
      confirmLabel={COPY["W-50"]}
      summaryLoading={!loaded}
      restatement={<Consequences lines={[...parts("W-51"), COPY["W-56"], ...radius]} />}
    >
      <Footer action="reconnect" />
    </ConfirmDialog>
  );
}

/**
 * Change budget: rung 1, drawn contract-first, so the range is the server's or "Not connected yet" (D09 §12).
 * Deferred to PR-2: the new-value field with its unit (D09:379), which needs the served write shape (D09-G8).
 */
export function ChangeBudgetDialog({
  account,
  range,
  refusal,
  ...base
}: DialogBase & {
  readonly account: string;
  readonly range: { readonly min: number; readonly max: number } | null;
  /** The server's mapped sentence for a refused value; the dialog stays open. */
  readonly refusal?: string;
}): JSX.Element {
  const allowed =
    range === null
      ? NOT_CONNECTED
      : (fill(COPY["W-61"], { "60": range.min, "420": range.max }) ?? "");
  const title = COPY["W-60"].replace(/…$/, "");
  return (
    <ConfirmDialog
      {...base}
      title={title}
      confirmLabel={SAVE_BUDGET}
      restatement={
        <>
          <p>{allowed}</p>
          <p>{fill(COPY["W-62"], { Main: account })}</p>
          <Consequences lines={parts("W-64")} />
        </>
      }
      {...(refusal === undefined ? {} : { failure: { message: refusal } })}
    >
      <Footer action="budget" />
    </ConfirmDialog>
  );
}

/** Why the two writes are gated, in D09 §17.5's order: view-as first, then the hold, then the connection budget. */
export type ActionGate =
  | { readonly kind: "open" }
  | { readonly kind: "view_as"; readonly user: string }
  | { readonly kind: "hold" }
  | { readonly kind: "wait"; readonly seconds: number };

export interface ConnectivityActionsProps {
  readonly gate: ActionGate;
  readonly onReconnect: () => void;
  readonly onChangeBudget: () => void;
}

/**
 * The page's two T2 writes (CMP-079 with the `lock`). Under view-as there is ONE read-only notice (G-T2.5), which
 * both controls point at; a gated press re-shows its reason and says it once, politely, through the shell's pair
 * (G-T2.3: the page, not the atom, owns the announcement). The page decides nothing: the server enforces.
 */
export function ConnectivityActions({
  gate,
  onReconnect,
  onChangeBudget,
}: ConnectivityActionsProps): JSX.Element {
  const noticeId = useId();
  const viewAs = gate.kind === "view_as";
  const reconnect = (
    <Button variant="secondary" onClick={onReconnect}>
      {COPY["W-50"]}
    </Button>
  );
  const budget = (
    <Button variant="secondary" onClick={onChangeBudget}>
      {COPY["W-60"]}
    </Button>
  );
  const holdReason = parts("W-36")[0] ?? COPY["W-36"];
  const waitReason = gate.kind === "wait" ? fill(COPY["W-57"], { "40": gate.seconds }) : null;
  const wrap = (
    child: ReactElement<{ disabledReason?: string }>,
    own: string | null,
  ): JSX.Element => {
    if (gate.kind === "view_as")
      return (
        <RbacGate
          form="notice"
          noticeId={noticeId}
          allowed={false}
          reason="rbac.view_as"
          fills={{ user: gate.user }}
        >
          {child}
        </RbacGate>
      );
    if (own === null) return <RbacGate allowed>{child}</RbacGate>;
    return cloneElement(child, { disabledReason: own });
  };
  return (
    <GatedAnnounceProvider announce={politeOnce}>
      {gate.kind === "view_as" ? (
        <Callout id={noticeId} title={fill(COPY["W-74"], { user: gate.user }) ?? ""} live="off" />
      ) : null}
      <div className="cv-connectivity__actions" data-view-as={viewAs ? "" : undefined}>
        {wrap(reconnect, gate.kind === "hold" ? holdReason : waitReason)}
        {wrap(budget, gate.kind === "hold" ? holdReason : null)}
      </div>
    </GatedAnnounceProvider>
  );
}
