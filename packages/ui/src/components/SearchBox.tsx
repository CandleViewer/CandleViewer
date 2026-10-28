import {
  useRef,
  type ChangeEvent,
  type ComponentPropsWithoutRef,
  type JSX,
  type KeyboardEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { focusFieldInput } from "./internal/fieldParts.js";
import { IconButton } from "./IconButton.js";

export interface SearchBoxProps extends Omit<
  ComponentPropsWithoutRef<"input">,
  | "className"
  | "style"
  | "children"
  | "type"
  | "value"
  | "defaultValue"
  | "onChange"
  | "disabled"
  | "prefix"
  | "size"
  | "aria-label"
  | "aria-labelledby"
  | "aria-disabled"
> {
  /** The query (controlled). */
  readonly value: string;
  /** Called with the typed query. */
  readonly onChange: (value: string, event: ChangeEvent<HTMLInputElement>) => void;
  /** The accessible name, through `aria-label` (D02F G13): mandatory, because a placeholder is never a name. */
  readonly label: string;
  /** The query is cleared (the clear button, or `Esc` on a non-empty query); the host sets `value` to "". */
  readonly onClear: () => void;
  /** Plain disabled, for everyone in the state. A search is a read and never gated, so there is no reason form. */
  readonly disabled?: boolean;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

/**
 * CMP-054: a filter field on the CMP-007 well (D02F CMP-054): a leading `search` glyph, the native search field, and
 * a CMP-002 ghost clear button only while there is a value. `Esc` clears a non-empty query and keeps focus; on an
 * empty query it does nothing, so it bubbles (a dialog closes). The host announces its result count, politely, once
 * per settled query.
 */
export function SearchBox({
  value,
  onChange,
  label,
  onClear,
  disabled = false,
  density,
  onKeyDown,
  ...rest
}: SearchBoxProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const filled = value !== "";

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    onKeyDown?.(event);
    if (event.key !== "Escape" || !filled || event.defaultPrevented) return;
    if (event.nativeEvent.isComposing) return;
    // Handled here: the native field must not clear on its own, and a dialog around it must not close.
    event.preventDefault();
    event.stopPropagation();
    onClear();
  };

  const clear = (): void => {
    onClear();
    inputRef.current?.focus();
  };

  return (
    <div className="cv-field-root cv-searchbox" data-cmp="CMP-054" data-density={density}>
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        className="cv-field"
        data-disabled={disabled ? "" : undefined}
        data-lead=""
        data-trail={filled ? "" : undefined}
        onMouseDown={(event) => focusFieldInput(event, inputRef)}
      >
        <span className="cv-field__lead">
          <Icon name="search" />
        </span>
        <input
          {...rest}
          ref={inputRef}
          type="search"
          className="cv-field__input"
          value={value}
          disabled={disabled}
          aria-label={label}
          onChange={(event) => onChange(event.target.value, event)}
          onKeyDown={handleKeyDown}
        />
        {filled ? (
          <IconButton
            icon="close"
            label="Clear search"
            variant="ghost"
            disabled={disabled}
            onClick={clear}
          />
        ) : null}
      </div>
    </div>
  );
}
