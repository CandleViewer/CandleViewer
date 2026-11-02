/**
 * The client side of the password policy (E09-D05 §4; `04-security-program.md` §6.3.1). The server
 * decides (R-1): what the client can evaluate is shown met or not met, and a rule only the server
 * checks reads "checked when you submit" until the server answers.
 */

/** `24` `AuthConfig.password_min_length` (C-85), in Unicode code points, never trimmed. */
export const MIN_LENGTH = 14;
/** The username or the email's local part counts only from this many characters (`04` §6.3.1). */
export const IDENTITY_MIN = 3;

export type ItemId = "length" | "breach" | "reuse" | "match" | "identity";
/** CMP-203's three states: `server` reads "checked when you submit" (E09-D05 §4.2). */
export type ItemState = "met" | "not-met" | "server";
export interface Item {
  readonly id: ItemId;
  readonly label: string;
  readonly state: ItemState;
}
/** The server items a refusal marked not met, until the new password is edited again. */
export type ServerVerdicts = Partial<Record<"breach" | "reuse" | "identity", true>>;
export interface Identity {
  readonly username: string;
  readonly email: string;
}

/** W-1 … W-5 (E09-D05 §11.1; W-1 with the ruled 14 of `14` SCR-004), in `14`:209's order. */
export const ITEM_LABELS: Readonly<Record<ItemId, string>> = {
  length: "≥14 chars",
  breach: "not in breach list",
  reuse: "not equal to previous 5",
  match: "must match confirmation",
  identity: "Doesn't contain your username or email",
};

/** The server's `len()`: code points, so an astral character counts once. */
export const codePoints = (value: string): number => Array.from(value).length;

/** INV:128–132's predicate, lower-cased; a part shorter than `IDENTITY_MIN` never matches. */
export function containsIdentity(password: string, identity: Identity): boolean {
  const pw = password.toLowerCase();
  const local = identity.email.split("@", 1)[0] ?? "";
  return [identity.username, local].some(
    (part) => codePoints(part) >= IDENTITY_MIN && pw.includes(part.toLowerCase()),
  );
}

/**
 * The five items (E09-D05 §4.1). The identity item is client-evaluated only when the host knows the
 * user's username and email; otherwise the server checks it.
 */
export function evaluate(
  next: string,
  confirm: string,
  identity: Identity | undefined,
  verdicts: ServerVerdicts,
): readonly Item[] {
  const lengthMet = codePoints(next) >= MIN_LENGTH;
  const identityState: ItemState =
    verdicts.identity === true
      ? "not-met"
      : identity === undefined
        ? "server"
        : next !== "" && !containsIdentity(next, identity)
          ? "met"
          : "not-met";
  const states: Record<ItemId, ItemState> = {
    length: lengthMet ? "met" : "not-met",
    breach: verdicts.breach === true ? "not-met" : "server",
    reuse: verdicts.reuse === true ? "not-met" : "server",
    match: next !== "" && next === confirm ? "met" : "not-met",
    identity: identityState,
  };
  return (Object.keys(ITEM_LABELS) as ItemId[]).map((id) => ({
    id,
    label: ITEM_LABELS[id],
    state: states[id],
  }));
}

export type Score = 0 | 1 | 2 | 3 | 4;
export type StrengthWord = "Weak" | "Fair" | "Strong";

/**
 * The frontend's estimator (E09-D05 §4.3, T Tech): length in code points, character classes and
 * distinct characters. Synchronous and local; it never makes a network call (§4.4).
 */
export function strengthScore(password: string): Score {
  const chars = Array.from(password);
  if (new Set(chars).size < 4) return 0;
  const classes = [/\p{Ll}/u, /\p{Lu}/u, /\p{N}/u, /[^\p{L}\p{N}]/u].filter((re) =>
    re.test(password),
  ).length;
  const points =
    Number(chars.length >= 8) +
    Number(chars.length >= MIN_LENGTH) +
    Number(chars.length >= 20) +
    Number(classes >= 3);
  return Math.min(points, 4) as Score;
}

/** W-8 by score; "Weak" whatever the score while the length item is not met (the cap, A-17). */
export function meterWord(score: Score, lengthMet: boolean): StrengthWord {
  if (!lengthMet || score <= 1) return "Weak";
  return score === 2 ? "Fair" : "Strong";
}
