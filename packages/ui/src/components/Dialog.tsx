import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { IconButton } from "./IconButton.js";
import { cx } from "./internal/cx.js";
import { trapTab, useFocusTrap, useReturnFocus, visibleTabbables } from "./internal/focusTrap.js";
import { useInertOutside } from "./internal/inertOutside.js";
import { LayerPortalProvider, useLayer, useLayerPortal } from "./internal/layers.js";
import { useExitTransition } from "./internal/motion.js";
import { useReadableScroll } from "./internal/readableScroll.js";
import { useScrollLock } from "./internal/scrollLock.js";

/** Maximum widths 420 / 560 / 960 px (H17). */
export type DialogSize = "sm" | "md" | "lg";
/** `alertdialog` asks for an explicit choice: no close button, and a scrim press does nothing (H17). */
export type DialogRole = "dialog" | "alertdialog";
/** Why the dialog asks to close; a host with unsaved changes opens its discard confirm instead (H36). */
export type DialogCloseReason = "escape" | "scrim" | "close";

export interface DialogProps {
  /** Controlled: the host owns the open state. */
  open: boolean;
  /**
   * Called with `false` and the reason on `Esc`, a scrim press (`dialog` only) and the close button.
   * A host may keep it open: a lock ignores `Esc` (H22), a dirty form asks first (H36).
   */
  onOpenChange: (open: boolean, reason: DialogCloseReason) => void;
  /** The heading (`h2`), and the name unless `aria-label` is given; the close button is "Close {title}". */
  title: string;
  /** The description under the title, linked by `aria-describedby`. */
  description?: ReactNode;
  /** Maximum width (default `md`). */
  size?: DialogSize;
  /** Default `dialog`; `alertdialog` for a confirm or a modal the system raises (H35). */
  role?: DialogRole;
  /** The host's name, over the title (SCR-076's "Confirm order - BTCUSDT - LIVE - Main"). */
  "aria-label"?: string;
  /** More description ids, after the description's: a CMP-044 restatement in the body. */
  "aria-describedby"?: string;
  /**
   * Takes focus on open; without it the first field, else the heading (conventions 32). An
   * `alertdialog` passes its Cancel or least-destructive choice here (H32). A ref on an element that
   * is no tab stop (a wrapper around a CMP-001, which takes no ref) focuses its first tab stop.
   */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /**
   * Where focus returns when the opener is gone (E40-D02's bell). The return never picks `body`, but
   * with neither the opener nor this ref able to take focus, focus stays where the browser left it:
   * a host whose opener can go passes a fallback that outlives it.
   */
  fallbackFocusRef?: RefObject<HTMLElement | null>;
  /**
   * A request is in flight: `aria-busy` on the card; `Esc` still closes the view and cancels nothing
   * (H22). The dialog does not drive its footer: the host sets its primary action's `loading` itself.
   */
  busy?: boolean;
  /** The footer: a CMP-001 row, `Cancel` first, the primary or danger action last. */
  footer?: ReactNode;
  className?: string;
  /** The body: the host's content; it scrolls between the header and the footer. */
  children?: ReactNode;
}

const FIELD = [
  "input",
  "select",
  "textarea",
  '[contenteditable]:not([contenteditable="false"])',
  '[role="combobox"]',
  '[role="searchbox"]',
  '[role="spinbutton"]',
  '[role="slider"]',
  '[role="textbox"]',
].join(",");

const warnAlertFocus = (): void => {
  if (import.meta.env?.DEV)
    console.warn(
      "Dialog: an alertdialog takes focus on its Cancel or least-destructive choice; pass initialFocusRef (H32).",
    );
};

