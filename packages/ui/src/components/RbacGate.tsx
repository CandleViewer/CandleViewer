import { cloneElement, useEffect, type JSX, type ReactElement } from "react";
import type { IconName } from "../icons/registry.js";
import { EmptyState, type EmptyStateEmptyProps } from "./EmptyState.js";
import type { HeadingLevel } from "./Typography.js";
import { GateNoticeProvider } from "./internal/disabledReason.js";
import { fillRbacReason, type RbacReasonArgs, type RbacReasonKey } from "./rbacReasons.js";

/** A single atom that takes the T2 contract natively (CMP-001, 002, 004, 006, 010, …). */
export type RbacGateChild = ReactElement<{ disabledReason?: string }>;

/**
 * The tooltip form's child: an icon-only control (CMP-002, a toolbar segment). JSX widens every element to
 * `ReactElement<any>`, so the compiler cannot hold this; a development warning does.
 */
export type RbacGateIconChild = ReactElement<{
  disabledReason?: string;
  icon: IconName;
  label: string;
}>;

/** 2a (default): the reason is the atom's own described-by node, its lock leading the label. */
interface FormInline {
  readonly form?: "inline";
  readonly noticeId?: never;
  /** Exactly one control; the gate adds no DOM of its own. */
  readonly children: RbacGateChild;
}

/** 2b: the lock badges the icon; the reason node is visually hidden and CMP-016 echoes it on hover and focus. */
interface FormTooltip {
  readonly form: "tooltip";
  readonly noticeId?: never;
  readonly children: RbacGateIconChild;
}

/**
 * One notice, many pointers: the control's description is the host's notice node (a CMP-028 with `live="off"`,
 * in the DOM at mount); the control renders no reason node and no echo, and still re-announces on a press.
 */
interface FormNotice {
  readonly form: "notice";
  /** The id of the notice node, whose text is the reason sentence. */
  readonly noticeId: string;
  readonly children: RbacGateChild;
}

/**
 * The sentence form (E09-D09 §8, `32-design-specs` G-T2.1c): an empty state whose sole CTA is gated. Allowed
 * renders the child (the host's empty state with its CTA); denied renders CMP-026 with `cta` omitted, the reason
 * its `description` in `color.text.secondary`: no button, no CMP-019 `lock` glyph, no `aria-disabled` (there is
 * nothing to press, describe or announce). The reason is text, read in the surface's browse order.
 */
interface FormSentence {
  readonly form: "sentence";
  readonly noticeId?: never;
  /** The fact the empty state states, e.g. "Not recorded". */
  readonly title: string;
  /** CMP-026's variant for the denied block; default `no-data`. */
  readonly variant?: EmptyStateEmptyProps["variant"];
  /** The heading's level; default 3, so it fits its panel's outline. */
  readonly headingLevel?: HeadingLevel;
  /** The allowed rendering: the host's CMP-026 with its CTA. */
  readonly children: ReactElement;
}

/** The rendering (E05-D02 G15); `tooltip` only for icon-only controls, `notice` only with `noticeId`. */
export type RbacGateForm = "inline" | "tooltip" | "notice" | "sentence";

type GateForm<F extends RbacGateForm> = F extends "tooltip"
  ? FormTooltip
  : F extends "notice"
    ? FormNotice
    : F extends "sentence"
      ? FormSentence
      : FormInline;

/** T1: the session may use the control. A `reason` here is ignored, so a host may keep it computed. */
interface Allowed {
  readonly allowed: true;
  readonly reason?: RbacReasonKey;
  readonly fills?: never;
}

/** T2: a D09 §3.1 key is required; a parametrised key also requires its fills. */
type Denied = {
  [K in RbacReasonKey]: {
    readonly allowed: false;
    readonly reason: K;
  } & (RbacReasonArgs<K> extends [infer F] ? { readonly fills: F } : { readonly fills?: never });
}[RbacReasonKey];

/**
 * Generic in the form, so the form is not crossed with the seven reasons into one flat union (a host's computed
 * `reason` would no longer narrow): `form="notice"` requires `noticeId`, every other form forbids it.
 */
export type RbacGateProps<F extends RbacGateForm = "inline"> = (Allowed | Denied) & {
  /** Default `inline`. A plain `form?: F` beside the conditional is what lets JSX infer `F`. */
  readonly form?: F;
} & GateForm<F>;

/** An icon and a name and no visible text: a text Button that also takes `icon` and `label` is not icon-only. */
const isIconOnly = (child: ReactElement): boolean => {
  const props = child.props as { icon?: unknown; label?: unknown; children?: unknown };
  return (
    typeof props.icon === "string" &&
    typeof props.label === "string" &&
    (props.children === undefined || props.children === null)
  );
};

/**
 * CMP-079 RbacGate: a UI affordance, not an authorisation control; the server enforces RBAC (C-12.4).
 * Allowed renders the child unchanged. Denied hands the reason sentence to the child's own
 * `disabledReason`, so the atom renders T2 itself: `aria-disabled`, never `disabled`, focusable,
 * `aria-describedby` to the reason, the lock glyph; no overlay layer (E09-D09 §2.2, §9). The three forms
 * (E05-D02 G15): `inline` (default), `tooltip` (icon-only controls), `notice` (with `noticeId`), and `sentence` (E09-D09 §8). The notice
 * form's provider is mounted allowed or denied, so a gate that flips never remounts the control.
 */
export function RbacGate<F extends RbacGateForm = "inline">(props: RbacGateProps<F>): JSX.Element {
  // The form is a type parameter, which does not narrow; read it as the plain union it is at run time.
  const { form, noticeId } = props as { readonly form?: RbacGateForm; readonly noticeId?: string };
  const sentence = props as Partial<FormSentence>;
  const misused = form === "tooltip" && !isIconOnly(props.children);
  // Once per mount (and again only if the misuse comes back), not on every render.
  useEffect(() => {
    if (misused && import.meta.env?.DEV) {
      console.warn("RbacGate: the tooltip form is for icon-only controls; use inline (CMP-079).");
    }
  }, [misused]);
  const reason = props.allowed ? undefined : fillRbacReason(props.reason, props.fills);
  if (form === "sentence") {
    if (reason === undefined) return props.children as ReactElement;
    return (
      <EmptyState
        variant={sentence.variant ?? "no-data"}
        title={sentence.title ?? ""}
        description={reason}
        {...(sentence.headingLevel === undefined ? {} : { headingLevel: sentence.headingLevel })}
      />
    );
  }
  const child =
    reason === undefined
      ? props.children
      : cloneElement(props.children, { disabledReason: reason });
  if (form !== "notice" || noticeId === undefined) return child;
  const notice = reason === undefined ? null : { noticeId, reason };
  return <GateNoticeProvider notice={notice}>{child}</GateNoticeProvider>;
}
