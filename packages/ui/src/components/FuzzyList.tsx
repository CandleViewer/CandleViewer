import {
  Fragment,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import type { MatchRange } from "./internal/fuzzy.js";
import { Skeleton } from "./Skeleton.js";
import { Tag } from "./Tag.js";

/** A word in an option's name, drawn as its glyph after the label (E08-D05 §6.1, A-D05-3). */
export type FuzzyListTag = "favourite" | "recent";

/** One option: text and chips only, never a control inside it (E08-D05 A-D05-3; axe `nested-interactive`). */
export interface FuzzyListItem {
  /** Unique in the list: the key and, through `fuzzyOptionId`, the option's id. */
  readonly id: string;
  /** The matched text (a symbol): never truncated. */
  readonly label: string;
  /** Spans of `label`, `[start, end)`, ascending: `<mark>`, semibold primary over regular secondary. */
  readonly matchRanges?: readonly MatchRange[];
  /** Consecutive items with the same group form one `role="group"` named by it, its header one row. */
  readonly group?: string;
  /** A leading registry glyph (decorative). */
  readonly icon?: IconName;
  /** A second text column (base / quote): it truncates, the label never does. */
  readonly hint?: string;
  /**
   * End-aligned numeric cells (24 h, 24 h turnover): "—" where a value is absent. Each one with a word in it joins
   * the option's name as shown, so the name holds the row's visible text (WCAG 2.5.3).
   */
  readonly values?: readonly string[];
  /** A trailing CMP-011 chip (recording, delisted): its words join the option's name. */
  readonly chip?: { readonly label: string; readonly icon?: IconName };
  readonly tags?: readonly FuzzyListTag[];
  /** Reached, never chosen (T2): `aria-disabled`, the lock (unless delisted), described by `reason`. */
  readonly disabled?: boolean;
  /** Why it can't be chosen: its description, in the DOM at mount; the host shows it (E08-D05 §6.4's detail bar). */
  readonly reason?: string;
  /** Delisted by the exchange (E08-D05 §6.4): the label struck in the delisted text. Pair it with `disabled`. */
  readonly delisted?: boolean;
  /** Beside the name (E08-D05 §9.1: the 24 h values in words). */
  readonly description?: string;
}

/** The column header's words, one per cell kind an option draws (E08-D05 §6.1: "Symbol", "Base / quote", "24 h"…). */
export interface FuzzyListColumns {
  readonly label: string;
  readonly hint?: string;
  /** Over the end-aligned `values`, in their order. */
  readonly values?: readonly string[];
  readonly chip?: string;
}

export interface FuzzyListProps {
  /** The listbox's id: the host input's `aria-controls`; an option's id is `fuzzyOptionId(id, item.id)`. */
  readonly id: string;
  readonly items: readonly FuzzyListItem[];
  /** The host's active option (its `aria-activedescendant`): `aria-selected`, the bar, kept in the window. */
  readonly activeId?: string | undefined;
  /** A press on an option, an unavailable one too (the host says its reason). */
  readonly onActivate: (item: FuzzyListItem) => void;
  /** A right-click: the host makes the option active and opens its menu at the point (E08-D05 §6.3). */
  readonly onContextMenu?: (
    item: FuzzyListItem,
    at: { readonly x: number; readonly y: number },
  ) => void;
  /** No list in memory yet: six static skeleton rows in a busy listbox (E08-D05 §6.2). */
  readonly loading?: boolean;
  /** In place of the listbox when nothing is listed and nothing loads: CMP-026 with the host's words. */
  readonly emptyMessage?: ReactNode;
  /** Rows shown before the list scrolls (E08-D05 §5: 16 / 11 in SCR-102, 8 / 6 in SCR-041). Default 8. */
  readonly visibleRows?: number;
  /**
   * A column header above the list, whatever stands in it (rows, skeleton or `emptyMessage`): one `aria-hidden` row of
   * the options' own cells, so a column that drops from the rows drops from it too. The option names carry the words.
   */
  readonly columns?: FuzzyListColumns;
  readonly "aria-label"?: string;
  readonly "aria-labelledby"?: string;
}

const OVERSCAN = 4;
const SKELETON_ROWS = 6;
const GLYPH: Readonly<Record<FuzzyListTag, string>> = { favourite: "★", recent: "↺" };
/** A value with a letter or digit joins the option's name; "—", the mark of an absent one, says nothing. */
const worded = (value: string): boolean => /[\p{L}\p{N}]/u.test(value);

/** The option's DOM id for the host's `aria-activedescendant`. */
export const fuzzyOptionId = (listId: string, itemId: string): string =>
  `${listId}-${encodeURIComponent(itemId)}`;

/** One row of the list: a group's header (no item) or an option, `at` of `of` in its run; one `size.row.height`. */
interface Line {
  readonly row: number;
  readonly run: number;
  readonly group: string | undefined;
  readonly item?: FuzzyListItem;
  readonly at: number;
  readonly of: number;
}

function linesOf(items: readonly FuzzyListItem[]): Line[] {
  const runs: { group: string | undefined; items: FuzzyListItem[] }[] = [];
  for (const item of items) {
    const last = runs[runs.length - 1];
    if (last !== undefined && last.group === item.group) last.items.push(item);
    else runs.push({ group: item.group, items: [item] });
  }
  return runs
    .flatMap(({ group, items: own }, run) => [
      ...(group === undefined ? [] : [{ run, group, at: 0, of: 0 }]),
      ...own.map((item, i) => ({ run, group, item, at: i + 1, of: own.length })),
    ])
    .map((line, row) => ({ ...line, row }));
}

/** The label with its matched spans in `<mark>`: weight and tone, never colour alone, over text nodes only. */
function marked(label: string, ranges: readonly MatchRange[] = []): ReactNode[] {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const [start, end] of ranges) {
    if (start < at || end <= start) continue;
    parts.push(
      label.slice(at, start),
      <mark key={start} className="cv-fuzzylist__match">
        {label.slice(start, end)}
      </mark>,
    );
    at = end;
  }
  parts.push(label.slice(at));
  return parts;
}

