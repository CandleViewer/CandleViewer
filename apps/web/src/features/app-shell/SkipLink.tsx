import { useState, type CSSProperties, type JSX, type MouseEvent } from "react";

/** Visually hidden until focused (the standard clip pattern; these sizes are not layout spacing). */
export const HIDDEN: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
};

/** CMP-085 tokens (`15` CMP-085; E10-D03 §2.1): the pill at the top bar's top-left, shown at once. */
const SHOWN: CSSProperties = {
  position: "absolute",
  top: "var(--space-2)",
  left: "var(--space-2)",
  zIndex: 1,
  display: "inline-flex",
  alignItems: "center",
  minHeight: "var(--size-control-height)",
  padding: "0 var(--space-inset-sm)",
  borderRadius: "var(--radius-control)",
  background: "var(--color-action-primary-default)",
  color: "var(--color-text-on-action)",
  outline: "calc(var(--border-focus) * 1px) solid var(--color-focus-ring)",
  outlineOffset: "calc(var(--border-focus) * 1px)",
};

/**
 * TEMPORARY skip link for the shell frame (E10-S01 S1, #304). CMP-085 SkipLink belongs to
 * E05-S04 (#267); this stand-in lives in apps/web only and is replaced by the `packages/ui`
 * component when #267 lands. The first focusable element of every shell page; activating it
 * moves focus to the target (`main`, which carries `tabIndex={-1}`), so the next Tab continues
 * from there. The click is handled in script so the hash never reaches the router.
 */
export function SkipLink({ targetId }: { readonly targetId: string }): JSX.Element {
  const [focused, setFocused] = useState(false);
  const onClick = (e: MouseEvent<HTMLAnchorElement>): void => {
    e.preventDefault();
    document.getElementById(targetId)?.focus();
  };
  return (
    <a
      href={`#${targetId}`}
      onClick={onClick}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={focused ? SHOWN : HIDDEN}
    >
      Skip to main content
    </a>
  );
}
