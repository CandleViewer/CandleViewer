import { useId, type ComponentPropsWithoutRef, type JSX } from "react";
import { cx } from "./internal/cx.js";
import { Text } from "./Typography.js";

export interface DividerProps extends Omit<
  ComponentPropsWithoutRef<"div">,
  "role" | "children" | "style" | "aria-orientation"
> {
  orientation?: "horizontal" | "vertical";
  /** Insets both ends: horizontal by `space.inset.md`, vertical by `space.inset.xs` (§5 E13). */
  inset?: boolean;
  /** Layout only (Radix Separator): no role, out of the accessibility tree. Default false: `separator`. */
  decorative?: boolean;
}

/**
 * CMP-018: a 1 px `color.border.subtle` rule, drawn as a border so forced colours keep it. Meaningful by
 * default (`role="separator"`, as inside a Menu or Toolbar); never focusable and never inside a listbox.
 */
export function Divider({
  orientation = "horizontal",
  inset = false,
  decorative = false,
  className,
  ...rest
}: DividerProps): JSX.Element {
  return (
    <div
      {...rest}
      className={cx("cv-divider", className)}
      data-cmp="CMP-018"
      data-orientation={orientation}
      data-inset={inset ? "" : undefined}
      role={decorative ? "none" : "separator"}
      aria-orientation={!decorative && orientation === "vertical" ? "vertical" : undefined}
    />
  );
}

export interface DividerLabelProps {
  /** The visible section caption; it also names the separator. */
  label: string;
  className?: string;
}

/**
 * CMP-030: a leading caption and a trailing rule. The caption is a sibling that names the separator
 * through `aria-labelledby`, never its child (a separator's children are presentational, §5 E24).
 */
export function DividerLabel({ label, className }: DividerLabelProps): JSX.Element {
  const id = useId();
  return (
    <div className={cx("cv-divider-label", className)} data-cmp="CMP-030">
      <Text id={id} variant="caption" tone="secondary" className="cv-divider-label__text">
        {label}
      </Text>
      <Divider className="cv-divider-label__rule" aria-labelledby={id} />
    </div>
  );
}
