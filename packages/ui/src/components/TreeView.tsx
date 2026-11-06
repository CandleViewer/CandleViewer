import {
  Fragment,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import { TextInput } from "./TextInput.js";

/** One node of the tree (`15` CMP-240 Props, E36-D05 §C A-6): an id, its visible label and its children. */
export interface TreeNode {
  readonly id: string;
  /** The item's name; SCR-088's reads "conditions › children › 2 › op: gte". */
  readonly label: string;
  /** A node with at least one child is a parent: it carries `aria-expanded` and its disclosure. */
  readonly children?: readonly TreeNode[];
}

/** What the per-item action slot is told about its item. */
export interface TreeItemActionsContext {
  /**
   * The focused item's actions take 0 (Tab reaches them after the item, then leaves the tree); every other item's
   * take -1, so the tree stays one roving stop (`05` §3.4 item 2). Pass it to each CMP-002 in the slot.
   */
  readonly tabIndex: 0 | -1;
}

/** The tree's accessible name: SCR-088 names it "IR tree"; one of the two, never both. */
type TreeViewName =
  | { readonly "aria-label": string; readonly "aria-labelledby"?: never }
  | { readonly "aria-labelledby": string; readonly "aria-label"?: never };

export type TreeViewProps = TreeViewName & {
  readonly nodes: readonly TreeNode[];
  /** The ids of the expanded parents; the host owns it. */
  readonly expanded: readonly string[];
  /** A parent asks to open (`true`) or close (`false`): `→` / `←`, `*`, or a press on its disclosure. */
  readonly onToggle: (id: string, expanded: boolean) => void;
  /** The ids of the selected items; the host owns it. Single-select holds at most one. */
  readonly selected: readonly string[];
  /** The selection the host should hold next. */
  readonly onSelect: (ids: readonly string[]) => void;
  /** The per-item CMP-002 slot (SCR-088's Copy path; SCR-036's eye / lock / menu). */
  readonly itemActions: (node: TreeNode, context: TreeItemActionsContext) => ReactNode;
  /**
   * SCR-036's multi-select (E13-D02 §6.3 D22, a declared hybrid of APG's two models): arrows move focus only;
   * `Ctrl+Space` / `Ctrl+click` toggle, `Shift+↑/↓` extend from the anchor, `Shift+Space` / `Shift+click` select a
   * range, `Ctrl+A` selects the focused item's group, `Esc` clears a selection. Without it, selection follows focus.
   */
  readonly multiSelect?: boolean;
  /** SCR-036's inline rename (`F2` or a double-click; `Enter` saves, `Esc` cancels). Absent: no rename. */
  readonly onRename?: (id: string, label: string) => void;
  /**
   * SCR-036's reorder within the item's group: `index` is the item's new place among its siblings. A drag handle and
   * its keyboard twin `Alt+↑/↓` appear only with it.
   */
  readonly onMove?: (id: string, index: number) => void;
};

/** A visible item, in reading order. */
interface Row {
  readonly node: TreeNode;
  readonly level: number;
  readonly parentId: string | null;
  readonly index: number;
  readonly siblings: readonly TreeNode[];
}

/** APG type-ahead: characters typed within this window join one search string. */
const TYPEAHEAD_MS = 500;

const isParent = (node: TreeNode): boolean => (node.children?.length ?? 0) > 0;

function visibleRows(nodes: readonly TreeNode[], open: ReadonlySet<string>): Row[] {
  const rows: Row[] = [];
  const walk = (list: readonly TreeNode[], level: number, parentId: string | null): void => {
    list.forEach((node, index) => {
      rows.push({ node, level, parentId, index, siblings: list });
      if (isParent(node) && open.has(node.id)) walk(node.children ?? [], level + 1, node.id);
    });
  };
  walk(nodes, 1, null);
  return rows;
}

function parentsOf(nodes: readonly TreeNode[]): Map<string, string | null> {
  const parents = new Map<string, string | null>();
  const walk = (list: readonly TreeNode[], parentId: string | null): void => {
    for (const node of list) {
      parents.set(node.id, parentId);
      walk(node.children ?? [], node.id);
    }
  };
  walk(nodes, null);
  return parents;
}

/**
 * CMP-240 TreeView (E13-D02 §10 G-1; `15` CMP-240, E36-D05 §C A-6..A-10, A-18): the WAI-ARIA APG tree. `role="tree"`
 * holds `treeitem`s and `group`s with `aria-level`, `aria-setsize`, `aria-posinset`, `aria-expanded` on parents and
 * `aria-selected` on every item; one roving stop. `↑` / `↓` move, `←` / `→` close / open or move to the parent /
 * first child, `Home` / `End`, `*` opens the focused item's siblings, letters type ahead. Two variants: the read-only
 * tree (SCR-088: no `onRename`, no `onMove`) and the editable object tree (SCR-036: `multiSelect`, `onRename`,
 * `onMove`). An empty `nodes` draws nothing: the host's empty state replaces the body (E13-D02 §6.4 D23).
 */
export function TreeView({
  nodes,
  expanded,
  onToggle,
  selected,
  onSelect,
  itemActions,
  multiSelect = false,
  onRename,
  onMove,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: TreeViewProps): JSX.Element | null {
  const open = useMemo(() => new Set(expanded), [expanded]);
  const chosen = useMemo(() => new Set(selected), [selected]);
  const rows = useMemo(() => visibleRows(nodes, open), [nodes, open]);
  const position = useMemo(() => new Map(rows.map((row, i) => [row.node.id, i])), [rows]);
  const parents = useMemo(() => parentsOf(nodes), [nodes]);
  const baseId = useId();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const items = useRef(new Map<string, HTMLLIElement>());
  const anchor = useRef<string | null>(null);
  const typed = useRef({ text: "", at: Number.NEGATIVE_INFINITY });
  const dragged = useRef<string | null>(null);
  /** Set when the item must take focus back after the host re-renders (a move, the end of a rename). */
  const refocus = useRef(false);
  const [, bump] = useState(0);

  // The focused item: the last one focused while it is visible, else its nearest visible ancestor (a parent closed
  // over it), else the first selected item, else the first item.
  let active = activeId;
  while (active !== null && !position.has(active)) active = parents.get(active) ?? null;
  active ??= rows.find((row) => chosen.has(row.node.id))?.node.id ?? rows[0]?.node.id ?? null;

  useEffect(() => {
    if (!refocus.current || active === null) return;
    refocus.current = false;
    items.current.get(active)?.focus();
  });

  useEffect(() => {
    if (editing === null) return;
    const field = items.current
      .get(editing)
      ?.querySelector<HTMLInputElement>(".cv-tree__row input");
    field?.focus();
    field?.select();
  }, [editing]);

  const focusItem = (id: string): void => {
    setActiveId(id);
    items.current.get(id)?.focus();
  };
  const selectOnly = (id: string): void => {
    anchor.current = id;
    if (selected.length !== 1 || selected[0] !== id) onSelect([id]);
  };
  const toggle = (id: string): void => {
    anchor.current = id;
    onSelect(chosen.has(id) ? selected.filter((s) => s !== id) : [...selected, id]);
  };
  const selectRange = (to: string): void => {
    const from = anchor.current !== null && position.has(anchor.current) ? anchor.current : active;
    const a = position.get(from ?? to) ?? 0;
    const b = position.get(to) ?? a;
    anchor.current = from ?? to;
    onSelect(rows.slice(Math.min(a, b), Math.max(a, b) + 1).map((row) => row.node.id));
  };
  /** Keyboard focus moves; in single-select the selection follows it, in multi-select only `Shift` extends it. */
  const go = (row: Row | undefined, extend = false): void => {
    if (row === undefined) return;
    focusItem(row.node.id);
    if (!multiSelect) selectOnly(row.node.id);
    else if (extend) selectRange(row.node.id);
  };
  const move = (row: Row, delta: -1 | 1): void => {
    const index = row.index + delta;
    if (onMove === undefined || index < 0 || index >= row.siblings.length) return;
    refocus.current = true;
    // Guarantees a render (and so one effect pass that consumes the flag) even when the host ignores the move.
    bump((n) => n + 1);
    onMove(row.node.id, index);
  };
  const finishRename = (node: TreeNode, value: string | null, keepFocus: boolean): void => {
    setEditing(null);
    refocus.current = keepFocus;
    const label = value?.trim() ?? "";
    if (onRename !== undefined && label !== "" && label !== node.label) onRename(node.id, label);
  };
  const typeAhead = (key: string, from: number): void => {
    const now = Date.now();
    const text = now - typed.current.at > TYPEAHEAD_MS ? key : typed.current.text + key;
    typed.current = { text, at: now };
    // One character repeated cycles through the items it starts (APG); a longer string may match the focused one.
    const search = /^(.)\1+$/u.test(text) ? key : text;
    const wanted = search.toLocaleLowerCase();
    const start = from + (search.length === 1 ? 1 : 0);
    for (let k = 0; k < rows.length; k += 1) {
      const row = rows[(start + k) % rows.length];
      if (row?.node.label.toLocaleLowerCase().startsWith(wanted)) return go(row);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    // Keys typed in a rename field, an item action or a descendant item are theirs, not this item's.
    const target = event.target;
    if (!(target instanceof HTMLElement) || target !== event.currentTarget) return;
    const at = position.get(target.dataset["nodeId"] ?? "");
    const row = at === undefined ? undefined : rows[at];
    if (at === undefined || row === undefined) return;
    const id = row.node.id;
    const key = event.key;
    const ctrl = event.ctrlKey || event.metaKey;
    // A chord with Alt, Ctrl or Meta is the platform's (Alt/Cmd+←/→ history, Ctrl/Cmd+Home/End, Ctrl+letter
    // shortcuts) unless the tree declares it: Alt+↑/↓ with `onMove`, Ctrl+Space and Ctrl+A with `multiSelect`.
    // Ctrl/Cmd+Shift+A is not Ctrl+A (Cmd+Shift+A is the browser's tab search on macOS).
    // An undeclared chord is left alone, its default intact.
    const declared =
      (event.altKey &&
        !ctrl &&
        onMove !== undefined &&
        (key === "ArrowUp" || key === "ArrowDown")) ||
      (ctrl &&
        !event.altKey &&
        multiSelect &&
        (key === " " || (!event.shiftKey && key.toLowerCase() === "a")));
    if ((event.altKey || ctrl) && !declared) return;
    const parent = isParent(row.node);
    switch (key) {
      case "ArrowDown":
      case "ArrowUp": {
        const delta = key === "ArrowDown" ? 1 : -1;
        if (event.altKey) move(row, delta);
        else go(rows[at + delta], multiSelect && event.shiftKey);
        break;
      }
      case "ArrowRight":
        if (parent && !open.has(id)) onToggle(id, true);
        else if (parent) go(rows[at + 1]);
        break;
      case "ArrowLeft":
        if (parent && open.has(id)) onToggle(id, false);
        else if (row.parentId !== null) go(rows[position.get(row.parentId) ?? -1]);
        break;
      case "Home":
        go(rows[0]);
        break;
      case "End":
        go(rows[rows.length - 1]);
        break;
      case "*":
        for (const sibling of row.siblings) {
          if (isParent(sibling) && !open.has(sibling.id)) onToggle(sibling.id, true);
        }
        break;
      case "F2":
        if (onRename === undefined) return;
        setEditing(id);
        break;
      case " ":
        // Plain `Space` is the host's (SCR-036: visibility); the tree takes only its selection chords.
        if (!multiSelect || !(ctrl || event.shiftKey)) return;
        if (event.shiftKey) selectRange(id);
        else toggle(id);
        break;
      case "Escape":
        if (!multiSelect || selected.length === 0) return;
        event.stopPropagation();
        onSelect([]);
        break;
      default:
        if (ctrl) {
          // The only chord left here is the declared Ctrl+A.
          onSelect(row.siblings.map((sibling) => sibling.id));
          break;
        }
        if (key.length !== 1) return;
        typeAhead(key, at);
    }
    // Reached by every key the tree handles, including the APG no-ops (an arrow past the first or last row,
    // ArrowRight on a leaf), which stay prevented so they never scroll the panel. Every key the tree leaves
    // to the browser returned above with its default intact.
    event.preventDefault();
  };

  const onRowClick = (event: MouseEvent<HTMLElement>, id: string): void => {
    if (event.target instanceof Element && event.target.closest("[data-tree-actions], input"))
      return;
    if (multiSelect && event.shiftKey) selectRange(id);
    else if (multiSelect && (event.ctrlKey || event.metaKey)) toggle(id);
    else selectOnly(id);
    focusItem(id);
  };
  /** An event on this item's own row, not one bubbling up from a descendant item. */
  const ownEvent = (event: { target: EventTarget; currentTarget: EventTarget }): boolean =>
    event.target instanceof Element &&
    event.target.closest('[role="treeitem"]') === event.currentTarget;
  const sameGroup = (id: string): boolean =>
    dragged.current !== null && parents.get(dragged.current) === parents.get(id);
  const onDragOver = (event: DragEvent<HTMLElement>, id: string): void => {
    if (sameGroup(id)) event.preventDefault();
  };
  const onDrop = (event: DragEvent<HTMLElement>, row: Row): void => {
    const from = dragged.current;
    const ok = sameGroup(row.node.id);
    dragged.current = null;
    if (from === null || !ok || from === row.node.id) return;
    event.preventDefault();
    refocus.current = true;
    setActiveId(from);
    onMove?.(from, row.index);
  };

  const renderItems = (list: readonly TreeNode[], level: number): JSX.Element[] =>
    list.map((node) => {
      const id = node.id;
      const at = position.get(id);
      const row = at === undefined ? undefined : rows[at];
      const parent = isParent(node);
      const isOpen = parent && open.has(id);
      const isSelected = chosen.has(id);
      const isActive = id === active;
      const labelId = `${baseId}-${encodeURIComponent(id)}`;
      const treeItem = (
        <li
          ref={(element) => {
            if (element === null) items.current.delete(id);
            else items.current.set(id, element);
          }}
          role="treeitem"
          className="cv-tree__item"
          data-node-id={id}
          aria-level={level}
          aria-setsize={list.length}
          aria-posinset={(row?.index ?? 0) + 1}
          aria-expanded={parent ? isOpen : undefined}
          aria-selected={isSelected}
          aria-labelledby={labelId}
          tabIndex={isActive ? 0 : -1}
          onFocus={(event) => {
            if (event.target === event.currentTarget) setActiveId(id);
          }}
          // The pointer twins of the item's keys; a descendant item's events are its own.
          onClick={(event) => ownEvent(event) && onRowClick(event, id)}
          onDoubleClick={(event) => {
            if (!ownEvent(event) || onRename === undefined) return;
            if (event.target instanceof Element && event.target.closest("[data-tree-actions]"))
              return;
            setEditing(id);
          }}
          onDragOver={(event) => ownEvent(event) && onDragOver(event, id)}
          onDrop={(event) => ownEvent(event) && row !== undefined && onDrop(event, row)}
          onKeyDown={onKeyDown}
        >
          <div
            className="cv-tree__row"
            style={{ "--cv-tree-depth": String(level - 1) } as CSSProperties}
            data-selected={isSelected ? "" : undefined}
          >
            {onMove === undefined ? null : (
              <span
                className="cv-tree__handle"
                aria-hidden="true"
                draggable
                onDragStart={(event) => {
                  dragged.current = id;
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", id);
                }}
                onDragEnd={() => {
                  dragged.current = null;
                }}
              >
                <Icon name="drag-handle" />
              </span>
            )}
            <span
              className="cv-tree__disclosure"
              aria-hidden="true"
              onClick={(event) => {
                if (!parent) return;
                event.stopPropagation();
                focusItem(id);
                onToggle(id, !isOpen);
              }}
            >
              {parent ? <Icon name={isOpen ? "chevron-down" : "chevron-right"} /> : null}
            </span>
            {/* The check carries the selection beside the fill: colour is never the only signal (D22, §13). */}
            <span className="cv-tree__check" aria-hidden="true">
              {isSelected ? <Icon name="check" /> : null}
            </span>
            <span id={labelId} className="cv-tree__label" hidden={editing === id}>
              {node.label}
            </span>
            {editing === id ? (
              <TextInput
                aria-label={`Rename ${node.label}`}
                defaultValue={node.label}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== "Escape") return;
                  event.preventDefault();
                  event.stopPropagation();
                  finishRename(
                    node,
                    event.key === "Enter" ? event.currentTarget.value : null,
                    true,
                  );
                }}
                // A blur elsewhere cancels. The blur a browser fires as Enter or Esc unmounts the field never
                // arrives: React drops events during its commit, so it cannot clear the refocus flag (tested).
                onBlur={() => finishRename(node, null, false)}
              />
            ) : null}
            <span className="cv-tree__actions" data-tree-actions="">
              {itemActions(node, { tabIndex: isActive ? 0 : -1 })}
            </span>
          </div>
        </li>
      );
      // The children's group follows its item (not inside it), so an item's text is its own row's alone and its
      // name matches it; the hierarchy is declared by `aria-level`, `aria-setsize` and `aria-posinset`.
      // One shape whether open or closed, so opening never remounts the focused item.
      return (
        <Fragment key={id}>
          {treeItem}
          {isOpen ? (
            <li role="none" className="cv-tree__group-host">
              <ul role="group" className="cv-tree__group">
                {renderItems(node.children ?? [], level + 1)}
              </ul>
            </li>
          ) : null}
        </Fragment>
      );
    });

  if (nodes.length === 0) return null;
  return (
    <ul
      role="tree"
      className="cv-tree"
      data-cmp="CMP-240"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      aria-multiselectable={multiSelect ? true : undefined}
    >
      {renderItems(nodes, 1)}
    </ul>
  );
}
