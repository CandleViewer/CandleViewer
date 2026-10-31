import { useEffect, type CSSProperties, type JSX, type MouseEvent } from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, announceGatedReason, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { useRoving, type RovingItemProps } from "./internal/useRoving.js";

/**
 * The `check` and `lock` glyph colour: `color.text.inverse` or `color.text.on-action`, whichever is
 * at least 3:1 on that swatch (catalogue Tokens line, D02 C12). `inverse` passes on both drawing tokens
 * in every theme; a palette colour that needs `on-action` names it.
 */
export type SwatchGlyphTone = "inverse" | "on-action";

interface SwatchColour {
  /** The displayed colour, a token custom property such as `var(--color-drawing-default)`. */
  readonly color: string;
  /** The colour's human name ("Cyan"), its accessible name: never the hex value. */
  readonly label: string;
}

export interface ColorSwatchProps extends SwatchColour {
  /** Adjacent text already names the colour: the swatch is hidden from assistive technology. */
  readonly decorative?: boolean;
  /** Emits `data-density` so `theme.css` re-points the swatch size; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

export interface ColorSwatchOption extends SwatchColour {
  /** Unique within the picker. */
  readonly value: string;
  /** The `check` and `lock` glyph colour on this swatch; `inverse` by default. */
  readonly glyphTone?: SwatchGlyphTone;
  /** Plain disabled: dimmed, and the arrows skip it. */
  readonly disabled?: boolean;
  /** Locked (T2): the arrows reach it so the reason can be read, but it is never selected. */
  readonly disabledReason?: string;
}

/** The picker names what is being coloured ("Line colour"): one of the two, never neither. */
type PickerName =
  | { readonly "aria-label": string; readonly "aria-labelledby"?: string }
  | { readonly "aria-labelledby": string; readonly "aria-label"?: string };

export interface ColorSwatchPickerBaseProps {
  readonly swatches: readonly ColorSwatchOption[];
  /** The selected value; `undefined` = none (the first enabled swatch then holds the tab stop). */
  readonly value?: string | undefined;
  readonly onChange?: (value: string) => void;
  readonly disabled?: boolean;
  /** The visible reason the whole picker is denied: disabled-with-reason (T2). */
  readonly disabledReason?: string;
  readonly density?: "comfortable" | "compact";
}

export type ColorSwatchPickerProps = PickerName & ColorSwatchPickerBaseProps;

const fill = (color: string): CSSProperties => ({ "--cv-swatch-color": color }) as CSSProperties;

/**
 * CMP-031 ColorSwatch / ThemeChip, the static form (no `onSelect`): a named `img`, or `aria-hidden`
 * beside text that names the colour (D02 C12). Not focusable. Pick colours with `ColorSwatchPicker`.
 */
export function ColorSwatch({
  color,
  label,
  decorative = false,
  density,
}: ColorSwatchProps): JSX.Element {
  return (
    <span
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative ? true : undefined}
      className="cv-swatch"
      data-cmp="CMP-031"
      data-density={density}
      style={fill(color)}
    />
  );
}

interface SwatchRadioProps {
  readonly option: ColorSwatchOption;
  readonly checked: boolean;
  readonly groupDisabled: boolean;
  readonly groupReasonId: string | undefined;
  readonly groupReason: string | undefined;
  readonly roving: RovingItemProps;
  readonly onPick: (value: string) => void;
}

function SwatchRadio({
  option,
  checked,
  groupDisabled,
  groupReasonId,
  groupReason,
  roving,
  onPick,
}: SwatchRadioProps): JSX.Element {
  const reason = useDisabledReason(option.disabled, option.disabledReason);
  const disabled = groupDisabled || (option.disabled === true && !reason.gated);
  const gated = !disabled && (reason.gated || groupReasonId !== undefined);
  // Every swatch of a locked picker carries the picker's reason (a click can focus any of them).
  const describedBy = cx(gated ? groupReasonId : undefined, reason.ariaDescribedBy);
  const handleClick = (event: MouseEvent<HTMLElement>): void => {
    // A refused swatch changes nothing. A gated one still takes focus from the browser's own focus on a
    // tabindex element (so its reason is read); this handler never calls focus() for it.
    if (gated) announceGatedReason(groupReason ?? reason.reason);
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
      onClick={handleClick}
      className="cv-swatch cv-focus-ring"
      aria-label={option.label}
      aria-checked={checked}
      aria-disabled={disabled || gated ? true : undefined}
      aria-describedby={describedBy || undefined}
      data-checked={checked ? "" : undefined}
      data-disabled={disabled ? "" : undefined}
      data-gated={gated ? "" : undefined}
      data-glyph={option.glyphTone ?? "inverse"}
      style={fill(option.color)}
    >
      {checked ? (
        <span className="cv-swatch__check" aria-hidden="true">
          <Icon name="check" />
        </span>
      ) : null}
      {gated ? (
        <span className="cv-swatch__badge" aria-hidden="true">
          <Icon name="lock" size="sm" />
        </span>
      ) : null}
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </div>
  );
}

/**
 * CMP-031 swatch picker: an APG radio group of colour swatches with a roving tabindex (arrows move and
 * select, wrapping). A selected swatch shows the `check` glyph; a gated one keeps its true colour and
 * carries a corner `lock` badge, stays in the roving order and is never selected.
 */
export function ColorSwatchPicker({
  swatches,
  value,
  onChange,
  disabled = false,
  disabledReason,
  density,
  ...name
}: ColorSwatchPickerProps): JSX.Element {
  const group = useDisabledReason(disabled, disabledReason);
  const groupDisabled = group.disabled;
  const refused = groupDisabled || group.gated;
  // Values key the swatches and the roving focus: a duplicate selects two and strands one (dev only).
  useEffect(() => {
    if (!import.meta.env?.DEV) return;
    const seen = new Set<string>();
    for (const s of swatches) {
      if (seen.has(s.value)) {
        console.warn(
          `ColorSwatchPicker: duplicate swatch value "${s.value}"; values must be unique`,
        );
      }
      seen.add(s.value);
    }
  }, [swatches]);
  const onPick = (next: string): void => {
    if (next !== value) onChange?.(next);
  };
  const roving = useRoving({
    items: swatches.map((s) => ({
      value: s.value,
      disabled: groupDisabled || (s.disabled === true && (s.disabledReason?.trim() ?? "") === ""),
      locked: (s.disabledReason?.trim() ?? "") !== "",
    })),
    checked: value,
    onSelect: onPick,
    gated: refused,
    onRefused: (v) =>
      announceGatedReason(
        group.reason ?? swatches.find((s) => s.value === v)?.disabledReason?.trim(),
      ),
  });
  return (
    <>
      <div
        {...name}
        role="radiogroup"
        className="cv-swatch-picker"
        data-cmp="CMP-031"
        data-density={density}
        aria-disabled={refused ? true : undefined}
        aria-describedby={group.ariaDescribedBy}
      >
        {swatches.map((option) => (
          <SwatchRadio
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
