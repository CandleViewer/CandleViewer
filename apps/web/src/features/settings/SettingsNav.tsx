import { useEffect, useId, useRef, useState, type CSSProperties, type JSX } from "react";
import { Link, useLocation } from "react-router";
import { NOT_BUILT_REASON, SECTIONS, type SettingsSection } from "./sections";

/** The section the location is on; a hash section wins over its route's plain section. */
export function currentSectionId(pathname: string, hash: string): string | null {
  const here = SECTIONS.filter((s) => s.path === pathname);
  return (here.find((s) => s.hash === hash) ?? here.find((s) => s.hash === undefined))?.id ?? null;
}

const TARGET = "var(--size-target-min, 24px)";
/** Token colours, never the browser's link blue (contrast); the open section is bold, not colour alone. */
const ITEM: CSSProperties = {
  display: "block",
  minHeight: TARGET,
  color: "var(--color-text-primary)",
  textDecoration: "underline",
  background: "none",
  border: "none",
  padding: 0,
  font: "inherit",
  textAlign: "start",
};
const DISABLED: CSSProperties = {
  ...ITEM,
  color: "var(--color-text-secondary)",
  textDecoration: "none",
};
const NOTE: CSSProperties = { display: "block", color: "var(--color-text-secondary)" };

interface ItemProps {
  readonly section: SettingsSection;
  readonly current: boolean;
  /** Roving tabindex: only the active item is a Tab stop; the arrows move it. */
  readonly tabStop: boolean;
  readonly onFocus: () => void;
}

function Item({ section, current, tabStop, onFocus }: ItemProps): JSX.Element {
  const descId = useId();
  const href = section.path === undefined ? null : `${section.path}${section.hash ?? ""}`;
  const tabIndex = tabStop ? 0 : -1;
  return (
    <li>
      {href === null ? (
        // No destination yet: focusable, aria-disabled, does nothing, its reason read with it (T2).
        <button
          type="button"
          aria-disabled="true"
          aria-describedby={descId}
          tabIndex={tabIndex}
          onFocus={onFocus}
          style={DISABLED}
          data-nav-item
        >
          {section.label}
        </button>
      ) : (
        <Link
          to={href}
          aria-current={current ? "page" : undefined}
          aria-describedby={descId}
          tabIndex={tabIndex}
          onFocus={onFocus}
          style={current ? { ...ITEM, fontWeight: 700 } : ITEM}
          data-nav-item
        >
          {section.label}
        </Link>
      )}
      <span style={NOTE} id={descId}>
        {href === null ? NOT_BUILT_REASON : section.description}
      </span>
    </li>
  );
}

/**
 * CMP-086 nav half: a list of links with `aria-current`. One Tab stop (roving tabindex, starting on the open
 * section); Up and Down move it, Home and End jump to the ends, and Tab leaves the list.
 */
export function SettingsNav(): JSX.Element {
  const { pathname, hash } = useLocation();
  const current = currentSectionId(pathname, hash);
  const [stop, setStop] = useState<string | null>(null);
  const tabStopId = stop ?? current ?? SECTIONS[0]?.id ?? null;
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    // The open section is the stop again whenever navigation changes it.
    setStop(null);
  }, [current]);

  useEffect(() => {
    const ul = list.current;
    if (ul === null) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const items = [...ul.querySelectorAll<HTMLElement>("[data-nav-item]")];
      const at = items.indexOf(document.activeElement as HTMLElement);
      const last = items.length - 1;
      const to =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? last
            : Math.min(last, Math.max(0, at + (event.key === "ArrowDown" ? 1 : -1)));
      event.preventDefault();
      items[to]?.focus(); // its onFocus makes it the Tab stop
    };
    ul.addEventListener("keydown", onKeyDown);
    return () => ul.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <nav aria-label="Settings">
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }} ref={list}>
        {SECTIONS.map((s) => (
          <Item
            key={s.id}
            section={s}
            current={s.id === current}
            tabStop={s.id === tabStopId}
            onFocus={() => setStop(s.id)}
          />
        ))}
      </ul>
    </nav>
  );
}
