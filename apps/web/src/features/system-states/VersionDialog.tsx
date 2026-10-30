import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type JSX,
  type RefObject,
} from "react";
import { Button, Dialog } from "@candleviewer/ui";
import { CLIENT_VERSION } from "../../lib/ws/protocol/frames";
import { continueReadOnly } from "../../shell/bootstrap/store";
import { useShellSelector } from "../../shell/useShellSelector";
import { SEARCH_TRIGGER_ID } from "../app-shell/TopBar";
import { VERSION_DIALOG_COPY as COPY } from "./copy";
import { ConsoleFallback } from "./OfflinePage";
import { incompatibleBuild, reportVersionMismatch } from "./versionMismatch";

/** Board 10's "What stops" and "Still works" lines. */
const LINE: CSSProperties = { margin: 0, fontWeight: "var(--font-weight-semibold)" };

/**
 * CMP-043's heading, the element that names the card, for `initialFocusRef`: §9.1 and E10-D04
 * T-15 start focus there, where H32 would name a choice. CMP-043 falls back to the heading anyway;
 * naming it keeps H32's DEV warning for an `alertdialog` with no choice quiet. Read before the
 * dialog moves focus.
 */
function useHeadingOf(inside: RefObject<HTMLElement | null>): RefObject<HTMLElement | null> {
  const heading = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const card = inside.current?.closest('[role="alertdialog"]');
    const id = card?.getAttribute("aria-labelledby");
    heading.current =
      id == null ? null : (card?.querySelector<HTMLElement>(`[id="${id}"]`) ?? null);
  });
  return heading;
}

interface VersionDialogProps {
  readonly open: boolean;
  /** The server's protocol label, `null` when the worker refused it. */
  readonly protocol: string | null;
  readonly serverVersion: string | undefined;
  readonly onContinue: () => void;
}

/**
 * SCR-157's blocking dialog (E10-D03 §9.1, boards 10 and 11): CMP-043 as an `alertdialog`, the
 * system raising it (E10-D04 F-08), modal over the body (the shell's scrim band; at 200 % it fills
 * the viewport, and its scrolling body still carries the console fallback, E17-D01 §6's kill-switch
 * path while the protocol is incompatible); the TopBar, the banner slot and the StatusBar stay
 * outside the inert page (`AppShell`). It is described in §9.1's order: the versions row, what
 * stops, what still works, the console fallback (`14` SCR-157: the versions "and what will
 * happen"). Focus starts on the heading; Tab reaches the copy block, then Continue read-only, the
 * one dismiss, which `Esc` is too (E10-D04 §13.2, C-08). Focus then goes to the TopBar's search
 * trigger, not back to where the server's answer found it.
 */
function VersionDialog(props: VersionDialogProps): JSX.Element {
  const { open, protocol, serverVersion, onContinue } = props;
  const first = useRef<HTMLParagraphElement>(null);
  const heading = useHeadingOf(first);
  const wasOpen = useRef(open);
  const id = useId();
  useEffect(() => {
    // after CMP-043's own return of focus, which aims at the opener
    if (wasOpen.current && !open) document.getElementById(SEARCH_TRIGGER_ID)?.focus();
    wasOpen.current = open;
  }, [open]);
  return (
    <Dialog
      open={open}
      onOpenChange={onContinue}
      role="alertdialog"
      title={COPY.heading}
      description={COPY.versions(CLIENT_VERSION, serverVersion, protocol)}
      aria-describedby={`${id}-stops ${id}-works ${id}-fallback ${id}-fallback-command`}
      initialFocusRef={heading}
      footer={
        <Button variant="primary" onClick={onContinue}>
          {COPY.continue}
        </Button>
      }
    >
      <p ref={first} id={`${id}-stops`} style={LINE}>
        {COPY.stops}
      </p>
      <p id={`${id}-works`} style={LINE}>
        {COPY.works}
      </p>
      <ConsoleFallback id={`${id}-fallback`} />
    </Dialog>
  );
}

/**
 * SCR-157's blocking variant (#306 slice 10b), in the banner slot: while the build is incompatible
 * (another protocol, or a label the worker refused: it fails closed) its dialog shows until
 * Continue read-only, once per build while the server keeps it (the store forgets the answer when
 * the build changes or the state ends, T-18). The gated set's T2 leg (`protocolLeg`) holds
 * meanwhile (§1.3); `app.version_mismatch` goes out once per pair, versions only.
 */
export function VersionDialogSlot(): JSX.Element | null {
  const build = useShellSelector(incompatibleBuild);
  const continued = useShellSelector((s) => s.continuedFor === build);
  const protocol = useShellSelector((s) => s.serverProtocol ?? null);
  const serverVersion = useShellSelector((s) => s.serverVersion);
  useEffect(() => {
    if (build !== undefined) reportVersionMismatch(CLIENT_VERSION, serverVersion ?? null, true);
  }, [build, serverVersion]);
  if (build === undefined) return null;
  return (
    <VersionDialog
      key={build}
      open={!continued}
      protocol={protocol}
      serverVersion={serverVersion}
      onContinue={() => continueReadOnly(build)}
    />
  );
}
