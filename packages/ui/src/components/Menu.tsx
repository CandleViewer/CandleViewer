import {
  cloneElement,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
} from "react";
import { createPortal } from "react-dom";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Kbd } from "./Kbd.js";
import { Spinner } from "./Spinner.js";
import { cx } from "./internal/cx.js";
import { useLayer, useLayerPortal } from "./internal/layers.js";
import { extendTyped, matchIndex, type Typed } from "./internal/listNav.js";
import { tabStopAfter, tabStopBefore } from "./internal/tabbable.js";
import { useAnchoredPosition } from "./internal/useAnchoredPosition.js";
import { useControllable } from "./internal/useControllable.js";

/** An item's role: `menuitem`, `menuitemcheckbox` or `menuitemradio` (H16). */
export type MenuItemKind = "action" | "checkbox" | "radio";

/** Consecutive items with the same group id form one `role="group"`, a separator between groups. */
export interface MenuGroup {
  readonly id: string;
  /** A caption above the group (`type.ui.caption`, not focusable) that names it. */
  readonly label?: string;
}

export interface MenuItem {
  /** Stable key, unique within the menu. */
  readonly id: string;
  /** The item's whole name; never truncated (it wraps). */
  readonly label: string;
  /** Runs on activation; never for a disabled, busy or gated item. */
  readonly onSelect: () => void;
  /** Default `action`. A `checkbox` or `radio` item toggles on `Space` and keeps the menu open. */
  readonly kind?: MenuItemKind;
  /** The host's state of a checkable item (`aria-checked`, the `check` glyph). */
  readonly checked?: boolean;
  readonly group?: MenuGroup;
  /** A leading registry glyph (decorative). */
  readonly icon?: IconName;
  /** The bound keys in the keymap's display form (`["Ctrl", "D"]`): a trailing CMP-022 and `aria-keyshortcuts`. */
  readonly shortcut?: readonly string[];
  /** A second line, and the item's description (a busy item's "Loading Sub-1 · LIVE…"). */
  readonly description?: string;
  /** Unavailable to everyone right now: reached by the arrows, never activated (`opacity.disabled`). */
  readonly disabled?: boolean;
  /** Gated (T2, rendering 2a): the lock, the label in tertiary, this reason as the second line. Wins over the rest. */
  readonly disabledReason?: string;
  /** The host is still loading what it acts on: CMP-014 leads the label, `aria-busy`, never activated. */
  readonly busy?: boolean;
  /** Destructive: moved to the menu's last group, described "Destructive action" (H16). */
  readonly danger?: boolean;
  /** Opens a CMP-044 confirm: the label ends with "…". */
  readonly opensConfirm?: boolean;
}

/** The props Menu composes onto its trigger; the trigger's own handlers run first. */
export interface MenuTriggerProps {
  id?: string | undefined;
  "aria-haspopup"?: "menu" | undefined;
  "aria-expanded"?: boolean | undefined;
  "aria-controls"?: string | undefined;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
}

export interface MenuProps {
  /** One button (CMP-001 or CMP-002): it opens the menu, names it and gets its ARIA. */
  trigger: ReactElement<MenuTriggerProps>;
  items: readonly MenuItem[];
  /** Controlled open state; leave it out to let the trigger toggle it (`defaultOpen`). */
  open?: boolean;
  defaultOpen?: boolean;
  /** Called with `false` on Esc, Tab, an activation, an outside press and focus leaving the menu. */
  onOpenChange?: (open: boolean) => void;
  /** Overrides the name the menu takes from its trigger. */
  "aria-label"?: string;
  /** The type-ahead clock, ms (`performance.now` by default); injectable for tests. */
  now?: () => number;
  className?: string;
}

type ItemState = "gated" | "disabled" | "busy" | undefined;

const reasonOf = (item: MenuItem): string | undefined => {
  const reason = item.disabledReason?.trim();
  return reason === "" ? undefined : reason;
};

