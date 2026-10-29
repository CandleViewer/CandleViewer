import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import { Dialog } from "./Dialog.js";
import { Kbd } from "./Kbd.js";
import { fuzzyRank, type MatchRange } from "./internal/fuzzy.js";
import { keyShortcuts } from "./internal/keyShortcuts.js";

export interface PaletteCommand {
  readonly id: string;
  readonly label: string;
  /** The group's header, as shown ("Navigate", "Action"): with a query, results group under it. */
  readonly group: string;
  /** The active keymap profile's binding in display form (`["Ctrl", "D"]`): CMP-022, `aria-keyshortcuts`. */
  readonly shortcut?: readonly string[];
  readonly onRun: () => void;
  /** Gated (T2, E09-D09's key sentence): the lock, the label tertiary, this reason its second line; never runs. */
  readonly disabledReason?: string;
  /** The `warning` glyph and the tag; it never runs here: Enter asks the host's confirm (`onRequestConfirm`). */
  readonly destructive?: boolean;
}

/** A section shown for an empty query: the host's data (Recent, Suggested). */
export interface PaletteSection {
  readonly label: string;
  readonly commands: readonly PaletteCommand[];
}

/** One command (Enter) or the group run (`Ctrl+Enter`). */
export type PaletteScope = "one" | "group";

export interface CommandPaletteProps {
  readonly open: boolean;
  /** `false` on `Esc`, the scrim, the close button, and after a command runs. `Ctrl+K` is the host's (#305). */
  readonly onOpenChange: (open: boolean) => void;
  /** Every command the session may see (a T3 command is absent, not gated). Ranked against the query. */
  readonly commands: readonly PaletteCommand[];
  /** What an empty query shows; empty sections are dropped. Absent: every command, grouped. */
  readonly sections?: readonly PaletteSection[];
  /** A destructive command's Enter (or `Ctrl+Enter`): the host opens its CMP-044 confirm. The palette stays open. */
  readonly onRequestConfirm?: (command: PaletteCommand, scope: PaletteScope) => void;
  /** `Ctrl+Enter`: run the active command for every account in its group. Absent: no group run, no footer. */
  readonly onRunGroup?: (command: PaletteCommand) => void;
  /** The query on open (stories, a host restoring one). */
  readonly defaultQuery?: string;
  /** E15's SCR-012 strings. Defaults, for stories only: "Command palette". */
  readonly title?: string;
  /** Default "Search commands". */
  readonly inputLabel?: string;
  /** Default "Commands". */
  readonly listLabel?: string;
  readonly placeholder?: string;
  /** The count sentence, said once per settled query. Default "N results". */
  readonly countText?: (count: number) => string;
  /** Shown and said for a query with no match. Default "No command or symbol matches '…'". */
  readonly noResultsText?: (query: string) => string;
  /** A destructive row's tag, also the end of its name. Default "confirms". */
  readonly confirmsTag?: string;
  /** The footer after the `Ctrl+Enter` caps, with `onRunGroup`. Default "runs for every account in the group". */
  readonly groupRunHint?: string;
  /** The keymap's name table for the spoken form of the caps (CMP-022). */
  readonly kbdNames?: Readonly<Record<string, string>>;
}

/** A query settles this long after the last keystroke (as CMP-048): then its count is said, once. */
const SETTLE_MS = 500;
/** PageUp / PageDown move this many options. */
const PAGE = 10;

interface Row {
  readonly key: string;
  readonly command: PaletteCommand;
  readonly ranges: readonly MatchRange[];
}
interface Group {
  readonly label: string;
  readonly rows: readonly Row[];
}

const reasonOf = (command: PaletteCommand): string | undefined =>
  command.disabledReason?.trim() || undefined;
const defaultCount = (n: number): string => `${String(n)} ${n === 1 ? "result" : "results"}`;
const defaultNoResults = (query: string): string => `No command or symbol matches '${query}'`;

