/**
 * HL-17's detail view at `?component={name}` (E42-D05 §5.3; generic for every tile [BQ-11]): the
 * component's open incidents from page 1 of `status=open`, said so; Recorder & storage for the
 * recorder and the DB tiers; no history yet (CG-17) and no last-hour metrics (CG-20). A name no
 * tile has says so and is never shown. Its way back takes focus when it opens; the page hands focus
 * to the tile's heading link when it closes. The document title names the view (A-1084P1-d04).
 */
import { useCallback, useEffect, useRef, type JSX } from "react";
import { Link } from "@candleviewer/ui";
import { documentTitle } from "../../../routes/titles";
import { routePath } from "../overview/links";
import { routerLink } from "../routerLink";
import { HEALTH_COPY as COPY } from "./copy";
import { useHealthSelector, type HealthState } from "./healthStore";
import { headingOf } from "./labels";
import { ANCHOR, componentsOf, FIXED_TILES } from "./tiles";

/** The components SCR-140 (Recorder & storage) reports on. */
const RECORDER_SCREEN: ReadonlySet<string> = new Set([
  "recorder",
  "postgres",
  "questdb",
  "parquet_store",
]);
const BACK = routePath("health") ?? "/admin/health";
const RECORDER = routePath("recorder");
const TITLE_ID = "health-detail-title";
/** The client-composed tiles name no served component: their own labels head their views. */
const FIXED = [...FIXED_TILES, { key: "clock", label: COPY.clock.label }];

const selectOpen = (s: HealthState): HealthState["reads"]["open"] => s.reads.open;
/** "yyyy-mm-dd hh:mm" in UTC. */
const minute = (iso: string): string => new Date(iso).toISOString().slice(0, 16).replace("T", " ");
/** The view's heading: a fixed tile's label, a served component's, or none for a name no tile has. */
function headingFor(name: string, s: HealthState): string | undefined {
  const fixed = FIXED.find((t) => t.key === name);
  if (fixed !== undefined) return fixed.label;
  const served = componentsOf(s).some((r) => r.name === name);
  // Until the report answers with a body, a name shaped as a component's may still be one.
  const { phase, data } = s.reads.health;
  const unread = phase === "idle" || (phase === "failed" && data === undefined);
  const pending = unread && ANCHOR.test(name);
  return served || pending ? headingOf(name) : undefined;
}
const arrow = (glyph: string): JSX.Element => <span aria-hidden="true">{glyph}</span>;

export function ComponentDetail({ name }: { readonly name: string }): JSX.Element {
  const root = useRef<HTMLElement>(null);
  const open = useHealthSelector(selectOpen);
  const heading = useHealthSelector(useCallback((s: HealthState) => headingFor(name, s), [name]));
  useEffect(() => {
    root.current?.querySelector<HTMLElement>("a")?.focus();
  }, [name]);
  useEffect(() => {
    const was = document.title;
    document.title = documentTitle(`${COPY.title} - ${heading ?? COPY.drill.unknownTitle}`);
    return () => {
      document.title = was;
    };
  }, [heading]);
  const rows = open.data?.items.filter((incident) => incident.component === name) ?? [];
  let list: JSX.Element | null = null;
  if (open.data === undefined) list = open.phase === "idle" ? null : <p>{COPY.drill.unread}</p>;
  else if (rows.length === 0) list = <p>{COPY.drill.none}</p>;
  else {
    list = (
      <ul>
        {rows.map((incident) => (
          <li key={incident.id}>
            {COPY.drill.row(
              incident.severity,
              incident.title ?? COPY.drill.withheld,
              minute(incident.last_seen_at),
            )}
          </li>
        ))}
      </ul>
    );
  }
  const back = (
    <p>
      <Link to={BACK} as={routerLink}>
        {arrow("← ")}
        {COPY.drill.back}
      </Link>
    </p>
  );
  if (heading === undefined) {
    return (
      <section ref={root} aria-labelledby={TITLE_ID}>
        {back}
        <h2 id={TITLE_ID}>{COPY.drill.unknown}</h2>
      </section>
    );
  }
  return (
    <section ref={root} aria-labelledby={TITLE_ID}>
      {back}
      <h2 id={TITLE_ID}>{heading}</h2>
      <p>{COPY.drill.filtered}</p>
      {list}
      {RECORDER === undefined || !RECORDER_SCREEN.has(name) ? null : (
        <p>
          <Link to={RECORDER} as={routerLink}>
            {COPY.drill.recorder}
            {arrow(" →")}
          </Link>
        </p>
      )}
      <p>{COPY.noHistory}</p>
      <p>{COPY.noMetrics}</p>
    </section>
  );
}
