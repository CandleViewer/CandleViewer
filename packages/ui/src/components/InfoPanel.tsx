import {
  useEffect,
  useId,
  useReducer,
  useRef,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Drawer, type DrawerSide } from "./Drawer.js";
import { ErrorState } from "./ErrorState.js";
import { Skeleton } from "./Skeleton.js";
import { cx } from "./internal/cx.js";
import { useControllable } from "./internal/useControllable.js";

/** `drawer`: a non-modal CMP-046; `inline`: an APG Disclosure inside its host that stays open while read (J17). */
export type InfoPanelVariant = "drawer" | "inline";

/** What the trigger spreads on its `button` (the CMP-227 chip, or any CMP-001 / native button). */
export interface InfoPanelTriggerProps {
  "aria-expanded": boolean;
  "aria-controls"?: string | undefined;
  /** The drawer form only: the chip opens a dialog (J18). */
  "aria-haspopup"?: "dialog";
  onClick: (event: MouseEvent<HTMLElement>) => void;
}

export interface InfoPanelProps {
  /** The detector's name: the heading, and the panel's name. */
  title: string;
  /** The static methodology: the plain-language summary first, the technical detail second. It shows at once. */
  content: ReactNode;
  /** The detector the panel explains; written as `data-detector` for the host's section routing. */
  relatedDetector?: string;
  /** Default `drawer` (J17). */
  variant?: InfoPanelVariant;
  /** Controlled open state; omit it (with `defaultOpen`) to let the panel hold it. */
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * Renders the trigger: a button that spreads these props. `Enter` and `Space` on a button are its click,
   * so the keyboard opens it with no handler of its own (J18).
   */
  trigger: (props: InfoPanelTriggerProps) => ReactNode;
  /** The current parameter values, under the methodology (`GET /api/v1/detectors/config`). */
  values?: ReactNode;
  /**
   * The values are loading: CMP-015 rows in their place and `aria-busy` on the part that loads (the
   * drawer's body; the inline form's values), so the static text stays readable.
   */
  loading?: boolean;
  /** The values failed to load: a polite CMP-027 inline error in their place; the static text stays. */
  error?: string;
  /** Retry for the error (a CMP-001 secondary button in the error's action row). */
  onRetry?: () => void;
  /** The drawer form's edge (default `right`) and width in px (default 480). */
  side?: DrawerSide;
  width?: number;
  /** The inline form's heading level (default 3, under its host's heading). */
  headingLevel?: 2 | 3 | 4 | 5 | 6;
  /** Where focus returns when the trigger is gone (the drawer form). */
  fallbackFocusRef?: RefObject<HTMLElement | null>;
  className?: string;
}

/** The trigger that controls `id`, found by its `aria-controls` (useId's colons make a selector awkward). */
const triggerOf = (id: string): HTMLElement | null =>
  [...document.querySelectorAll<HTMLElement>("[aria-controls]")].find(
    (element) => element.getAttribute("aria-controls") === id,
  ) ?? null;

/**
 * CMP-069: the methodology note behind every "(estimated)" value. `drawer`: a non-modal CMP-046 that
 * `Enter` / `Space` on the trigger opens with focus on its heading; `Esc` closes it and focus goes back to
 * the trigger; Tab past its last control moves on to the page and it stays open. `inline`: an APG
 * Disclosure under its trigger row that takes focus to its heading on open; the trigger, or `Esc` inside,
 * closes it, focus back on the trigger. The static text shows at once; the parameter values load under it
 * (`aria-busy`, CMP-015 rows), or fail as a polite CMP-027 with Retry.
 */
