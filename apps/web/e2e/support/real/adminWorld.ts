import type { generated } from "@candleviewer/protocol";
import type { BrowserContext, Page } from "@playwright/test";
import { TOTP_STEP_S, totp } from "../totp";
import { expect, type Lane } from "./failureArtefacts";
import { signIn, submitPassword } from "./signIn";
import type { FixtureRole, FixtureUser, RealStack } from "./stack";
import { tapWebSocket, type WsTap } from "./wsTap";

// E42-Q02 (#1215) part 1: the admin suite's actors on the real lane (BQ-2, BQ-3). An actor is a
// fixture user of one role, claimed for the test (`lane.user(role)`), in a browser of its own
// (`lane.newContext()`), signed in through the real SCR-001 with codes made at the server's time.
// There are two kinds, because a refresh and a step-up each rotate the session and revoke the
// bearer they replace (22 `authStepUp` "Session rotation"; `session_service.py` `refresh`): the SPA
// and the test cannot both hold one session's bearer, as each rotation would revoke the other's.
// - A page actor loads the SPA, which signs itself in from `cv_refresh` (one refresh, which its
//   test declares) and opens its socket, tapped from before the first page load (`wsTap.ts`). The
//   test reads its session by cookie (`session()`), never with a bearer of its own.
// - An API actor stays on SCR-002 after its password: the page completes MFA by `fetch` and keeps
//   the bearer that answer issued, and each one a step-up rotates in, in a closure that no page
//   script can enumerate (`window[BRIDGE]`). It presents no refresh. Its requests go out from the
//   page and come back as facts: a status, a problem code, an `ETag`, and the body with every
//   member named like a credential dropped. A bearer lives one access-token lifetime (about 12
//   minutes): a longer test opens another actor.
// A step-up is real, never a disabled gate: the password and a code at the server's time that no
// sign-in or step-up of the user has spent (one use per 30 s step), so a spent step moves the
// testnet test clock one step on. No live-enablement challenge is ever answered here.

/** A request the page sends. `path` is the contract's (`/users/{id}`): the page adds `/api/v1`. */
export interface ApiCall {
  readonly method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  readonly path: string;
  readonly body?: unknown;
  /** An `ETag` an earlier answer carried, sent as `If-Match`. */
  readonly ifMatch?: string;
  /** Sent as `Idempotency-Key`; a re-send carries the same one. */
  readonly idempotencyKey?: string;
}

/** An answer as the test reads it. */
export interface ApiFacts {
  readonly status: number;
  /** The problem's `code`, or `null`. */
  readonly code: string | null;
  /** The JSON body, every member named like a credential dropped; `null` when there is none. */
  readonly body: unknown;
  readonly etag: string | null;
}

/** `withChallenge`'s answers in order: the refused request, the step-up, the one re-send. */
export interface ChallengedFacts {
  readonly first: ApiFacts;
  readonly stepUp: ApiFacts | null;
  readonly resent: ApiFacts | null;
}

/** `GET /auth/session` by the page's cookie alone, as facts. */
export interface SessionFacts {
  readonly status: number;
  readonly code: string | null;
  readonly userId: string | null;
  readonly roles: readonly string[];
}

export interface Actor {
  readonly user: FixtureUser;
  readonly role: FixtureRole;
  readonly context: BrowserContext;
  readonly page: Page;
  /** The session its cookie names (`GET /auth/session`): no bearer, no refresh, no activity. */
  session(): Promise<SessionFacts>;
}

/** The SPA's own session, its socket tapped. */
export interface PageActor extends Actor {
  readonly tap: WsTap;
}

/** A session the SPA never holds, driven over the API from its page. */
export interface ApiActor extends Actor {
  api(call: ApiCall): Promise<ApiFacts>;
}

type StepUpBody =
  generated.rest.operations["authStepUp"]["requestBody"]["content"]["application/json"];

/**
 * The step-up classes the contract defines (22 `authStepUp` `action_class`), but
 * `live_enablement`, which this harness never elevates: the only classes `elevate` takes.
 */
export type ElevateClass = Exclude<NonNullable<StepUpBody["action_class"]>, "live_enablement">;

/** The grace classes this suite elevates (5 minutes each, 22 `authStepUp`). */
export type GraceClass = Extract<ElevateClass, "users" | "flags" | "audit" | "recorder">;

/** The page side's methods, on `window[BRIDGE]`. */
export interface Bridge {
  call(call: ApiCall): Promise<ApiFacts>;
  /** A step-up for a known class; any other class is refused before anything is sent. */
  elevate(password: string, code: string, actionClass: ElevateClass): Promise<ApiFacts>;
  challenged(call: ApiCall, password: string, code: string): Promise<ChallengedFacts>;
}

export const BRIDGE = "__cvE2eAdminApi";

/** What the page side opens with: its property, and the MFA step it completes. */
export interface BridgeOpen {
  readonly name: string;
  readonly handle: string;
  readonly code: string;
}

