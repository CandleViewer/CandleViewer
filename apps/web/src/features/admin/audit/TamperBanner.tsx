/**
 * The integrity incident (E42-S04; E42-D04 §7, D10, D11, AL-13): CMP-028 `danger`, never
 * dismissible, between the page header and the filters while an episode stands (a run's
 * `verified: false`, or an `open` or `acknowledged` `audit_chain_break` incident). Its message is
 * `role="alert"` on the episode's first mount only (one voice per episode, kept in session state),
 * static on every later one. It names the entry, the time and the range as text; the meaning, the
 * safety line (the halt sentence while the served incident is `open`, the orchestrator's BQ-5) and
 * the recheck line. Outside the message: [Copy details] (the served fields as served), the
 * "What to do now" disclosure, which only toggles `aria-expanded`, and the links to the incident
 * log (R-350: SCR-144 has no route of its own yet, E42-D05 CG-23) and the security centre (R-354).
 * Never a Retry, a re-run, a dismiss or an acknowledge, and never a cause (§7 "What it never
 * offers"); Run tamper check stays in the footer (D10). Mounted under a modal (the page inert,
 * its alert unheard), the episode's one voice is the shell's assertive region instead, which
 * stays live under a modal, and the mount stays static (A-1135P2-10).
 */
import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import { Button, Callout, CopyButton, Link } from "@candleviewer/ui";
import { announce } from "../../app-shell/announcer";
import { routerLink } from "../routerLink";
import { AUDIT_COPY as COPY } from "./copy";
import type { BannerModel } from "./integrity";

/** R-350, where the incident persists until SCR-144 has a route; R-354, the security centre. */
export const INCIDENT_LOG_PATH = "/admin/health";
export const SECURITY_CENTRE_PATH = "/admin/security";

const BANNER: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };
const ROW: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-stack-sm)",
};
const STEPS: CSSProperties = { margin: 0, color: "var(--color-text-primary)" };
const LINE: CSSProperties = { margin: 0 };

export interface TamperBannerProps {
  readonly model: BannerModel;
  /** This episode has not spoken yet: this mount's message is `role="alert"` (D11). */
  readonly speak: boolean;
  /** The message has been mounted to speak: the episode's voice is spent. */
  readonly onSpoken: (voice: string) => void;
}

/** An inert page (CMP-043's `inertOutside`, or its `aria-hidden` fallback) hides its live regions. */
const INERT = "[inert], [aria-hidden='true']";

export function TamperBanner({ model, speak, onSpoken }: TamperBannerProps): JSX.Element {
  // Fixed for this mount: the alert stays an alert while it is read, and a later mount is static.
  const [live, setLive] = useState<"assertive" | "off">(speak ? "assertive" : "off");
  const [open, setOpen] = useState(false);
  const stepsId = useId();
  const root = useRef<HTMLDivElement>(null);
  const { voice } = model;
  const message = [model.title, model.facts, model.meaning, model.safe, model.recheck]
    .filter((line) => line !== null)
    .join(" ");
  useLayoutEffect(() => {
    if (live !== "assertive") return;
    const inert = root.current?.closest(INERT) ?? null;
    if (inert !== null) {
      announce("assertive", message, `audit:banner:${voice}`);
      setLive("off");
    }
    onSpoken(voice);
  }, [live, voice, message, onSpoken]);
  return (
    <div ref={root} style={BANNER} data-tamper-banner="">
      <Callout tone="danger" title={model.title} live={live}>
        {model.facts === null ? null : <p style={LINE}>{model.facts}</p>}
        <p style={LINE}>{model.meaning}</p>
        <p style={LINE} data-halted={model.halted ? "" : undefined}>
          {model.safe}
        </p>
        <p style={LINE}>{model.recheck}</p>
      </Callout>
      <div style={ROW}>
        <CopyButton value={model.details} label={COPY.tamper.failed.copy} />
        <Button
          variant="secondary"
          aria-expanded={open}
          aria-controls={stepsId}
          onKeyDown={(event) => {
            if (event.repeat && (event.key === "Enter" || event.key === " "))
              event.preventDefault();
          }}
          onClick={() => setOpen((now) => !now)}
        >
          {COPY.labels.act.whatToDo}
        </Button>
        <Link to={INCIDENT_LOG_PATH} as={routerLink}>
          {COPY.labels.act.incidentLog}
        </Link>
        <Link to={SECURITY_CENTRE_PATH} as={routerLink}>
          {COPY.labels.act.securityCentre}
        </Link>
      </div>
      <p id={stepsId} style={STEPS} hidden={!open}>
        {model.steps}
      </p>
    </div>
  );
}
