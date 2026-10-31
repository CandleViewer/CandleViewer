import { useEffect, useState, type JSX, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Button } from "./Button.js";
import { IconButton } from "./IconButton.js";

export type CalloutTone =
  "info" | "warning" | "danger" | "success" | "connection-reconnecting" | "connection-disconnected";

/** `off` renders no live role: for a callout whose announcement another region already makes. */
export type CalloutLive = "assertive" | "polite" | "off";

export interface CalloutAction {
  label: string;
  onClick: () => void;
}

/**
 * Each tone's registry glyph: colour is never the only signal, the glyph and the title's words carry the tone.
 * Both connection tones draw `disconnected` until E17-D02 CR-8's own glyphs are registered.
 */
const TONE_GLYPH: Readonly<Record<CalloutTone, IconName>> = {
  info: "info",
  success: "success",
  warning: "warning",
  danger: "danger",
  "connection-reconnecting": "disconnected",
  "connection-disconnected": "disconnected",
};

/** The default politeness by tone (CMP-028 A11y): status for info, success and reconnecting, alert otherwise. */
const TONE_LIVE: Readonly<Record<CalloutTone, Exclude<CalloutLive, "off">>> = {
  info: "polite",
  success: "polite",
  "connection-reconnecting": "polite",
  warning: "assertive",
  danger: "assertive",
  "connection-disconnected": "assertive",
};

interface CalloutBase {
  /** Default `info`. */
  tone?: CalloutTone;
  /** The state's words, `type.ui.body-strong`. Never raw exchange error text: map it to a state label first. */
  title: string;
  /**
   * The body, `type.ui.body` in `color.text.secondary` (a sentence, or a sentence and a CMP-023). It is part of
   * the announced message, so it must not be focusable: links and buttons go in `retry` / `actions`. A change of
   * live role remounts the message region, the body included, so it re-announces.
   */
  children?: ReactNode;
  /** A connection tone's caller-written details sentence, under the body; never a passthrough of a wire error. */
  details?: string;
  /** `inline` (default) sits in a panel or form; `band` is full width and square, in the shell's slot. */
  placement?: "inline" | "band";
  /** Overrides the tone's default politeness; `off` renders no live role. */
  live?: CalloutLive;
  /** A registered glyph replacing the tone's. */
  icon?: IconName;
  /**
   * The message's id (title, body, details; never the buttons), so controls can point `aria-describedby` at it:
   * the CMP-079 notice form's one notice (E42-D03).
   */
  id?: string;
  /** A CMP-001 secondary button, first in the action row (e.g. "Retry now"). */
  retry?: CalloutAction;
  /** More CMP-001 secondary buttons after `retry` (e.g. "Details", "Flatten now"). */
  actions?: readonly CalloutAction[];
}

interface Persistent extends CalloutBase {
  dismissible?: false;
  onDismiss?: never;
}

/**
 * Dismissible: a trailing ghost CMP-002 `close` named "Dismiss {title}". The callout never moves focus itself;
 * `onDismiss` hands the dismissal to the host, which removes the callout and moves focus to its own next
 * stop (never `<body>`). A lockout, freeze, disconnect or protection banner is never dismissible while it holds.
 */
interface Dismissible extends CalloutBase {
  dismissible: true;
  onDismiss: () => void;
}

/*
 * Not built here: `edge="hatched"` (the `unprotected` banner's 4 px hatched start edge). Its
 * `pattern.hatch.unprotected` token is PROPOSED (E30-D04 CR-5) and deferred; until it lands every callout draws
 * the solid 2 px edge. The "What changed" disclosure is held (E05-D02 §6 H15 (3)). The dismissal fade waits for
 * the E05-D03 motion recipe: the host's removal is a cut, which every order-ticket banner needs anyway. The
 * flap-collapse (reconnect attempts within 5 s read as one "Connection unstable") is the host's (CMP-077), which
 * owns the connection state; this callout announces each state entry it is given once.
 */
export type CalloutProps = Persistent | Dismissible;

const roleOf = (live: CalloutLive): "status" | "alert" | undefined =>
  live === "off" ? undefined : live === "polite" ? "status" : "alert";

/**
 * CMP-028 Callout / Banner: an inline block inside a panel or form, or a band under the TopBar. Its message is
 * its own live region, mounted with the callout and filled after mount so the entry is announced once; the
 * buttons sit outside it, so their names are not read with the message.
 */
export function Callout(props: CalloutProps): JSX.Element {
  const {
    tone = "info",
    title,
    children,
    details,
    placement = "inline",
    live,
    icon,
    id,
    retry,
    actions = [],
  } = props;
  const politeness = live ?? TONE_LIVE[tone];
  const role = roleOf(politeness);
  // A live region announces content inserted after it exists, so the message lands one effect after the region
  // mounts. The region is keyed on its role: a change of role (a tone crossing the polite / assertive line, or
  // `live` going from off to on) mounts a fresh region and repeats the empty-then-insert step, so it re-announces.
  // Trade-off: the title and body are blank for one frame on entry and on each role change; an empty frame is the
  // price of a reliable announcement (the same step CMP-014 and CMP-038 take). `off` fills at once.
  const regionKey = role ?? "off";
  const [filledKey, setFilledKey] = useState<string | null>(role === undefined ? regionKey : null);
  useEffect(() => {
    setFilledKey(regionKey);
  }, [regionKey]);
  const filled = role === undefined || filledKey === regionKey;
  const buttons = retry === undefined ? actions : [retry, ...actions];
  const dismiss = props.dismissible === true ? props.onDismiss : undefined;
  return (
    <div className="cv-callout" data-cmp="CMP-028" data-tone={tone} data-placement={placement}>
      <span className="cv-callout__glyph">
        <Icon name={icon ?? TONE_GLYPH[tone]} />
      </span>
      <div className="cv-callout__main">
        <div
          key={regionKey}
          id={id}
          className="cv-callout__message"
          role={role}
          aria-live={role === undefined ? undefined : politeness}
          aria-atomic={role === undefined ? undefined : true}
        >
          {filled ? (
            <>
              <p className="cv-callout__title">{title}</p>
              {children === undefined ? null : <div className="cv-callout__body">{children}</div>}
              {details === undefined ? null : <p className="cv-callout__details">{details}</p>}
            </>
          ) : null}
        </div>
        {buttons.length === 0 ? null : (
          <div className="cv-callout__actions">
            {buttons.map((action, index) => (
              <Button
                key={`${index}-${action.label}`}
                variant="secondary"
                onClick={() => action.onClick()}
              >
                {action.label}
              </Button>
            ))}
          </div>
        )}
      </div>
      {dismiss === undefined ? null : (
        <IconButton
          icon="close"
          label={`Dismiss ${title}`}
          variant="ghost"
          onClick={() => dismiss()}
        />
      )}
    </div>
  );
}
