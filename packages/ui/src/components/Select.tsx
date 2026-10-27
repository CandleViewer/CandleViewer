import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { FieldMessage, useRefusalAnnounce } from "./internal/fieldParts.js";
import {
  extendTyped,
  firstIndex,
  lastIndex,
  matchIndex,
  openIndex,
  pageIndex,
  stepIndex,
  TYPE_AHEAD_MS,
  type Typed,
} from "./internal/listNav.js";

export interface SelectOption {
  readonly value: string;
  readonly label: string;
  /** Plain disabled: dimmed, passed over by the arrows, never chosen. */
  readonly disabled?: boolean;
  /**
   * The form's own rules make this option unavailable, and say why: the validity look. Arrow-reachable, never
   * chosen; the reason is its second line and its description. A reason wins over `disabled`.
   */
  readonly unavailableReason?: string;
  /** A gated option (T2): the lock, the label in `color.text.tertiary`, the reason as its second line. Never chosen. */
  readonly disabledReason?: string;
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

/** Where the popup sits and how much room that side has (px; conv. 28: a popup caps to the room and scrolls). */
interface Fit {
  readonly placement: Placement;
  readonly room: number | undefined;
  readonly wide: number | undefined;
}

/** Page Up / Page Down move this many options (D02F keyboard table). */
const PAGE = 10;

/** The keys a gated trigger refuses: those that would open it or move through it (printables are always refused). */
const GATED_KEYS: ReadonlySet<string> = new Set(["ArrowDown", "ArrowUp", "Home", "End"]);

/** No measurement yet: below, uncapped. One shared object, so setting it again does not re-render. */
const UNFIT: Fit = { placement: "below", room: undefined, wide: undefined };

const fitStyle = (fit: Fit): CSSProperties | undefined =>
  fit.room === undefined
    ? undefined
    : ({
        "--cv-select-room": `${String(fit.room)}px`,
        "--cv-select-wide": `${String(fit.wide)}px`,
      } as CSSProperties);

interface Recall {
  readonly index: number;
  readonly count: number;
}

const NONE: SelectOption = { value: "", label: "" };

type Kind = "disabled" | "unavailable" | "locked";

const trimmed = (text: string | undefined): string | undefined => {
  const t = text?.trim();
  return t === "" ? undefined : t;
};

/** How an option looks and behaves: a stated reason (T2 first) makes it reachable; plain disabled has none. */
function look(option: SelectOption): { kind: Kind | undefined; reason: string | undefined } {
  const locked = trimmed(option.disabledReason);
  if (locked !== undefined) return { kind: "locked", reason: locked };
  const unavailable = trimmed(option.unavailableReason);
  if (unavailable !== undefined) return { kind: "unavailable", reason: unavailable };
  return { kind: option.disabled === true ? "disabled" : undefined, reason: undefined };
}

/** The arrows pass over exactly these options: plain disabled. Unavailable and T2 options stay reachable. */
const skipped = (option: SelectOption): boolean => look(option).kind === "disabled";

const labelOf = (option: SelectOption): string => option.label;

/** Never chosen, by key or pointer: every kind of denied option. */
const blocked = (option: SelectOption): boolean => look(option).kind !== undefined;

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
  const [fit, setFit] = useState<Fit>(UNFIT);
  // The option whose reason Enter or a press re-showed, and how many times (the count re-keys the status node, so
  // a repeat press is announced again). Any move of the active option clears the index: arrows stay silent.
  const [recall, setRecall] = useState<Recall>({ index: -1, count: 0 });
  const typed = useRef<Typed>({ text: "", at: 0 });
  // Only a keyboard move (or an open) scrolls the active row into view; a hover must not move the list under the pointer.
  const scrollActive = useRef(true);

  const chosen = options.findIndex((option) => option.value === value);
  // `options` may change while open: an index that no longer names a reachable option falls back to the start.
  const activeOption = options[active];
  const current =
    activeOption !== undefined && !skipped(activeOption)
      ? active
      : openIndex(options, chosen, skipped);
  const shown = options[chosen]?.label ?? placeholder;
  const optionId = (index: number): string => `${listId}-${String(index)}`;
  // Stable per option: the name and the description both point at these two nodes.
  const labelId = (index: number): string => `${optionId(index)}-label`;
  const reasonId = (index: number): string => `${optionId(index)}-reason`;

