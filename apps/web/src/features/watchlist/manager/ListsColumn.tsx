/**
 * SCR-101's Lists column (E08-D07 §4.3 Lists, §6.5; board 10): the caller's lists as a listbox, options named "Majors,
 * 12 symbols" (their visible words, "Majors 12", kept apart so the name holds them), one Tab stop on the selected one.
 * Selection follows focus (`↑`/`↓`, `Home`/`End`, `PageUp`/`PageDown` by ten); `Enter` and `Space` are inert (their
 * default prevented: `Space` never scrolls the dialog); `F2` renames in place and `Del` opens Delete… (both T2 without
 * `workspaces:write`: nothing changes and the reason is said once). Only the selected option draws the selection bar
 * (a border, which forced colours keep; the others draw none). The name field is drawn over its option, outside the
 * listbox (an option holds no control), with its key hint under it: `Enter` commits, `Esc` cancels, leaving it commits
 * a valid name; a refused name shows under it (`aria-invalid`) and keeps focus there. The option grows to the field's
 * height, so the field's error and hint push the next lists down rather than cover them. A commit is sent once (the
 * field's blur after `Enter` sends nothing more). "+ New watchlist" follows the list. No list: no listbox (it would hold
 * no option), the button alone.
 */
import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
  type KeyboardEvent,
} from "react";
import { Button, TextInput, useFocusRing, watchlistCountName } from "@candleviewer/ui";
import { MANAGER_COPY } from "./copy";
import type { ManagerItem } from "./managerStore";

const COLUMN: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-2)",
  minInlineSize: "12rem",
  flex: "0 1 15rem",
};
const LABEL: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
const BOX: CSSProperties = { position: "relative" };
const LISTBOX: CSSProperties = { margin: 0, padding: 0, listStyle: "none" };
/** The selection bar's width: an unselected option pads by it instead, so no text moves and no border is drawn. */
const BAR = "2px";
const OPTION: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "var(--space-2)",
  minBlockSize: "var(--size-row-height)",
  alignItems: "center",
  paddingInlineStart: `calc(var(--space-2) + ${BAR})`,
  paddingInlineEnd: "var(--space-2)",
  cursor: "default",
};
const SELECTED: CSSProperties = {
  ...OPTION,
  background: "var(--color-surface-selected)",
  paddingInlineStart: "var(--space-2)",
  borderInlineStart: `${BAR} solid var(--color-border-selected)`,
};
/** The lists `PageUp` and `PageDown` move. */
const PAGE = 10;
const COUNT: CSSProperties = { color: "var(--color-text-secondary)" };
const FIELD: CSSProperties = {
  position: "absolute",
  insetInline: 0,
  background: "var(--color-surface-overlay)",
};
const HINT: CSSProperties = {
  margin: 0,
  paddingBlockStart: "var(--space-1)",
  color: "var(--color-text-secondary)",
};

export interface ListsColumnProps {
  readonly items: readonly ManagerItem[];
  readonly selected: string | null;
  readonly renaming: string | null;
  /** The server's refusal of the name being edited, as words. */
  readonly nameError: string | undefined;
  /** T2 for every write; `reasonId` is the node that shows it (the notice, or the no-list sentence). */
  readonly writeReason: string | undefined;
  readonly reasonId: string | undefined;
  /** Each option's DOM id, so the dialog can move focus to one. */
  readonly optionId: (key: string) => string;
  readonly newListId: string;
  readonly onSelect: (key: string) => void;
  readonly onRename: (key: string) => void;
  readonly onDelete: (key: string) => void;
  readonly onNew: () => void;
  /** The name's words of refusal, or `undefined` once it is applied. */
  readonly onCommit: (key: string, name: string) => string | undefined;
  readonly onCancel: (key: string) => void;
  /** Says a refused key's reason once (the gated announcement). */
  readonly refuse: (reason: string) => void;
}

