import {
  forwardRef,
  useId,
  type ComponentPropsWithoutRef,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";
import type { PopoverAnchorProps } from "./Popover.js";

/** The value's recording state, the host's (`GET /recording/symbols`, then the `recorder` topic; E08-D05 §3). */
export type SymbolRecordingState = "recording" | "not-recorded" | "unknown";

export interface SymbolPickerProps extends Omit<
  ComponentPropsWithoutRef<"button">,
  | "aria-disabled"
  | "aria-expanded"
  | "aria-haspopup"
  | "aria-label"
  | "aria-labelledby"
  | "aria-pressed"
  | "children"
  | "className"
  | "disabled"
  | "onClick"
  | "role"
  | "style"
  | "type"
  | "value"
> {
  /** The current symbol ("BTCUSDT"): drawn whole, never truncated, and the heart of the name. */
  readonly value: string;
  /**
   * A press (a click, `Enter` or `Space`): the host opens its dialog, SCR-041 from the chart toolbar or SCR-102 from
   * the TopBar (E08-D05 A-D05-4), and moves focus to its input. The type-ahead, the list and `Esc` are the host's.
   * As a CMP-017 Popover's anchor, the Popover's own toggle runs after it: a press on the open trigger closes it.
   * It fires on every press, also while `expanded`: as a Popover's anchor it can be a no-op; any other host decides
   * what a press on an open trigger does (SCR-102 closes its dialog, E08-D05 D-11).
   */
  readonly onOpen: () => void;
  /**
   * The host's dialog is open: `aria-expanded`, and the selected fill (B02). Default `false`. A CMP-017 Popover's
   * anchor needs none: the trigger takes the Popover's own state, which wins over this.
   */
  readonly expanded?: boolean;
  /** The pane's interval in words ("1 minute"): the name's last part (hand-off Table 3), never drawn here. */
  readonly interval?: string;
  /** The chip beside the button, its description. Default `unknown`: no chip (unknown is never "not recorded"). */
  readonly recording?: SymbolRecordingState;
  /** Delisted by the exchange (E08-D05 §6.4): the value struck, the delisted chip in the recording chip's place. */
  readonly delisted?: boolean;
  /** Emits `data-density`, so `theme.css` re-points the control height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

type Marker = Exclude<SymbolRecordingState, "unknown"> | "delisted";
const WORDS: Readonly<Record<Marker, string>> = {
  recording: "Recording",
  "not-recorded": "Not recorded",
  delisted: "Delisted by the exchange",
};

/**
 * CMP-219 SymbolPicker: the compact in-chrome symbol trigger (E08-D05 A-D05-4, board B02), a native button with
 * `aria-haspopup="dialog"`, not a combobox. Its name is "Symbol: BTCUSDT, 1 minute" (hand-off Table 3), built from
 * the value it draws, so it always holds the visible text (WCAG 2.5.3, axe's label-content-name-mismatch); the
 * chevron is decorative. The chip sits beside the button, as B02 draws it, and is its description: one marker at a
 * time, delisted first (CMP-239's rule). A delisted value still opens, to choose another symbol.
 *
 * As a CMP-017 Popover's anchor it keeps what the Popover composes onto it past this type (`PopoverAnchorProps`):
 * the Popover's `aria-expanded` and `aria-controls`, and its toggle after `onOpen`, so that host wires no state. The
 * ref is the button's, for CMP-221's roving toolbar.
 */
export const SymbolPicker = forwardRef<HTMLButtonElement, SymbolPickerProps>(
  function SymbolPicker(props, ref): JSX.Element {
    const {
      value,
      onOpen,
      expanded = false,
      interval,
      recording = "unknown",
      delisted = false,
      density,
      onKeyDown,
      "aria-describedby": describedBy,
      ...rest
    } = props;
    // A CMP-017 Popover clones its anchor props onto this element; the props type leaves them out, so read them here.
    const popover: PopoverAnchorProps = props;
    const chipId = useId();
    const ring = useFocusRing();
    const marker: Marker | undefined = delisted
      ? "delisted"
      : recording === "unknown"
        ? undefined
        : recording;
    const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
      onKeyDown?.(event);
      // Hand-off Table 2: the trigger stops the Enter and Space it handles, so the shell's window-level keymap never
      // sees them (Space would post its "not available here" notice). React's stopPropagation stops the native event;
      // the button's own activation still runs.
      const plain = !event.ctrlKey && !event.altKey && !event.metaKey;
      if (plain && (event.key === "Enter" || event.key === " ")) event.stopPropagation();
    };
    const said = interval?.trim();
    return (
      <span className="cv-symbolpicker" data-cmp="CMP-219" data-density={density}>
        <button
          {...rest}
          ref={ref}
          // The role, the name and the state are the trigger's own (A-D05-4, WCAG 2.5.3), whatever reaches it past
          // its type: a host's role, aria-labelledby, aria-disabled, aria-pressed, disabled or style is dropped.
          role={undefined}
          aria-labelledby={undefined}
          aria-disabled={undefined}
          aria-pressed={undefined}
          disabled={undefined}
          style={undefined}
          type="button"
          className={cx("cv-control", ring.className, "cv-symbolpicker__trigger")}
          aria-label={said ? `Symbol: ${value}, ${said}` : `Symbol: ${value}`}
          aria-haspopup="dialog"
          aria-expanded={popover["aria-expanded"] ?? expanded}
          aria-describedby={cx(describedBy, marker !== undefined && chipId) || undefined}
          data-delisted={delisted ? "" : undefined}
          onClick={(event: MouseEvent<HTMLButtonElement>) => {
            onOpen();
            popover.onClick?.(event);
          }}
          onKeyDown={handleKeyDown}
        >
          <span className="cv-symbolpicker__value">{value}</span>
          <span className="cv-symbolpicker__chevron">
            <Icon name="chevron-down" />
          </span>
        </button>
        {marker === undefined ? null : (
          <span id={chipId} className="cv-symbolpicker__chip" data-marker={marker}>
            {marker === "delisted" ? (
              <span className="cv-symbolpicker__glyph">
                <Icon name="cancelled" />
              </span>
            ) : (
              <span className="cv-symbolpicker__dot" />
            )}
            {WORDS[marker]}
          </span>
        )}
      </span>
    );
  },
);