/**
 * The API actor's page side, run by `page.evaluate`: self-contained, as Playwright sends its
 * source alone. It defines `window[name]` (not enumerable, not writable), then completes MFA, and
 * keeps the newest bearer any answer issued in its closure. It returns facts only.
 */
export async function openBridge({ name, handle, code }: BridgeOpen): Promise<ApiFacts> {
  // A member whose name holds one of these words is dropped, at any depth and in any case, before
  // a body becomes a fact (and so before any report, log line or artefact can hold it): `secret`
  // and `seed` anywhere in a name (`totp_secret`, `recovery_seed`), and `otpauth`, the
  // provisioning URI an MFA enrolment answers with.
  const CREDENTIAL =
    /token|secret|password|passphrase|cookie|csrf|authorization|bearer|seed|totp|otpauth|recovery|challenge|signature|hmac|(^|_)key$|^kek|^dek|_url$/iu;
  // The classes `elevate` sends (`ElevateClass`, 22 `authStepUp`): anything else, a string the
  // contract does not define or `live_enablement`, throws before a request is made.
  const ELEVATED: readonly string[] = [
    "keys",
    "users",
    "killswitch",
    "risk_caps",
    "recorder",
    "flags",
    "audit",
    "backups",
    "sl_loosen",
    "accounts",
    "recorder_purge",
    "instruments",
  ] satisfies readonly ElevateClass[];
  // The classes this suite's challenges may be answered for: an explicit list, so a refusal whose
  // class is missing, not a string, unknown or `live_enablement` is never answered (fails closed).
  const ANSWERED: readonly string[] = [
    "users",
    "flags",
    "audit",
    "recorder",
    "keys",
    "killswitch",
    "risk_caps",
    "backups",
    "accounts",
    "recorder_purge",
  ];
  const scrub = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(scrub);
    if (value === null || typeof value !== "object") return value;
    const kept = Object.entries(value).filter(([member]) => !CREDENTIAL.test(member));
    return Object.fromEntries(kept.map(([member, inner]) => [member, scrub(inner)]));
  };
  let bearer = "";
  const mark = (): string => {
    const pairs = document.cookie.split(";").map((pair) => pair.trim());
    const pair = pairs.find((p) => p.startsWith("__Host-cv_csrf="));
    return pair === undefined ? "" : pair.slice("__Host-cv_csrf=".length);
  };
  const send = async (
    call: ApiCall,
  ): Promise<{ facts: ApiFacts; raw: Readonly<Record<string, unknown>> }> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (bearer !== "") headers["Authorization"] = `Bearer ${bearer}`;
    if (mark() !== "") headers["X-CSRF-Token"] = mark();
    if (call.ifMatch !== undefined) headers["If-Match"] = call.ifMatch;
    if (call.idempotencyKey !== undefined) headers["Idempotency-Key"] = call.idempotencyKey;
    const init: RequestInit = { method: call.method, headers, credentials: "same-origin" };
    if (call.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(call.body);
    }
    const res = await fetch(`/api/v1${call.path}`, init);
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text === "" ? null : (JSON.parse(text) as unknown);
    } catch {
      parsed = null;
    }
    const isObject = parsed !== null && typeof parsed === "object" && !Array.isArray(parsed);
    const raw = isObject ? (parsed as Record<string, unknown>) : {};
    const issued = raw["tokens"];
    const next =
      issued !== null && typeof issued === "object"
        ? (issued as Record<string, unknown>)["access_token"]
        : undefined;
    if (res.ok && typeof next === "string" && next !== "") bearer = next; // a rotation's successor
    const problem = raw["code"];
    const facts = {
      status: res.status,
      code: typeof problem === "string" ? problem : null,
      body: scrub(parsed),
      etag: res.headers.get("etag"),
    };
    return { facts, raw };
  };
  const stepUp = async (body: Record<string, unknown>): Promise<ApiFacts> =>
    (await send({ method: "POST", path: "/auth/step-up", body })).facts;
  const bridge: Bridge = Object.freeze({
    call: async (call: ApiCall) => (await send(call)).facts,
    elevate: async (password: string, now: string, actionClass: ElevateClass) => {
      if (typeof actionClass !== "string" || !ELEVATED.includes(actionClass)) {
        throw new Error(
          "elevate takes a step-up class the contract defines, never live_enablement",
        );
      }
      return stepUp({ password, code: now, action_class: actionClass });
    },
    challenged: async (call: ApiCall, password: string, now: string) => {
      const first = await send(call);
      const challenge = first.raw["challenge_id"];
      const cls = first.raw["action_class"];
      const known = typeof cls === "string" && ANSWERED.includes(cls); // never live_enablement
      if (first.facts.code !== "step_up_required" || typeof challenge !== "string" || !known) {
        return { first: first.facts, stepUp: null, resent: null };
      }
      const granted = await stepUp({ password, code: now, challenge_id: challenge });
      const resent = granted.status === 200 ? (await send(call)).facts : null;
      return { first: first.facts, stepUp: granted, resent };
    },
  });
  Object.defineProperty(window, name, { value: bridge, enumerable: false, writable: false });
  const verify = { mfa_token: handle, method: "totp", code };
  return (await send({ method: "POST", path: "/auth/mfa/verify", body: verify })).facts;
}