/** Groups in the order their first command appears; empty groups are never made. */
function grouped(rows: readonly Row[], order: readonly PaletteCommand[]): Group[] {
  const rank = new Map<string, number>();
  order.forEach((c) => {
    if (!rank.has(c.group)) rank.set(c.group, rank.size);
  });
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const list = groups.get(row.command.group) ?? [];
    list.push(row);
    groups.set(row.command.group, list);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (rank.get(a) ?? 0) - (rank.get(b) ?? 0))
    .map(([label, list]) => ({ label, rows: list }));
}

function groupsFor(
  query: string,
  commands: readonly PaletteCommand[],
  sections: readonly PaletteSection[] | undefined,
): Group[] {
  const row =
    (prefix: string) =>
    (command: PaletteCommand, ranges: readonly MatchRange[] = []): Row => ({
      key: `${prefix}:${command.id}`,
      command,
      ranges,
    });
  if (query !== "") {
    const ranked = fuzzyRank(commands, query, (c) => c.label);
    return grouped(
      ranked.map((r) => row("q")(r.item, r.match.ranges)),
      commands,
    );
  }
  if (sections === undefined)
    return grouped(
      commands.map((c) => row("all")(c)),
      commands,
    );
  return sections
    .map((s, i) => ({ label: s.label, rows: s.commands.map((c) => row(String(i))(c)) }))
    .filter((g) => g.rows.length > 0);
}

/** The matched characters in `<mark>` with weight: never colour alone. */
function marked(label: string, ranges: readonly MatchRange[]): ReactNode {
  if (ranges.length === 0) return label;
  const parts: ReactNode[] = [];
  let at = 0;
  for (const [start, end] of ranges) {
    if (start > at) parts.push(label.slice(at, start));
    parts.push(
      <mark key={start} className="cv-palette__match">
        {label.slice(start, end)}
      </mark>,
    );
    at = end;
  }
  if (at < label.length) parts.push(label.slice(at));
  return parts;
}

/**
 * CMP-059: the command palette, an APG combobox with a grouped listbox inside a CMP-043 modal Dialog, 640 px wide.
 * Focus stays in the input; `aria-activedescendant` names the active option. ↓ / ↑ wrap, Home / End go to the
 * ends, PageUp / PageDown move ten. Enter runs the active command and closes; a destructive one asks the host's
 * confirm instead; a gated one (T2) runs nothing and says its reason once per press. `Ctrl+Enter` is the group run
 * when the host gives `onRunGroup`. `Esc` closes and focus returns to the opener (the Dialog's). The count is said
 * once per settled query through one polite region. Every string is a prop; the `Ctrl+K` binding is the host's.
 */
