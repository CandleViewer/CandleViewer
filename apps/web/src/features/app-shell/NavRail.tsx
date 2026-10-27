import { useEffect, useRef, type CSSProperties, type JSX } from "react";
import { NavLink, useNavigate } from "react-router";
import { Icon } from "@candleviewer/ui";
import { getMeClaims } from "../../lib/auth/meCache";
import { registerCommand } from "../../keymap/KeymapHost";
import { ROUTE_MANIFEST } from "../../routes/manifest";
import { evaluateAccess, type MeClaims } from "../../routes/rbac";
import { NAV_ITEMS, type NavBadges, type NavItem } from "./navItems";

type RailItem = (typeof NAV_ITEMS)[number] & { readonly to: string };

const PATHS = new Map(ROUTE_MANIFEST.map((e) => [e.id, e]));

/**
 * The items `claims` may open, in rail order. A UX affordance only: the route guard and the
 * server's 403 stay the boundary (`04-security-program.md` §7.3). Filtering here, before render,
 * keeps a denied item (Admin for a non-owner, plan gaps 1 and 2) out of the DOM and the a11y tree.
 */
export function visibleNavItems(claims: MeClaims): readonly RailItem[] {
  return NAV_ITEMS.flatMap((item) => {
    const entry = PATHS.get(item.routeId);
    if (!entry || evaluateAccess(entry.access, claims).kind !== "allow") return [];
    return [{ ...item, to: entry.path }];
  });
}

/** `Alt+N` for the Nth item; Admin and anything past the ninth get none (plan gap 3). */
function digitFor(item: NavItem, index: number): number | null {
  return item.id === "admin" || index >= 9 ? null : index + 1;
}

const LIST: CSSProperties = { listStyle: "none", margin: 0, padding: "var(--space-2) 0" };

/** D03 §5.2 "current": the selected fill, a 3 px leading bar and the medium weight — not colour alone. */
function linkStyle({ isActive }: { isActive: boolean }): CSSProperties {
  return {
    display: "flex",
    gap: "var(--space-2)",
    padding: "var(--space-inset-sm)",
    minHeight: "var(--size-target-min)",
    color: "var(--color-text-primary)",
    textDecoration: "none",
    fontWeight: isActive ? "var(--font-weight-medium)" : "var(--font-weight-regular)",
    background: isActive ? "var(--color-surface-selected)" : "transparent",
    boxShadow: isActive ? "inset 3px 0 0 var(--color-border-selected)" : "none",
  };
}

const BADGE: CSSProperties = { color: "var(--color-text-secondary)" };

const ARROWS: Readonly<Record<string, (i: number, n: number) => number>> = {
  ArrowDown: (i, n) => (i + 1) % n,
  ArrowUp: (i, n) => (i - 1 + n) % n,
  Home: () => 0,
  End: (_i, n) => n - 1,
};

export interface NavRailProps {
  /** Count words per item ("2 new"). Nothing supplies one yet; the slot renders nothing. */
  readonly badges?: NavBadges;
}

/**
 * CMP-071 NavRail (E10-S01 S5, #304), expanded variant: a list of links inside the shell's
 * `nav` "Primary". CMP-071 and the ticket name a `nav` with `aria-current`; SCR-011, E10-D02 and
 * D03 say `role="tree"` (plan gap 9): links stay in the Tab order, and the arrows, Home and End
 * also move between them (D03 §5.4). Collapse, pin and tooltips are S6. Stand-ins: the badge is
 * a plain span (CMP-012), the `Alt+N` hint is `aria-keyshortcuts` only (CMP-016 / CMP-022).
 */
export function NavRail({ badges = {} }: NavRailProps): JSX.Element {
  const navigate = useNavigate();
  const items = visibleNavItems(getMeClaims());
  const list = useRef<HTMLUListElement>(null);

  const targets = items.flatMap((item, i) => (digitFor(item, i) === null ? [] : [item.to]));
  // `Alt+1..9` (keymap.json); re-registered per render (on navigation only), so it sees these items.
  useEffect(() =>
    registerCommand("global.nav_rail", (digit) => {
      const to = digit === undefined ? undefined : targets[digit - 1];
      if (to !== undefined) void navigate(to);
    }),
  );

  // The list owns the arrow keys of the links inside it; each link stays a Tab stop.
  useEffect(() => {
    const el = list.current;
    const onKeyDown = (e: KeyboardEvent): void => {
      const move = ARROWS[e.key];
      const links = [...(el?.querySelectorAll<HTMLAnchorElement>("a") ?? [])];
      const at = links.findIndex((a) => a === document.activeElement);
      if (!move || at < 0) return;
      e.preventDefault();
      links[move(at, links.length)]?.focus();
    };
    el?.addEventListener("keydown", onKeyDown);
    return () => el?.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <ul ref={list} style={LIST}>
      {items.map((item, i) => {
        const badge = badges[item.id];
        const digit = digitFor(item, i);
        return (
          <li key={item.id}>
            <NavLink
              to={item.to}
              style={linkStyle}
              aria-label={badge === undefined ? undefined : `${item.label}, ${badge}`}
              aria-keyshortcuts={digit === null ? undefined : `Alt+${digit}`}
            >
              {item.icon === null ? null : <Icon name={item.icon} />}
              <span>{item.label}</span>
              {badge === undefined ? null : <span style={BADGE}>{badge}</span>}
            </NavLink>
          </li>
        );
      })}
    </ul>
  );
}
