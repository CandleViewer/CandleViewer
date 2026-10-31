import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import { Button } from "./Button.js";
import { IconButton } from "./IconButton.js";
import { Menu, type MenuItem } from "./Menu.js";
import { cx } from "./internal/cx.js";
import { useRoving } from "./internal/useRoving.js";

/** A list's symbol cap (E08-D07 §1, `22` `WatchlistInput.symbols` `maxItems: 200`). */
export const WATCHLIST_SYMBOL_CAP = 200;
/** From here a list's count reads against the cap (E08-D07 D10). */
export const WATCHLIST_NEAR_CAP = 180;

/** A list's name with its count, as a tab and a list menu item read it (E08-D07 §4.2, D10). */
export function watchlistCountName(name: string, count: number): string {
  if (count >= WATCHLIST_NEAR_CAP) return `${name}, ${count} of ${WATCHLIST_SYMBOL_CAP} symbols`;
  return `${name}, ${count} ${count === 1 ? "symbol" : "symbols"}`;
}

/** A saved list (`22` `Watchlist`): its id and name. */
export interface WatchlistGroup {
  readonly id: string;
  readonly name: string;
}

export interface WatchlistGroupTabsProps {
  readonly groups: readonly WatchlistGroup[];
  /** Each list's symbol count, by id: the tab's "· 12" and its name "Majors, 12 symbols". */
  readonly counts: Readonly<Record<string, number>>;
  /** The list the panel shows. */
  readonly activeId: string | undefined;
  /**
   * `Enter`, `Space` or a click on a tab, or a list chosen from "More lists". Manual activation: a switch changes
   * the panel's subscriptions (`23` L1190), so the arrows only move focus.
   */
  readonly onSwitch: (id: string) => void;
  /** "+" (New watchlist). */
  readonly onCreate: () => void;
  readonly onRename: (id: string) => void;
  readonly onDuplicate: (id: string) => void;
  /** Delete… (the host's CMP-044 confirm, E08-D07 D26). */
  readonly onDelete: (id: string) => void;
  /** Manage watchlists… (SCR-101, D24). */
  readonly onManage: () => void;
  /**
   * T2 for every write (E08-D07 §6.6, D13): the reason CMP-079 RbacGate gives a session without `workspaces:write` or
   * viewing as. "+", Rename, Duplicate and Delete… stay, disabled with it; Manage watchlists… stays live.
   */
  readonly writeReason?: string;
  /**
   * The host's one notice that shows `writeReason` (E09-D09 §2.2 "one notice, many pointers"; SCR-100's read-only
   * panel): "+" is described by it instead of a copy of its own. The menu's items keep their second line.
   */
  readonly writeReasonId?: string;
  /** The tablist's name. */
  readonly "aria-label": string;
  /** The header row's controls after "+": the panel status and the ⋮ panel menu (E08-D07 §4.1, §6.3). */
  readonly headerEnd?: ReactNode;
  /** The active list's content (the grid and its footer), in the panel its tab controls. */
  readonly children?: ReactNode;
  /** Emits `data-density` so `theme.css` re-points the tab height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

/**
 * How many tabs fit `room` (the strip less "+") beside "More lists" (`more`), the strip's `gap` counted between its
 * parts: all when every tab and the gap before "+" fit (nothing laid out measures 0 and fits), else as many as fit
 * with "More lists" and a gap either side of it, so "More lists" never squeezes; at least one, the active one, which
 * is always shown. No room at all is one.
 */
function fitCount(room: number, widths: readonly number[], more: number, gap: number): number {
  const total = widths.reduce((sum, width) => sum + width, 0);
  if (total + gap <= room) return widths.length;
  let used = more + 2 * gap;
  let count = 0;
  for (const width of widths) {
    if (used + width > room) break;
    used += width;
    count += 1;
  }
  return Math.max(1, count);
}

/**
 * CMP-162 WatchlistGroupTabs (E08-D07 §5): the saved lists as the CMP-042 Tabs pattern over SCR-100's grid, with
 * manual activation. Each tab draws "Majors · 12" and is named "Majors, 12 symbols" ("187 of 200" from 180, D10). One
 * Tab stop; the arrows (wrapping), Home and End move focus; `Enter` or `Space` switches (on the active tab, nothing).
 * `Shift+F10`, the Menu key or a right-click on a tab opens its CMP-041 menu: Rename, Duplicate, Delete…, Manage
 * watchlists…. Tabs that do not fit the header row go into "More lists" (measured, never wrapped; re-measured as
 * the text scales), the active one always shown. "+" creates a list. Without `workspaces:write` or while viewing
 * as, "+", Rename, Duplicate and Delete… are T2 with `writeReason`, "+" described by the host's notice with
 * `writeReasonId`.
 */
export function WatchlistGroupTabs({
  groups,
  counts,
  activeId,
  onSwitch,
  onCreate,
  onRename,
  onDuplicate,
  onDelete,
  onManage,
  writeReason,
  writeReasonId,
  headerEnd,
  children,
  density,
  "aria-label": label,
}: WatchlistGroupTabsProps): JSX.Element {
  const base = useId();
  const tabId = (index: number): string => `${base}-tab-${index}`;
  const panelId = (index: number): string => `${base}-panel-${index}`;
  const strip = useRef<HTMLDivElement>(null);
  const plus = useRef<HTMLSpanElement>(null);
  const ghosts = useRef<HTMLDivElement>(null);
  const tablist = useRef<HTMLDivElement>(null);
  const reason = writeReason?.trim() || undefined;
  const nameOf = (group: WatchlistGroup): string =>
    watchlistCountName(group.name, counts[group.id] ?? 0);

  // The tabs that fit, measured from hidden copies of every tab, so a list in "More lists" is measured too.
  const [fit, setFit] = useState(Number.POSITIVE_INFINITY);
  const measure = useCallback((): void => {
    const box = ghosts.current;
    const row = strip.current;
    if (box === null) return;
    const room =
      (row?.getBoundingClientRect().width ?? 0) -
      (plus.current?.getBoundingClientRect().width ?? 0);
    // The strip's flex gap (`space.inset.xs`) sits between the tabs, "More lists" and "+".
    const gap = row === null ? 0 : parseFloat(getComputedStyle(row).columnGap) || 0;
    const widths = [...box.querySelectorAll<HTMLElement>(".cv-wltabs__ghost-tab")].map(
      (ghost) => ghost.getBoundingClientRect().width,
    );
    const more = box.querySelector(".cv-wltabs__ghost-more")?.getBoundingClientRect().width ?? 0;
    const next = fitCount(room, widths, more, gap);
    setFit((prev) => (prev === next ? prev : next));
  }, []);
  const names = groups.map(nameOf).join("\n");
  useLayoutEffect(measure, [measure, names]);
  useEffect(() => {
    const box = strip.current;
    if (box === null || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    // A text-scale or zoom change at a fixed width resizes the copies and "+", never the strip: watch them too.
    for (const copy of ghosts.current?.children ?? []) observer.observe(copy);
    if (plus.current !== null) observer.observe(plus.current);
    return () => observer.disconnect();
  }, [measure, names]);

  // The first tabs that fit, the active list always among them (in the last place when it would not be).
  const fitting = groups.slice(0, Math.min(fit, groups.length));
  const active = groups.find((group) => group.id === activeId);
  const shown =
    active === undefined || fitting.includes(active)
      ? fitting
      : [...fitting.slice(0, Math.max(0, fitting.length - 1)), active];
  const overflow = groups.filter((group) => !shown.includes(group));

  const roving = useRoving({
    items: shown.map((group) => ({ value: group.id })),
    checked: activeId,
    // `Enter` or `Space` on the list already shown switches nothing (no re-subscription), as a click does.
    onSelect: (id) => {
      if (id !== activeId) onSwitch(id);
    },
    selectOnFocus: false,
    groupRole: "tablist",
    orientation: "horizontal",
  });

  // The tab menu acts on the tab it opened from (focus is on it: a right-click focuses it first).
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuFor, setMenuFor] = useState<string | undefined>(undefined);
  const menuGroup = groups.find((group) => group.id === menuFor);
  const gate = reason === undefined ? {} : { disabledReason: reason };
  const noticeId = writeReasonId?.trim() || undefined;
  const plusGate =
    reason === undefined || noticeId === undefined ? gate : { ...gate, disabledReasonId: noticeId };
  const tabMenu = (group: WatchlistGroup): readonly MenuItem[] => [
    { id: "rename", label: "Rename", onSelect: () => onRename(group.id), ...gate },
    { id: "duplicate", label: "Duplicate", onSelect: () => onDuplicate(group.id), ...gate },
    {
      id: "delete",
      label: "Delete…",
      opensConfirm: true,
      onSelect: () => onDelete(group.id),
      ...gate,
    },
    { id: "manage", label: "Manage watchlists…", onSelect: onManage },
  ];
  const focusedGroup = (): string | undefined => {
    const held = document.activeElement;
    return held instanceof HTMLElement
      ? held.closest<HTMLElement>("[data-group]")?.dataset["group"]
      : undefined;
  };

  const ghostCount = (group: WatchlistGroup): ReactNode => (
    <>
      <span className="cv-wltabs__name">{group.name}</span>
      <span className="cv-wltabs__count"> · {counts[group.id] ?? 0}</span>
    </>
  );

  return (
    <div className="cv-tabs cv-wltabs" data-cmp="CMP-162" data-density={density}>
      <div className="cv-wltabs__bar">
        <div ref={strip} className="cv-wltabs__strip">
          <div ref={tablist} role="tablist" aria-label={label} className="cv-wltabs__list">
            {shown.map((group, index) => {
              const selected = group.id === activeId;
              const item = roving.itemProps(group.id);
              return (
                <div
                  key={group.id}
                  ref={item.ref}
                  id={tabId(index)}
                  role="tab"
                  className="cv-tabs__tab cv-wltabs__tab"
                  tabIndex={item.tabIndex}
                  aria-selected={selected}
                  aria-controls={panelId(index)}
                  aria-label={nameOf(group)}
                  data-selected={selected ? "" : undefined}
                  data-group={group.id}
                  onKeyDown={item.onKeyDown}
                  onFocus={item.onFocus}
                  onBlur={item.onBlur}
                  onClick={(event: MouseEvent<HTMLElement>) => {
                    event.currentTarget.focus();
                    if (!selected) onSwitch(group.id);
                  }}
                >
                  {ghostCount(group)}
                </div>
              );
            })}
          </div>
          {overflow.length === 0 ? null : (
            <Menu
              trigger={
                <Button variant="ghost" size="sm" iconRight="chevron-down">
                  More lists
                </Button>
              }
              items={overflow.map((group) => ({
                id: group.id,
                label: nameOf(group),
                onSelect: () => onSwitch(group.id),
              }))}
            />
          )}
          <span ref={plus} className="cv-wltabs__create">
            <IconButton
              icon="plus"
              label="New watchlist"
              variant="ghost"
              {...plusGate}
              onClick={() => onCreate()}
            />
          </span>
        </div>
        {headerEnd === undefined ? null : <div className="cv-wltabs__end">{headerEnd}</div>}
      </div>
      <Menu
        contextTarget={tablist}
        aria-label={`Actions for ${menuGroup?.name ?? ""}`}
        open={menuOpen}
        onOpenChange={(next) => {
          if (next) setMenuFor(focusedGroup());
          setMenuOpen(next);
        }}
        items={menuOpen && menuGroup !== undefined ? tabMenu(menuGroup) : []}
      />
      {/* Hidden copies of every tab and of "More lists": their widths decide what fits. */}
      <div ref={ghosts} className="cv-wltabs__measure" aria-hidden="true">
        {groups.map((group) => (
          <span key={group.id} className="cv-tabs__tab cv-wltabs__ghost-tab">
            {ghostCount(group)}
          </span>
        ))}
        <span
          className="cv-control cv-button cv-wltabs__ghost-more"
          data-variant="ghost"
          data-size="sm"
        >
          <span className="cv-button__label">More lists</span>
          <span className="cv-button__icon">
            <Icon name="chevron-down" />
          </span>
        </span>
      </div>
      {active === undefined
        ? children
        : shown.map((group, index) => {
            const selected = group.id === activeId;
            return (
              <div
                key={group.id}
                id={panelId(index)}
                role="tabpanel"
                className={cx("cv-wltabs__panel", selected && "cv-wltabs__panel--active")}
                aria-labelledby={tabId(index)}
                hidden={!selected}
              >
                {selected ? children : null}
              </div>
            );
          })}
    </div>
  );
}
