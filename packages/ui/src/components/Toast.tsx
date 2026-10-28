import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type JSX,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Button } from "./Button.js";
import { IconButton } from "./IconButton.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";
import { modalLayerOpen, watchLayers } from "./internal/layers.js";
import { tabbables } from "./internal/tabbable.js";

export type ToastTone = "info" | "success" | "warning" | "danger";

/** Where a toast's sentence is spoken: CMP-212's polite or assertive region (H28). */
export type ToastPoliteness = "polite" | "assertive";

/** How a toast left: its dismiss button, `Esc` on a focused toast, or its timer. */
export type ToastDismissReason = "dismiss" | "escape" | "timeout";

export interface ToastAction {
  label: string;
  onClick: () => void;
  /** CMP-001 `secondary` (default) or `ghost`, compact. */
  variant?: "secondary" | "ghost";
  /** The request is in flight: busy, not a gate (conventions 37). */
  loading?: boolean;
  /**
   * T2 (E09-D09 §2.2): the action stays focusable with `aria-disabled`, the `lock` leads its label, and its
   * description is the one reason line under the actions, shared by every action gated for the same sentence.
   */
  disabledReason?: string;
}

/** A local, reversible action's Undo (H27); never an order cancel's. */
export interface ToastUndo {
  /** Default "Undo". */
  label?: string;
  onUndo: () => void;
  /** The line that replaces Undo once its window has closed, e.g. "EMA 21 removed." */
  outcome: string;
}

export interface ToastProps {
  title: string;
  /** The body: clamped to two lines (three at comfortable density); the full text stays in the DOM. */
  description?: string | undefined;
  /** The tone's word and the kind ("Warning · Alert"). */
  kicker?: string | undefined;
  /** A numeric line (symbol, timeframe, time) in `type.num.sm`. */
  meta?: string | undefined;
  /** Default `info`. */
  tone?: ToastTone | undefined;
  actions?: readonly ToastAction[] | undefined;
  undo?: ToastUndo | undefined;
  /** The Undo window has closed: the outcome line replaces the Undo button. */
  undoClosed?: boolean;
  /** Default true. The dismiss button is never gated. */
  dismissible?: boolean | undefined;
  /** The dismiss button or `Esc` on a focused toast; the host removes the toast. */
  onDismiss?: (reason: Exclude<ToastDismissReason, "timeout">) => void;
  /** A press on a gated action: the host speaks the reason once, politely (the region routes it to `announce`). */
  onRefuse?: (reason: string) => void;
}

/** Each tone's glyph (anatomy): colour is never the only signal, the glyph and the kicker carry the tone. */
const TONE_GLYPH: Readonly<Record<ToastTone, IconName>> = {
  info: "info",
  success: "check",
  warning: "warning",
  danger: "danger",
};

const reasonOf = (action: ToastAction): string | undefined => {
  const trimmed = action.disabledReason?.trim();
  return trimmed === undefined || trimmed === "" ? undefined : trimmed;
};

/**
 * A gated action (conventions 36): CMP-001's T2 look, described by the shared notice instead of its own line.
 * CMP-001 renders one reason line per button, so this mirrors its gated markup (`cv-control`, `cv-button`,
 * `data-gated`, `cv-button__glyph`); a unit test pins the two to the same classes and data attributes, so a change
 * to CMP-001's markup fails here rather than diverging silently.
 */
function GatedAction({
  action,
  noticeId,
  onRefuse,
}: {
  readonly action: ToastAction;
  readonly noticeId: string;
  readonly onRefuse: () => void;
}): JSX.Element {
  const ring = useFocusRing();
  const refuse = (event: MouseEvent<HTMLButtonElement>): void => {
    // Enter and Space reach here as clicks: nothing changes but the one polite announcement.
    event.preventDefault();
    onRefuse();
  };
  return (
    <button
      type="button"
      className={cx("cv-control", ring.className, "cv-button")}
      data-variant={action.variant ?? "secondary"}
      data-size="sm"
      data-gated=""
      aria-disabled
      aria-describedby={noticeId}
      onClick={refuse}
    >
      <span className="cv-button__glyph">
        <Icon name="lock" />
      </span>
      <span className="cv-button__label">{action.label}</span>
    </button>
  );
}

/**
 * CMP-045 Toast: a `group` named by its title on the overlay surface, with the tone's `.default` start edge and its
 * `.strong` glyph (H6). It is never its own live region (H28): the toast region writes its sentence into the
 * shell's announcer. It never takes focus; `Esc` on a focused toast dismisses it. Gated actions share one reason line
 * (one notice, many pointers); an Undo gives way to its outcome line when its window closes (H27).
 */
