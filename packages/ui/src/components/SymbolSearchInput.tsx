import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import {
  FuzzyList,
  fuzzyOptionId,
  type FuzzyListColumns,
  type FuzzyListItem,
} from "./FuzzyList.js";
import { ReasonText } from "./internal/disabledReason.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { focusFieldInput, useRefusalAnnounce } from "./internal/fieldParts.js";
import { Tag } from "./Tag.js";

/** The pane a commit changes (E08-D05 D-10): the chip, and E30-D02's ARMED pill when it is armed. */
export interface SymbolSearchTarget {
  /** "Changes Chart 1 · BTCUSDT 1m", or "Opens a new chart" when no pane is bound. */
  readonly label: string;
  /** The pane is armed (CMP-229): the ARMED pill (word and glyph) joins the chip. */
  readonly armed?: boolean;
  /**
   * The chip's id. Its text is the chip's ("Changes Chart 1 · BTCUSDT 1m ARMED"), not E08-D05 §9.1's spoken target
   * line ("Changes Chart 1, BTCUSDT 1 minute."), which the host's dialog writes for its own `aria-describedby`.
   */
  readonly id?: string;
}

export interface SymbolSearchInputProps {
  /** The query as typed: the host normalises it for its ranking, never in the field (`maxlength` 32, `22` `q`). */
  readonly value: string;
  readonly onChange: (value: string) => void;
  /** Enter or a press on an available option: its symbol (the item's id) and the item. */
  readonly onSelect: (symbol: string, item: FuzzyListItem) => void;
  /** The host's ranked rows for `value` (E08-D05 §4, at most 50), re-ranked on every keystroke. */
  readonly items: readonly FuzzyListItem[];
  /** Every match before the host's cap: the count says it. Default `items.length`. */
  readonly total?: number;
  /** A "Recent" group before `items` while the query is empty (E08-D05 V11); a delisted one is shown, never chosen. */
  readonly recentSymbols?: readonly FuzzyListItem[];
  /**
   * USDT linear perpetuals only in v1 (C-1.2 item 3): the one category. Nothing reads it, since there is nothing to
   * choose between: it keeps the catalogued prop (A-D05-6) and refuses, by type, a host that passes another.
   */
  readonly category?: "linear";
  readonly target?: SymbolSearchTarget;
  /**
   * The host's sentence (loading, checking, no match): said instead of the count, at once and whatever the query
   * (E08-D05 §6.2's Loading opens with an empty one), and again only when it changes.
   */
  readonly message?: string;
  /**
   * A new value says `message` again, the same words too (E08-D05 §6.2: `Enter` with no openable option), over a reason
   * the input said for a press on an unavailable option.
   */
  readonly messageKey?: string | number;
  /**
   * No list in memory: CMP-213's skeleton rows. No option is active then, so the arrows and `PageUp` / `PageDown`
   * move nothing and `Enter` is the host's.
   */
  readonly loading?: boolean;
  /** Shown in the list's place when nothing is listed (CMP-026 with E08-D05 §6.2's words). */
  readonly emptyMessage?: ReactNode;
  /** Default 8 (E08-D05 §5); `PageUp` / `PageDown` move by it. */
  readonly visibleRows?: number;
  /** CMP-213's column header above the list (E08-D05 §6.1). */
  readonly columns?: FuzzyListColumns;
  /** The rest after the last keystroke before the count is said. Default 300 (E08-D05 A-D05-6). */
  readonly settleMs?: number;
  /**
   * Runs first on every key outside an IME composition, with the active option: the host's `Shift+Enter`,
   * `Shift+F10`, the Menu key and `Esc`. Its `preventDefault()` skips this input's own handling of that key.
   */
  readonly onKeyDown?: (
    event: KeyboardEvent<HTMLInputElement>,
    active: FuzzyListItem | undefined,
  ) => void;
  /** The active option changed (a key, a press, a re-rank that drops it; not the mount): the host's bar and menu. */
  readonly onActiveChange?: (active: FuzzyListItem | undefined) => void;
  /** A right-click on an option, made active: the host opens its menu at the point (E08-D05 §6.3). */
  readonly onContextMenu?: (
    item: FuzzyListItem,
    at: { readonly x: number; readonly y: number },
  ) => void;
  readonly placeholder?: string;
  readonly disabled?: boolean;
  /** T2 (E08-D07 §6.6): the lock leads the value, the list is not shown, a refused key says the reason once. */
  readonly disabledReason?: string;
  /** Default "Search symbols" (E08-D05 §9.1); inside a CMP-040 FormField its label names the input. */
  readonly "aria-label"?: string;
  /** More of the input's description (the host's key hints, E08-D05 §9.1). */
  readonly "aria-describedby"?: string;
  /** The listbox's name. Default "Symbols". */
  readonly listLabel?: string;
}

