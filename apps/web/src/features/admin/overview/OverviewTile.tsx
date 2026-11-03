import { memo, type CSSProperties, type JSX } from "react";
import {
  AuditRow,
  AuditRowList,
  KeyValueRow,
  Link,
  MonoText,
  SystemHealthTile,
} from "@candleviewer/ui";
import { useShellSelector } from "../../../shell/useShellSelector";
import { routerLink } from "../routerLink";
import { OVERVIEW_COPY as COPY } from "./copy";
import { routePath } from "./links";
import { adminReads, useAdminSelector } from "./readStore";
import { hms, tileModel, type TileKey, type TileRow } from "./tileModels";

/** A tile's lines: CMP-036 rows, one under another (`space.stack.xs` is the tile body's own gap). */
const ROWS: CSSProperties = { display: "grid", margin: 0 };

/** A line's own read time, drawn as the tile's own "as of" line is (`.cv-health-tile__meta`). */
const AS_OF: CSSProperties = {
  color: "var(--color-text-tertiary)",
  font: "var(--type-ui-caption-font-weight) var(--type-ui-caption-font-size) / var(--type-ui-caption-line-height) var(--type-ui-caption-font-family)",
};

/**
 * "as of 14:02:11 UTC" after a line whose read is asked once per entry: its tile's "as of" is the
 * cycled overview's, so the line says when its own read answered (C-5330-11).
 */
const asOfMark = (ms: number): JSX.Element => <span style={AS_OF}>{COPY.rowAsOf(hms(ms))}</span>;

/**
 * A row: a count in `type.num.base` (§6 Keys), CMP-020's fixed-width digits; a value that is a route
 * (the maintenance line) links it through the router (CMP-021). A value with its own read time ends
 * in it, in the value's own text flow.
 */
function Row({ row }: { readonly row: TileRow }): JSX.Element {
  const shown =
    typeof row.value === "number" ? (
      <MonoText size="base">{String(row.value)}</MonoText>
    ) : row.href === undefined || row.value === null ? (
      row.value
    ) : (
      <Link to={row.href} as={routerLink}>
        {row.value}
      </Link>
    );
  const value =
    row.asOf === undefined || row.value === null ? (
      shown
    ) : (
      <>
        {shown} {asOfMark(row.asOf)}
      </>
    );
  return <KeyValueRow label={row.label} value={value} missingLabel={COPY.notReceived} />;
}

/** SCR-136's place for now: the audit log (R-360); the entry's own drawer link is E42-S04's. */
const AUDIT_ENTRY_HREF = routePath("audit") ?? "/admin/audit";

/**
 * One SCR-120 tile: CMP-178 over its model (`tileModels.ts`). It re-renders only when its model
 * changes, so a 30 s re-read that changed nothing leaves it as it was. Retry repeats its own reads
 * and shows this tile loading, no other.
 */
export const OverviewTile = memo(function OverviewTile({
  tile,
}: {
  readonly tile: TileKey;
}): JSX.Element {
  const env = useShellSelector((s) => s.environment);
  const model = useAdminSelector((s) => tileModel(tile, s, env));
  const onRetry =
    model.retry.length === 0 ? undefined : () => adminReads.retry(model.retry, model.key);
  return (
    <SystemHealthTile
      label={model.label}
      href={model.href}
      linkAs={routerLink}
      state={model.state}
      tone={model.tone}
      stateWord={model.stateWord}
      detail={model.detail}
      asOf={model.asOf}
      lastGoodAt={model.lastGoodAt}
      staleSince={model.staleSince}
      stopsWorking={model.stopsWorking}
      env={model.env}
      onRetry={onRetry}
    >
      {model.rows.length === 0 ? null : (
        <dl style={ROWS}>
          {model.rows.map((row) => (
            <Row key={row.label} row={row} />
          ))}
        </dl>
      )}
      {model.note === undefined ? null : (
        <p>
          {model.note}
          {model.noteAsOf === undefined ? null : <> {asOfMark(model.noteAsOf)}</>}
        </p>
      )}
      {model.audit === undefined || model.audit.length === 0 ? null : (
        <AuditRowList>
          {model.audit.map((entry) => (
            <AuditRow
              key={entry.id}
              entry={entry}
              variant="compact"
              href={AUDIT_ENTRY_HREF}
              linkAs={routerLink}
            />
          ))}
        </AuditRowList>
      )}
      {model.marker === undefined ? null : <p>{model.marker}</p>}
    </SystemHealthTile>
  );
});
