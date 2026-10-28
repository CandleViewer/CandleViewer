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
  type RefObject,
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
import {
  pointAnchor,
  useAnchoredPosition,
  type AnchoredAlign,
  type AnchorReference,
} from "./internal/useAnchoredPosition.js";
import { useControllable } from "./internal/useControllable.js";

/** An item's role: `menuitem`, `menuitemcheckbox` or `menuitemradio` (H16). */
export type MenuItemKind = "action" | "checkbox" | "radio";

/** Consecutive items with the same group id form one `role="group"`, a separator between groups. */
export interface MenuGroup {
  readonly id: string;
  /** A caption above the group (`type.ui.caption`, not focusable) that names it. */
  readonly label?: string;
}

interface MenuItemShared {
  /** Stable key, unique within its menu. */
  readonly id: string;
  /** The item's whole name; never truncated (it wraps). */
  readonly label: string;
  readonly group?: MenuGroup;
  /** A leading registry glyph (decorative). */
  readonly icon?: IconName;
  /** A second line, and the item's description (a busy item's "Loading Sub-1 · LIVE…"). */
  readonly description?: string;
  /** Unavailable to everyone right now: reached by the arrows, never activated (`opacity.disabled`). */
  readonly disabled?: boolean;
  /** Gated (T2, rendering 2a): the lock, the label in tertiary, this reason as the second line. Wins over the rest. */
  readonly disabledReason?: string;
  /** The host is still loading what it acts on: CMP-014 leads the label, `aria-busy`, never activated. */
  readonly busy?: boolean;
}

/** An item that acts. */
export interface MenuActionItem extends MenuItemShared {
  /** Runs on activation; never for a disabled, busy or gated item. */
  readonly onSelect: () => void;
  /** Default `action`. A `checkbox` or `radio` item toggles on `Space` and keeps the menu open. */
  readonly kind?: MenuItemKind;
  /** The host's state of a checkable item (`aria-checked`, the `check` glyph). */
  readonly checked?: boolean;
  /** The bound keys in the keymap's display form (`["Ctrl", "D"]`): a trailing CMP-022 and `aria-keyshortcuts`. */
  readonly shortcut?: readonly string[];
  /** Destructive: moved to the menu's last group, described "Destructive action" (H16). */
  readonly danger?: boolean;
  /** Opens a CMP-044 confirm: the label ends with "…". */
  readonly opensConfirm?: boolean;
  readonly items?: undefined;
}

/**
 * An item that opens a submenu (`aria-haspopup="menu"`, `aria-expanded`, a trailing `chevron-right`): `→`, Enter,
 * Space or a click opens it on its first item. It has no action, shortcut, check or danger of its own.
 */
export interface MenuSubmenuItem extends MenuItemShared {
  readonly items: readonly MenuItem[];
  readonly onSelect?: undefined;
  readonly kind?: undefined;
  readonly checked?: undefined;
  readonly shortcut?: undefined;
  readonly danger?: undefined;
  readonly opensConfirm?: undefined;
}

export type MenuItem = MenuActionItem | MenuSubmenuItem;

/** The props Menu composes onto its trigger; the trigger's own handlers run first. */
export interface MenuTriggerProps {
  id?: string | undefined;
  "aria-haspopup"?: "menu" | undefined;
  "aria-expanded"?: boolean | undefined;
  "aria-controls"?: string | undefined;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
}

interface MenuOwnProps {
  items: readonly MenuItem[];
  /** Controlled open state; leave it out to let the trigger (or the context target) open it (`defaultOpen`). */
  open?: boolean;
  defaultOpen?: boolean;
  /** Called with `false` on Esc, Tab, an activation, an outside press and focus leaving the menu. */
  onOpenChange?: (open: boolean) => void;
  /** The type-ahead clock, ms (`performance.now` by default); injectable for tests. */
  now?: () => number;
  className?: string;
}

/** A menu button: the trigger opens the menu below it. */
export interface MenuButtonProps extends MenuOwnProps {
  /** One button (CMP-001 or CMP-002): it opens the menu, names it and gets its ARIA. */
  trigger: ReactElement<MenuTriggerProps>;
  contextTarget?: undefined;
  /** Overrides the name the menu takes from its trigger. */
  "aria-label"?: string;
}