const rowsTall = (rows: number): string => `calc(${String(rows)} * var(--size-row-height))`;

/** The rows `[from, to)` not drawn, as one spacer `size.row.height`s tall (none when empty). */
const spacer = (from: number, to: number): JSX.Element[] =>
  to > from
    ? [
        <div
          key={`gap-${String(to)}`}
          aria-hidden="true"
          style={{ blockSize: rowsTall(to - from) }}
        />,
      ]
    : [];

/**
 * CMP-213 FuzzyList: the listbox half of a combobox (E08-D05 §6.1, §9.1). The host keeps DOM focus in its input and
 * drives `activeId`; this list marks that option and keeps it in view. Options are text and chips only. Above twice
 * the visible rows it windows: the visible rows and four each way, between spacers counted in `size.row.height`s,
 * so no row is ever measured (a scroll reads the list's offset and height; a new list with nothing active is put
 * back at its top). The active option is always drawn, so the host's `aria-activedescendant` never dangles. A press
 * never takes focus. An option's name is its label, hint, worded values, chip and tag words, in the order they
 * show, so it holds the row's visible text (WCAG 2.5.3; E08-D05 §9.1's name left the values to the description).
 */
export function FuzzyList({
  id,
  items,
  activeId,
  onActivate,
  onContextMenu,
  loading = false,
  emptyMessage,
  visibleRows = 8,
  columns,
  ...name
}: FuzzyListProps): JSX.Element {
  const rows = Math.max(1, Math.floor(visibleRows));
  const lines = useMemo(() => linesOf(items), [items]);
  const ids = useMemo(() => items.map((item) => item.id).join("\n"), [items]);
  const list = useRef<HTMLDivElement>(null);
  const n = lines.length;
  const windowed = n > 2 * rows;
  const activeLine = activeId === undefined ? -1 : lines.findIndex((l) => l.item?.id === activeId);
  // The window's first row: it follows a new active option once (the rows above it, or it at the bottom); a scroll
  // then moves it freely, and a new list with nothing active starts at the top.
  const follow = (from: number): number =>
    activeLine < 0 ? from : Math.min(Math.max(from, activeLine - rows + 1), activeLine);
  const [view, setView] = useState(() => ({ top: follow(0), active: activeId, ids }));
  if (view.active !== activeId || view.ids !== ids)
    setView({
      top: follow(activeLine < 0 && view.ids !== ids ? 0 : view.top),
      active: activeId,
      ids,
    });
  const top = Math.min(view.top, Math.max(0, n - rows));
  const from = windowed ? Math.max(0, top - OVERSCAN) : 0;
  const to = windowed ? Math.min(n, top + rows + OVERSCAN) : n;
  // A scroll can leave the active option outside the window: it stays drawn, so the host's `aria-activedescendant`
  // and a menu anchored to it never dangle, and the window gives up its overscan row on that side for it.
  const above = activeLine >= 0 && activeLine < from;
  const below = activeLine >= to;
  const drawn = [
    ...(above ? lines.slice(activeLine, activeLine + 1) : []),
    ...lines.slice(above ? from + 1 : from, below ? to - 1 : to),
    ...(below ? lines.slice(activeLine, activeLine + 1) : []),
  ];
  const kept = useRef(false);
  // The offset the list's last scroll event left (0 at mount): the reset below reads no layout to know it.
  const offset = useRef(0);
  useLayoutEffect(() => {
    kept.current = activeLine >= 0;
  });

  // A new list goes back to its top, unless its active option keeps its place: then it scrolls to that option, so
  // the scroll offset stays in step with the window, which has followed it (E08-D05 §9.2: a re-rank keeps it). A list
  // already at its top is left alone, so a keystroke's new list never forces a layout.
  useLayoutEffect(() => {
    if (kept.current || offset.current === 0 || list.current === null) return;
    list.current.scrollTop = 0;
    offset.current = 0;
  }, [ids]);
  useLayoutEffect(() => {
    if (activeId === undefined) return;
    document.getElementById(fuzzyOptionId(id, activeId))?.scrollIntoView?.({ block: "nearest" });
    offset.current = NaN; // it may have scrolled: unknown until its scroll event says
  }, [id, activeId, ids]);

  const head =
    columns === undefined ? null : (
      <div className="cv-fuzzylist__header cv-fuzzylist__columns" aria-hidden="true">
        <span className="cv-fuzzylist__label">{columns.label}</span>
        {columns.hint === undefined ? null : (
          <span className="cv-fuzzylist__hint">{columns.hint}</span>
        )}
        {(columns.values ?? []).map((value, i) => (
          <span key={`value-${String(i)}`} className="cv-fuzzylist__value">
            {value}
          </span>
        ))}
        {columns.chip === undefined ? null : (
          <span className="cv-fuzzylist__chip">{columns.chip}</span>
        )}
      </div>
    );

  if (!loading && n === 0)
    return (
      <div className="cv-fuzzylist" data-cmp="CMP-213">
        {head}
        {emptyMessage}
      </div>
    );

  const option = (line: Line, item: FuzzyListItem): JSX.Element => {
    const optionId = fuzzyOptionId(id, item.id);
    const tags = item.tags ?? [];
    const values = item.values ?? [];
    const reason = item.disabled === true ? item.reason?.trim() || undefined : undefined;
    const describedBy = [
      reason === undefined ? "" : `${optionId}-why`,
      item.description === undefined ? "" : `${optionId}-more`,
    ].filter(Boolean);
    const lead = item.disabled === true && item.delisted !== true ? "lock" : item.icon;
    // The cells in their order, a space between each (a flex row draws none): the row's text is then its words,
    // "BTCUSDT BTC / USDT", never "BTCUSDTBTC / USDT", and the name holds them all (WCAG 2.5.3).
    const cells = [
      lead === undefined ? null : (
        <span key="lead" className="cv-fuzzylist__lead">
          <Icon name={lead} />
        </span>
      ),
      <span key="label" className="cv-fuzzylist__label">
        {marked(item.label, item.matchRanges)}
        {tags.length === 0 ? null : (
          <span className="cv-fuzzylist__tags">{tags.map((tag) => GLYPH[tag]).join(" ")}</span>
        )}
      </span>,
      item.hint === undefined ? null : (
        <span key="hint" className="cv-fuzzylist__hint">
          {item.hint}
        </span>
      ),
      ...values.map((value, i) => (
        <span key={`value-${String(i)}`} className="cv-fuzzylist__value">
          {value}
        </span>
      )),
      item.chip === undefined ? null : (
        <span key="chip" className="cv-fuzzylist__chip">
          <Tag label={item.chip.label} {...(item.chip.icon ? { icon: item.chip.icon } : {})} />
        </span>
      ),
    ].filter((cell) => cell !== null);
    return (
      // A presentational pointer target around the option: the host's input is the keyboard and AT target.
      <div
        key={item.id}
        role="presentation"
        onClick={() => onActivate(item)}
        onContextMenu={
          onContextMenu === undefined
            ? undefined
            : (event) => {
                event.preventDefault();
                onContextMenu(item, { x: event.clientX, y: event.clientY });
              }
        }
      >
        <div
          id={optionId}
          role="option"
          className="cv-fuzzylist__row"
          aria-label={[item.label, item.hint, ...values.filter(worded), item.chip?.label, ...tags]
            .filter(Boolean)
            .join(", ")}
          aria-selected={item.id === activeId ? true : undefined}
          aria-disabled={item.disabled === true ? true : undefined}
          aria-describedby={describedBy.length === 0 ? undefined : describedBy.join(" ")}
          aria-posinset={windowed ? line.at : undefined}
          aria-setsize={windowed ? line.of : undefined}
          data-active={item.id === activeId ? "" : undefined}
          data-delisted={item.delisted === true ? "" : undefined}
        >
          {cells.flatMap((cell, i) => (i === 0 ? [cell] : [" ", cell]))}
          {reason === undefined ? null : (
            <span id={`${optionId}-why`} className="cv-visually-hidden">
              {reason}
            </span>
          )}
          {item.description === undefined ? null : (
            <span id={`${optionId}-more`} className="cv-visually-hidden">
              {item.description}
            </span>
          )}
        </div>
      </div>
    );
  };

  // The drawn rows by run: each run is one container, a `role="group"` named whether or not its header is drawn (or
  // a fragment), so a row keeps its node while it is drawn, wherever the window moves; spacers stand for the rest.
  const runs: { readonly head: Line; readonly own: Line[] }[] = [];
  for (const line of drawn) {
    const last = runs[runs.length - 1];
    if (last?.head.run === line.run) last.own.push(line);
    else runs.push({ head: line, own: [line] });
  }
  const shown: JSX.Element[] = [];
  let next = 0; // the first row neither drawn nor spaced yet
  for (const { head, own } of runs) {
    shown.push(...spacer(next, head.row));
    next = head.row;
    const body: JSX.Element[] = [];
    for (const line of own) {
      body.push(
        ...spacer(next, line.row),
        line.item === undefined ? (
          <div key="header" className="cv-fuzzylist__header" aria-hidden="true">
            {line.group}
          </div>
        ) : (
          option(line, line.item)
        ),
      );
      next = line.row + 1;
    }
    shown.push(
      head.group === undefined ? (
        <Fragment key={`run-${String(head.run)}`}>{body}</Fragment>
      ) : (
        <div key={`run-${String(head.run)}`} role="group" aria-label={head.group}>
          {body}
        </div>
      ),
    );
  }
  shown.push(...spacer(next, n));

  return (
    <div
      className="cv-fuzzylist"
      data-cmp="CMP-213"
      style={{ "--cv-fuzzylist-rows": String(rows) } as CSSProperties}
    >
      {head}
      {/* A pointer surface: a press keeps focus in the host's input, which drives the list. */}
      <div
        ref={list}
        id={id}
        role="listbox"
        tabIndex={-1}
        className="cv-fuzzylist__list"
        aria-label={name["aria-label"]}
        aria-labelledby={name["aria-labelledby"]}
        aria-busy={loading ? true : undefined}
        onMouseDown={(event) => event.preventDefault()}
        onScroll={({ currentTarget: box }) => {
          offset.current = box.scrollTop;
          const row = windowed ? box.scrollHeight / n : 0;
          if (row <= 0) return;
          const at = Math.floor(offset.current / row); // the same row sets no state
          setView((prev) => (prev.top === at ? prev : { ...prev, top: at }));
        }}
      >
        {loading ? (
          <span className="cv-fuzzylist__skeleton">
            <Skeleton shape="row" count={SKELETON_ROWS} surface="overlay" />
          </span>
        ) : (
          shown
        )}
      </div>
    </div>
  );
}
