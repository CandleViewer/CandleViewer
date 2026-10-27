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
  /** The body, `type.ui.body` in `color.text.secondary` (a sentence, or a sentence and a CMP-023). */
  children?: ReactNode;
  /** A connection tone's caller-written details sentence, under the body; never a passthrough of a wire error. */
  details?: string;
  /** `inline` (default) sits in a panel or form; `band` is full width and square, in the shell's slot. */
  placement?: "inline" | "band";
  /** Overrides the tone's default politeness; `off` renders no live role. */
  live?: CalloutLive;
  /** A registered glyph replacing the tone's. */
  icon?: IconName;
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
 * the E05-D03 motion recipe: the host's removal is a cut, which every order-ticket banner needs anyway.
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
    retry,
    actions = [],
  } = props;
  const politeness = live ?? TONE_LIVE[tone];
  const role = roleOf(politeness);
  // A live region announces content inserted after it exists, so the message lands one effect after mount.
  const [mounted, setMounted] = useState(role === undefined);
  useEffect(() => {
    setMounted(true);
  }, []);
  const buttons = retry === undefined ? actions : [retry, ...actions];
  const dismiss = props.dismissible === true ? props.onDismiss : undefined;
  return (
    <div className="cv-callout" data-cmp="CMP-028" data-tone={tone} data-placement={placement}>
      <span className="cv-callout__glyph">
        <Icon name={icon ?? TONE_GLYPH[tone]} />
      </span>
      <div className="cv-callout__main">
        <div
          className="cv-callout__message"
          role={role}
          aria-live={role === undefined ? undefined : politeness}
          aria-atomic={role === undefined ? undefined : true}
        >
          {mounted ? (
            <>
              <p className="cv-callout__title">{title}</p>
              {children === undefined ? null : <div className="cv-callout__body">{children}</div>}
              {details === undefined ? null : <p className="cv-callout__details">{details}</p>}
            </>
          ) : null}
        </div>
        {buttons.length === 0 ? null : (
          <div className="cv-callout__actions">
            {buttons.map((action) => (
              <Button key={action.label} variant="secondary" onClick={() => action.onClick()}>
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