/** A context menu: a right-click opens it at the pointer, `Shift+F10` or the Menu key below the focused element. */
export interface ContextMenuProps extends MenuOwnProps {
  /** The element the context trigger listens on (a grid, a row); focus returns to the element it opened from. */
  contextTarget: RefObject<HTMLElement | null>;
  trigger?: undefined;
  /** A context menu has no trigger to name it. */
  "aria-label": string;
}

export type MenuProps = MenuButtonProps | ContextMenuProps;

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

const opensSubmenu = (item: MenuItem): item is MenuSubmenuItem => item.items !== undefined;

/** True when any item, at any depth, carries a T2 reason (the menu then renders its status region). */
const anyReason = (items: readonly MenuItem[]): boolean =>
  items.some((item) => reasonOf(item) !== undefined || anyReason(item.items ?? []));

/** What a focusable element in a context target looks like (the origin a right-click lands in). */
const FOCUSABLE = "[tabindex], button, a[href], input, select, textarea";

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

/** What every level of one menu shares: the root's close, its origin and its announcer. */
interface MenuRoot {
  /** Set while the menu moves focus itself, so no level's `focusout` closes it a second time. */
  readonly leaving: { current: boolean };
  /** Moves focus to `target` (the origin by default) and closes every level. */
  readonly closeAll: (target?: HTMLElement | null) => void;
  /** Tab / Shift+Tab: closes every level and moves on from the origin. */
  readonly tabOut: (back: boolean) => void;
  /** A press on a gated item: its reason, announced once per press. */
  readonly refuse: (key: string, reason: string) => void;
  /** An item took focus: a re-shown reason that is not its own is cleared. */
  readonly focused: (key: string) => void;
  readonly now: () => number;
}

/**
 * The context trigger on `host`: a right-click at the pointer, Shift+F10 or the Menu key on the focused element.
 * The key also makes the browser fire `contextmenu`; a right-click always presses first, so `byKey` tells them
 * apart. The flag ends with the key's `contextmenu`, a press, another key, or a macrotask after the key is released
 * (where no `contextmenu` follows), so a later synthetic `contextmenu` is never swallowed. Returns the teardown.
 */
function listenForContext(
  host: HTMLElement,
  open: (from: HTMLElement, at: AnchorReference) => void,
): () => void {
  let byKey = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const isContextKey = (event: globalThis.KeyboardEvent): boolean =>
    event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey);
  const onKey = (event: globalThis.KeyboardEvent): void => {
    if (event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey) return;
    if (!isContextKey(event)) {
      if (event.key !== "Shift") byKey = false;
      return;
    }
    event.preventDefault();
    clearTimeout(timer);
    byKey = true;
    const from =
      event.target instanceof HTMLElement && host.contains(event.target) ? event.target : host;
    open(from, from);
  };
  const onContext = (event: globalThis.MouseEvent): void => {
    event.preventDefault();
    if (byKey) {
      byKey = false;
      return;
    }
    const active = document.activeElement;
    const pressed = event.target instanceof Element ? event.target.closest(FOCUSABLE) : null;
    const from =
      active instanceof HTMLElement && active !== host && host.contains(active)
        ? active
        : pressed instanceof HTMLElement && host.contains(pressed)
          ? pressed
          : host;
    open(from, pointAnchor(event.clientX, event.clientY));
  };
  const onDown = (): void => {
    byKey = false;
  };
  const onKeyUp = (event: globalThis.KeyboardEvent): void => {
    if (!byKey || (event.key !== "ContextMenu" && event.key !== "F10")) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      byKey = false;
    }, 0);
  };
  // Bubbling to the document: the keys move focus into the menu, so their keyup is not on the target.
  host.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKeyUp);
  host.addEventListener("contextmenu", onContext);
  host.addEventListener("pointerdown", onDown);
  return () => {
    clearTimeout(timer);
    host.removeEventListener("keydown", onKey);
    document.removeEventListener("keyup", onKeyUp);
    host.removeEventListener("contextmenu", onContext);
    host.removeEventListener("pointerdown", onDown);
  };
}

