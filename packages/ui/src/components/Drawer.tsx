import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
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
import { tabStopAfter } from "./internal/tabbable.js";
import { useNarrowViewport } from "./internal/useNarrowViewport.js";

/** The edge it slides in from. */
export type DrawerSide = "right" | "left";
/** Why the drawer asks to close (as CMP-043's); `scrim` is a modal drawer's only. */
export type DrawerCloseReason = "escape" | "scrim" | "close";

export interface DrawerProps {
  /** Controlled: the host owns the open state. */
  open: boolean;
  /** Called with `false` and the reason on `Esc`, a scrim press (modal only) and the close button. */
  onOpenChange: (open: boolean, reason: DrawerCloseReason) => void;
  /** The heading (`h2`), and the name unless `aria-label` is given; the close button is "Close {title}". */
  title: string;
  /** Default `right`. */
  side?: DrawerSide;
  /**
   * Default `true`: over the scrim, the page inert, Tab cycling inside. `false` beside a live chart: a
   * `role="dialog"` without `aria-modal` at `elevation.popover`, no scrim, and Tab flows on to the page
   * after its opener (H31). At a viewport of 720 CSS px or less it covers the page, so it then acts as modal
   * while open (the scrim, the trap, the inert page, `aria-modal`): E05-D02 conventions 39, ruling A of #5144
   * (ledger row A54).
   */
  modal?: boolean;
  /** The host's name, over the title (SCR-077's "Order rejected - BTCUSDT - LIVE - Main"). */
  "aria-label"?: string;
  /** Takes focus on open; without it the heading (conventions 32: the body is content to read). */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Where focus returns, and where a non-modal drawer's Tab path starts, when the opener is gone. */
  fallbackFocusRef?: RefObject<HTMLElement | null>;
  /** Content is loading: `aria-busy` on the body; the host renders its CMP-015 rows. */
  busy?: boolean;
  /** The panel's width in CSS px, host data (default 480); the full width at a viewport of 720 px or less. */
  width?: number;
  /** An optional sticky footer: a CMP-001 row. */
  footer?: ReactNode;
  /** The panel's id, for the opener's `aria-controls`. */
  id?: string;
  className?: string;
  children?: ReactNode;
}

/** An element focus may move to: still in the document and not under an inert page. */
const reachable = (element: HTMLElement | null | undefined): element is HTMLElement =>
  element !== null &&
  element !== undefined &&
  element.isConnected &&
  element.closest("[inert]") === null;

/**
 * CMP-046: a side panel, portalled into its own layer. Modal (default): APG Dialog (Modal) over a scrim,
 * the page inert and not scrolling, Tab cycling inside. Non-modal: a `role="dialog"` without
 * `aria-modal`, no scrim, the page live; it follows its opener in the Tab order (Tab from the opener goes
 * in, Tab past its last control goes on to the page after the opener, Shift+Tab before its first goes
 * back to the opener) and stays open when focus leaves it; `Esc` closes it while focus is inside. With
 * neither the opener nor `fallbackFocusRef` reachable it has no anchor: Tab keeps the browser's order,
 * and the drawer, portalled last in `body`, passes Tab on past the page. Both:
 * focus to `initialFocusRef`, else the heading; `Esc` and Close return focus to the opener, else
 * `fallbackFocusRef`. It slides in opaque from the first frame and out over `fast`; reduced motion is a
 * cut. Overlays inside it portal into its layer.
 */