export function Toast({
  title,
  description,
  kicker,
  meta,
  tone = "info",
  actions = [],
  undo,
  undoClosed = false,
  dismissible = true,
  onDismiss,
  onRefuse,
}: ToastProps): JSX.Element {
  const id = useId();
  const titleId = `${id}-title`;
  const reasons = [...new Set(actions.map(reasonOf).filter((r): r is string => r !== undefined))];
  const noticeId = (reason: string): string => `${id}-notice-${reasons.indexOf(reason)}`;
  const root = useRef<HTMLDivElement | null>(null);
  const escape = useRef<(() => void) | null>(null);
  escape.current = dismissible && onDismiss !== undefined ? () => onDismiss("escape") : null;
  // `Esc` on a focused toast, before the layer stack's document listener: a native listener on the group, as the
  // group is not a widget. A tooltip echo over the focused control takes it first (conventions 32). It stops the
  // event, so React-delegated `Esc` handlers on descendants (a nested menu, an action's own handler) never see it:
  // a toast holds only buttons today, so `Esc` has one meaning here. A descendant that needs its own `Esc` must
  // handle it natively and call `preventDefault()`, which this listener honours.
  useEffect(() => {
    const group = root.current;
    if (group === null) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      const dismiss = escape.current;
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || dismiss === null)
        return;
      event.preventDefault();
      event.stopPropagation();
      dismiss();
    };
    group.addEventListener("keydown", onKeyDown);
    return () => group.removeEventListener("keydown", onKeyDown);
  }, []);
  const showUndo = undo !== undefined && !undoClosed;
  const hasRow = actions.length > 0 || showUndo;
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className="cv-toast"
      data-cmp="CMP-045"
      data-tone={tone}
      ref={root}
    >
      <span className="cv-toast__glyph">
        <Icon name={TONE_GLYPH[tone]} />
      </span>
      <div className="cv-toast__main">
        {kicker === undefined ? null : <p className="cv-toast__kicker">{kicker}</p>}
        <p id={titleId} className="cv-toast__title">
          {title}
        </p>
        {description === undefined ? null : <p className="cv-toast__body">{description}</p>}
        {meta === undefined ? null : <p className="cv-toast__meta">{meta}</p>}
        {hasRow ? (
          <div className="cv-toast__actions">
            {showUndo ? (
              <Button size="sm" onClick={() => undo.onUndo()}>
                {undo.label ?? "Undo"}
              </Button>
            ) : null}
            {actions.map((action, index) => {
              const reason = reasonOf(action);
              const key = `${index}-${action.label}`;
              return reason === undefined ? (
                <Button
                  key={key}
                  size="sm"
                  variant={action.variant ?? "secondary"}
                  loading={action.loading === true}
                  onClick={() => action.onClick()}
                >
                  {action.label}
                </Button>
              ) : (
                <GatedAction
                  key={key}
                  action={action}
                  noticeId={noticeId(reason)}
                  onRefuse={() => onRefuse?.(reason)}
                />
              );
            })}
          </div>
        ) : null}
        {reasons.map((reason) => (
          <p key={reason} id={noticeId(reason)} className="cv-toast__notice">
            {reason}
          </p>
        ))}
        {undo !== undefined && undoClosed ? (
          <p className="cv-toast__outcome">{undo.outcome}</p>
        ) : null}
      </div>
      {dismissible && onDismiss !== undefined ? (
        <IconButton
          icon="close"
          label={`Dismiss ${title}`}
          variant="ghost"
          onClick={() => onDismiss("dismiss")}
        />
      ) : null}
    </div>
  );
}

/** The shell's one announcer (E17-D02 §11): `key` tells a repeat of the same words apart, so each is spoken. */
export type ToastAnnounce = (politeness: ToastPoliteness, text: string, key: string) => void;

export interface ToastItem extends Omit<ToastProps, "onDismiss" | "onRefuse" | "undoClosed"> {
  /** Stable for the toast's life: its announcement, timer and focus hand-off key on it. */
  id: string;
  /** Overrides the region's duration for this toast; `null` is "until dismissed". */
  durationMs?: number | null;
  /**
   * Overrides the timing rule (H26): `true` never times out, `false` follows the duration even with an action. An
   * Undo toast ignores `false`: it never times out, only its Undo window closes (H27).
   */
  persistent?: boolean;
  /** An error that is not `danger` in tone: persistent and assertive by default, like `danger`. */
  error?: boolean;
  /** Overrides the default: assertive for `danger` or an error, else polite (H28). */
  politeness?: ToastPoliteness;
}

