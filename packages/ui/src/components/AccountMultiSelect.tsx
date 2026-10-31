import {
  cloneElement,
  useEffect,
  useId,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { Icon } from "../icons/Icon.js";
import { Button } from "./Button.js";
import { Popover, type PopoverAnchorProps } from "./Popover.js";
import { firstIndex, lastIndex, stepIndex } from "./internal/listNav.js";
import { useControllable } from "./internal/useControllable.js";

export interface AccountOption {
  /** The exchange account's id, unique in the list: `onToggle` receives it. */
  readonly id: string;
  /** Its label, the option's whole name: "Sub-1". Long labels wrap, never truncate. */
  readonly label: string;
  /** Whether the filter includes the account now; the host owns it (controlled). */
  readonly selected: boolean;
}

/** What the picker composes onto its trigger: the popover's ARIA and toggle, an id (its name) and `Alt+↓`. */
export interface AccountMultiSelectTriggerProps extends PopoverAnchorProps {
  id?: string | undefined;
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
}

export interface AccountMultiSelectProps {
  /**
   * `account` only: E29-S01 builds the account filter use (E29-D04 §2.6, BQ-23), without `badge`, `profileSummary`,
   * `onEditProfile`, the group rows or the leg rows, which arrive with E30's fan-out build.
   */
  readonly mode: "account";
  /**
   * One button (CMP-001 or CMP-002) that opens the picker and names it: "+ Filter" on SCR-063's toolbar
   * (E29-D04 board 05). Its own `onClick` and `onKeyDown` run first.
   */
  readonly trigger: ReactElement<AccountMultiSelectTriggerProps>;
  /**
   * The list's name, when the trigger's words don't name the choice: a "+ Filter" menu whose Account item opens the
   * picker (E29-D02 §9.1). Absent or blank, the trigger names the list, as it names the panel. The words are the copy
   * owner's (E29-D03).
   */
  readonly listLabel?: string;
  /** The server-scoped accounts: a Manager's assigned ones only, set server-side, so no option carries a reason. */
  readonly accounts: readonly AccountOption[];
  /** Includes or drops one account (Space, or a press on its row). */
  readonly onToggle: (id: string) => void;
  /** "Select all", a distinct labelled control (`15` CMP-105 A11y), never implicit. */
  readonly onSelectAll: () => void;
  /** Controlled open state; leave it out to let the trigger open it (`defaultOpen`). */
  readonly open?: boolean;
  readonly defaultOpen?: boolean;
  /** Called on every open and close: the trigger, `Alt+↓`, `Enter` in the list, `Esc`, Tab out, an outside press. */
  readonly onOpenChange?: (open: boolean) => void;
  /** Emits `data-density` on the list and its control (the panel is portalled, so it cannot inherit it). */
  readonly density?: "comfortable" | "compact";
}

/** Every account is reachable: an account filter has no unavailable option (E29-D04 §4.2). */
const NONE = (): boolean => false;

/**
 * CMP-105 AccountMultiSelect, the account filter use (E29-D04 §2.6, D04H A-7; E30-D04 §8's keyboard): its trigger
 * opens a CMP-017 popover holding a `listbox` with `aria-multiselectable="true"` and a distinct "Select all"; the
 * trigger names both, unless the host's `listLabel` names the list.
 * `Alt+↓` or `Enter` on the trigger opens it with focus on the list, the active option the first selected one;
 * `↑` / `↓`, `Home` / `End` move the active option (`aria-activedescendant`); `Space` includes or drops it; `Enter`
 * closes; `Esc` closes and returns focus to the trigger. Each option is `role="option"` with `aria-selected`, its
 * check box CMP-005's plate, drawn and hidden from assistive technology. A reading and view choice, never T2, no
 * live region of its own (the table's polite line speaks the filtered result); the chosen accounts become CMP-055
 * chips in the host's toolbar.
 */
export function AccountMultiSelect({
  mode,
  trigger,
  listLabel,
  accounts,
  onToggle,
  onSelectAll,
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  density,
}: AccountMultiSelectProps): JSX.Element {
  const id = useId();
  const triggerId = trigger.props.id ?? `${id}-trigger`;
  const named = listLabel?.trim();
  /** The host's name for the list; none, or a blank one, leaves the trigger naming it. */
  const listName = named === "" ? undefined : named;
  const list = useRef<HTMLDivElement>(null);
  const [open, setHeld] = useControllable(openProp, defaultOpen);
  /** The active option by account id, so it survives a change of `accounts`; null: the default. */
  const [activeId, setActiveId] = useState<string | null>(null);

  const setOpen = (next: boolean): void => {
    if (next && !open) setActiveId(null);
    setHeld(next);
    onOpenChange?.(next);
  };

  const held = accounts.findIndex((account) => account.id === activeId);
  const chosen = accounts.findIndex((account) => account.selected);
  const current = held >= 0 ? held : chosen >= 0 ? chosen : firstIndex(accounts, NONE);
  const optionId = (index: number): string => `${id}-option-${String(index)}`;

  // The active option stays in view in a long list (its own document, so a popped-out panel works too).
  useEffect(() => {
    if (!open || current < 0) return;
    list.current?.ownerDocument
      .getElementById(`${id}-option-${String(current)}`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [open, current, id]);

  const moveTo = (index: number): void => {
    const account = accounts[index];
    if (account !== undefined) setActiveId(account.id);
  };

  const onListKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp":
        event.preventDefault();
        moveTo(stepIndex(accounts, current, event.key === "ArrowDown" ? 1 : -1, NONE));
        return;
      case "Home":
      case "End":
        event.preventDefault();
        moveTo((event.key === "Home" ? firstIndex : lastIndex)(accounts, NONE));
        return;
      case " ": {
        event.preventDefault();
        const account = accounts[current];
        if (account !== undefined) onToggle(account.id);
        return;
      }
      case "Enter":
        // The choices are already applied: Enter only closes, and focus returns to the trigger.
        event.preventDefault();
        setOpen(false);
        return;
      default:
        return;
    }
  };

  const own = trigger.props;
  const anchor = cloneElement(trigger, {
    id: triggerId,
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
      own.onKeyDown?.(event);
      if (event.defaultPrevented) return;
      if (event.key === "ArrowDown" && event.altKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        if (!open) setOpen(true);
      }
    },
  });
  const dense = density === undefined ? {} : { density };

  return (
    <span className="cv-account-multi-select" data-cmp="CMP-105" data-mode={mode}>
      <Popover
        open={open}
        onOpenChange={setOpen}
        anchor={anchor}
        aria-labelledby={triggerId}
        initialFocusRef={list}
        className="cv-account-multi-select__panel"
        footer={
          <Button variant="ghost" {...dense} onClick={() => onSelectAll()}>
            Select all
          </Button>
        }
      >
        <div
          ref={list}
          role="listbox"
          aria-multiselectable="true"
          aria-label={listName}
          aria-labelledby={listName === undefined ? triggerId : undefined}
          aria-activedescendant={current >= 0 ? optionId(current) : undefined}
          tabIndex={0}
          className="cv-account-multi-select__list"
          data-density={density}
          onKeyDown={onListKeyDown}
        >
          {accounts.map((account, index) => (
            // The row is a presentational pointer target; the option inside it holds the state and its name, and
            // the list keeps DOM focus and drives the options (as CMP-009's rows do).
            <div
              key={account.id}
              role="presentation"
              className="cv-account-multi-select__row"
              data-active={index === current ? "" : undefined}
              onPointerMove={() => {
                if (index !== current) setActiveId(account.id);
              }}
              onClick={() => {
                setActiveId(account.id);
                onToggle(account.id);
              }}
            >
              <div
                id={optionId(index)}
                role="option"
                aria-selected={account.selected}
                className="cv-account-multi-select__option"
              >
                <span className="cv-account-multi-select__box" aria-hidden="true">
                  {account.selected ? <Icon name="check" size="sm" /> : null}
                </span>
                <span className="cv-account-multi-select__label">{account.label}</span>
              </div>
            </div>
          ))}
        </div>
      </Popover>
    </span>
  );
}
