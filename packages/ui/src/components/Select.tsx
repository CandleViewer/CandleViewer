import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { FieldMessage, useRefusalAnnounce } from "./internal/fieldParts.js";
import { firstIndex, lastIndex, openIndex, stepIndex } from "./internal/listNav.js";

export interface SelectOption {
  readonly value: string;
  readonly label: string;
  /** Plain disabled: dimmed, passed over by the arrows, never chosen. */
  readonly disabled?: boolean;
}

export interface SelectProps {
  readonly options: readonly SelectOption[];
  /** The chosen option's `value`; one that matches no option shows the placeholder. */
  readonly value: string | undefined;
  readonly onChange: (value: string) => void;
  /** Shown in `color.text.tertiary` while nothing is chosen. */
  readonly placeholder?: string;
  /** The name comes from the host's label (CMP-040): `aria-labelledby`, or `aria-label`. */
  readonly "aria-label"?: string;
  readonly "aria-labelledby"?: string;
  readonly "aria-describedby"?: string;
  /** Validity is a message (D02F conv. 23): the host decides when, the atom renders it. */
  readonly invalid?: boolean;
  readonly errorMessage?: string;
  readonly disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): T2. The listbox never opens. */
  readonly disabledReason?: string;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
  /** The editable combobox is CMP-048's, not this atom's (D02F G9). */
  readonly searchable?: never;
}

type Placement = "below" | "above";

/** The keys a gated trigger refuses: those that would open it or move through it (printables are always refused). */
const GATED_KEYS: ReadonlySet<string> = new Set(["ArrowDown", "ArrowUp", "Home", "End"]);

/** The seam for slice 11: the arrows pass over exactly these options. */
const skipped = (option: SelectOption): boolean => option.disabled === true;

/** CMP-009: the select-only combobox (APG). Focus stays on the trigger; `aria-activedescendant` names the option. */
export function Select({
  options,
  value,
  onChange,
  placeholder,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  "aria-describedby": describedBy,
  invalid = false,
  errorMessage,
  disabled,
  disabledReason,
  density,
}: SelectProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const errorId = useId();
  const listId = useId();
  const anchorRef = useRef<HTMLDivElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [placement, setPlacement] = useState<Placement>("below");

  const chosen = options.findIndex((option) => option.value === value);
  const shown = options[chosen]?.label ?? placeholder;
  const optionId = (index: number): string => `${listId}-${String(index)}`;

  const choose = (index: number): void => {
    const option = options[index];
    if (option !== undefined && skipped(option)) return;
    if (option !== undefined && option.value !== value) onChange(option.value);
    setOpen(false);
  };
  const openAt = (index: number): void => {
    setActive(index);
    setOpen(true);
  };

  // Measured once per open, after layout and before paint: flip above only when the room below is short.
  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    const popup = popupRef.current;
    if (!open || anchor === null || popup === null) return;
    const room = anchor.getBoundingClientRect();
    const need = popup.getBoundingClientRect().height;
    const below = window.innerHeight - room.bottom;
    setPlacement(need > below && room.top > below ? "above" : "below");
  }, [open]);

  // The active option stays in view in a long list.
  useEffect(() => {
    if (open && active >= 0) {
      document.getElementById(optionId(active))?.scrollIntoView({ block: "nearest" });
    }
    // `optionId` is derived from `listId`, which is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, active]);

  const handleKey = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (reason.gated || reason.disabled) return;
    const { key } = event;
    // A chord belongs to the host (Shift+Tab is focus movement, not a chord of ours).
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.shiftKey && key !== "Tab") return;
    if (key === "Tab") {
      if (open) choose(active); // no preventDefault: focus moves on (APG)
      return;
    }
    const consume = (): void => event.preventDefault();
    if (!open) {
      if (key === "Enter" || key === " " || key === "ArrowDown" || key === "ArrowUp") {
        consume();
        openAt(openIndex(options, chosen, skipped));
      } else if (key === "Home" || key === "End") {
        consume();
        openAt((key === "Home" ? firstIndex : lastIndex)(options, skipped));
      }
      return;
    }
    switch (key) {
      case "ArrowDown":
      case "ArrowUp":
        consume();
        setActive(stepIndex(options, active, key === "ArrowDown" ? 1 : -1, skipped));
        break;
      case "Home":
      case "End":
        consume();
        setActive((key === "Home" ? firstIndex : lastIndex)(options, skipped));
        break;
      case "Enter":
        consume();
        choose(active);
        break;
      case "Escape":
        // The first Esc closes the list and stops there; a second one bubbles to the host.
        consume();
        event.stopPropagation();
        setOpen(false);
        break;
      default:
        break;
    }
  };

  const refusal = useRefusalAnnounce<HTMLDivElement>(reason, { onKeyDown: handleKey }, GATED_KEYS);

  const onTriggerClick = (): void => {
    if (reason.gated) refusal.refuse();
    else if (!reason.disabled) {
      if (open) setOpen(false);
      else openAt(openIndex(options, chosen, skipped));
    }
  };

  // Keep focus on the trigger when the popup is pressed (also a press on its padding or scrollbar).
  const keepFocus = (event: MouseEvent<HTMLElement>): void => event.preventDefault();

  const description = reason.gated ? reason.ariaDescribedBy : cx(errorId, describedBy) || undefined;
  const unavailable = reason.gated || reason.disabled;

  return (
    <div className="cv-field-root" data-cmp="CMP-009" data-density={density}>
      <div className="cv-select__anchor" ref={anchorRef}>
        <div
          className="cv-field"
          data-invalid={invalid ? "" : undefined}
          data-gated={reason.gated ? "" : undefined}
          data-disabled={reason.disabled ? "" : undefined}
        >
          <div
            role="combobox"
            className="cv-select__trigger"
            tabIndex={reason.disabled ? -1 : 0}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={listId}
            aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            aria-describedby={description}
            aria-invalid={invalid ? true : undefined}
            aria-disabled={unavailable ? true : undefined}
            onClick={onTriggerClick}
            onKeyDown={refusal.handlers.onKeyDown}
            onBlur={(event) => {
              refusal.handlers.onBlur?.(event);
              setOpen(false);
            }}
          >
            {reason.gated ? (
              <span className="cv-select__lock">
                <Icon name="lock" decorative={false} label="Not available" />
              </span>
            ) : null}
            <span className="cv-select__value" data-placeholder={chosen < 0 ? "" : undefined}>
              {shown}
            </span>
            <span className="cv-select__chevron">
              <Icon name="chevron-down" />
            </span>
          </div>
        </div>
        {open ? (
          // The listbox is a pointer surface only; the keyboard and AT target is the trigger (never in the Tab order).
          <div
            tabIndex={-1}
            ref={popupRef}
            id={listId}
            role="listbox"
            className="cv-select__popup"
            data-placement={placement}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            onMouseDown={keepFocus}
          >
            {options.map((option, index) => (
              // The trigger holds focus and drives the options; an option is a pointer target.
              // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus -- see above
              <div
                key={option.value}
                id={optionId(index)}
                role="option"
                className="cv-select__option"
                aria-selected={index === chosen}
                aria-disabled={skipped(option) ? true : undefined}
                data-active={index === active ? "" : undefined}
                onMouseMove={() => {
                  if (!skipped(option) && index !== active) setActive(index);
                }}
                onClick={() => choose(index)}
              >
                <span className="cv-select__check">
                  {index === chosen ? <Icon name="check" /> : null}
                </span>
                <span>{option.label}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <FieldMessage id={errorId} message={invalid ? errorMessage : undefined} />
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      {refusal.status}
    </div>
  );
}