export function InfoPanel({
  title,
  content,
  relatedDetector,
  variant = "drawer",
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  trigger,
  values,
  loading = false,
  error,
  onRetry,
  side = "right",
  width,
  headingLevel = 3,
  fallbackFocusRef,
  className,
}: InfoPanelProps): JSX.Element {
  const id = useId();
  const panelId = `${id}-panel`;
  const headingId = `${id}-heading`;
  const [open, setHeld] = useControllable(openProp, defaultOpen);
  const triggerNode = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  /**
   * Set by the trigger, so the inline form takes focus on a user's open only (never at mount). The
   * trigger also forces a commit, so the effect below reads the flag on the very next render and clears
   * it whether or not a controlled host took the change: a later programmatic open never steals focus.
   */
  const opening = useRef(false);
  const [, rerender] = useReducer((count: number) => count + 1, 0);

  const change = (next: boolean): void => {
    setHeld(next);
    onOpenChange?.(next);
  };

  // Inline: a user's open moves focus to the heading (E12-D03 §6.4). Runs after every commit on purpose:
  // the trigger's own commit consumes the flag (see `opening`).
  useEffect(() => {
    if (!opening.current) return;
    opening.current = false;
    if (variant === "inline" && open) heading.current?.focus({ preventScroll: true });
  });

  /**
   * Inline: `Esc` inside closes it, focus back on the trigger (E12-D03 §6.4). A React handler on the
   * region: it runs after the handlers of the controls inside (an `Esc` one of them took, a
   * defaultPrevented one, stays its own) and before the overlay layer stack's document listener, so an
   * inline panel inside a Dialog or Drawer collapses first; the next `Esc` closes the overlay. Only a key
   * from the region's own DOM counts: a popover portalled out of it keeps its `Esc`.
   */
  const onRegionKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    if (event.key !== "Escape" || event.defaultPrevented || event.nativeEvent.isComposing) return;
    if (!(event.target instanceof Node) || !event.currentTarget.contains(event.target)) return;
    event.preventDefault();
    change(false);
    const back = triggerNode.current;
    (back?.isConnected === true ? back : triggerOf(panelId))?.focus();
  };

  const onTrigger = (event: MouseEvent<HTMLElement>): void => {
    triggerNode.current = event.currentTarget;
    opening.current = !open;
    rerender();
    change(!open);
  };

  const failed = error !== undefined && error !== "";
  const valuesPart = loading ? (
    <Skeleton shape="text" count={3} surface={variant === "drawer" ? "overlay" : "base"} />
  ) : failed ? (
    <ErrorState
      form="inline"
      message={error}
      live="polite"
      {...(onRetry === undefined ? {} : { retry: { label: "Retry", onClick: onRetry } })}
    />
  ) : (
    values
  );
  const parts = (
    <>
      <div className="cv-info-panel__content">{content}</div>
      {valuesPart === undefined || valuesPart === null ? null : (
        <div
          className="cv-info-panel__values"
          aria-busy={variant === "inline" && loading ? true : undefined}
        >
          {valuesPart}
        </div>
      )}
    </>
  );

  if (variant === "drawer") {
    return (
      <>
        {trigger({
          "aria-expanded": open,
          "aria-controls": open ? panelId : undefined,
          "aria-haspopup": "dialog",
          onClick: onTrigger,
        })}
        <Drawer
          open={open}
          modal={false}
          title={title}
          id={panelId}
          side={side}
          {...(width === undefined ? {} : { width })}
          busy={loading}
          fallbackFocusRef={fallbackFocusRef ?? triggerNode}
          onOpenChange={(next) => change(next)}
        >
          <div
            className={cx("cv-info-panel", className)}
            data-cmp="CMP-069"
            data-variant="drawer"
            data-detector={relatedDetector}
          >
            {parts}
          </div>
        </Drawer>
      </>
    );
  }

  const Tag = `h${String(headingLevel)}` as "h2" | "h3" | "h4" | "h5" | "h6";
  return (
    <>
      {trigger({ "aria-expanded": open, "aria-controls": panelId, onClick: onTrigger })}
      {open ? (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- the Disclosure's `Esc` (E12-D03 §6.4) bubbling from the controls inside; the region is no widget (see onRegionKeyDown)
        <section
          id={panelId}
          aria-labelledby={headingId}
          className={cx("cv-info-panel", className)}
          data-cmp="CMP-069"
          data-variant="inline"
          data-detector={relatedDetector}
          onKeyDown={onRegionKeyDown}
        >
          <Tag ref={heading} id={headingId} className="cv-info-panel__title" tabIndex={-1}>
            {title}
          </Tag>
          {parts}
        </section>
      ) : null}
    </>
  );
}
