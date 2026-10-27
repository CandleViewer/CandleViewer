import { cloneElement, type JSX, type ReactElement } from "react";
import { fillRbacReason, type RbacReasonArgs, type RbacReasonKey } from "./rbacReasons.js";

/** A single atom that takes the T2 contract natively (CMP-001, 002, 004, 006, 010, …). */
export type RbacGateChild = ReactElement<{ disabledReason?: string }>;

interface GateBase {
  /**
   * The rendering. Only `inline` (2a) ships today; `tooltip` (2b) and `notice` (with `noticeId`) follow
   * once CMP-016 Tooltip lands (E05-D02 G15, E09-D09 §8 DS-2).
   */
  readonly form?: "inline";
  /** Exactly one control; the gate adds no DOM of its own. */
  readonly children: RbacGateChild;
}

/** T1: the session may use the control. A `reason` here is ignored, so a host may keep it computed. */
interface Allowed extends GateBase {
  readonly allowed: true;
  readonly reason?: RbacReasonKey;
  readonly fills?: never;
}

/** T2: a D09 §3.1 key is required; a parametrised key also requires its fills. */
type Denied = {
  [K in RbacReasonKey]: GateBase & {
    readonly allowed: false;
    readonly reason: K;
  } & (RbacReasonArgs<K> extends [infer F] ? { readonly fills: F } : { readonly fills?: never });
}[RbacReasonKey];

export type RbacGateProps = Allowed | Denied;

/**
 * CMP-079 RbacGate: a UI affordance, not an authorisation control; the server enforces RBAC (C-12.4).
 * Allowed renders the child unchanged. Denied hands the reason sentence to the child's own
 * `disabledReason`, so the atom renders T2 itself: `aria-disabled`, never `disabled`, focusable,
 * `aria-describedby` to the reason, the lock glyph; no overlay layer (E09-D09 §2.2, §9).
 */
export function RbacGate(props: RbacGateProps): JSX.Element {
  if (props.allowed) return props.children;
  return cloneElement(props.children, {
    disabledReason: fillRbacReason(props.reason, props.fills),
  });
}