/**
 * CMP-041 Menu: the WAI-ARIA APG Menu Button, or a context menu. Enter, Space or ↓ on the trigger opens it on its
 * first item, ↑ on its last; a menu whose items all pick one value (radio) opens on its checked item. The arrows
 * wrap and reach every item, disabled, busy and gated ones too, none of which is ever activated; type-ahead moves to
 * the next label that starts with the typed text. Enter activates and closes, focus back on the trigger (or into
 * the dialog the item opens); Space toggles a checkable item and keeps it open; Tab closes every level and moves on
 * from the trigger; Esc closes the topmost level through the overlay layer stack. An item with `items` opens a
 * submenu on `→`, Enter, Space or a click, at its first item, beside its row; `←` or Esc closes only that submenu,
 * focus back on its item. With `contextTarget` instead of a trigger, a right-click opens it at the pointer (a
 * point-anchored virtual reference) and `Shift+F10` or the Menu key below the focused element; focus returns to
 * that element. Anchored by `useAnchoredPosition` with `fit`, its height capped to the room on its side (it
 * scrolls). It opens at once and fades out over `fast`; submenus switch at once.
 */
export function Menu(props: MenuProps): JSX.Element {
  const {
    items,
    open: openProp,
    defaultOpen = false,
    onOpenChange,
    now = () => performance.now(),
    className,
  } = props;
  const ariaLabel = props["aria-label"];
  const triggerElement = props.trigger;
  const contextTarget = props.contextTarget;
  const id = useId();
  const [open, setHeld] = useControllable(openProp, defaultOpen);
  /** Where focus returns: the trigger, or the element a context menu opened from. */
  const origin = useRef<HTMLElement | null>(null);
  /** What the menu is positioned against: the trigger, the focused element, or the pointer. */
  const anchor = useRef<AnchorReference | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);
  /** Where the next open puts focus; read once by the open effect. */
  const pending = useRef<Start>("first");
  const leaving = useRef(false);
  // The gated item whose reason a press re-showed, and how many times (the count re-keys the status node).
  const [recall, setRecall] = useState<{ key: string; text?: string; count: number }>({
    key: "",
    count: 0,
  });

  const flat = sectionsOf(items).flatMap((section) => section.items);
  const pickOne = flat.length > 0 && flat.every((item) => item.kind === "radio");
  const startAt = useRef(0);
  startAt.current = Math.max(pickOne ? flat.findIndex((item) => item.checked === true) : -1, 0);
  const triggerId = triggerElement?.props.id ?? `${id}-trigger`;

  // What this menu last reported or rendered: an outside press and the focus loss it causes report one close.
  // A host that ignores the report (controlled, it keeps `open`) renders nothing new, so after a macrotask the
  // rendered state wins again and the next Esc or outside press is reported too.
  const rendered = useRef(open);
  rendered.current = open;
  const reported = useRef(open);
  reported.current = open;
  const change = (next: boolean): void => {
    if (reported.current === next) return;
    reported.current = next;
    setHeld(next);
    onOpenChange?.(next);
    setTimeout(() => {
      reported.current = rendered.current;
    }, 0);
  };
  const latest = useRef(change);
  latest.current = change;

  // A controlled open has no press to read its origin from, and a trigger may remount while the menu stays
  // open: every open render re-resolves it (the trigger by its id, else the context target) unless the held
  // element is still in the document.
  useLayoutEffect(() => {
    if (!open || origin.current?.isConnected === true) return;
    const found =
      triggerElement === undefined
        ? (contextTarget?.current ?? null)
        : document.getElementById(triggerId);
    origin.current = found;
    if (triggerElement !== undefined || anchor.current === null) anchor.current = found;
  });

  const nodes = (): HTMLElement[] =>
    surface.current === null
      ? []
      : [...surface.current.querySelectorAll<HTMLElement>("[data-menu-item]")];

  const openAt = (start: Start): void => {
    pending.current = start;
    if (open) {
      const list = nodes();
      (start === "last" ? list[list.length - 1] : list[startAt.current])?.focus();
      return;
    }
    change(true);
  };

  /** Opens a context menu from `from` (focus returns there), positioned against `at`. */
  const openFrom = useRef((from: HTMLElement, at: AnchorReference): void => {
    origin.current = from;
    anchor.current = at;
    pending.current = "first";
    latest.current(true);
  });

  // The context target's element, re-resolved after every render: a target swapped or mounted after the Menu
  // is bound on the Menu's next render (a target that mounts later without one is never bound).
  const bound = useRef<{ element: HTMLElement | null; release: () => void }>({
    element: null,
    release: () => undefined,
  });
  useEffect(() => {
    const element = contextTarget?.current ?? null;
    if (element === bound.current.element) return;
    bound.current.release();
    const release =
      element === null
        ? () => undefined
        : listenForContext(element, (from, at) => openFrom.current(from, at));
    bound.current = { element, release };
  });
  useEffect(() => {
    const binding = bound;
    return () => {
      binding.current.release();
      binding.current = { element: null, release: () => undefined };
    };
  }, []);

  const root: MenuRoot = {
    leaving,
    closeAll: (target = origin.current) => {
      leaving.current = true;
      target?.focus({ preventScroll: true });
      leaving.current = false;
      latest.current(false);
    },
    tabOut: (back) => {
      const from = origin.current;
      const next =
        from === null
          ? undefined
          : back
            ? tabStopBefore(from, surface.current)
            : tabStopAfter(from, surface.current);
      root.closeAll(next ?? from);
    },
    refuse: (key, text) => setRecall((prev) => ({ key, text, count: prev.count + 1 })),
    focused: (key) => {
      if (recall.key !== key && recall.text !== undefined)
        setRecall((prev) => ({ key: "", count: prev.count }));
    },
    now,
  };

  const own = triggerElement?.props;
  const triggerProps: MenuTriggerProps = {
    id: triggerId,
    "aria-haspopup": "menu",
    "aria-expanded": open,
    "aria-controls": id,
    onClick: (event) => {
      own?.onClick?.(event);
      if (event.defaultPrevented) return;
      origin.current = event.currentTarget;
      anchor.current = event.currentTarget;
      if (open) change(false);
      else openAt("first");
    },
    onKeyDown: (event) => {
      own?.onKeyDown?.(event);
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return; // Enter and Space click
      event.preventDefault();
      origin.current = event.currentTarget;
      anchor.current = event.currentTarget;
      openAt(event.key === "ArrowUp" ? "last" : "first");
    },
  };

  const isContext = triggerElement === undefined;
  return (
    <>
      {isContext ? null : cloneElement(triggerElement, triggerProps)}
      {anyReason(items) ? (
        <span className="cv-visually-hidden" role="status">
          {recall.text === undefined ? null : <span key={recall.count}>{recall.text}</span>}
        </span>
      ) : null}
      <MenuSurface
        root={root}
        id={id}
        level={0}
        items={items}
        surface={surface}
        open={open}
        anchor={anchor}
        side="bottom"
        align={isContext ? "start" : "center"}
        labelledBy={ariaLabel === undefined ? triggerId : undefined}
        label={ariaLabel}
        className={className}
        startIndex={() => {
          const at = pending.current === "last" ? -1 : startAt.current;
          pending.current = "first";
          return at;
        }}
        returnTo={() => origin.current}
        onBack={() => root.closeAll()}
        onLeave={(next) => {
          if (origin.current?.contains(next) !== true || isContext) change(false);
        }}
        exempt={(node) => !isContext && origin.current?.contains(node) === true}
      />
    </>
  );
}

