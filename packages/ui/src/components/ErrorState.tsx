import { useEffect, useId, useState, type JSX, type MouseEvent, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Button } from "./Button.js";
import { CopyButton } from "./CopyButton.js";
import { Link } from "./Link.js";
import { Heading, type HeadingLevel } from "./Typography.js";
import { cx } from "./internal/cx.js";

export type ErrorSeverity = "warning" | "error";

/** `panel` lays out as CMP-026's block; `inline` is one row at the point of action; `banner` is CMP-028's box. */
export type ErrorStateForm = "panel" | "inline" | "banner";

/** `off` renders no live role: for a failure another node already announced. */
export type ErrorStateLive = "assertive" | "polite" | "off";

export interface ErrorStateAction {
  label: string;
  onClick: () => void;
}

/** An error summary's link: `href` is `#{field id}`, and following it moves focus to that field. */
export interface ErrorStateItem {
  label: string;
  href: string;
}

export interface ErrorStateProps {
  /**
   * CandleViewer's own words: a mapped class line, `LegError.message` or a problem's `detail`. Never the
   * exchange's `ret_msg` or a wire payload (E30-D03 D5, E30-D04 C9).
   */
  message: string;
  /** Default `error`. Sets the glyph, the tone and the default politeness. */
  severity?: ErrorSeverity;
  /** Default `panel`. */
  form?: ErrorStateForm;
  /** A heading over the message, e.g. an error summary's "Can't submit — 2 problems". */
  title?: string;
  /** The title's level; default 3, so it fits a panel's outline. */
  headingLevel?: HeadingLevel;
  /**
   * The title heading's id. The heading takes `tabindex="-1"`, so an error summary's host moves focus to it
   * after a failed submit (`document.getElementById(headingId)?.focus()`, E30-D02 D16).
   */
  headingId?: string;
  /** An error summary's links, one per field, in document order (E30-D02 D16). */
  items?: readonly ErrorStateItem[];
  /**
   * Overrides the severity's politeness (error assertive, warning polite): `polite` for an in-panel load
   * failure, `off` when another node already announced it (E05-D02 H14, H37).
   */
  live?: ErrorStateLive;
  /** A CMP-001 secondary button, first in the action row. */
  retry?: ErrorStateAction;
  /** A second CMP-001 secondary button after `retry`. */
  action?: ErrorStateAction;
  /** Technical detail (a code, a correlation id) behind a "Technical details" disclosure; never in the live region. */
  details?: string;
}

/**
 * The glyph by severity. `error` is the registry's `lucide/circle-x`, the shape E30-D04 §3.3's PROPOSED
 * `icon/x-circle` names; a renamed registry entry re-points it here.
 */
const SEVERITY_GLYPH: Readonly<Record<ErrorSeverity, IconName>> = {
  error: "error",
  warning: "warning",
};

const SEVERITY_LIVE: Readonly<Record<ErrorSeverity, Exclude<ErrorStateLive, "off">>> = {
  error: "assertive",
  warning: "polite",
};

const roleOf = (live: ErrorStateLive): "status" | "alert" | undefined =>
  live === "off" ? undefined : live === "polite" ? "status" : "alert";

/** An in-page `#id` link moves focus to its field (as GOV.UK's error summary does); anything else navigates. */
function focusField(event: MouseEvent<HTMLAnchorElement>, href: string): void {
  if (!href.startsWith("#") || href.length < 2) return;
  const field = document.getElementById(decodeURIComponent(href.slice(1)));
  if (field === null) return;
  event.preventDefault();
  field.focus();
  field.scrollIntoView?.({ block: "center" });
}

/** "Technical details": an APG Disclosure over a selectable box with a CMP-033 copy. */
function Details({ text }: { text: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="cv-error-state__disclosure">
      <Button
        variant="ghost"
        size="sm"
        iconRight="chevron-down"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
      >
        Technical details
      </Button>
      <div id={id} className="cv-error-state__details" hidden={!open}>
        <code className="cv-error-state__details-text">{text}</code>
        <CopyButton value={text} label="Copy technical details" />
      </div>
    </div>
  );
}

/**
 * CMP-027 ErrorState: a panel, inline or banner error surface. Its words are their own live region, mounted
 * with the component and filled after mount so a failure is announced once; the buttons and the details sit
 * outside it. The `banner` form reuses CMP-028's box (`callout.css`) in the error or warning tone.
 */
export function ErrorState({
  message,
  severity = "error",
  form = "panel",
  title,
  headingLevel = 3,
  headingId,
  items = [],
  live,
  retry,
  action,
  details,
}: ErrorStateProps): JSX.Element {
  const politeness = live ?? SEVERITY_LIVE[severity];
  const role = roleOf(politeness);
  // A live region announces content inserted after it exists, so the words land one effect after mount.
  const [mounted, setMounted] = useState(role === undefined);
  useEffect(() => {
    setMounted(true);
  }, []);
  const banner = form === "banner";
  const buttons = [retry, action].filter((b): b is ErrorStateAction => b !== undefined);
  const content: ReactNode = mounted ? (
    <>
      {title === undefined ? null : (
        <Heading
          id={headingId}
          level={headingLevel}
          variant="heading-sm"
          tabIndex={-1}
          className="cv-error-state__title"
        >
          {title}
        </Heading>
      )}
      <p className={cx("cv-error-state__text", banner ? "cv-callout__title" : undefined)}>
        {message}
      </p>
      {items.length === 0 ? null : (
        <ul className="cv-error-state__items">
          {items.map((item) => (
            <li key={item.href}>
              <Link href={item.href} onClick={(e) => focusField(e, item.href)}>
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  ) : null;
  return (
    <div
      className={cx("cv-error-state", banner ? "cv-callout" : undefined)}
      data-cmp="CMP-027"
      data-form={form}
      data-severity={severity}
      data-tone={banner ? (severity === "error" ? "danger" : "warning") : undefined}
      data-placement={banner ? "inline" : undefined}
    >
      <span className={cx("cv-error-state__glyph", banner ? "cv-callout__glyph" : undefined)}>
        <Icon name={SEVERITY_GLYPH[severity]} {...(form === "panel" ? { size: "lg" } : {})} />
      </span>
      <div className={cx("cv-error-state__main", banner ? "cv-callout__main" : undefined)}>
        <div
          className={cx("cv-error-state__message", banner ? "cv-callout__message" : undefined)}
          role={role}
          aria-live={role === undefined ? undefined : politeness}
          aria-atomic={role === undefined ? undefined : true}
        >
          {content}
        </div>
        {buttons.length === 0 ? null : (
          <div
            className={cx("cv-error-state__actions", banner ? "cv-callout__actions" : undefined)}
          >
            {buttons.map((b) => (
              <Button
                key={b.label}
                variant="secondary"
                size={form === "inline" ? "sm" : "md"}
                onClick={() => b.onClick()}
              >
                {b.label}
              </Button>
            ))}
          </div>
        )}
        {details === undefined ? null : <Details text={details} />}
      </div>
    </div>
  );
}

export type InlineErrorProps = Omit<ErrorStateProps, "form">;

/** CMP-027 InlineError: the `inline` form, one row at the point of action. */
export function InlineError(props: InlineErrorProps): JSX.Element {
  return <ErrorState {...props} form="inline" />;
}