export function ListsColumn(props: ListsColumnProps): JSX.Element {
  const { items, selected, renaming, writeReason, optionId } = props;
  const labelId = useId();
  const ring = useFocusRing({ inset: true });
  const box = useRef<HTMLDivElement>(null);
  const focusOption = (key: string | undefined): void => {
    if (key !== undefined) document.getElementById(optionId(key))?.focus();
  };
  const stop = items.some((i) => i.key === selected) ? selected : (items[0]?.key ?? null);

  // The name field sits over its option, which grows to the field's height (its error and hint in the flow).
  const [top, setTop] = useState(0);
  const [fieldHeight, setFieldHeight] = useState(0);
  useLayoutEffect(() => {
    if (renaming === null) return;
    const options = box.current?.querySelectorAll<HTMLElement>("[data-key]") ?? [];
    const option = [...options].find((node) => node.dataset["key"] === renaming);
    setTop(option?.offsetTop ?? 0);
  }, [renaming]);

  const onKeyDown =
    (item: ManagerItem, index: number) =>
    (event: KeyboardEvent<HTMLLIElement>): void => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const step =
        event.key === "ArrowDown"
          ? 1
          : event.key === "ArrowUp"
            ? -1
            : event.key === "PageDown"
              ? PAGE
              : event.key === "PageUp"
                ? -PAGE
                : event.key === "Home"
                  ? -items.length
                  : event.key === "End"
                    ? items.length
                    : 0;
      const to =
        step === 0 ? undefined : items[Math.min(Math.max(index + step, 0), items.length - 1)];
      if (to !== undefined) {
        event.preventDefault();
        props.onSelect(to.key);
        focusOption(to.key);
        return;
      }
      // Enter and Space are inert on a list (the selection already follows focus): Space never scrolls the dialog.
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        return;
      }
      if (event.key !== "F2" && event.key !== "Delete") return;
      event.preventDefault();
      if (event.repeat || item.pending) return;
      if (writeReason !== undefined) props.refuse(writeReason);
      else if (event.key === "F2") props.onRename(item.key);
      else props.onDelete(item.key);
    };

  const renamed = items.find((i) => i.key === renaming);
  const gate =
    writeReason === undefined
      ? {}
      : {
          disabledReason: writeReason,
          ...(props.reasonId === undefined ? {} : { disabledReasonId: props.reasonId }),
        };
  return (
    <div style={COLUMN}>
      <p id={labelId} style={LABEL}>
        {MANAGER_COPY.lists}
      </p>
      <div ref={box} style={BOX}>
        {items.length === 0 ? null : (
          <ul role="listbox" aria-labelledby={labelId} style={LISTBOX}>
            {items.map((item, index) => {
              const on = item.key === selected;
              const style = on ? SELECTED : OPTION;
              return (
                <li
                  key={item.uiKey}
                  id={optionId(item.key)}
                  role="option"
                  aria-selected={on}
                  aria-label={watchlistCountName(item.name, item.count)}
                  data-key={item.key}
                  className={ring.className}
                  tabIndex={item.key === stop ? 0 : -1}
                  style={
                    item.key === renaming && fieldHeight > 0
                      ? {
                          ...style,
                          minBlockSize: `max(var(--size-row-height), ${String(fieldHeight)}px)`,
                        }
                      : style
                  }
                  onClick={(event) => {
                    event.currentTarget.focus();
                    props.onSelect(item.key);
                  }}
                  onKeyDown={onKeyDown(item, index)}
                >
                  {/* Words apart, so the name ("Majors, 12 symbols") holds the text ("Majors 12"). */}
                  <span>{item.name}</span> <span style={COUNT}>{item.count}</span>
                </li>
              );
            })}
          </ul>
        )}
        {renamed === undefined ? null : (
          <NameField
            key={renamed.key}
            initial={renamed.name}
            top={top}
            onHeight={setFieldHeight}
            problem={props.nameError}
            onCommit={(name, moveFocus) => {
              const refused = props.onCommit(renamed.key, name);
              if (refused === undefined && moveFocus) focusOption(renamed.key);
              return refused;
            }}
            onCancel={(moveFocus) => {
              props.onCancel(renamed.key);
              if (moveFocus) focusOption(renamed.key);
            }}
          />
        )}
      </div>
      <span>
        <Button
          id={props.newListId}
          iconLeft="plus"
          variant="ghost"
          size="sm"
          {...gate}
          onClick={props.onNew}
        >
          {MANAGER_COPY.newList}
        </Button>
      </span>
    </div>
  );
}

function NameField(props: {
  readonly initial: string;
  readonly top: number;
  readonly problem: string | undefined;
  /** The field's height as drawn (its error and hint included), for its option to make room. */
  readonly onHeight: (px: number) => void;
  /** The name's words of refusal, or `undefined` once applied; `moveFocus` after a key, not a blur. */
  readonly onCommit: (name: string, moveFocus: boolean) => string | undefined;
  readonly onCancel: (moveFocus: boolean) => void;
}): JSX.Element {
  const [value, setValue] = useState(props.initial);
  const [error, setError] = useState(props.problem);
  const box = useRef<HTMLDivElement>(null);
  const hintId = useId();
  /** Committed or cancelled: a blur after it changes nothing. */
  const settled = useRef(false);
  useLayoutEffect(() => {
    const input = box.current?.querySelector("input");
    input?.focus();
    input?.select();
  }, []);
  const { onHeight } = props;
  useLayoutEffect(() => {
    const node = box.current;
    if (node === null) return undefined;
    const measure = (): void => onHeight(node.offsetHeight);
    measure();
    if (typeof ResizeObserver !== "function") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => {
      observer.disconnect();
      onHeight(0);
    };
  }, [onHeight, error]);
  return (
    <div ref={box} style={{ ...FIELD, top: props.top }} data-name-field="">
      <TextInput
        aria-label={MANAGER_COPY.nameField}
        aria-describedby={hintId}
        value={value}
        invalid={error !== undefined}
        {...(error === undefined ? {} : { errorMessage: error })}
        onChange={(event) => {
          setValue(event.currentTarget.value);
          setError(undefined);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            // Settled before the commit moves focus to the option: the field's blur then sends nothing more.
            settled.current = true;
            const refused = props.onCommit(value, true);
            if (refused !== undefined) {
              settled.current = false;
              setError(refused);
            }
          } else if (event.key === "Escape") {
            // Esc cancels the rename first; the dialog closes on the next one (E08-D07 §6.5).
            event.preventDefault();
            settled.current = true;
            props.onCancel(true);
          }
        }}
        onBlur={(event) => {
          const next = event.relatedTarget;
          if (settled.current || (next instanceof Node && box.current?.contains(next) === true))
            return;
          settled.current = true;
          // Leaving the field: a valid name is kept, any other is dropped.
          if (props.onCommit(value, false) !== undefined) props.onCancel(false);
        }}
      />
      <p id={hintId} style={HINT}>
        {MANAGER_COPY.nameHint}
      </p>
    </div>
  );
}
