import { useEffect, useId, useRef, useState, type JSX } from "react";
import { Icon } from "../icons/Icon.js";
import { Button } from "./Button.js";

/**
 * CMP-091's copy (E05-D02 §7 CMP-091; SCR-156). "D03" = `docs/design/E10/E10-D03.md` §9.4; "board" =
 * its board 10 export, frames `SCR-156/panel-level` and `SCR-156/route-level` (read off at full size).
 * Every string is verbatim from its source; the ones no design fixes are marked PROPOSED.
 */
export const GLOBAL_ERROR_FALLBACK_COPY = {
  panel: {
    /** D03:328, :371; E10-D04 `shell.scr156.fallback`. */
    heading: "This panel stopped working",
    /** Board `SCR-156/panel-level`, verbatim. */
    body: "The surviving workspace is unaffected. Copy diagnostics and report it, or reload the panel.",
    /** D03 §9.4. */
    reload: "Reload panel",
    /** PROPOSED: E04-D01:189, "This panel keeps crashing — reload disabled." */
    repeatedHeading: "This panel keeps crashing — reload disabled.",
  },
  route: {
    /** Board `SCR-156/route-level`, verbatim. */
    heading: "Something went wrong",
    /** PROPOSED: the board's sentence without its safe-mode clause, until safe mode exists. */
    body: "Reload the page or the app.",
    /** D03 §9.4. */
    reload: "Reload page",
    /** PROPOSED: E04-D01:189's string, for a page. */
    repeatedHeading: "This page keeps crashing — reload disabled.",
  },
  app: {
    /** PROPOSED: the route board's heading; no design draws the app scope's words. */
    heading: "Something went wrong",
    /** PROPOSED. */
    body: "Reload the app.",
    /** D03 §9.4 ("Reload app"). */
    reload: "Reload app",
    /** PROPOSED: E04-D01:189's string, for the app. */
    repeatedHeading: "The app keeps crashing.",
  },
  /** PROPOSED: E04-D01:189-190 asks for the reason in plain text; D03 §9.4 gives the threshold. */
  repeatedReason: "It crashed three times in two minutes. Reload the app to start again.",
  /** D03 §9.4. */
  reloadApp: "Reload app",
  /** D03 §9.4. */
  removePanel: "Remove panel",
  /** D03 §9.4. */
  safeMode: "Start in safe mode",
  /** D03 §9.4. */
  copyDiagnostics: "Copy diagnostics",
  /** D03 §9.4 (E05-D02 CMP-091's disclosure name). */
  technicalDetail: "Technical detail",
  /** Board `SCR-156/panel-level`: "error id 7f3a-2c · 14:02:05 UTC" (the timestamp is not shown yet). */
  errorId: "error id",
  /** PROPOSED (both): no drawn string for the copy result. */
  copied: "Diagnostics copied.",
  copyFailed: "Couldn't copy the diagnostics.",
} as const;

export type GlobalErrorScope = "panel" | "route" | "app";

export interface GlobalErrorBoundaryFallbackProps {
  /** `panel` keeps the workspace around it; `route` keeps the chrome; `app` is the root boundary. */
  readonly scope?: GlobalErrorScope;
  /** The crash's error id, shown selectable. */
  readonly correlationId: string;
  /** Three crashes in two minutes: the reload of this scope is no longer offered and the reason is said. */
  readonly repeated?: boolean;
  /** Reload panel / Reload page; for `app` it is the Reload app action. */
  readonly onReload: () => void;
  /** Reload app: offered by `route`, and by `panel` once the crash repeats. */
  readonly onReloadApp?: (() => void) | undefined;
  /** Remove panel (`panel` only); omitted, the button is not rendered. */
  readonly onRemovePanel?: (() => void) | undefined;
  /** Start in safe mode (`route`, `app`); omitted, the button is not rendered. */
  readonly onSafeMode?: (() => void) | undefined;
  /**
   * Copy diagnostics: the host copies its redacted payload (SR-177) and resolves, or rejects on
   * failure. The component never sees an error object or the clipboard.
   */
  readonly onCopyDiagnostics: () => Promise<void>;
  /**
   * "Technical detail": a host-redacted string (today this crash's redacted log line, not a stack),
   * rendered as text. Omitted, no disclosure.
   */
  readonly details?: string | undefined;
  /** The host's protection sentence, only where true (D03 §9.4). */
  readonly protectionNote?: string | undefined;
}

const C = GLOBAL_ERROR_FALLBACK_COPY;

const headingOf = (scope: GlobalErrorScope, repeated: boolean): string =>
  repeated ? C[scope].repeatedHeading : C[scope].heading;

export interface GlobalErrorAnnouncementProps {
  readonly scope: "panel" | "route";
  readonly repeated?: boolean;
}