/** Gated wins (a T2 reason is the one thing a user can act on), then plain disabled, then busy. */
const stateOf = (item: MenuItem): ItemState => {
  if (reasonOf(item) !== undefined) return "gated";
  if (item.disabled === true) return "disabled";
  return item.busy === true ? "busy" : undefined;
};

const checkable = (item: MenuItem): boolean => item.kind === "checkbox" || item.kind === "radio";

const ROLES: Readonly<Record<MenuItemKind, string>> = {
  action: "menuitem",
  checkbox: "menuitemcheckbox",
  radio: "menuitemradio",
};

const shown = (item: MenuItem): string =>
  item.opensConfirm === true && !item.label.endsWith("…") ? `${item.label}…` : item.label;

/** The keymap's display words that `aria-keyshortcuts` spells differently (UI Events key values). */
const ARIA_KEYS: Readonly<Record<string, string>> = {
  Ctrl: "Control",
  Cmd: "Meta",
  Opt: "Alt",
  Del: "Delete",
  Esc: "Escape",
  Ins: "Insert",
  PgUp: "PageUp",
  PgDn: "PageDown",
  Return: "Enter",
  "↑": "ArrowUp",
  "↓": "ArrowDown",
  "←": "ArrowLeft",
  "→": "ArrowRight",
};

const keyShortcuts = (keys: readonly string[] | undefined): string | undefined => {
  const bound = (keys ?? []).map((key) => key.trim()).filter((key) => key !== "");
  if (bound.length === 0) return undefined;
  return bound.map((key) => (Object.hasOwn(ARIA_KEYS, key) ? ARIA_KEYS[key] : key)).join("+");
};

interface Section {
  readonly key: string;
  readonly label: string | undefined;
  readonly items: MenuItem[];
}

/** Runs of one group id, in order; every danger item moves into one last group (H16). */
function sectionsOf(items: readonly MenuItem[]): Section[] {
  const sections: Section[] = [];
  const danger = items.filter((item) => item.danger === true);
  for (const item of items) {
    if (item.danger === true) continue;
    const key = item.group?.id ?? "";
    const last = sections[sections.length - 1];
    if (last?.key === key) last.items.push(item);
    else sections.push({ key, label: item.group?.label, items: [item] });
  }
  if (danger.length > 0) {
    const first = danger[0]?.group;
    const shared = danger.every((item) => item.group?.id === first?.id);
    sections.push({ key: "danger", label: shared ? first?.label : undefined, items: danger });
  }
  return sections;
}

type Start = "first" | "last";

/**
 * CMP-041 Menu: the WAI-ARIA APG Menu Button. Enter, Space or ↓ on the trigger opens it on its first item, ↑ on
 * its last; a menu whose items all pick one value (radio) opens on its checked item. The arrows wrap and reach
 * every item, disabled, busy and gated ones too, none of which is ever activated; type-ahead moves to the next
 * label that starts with the typed text. Enter activates and closes, focus back on the trigger (or into the dialog
 * the item opens); Space toggles a checkable item and keeps it open; Tab closes it and moves on from the trigger;
 * Esc closes it through the overlay layer stack, focus back on the trigger. Anchored by `useAnchoredPosition`
 * with `fit`, its height capped to the room on its side (it scrolls). It opens at once and fades out over `fast`.
 */
