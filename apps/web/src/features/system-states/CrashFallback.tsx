/**
 * TEMPORARY CMP-091 GlobalErrorBoundaryFallback (E10-S04 #306 slice 6): E05-S04's design-system CMP-091
 * (#267) replaces it, with its styling and stories; until then its states are axe-checked in
 * `test/features/system-states/errorBoundary.test.tsx`. The raw error is never rendered ("Technical
 * detail" waits for #267); Copy diagnostics is an explicit action over the redacted payload (SR-177).
 * Focus (`15` CMP-091): to the heading only when the crash dropped it to the body. The announcement is
 * the host's polite region (PROPOSED: D04 F-09's shell assertive region does not exist yet).
 */
import { useEffect, useId, useRef, useState, type JSX } from "react";
import { buildDiagnostics } from "../../shell/crash/reportCrash";
import { CRASH_COPY } from "./copy";
import type { CrashRecord } from "./crashGuard";

export interface CrashFallbackProps {
  readonly scope: "panel" | "route";
  readonly crash: CrashRecord;
  /** Reload panel (re-mounts the child) or Reload page. Not offered once the crash repeats. */
  readonly onReload: () => void;
  readonly onReloadApp?: (() => void) | undefined;
}

export function CrashFallback({
  scope,
  crash,
  onReload,
  onReloadApp = () => window.location.reload(),
}: CrashFallbackProps): JSX.Element {
  const copy = CRASH_COPY[scope];
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [copyResult, setCopyResult] = useState<string | null>(null);

  useEffect(() => {
    const active = document.activeElement;
    if (active === null || active === document.body) headingRef.current?.focus();
  }, []);

  const copyDiagnostics = (): void => {
    const failed = (): void => setCopyResult(CRASH_COPY.copyFailed);
    try {
      const clipboard = (navigator as Partial<Navigator>).clipboard;
      if (clipboard === undefined) return failed();
      const text = JSON.stringify(buildDiagnostics(), null, 2);
      clipboard.writeText(text).then(() => setCopyResult(CRASH_COPY.copied), failed);
    } catch {
      failed();
    }
  };

  const Heading = scope === "panel" ? "h2" : "h1";
  return (
    <section aria-labelledby={headingId}>
      <Heading id={headingId} ref={headingRef} tabIndex={-1}>
        {crash.repeated ? copy.repeatedHeading : copy.heading}
      </Heading>
      <p>{crash.repeated ? CRASH_COPY.repeatedReason : copy.body}</p>
      <p>
        {CRASH_COPY.errorId} <code>{crash.correlationId}</code>
      </p>
      {crash.repeated ? null : (
        <button type="button" onClick={onReload}>
          {copy.reload}
        </button>
      )}
      {crash.repeated || scope === "route" ? (
        <button type="button" onClick={onReloadApp}>
          {CRASH_COPY.reloadApp}
        </button>
      ) : null}
      <button type="button" onClick={copyDiagnostics}>
        {CRASH_COPY.copyDiagnostics}
      </button>
      {copyResult === null ? null : <p>{copyResult}</p>}
    </section>
  );
}
