import { useEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import { Button, Icon } from "@candleviewer/ui";
import { CLIENT_VERSION } from "../../lib/ws/protocol/frames";
import { BROWSER_CAPABILITIES } from "../../shell/BrowserShellAdapter";
import { ELECTRON_CAPABILITIES } from "../../shell/ElectronShellAdapter";
import { deferUpdate } from "../../shell/bootstrap/store";
import { useShellSelector } from "../../shell/useShellSelector";
import { lastWrittenAt, REGION_BUDGET_MS } from "../app-shell/announcer";
import { SEARCH_TRIGGER_ID } from "../app-shell/TopBar";
import { VERSION_COPY } from "./copy";
import { nextStopAfter } from "./DegradedModeBanner";
import { checkVersion, reportVersionMismatch } from "./versionMismatch";

/** However often others speak, the words give way to them for this long in all (9a's cap). */
const ENTRY_CAP_MS = 15_000;

/**
 * 9a's turn (`OfflineOverlay`; a pinned copy, as 10b's dialog opens at once, E10-D04 T-15):
 * `enter` runs once both shell regions have been quiet REGION_BUDGET_MS (E17-D02 §11), so
 * CMP-077's row 1 is never cut; re-armed by a write meanwhile, each wait at most the budget and
 * ENTRY_CAP_MS in all.
 */
function afterRegionBudget(enter: () => void): () => void {
  let id: ReturnType<typeof setTimeout> | undefined;
  let waited = 0; // counted by the timers, so a wall-clock step cannot stretch the cap
  const attempt = (armedAt?: number): void => {
    const last = Math.max(lastWrittenAt("polite"), lastWrittenAt("assertive"));
    if (last === armedAt) return enter(); // nobody spoke during the wait: the budget is spent
    const since = last + REGION_BUDGET_MS - Date.now();
    const waitMs = Math.min(since, REGION_BUDGET_MS, ENTRY_CAP_MS - waited);
    if (waitMs <= 0) return enter();
    waited += waitMs;
    id = setTimeout(() => attempt(last), waitMs);
  };
  attempt();
  return () => clearTimeout(id);
}

/**
 * E10-D04 T-19 (PROPOSED): after Later, focus goes to the next banner's first control, else to the
 * TopBar's search trigger, never into the canvas, where a repeated key could act.
 */
function afterLaterTarget(band: HTMLElement): HTMLElement | null {
  const next = nextStopAfter(band);
  const slot = band.closest('[data-shell-slot="banner"]');
  return next !== undefined && slot?.contains(next) === true
    ? next
    : document.getElementById(SEARCH_TRIGGER_ID);
}

const TYPE_UI_BODY =
  "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / " +
  "var(--type-ui-body-line-height) var(--type-ui-body-font-family)";
/** E10-D03 §9.1 and §11.4's banner row; at 200 % the actions wrap to a second line (§11.3). */
const BAND: CSSProperties = {
  position: "relative", // the words' hidden region is placed in it
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-1) var(--space-inset-sm)",
  minHeight: "var(--size-target-min)",
  padding: "var(--space-1) var(--space-inset-md)",
  background: "var(--color-status-info-subtle)",
  border: "calc(var(--border-hairline) * 1px) solid transparent", // forced colours draw it
  color: "var(--color-text-primary)",
  font: TYPE_UI_BODY,
};
const MESSAGE: CSSProperties = { flex: "1 1 auto", minWidth: 0, overflowWrap: "anywhere" };
const LABEL: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "var(--space-2)",
  color: "var(--color-status-info-strong)",
  fontWeight: "var(--font-weight-semibold)",
};
const ACTIONS: CSSProperties = { display: "flex", flexWrap: "wrap", gap: "var(--space-inset-sm)" };

interface VersionBannerProps {
  readonly desktop: boolean;
  readonly serverVersion: string;
  readonly onReload: () => void;
}

/**
 * SCR-157's band (E10-D03 §9.1, board 10), shown at once: the glyph and label in `.strong`, the
 * sentence, Later and, in a browser, Reload. Its words go to a hidden `role="status"` region,
 * mounted empty and filled at its turn (9a's entry, CMP-092's regions), so they are said once.
 */
function VersionBanner({ desktop, serverVersion, onReload }: VersionBannerProps): JSX.Element {
  const root = useRef<HTMLDivElement>(null);
  const [said, setSaid] = useState(false);
  useEffect(() => afterRegionBudget(() => setSaid(true)), []);
  const reason = (desktop ? ELECTRON_CAPABILITIES : BROWSER_CAPABILITIES).reason.autoUpdate;
  const sentence = `${VERSION_COPY.versions(desktop, CLIENT_VERSION, serverVersion)}${
    reason === undefined ? "" : ` ${reason}`
  }`;
  const later = (): void => {
    const target = root.current === null ? null : afterLaterTarget(root.current);
    deferUpdate();
    target?.focus();
  };
  return (
    <div ref={root} data-version-banner={desktop ? "desktop" : "browser"} style={BAND}>
      <div role="status" aria-live="polite" aria-atomic="true" className="cv-visually-hidden">
        {said ? `${VERSION_COPY.label}. ${sentence}` : null}
      </div>
      <span style={LABEL}>
        <Icon name="info" size="sm" />
        {VERSION_COPY.label}
      </span>
      <span style={MESSAGE}>{sentence}</span>
      <div style={ACTIONS}>
        <Button size="sm" onClick={later}>
          {VERSION_COPY.later}
        </Button>
        {desktop ? null : (
          <Button variant="primary" size="sm" onClick={onReload}>
            {VERSION_COPY.reload}
          </Button>
        )}
      </div>
    </div>
  );
}

export interface VersionBannerSlotProps {
  /** Reload; `window.location.reload` by default (tests pass a spy). */
  readonly reload?: () => void;
}

/**
 * SCR-157's container (#306 slice 10a), in the banner slot: only `update_available` shows, until
 * Later (`incompatible` is `VersionDialogSlot`'s); each pair is a band of its own (keyed) and is
 * reported once, shown or not. The desktop app (the preload bridge, `createShellPort`'s rule) has
 * no Restart and update before signing (an absence, not T2) and no Reload.
 */
export function VersionBannerSlot({
  reload = () => window.location.reload(),
}: VersionBannerSlotProps): JSX.Element | null {
  const pending = useShellSelector((s) =>
    checkVersion(CLIENT_VERSION, s.serverProtocol, s.serverVersion) === "update_available"
      ? s.serverVersion
      : undefined,
  );
  const deferred = useShellSelector((s) => s.updateDeferred);
  useEffect(() => {
    if (pending !== undefined) reportVersionMismatch(CLIENT_VERSION, pending, false);
  }, [pending]);
  if (pending === undefined || deferred) return null;
  return (
    <VersionBanner
      key={pending}
      desktop={window.cv !== undefined}
      serverVersion={pending}
      onReload={reload}
    />
  );
}