export interface ToastRegionProps {
  /** The stack, in the order it renders; the host owns the queue and removes a toast on `onDismiss`. */
  toasts: readonly ToastItem[];
  onDismiss: (id: string, reason: ToastDismissReason) => void;
  /** Writes a sentence into the shell's pre-rendered polite or assertive region; the region never renders one. */
  announce: ToastAnnounce;
  /** The user's toast duration (5 / 10 / 20 s); `null` is "until dismissed". Default 5,000 ms. */
  durationMs?: number | null;
  /** The region's accessible name. Default "Notifications". */
  label?: string;
}

const DEFAULT_DURATION_MS = 5000;

/** H26: persistent with an action, an error or `danger`; else timed. An explicit `persistent` wins. */
const isPersistent = (toast: ToastItem): boolean =>
  toast.persistent ??
  ((toast.actions?.length ?? 0) > 0 || toast.tone === "danger" || toast.error === true);

const politenessOf = (toast: ToastItem): ToastPoliteness =>
  toast.politeness ?? (toast.tone === "danger" || toast.error === true ? "assertive" : "polite");

/** The sentence spoken once on arrival: the kicker, the title and the body. */
const sentenceOf = (toast: ToastItem): string =>
  [toast.kicker, toast.title, toast.description]
    .filter((part): part is string => part !== undefined && part.trim() !== "")
    .join(". ");

/**
 * A timeout that pauses: while `paused` the remaining time is kept, and it runs on from there. `ms === null` runs
 * no timer; a change of `ms` starts the count again. It fires at most once per count: a host that keeps the toast
 * after `onFire` (an async removal) gets no second call when a later hover or focus change toggles `paused`.
 */
function usePausableTimeout(ms: number | null, paused: boolean, onFire: () => void): void {
  const fire = useRef(onFire);
  fire.current = onFire;
  const remaining = useRef<number | null>(ms);
  const forMs = useRef<number | null>(ms);
  const fired = useRef(false);
  useEffect(() => {
    if (forMs.current !== ms) {
      forMs.current = ms;
      remaining.current = ms;
      fired.current = false;
    }
    const left = remaining.current;
    if (fired.current || ms === null || left === null || paused) return undefined;
    const started = Date.now();
    const handle = setTimeout(
      () => {
        fired.current = true;
        remaining.current = 0;
        fire.current();
      },
      Math.max(0, left),
    );
    return () => {
      clearTimeout(handle);
      if (!fired.current) remaining.current = Math.max(0, left - (Date.now() - started));
    };
  }, [ms, paused]);
}

/** One toast in the stack, with its lifetime timer and its Undo window. */
function RegionToast({
  toast,
  duration,
  paused,
  announce,
  onDismiss,
}: {
  readonly toast: ToastItem;
  readonly duration: number | null;
  readonly paused: boolean;
  readonly announce: ToastAnnounce;
  readonly onDismiss: (reason: ToastDismissReason) => void;
}): JSX.Element {
  const { id, durationMs } = toast;
  const ms = durationMs === undefined ? duration : durationMs;
  const [undoClosed, setUndoClosed] = useState(false);
  const refusals = useRef(0);
  // An Undo toast persists; its Undo window follows the duration, then the outcome line (H27).
  const timed = toast.undo === undefined && !isPersistent(toast);
  usePausableTimeout(timed ? ms : null, paused, () => onDismiss("timeout"));
  usePausableTimeout(toast.undo !== undefined && !undoClosed ? ms : null, paused, () => {
    setUndoClosed(true);
    if (toast.undo !== undefined) announce("polite", toast.undo.outcome, `${id}:outcome`);
  });
  return (
    <li className="cv-toast-region__item" data-toast-id={id}>
      <Toast
        title={toast.title}
        description={toast.description}
        kicker={toast.kicker}
        meta={toast.meta}
        tone={toast.tone}
        actions={toast.actions}
        undo={toast.undo}
        dismissible={toast.dismissible}
        undoClosed={undoClosed}
        onDismiss={(reason) => onDismiss(reason)}
        onRefuse={(reason) => {
          refusals.current += 1;
          announce("polite", reason, `${id}:refuse:${refusals.current}`);
        }}
      />
    </li>
  );
}

const subscribeLayers = (onChange: () => void): (() => void) => watchLayers(onChange);
const noModal = (): boolean => false;