export function Drawer({
  open,
  onOpenChange,
  title,
  side = "right",
  modal = true,
  "aria-label": label,
  initialFocusRef,
  fallbackFocusRef,
  busy = false,
  width,
  footer,
  id: panelId,
  className,
  children,
}: DrawerProps): JSX.Element | null {
  const id = useId();
  // Conventions 39 / #5144 ruling A (ledger row A54): full width at the narrow breakpoint, a non-modal drawer
  // covers every page stop Tab could reach (SC 2.4.11), so it is modal while open there. Every modal
  // behaviour below reads this, not the prop; the prop keeps its meaning on wide screens.
  const narrow = useNarrowViewport();
  const isModal = modal || narrow;
  const titleId = `${id}-title`;
  const parent = useLayerPortal();
  const [host] = useState(() =>
    typeof document === "undefined" ? null : document.createElement("div"),
  );
  const hostRef = useRef(host);
  const panel = useRef<HTMLDivElement | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const body = useRef<HTMLDivElement | null>(null);
  const lastInside = useRef<HTMLElement | null>(null);
  /** The element that held focus at open: the start of a non-modal drawer's Tab path. */
  const opener = useRef<HTMLElement | null>(null);
  /** Whether the drawer was the topmost layer when the current scrim press began. */
  const scrimPress = useRef(false);
  const rendered = useExitTransition(open, () => panel.current);
  const readable = useReadableScroll(open, body);
  const initialFocus = useRef(initialFocusRef);
  initialFocus.current = initialFocusRef;
  const fallback = useRef(fallbackFocusRef);
  fallback.current = fallbackFocusRef;
  const latestClose = useRef(onOpenChange);
  latestClose.current = onOpenChange;
  const close = (reason: DrawerCloseReason): void => latestClose.current(false, reason);

  // The layer root is in the document only while the drawer renders (open, or sliding out).
  useLayoutEffect(() => {
    if (!rendered || host === null || parent === null) return undefined;
    host.className = "cv-drawer-layer";
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

  // The opener, read before focus moves in (and before a modal drawer's inert page would blur it).
  useLayoutEffect(() => {
    if (!open) return;
    const active = document.activeElement;
    if (active !== null && (host?.contains(active) ?? false)) return;
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, [open, host]);

  /** Where a non-modal drawer's Tab path is anchored: the opener, else the host's fallback (refs only). */
  const [anchor] = useState(
    () => (): HTMLElement | undefined =>
      [opener.current, fallback.current?.current].find(reachable),
  );

  const layer = useLayer(open, {
    element: hostRef,
    modal: isModal,
    onEscape: () => close("escape"),
    // Non-modal: `Esc` is the drawer's only while focus is inside it; on the page it stays the page's.
    claimsEscape: isModal ? undefined : () => host?.contains(document.activeElement) ?? false,
  });
  // Order matters (as CMP-043's): the guard's cleanup runs before focus returns; the opener is read
  // before the page goes inert.
  useFocusTrap(open && isModal, {
    container: panel,
    allow: (node) => (host?.contains(node) ?? false) || layer.inLayerAbove(node),
    lastInside,
  });
  useReturnFocus(open, hostRef, fallbackFocusRef);
  useInertOutside(open && isModal, hostRef);
  useScrollLock(open && isModal);

  // Focus in on open (conventions 32): `initialFocusRef`, else the heading.
  useEffect(() => {
    const surface = panel.current;
    if (!open || surface === null) return;
    const ref = initialFocus.current?.current ?? undefined;
    const given = ref === undefined || ref.tabIndex >= 0 ? ref : (visibleTabbables(ref)[0] ?? ref);
    const first = given ?? heading.current ?? surface;
    first.focus({ preventScroll: true });
    lastInside.current = first;
  }, [open]);

  // A resize to narrow while open: the page goes inert, so focus left on it is brought in (the last stop
  // inside, else the heading); focus already inside stays.
  useEffect(() => {
    const surface = panel.current;
    if (!open || !isModal || surface === null || (host?.contains(document.activeElement) ?? false))
      return;
    const target = lastInside.current?.isConnected === true ? lastInside.current : heading.current;
    (target ?? surface).focus({ preventScroll: true });
  }, [open, isModal, host]);

  // The panel's own listeners: modal, the Tab trap; non-modal, the Tab path out to the page.
  const latestModal = useRef(isModal);
  latestModal.current = isModal;
  useEffect(() => {
    const surface = panel.current;
    if (!open || surface === null) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Tab" || event.defaultPrevented) return;
      if (latestModal.current) {
        trapTab(event, surface);
        return;
      }
      const items = visibleTabbables(surface);
      const active = document.activeElement;
      const onItem = items.some((item) => item === active);
      const from = anchor();
      // No anchor (opener and fallback both gone): the browser's own order, documented above.
      if (from === undefined) return;
      if (event.shiftKey && (active === items[0] || !onItem)) {
        event.preventDefault();
        from.focus();
      } else if (!event.shiftKey && active === items[items.length - 1]) {
        const next = tabStopAfter(from, host);
        if (next === undefined) return;
        event.preventDefault();
        next.focus();
      }
    };
    const onFocusIn = (event: FocusEvent): void => {
      if (event.target instanceof HTMLElement) lastInside.current = event.target;
    };
    surface.addEventListener("keydown", onKeyDown);
    surface.addEventListener("focusin", onFocusIn);
    return () => {
      surface.removeEventListener("keydown", onKeyDown);
      surface.removeEventListener("focusin", onFocusIn);
    };
  }, [open, host, anchor]);

  // Non-modal: the drawer sits after its opener in the Tab order. Tab on the opener goes in; Shift+Tab
  // on the page's next stop after the opener comes back in at its last control.
  useEffect(() => {
    if (!open || isModal) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      const surface = panel.current;
      const from = anchor();
      if (event.key !== "Tab" || event.defaultPrevented || surface === null || from === undefined)
        return;
      const items = visibleTabbables(surface);
      if (!event.shiftKey && event.target === from) {
        event.preventDefault();
        (items[0] ?? heading.current ?? surface).focus();
      } else if (event.shiftKey && event.target === tabStopAfter(from, host)) {
        event.preventDefault();
        (items[items.length - 1] ?? heading.current ?? surface).focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, isModal, host, anchor]);

  if (host === null || !rendered) return null;

  const labelled = label === undefined;
  const sized = width !== undefined && Number.isFinite(width) && width > 0;
  const style = sized
    ? ({ "--cv-drawer-width": `${String(width)}px` } as CSSProperties)
    : undefined;
  const content = (
    <LayerPortalProvider value={host}>
      {isModal ? (
        <div
          className="cv-drawer__scrim"
          aria-hidden="true"
          onPointerDown={() => {
            scrimPress.current = layer.isTopmost();
          }}
          onClick={() => {
            const topmost = scrimPress.current;
            scrimPress.current = false;
            // A press on the scrim is Cancel (conventions 31).
            if (topmost) close("scrim");
          }}
        />
      ) : null}
      <div
        ref={panel}
        id={panelId}
        role="dialog"
        aria-modal={isModal ? true : undefined}
        aria-label={label}
        aria-labelledby={labelled ? titleId : undefined}
        tabIndex={-1}
        className={cx("cv-drawer", className)}
        style={style}
        data-cmp="CMP-046"
        data-side={side}
        data-modal={isModal ? "" : undefined}
      >
        <div className="cv-drawer__header">
          <h2 ref={heading} id={titleId} className="cv-drawer__title" tabIndex={-1}>
            {title}
          </h2>
          <IconButton
            icon="close"
            label={`Close ${title}`}
            variant="ghost"
            onClick={() => close("close")}
          />
        </div>
        <div
          ref={body}
          className="cv-drawer__body"
          aria-busy={busy ? true : undefined}
          tabIndex={readable ? 0 : undefined}
          aria-labelledby={readable && labelled ? titleId : undefined}
          aria-label={readable && !labelled ? label : undefined}
          role={readable ? "group" : undefined}
        >
          {children}
        </div>
        {footer === undefined || footer === null ? null : (
          <div className="cv-drawer__footer">{footer}</div>
        )}
      </div>
    </LayerPortalProvider>
  );
  return createPortal(content, host);
}