interface MenuSurfaceProps {
  readonly root: MenuRoot;
  readonly id: string;
  /** 0 for the menu itself, 1 for its submenus, and so on. */
  readonly level: number;
  readonly items: readonly MenuItem[];
  readonly surface: { current: HTMLDivElement | null };
  readonly open: boolean;
  readonly anchor: RefObject<AnchorReference | null>;
  readonly side: "bottom" | "right";
  readonly align: AnchoredAlign;
  readonly labelledBy?: string | undefined;
  readonly label?: string | undefined;
  readonly className?: string | undefined;
  /** The item focus lands on when it opens (-1: the last); read once per open. */
  readonly startIndex: () => number;
  /** Where focus goes when this level closes with focus inside it, or lost. */
  readonly returnTo: () => HTMLElement | null;
  /** Esc (and `←` on a submenu): closes this level only, focus back where it opened from. */
  readonly onBack: () => void;
  /** Focus left this level for `next`, which is neither inside it nor in a layer above it. */
  readonly onLeave: (next: Node) => void;
  /** The menu itself only: a press on what this returns true for is not an outside press (its trigger). */
  readonly exempt?: (node: Node) => boolean;
}

/**
 * One level: the portalled `role="menu"` surface, its layer, its keys and its rows, and the one submenu open from
 * it (rendered beside it, outside its surface, so the submenu's events never reach this level's handlers).
 */