/**
 * The toast region (#266 slice 7; CMP-212's count, storm summary and "Focus toasts" come later): one portalled
 * stack, named "Notifications". Each toast is announced once on arrival through `announce`, politely, or
 * assertively for `danger` or an error; nothing here takes focus. The timing rule (H26): a toast with an action,
 * an error or `danger` persists, any other closes after the duration; no countdown bar. Every timer pauses while
 * the pointer is over the stack, while focus is in it, and while a modal layer is open. Under a modal layer the
 * stack stays visible but inert: the region is a child of `body`, so the layer's inert-outside pass (conventions 31)
 * covers it and this component sets no `inert` of its own. `Esc` on a focused toast dismisses it and moves focus to
 * the next toast, else back where it came from; a focused toast the host removes by itself also gives focus back.
 * The region is a named landmark on purpose: it exists only while a toast shows, and it is what CMP-212's
 * "Focus toasts" will move to; it is never a live region (H28), since `announce` speaks for it.
 */
export function ToastRegion({
  toasts,
  onDismiss,
  announce,
  durationMs = DEFAULT_DURATION_MS,
  label = "Notifications",
}: ToastRegionProps): JSX.Element | null {
  const list = useRef<HTMLOListElement | null>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const modal = useSyncExternalStore(subscribeLayers, modalLayerOpen, noModal);
  /** Where focus was before it entered the stack: `Esc` on the last toast gives it back. */
  const cameFrom = useRef<HTMLElement | null>(null);
  /** Focus is in the stack, mirrored for the layout effect below without making it a dependency. */
  const focusIn = useRef(false);
  const spoken = useRef(new Set<string>());
  const latestAnnounce = useRef(announce);
  latestAnnounce.current = announce;

  // Each toast speaks once, on arrival; an id that leaves and comes back is a new arrival.
  useEffect(() => {
    const ids = new Set(toasts.map((toast) => toast.id));
    for (const id of spoken.current) if (!ids.has(id)) spoken.current.delete(id);
    for (const toast of toasts) {
      if (spoken.current.has(toast.id)) continue;
      spoken.current.add(toast.id);
      latestAnnounce.current(politenessOf(toast), sentenceOf(toast), toast.id);
    }
  }, [toasts]);

  // A focused toast removed by its host fires no blur, and an emptied stack no pointer leave: re-read after a change.
  // Focus that fell to the page body with the removed toast goes back where it came from.
  useLayoutEffect(() => {
    const root = list.current;
    if (root === null) setHovered(false);
    if (root !== null && root.contains(document.activeElement)) return;
    if (focusIn.current) {
      focusIn.current = false;
      const active = document.activeElement;
      const back = cameFrom.current;
      if ((active === null || active === document.body) && back?.isConnected === true) back.focus();
    }
    setFocused(false);
  }, [toasts]);

  const dismiss = useCallback(
    (id: string, reason: ToastDismissReason): void => {
      const items = [...(list.current?.children ?? [])].filter(
        (node): node is HTMLElement => node instanceof HTMLElement,
      );
      const index = items.findIndex((node) => node.dataset["toastId"] === id);
      const item = items[index];
      // Hand focus on before the toast goes, so it never falls to the page body.
      if (item?.contains(document.activeElement) === true) {
        const next = items[index + 1] ?? items[index - 1];
        const target = next === undefined ? undefined : tabbables(next)[0];
        const back = cameFrom.current;
        if (target !== undefined) target.focus();
        else if (back?.isConnected === true) back.focus();
      }
      onDismiss(id, reason);
    },
    [onDismiss],
  );

  if (typeof document === "undefined" || toasts.length === 0) return null;
  const paused = hovered || focused || modal;
  return createPortal(
    <section className="cv-toast-region" aria-label={label} data-paused={paused ? "" : undefined}>
      <ol
        ref={list}
        className="cv-toast-region__list"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) {
            cameFrom.current =
              event.relatedTarget instanceof HTMLElement ? event.relatedTarget : null;
          }
          focusIn.current = true;
          setFocused(true);
        }}
        onBlur={(event) => {
          if (event.currentTarget.contains(event.relatedTarget)) return;
          focusIn.current = false;
          setFocused(false);
        }}
      >
        {toasts.map((toast) => (
          <RegionToast
            key={toast.id}
            toast={toast}
            duration={durationMs}
            paused={paused}
            announce={announce}
            onDismiss={(reason) => dismiss(toast.id, reason)}
          />
        ))}
      </ol>
    </section>,
    document.body,
  );
}