const SETTLE_MS = 300;
const QUERY_MAX = 32;
const RECENT = "Recent";
const GATED_KEYS: ReadonlySet<string> = new Set(["ArrowDown", "ArrowUp", "PageDown", "PageUp"]);
const counted = (n: number): string => `${String(n)} ${n === 1 ? "result" : "results"}`;

/** A listed row and the host's item it stands for (a Recent row's id is namespaced, its item untouched). */
interface Entry {
  readonly row: FuzzyListItem;
  readonly item: FuzzyListItem;
}

/**
 * CMP-160 SymbolSearchInput: CMP-048's combobox over CMP-213's list, shown in place (E08-D05 §6.1: the list is
 * part of the surface, so it never closes on a blur and keeps its active option while a host's menu has focus).
 * Focus stays in the input; `↓` / `↑` move without wrapping (`↑` on the first returns to the text), `PageDown` /
 * `PageUp` by the visible rows, `Enter` chooses (an unavailable option says its reason). The host ranks: the list
 * follows each keystroke, and the count is said once the query rests for `settleMs`. `Esc` is the host's.
 */
export function SymbolSearchInput(props: SymbolSearchInputProps): JSX.Element {
  const { value, onChange, items, recentSymbols, target, message, loading = false } = props;
  const { visibleRows = 8, settleMs = SETTLE_MS } = props;
  const control = useFieldControl(props.disabled, props.disabledReason, false, undefined);
  const { reason } = control;
  const unavailable = reason.gated || reason.disabled;
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const query = value.trim();
  const latest = useRef(query);
  const [settled, setSettled] = useState<string | null>(null);
  const [activeKey, setActiveKey] = useState<string | undefined>(undefined);
  // A press on an unavailable option says its reason; the count re-keys the node, so each press is said again.
  const [recall, setRecall] = useState<{ readonly text: string; readonly n: number } | null>(null);
  // A new `messageKey` is the host's own act (a press, a key): its message is said over a reason said earlier.
  const [keyed, setKeyed] = useState(props.messageKey);
  if (keyed !== props.messageKey) {
    setKeyed(props.messageKey);
    setRecall(null);
  }
  // The status region is empty at mount and filled after it, so a message set from the start is said too.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const list = useMemo<Entry[]>(
    () => [
      ...(query === "" ? (recentSymbols ?? []) : []).map((item) => ({
        row: { ...item, id: `recent:${item.id}`, group: RECENT },
        item,
      })),
      ...items.map((item) => ({ row: item, item })),
    ],
    [query, recentSymbols, items],
  );
  const rows = useMemo(() => list.map((entry) => entry.row), [list]);
  // While loading only skeleton rows are drawn: no option is active and the keys move nothing, so
  // `aria-activedescendant` never names a node that is not in the DOM (CR-B2AD-02).
  const index = loading ? -1 : list.findIndex((entry) => entry.row.id === activeKey);
  const active = list[index];
  const activeId = active?.row.id;
  const expanded = !unavailable && (loading || list.length > 0);
  const count = props.total ?? items.length;
  // The host's sentence is said at once; only the count waits for the query to rest.
  const counting = query !== "" && settled === query;
  const said =
    message === undefined ? (counting ? counted(count) : undefined) : mounted ? message : undefined;

  const report = useRef(props.onActiveChange);
  const current = useRef(active?.item);
  // What the settle timer and the report below read: kept after each commit, never written while rendering.
  useLayoutEffect(() => {
    latest.current = query;
    report.current = props.onActiveChange;
    current.current = active?.item;
  });
  const reported = useRef(activeId);
  useEffect(() => {
    if (reported.current === activeId) return;
    reported.current = activeId;
    report.current?.(current.current);
  }, [activeId]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const choose = ({ item }: Entry): void => {
    if (item.disabled !== true) return props.onSelect(item.id, item);
    const why = item.reason?.trim();
    if (why) setRecall((prev) => ({ text: why, n: (prev?.n ?? 0) + 1 }));
  };
  const entryOf = (row: FuzzyListItem): Entry | undefined => list.find((e) => e.row.id === row.id);
  const edit = (text: string): void => {
    onChange(text);
    setActiveKey(undefined);
    setRecall(null);
    setSettled(null);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSettled(latest.current), settleMs);
  };

  const handleKey = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.nativeEvent.isComposing) return;
    const prevented = event.defaultPrevented; // before the host's turn
    props.onKeyDown?.(event, active?.item);
    if (unavailable || event.defaultPrevented !== prevented) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return; // chords are the host's
    const last = loading ? -1 : list.length - 1;
    const page = Math.max(1, Math.floor(visibleRows));
    if (event.key === "Enter") {
      if (active === undefined) return; // with none active, Enter is the host's
      event.preventDefault();
      if (!event.repeat) choose(active);
      return;
    }
    const moves: Readonly<Record<string, number>> = {
      ArrowDown: Math.min(index + 1, last),
      ArrowUp: index - 1, // the first returns to the text
      PageDown: Math.min(index + page, last),
      PageUp: index < 0 ? index : Math.max(index - page, 0), // never back to the text
    };
    const next = moves[event.key];
    if (next === undefined || last < 0) return;
    event.preventDefault();
    setActiveKey(list[next]?.row.id);
    setRecall(null);
  };
  const refusal = useRefusalAnnounce(reason, { onKeyDown: handleKey }, GATED_KEYS);

  return (
    <div className="cv-symbolsearch" data-cmp="CMP-160">
      {target === undefined ? null : (
        <div className="cv-symbolsearch__target" id={target.id}>
          <Tag label={target.label} />
          {target.armed === true ? " " : null}
          {target.armed === true ? (
            <span className="cv-symbolsearch__armed">
              <Icon name="unlock" />
              ARMED
            </span>
          ) : null}
        </div>
      )}
      <div className="cv-symbolsearch__bar">
        {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
        <div
          className="cv-field"
          data-gated={reason.gated ? "" : undefined}
          data-disabled={reason.disabled ? "" : undefined}
          data-lead=""
          onMouseDown={(event) => focusFieldInput(event, inputRef)}
        >
          {reason.gated ? (
            <span className="cv-field__lead cv-field__lock">
              <Icon name="lock" decorative={false} label="Not available" />
            </span>
          ) : null}
          <span className="cv-field__lead cv-field__affix">
            <Icon name="search" />
          </span>
          <input
            ref={inputRef}
            id={control.field?.controlId}
            type="text"
            role="combobox"
            className="cv-field__input"
            value={value}
            placeholder={props.placeholder}
            maxLength={QUERY_MAX}
            autoComplete="off"
            spellCheck={false}
            disabled={reason.disabled}
            readOnly={reason.gated}
            aria-autocomplete="list"
            aria-expanded={expanded}
            aria-controls={expanded ? listId : undefined}
            aria-activedescendant={
              expanded && activeId !== undefined ? fuzzyOptionId(listId, activeId) : undefined
            }
            aria-label={
              props["aria-label"] ?? (control.field === null ? "Search symbols" : undefined)
            }
            aria-describedby={control.describe(props["aria-describedby"])}
            aria-disabled={reason.ariaDisabled}
            onChange={(event) => edit(event.target.value)}
            {...refusal.handlers}
          />
        </div>
        {query === "" || loading || items.length === 0 ? null : (
          <span className="cv-symbolsearch__count" aria-hidden="true">
            {counted(count)}
          </span>
        )}
      </div>
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
      {refusal.status}
      {unavailable ? null : (
        <>
          <FuzzyList
            id={listId}
            items={rows}
            activeId={activeId}
            loading={loading}
            emptyMessage={props.emptyMessage}
            visibleRows={visibleRows}
            {...(props.columns === undefined ? {} : { columns: props.columns })}
            aria-label={props.listLabel ?? "Symbols"}
            onActivate={(row) => {
              const entry = entryOf(row);
              setActiveKey(row.id);
              if (entry !== undefined) choose(entry);
            }}
            {...(props.onContextMenu === undefined
              ? {}
              : {
                  onContextMenu: (
                    row: FuzzyListItem,
                    at: { readonly x: number; readonly y: number },
                  ) => {
                    const entry = entryOf(row);
                    setActiveKey(row.id);
                    if (entry !== undefined) props.onContextMenu?.(entry.item, at);
                  },
                })}
          />
          {/* One polite region: the count once per settled query, or the host's sentence; a reason per press. */}
          <span className="cv-visually-hidden" role="status">
            {recall !== null ? (
              <span key={`why:${String(recall.n)}`}>{recall.text}</span>
            ) : said === undefined ? null : (
              <span
                key={
                  message === undefined
                    ? `said:${query}`
                    : `message:${message}:${String(props.messageKey ?? "")}`
                }
              >
                {said}
              </span>
            )}
          </span>
        </>
      )}
    </div>
  );
}