function MenuSurface({
  root,
  id,
  level,
  items,
  surface,
  open,
  anchor,
  side,
  align,
  labelledBy,
  label,
  className,
  startIndex,
  returnTo,
  onBack,
  onLeave,
  exempt,
}: MenuSurfaceProps): JSX.Element {
  const portalRoot = useLayerPortal();
  const typed = useRef<Typed>({ text: "", at: 0 });
  /** The flat index of the item whose submenu is open, or -1. */
  const [expanded, setExpanded] = useState(-1);
  const subSurface = useRef<HTMLDivElement | null>(null);
  const subAnchor = useRef<HTMLElement | null>(null);
  const isRoot = level === 0;

  const sections = sectionsOf(items);
  const flat = sections.flatMap((section) => section.items);
  const itemId = (index: number): string => `${id}-item-${String(index)}`;
  const subId = (index: number): string => `${itemId(index)}-menu`;

  useAnchoredPosition({ open, reference: anchor, floating: surface, side, align, fit: true });

  const nodes = (): HTMLElement[] =>
    surface.current === null
      ? []
      : [...surface.current.querySelectorAll<HTMLElement>("[data-menu-item]")];

  // The latest callbacks, read by the effects below (which run per open, not per render).
  const live = useRef({ startIndex, returnTo, exempt, root });
  live.current = { startIndex, returnTo, exempt, root };

  // Focus in on open (conventions 32); on close, back where it opened from when focus is inside or lost.
  useEffect(() => {
    const menu = surface.current;
    if (!open || menu === null) return undefined;
    const list = [...menu.querySelectorAll<HTMLElement>("[data-menu-item]")];
    const at = live.current.startIndex();
    const target = (at < 0 ? list[list.length - 1] : list[at]) ?? menu;
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ block: "nearest" });
    return () => {
      typed.current = { text: "", at: 0 };
      setExpanded(-1);
      const active = document.activeElement;
      const lost = active === null || active === document.body || menu.contains(active);
      const back = live.current.returnTo();
      if (lost && back?.isConnected === true) back.focus({ preventScroll: true });
    };
  }, [open, surface]);

  const layer = useLayer(open, { element: surface, modal: false, onEscape: () => onBack() });

  // The menu itself: an outside press closes every level (a press in a submenu or a layer opened above does not);
  // focus goes where the press lands.
  useEffect(() => {
    if (!open || !isRoot) return undefined;
    const onDown = (event: PointerEvent): void => {
      const target = event.target instanceof Node ? event.target : null;
      if (target === null || surface.current?.contains(target) === true) return;
      if (live.current.exempt?.(target) === true || layer.inLayerAbove(target)) return;
      live.current.root.closeAll(null);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open, layer, isRoot, surface]);

  const focusAt = (index: number): void => nodes()[index]?.focus();

  /** Opens the submenu of the item at `index` on its first item (or focuses it, already open). */
  const openSub = (index: number): void => {
    if (expanded === index) {
      subSurface.current?.querySelector<HTMLElement>("[data-menu-item]")?.focus();
      return;
    }
    subAnchor.current = nodes()[index]?.closest<HTMLElement>(".cv-menu__row") ?? null;
    setExpanded(index);
  };

  /** Closes the open submenu, focus back on its item. */
  const closeSub = (): void => {
    const item = nodes()[expanded];
    root.leaving.current = true;
    item?.focus({ preventScroll: true });
    root.leaving.current = false;
    setExpanded(-1);
  };

  const activate = (index: number, how: "enter" | "space" | "click" | "right"): void => {
    const item = flat[index];
    if (item === undefined) return;
    const state = stateOf(item);
    const reason = reasonOf(item);
    // A press (Enter, Space, a click) re-shows a T2 reason; a plain → on a gated submenu item does not.
    if (state === "gated" && reason !== undefined && how !== "right")
      root.refuse(itemId(index), reason);
    if (state !== undefined) return;
    if (opensSubmenu(item)) {
      openSub(index);
      return;
    }
    if (how === "right") return;
    if (how === "space" && checkable(item)) {
      item.onSelect();
      return;
    }
    // A pointer click behaves like Enter, so it closes even on a checkable item (only Space keeps it open).
    // Focus is on the origin before the host runs, so a dialog the item opens returns there.
    root.closeAll();
    item.onSelect();
  };

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
      case "ArrowRight":
        handled();
        if (at >= 0 && flat[at]?.items !== undefined) activate(at, "right");
        return;
      case "ArrowLeft":
        handled();
        if (!isRoot) onBack();
        return;
      case "Escape":
        // The topmost layer takes Esc and stops there (conventions 32): a submenu closes alone.
        handled();
        event.stopPropagation();
        onBack();
        return;
      case "Tab":
        handled();
        root.tabOut(event.shiftKey);
        return;
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
    const next = extendTyped(typed.current, key, root.now());
    typed.current = next;
    const found = matchIndex(flat, at, next.text, shown, () => false);
    if (found >= 0) {
      handled();
      focusAt(found);
    }
  };

  /** Focus left a submenu of this level for `next`: back into this level closes the submenu alone. */
  const leaveFromSub = (next: Node): void => {
    if (surface.current?.contains(next) === true) setExpanded(-1);
    else onLeave(next);
  };

  const onMenuFocusOut = (event: FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget instanceof Node ? event.relatedTarget : null;
    // Focus lost to nothing (the window blurs) keeps it open; an outside press is caught by `pointerdown`.
    if (!open || root.leaving.current || next === null) return;
    if (surface.current?.contains(next) === true || layer.inLayerAbove(next)) return;
    onLeave(next);
  };

  /** Each section's first flat index. */
  const offsets = sections.map((_, at) =>
    sections.slice(0, at).reduce((sum, section) => sum + section.items.length, 0),
  );
  const opened = open ? flat[expanded] : undefined;
  const menu = (
    <div
      ref={surface}
      id={id}
      role="menu"
      aria-labelledby={label === undefined ? labelledBy : undefined}
      aria-label={label}
      tabIndex={-1}
      className={cx("cv-menu", isRoot ? undefined : "cv-menu--submenu", className)}
      data-cmp={isRoot ? "CMP-041" : undefined}
      hidden={!open}
      onKeyDown={onMenuKeyDown}
      onBlur={onMenuFocusOut}
      onContextMenu={(event) => event.preventDefault()}
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
                  expanded={expanded === position}
                  controls={expanded === position ? subId(position) : undefined}
                  onActivate={() => activate(position, "click")}
                  onFocus={() => root.focused(itemId(position))}
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
      {portalRoot === null ? null : createPortal(menu, portalRoot)}
      {opened?.items === undefined ? null : (
        <MenuSurface
          key={opened.id}
          root={root}
          id={subId(expanded)}
          level={level + 1}
          items={opened.items}
          surface={subSurface}
          open
          anchor={subAnchor}
          side="right"
          align="start"
          labelledBy={itemId(expanded)}
          startIndex={() => 0}
          returnTo={() => nodes()[expanded] ?? null}
          onBack={closeSub}
          onLeave={leaveFromSub}
        />
      )}
    </>
  );
}

