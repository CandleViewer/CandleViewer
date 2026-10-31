import { useId, useLayoutEffect, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { Button } from "./Button.js";
import { Checkbox } from "./Checkbox.js";
import { IconButton } from "./IconButton.js";
import { Menu } from "./Menu.js";
import { useGatedAnnounce } from "./internal/disabledReason.js";

/** One column the picker lists, in the table's order. */
export interface ColumnPickerColumn {
  readonly id: string;
  readonly label: string;
  readonly visible: boolean;
  /**
   * A locked column (SCR-101's Symbol): shown checked and T2 with this reason, shown under its row (2a), never hidden
   * and never moved ("The symbol column is always shown.", E08-D07 §6.7). It is outside the movable range.
   */
  readonly lockedReason?: string;
}

interface ColumnPickerBase {
  readonly columns: readonly ColumnPickerColumn[];
  /** Shows or hides one column. */
  readonly onChange: (id: string, visible: boolean) => void;
  /**
   * T2 for every write (E08-D07 §6.6, CMP-079 RbacGate's sentence, the host's notice): without `workspaces:write`
   * or while viewing as. The list's items and move buttons, or the menu's button, take it.
   */
  readonly writeReason?: string;
  /**
   * The host's one notice that shows `writeReason` (E09-D09 §2.2 "one notice, many pointers"; D07 §5: CMP-056 is
   * "described by the host's notice"): every control `writeReason` gates is described by it, with no copy of its own.
   */
  readonly writeReasonId?: string;
}

/** The checklist where the picker sits in a dialog (SCR-101's Columns tab): show, hide and reorder. */
export interface ColumnPickerListProps extends ColumnPickerBase {
  readonly variant?: "list";
  /** The group's name. */
  readonly label: string;
  /** Moves a column to index `to` of `columns`. */
  readonly onReorder: (id: string, to: number) => void;
  /**
   * The host's polite region says a move; absent, the picker's own does. A refusal is the gated announcement's
   * (`GatedAnnounceProvider`), said once.
   */
  readonly announce?: (text: string) => void;
}

/** A CMP-041 menu of checkable columns behind a button (SCR-100's footer "Columns"): show and hide. */
export interface ColumnPickerMenuProps extends ColumnPickerBase {
  readonly variant: "menu";
  /** The button's label, which names the menu. */
  readonly label: string;
  readonly onReorder?: undefined;
  readonly announce?: undefined;
}

export type ColumnPickerProps = ColumnPickerListProps | ColumnPickerMenuProps;

const reasonOf = (text: string | undefined): string | undefined => text?.trim() || undefined;

/** Which control of a row had focus when it moved: focus goes back to the same one on its new row. */
type Control = "box" | "up" | "down";

/**
 * CMP-056 ColumnPicker (E08-D07 §5, §6.4): watchlist columns (SCR-100, SCR-101), and any table's. The list variant
 * is a named group of CMP-005 boxes, each with "Move {column} up" and "Move {column} down" CMP-002 buttons; `Alt+↑` /
 * `Alt+↓` on a focused box moves it too. A move keeps focus on the control pressed and says the new position once,
 * politely ("Funding % moved to position 4 of 9."). A locked column is checked and T2 with its reason, shown under its
 * row (2a, the box's description; the lock leads its label), outside the movable range, whose ends are T2: "Already
 * first.", "Already last." (2b). With `writeReason` every box and button is T2 with it, described by the host's
 * notice with `writeReasonId`. A refused key says its reason once, through the gated announcement. The menu variant
 * is a CMP-041 menu button of `menuitemcheckbox` items (show and hide only); with `writeReason` the same button is
 * T2 and no key opens the menu: `Enter`, `Space`, `↓` or `↑` re-show the reason once per press. It is one tree
 * either way, so a focused Columns button keeps focus as the reason comes and goes.
 */
export function ColumnPicker(props: ColumnPickerProps): JSX.Element {
  if (props.variant === "menu") return <ColumnMenu {...props} />;
  return <ColumnList {...props} />;
}

function ColumnMenu({
  label,
  columns,
  onChange,
  writeReason,
  writeReasonId,
}: ColumnPickerMenuProps): JSX.Element {
  const reason = reasonOf(writeReason);
  const noticeId = reasonOf(writeReasonId);
  const announceGated = useGatedAnnounce();
  // T2 (G-T2.3; E09-D09 §9.3): one tree whatever `reason` is, so the button is never swapped for another and a
  // focused one keeps focus as the reason comes and goes. ↓ and ↑, the menu button's open keys, change nothing and
  // re-show the reason once per press (a held key's repeats say nothing); CMP-041 runs the trigger's own handler
  // first and skips a key it prevented, so no key opens the menu. Enter and Space press the button, which re-shows
  // the reason itself (CMP-001).
  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    if (reason === undefined || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    if (!event.repeat) announceGated(reason);
  };
  return (
    <span className="cv-colpicker" data-cmp="CMP-056" data-variant="menu">
      <Menu
        trigger={
          <Button
            variant="ghost"
            size="sm"
            iconRight="chevron-down"
            onKeyDown={onTriggerKeyDown}
            {...(reason === undefined
              ? {}
              : {
                  disabledReason: reason,
                  ...(noticeId === undefined ? {} : { disabledReasonId: noticeId }),
                })}
          >
            {label}
          </Button>
        }
        items={columns.map((column) => {
          const locked = reasonOf(column.lockedReason);
          return {
            id: column.id,
            label: column.label,
            kind: "checkbox" as const,
            checked: column.visible,
            onSelect: () => onChange(column.id, !column.visible),
            ...(locked === undefined ? {} : { disabledReason: locked }),
          };
        })}
      />
    </span>
  );
}

function ColumnList({
  label,
  columns,
  onChange,
  onReorder,
  writeReason,
  writeReasonId,
  announce,
}: ColumnPickerListProps): JSX.Element {
  const labelId = useId();
  const captionBase = useId();
  const reason = reasonOf(writeReason);
  const noticeId = reasonOf(writeReasonId);
  const announceGated = useGatedAnnounce();
  const list = useRef<HTMLUListElement>(null);
  // The movable range: every column but the locked ones.
  const movable = columns.filter((column) => reasonOf(column.lockedReason) === undefined);
  const firstMovable = movable[0]?.id;
  const lastMovable = movable[movable.length - 1]?.id;
  // The picker's own polite line, re-keyed per message so the same words are said again.
  const [said, setSaid] = useState<{ readonly n: number; readonly text: string }>({
    n: 0,
    text: "",
  });
  const say = (text: string): void => {
    if (announce !== undefined) announce(text);
    else setSaid((prev) => ({ n: prev.n + 1, text }));
  };
  // A move re-orders the rows: focus goes back to the control pressed, on the moved row.
  const refocus = useRef<{ readonly id: string; readonly control: Control } | null>(null);
  useLayoutEffect(() => {
    const want = refocus.current;
    if (want === null) return;
    refocus.current = null;
    const row = [...(list.current?.querySelectorAll<HTMLElement>("[data-column]") ?? [])].find(
      (item) => item.dataset["column"] === want.id,
    );
    const target =
      want.control === "box"
        ? row?.querySelector<HTMLElement>('input[type="checkbox"]')
        : row?.querySelector<HTMLElement>(`[data-move="${want.control}"]`);
    if (target != null && target !== document.activeElement) target.focus();
  });

  /** The refusal a move meets, if any: the session's, then the range's end (E09-D09 §2.1's order). */
  const moveRefusal = (column: ColumnPickerColumn, direction: "up" | "down"): string | undefined =>
    reason ??
    (direction === "up" && column.id === firstMovable
      ? "Already first."
      : direction === "down" && column.id === lastMovable
        ? "Already last."
        : undefined);

  /** A move, or its refusal said once per press (`repeat`: a held key's repeat, which keeps moving but says nothing). */
  const move = (
    column: ColumnPickerColumn,
    direction: "up" | "down",
    control: Control,
    repeat = false,
  ): void => {
    const refused = moveRefusal(column, direction);
    if (refused !== undefined) {
      if (!repeat) announceGated(refused);
      return;
    }
    const from = columns.indexOf(column);
    const step = direction === "up" ? -1 : 1;
    // The next movable place in that direction (locked columns keep theirs).
    let to = from + step;
    while (columns[to] !== undefined && reasonOf(columns[to]?.lockedReason) !== undefined)
      to += step;
    if (columns[to] === undefined) return;
    refocus.current = { id: column.id, control };
    onReorder(column.id, to);
    say(`${column.label} moved to position ${to + 1} of ${columns.length}.`);
  };

  const onBoxKeyDown =
    (column: ColumnPickerColumn) =>
    (event: KeyboardEvent<HTMLInputElement>): void => {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      // A bound key on a T2 box changes nothing and says why, once per press (E09-D09 §9.3).
      const locked = reasonOf(column.lockedReason);
      if (locked === undefined)
        move(column, event.key === "ArrowUp" ? "up" : "down", "box", event.repeat);
      else if (!event.repeat) announceGated(locked);
    };

  return (
    <div
      className="cv-colpicker"
      data-cmp="CMP-056"
      data-variant="list"
      role="group"
      aria-labelledby={labelId}
    >
      <span id={labelId} className="cv-visually-hidden">
        {label}
      </span>
      <ul ref={list} className="cv-colpicker__list">
        {columns.map((column, index) => {
          const locked = reasonOf(column.lockedReason);
          const boxReason = locked ?? reason;
          const upReason = moveRefusal(column, "up");
          const downReason = moveRefusal(column, "down");
          // Where each reason is shown: a locked row's under it (2a), the session's in the host's notice.
          const captionId = `${captionBase}-${index}`;
          const boxReasonId = locked !== undefined ? captionId : noticeId;
          const pointer = (refusal: string | undefined): { disabledReasonId?: string } =>
            refusal !== undefined && refusal === reason && noticeId !== undefined
              ? { disabledReasonId: noticeId }
              : {};
          return (
            <li key={column.id} className="cv-colpicker__item" data-column={column.id}>
              <Checkbox
                label={column.label}
                checked={column.visible || locked !== undefined}
                {...(boxReason === undefined ? {} : { disabledReason: boxReason })}
                {...(boxReason === undefined || boxReasonId === undefined
                  ? {}
                  : { disabledReasonId: boxReasonId })}
                onChange={(visible) => onChange(column.id, visible)}
                onKeyDown={onBoxKeyDown(column)}
              />
              {locked === undefined ? (
                <span className="cv-colpicker__moves">
                  <IconButton
                    icon="chevron-up"
                    label={`Move ${column.label} up`}
                    variant="ghost"
                    data-move="up"
                    {...(upReason === undefined ? {} : { disabledReason: upReason })}
                    {...pointer(upReason)}
                    onClick={() => move(column, "up", "up")}
                  />
                  <IconButton
                    icon="chevron-down"
                    label={`Move ${column.label} down`}
                    variant="ghost"
                    data-move="down"
                    {...(downReason === undefined ? {} : { disabledReason: downReason })}
                    {...pointer(downReason)}
                    onClick={() => move(column, "down", "down")}
                  />
                </span>
              ) : (
                <span id={captionId} className="cv-colpicker__reason">
                  {locked}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {announce === undefined ? (
        <span role="status" className="cv-visually-hidden">
          {said.text === "" ? null : <span key={said.n}>{said.text}</span>}
        </span>
      ) : null}
    </div>
  );
}
