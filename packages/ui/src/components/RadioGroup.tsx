import { useId, type JSX, type MouseEvent } from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, useDisabledReason, useGatedAnnounce } from "./internal/disabledReason.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
import { cx } from "./internal/cx.js";
import { useRoving, type RovingItemProps } from "./internal/useRoving.js";

export interface RadioOption {
  readonly value: string;
  readonly label: string;
  /** Plain disabled: the arrows skip it. */
  readonly disabled?: boolean;
  /** Locked (T2): the arrows reach it so the reason can be read, but it is never checked. */
  readonly disabledReason?: string;
}

/** The group's accessible name is required: one of the two, never neither. */
type RadioGroupName =
  | { readonly "aria-label": string; readonly "aria-labelledby"?: string }
  | { readonly "aria-labelledby": string; readonly "aria-label"?: string };

export interface RadioGroupBaseProps {
  readonly options: readonly RadioOption[];
  /** The checked value; `undefined` = nothing checked (the first enabled radio then holds the tab stop). */
  readonly value?: string | undefined;
  readonly onChange?: (value: string) => void;
  readonly orientation?: "vertical" | "horizontal";
  readonly disabled?: boolean;
  /** The visible reason the whole group is denied: disabled-with-reason (T2). */
  readonly disabledReason?: string;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

export type RadioGroupProps = RadioGroupName & RadioGroupBaseProps;

interface RadioRowProps {
  readonly option: RadioOption;
  readonly checked: boolean;
  readonly groupDisabled: boolean;
  readonly groupReasonId: string | undefined;
  /** The group's reason text, echoed on every row of a gated group (hover reaches any row). */
  readonly groupReason: string | undefined;
  readonly roving: RovingItemProps;
  readonly onPick: (value: string) => void;
}

function RadioRow({
  option,
  checked,
  groupDisabled,
  groupReasonId,
  groupReason,
  roving,
  onPick,
}: RadioRowProps): JSX.Element {
  const reason = useDisabledReason(option.disabled, option.disabledReason);
  const announceGated = useGatedAnnounce();
  const labelId = useId();
  const disabled = groupDisabled || (option.disabled === true && !reason.gated);
  const gated = !disabled && (reason.gated || groupReasonId !== undefined);
  // Only the tab stop carries the group's reason; the option's own reason is always its description.
  const describedBy = cx(roving.tabIndex === 0 ? groupReasonId : undefined, reason.ariaDescribedBy);
  // One lock per gated group, after the tab-stop row (the checked one); an option's own reason always shows its lock.
  const showLock = gated && (reason.gated || roving.tabIndex === 0);
  // The echo: the group's reason on every gated row (hover reaches any row), then the option's own, joined by
  // " · " as CMP-002's name and reason are. Visual only (aria-hidden); the description keeps its two id refs.
  const echo = gated
    ? [groupReason, reason.reason].filter((r) => r !== undefined).join(" · ") || undefined
    : undefined;
  const handleClick = (event: MouseEvent<HTMLElement>): void => {
    // The whole row is the target. A refused row takes focus (to show its reason) and changes nothing.
    if (gated) announceGated(groupReason ?? reason.reason);
    if (disabled || gated) return;
    event.currentTarget.focus();
    onPick(option.value);
  };
  return (
    <ReasonEcho text={echo}>
      <div
        ref={roving.ref}
        role="radio"
        tabIndex={roving.tabIndex}
        onKeyDown={roving.onKeyDown}
        onFocus={roving.onFocus}
        onBlur={roving.onBlur}
        className="cv-radio cv-focus-ring-host"
        aria-checked={checked}
        aria-disabled={disabled || gated ? true : undefined}
        aria-labelledby={labelId}
        aria-describedby={describedBy || undefined}
        data-checked={checked ? "" : undefined}
        data-disabled={disabled ? "" : undefined}
        data-gated={gated ? "" : undefined}
        onClick={handleClick}
      >
        <span className="cv-radio__mark" aria-hidden="true">
          <span className="cv-radio__ring cv-focus-ring-target" />
        </span>
        <span id={labelId} className="cv-radio__label">
          {option.label}
        </span>
        {showLock ? (
          <span className="cv-radio__mark cv-radio__lock" aria-hidden="true">
            <Icon name="lock" />
          </span>
        ) : null}
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      </div>
    </ReasonEcho>
  );
}

/** CMP-006: a single choice from a short list; APG radio group with a roving tabindex (arrows move and check). */
export function RadioGroup({
  options,
  value,
  onChange,
  orientation = "vertical",
  disabled = false,
  disabledReason,
  density,
  ...name
}: RadioGroupProps): JSX.Element {
  const group = useDisabledReason(disabled, disabledReason);
  const announceGated = useGatedAnnounce();
  const groupDisabled = group.disabled;
  const refused = groupDisabled || group.gated;
  const onPick = (next: string): void => {
    if (next !== value) onChange?.(next);
  };
  const roving = useRoving({
    items: options.map((o) => ({
      value: o.value,
      disabled: groupDisabled || (o.disabled === true && (o.disabledReason?.trim() ?? "") === ""),
      locked: (o.disabledReason?.trim() ?? "") !== "",
    })),
    checked: value,
    onSelect: onPick,
    gated: refused,
    onRefused: (v) =>
      announceGated(group.reason ?? options.find((o) => o.value === v)?.disabledReason?.trim()),
  });
  return (
    <>
      <div
        {...name}
        role="radiogroup"
        className="cv-radio-group"
        data-cmp="CMP-006"
        data-orientation={orientation}
        data-density={density}
        aria-disabled={refused ? true : undefined}
        aria-describedby={group.ariaDescribedBy}
      >
        {options.map((option) => (
          <RadioRow
            key={option.value}
            option={option}
            checked={option.value === value}
            groupDisabled={groupDisabled}
            groupReasonId={group.gated ? group.reasonId : undefined}
            groupReason={group.reason}
            roving={roving.itemProps(option.value)}
            onPick={onPick}
          />
        ))}
      </div>
      <ReasonText id={group.reasonId}>{group.reason}</ReasonText>
    </>
  );
}