export function Menu({
  trigger: triggerElement,
  items,
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  "aria-label": ariaLabel,
  now = () => performance.now(),
  className,
}: MenuProps): JSX.Element {
  const id = useId();
  const portalRoot = useLayerPortal();
  const [open, setHeld] = useControllable(openProp, defaultOpen);
  const trigger = useRef<HTMLElement | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);
  /** Where the next open puts focus; read once by the open effect. */
  const pending = useRef<Start>("first");
  /** Set while this component moves focus out itself, so `focusout` does not close it a second time. */
  const leaving = useRef(false);
  const typed = useRef<Typed>({ text: "", at: 0 });
  // The gated item whose reason a press re-showed, and how many times (the count re-keys the status node).
  const [recall, setRecall] = useState({ index: -1, count: 0 });

  const sections = sectionsOf(items);
  const flat = sections.flatMap((section) => section.items);
  const pickOne = flat.length > 0 && flat.every((item) => item.kind === "radio");
  const checkedAt = pickOne ? flat.findIndex((item) => item.checked === true) : -1;
  const startAt = useRef(0);
  startAt.current = Math.max(checkedAt, 0);
  const triggerId = triggerElement.props.id ?? `${id}-trigger`;
  const itemId = (index: number): string => `${id}-item-${String(index)}`;

  // What this menu last reported or rendered: an outside press and the focus loss it causes report one close.
  const reported = useRef(open);
  reported.current = open;
  const change = (next: boolean): void => {
    if (reported.current === next) return;
    reported.current = next;
    setHeld(next);
    onOpenChange?.(next);
  };
  const latest = useRef(change);
  latest.current = change;

  // A controlled open has no press to read the trigger from, and a trigger may remount while the menu stays
  // open: every open render re-resolves it by its id unless the held element is still in the document.
  useLayoutEffect(() => {
    if (!open || trigger.current?.isConnected === true) return;
    trigger.current = document.getElementById(triggerId);
  });

  useAnchoredPosition({ open, reference: trigger, floating: surface, side: "bottom", fit: true });

  const nodes = (): HTMLElement[] =>
    surface.current === null
      ? []
      : [...surface.current.querySelectorAll<HTMLElement>("[data-menu-item]")];

  // Focus in on open (conventions 32); on close, back to the trigger when focus is inside or lost.
  useEffect(() => {
    const menu = surface.current;
    if (!open || menu === null) return undefined;
    const list = nodes();
    const target =
      (pending.current === "last" ? list[list.length - 1] : list[startAt.current]) ?? menu;
    pending.current = "first";
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ block: "nearest" });
    return () => {
      typed.current = { text: "", at: 0 };
      const active = document.activeElement;
      const lost = active === null || active === document.body || menu.contains(active);
      const back = trigger.current;
      if (lost && back?.isConnected === true) back.focus({ preventScroll: true });
    };
  }, [open]);

  const layer = useLayer(open, {
    element: surface,
    modal: false,
    onEscape: () => {
      trigger.current?.focus({ preventScroll: true });
      latest.current(false);
    },
  });

  // An outside press closes it (a press in a layer opened above it does not); focus goes where the press lands.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: PointerEvent): void => {
      const target = event.target instanceof Node ? event.target : null;
      if (target === null || surface.current?.contains(target) === true) return;
      if (trigger.current?.contains(target) === true || layer.inLayerAbove(target)) return;
      latest.current(false);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open, layer]);

  const openAt = (start: Start): void => {
    pending.current = start;
    if (open) {
      const list = nodes();
      (start === "last" ? list[list.length - 1] : list[startAt.current])?.focus();
      return;
    }
    change(true);
  };

  /** Moves focus to `target` (the trigger by default) and closes. */
  const closeTo = (target: HTMLElement | null | undefined = trigger.current): void => {
    leaving.current = true;
    target?.focus({ preventScroll: true });
    leaving.current = false;
    change(false);
  };

  const refuse = (index: number): void => setRecall((prev) => ({ index, count: prev.count + 1 }));

  const activate = (index: number, how: "enter" | "space" | "click"): void => {
    const item = flat[index];
    if (item === undefined) return;
    const state = stateOf(item);
    if (state === "gated") refuse(index);
    if (state !== undefined) return;
    if (how === "space" && checkable(item)) {
      item.onSelect();
      return;
    }
    // A pointer click behaves like Enter, so it closes even on a checkable item (only Space keeps it open).
    // Focus is on the trigger before the host runs, so a dialog the item opens returns there.
    closeTo();
    item.onSelect();
  };

  const focusAt = (index: number): void => nodes()[index]?.focus();

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.ctrlKey || event.altKey || event.metaKey || event.nativeEvent.isComposing) return;
    const count = flat.length;
    const at = nodes().findIndex((node) => node === document.activeElement);
    const { key } = event;
    const handled = (): void => event.preventDefault();
    switch (key) {
      case "ArrowDown":
        handled();
        if (count > 0) focusAt(at < 0 ? 0 : (at + 1) % count);
        return;
      case "ArrowUp":
        handled();
        if (count > 0) focusAt(at < 0 ? count - 1 : (at - 1 + count) % count);
        return;
      case "Home":
      case "End":
        handled();
        focusAt(key === "Home" ? 0 : count - 1);
        return;
      case "Escape":
        // The topmost layer takes Esc and stops there (conventions 32).
        handled();
        event.stopPropagation();
        closeTo();
        return;
      case "Tab": {
        handled();
        const from = trigger.current;
        const next =
          from === null
            ? undefined
            : event.shiftKey
              ? tabStopBefore(from, surface.current)
              : tabStopAfter(from, surface.current);
        closeTo(next ?? from);
        return;
      }
      case "Enter":
      case " ":
        handled();
        activate(at, key === "Enter" ? "enter" : "space");
        return;
      default:
        break;
    }
    if (key.length !== 1) return;
    // Space is the activation key above (APG), so type-ahead never matches past a space ("Move u" at most).
    // Type-ahead (APG): printables extend a short-lived string; the next label that starts with it takes focus.
    const next = extendTyped(typed.current, key, now());
    typed.current = next;
    const found = matchIndex(flat, at, next.text, shown, () => false);
    if (found >= 0) {
      handled();
      focusAt(found);
    }
  };

  const onMenuFocusOut = (event: FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget instanceof Node ? event.relatedTarget : null;
    if (!open || leaving.current || next === null) return;
    if (surface.current?.contains(next) === true || trigger.current?.contains(next) === true)
      return;
    if (!layer.inLayerAbove(next)) change(false);
  };

  const own = triggerElement.props;
  const triggerProps: MenuTriggerProps = {
    id: triggerId,
    "aria-haspopup": "menu",
    "aria-expanded": open,
    "aria-controls": id,
    onClick: (event) => {
      own.onClick?.(event);
      if (event.defaultPrevented) return;
      trigger.current = event.currentTarget;
      if (open) change(false);
      else openAt("first");
    },
    onKeyDown: (event) => {
      own.onKeyDown?.(event);
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return; // Enter and Space click
      event.preventDefault();
      trigger.current = event.currentTarget;
      openAt(event.key === "ArrowUp" ? "last" : "first");
    },
  };

  const recalled = flat[recall.index];
  const said = recalled === undefined ? undefined : reasonOf(recalled);
  /** Each section's first flat index. */
  const offsets = sections.map((_, at) =>
    sections.slice(0, at).reduce((sum, section) => sum + section.items.length, 0),
  );
  const menu = (
    <div
      ref={surface}
      id={id}
      role="menu"
      aria-labelledby={ariaLabel === undefined ? triggerId : undefined}
      aria-label={ariaLabel}
      tabIndex={-1}
      className={cx("cv-menu", className)}
      data-cmp="CMP-041"
      hidden={!open}
      onKeyDown={onMenuKeyDown}
      onBlur={onMenuFocusOut}
    >
      {sections.map((section, at) => {
        const groupLabelId = `${id}-group-${String(at)}`;
        return [
          at === 0 ? null : (
            <div key={`sep-${String(at)}`} role="separator" className="cv-menu__separator" />
          ),
          <div
            key={`group-${String(at)}`}
            role="group"
            aria-labelledby={section.label === undefined ? undefined : groupLabelId}
            className="cv-menu__group"
          >
            {section.label === undefined ? null : (
              <div id={groupLabelId} className="cv-menu__group-label" aria-hidden="true">
                {section.label}
              </div>
            )}
            {section.items.map((item, inSection) => {
              const position = (offsets[at] ?? 0) + inSection;
              return (
                <MenuRow
                  key={item.id}
                  item={item}
                  id={itemId(position)}
                  onActivate={() => activate(position, "click")}
                  onFocus={() => {
                    if (recall.index !== position)
                      setRecall((prev) => ({ index: -1, count: prev.count }));
                  }}
                />
              );
            })}
          </div>,
        ];
      })}
    </div>
  );

  return (
    <>
      {cloneElement(triggerElement, triggerProps)}
      {flat.some((item) => reasonOf(item) !== undefined) ? (
        <span className="cv-visually-hidden" role="status">
          {said === undefined ? null : <span key={recall.count}>{said}</span>}
        </span>
      ) : null}
      {portalRoot === null ? null : createPortal(menu, portalRoot)}
    </>
  );
}