interface MenuRowProps {
  readonly item: MenuItem;
  readonly id: string;
  /** A submenu item whose submenu is open. */
  readonly expanded: boolean;
  /** The open submenu's id. */
  readonly controls: string | undefined;
  readonly onActivate: () => void;
  readonly onFocus: () => void;
}

/**
 * One item. The row (`role="none"`) is the hit target and carries the look; the `menuitem` inside it holds the
 * label alone, so its name is its visible label (WCAG 2.5.3). The second line, the hidden "Destructive action" and
 * the shortcut sit beside it as its description and as `aria-keyshortcuts`, read once (they are `aria-hidden`).
 * A submenu item adds `aria-haspopup="menu"` and `aria-expanded`, and a trailing `chevron-right`.
 */
function MenuRow({ item, id, expanded, controls, onActivate, onFocus }: MenuRowProps): JSX.Element {
  const state = stateOf(item);
  const kind = item.kind ?? "action";
  const reason = reasonOf(item);
  const submenu = opensSubmenu(item);
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
      data-expanded={expanded ? "" : undefined}
      data-lines={second === undefined ? undefined : 2}
      onClick={onActivate}
      onPointerMove={(event) => {
        // The pointer crossing an open submenu's own row on its way in leaves focus in the submenu.
        if (expanded) return;
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
          aria-haspopup={submenu ? "menu" : undefined}
          aria-expanded={submenu ? expanded : undefined}
          aria-controls={controls}
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
      {submenu ? (
        <span className="cv-menu__chevron" aria-hidden="true">
          <Icon name="chevron-right" />
        </span>
      ) : null}
    </div>
  );
}
