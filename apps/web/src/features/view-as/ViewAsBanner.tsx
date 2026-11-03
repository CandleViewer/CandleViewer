import { useEffect, useRef, useState, type JSX } from "react";
import { Button, Callout, Countdown, Icon } from "@candleviewer/ui";
import type { HeldViewAs } from "../../shell/bootstrap/store";
import { useShellSelector } from "../../shell/useShellSelector";
import { announce, forget } from "../app-shell/announcer";
import {
  PHASE_GLYPH,
  bannerAnnouncement,
  bannerPhase,
  nextPhaseInMs,
  type BannerPhase,
} from "./bannerPhase";
import { VA_COPY, bannerSentences, fillUser } from "./copy";
import { exitViewAs, takeBackNote, type ExitOutcome } from "./exitViewAs";
import "./viewAs.css";

/** The node under Exit that says V-14, which Exit points at. */
export const EXIT_FAILED_ID = "cv-view-as-exit-failed";
const EXIT_FAILED_KEY = "view-as:exit-failed";

export interface ViewAsBannerViewProps {
  /** The context the server says the session holds. */
  readonly held: HeldViewAs;
  /** The client clock (epoch ms); the banner adds the server's offset. `Date.now` by default. */
  readonly now?: (() => number) | undefined;
  /** Exit's call: `leaving` once the page is leaving, `failed` (V-14), `locked` (SCR-005 has it). */
  readonly onExit?: (() => Promise<ExitOutcome>) | undefined;
}

/**
 * SCR-124's banner (E42-S03; E42-D03 §10, D24, §13): a `section` named "View-as", never a live
 * region, the shell's first row above the skip link and the TopBar. CMP-028 (info, band, `live`
 * off, the eye glyph) carries `va.banner_ro` around a CMP-035 count of the server's `expires_at`,
 * then `va.notified`; once the server ended the context, `va.ended`. Exit (CMP-001 primary, with
 * D24's 1 px `color.text.primary` border) is its one control and so the page's first Tab stop:
 * Enter or Space leaves, Esc never does. The banner speaks through the shell announcer: on entry
 * and once the context ended (assertive), at 5:00 (polite) and 1:00 (assertive); never per tick.
 */
export function ViewAsBannerView({
  held,
  now = Date.now,
  onExit = exitViewAs,
}: ViewAsBannerViewProps): JSX.Element {
  // The latest clock, read by the timer and the count without restarting either (as CMP-035).
  const clock = useRef(now);
  useEffect(() => {
    clock.current = now;
  });
  const [phase, setPhase] = useState<BannerPhase>(() => bannerPhase(held, now()));
  // bumped when a mark's timer fires before the page clock reached the mark: look again
  const [nudge, setNudge] = useState(0);
  const spoken = useRef<BannerPhase | null>(null);
  const [exiting, setExiting] = useState(false);
  const [failed, setFailed] = useState(false);
  const user = held.targetName;

  // The phase moves at the two marks only: one timer to the next, re-armed when it moves. `Date`
  // and timers are separate clocks (a clock sync, a resume): a timer that finds the mark not yet
  // reached on the page clock arms again for what is left, never giving the mark up.
  useEffect(() => {
    const current = bannerPhase(held, clock.current());
    if (current !== phase) {
      setPhase(current);
      return undefined;
    }
    const delay = nextPhaseInMs(held, clock.current());
    if (delay === null) return undefined;
    const timer = setTimeout(() => {
      const next = bannerPhase(held, clock.current());
      if (next === phase) setNudge((n) => n + 1);
      else setPhase(next);
    }, delay);
    return () => clearTimeout(timer);
  }, [held, phase, nudge]);

  useEffect(() => {
    const said = bannerAnnouncement(spoken.current, phase);
    spoken.current = phase;
    if (said !== null) announce(said.politeness, fillUser(said.text, user), said.key);
  }, [phase, user]);

  const exit = async (): Promise<void> => {
    if (exiting) return;
    setExiting(true);
    setFailed(false);
    forget(EXIT_FAILED_KEY); // each failure is said once
    const outcome = await onExit();
    if (outcome === "leaving") return; // the page is leaving: Exit stays busy
    setExiting(false);
    if (outcome === "locked") return; // SCR-005 asks to unlock; Exit is there again after it
    setFailed(true);
    announce("assertive", VA_COPY.exitFailed, EXIT_FAILED_KEY);
  };

  // the server's word, in the very render it arrives in; the phase follows one effect later
  const ended = held.state === "expired" || phase === "ended";
  const glyph = PHASE_GLYPH[phase];
  const sentences = bannerSentences(user);
  const serverNow = (): number => clock.current() + held.offsetMs;
  return (
    <section aria-label={VA_COPY.region} className="cv-view-as" data-phase={phase}>
      <div className="cv-view-as__message">
        <Callout
          tone="info"
          placement="band"
          live="off"
          icon="show"
          title={ended ? fillUser(VA_COPY.ended, user) : sentences.lead}
        >
          {ended ? undefined : (
            <>
              <span className="cv-view-as__ends">
                {sentences.endsBefore}
                {glyph === null ? null : (
                  <span className="cv-view-as__glyph" data-glyph={glyph}>
                    <Icon name={glyph} />
                  </span>
                )}
                <Countdown expiresAt={held.expiresAtMs} now={serverNow} thresholds={[]} />
                {sentences.endsAfter}
              </span>{" "}
              <span>{fillUser(VA_COPY.notified, user)}</span>
            </>
          )}
        </Callout>
      </div>
      <div className="cv-view-as__exit">
        <Button
          variant="primary"
          loading={exiting}
          onClick={() => void exit()}
          aria-describedby={failed ? EXIT_FAILED_ID : undefined}
        >
          {VA_COPY.exit}
        </Button>
        {failed ? (
          <p id={EXIT_FAILED_ID} className="cv-view-as__failed">
            {VA_COPY.exitFailed}
          </p>
        ) : null}
      </div>
    </section>
  );
}

/**
 * The shell's view-as row (`ShellViewAsSlot`): the banner while the session holds a context, else
 * nothing (0 px, no node, no Tab stop). After Exit's load it says `va.back` once (V-9).
 */
export function ViewAsBanner(): JSX.Element | null {
  const viewAs = useShellSelector((s) => s.viewAs);
  useEffect(() => {
    if (takeBackNote()) announce("polite", VA_COPY.back, "view-as:back");
  }, []);
  return viewAs.kind === "held" ? <ViewAsBannerView held={viewAs} /> : null;
}