interface MenuRowProps {
  readonly item: MenuItem;
  readonly id: string;
  readonly onActivate: () => void;
  readonly onFocus: () => void;
}

/**
 * One item. The row (`role="none"`) is the hit target and carries the look; the `menuitem` inside it holds the
 * label alone, so its name is its visible label (WCAG 2.5.3). The second line, the hidden "Destructive action" and
 * the shortcut sit beside it as its description and as `aria-keyshortcuts`, read once (they are `aria-hidden`).
 */
function MenuRow({ item, id, onActivate, onFocus }: MenuRowProps): JSX.Element {
  const state = stateOf(item);
  const kind = item.kind ?? "action";
  const reason = reasonOf(item);
  const second = reason ?? item.description;
  const secondId = `${id}-second`;
  const dangerId = `${id}-danger`;
  const describedBy =
    [second === undefined ? "" : secondId, item.danger === true ? dangerId : ""]
      .filter((part) => part !== "")
      .join(" ") || undefined;
  const checked = checkable(item) ? item.checked === true : undefined;
  const lead =
    state === "busy" ? (
      <Spinner size="sm" />
    ) : state === "gated" ? (
      <Icon name="lock" />
    ) : checked !== undefined ? (
      checked ? (
        <Icon name="check" />
      ) : null
    ) : item.icon === undefined ? null : (
      <Icon name={item.icon} />
    );
  return (
    <div
      role="none"
      className="cv-menu__row"
      data-state={state}
      data-danger={item.danger === true ? "" : undefined}
      data-checked={checked === true ? "" : undefined}
      data-lines={second === undefined ? undefined : 2}
      onClick={onActivate}
      onPointerMove={(event) => {
        const target = event.currentTarget.querySelector<HTMLElement>("[data-menu-item]");
        if (target !== null && document.activeElement !== target)
          target.focus({ preventScroll: true });
      }}
    >
      <span className="cv-menu__lead" aria-hidden="true">
        {lead}
      </span>
      <span className="cv-menu__body">
        <span
          id={id}
          role={ROLES[kind]}
          tabIndex={-1}
          className="cv-menu__item"
          data-menu-item=""
          aria-describedby={describedBy}
          aria-disabled={state === "gated" || state === "disabled" ? true : undefined}
          aria-busy={state === "busy" ? true : undefined}
          aria-checked={checked}
          aria-keyshortcuts={keyShortcuts(item.shortcut)}
          onFocus={onFocus}
        >
          {shown(item)}
        </span>
        {second === undefined ? null : (
          <span id={secondId} className="cv-menu__second" aria-hidden="true">
            {second}
          </span>
        )}
      </span>
      {item.danger === true ? (
        <span id={dangerId} className="cv-visually-hidden" aria-hidden="true">
          Destructive action
        </span>
      ) : null}
      {item.shortcut === undefined ? null : (
        <Kbd keys={item.shortcut} aria-hidden="true" className="cv-menu__kbd" />
      )}
    </div>
  );
}