/**
 * CMP-043: a modal dialog (APG Dialog (Modal); Alert Dialog for `role="alertdialog"`), portalled into
 * its own layer over a scrim. Opening takes focus to `initialFocusRef`, else the first field, else
 * the heading; Tab cycles inside the card; `Esc` closes the topmost layer only (a tooltip or a popover
 * inside goes first); closing returns focus to the opener, else `fallbackFocusRef`. While open, the
 * page under it is inert (spared: `data-cv-inert-exempt` regions) and does not scroll. The scrim
 * fades in while the card is a cut (H21); the exit fades with no pointer events; reduced motion is a
 * cut both ways. Overlays inside it (Popover, Tooltip, a nested Dialog) portal into its layer.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  size = "md",
  role = "dialog",
  "aria-label": label,
  "aria-describedby": describedBy,
  initialFocusRef,
  fallbackFocusRef,
  busy = false,
  footer,
  className,
  children,
}: DialogProps): JSX.Element | null {
  const id = useId();
  const titleId = `${id}-title`;
  const descriptionId = `${id}-description`;
  const parent = useLayerPortal();
  const [host] = useState(() =>
    typeof document === "undefined" ? null : document.createElement("div"),
  );
  const hostRef = useRef(host);
  const card = useRef<HTMLDivElement | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const body = useRef<HTMLDivElement | null>(null);
  const lastInside = useRef<HTMLElement | null>(null);
  /** Whether the dialog was the topmost layer when the current scrim press began. */
  const scrimPress = useRef(false);
  // Open: render. Closed: keep the layer through the scrim's exit fade, then clear (at once when none runs).
  const rendered = useExitTransition(open, () => host?.querySelector(".cv-dialog__scrim"));
  /** A body that scrolls with nothing focusable in it is a Tab stop itself, so the keyboard can scroll it. */
  const readable = useReadableScroll(open, body);
  const initialFocus = useRef(initialFocusRef);
  initialFocus.current = initialFocusRef;
  /** Read at open only: a role change while open does not move focus. */
  const latestRole = useRef(role);
  latestRole.current = role;
  const latestClose = useRef(onOpenChange);
  latestClose.current = onOpenChange;
  const close = (reason: DialogCloseReason): void => latestClose.current(false, reason);

  // The layer root is in the document only while the dialog renders (open, or fading out).
  useLayoutEffect(() => {
    if (!rendered || host === null || parent === null) return undefined;
    host.className = "cv-dialog-layer";
    host.setAttribute("data-cv-layer", "");
    parent.appendChild(host);
    return () => host.remove();
  }, [rendered, host, parent]);

  // Closing: the layer leaves the focus order and the pointer at once, and is read no more.
  useLayoutEffect(() => {
    if (host === null) return;
    if (open) host.removeAttribute("inert");
    else host.setAttribute("inert", "");
    host.setAttribute("data-state", open ? "open" : "closing");
  }, [open, host]);

  const layer = useLayer(open, { element: hostRef, modal: true, onEscape: () => close("escape") });
  // Order matters: the guard's cleanup runs before focus returns; the opener is read before the page
  // goes inert (which would blur it).
  useFocusTrap(open, {
    container: card,
    allow: (node) => (host?.contains(node) ?? false) || layer.inLayerAbove(node),
    lastInside,
  });
  useReturnFocus(open, hostRef, fallbackFocusRef);
  useInertOutside(open, hostRef);
  useScrollLock(open);

  // Focus in on open (conventions 32, H32).
  useEffect(() => {
    const surface = card.current;
    if (!open || surface === null) return;
    const alert = latestRole.current === "alertdialog";
    const ref = initialFocus.current?.current ?? undefined;
    const given = ref === undefined || ref.tabIndex >= 0 ? ref : (visibleTabbables(ref)[0] ?? ref);
    if (given === undefined && alert) warnAlertFocus();
    const field =
      alert || body.current === null
        ? undefined
        : visibleTabbables(body.current).find((element) => element.matches(FIELD));
    const first = given ?? field ?? heading.current ?? surface;
    first.focus({ preventScroll: true });
    lastInside.current = first;
  }, [open]);

  // The card's own listeners: the Tab trap, and the last focused element for the guard.
  useEffect(() => {
    const surface = card.current;
    if (!open || surface === null) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => trapTab(event, surface);
    const onFocusIn = (event: FocusEvent): void => {
      if (event.target instanceof HTMLElement) lastInside.current = event.target;
    };
    surface.addEventListener("keydown", onKeyDown);
    surface.addEventListener("focusin", onFocusIn);
    return () => {
      surface.removeEventListener("keydown", onKeyDown);
      surface.removeEventListener("focusin", onFocusIn);
    };
  }, [open]);

  if (host === null || !rendered) return null;

  const labelled = label === undefined;
  const hasDescription = description !== undefined && description !== null && description !== false;
  const content = (
    <LayerPortalProvider value={host}>
      <div
        className="cv-dialog__scrim"
        aria-hidden="true"
        onPointerDown={() => {
          scrimPress.current = layer.isTopmost();
        }}
        onClick={() => {
          const topmost = scrimPress.current;
          scrimPress.current = false;
          // A press on the scrim is Cancel for a dialog; an alertdialog asks for a choice (conventions 31).
          if (topmost && role === "dialog") close("scrim");
        }}
      />
      <div
        ref={card}
        role={role}
        aria-modal="true"
        aria-label={label}
        aria-labelledby={labelled ? titleId : undefined}
        aria-describedby={cx(hasDescription && descriptionId, describedBy) || undefined}
        aria-busy={busy ? true : undefined}
        tabIndex={-1}
        className={cx("cv-dialog", className)}
        data-cmp="CMP-043"
        data-size={size}
        data-role={role}
        data-busy={busy ? "" : undefined}
      >
        <div className="cv-dialog__header">
          <div className="cv-dialog__titles">
            <h2 ref={heading} id={titleId} className="cv-dialog__title" tabIndex={-1}>
              {title}
            </h2>
            {hasDescription ? (
              <p id={descriptionId} className="cv-dialog__description">
                {description}
              </p>
            ) : null}
          </div>
          {role === "dialog" ? (
            <IconButton
              icon="close"
              label={`Close ${title}`}
              variant="ghost"
              onClick={() => close("close")}
            />
          ) : null}
        </div>
        <div
          ref={body}
          className="cv-dialog__body"
          tabIndex={readable ? 0 : undefined}
          aria-labelledby={readable ? (labelled ? titleId : undefined) : undefined}
          aria-label={readable && !labelled ? label : undefined}
          role={readable ? "group" : undefined}
        >
          {children}
        </div>
        {footer === undefined || footer === null ? null : (
          <div className="cv-dialog__footer">{footer}</div>
        )}
      </div>
    </LayerPortalProvider>
  );
  return createPortal(content, host);
}