  const endTyping = (): void => {
    typed.current = { text: "", at: 0 };
  };
  const choose = (index: number): void => {
    const option = options[index];
    if (option !== undefined && blocked(option)) {
      // An unavailable or T2 option is never chosen; its reason is shown again, every time. Plain disabled says nothing.
      if (look(option).reason !== undefined) {
        setActive(index); // a tap or an AT click with no prior pointer move: the pressed row is the active one
        setRecall((prev) => ({ index, count: prev.count + 1 }));
      }
      return;
    }
    if (option !== undefined && option.value !== value) onChange(option.value);
    endTyping();
    setOpen(false);
  };
  const moveTo = (index: number): void => {
    setRecall((prev) => ({ index: -1, count: prev.count }));
    setActive(index);
  };
  const openAt = (index: number): void => {
    moveTo(index);
    setOpen(true);
  };

  // Measured once per open, after layout and before paint: flip above only when the room below is short.
  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    const popup = popupRef.current;
    if (!open || anchor === null || popup === null) {
      // Closed: forget the last cap, so a reopen measures the natural height and picks the roomier side.
      setFit(UNFIT);
      return;
    }
    const rect = anchor.getBoundingClientRect();
    const need = popup.getBoundingClientRect().height;
    const below = window.innerHeight - rect.bottom;
    // Flip only when it does not fit below and above is the larger side; the popup then caps to that side's room.
    const above = need > below && rect.top > below;
    setFit({
      placement: above ? "above" : "below",
      room: above ? rect.top : below,
      wide: window.innerWidth - rect.left,
    });
  }, [open]);

  // The active option stays in view in a long list.
  useEffect(() => {
    if (open && current >= 0 && scrollActive.current) {
      document.getElementById(optionId(current))?.scrollIntoView({ block: "nearest" });
    }
    scrollActive.current = true;
    // `optionId` is derived from `listId`, which is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, current]);

  const handleKey = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (reason.gated || reason.disabled) return;
    const { key } = event;
    scrollActive.current = true;
    // Alt+Down opens and Alt+Up chooses (APG); every other chord belongs to the host (Shift+Tab is focus movement).
    if (event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
      if (key === "ArrowDown" && !open) {
        event.preventDefault();
        openAt(openIndex(options, chosen, skipped)); // opens without moving the active option
      } else if (key === "ArrowUp" && open) {
        event.preventDefault();
        choose(current); // never a reason option: that re-shows its reason
      }
      return;
    }
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.shiftKey && key !== "Tab" && (key.length > 1 || key === " ")) return;
    if (key === "Tab") {
      // No preventDefault: focus moves on (APG). A reason option is never chosen and never announced as focus leaves.
      if (open) {
        const leaving = options[current];
        if (leaving !== undefined && blocked(leaving)) setOpen(false);
        else choose(current);
      }
      return;
    }
    // Type-ahead (APG): printables extend a short-lived string; the next label that starts with it becomes active.
    // A Space inside a typed string continues it while the longer string still matches ("sub account"); otherwise it
    // does its own job (opens, or chooses) and is always consumed, so it never scrolls the page.
    const now = performance.now();
    const typing = typed.current.text !== "" && now - typed.current.at <= TYPE_AHEAD_MS;
    if (key.length === 1) {
      const next = extendTyped(typed.current, key, now);
      const found = matchIndex(options, open ? current : chosen, next.text, labelOf, skipped);
      if (key !== " ") {
        typed.current = next;
        if (found >= 0) {
          event.preventDefault(); // a printable that did something is ours; one that matched nothing stays the host's
          openAt(found);
        }
        return;
      }
      if (typing && found >= 0) {
        typed.current = next;
        event.preventDefault();
        openAt(found);
        return;
      }
      endTyping();
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
        moveTo(stepIndex(options, current, key === "ArrowDown" ? 1 : -1, skipped));
        break;
      case "PageDown":
      case "PageUp":
        consume();
        moveTo(pageIndex(options, current, key === "PageDown" ? 1 : -1, PAGE, skipped));
        break;
      case "Home":
      case "End":
        consume();
        moveTo((key === "Home" ? firstIndex : lastIndex)(options, skipped));
        break;
      case "Enter":
      case " ": // APG select-only: Space chooses the active option; the spec's open rows are silent on it
        consume();
        choose(current);
        break;
      case "Escape":
        // The first Esc closes the list and stops there; a second one bubbles to the host. React's stopPropagation
        // also stops the native event, so a bubble-phase document listener never sees it (a capture one still does).
        consume();
        event.stopPropagation();
        endTyping();
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

  // Announced politely: only a press on the active reason option (Enter, Space, Alt+Up or a click), never an arrival.
  const said = open && recall.index === current ? look(options[current] ?? NONE).reason : undefined;
  const description = reason.gated ? reason.ariaDescribedBy : cx(errorId, describedBy) || undefined;
  const unavailable = reason.gated || reason.disabled;
  // A plain-disabled trigger is not focusable at all (a press never focuses it), like a native disabled control.
  const triggerTabIndex = reason.disabled ? undefined : 0;

  return (
    <div className="cv-field-root" data-cmp="CMP-009" data-density={density}>
      <div className="cv-select__anchor" ref={anchorRef}>
        <div
          className="cv-field"
          data-invalid={invalid ? "" : undefined}
          data-gated={reason.gated ? "" : undefined}
          data-disabled={reason.disabled ? "" : undefined}
        >
          {/* The tabindex is absent only when plain disabled, where `aria-activedescendant` is never set (the list cannot open). */}
          {/* eslint-disable-next-line jsx-a11y/aria-activedescendant-has-tabindex -- see above */}
          <div
            role="combobox"
            className="cv-select__trigger"
            tabIndex={triggerTabIndex}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={open ? listId : undefined}
            aria-activedescendant={open && current >= 0 ? optionId(current) : undefined}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            aria-describedby={description}
            aria-invalid={invalid ? true : undefined}
            aria-disabled={unavailable ? true : undefined}
            onClick={onTriggerClick}
            onKeyDown={refusal.handlers.onKeyDown}
            onBlur={(event) => {
              refusal.handlers.onBlur?.(event);
              endTyping();
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
            data-placement={fit.placement}
            style={fitStyle(fit)}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            onMouseDown={keepFocus}
          >
            {options.map((option, index) => {
              const { kind, reason: why } = look(option);
              return (
                // The trigger holds focus and drives the options; an option is a pointer target.
                // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus -- see above
                <div
                  key={option.value}
                  id={optionId(index)}
                  role="option"
                  className="cv-select__option"
                  aria-selected={index === chosen}
                  aria-describedby={why === undefined ? undefined : reasonId(index)}
                  data-lines={why === undefined ? undefined : 2}
                  aria-disabled={kind === undefined ? undefined : true}
                  data-kind={kind}
                  data-active={index === current ? "" : undefined}
                  onMouseMove={() => {
                    if (kind !== "disabled" && index !== current) {
                      scrollActive.current = false;
                      moveTo(index);
                    }
                  }}
                  onClick={() => {
                    if (index !== current) scrollActive.current = false; // under the pointer already
                    choose(index);
                  }}
                >
                  <span className="cv-select__check">
                    {index === chosen ? <Icon name="check" /> : null}
                  </span>
                  <span className="cv-select__body">
                    <span className="cv-select__line">
                      {kind === "locked" ? (
                        <span className="cv-select__optlock">
                          <Icon name="lock" />
                        </span>
                      ) : null}
                      <span id={labelId(index)} className="cv-select__label">
                        {option.label}
                      </span>
                    </span>
                    {why === undefined ? null : (
                      <span id={reasonId(index)} className="cv-select__reason">
                        {why}
                      </span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
      <FieldMessage id={errorId} message={invalid ? errorMessage : undefined} />
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      {refusal.status}
      {options.some((option) => look(option).reason !== undefined) ? (
        <span className="cv-visually-hidden" role="status">
          {said === undefined ? null : <span key={recall.count}>{said}</span>}
        </span>
      ) : null}
    </div>
  );
}
