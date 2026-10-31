import { createContext, useCallback, useContext, useId, type JSX, type ReactNode } from "react";
import { announcePolite } from "../../theme/a11y.js";

export interface DisabledReasonAttrs {
  /** True when a non-empty reason is given: the control is gated (T2), not natively disabled. */
  readonly gated: boolean;
  /** Native `disabled`: only for a plain disabled control, so a gated one stays focusable. */
  readonly disabled: boolean;
  readonly reasonId: string;
  readonly reason: string | undefined;
  readonly ariaDisabled: true | undefined;
  readonly ariaDescribedBy: string | undefined;
  /**
   * The reason's node is the host's (`disabledReasonId`, E09-D09 §2.2 rendering 2a: a caption under the control, or
   * a read-only panel's one notice): the control points at it and renders no reason node of its own.
   */
  readonly external: boolean;
  /** True when the reason is a gate notice's sentence: the notice node is the description, so no echo or node. */
  readonly fromNotice: boolean;
}

/** The CMP-079 notice form: one notice node, by id, that carries `reason`; every gated control points at it. */
export interface GateNotice {
  readonly noticeId: string;
  readonly reason: string;
}

/**
 * Set by `RbacGate form="notice"` (E09-D09 §2.2 "one notice, many pointers"; E42-D03). Only a control whose own
 * reason is the notice's sentence follows it, so a descendant with another reason (a portalled menu item, say) keeps
 * its own node; context crosses portals, the sentence match does not.
 */
const GateNoticeContext = createContext<GateNotice | null>(null);

export function GateNoticeProvider({
  notice,
  children,
}: {
  readonly notice: GateNotice | null;
  readonly children: ReactNode;
}): JSX.Element {
  return <GateNoticeContext.Provider value={notice}>{children}</GateNoticeContext.Provider>;
}

/** The notice id when `reason` is the enclosing gate notice's sentence, else undefined. */
export function useGateNoticeFor(reason: string | undefined): string | undefined {
  const notice = useContext(GateNoticeContext);
  return notice !== null && reason !== undefined && reason === notice.reason.trim()
    ? notice.noticeId
    : undefined;
}

/**
 * The T2 contract (D02 conv. 3, D09 2.2): a reason wins over `disabled`; `aria-disabled`, never `disabled`. With
 * `hostReasonId` the reason is already shown by the host, in the node with that id, which describes the control.
 */
export function useDisabledReason(
  disabled: boolean | undefined,
  disabledReason: string | undefined,
  hostReasonId?: string,
): DisabledReasonAttrs {
  const ownId = useId();
  // Whitespace-only is no reason: a sighted user would see nothing, a screen reader a blank description.
  const trimmed = disabledReason?.trim();
  const gated = trimmed !== undefined && trimmed !== "";
  const host = hostReasonId?.trim() || undefined;
  const external = gated && host !== undefined;
  // Under a gate notice the reason node is the notice: every id that pointed at the own node points there instead.
  // An explicit host id wins over the notice; the notice wins over the control's own node.
  const noticeId = useGateNoticeFor(gated && !external ? trimmed : undefined);
  const reasonId = external && host !== undefined ? host : (noticeId ?? ownId);
  return {
    gated,
    disabled: disabled === true && !gated,
    reasonId,
    reason: gated ? trimmed : undefined,
    ariaDisabled: gated ? true : undefined,
    ariaDescribedBy: gated ? reasonId : undefined,
    external,
    fromNotice: noticeId !== undefined,
  };
}

/**
 * D09 2.2: a refused activation re-shows the reason with one polite announcement. The region is cleared, then set
 * in a microtask: an unchanged sentence would not announce again on a repeat press, and a microtask (unlike a
 * frame) runs deterministically under fake timers. Best effort: whether a reader re-speaks an identical sentence
 * set in the same task is the reader's; real-reader checks are E05-Q02's.
 */
function announceInOwnRegion(reason: string): void {
  announcePolite("");
  queueMicrotask(() => announcePolite(reason));
}

const GatedAnnounceContext = createContext<(reason: string) => void>(announceInOwnRegion);

export interface GatedAnnounceProviderProps {
  /** Receives the reason of a refused activation instead of this package's own polite region. */
  readonly announce: (reason: string) => void;
  readonly children?: ReactNode;
}

/** A host that owns one announcer (the app shell) routes the gated announcement there, or passes a no-op. */
export function GatedAnnounceProvider({
  announce,
  children,
}: GatedAnnounceProviderProps): JSX.Element {
  return <GatedAnnounceContext.Provider value={announce}>{children}</GatedAnnounceContext.Provider>;
}

/** The announce function each gated atom calls on a refused activation; a no-op for an undefined reason. */
export function useGatedAnnounce(): (reason: string | undefined) => void {
  const announce = useContext(GatedAnnounceContext);
  return useCallback(
    (reason: string | undefined) => {
      if (reason !== undefined) announce(reason);
    },
    [announce],
  );
}

/**
 * The reason as a plain text node, in the DOM at mount and visually hidden; nothing renders without one. It is the
 * accessible description; `ReasonEcho` shows a sighted user the same text on hover and focus.
 */
export function ReasonText({
  id,
  children,
}: {
  readonly id: string;
  readonly children: string | undefined;
}): JSX.Element | null {
  // Under a gate notice carrying this sentence, the notice is the node: rendering it here would read it twice.
  const noticeId = useGateNoticeFor(children);
  if (children === undefined || noticeId !== undefined) return null;
  return (
    <span id={id} className="cv-visually-hidden">
      {children}
    </span>
  );
}
