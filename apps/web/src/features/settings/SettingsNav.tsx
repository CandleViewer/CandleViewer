import { useEffect, useId, useRef, type JSX } from "react";
import { Link, useLocation } from "react-router";
import { NOT_BUILT_REASON, SECTIONS, type SettingsSection } from "./sections";

/** The section the location is on; a hash section wins over its route's plain section. */
export function currentSectionId(pathname: string, hash: string): string | null {
  const here = SECTIONS.filter((s) => s.path === pathname);
  return (here.find((s) => s.hash === hash) ?? here.find((s) => s.hash === undefined))?.id ?? null;
}

function Item({ section, current }: { section: SettingsSection; current: boolean }): JSX.Element {
  const reasonId = useId();
  const href = section.path === undefined ? null : `${section.path}${section.hash ?? ""}`;
  return (
    <li>
      {href === null ? (
        // No destination yet: focusable, aria-disabled, does nothing, its reason read with it (T2).
        <button type="button" aria-disabled="true" aria-describedby={reasonId} data-nav-item>
          {section.label}
        </button>
      ) : (
        <Link to={href} aria-current={current ? "page" : undefined} data-nav-item>
          {section.label}
        </Link>
      )}
      <span style={{ display: "block" }} id={reasonId}>
        {href === null ? NOT_BUILT_REASON : section.description}
      </span>
    </li>
  );
}

/** CMP-086 nav half: a list of links with `aria-current`; Up/Down/Home/End move between items. */
export function SettingsNav(): JSX.Element {
  const { pathname, hash } = useLocation();
  const current = currentSectionId(pathname, hash);

  const list = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const ul = list.current;
    if (ul === null) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
      if (!keys.includes(event.key)) return;
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
      items[to]?.focus();
    };
    ul.addEventListener("keydown", onKeyDown);
    return () => ul.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <nav aria-label="Settings">
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }} ref={list}>
        {SECTIONS.map((s) => (
          <Item key={s.id} section={s} current={s.id === current} />
        ))}
      </ul>
    </nav>
  );
}
