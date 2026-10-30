import type { CSSProperties, JSX, ReactNode, Ref } from "react";
import { Button, CopyButton, Icon } from "@candleviewer/ui";
import { SCR159_COPY } from "./copy";

export interface OfflinePageProps {
  readonly heading: string;
  readonly sentence: string;
  readonly headingRef?: Ref<HTMLHeadingElement> | undefined;
  /** Seconds to the next automatic try ("Retrying in ~N s"); `null` while a try runs. */
  readonly retryInS: number | null;
  /** A try is running: `aria-busy` on the page. */
  readonly busy?: boolean;
  readonly onRetry: () => void;
  /** Retry now as the primary action (R-902's takeover); secondary in the canvas (board 10). */
  readonly primary?: boolean;
  /** SCR-157's fallback block: the console kill switch while no in-app exit reaches the server. */
  readonly fallback?: boolean;
  /** A second action after Retry now: the GPU page's Keep software rendering (D02 f28). */
  readonly secondary?: { readonly label: string; readonly onClick: () => void } | undefined;
  /** A variant's own lines (the checks), between the sentence and the retry line. */
  readonly children?: ReactNode;
}

const PAGE: CSSProperties = {
  display: "grid",
  gap: "var(--space-stack-sm)",
  justifyItems: "start",
  padding: "var(--space-inset-lg)",
  color: "var(--color-text-secondary)",
  font: "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)",
};
const HEADING: CSSProperties = {
  margin: 0,
  color: "var(--color-text-primary)",
  font: "var(--type-ui-heading-md-font-weight) var(--type-ui-heading-md-font-size) / var(--type-ui-heading-md-line-height) var(--type-ui-heading-md-font-family)",
};
const P: CSSProperties = { margin: 0 };
/** Board 10 draws the block's line semibold, on SCR-159 and SCR-157 alike. */
const LABEL: CSSProperties = {
  color: "var(--color-text-primary)",
  fontWeight: "var(--font-weight-semibold)",
};
const ACTIONS: CSSProperties = { display: "flex", flexWrap: "wrap", gap: "var(--space-2)" };
const CODE: CSSProperties = {
  margin: 0,
  padding: "var(--space-inset-xs) var(--space-inset-sm)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  fontFamily: "var(--font-family-mono)",
};

/**
 * SCR-157's fallback block (E10-D03 §9.1, §9.2; CMP-068 with CMP-033, SR-086): the server console
 * command, the stop-harm route while no in-app exit reaches the server; on SCR-159 and SCR-157.
 * `id` names the line, and `{id}-command` the command, for a host that reads them (SCR-157).
 */
export function ConsoleFallback({ id }: { readonly id?: string }): JSX.Element {
  return (
    <>
      <p id={id} style={{ ...P, ...LABEL }}>
        {SCR159_COPY.fallback}
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
        <pre id={id === undefined ? undefined : `${id}-command`} style={CODE}>
          <code>{SCR159_COPY.command}</code>
        </pre>
        <CopyButton value={SCR159_COPY.command} label={SCR159_COPY.copyCommand} />
      </div>
    </>
  );
}

/**
 * The SCR-159 page template (E10-D03 §9.2): the `disconnected` glyph, a heading, one plain
 * sentence, the variant's lines, a retry line and Retry now, with the GPU page's second action
 * beside it (slice 9c). The glyph is decorative: the heading names the condition, so colour or
 * glyph is never the only signal. The heading is the page's `h1` (the page replaces what it
 * covers; D02 / D03 pin no level) and takes focus once (`tabIndex` -1); the retry line is plain
 * text outside every live region, never announced.
 */
export function OfflinePage(props: OfflinePageProps): JSX.Element {
  const {
    heading,
    sentence,
    headingRef,
    retryInS,
    busy,
    onRetry,
    primary,
    fallback,
    secondary,
    children,
  } = props;
  const retry = (
    <Button variant={primary === true ? "primary" : "secondary"} onClick={onRetry}>
      {SCR159_COPY.retryNow}
    </Button>
  );
  return (
    <div style={PAGE} aria-busy={busy === true ? true : undefined}>
      <Icon name="disconnected" size="lg" />
      <h1 ref={headingRef} tabIndex={-1} style={HEADING}>
        {heading}
      </h1>
      <p style={P}>{sentence}</p>
      {children}
      {retryInS === null ? null : <p style={P}>{SCR159_COPY.retryIn(retryInS)}</p>}
      {fallback === true ? <ConsoleFallback /> : null}
      {secondary === undefined ? (
        retry
      ) : (
        <div style={ACTIONS}>
          {retry}
          <Button onClick={secondary.onClick}>{secondary.label}</Button>
        </div>
      )}
    </div>
  );
}