export function CommandPalette({
  open,
  onOpenChange,
  commands,
  sections,
  onRequestConfirm,
  onRunGroup,
  defaultQuery = "",
  title = "Command palette",
  inputLabel = "Search commands",
  listLabel = "Commands",
  placeholder,
  countText = defaultCount,
  noResultsText = defaultNoResults,
  confirmsTag = "confirms",
  groupRunHint = "runs for every account in the group",
  kbdNames,
}: CommandPaletteProps): JSX.Element | null {
  const id = useId();
  const listId = `${id}-list`;
  const input = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // The last pointer position over the list: a mousemove at the same spot is the list scrolling under a still
  // pointer (a key move), not a hover, so it never takes the active option from the keyboard.
  const pointer = useRef<{ readonly x: number; readonly y: number } | null>(null);
  const [text, setText] = useState(defaultQuery);
  const [settled, setSettled] = useState(defaultQuery.trim());
  const [active, setActive] = useState({ index: 0, scroll: false });
  // A press on a gated row says its reason; the count re-keys the node, so each press is said again.
  const [recall, setRecall] = useState<{ readonly text: string; readonly n: number } | null>(null);
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    // Each opening starts afresh: the host's query, the first option, nothing said yet. A query still settling
    // when the palette closed must not land on the reopened one (its count would never be said).
    setWasOpen(open);
    clearTimeout(timer.current);
    timer.current = undefined;
    pointer.current = null;
    if (open) {
      setText(defaultQuery);
      setSettled(defaultQuery.trim());
      setActive({ index: 0, scroll: false });
      setRecall(null);
    }
  }

  const query = text.trim();
  const groups = useMemo(() => groupsFor(query, commands, sections), [query, commands, sections]);
  const rows = useMemo(() => groups.flatMap((g) => g.rows), [groups]);
  const count = rows.length;
  const current = count === 0 ? -1 : Math.min(active.index, count - 1);
  const optionId = (index: number): string => `${id}-opt-${String(index)}`;
  const said =
    query === "" || settled !== query
      ? undefined
      : count === 0
        ? noResultsText(query)
        : countText(count);

  const edit = (next: string): void => {
    setText(next);
    setActive({ index: 0, scroll: false });
    setRecall(null);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSettled(next.trim()), SETTLE_MS);
  };
  const move = (index: number): void => {
    setActive({ index, scroll: true });
    setRecall(null);
  };
  const activate = (index: number, scope: PaletteScope): void => {
    const command = rows[index]?.command;
    if (command === undefined) return;
    if (scope === "group" && onRunGroup === undefined) return;
    const why = reasonOf(command);
    if (why !== undefined) {
      setRecall((prev) => ({ text: why, n: (prev?.n ?? 0) + 1 }));
      return;
    }
    if (command.destructive === true) {
      onRequestConfirm?.(command, scope);
      return;
    }
    onOpenChange(false);
    if (scope === "group") onRunGroup?.(command);
    else command.onRun();
  };

  const handleKey = (event: KeyboardEvent<HTMLInputElement>): void => {
    // An IME composing (Safari reports its keys as keyCode 229 without isComposing) owns the keys.
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
    const { key } = event;
    const plain = !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
    if (key === "Enter") {
      if (current < 0 || event.altKey || event.shiftKey) return;
      event.preventDefault();
      // A held key fires once: a reason is re-shown once per press, a command runs once.
      if (!event.repeat) activate(current, event.ctrlKey || event.metaKey ? "group" : "one");
      return;
    }
    if (!plain || count === 0) return;
    const last = count - 1;
    let next: number | undefined;
    if (key === "ArrowDown") next = current >= last ? 0 : current + 1;
    else if (key === "ArrowUp") next = current <= 0 ? last : current - 1;
    else if (key === "Home") next = 0;
    else if (key === "End") next = last;
    else if (key === "PageDown") next = Math.min(current + PAGE, last);
    else if (key === "PageUp") next = Math.max(current - PAGE, 0);
    if (next === undefined) return;
    event.preventDefault();
    move(next);
  };

  // A key move scrolls the active row into view; a hover or a new query never scrolls the list.
  useEffect(() => {
    if (open && current >= 0 && active.scroll)
      document
        .getElementById(`${id}-opt-${String(current)}`)
        ?.closest(".cv-palette__row")
        ?.scrollIntoView({ block: "nearest" });
  }, [open, current, active, id]);
  useEffect(() => () => clearTimeout(timer.current), []);

  // Each group's first option index, so ids follow the reading order.
  const starts = groups.map((_, g) =>
    groups.slice(0, g).reduce((sum, prev) => sum + prev.rows.length, 0),
  );
  const names = kbdNames === undefined ? {} : { names: kbdNames };
  const footer =
    onRunGroup === undefined ? undefined : (
      <p className="cv-palette__footer">
        <Kbd keys={["Ctrl", "Enter"]} {...names} /> {groupRunHint}
      </p>
    );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => onOpenChange(next)}
      title={title}
      className="cv-palette"
      initialFocusRef={input}
      footer={footer}
    >
      <div className="cv-palette__root" data-cmp="CMP-059">
        <div className="cv-field cv-palette__well" data-lead="">
          <span className="cv-field__lead cv-field__affix">
            <Icon name="search" />
          </span>
          <input
            ref={input}
            type="text"
            role="combobox"
            className="cv-field__input"
            value={text}
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
            aria-label={inputLabel}
            aria-autocomplete="list"
            aria-expanded={count > 0}
            aria-controls={count > 0 ? listId : undefined}
            aria-activedescendant={current >= 0 ? optionId(current) : undefined}
            onChange={(event) => edit(event.target.value)}
            onKeyDown={handleKey}
          />
        </div>
        {count === 0 ? (
          query === "" ? null : (
            <p className="cv-palette__empty">{noResultsText(query)}</p>
          )
        ) : (
          // A pointer surface: a press keeps focus in the input, which drives the list.
          <div
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label={listLabel}
            className="cv-palette__list"
            onMouseDown={(event) => event.preventDefault()}
          >
            {groups.map((group, g) => {
              const headerId = `${id}-group-${String(g)}`;
              return (
                <div key={String(g)} role="group" aria-labelledby={headerId}>
                  <div id={headerId} className="cv-palette__header">
                    {group.label}
                  </div>
                  {group.rows.map((row, r) => {
                    const at = (starts[g] ?? 0) + r;
                    const { command } = row;
                    const why = reasonOf(command);
                    const whyId = `${optionId(at)}-why`;
                    const destructive = command.destructive === true;
                    return (
                      <div
                        key={row.key}
                        role="presentation"
                        className="cv-palette__row"
                        data-kind={
                          why !== undefined ? "locked" : destructive ? "destructive" : undefined
                        }
                        data-active={at === current ? "" : undefined}
                        onMouseMove={(event) => {
                          const { clientX: x, clientY: y } = event;
                          const last = pointer.current;
                          if (last !== null && last.x === x && last.y === y) return;
                          pointer.current = { x, y };
                          if (at !== current) setActive({ index: at, scroll: false });
                        }}
                        onClick={() => {
                          setActive({ index: at, scroll: false });
                          activate(at, "one");
                        }}
                      >
                        <span className="cv-palette__lead">
                          {why !== undefined ? (
                            <Icon name="lock" />
                          ) : destructive ? (
                            <Icon name="warning" />
                          ) : null}
                        </span>
                        <div className="cv-palette__body">
                          {/* The option is the label; its tag sits beside it, and ends its name. */}
                          <div className="cv-palette__line">
                            <span
                              id={optionId(at)}
                              role="option"
                              className="cv-palette__label"
                              aria-label={
                                destructive ? `${command.label}, ${confirmsTag}` : command.label
                              }
                              aria-selected={at === current ? true : undefined}
                              aria-disabled={why === undefined ? undefined : true}
                              aria-describedby={why === undefined ? undefined : whyId}
                              aria-keyshortcuts={keyShortcuts(command.shortcut)}
                            >
                              {marked(command.label, row.ranges)}
                            </span>
                            {destructive ? (
                              <span className="cv-palette__tag" aria-hidden="true">
                                {confirmsTag}
                              </span>
                            ) : null}
                          </div>
                          {why === undefined ? null : (
                            <div id={whyId} className="cv-palette__reason" aria-hidden="true">
                              {why}
                            </div>
                          )}
                        </div>
                        {command.shortcut === undefined ? null : (
                          <Kbd
                            keys={command.shortcut}
                            {...names}
                            aria-hidden="true"
                            className="cv-palette__kbd"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
        {/* One polite region: the count once per settled query; a re-shown reason added beside it. */}
        <span className="cv-visually-hidden" role="status">
          {said === undefined ? null : <span key={`count:${settled}`}>{said}</span>}
          {recall === null ? null : <span key={`why:${String(recall.n)}`}>{recall.text}</span>}
        </span>
      </div>
    </Dialog>
  );
}
