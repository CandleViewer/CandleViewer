import { useState, type JSX, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { Countdown, spokenCountdown } from "./Countdown.js";
import { Link, type LinkRoute } from "./Link.js";
import { MonoText } from "./Typography.js";

/** CMP-087's copy, verbatim from E42-D03 §14 (`band.*`, `strip.*`, `footer.area_entered`). */
export const ADMIN_COPY = {
  bandName: "Admin area",
  /** `band.label` "◆ Admin area · {route}": the diamond is drawn `aria-hidden`. */
  bandGlyph: "◆",
  bandLabel: (route: string): string => `Admin area · ${route}`,
  /** `band.grace` "Still trusted for {class} · {m:ss}", up to CMP-035's count. */
  graceLead: (classLabel: string): string => `Still trusted for ${classLabel} · `,
  /**
   * PROPOSED (§14 has no key for (b)): the grace line's polite sentence at 60 s and 10 s, `left` in
   * words. Like `announce.admin_1min`, "Admin unlock expires in 1 minute.", it names what runs out.
   */
  graceAnnounce: (classLabel: string, left: string): string =>
    `Trust for ${classLabel} expires in ${left}.`,
  /** The strip's name and `strip.title`'s words, "Needs your action ({n})". */
  stripName: "Needs your action",
  stripNone: "Nothing needs your action",
  /** §6 Keys: "Attention:" prefixes every warning's accessible name. */
  attention: "Attention:",
  /** The host's footer once an `/admin/*` read was served (D27). */
  footerAreaEntered: "Entering this area was recorded — Area entered (admin.area_entered)",
} as const;

/** §4's ordering classes: OV-9 withdrawal, OV-10 break-glass, OV-5 tamper, SH-4 lock, the rest. */
export type AdminStripKind = "withdrawal" | "break_glass" | "tamper" | "locked" | "other";
export type AdminStripSeverity = "critical" | "warning" | "info";
export type AdminEnv = "LIVE" | "DEMO" | "TESTNET";

export interface AdminStripItem {
  /** A stable domain id: the list key. */
  readonly id: string;
  /** The host's §14 `strip.*` words, e.g. "1 key expires within 30 days → Accounts and keys". */
  readonly label: string;
  /** CMP-021's `to` through `linkAs`, else its plain `href`. */
  readonly href: string;
  readonly kind: AdminStripKind;
  readonly severity: AdminStripSeverity;
  /** The slice's environment badge, read in the item's name; none for a slice without one. */
  readonly env?: AdminEnv | undefined;
  /** When the condition was raised, epoch ms: the recency tie-break, newest first. */
  readonly at?: number | undefined;
}

/** A live step-up grace for one action class (variant (b), SH-5), from the step-up answer. */
export interface AdminGrace {
  /** "user changes" (`users`) or "risk limits" (`risk_caps`). */
  readonly classLabel: string;
  /** The server's `elevated_until`, epoch ms on the server clock: counted, never recomputed. */
  readonly expiresAt: number;
}

export interface AdminLayoutProps {
  /** "Users" reads "◆ Admin area · Users". */
  readonly routeLabel: string;
  /** The items, any order; `[]` reads `strip.none`; omitted (no source read yet), no strip. */
  readonly strip?: readonly AdminStripItem[] | undefined;
  /** The grace line at the band's end; omitted, the band holds its label only (SH-6). */
  readonly grace?: AdminGrace | undefined;
  /** Fires once when the grace's deadline passes and its line goes; focus never moves. */
  readonly onGraceExpire?: (() => void) | undefined;
  /** The app's router link component for the strip's links (CMP-021's `as`). */
  readonly linkAs?: LinkRoute | undefined;
  /** One plain-text line after the route content, e.g. `ADMIN_COPY.footerAreaEntered`. */
  readonly footer?: ReactNode;
  /** The server's clock, epoch ms (the client's plus its measured offset), for the grace count. */
  readonly now?: (() => number) | undefined;
  /** The route content: its CMP-088 PageHeader (the page's one `h1`), then the page. */
  readonly children: ReactNode;
}

const KINDS: readonly AdminStripKind[] = ["withdrawal", "break_glass", "tamper", "locked", "other"];
const SEVERITIES: readonly AdminStripSeverity[] = ["critical", "warning", "info"];
/** The glyph and the words carry the tone, never the fill alone. */
const GLYPH = { critical: "danger", warning: "warning", info: "info" } as const;
/** SH-5: one polite announcement at 60 s and one at 10 s (D06:67); the line goes at 0. */
const GRACE_THRESHOLDS: readonly number[] = [60, 10];

const rank = <T,>(order: readonly T[], a: T, b: T): number => order.indexOf(a) - order.indexOf(b);

/**
 * §4's order (D02:118): withdrawal, break-glass, tamper and the lock first, then severity, then
 * recency (untimed last). Stable, and a new array: the host's is left as it was.
 */
export function sortAdminStrip(items: readonly AdminStripItem[]): AdminStripItem[] {
  const recency = (a: AdminStripItem, b: AdminStripItem): number => {
    const [x, y] = [a.at ?? -Infinity, b.at ?? -Infinity];
    return x === y ? 0 : x > y ? -1 : 1;
  };
  return [...items].sort(
    (a, b) =>
      rank(KINDS, a.kind, b.kind) || rank(SEVERITIES, a.severity, b.severity) || recency(a, b),
  );
}

/** A CMP-021 link drawn as the tone pill, named "Attention: {label} {ENV}". */
function StripItem({ item, linkAs }: { item: AdminStripItem; linkAs?: LinkRoute }): JSX.Element {
  const attention = item.severity !== "info" && !item.label.startsWith(ADMIN_COPY.attention);
  const content = (
    <>
      <span className="cv-adminlayout__glyph">
        <Icon name={GLYPH[item.severity]} />
      </span>
      {attention ? <span className="cv-visually-hidden">{`${ADMIN_COPY.attention} `}</span> : null}
      <span className="cv-adminlayout__text">{item.label}</span>
      {item.env === undefined ? null : (
        <span className={`cv-adminlayout__env cv-adminlayout__env--${item.env.toLowerCase()}`}>
          {` ${item.env}`}
        </span>
      )}
    </>
  );
  return (
    <li className="cv-adminlayout__item" data-severity={item.severity}>
      {linkAs === undefined ? (
        <Link href={item.href}>{content}</Link>
      ) : (
        <Link to={item.href} as={linkAs}>
          {content}
        </Link>
      )}
    </li>
  );
}

/**
 * CMP-087 to variant (b), per-action step-up (E42-D03 §4): the "Admin area" band (never focusable; the
 * optional grace line), its 4 px rule, the "Needs your action" strip (links, not live), the route content
 * and the footer line. Comfortable density on its subtree is one of the carriers that set the admin area
 * apart without colour. No `h1`, no `main`, no live region but CMP-035's; it never moves focus.
 */
export function AdminLayout(props: AdminLayoutProps): JSX.Element {
  const { routeLabel, strip, grace, onGraceExpire, linkAs, footer, now, children } = props;
  // The deadline whose line has gone: a new `expiresAt` brings the line back.
  const [expiredAt, setExpiredAt] = useState<number | null>(null);
  return (
    <div className="cv-adminlayout" data-cmp="CMP-087" data-density="comfortable">
      <section className="cv-adminlayout__band" aria-label={ADMIN_COPY.bandName}>
        <span className="cv-adminlayout__label">
          <span aria-hidden="true">{ADMIN_COPY.bandGlyph}</span> {ADMIN_COPY.bandLabel(routeLabel)}
        </span>
        {grace === undefined || expiredAt === grace.expiresAt ? null : (
          <span className="cv-adminlayout__grace">
            {ADMIN_COPY.graceLead(grace.classLabel)}
            <Countdown
              expiresAt={grace.expiresAt}
              thresholds={GRACE_THRESHOLDS}
              announce={(seconds) =>
                ADMIN_COPY.graceAnnounce(grace.classLabel, spokenCountdown(seconds, "mm:ss"))
              }
              size="base"
              onExpire={() => {
                setExpiredAt(grace.expiresAt);
                onGraceExpire?.();
              }}
              {...(now === undefined ? {} : { now })}
            />
          </span>
        )}
      </section>
      {strip === undefined ? null : (
        <section className="cv-adminlayout__strip" aria-label={ADMIN_COPY.stripName}>
          {strip.length === 0 ? (
            <p className="cv-adminlayout__none">{ADMIN_COPY.stripNone}</p>
          ) : (
            <>
              <p className="cv-adminlayout__title">
                {ADMIN_COPY.stripName} <MonoText size="base">{`(${strip.length})`}</MonoText>
              </p>
              <ul className="cv-adminlayout__list">
                {sortAdminStrip(strip).map((item) => (
                  <StripItem key={item.id} item={item} {...(linkAs ? { linkAs } : {})} />
                ))}
              </ul>
            </>
          )}
        </section>
      )}
      {children}
      {footer === undefined || footer === null || footer === false ? null : (
        <div className="cv-adminlayout__footer">{footer}</div>
      )}
    </div>
  );
}
