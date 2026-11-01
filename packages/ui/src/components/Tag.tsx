import type { JSX } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { IconButton } from "./IconButton.js";

/** The status tones and their fixed registry glyph: colour is never the only signal (D02 conv. 4, E10). */
const STATUS_GLYPH = { info: "info", warning: "warning", danger: "danger" } as const;
type StatusTone = keyof typeof STATUS_GLYPH;

interface TagBase {
  /** The visible text; for a status chip it is the status word, e.g. "Degraded". */
  label: string;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** A static neutral chip: an optional leading glyph, never focusable. */
interface NeutralStatic extends TagBase {
  variant?: "neutral";
  icon?: IconName;
  removable?: false;
  onRemove?: never;
  disabled?: never;
  disabledReason?: never;
}

/**
 * A removable neutral chip (E10: only neutral chips are removable). The remove control is a ghost CMP-002
 * named "Remove {label}". `onRemove` hands focus to the owning group (CMP-169, CMP-055): next chip's remove
 * button, else the previous one, else its input, never `<body>`. The chip never moves focus itself.
 */
interface NeutralRemovable extends TagBase {
  variant?: "neutral";
  icon?: IconName;
  removable: true;
  onRemove: () => void;
  /** Plain disabled remove button; dimming is the nested IconButton's only (conv. 20). */
  disabled?: boolean;
  /** Gated removal (E09-D09 §2.2 T2) through the nested CMP-002: lock badge, reason as its description. */
  disabledReason?: string;
  /**
   * The node in which the host already shows `disabledReason` (one notice, many pointers: CMP-055's bar): the remove is
   * described by it and renders no copy of its own; the lock badge and the echo stay (2b).
   */
  disabledReasonId?: string;
}

/** A status chip: its registry glyph always renders, so `icon` is not accepted, and it is never removable. */
interface StatusTag extends TagBase {
  variant: StatusTone;
  icon?: never;
  removable?: false;
  onRemove?: never;
  disabled?: never;
  disabledReason?: never;
}

/*
 * Not built here:
 * - `estimated`: a deprecated alias of CMP-227 EstimatedBadge (D02 §5 E19, E25-D05); it waits on CMP-227
 *   so that no second estimated look ships.
 * - `toggle` (an `aria-pressed` filter chip): slice 1b of #265, once its `15` line lands. It would be a fourth union
 *   member here, with its own `data-variant`, so the existing members stay unchanged.
 */
export type TagProps = NeutralStatic | NeutralRemovable | StatusTag;

const isStatus = (variant: TagProps["variant"]): variant is StatusTone =>
  variant !== undefined && variant !== "neutral";

/**
 * CMP-011 Tag / Chip: a compact label. Static chips are a generic span named by their text; the leading
 * glyph is decorative because the word is in the label. Only the nested remove button is interactive.
 */
export function Tag(props: TagProps): JSX.Element {
  const { label, density, variant = "neutral" } = props;
  // `icon` is typed `never` on status chips, and their own glyph wins regardless.
  const glyph: IconName | undefined = isStatus(variant) ? STATUS_GLYPH[variant] : props.icon;
  const removable = props.removable === true ? props : undefined;
  return (
    <span
      className="cv-tag"
      data-cmp="CMP-011"
      data-variant={variant}
      data-density={density}
      data-removable={removable ? "" : undefined}
    >
      {glyph === undefined ? null : (
        <span className="cv-tag__glyph">
          <Icon name={glyph} />
        </span>
      )}
      <span className="cv-tag__label">{label}</span>
      {removable ? (
        <IconButton
          icon="close"
          label={`Remove ${label}`}
          variant="ghost"
          {...(density === undefined ? {} : { density })}
          {...(removable.disabled === undefined ? {} : { disabled: removable.disabled })}
          {...(removable.disabledReason === undefined
            ? {}
            : { disabledReason: removable.disabledReason })}
          {...(removable.disabledReasonId === undefined
            ? {}
            : { disabledReasonId: removable.disabledReasonId })}
          onClick={() => removable.onRemove()}
        />
      ) : null}
    </span>
  );
}