/**
 * CMP-091's one sentence for a panel or route crash (E05-D02 §7 name/role table, H20): the host
 * injects it into its pre-rendered `role="alert"` region, which holds nothing else, so the
 * announcement is made once per crash and later fallback changes never repeat it.
 */
export function GlobalErrorAnnouncement({
  scope,
  repeated = false,
}: GlobalErrorAnnouncementProps): JSX.Element {
  return <span className="cv-visually-hidden">{headingOf(scope, repeated)}</span>;
}

/**
 * CMP-091 GlobalErrorBoundaryFallback (E05-D02 §7, H20). Props only: the host reports the crash and
 * redacts what it passes. A panel or route host renders this beside its pre-rendered `role="alert"`
 * region and announces through `GlobalErrorAnnouncement`; the `app` scope (no shell left) wraps only
 * its static lead in its own alert. The copy result speaks through a polite status outside any alert.
 * Focus goes to the heading only when the crash dropped it to the body (a restoration, never a steal).
 */
export function GlobalErrorBoundaryFallback({
  scope = "panel",
  correlationId,
  repeated = false,
  onReload,
  onReloadApp,
  onRemovePanel,
  onSafeMode,
  onCopyDiagnostics,
  details,
  protectionNote,
}: GlobalErrorBoundaryFallbackProps): JSX.Element {
  const copy = C[scope];
  const headingId = useId();
  const detailId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [open, setOpen] = useState(false);
  const [copyResult, setCopyResult] = useState<string | null>(null);

  useEffect(() => {
    const active = document.activeElement;
    if (active === null || active === document.body) headingRef.current?.focus();
  }, []);

  const copyDiagnostics = (): void => {
    const failed = (): void => setCopyResult(C.copyFailed);
    try {
      onCopyDiagnostics().then(() => setCopyResult(C.copied), failed);
    } catch {
      failed();
    }
  };

  const Heading = scope === "panel" ? "h2" : "h1";
  const isApp = scope === "app";
  // The app scope's reload is Reload app, so it stays offered when the crash repeats (a manual exit).
  const showReload = isApp || !repeated;
  const showReloadApp = !isApp && (repeated || scope === "route");
  return (
    <section
      className="cv-crash"
      data-cmp="CMP-091"
      data-scope={scope}
      data-repeated={repeated ? "" : undefined}
      aria-labelledby={headingId}
    >
      {/* Static after mount: the app scope's alert wraps only this lead. */}
      <div className="cv-crash__lead" role={isApp ? "alert" : undefined}>
        <span className="cv-crash__glyph">
          <Icon name="danger" size="lg" />
        </span>
        <Heading id={headingId} ref={headingRef} tabIndex={-1} className="cv-crash__heading">
          {headingOf(scope, repeated)}
        </Heading>
        <p className="cv-crash__body">{repeated ? C.repeatedReason : copy.body}</p>
        {protectionNote === undefined ? null : <p className="cv-crash__body">{protectionNote}</p>}
        <p className="cv-crash__id">
          {C.errorId} <code>{correlationId}</code>
        </p>
      </div>
      <div className="cv-crash__actions">
        {showReload ? (
          <Button variant="primary" onClick={onReload}>
            {copy.reload}
          </Button>
        ) : null}
        {showReloadApp && onReloadApp !== undefined ? (
          <Button variant={repeated ? "primary" : "secondary"} onClick={onReloadApp}>
            {C.reloadApp}
          </Button>
        ) : null}
        {scope === "panel" && onRemovePanel !== undefined ? (
          <Button onClick={onRemovePanel}>{C.removePanel}</Button>
        ) : null}
        {scope !== "panel" && onSafeMode !== undefined ? (
          <Button onClick={onSafeMode}>{C.safeMode}</Button>
        ) : null}
        <Button onClick={copyDiagnostics}>{C.copyDiagnostics}</Button>
      </div>
      {/* Pre-rendered empty, polite: the copy result is never part of the crash announcement. */}
      <p className="cv-crash__result" role="status">
        {copyResult}
      </p>
      {details === undefined ? null : (
        <div className="cv-crash__details">
          <button
            type="button"
            className="cv-control cv-crash__disclosure"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((o) => !o)}
          >
            <span className="cv-crash__chevron">
              <Icon name={open ? "chevron-down" : "chevron-right"} />
            </span>
            {C.technicalDetail}
          </button>
          {/* Mounted empty while closed: the disclosure's target exists, its text does not. */}
          <div id={detailId} hidden={!open}>
            {open ? <pre className="cv-crash__detail-text">{details}</pre> : null}
          </div>
        </div>
      )}
    </section>
  );
}
