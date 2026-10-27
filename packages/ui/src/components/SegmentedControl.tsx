import { type JSX, type MouseEvent } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { useRoving, type RovingItemProps } from "./internal/useRoving.js";

export interface SegmentedOption {
  /** Must be unique within the group (the roving focus and the checked state are keyed by it). */
  readonly value: string;
  /** The visible text; with `iconOnly` it is the radio's `aria-label` instead. */
  readonly label: string;
  readonly icon?: IconName;
}

/** Two to six options: a segmented control with one or seven is a different control. */
export type SegmentedOptions = readonly [
  SegmentedOption,
  SegmentedOption,
  SegmentedOption?,
  SegmentedOption?,
  SegmentedOption?,
  SegmentedOption?,
];

/** The group's accessible name is required: one of the two, never neither. */
type SegmentedName =
  | { readonly "aria-label": string; readonly "aria-labelledby"?: string }
  | { readonly "aria-labelledby": string; readonly "aria-label"?: string };

export interface SegmentedControlBaseProps {
  readonly options: SegmentedOptions;
  /** The checked value; `undefined` = nothing checked (the first segment then holds the tab stop). */
  readonly value?: string | undefined;
  readonly onChange?: (value: string) => void;
  readonly size?: "sm" | "md";
  readonly fullWidth?: boolean;
  /** Content=icon-only: every segment shows its icon and its label becomes the `aria-label`. */
  readonly iconOnly?: boolean;
  readonly disabled?: boolean;
  /** The visible reason the whole control is denied: disabled-with-reason (T2). */
  readonly disabledReason?: string;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

export type SegmentedControlProps = SegmentedName & SegmentedControlBaseProps;

interface SegmentProps {
  readonly option: SegmentedOption;
  readonly checked: boolean;
  readonly iconOnly: boolean;
  readonly disabled: boolean;
  readonly gated: boolean;
  readonly groupReasonId: string | undefined;
  readonly roving: RovingItemProps;
  readonly onPick: (value: string) => void;
}

function Segment({
  option,
  checked,
  iconOnly,
  disabled,
  gated,
  groupReasonId,
  roving,
  onPick,
}: SegmentProps): JSX.Element {
  const showIcon = option.icon !== undefined;
  const nameOnly = iconOnly && showIcon;
  const isStop = roving.tabIndex === 0;
  const handleMouseDown = (event: MouseEvent<HTMLElement>): void => {
    // A refused segment takes no focus: a gated group sends it to the tab stop, which carries the reason.
    if (!disabled && !gated) return;
    event.preventDefault();
    if (gated) {
      event.currentTarget
        .closest<HTMLElement>('[role="radiogroup"]')
        ?.querySelector<HTMLElement>('[tabindex="0"]')
        ?.focus();
    }
  };
  const handleClick = (event: MouseEvent<HTMLElement>): void => {
    if (disabled || gated) return;
    event.currentTarget.focus();
    onPick(option.value);
  };
  return (
    <div
      ref={roving.ref}
      role="radio"
      tabIndex={roving.tabIndex}
      onKeyDown={roving.onKeyDown}
      onFocus={roving.onFocus}
      onBlur={roving.onBlur}
      className="cv-segmented__option"
      aria-checked={checked}
      aria-disabled={disabled || gated ? true : undefined}
      aria-label={nameOnly ? option.label : undefined}
      aria-describedby={isStop ? groupReasonId : undefined}
      data-checked={checked ? "" : undefined}
      data-disabled={disabled ? "" : undefined}
      data-gated={gated ? "" : undefined}
      onMouseDown={handleMouseDown}
      onClick={handleClick}
    >
      {option.icon !== undefined ? (
        <span className="cv-segmented__icon" aria-hidden="true">
          <Icon name={option.icon} />
        </span>
      ) : null}
      {nameOnly ? null : (
        <span className="cv-segmented__label" data-label={option.label}>
          {option.label}
        </span>
      )}
    </div>
  );
}

/**
 * CMP-003: a short either-or choice; APG radio group with a roving tabindex (arrows move and check).
 * Arrow keys are not mirrored under `dir="rtl"` (Right/Down is always "next"), as for the Slider.
 */
export function SegmentedControl({
  options,
  value,
  onChange,
  size = "md",
  fullWidth = false,
  iconOnly = false,
  disabled = false,
  disabledReason,
  density,
  ...name
}: SegmentedControlProps): JSX.Element {
  const group = useDisabledReason(disabled, disabledReason);
  const refused = group.disabled || group.gated;
  const list = options.filter((o): o is SegmentedOption => o !== undefined);
  const onPick = (next: string): void => {
    if (next !== value) onChange?.(next);
  };
  const roving = useRoving({
    items: list.map((o) => ({ value: o.value, disabled: group.disabled })),
    checked: value,
    onSelect: onPick,
    gated: refused,
  });
  return (
    <>
      <div
        {...name}
        role="radiogroup"
        className="cv-segmented"
        data-cmp="CMP-003"
        data-size={size}
        data-density={density}
        data-full-width={fullWidth ? "" : undefined}
        data-disabled={group.disabled ? "" : undefined}
        data-gated={group.gated ? "" : undefined}
        aria-disabled={refused ? true : undefined}
        aria-describedby={group.ariaDescribedBy}
      >
        {list.map((option) => (
          <Segment
            key={option.value}
            option={option}
            checked={option.value === value}
            iconOnly={iconOnly}
            disabled={group.disabled}
            gated={group.gated}
            groupReasonId={group.gated ? group.reasonId : undefined}
            roving={roving.itemProps(option.value)}
            onPick={onPick}
          />
        ))}
        {group.gated ? (
          <span className="cv-segmented__icon cv-segmented__lock" aria-hidden="true">
            <Icon name="lock" />
          </span>
        ) : null}
      </div>
      <ReasonText id={group.reasonId}>{group.reason}</ReasonText>
    </>
  );
}
