/**
 * E16-S04: SCR-142's test harness: the section mounted alone over the stubbed `apiFetch` (the test file mocks
 * `lib/http/csrfFetch`, so this module reads the double), answers from `22`'s examples, the shell announcer beside
 * it, a router for the System health link, and the queries the tests share (the section, its one polite region,
 * a card's rows, axe). No network (C-13.5); the clock is the test's fake one.
 */
import { createRequire } from "node:module";
import { act, render, screen, within, type RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import type { StoragePanelProps } from "../../../../src/features/recorder/extensions";
import {
  StoragePanel,
  type StoragePanelOptions,
} from "../../../../src/features/recorder/storage/StoragePanel";
import { apiFetch } from "../../../../src/lib/http/csrfFetch";
import { HEALTH, REPORT, STATUS, frameWith } from "./storageFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

export const HEADING = "cv-recorder-storage";
export const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
export const problem = (status: number, code: string): Response =>
  json(status, { code, status, title: "x", type: "about:blank", detail: "never rendered" });
export const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
export const advance = (ms: number) =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

/** A route answers a request (a held answer is a promise), or leaves it to the reads' defaults. */
export type Route = (method: string, url: string) => Response | Promise<Response> | undefined;
const fetchDouble = () => vi.mocked(apiFetch);

/** The section's reads by path (`22`'s examples); `over` answers first. */
export function serve(over: Route = () => undefined) {
  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const first = over(method, url);
    if (first !== undefined) return first;
    const path = url.replace("/api/v1", "");
    if (path === "/recording/storage") return json(200, REPORT);
    if (path === "/admin/health") return json(200, HEALTH);
    return problem(404, "not_found");
  };
}

/** Every request sent: "METHOD /path", with its JSON body when it has one. */
export const sent = (): string[] =>
  fetchDouble().mock.calls.map(([url, init]) => {
    const head = `${init?.method ?? "GET"} ${String(url).replace("/api/v1", "")}`;
    return typeof init?.body === "string" ? `${head} ${init.body}` : head;
  });
/** The writes alone. */
export const writes = (): string[] => sent().filter((line) => !line.startsWith("GET "));
/** The headers of the `n`th write. */
export function writeHeaders(n = 0): Headers {
  const posts = fetchDouble().mock.calls.filter(([, init]) => (init?.method ?? "GET") !== "GET");
  return new Headers(posts[n]?.[1]?.headers);
}

export type PanelProps = Partial<StoragePanelProps & StoragePanelOptions>;
const base: StoragePanelProps = {
  headingId: HEADING,
  status: STATUS,
  storage: null,
  frame: frameWith(),
  stale: false,
};

export function panel(props: PanelProps = {}) {
  return (
    <MemoryRouter>
      <StoragePanel {...base} {...props} />
      <ShellAnnouncer />
    </MemoryRouter>
  );
}
export async function mount(props: PanelProps = {}, over?: Route): Promise<RenderResult> {
  fetchDouble().mockImplementation(serve(over));
  const view = render(panel(props));
  await flush();
  return view;
}

export const section = (): HTMLElement =>
  screen.getByRole("region", { name: "Storage and database" });
/** RG-13: the section's one polite region. */
export const region = (): HTMLElement =>
  section().querySelector(':scope > [role="status"][aria-live="polite"]') as HTMLElement;
/**
 * Each utterance written into `target`, in order: one per node it mounts (every utterance re-keys its node), so the
 * same words said twice count twice (C-486P3-13).
 */
export function utterancesOf(target: Element): () => string[] {
  const said: string[] = [];
  const collect = (records: readonly MutationRecord[]): void => {
    for (const record of records) {
      for (const node of record.addedNodes)
        if (node instanceof Element) said.push(node.textContent ?? "");
    }
  };
  const observer = new MutationObserver(collect);
  observer.observe(target, { childList: true });
  return () => {
    collect(observer.takeRecords());
    return said;
  };
}
/** Each utterance of the section's region, in order. */
export const utterances = (): (() => string[]) => utterancesOf(region());
/**
 * The shell announcer's polite region: exempt from a modal's inert, as the section's own is, and the only one with
 * no role (its regions carry `aria-live` alone).
 */
export const shellRegion = (): Element | null =>
  document.querySelector('[aria-live="polite"][data-cv-inert-exempt]:not([role])');
/** The shell announcer's polite words now (a T2 reason, a refusal at the point of action). */
export const shellSaid = (): string => shellRegion()?.textContent ?? "";
/** An answer held until the test lets it land. */
export function held(): {
  readonly answer: () => Promise<Response>;
  readonly land: (response: Response) => void;
} {
  let land: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    land = resolve;
  });
  return { answer: () => pending, land: (response) => land(response) };
}

export const card = (title: string): HTMLElement =>
  screen
    .getByRole("heading", { level: 3, name: new RegExp(`^${title}`) })
    .closest("[data-cmp='CMP-050']") as HTMLElement;
/** A card's rows as "term: definition", the definition as read (an aria-hidden "—" left out). */
export function rowsOf(host: HTMLElement): Record<string, string> {
  const terms = within(host).getAllByRole("term");
  const defs = within(host).getAllByRole("definition");
  return Object.fromEntries(
    terms.map((term, i) => {
      const def = defs[i]?.cloneNode(true) as HTMLElement;
      def.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
      return [term.textContent ?? "", (def.textContent ?? "").trim()];
    }),
  );
}

/** axe's serious and critical findings (jsdom has no layout: contrast is the real browser's). */
export async function seriousAxe(element: Element): Promise<unknown[]> {
  vi.useRealTimers();
  const res = await axe.run(element, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}