/** One bridge method, called in the API actor's page. */
async function viaBridge<R>(
  page: Page,
  method: keyof Bridge,
  args: readonly unknown[],
): Promise<R> {
  const answer: unknown = await page.evaluate(
    async ([name, called, given]) => {
      const bridge = (window as unknown as Record<string, Bridge | undefined>)[name];
      if (bridge === undefined) {
        throw new Error("the API actor's page loaded another document, which dropped its bearer");
      }
      return (bridge[called] as (...a: readonly unknown[]) => Promise<unknown>)(...given);
    },
    [BRIDGE, method, args] as const,
  );
  return answer as R;
}

/** `GET /auth/session` from `page` with its cookie alone. */
async function sessionOf(page: Page): Promise<SessionFacts> {
  return page.evaluate(async () => {
    const res = await fetch("/api/v1/auth/session", { credentials: "same-origin" });
    const body = (await res.json().catch(() => ({}))) as {
      code?: unknown;
      user?: { id?: unknown; roles?: unknown };
    };
    const roles = body.user?.roles;
    return {
      status: res.status,
      code: typeof body.code === "string" ? body.code : null,
      userId: typeof body.user?.id === "string" ? body.user.id : null,
      roles: Array.isArray(roles) ? roles.filter((r): r is string => typeof r === "string") : [],
    };
  });
}

const STEP_MS = TOTP_STEP_S * 1_000;

/** Codes for `user` at the server's time, never two in one step: a spent step moves the clock on. */
export function codeMaker(stack: RealStack, user: FixtureUser): () => string {
  let spent = Number.NEGATIVE_INFINITY;
  return () => {
    let at = stack.clock.serverNow();
    if (Math.floor(at / STEP_MS) <= spent) {
      stack.clock.advance(TOTP_STEP_S);
      at = stack.clock.serverNow();
    }
    spent = Math.floor(at / STEP_MS);
    return totp(user.seed(), at);
  };
}

/** Each API actor's password and codes, out of the actor's own reach. */
const OWN = new WeakMap<
  ApiActor,
  { readonly password: () => string; readonly code: () => string }
>();

/**
 * A page actor: signed in, then the SPA loads `route` (one refresh). `before` runs just before
 * that page load, to watch it from its first request.
 */
export async function openPageActor(
  lane: Lane,
  role: FixtureRole,
  { route, before }: { route: string; before?: (page: Page) => void },
): Promise<PageActor> {
  const user = lane.user(role);
  const page = await (await lane.newContext()).newPage();
  const tap = await tapWebSocket(page);
  await signIn(page, lane.stack, user);
  before?.(page);
  await page.goto(route);
  return { user, role, context: page.context(), page, tap, session: () => sessionOf(page) };
}

/** An API actor: its password through SCR-001, then MFA from its page, which keeps the bearer. */
export async function openApiActor(lane: Lane, role: FixtureRole): Promise<ApiActor> {
  const user = lane.user(role);
  const page = await (await lane.newContext()).newPage();
  const code = codeMaker(lane.stack, user);
  await page.goto("/login");
  const step = await submitPassword(page, user, lane.stack.password());
  expect(step.mfaRequired, "the password step asks for the second factor").toBe(true);
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  const open: BridgeOpen = { name: BRIDGE, handle: step.mfaToken(), code: code() };
  const verified = await page.evaluate(openBridge, open);
  expect(verified.status, "MFA from the page authenticated the session").toBe(200);
  const actor: ApiActor = {
    user,
    role,
    context: page.context(),
    page,
    session: () => sessionOf(page),
    api: (call) => viaBridge<ApiFacts>(page, "call", [call]),
  };
  OWN.set(actor, { password: () => lane.stack.password(), code });
  return actor;
}

function own(actor: ApiActor): { readonly password: () => string; readonly code: () => string } {
  const found = OWN.get(actor);
  if (found === undefined) throw new Error("not an actor openApiActor opened");
  return found;
}

/** A real step-up for a grace class, with a fresh code; the page takes the rotated bearer. */
export async function elevate(actor: ApiActor, cls: GraceClass): Promise<ApiFacts> {
  const { password, code } = own(actor);
  return viaBridge<ApiFacts>(actor.page, "elevate", [password(), code(), cls]);
}

/**
 * A no-grace class's request: sent; a `403 step_up_required` answered at `POST /auth/step-up`
 * with a fresh code and its `challenge_id`; then the same request re-sent once, unchanged.
 */
export async function withChallenge(actor: ApiActor, call: ApiCall): Promise<ChallengedFacts> {
  const { password, code } = own(actor);
  return viaBridge<ChallengedFacts>(actor.page, "challenged", [call, password(), code()]);
}
