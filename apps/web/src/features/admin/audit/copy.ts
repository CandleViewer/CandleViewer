/**
 * SCR-135 and SCR-136's words (E42-S04): E42-D04 §14's keys, verbatim, and the keys it inherits by
 * reference (E42-D03's `meta.asof`, E09-D09's `inflight.*` and `rbac.owner_only` verbs). A screen
 * cites a key here, never its own string (D04 D30; D09:85). A string no source gives is marked
 * PROPOSED, with its owner, and listed in `14`'s "As built" line. `{…}` fills come in already
 * formatted: times through `utc`, ids and counts through `num` (§1: "entry 1,204,118").
 */

const two = (n: number): string => String(n).padStart(2, "0");

/** UTC clock fills (D02:119): every absolute time is UTC and says so. */
export const utc = {
  /** "hh:mm:ss" */
  hms: (ms: number): string => {
    const d = new Date(ms);
    return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`;
  },
  /** "hh:mm" */
  hm: (ms: number): string => {
    const d = new Date(ms);
    return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
  },
  /** "yyyy-mm-dd" */
  date: (ms: number): string => new Date(ms).toISOString().slice(0, 10),
  /** "yyyy-mm-dd hh:mm" */
  dateHm: (ms: number): string => `${new Date(ms).toISOString().slice(0, 10)} ${utc.hm(ms)}`,
} as const;

/** An id or a count with §1's thousands separators: 1204118 → "1,204,118". */
export const num = (n: number): string =>
  Number.isSafeInteger(n) ? String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",") : String(n);

/** A size in human units (D04 AL-22, DJ): decimal, one place, as the overview's disk lines. */
export function size(bytes: number): string {
  if (bytes < 1_000) return `${bytes} B`;
  const units = ["kB", "MB", "GB", "TB"] as const;
  let value = bytes / 1_000;
  let unit = 0;
  while (value >= 1_000 && unit < units.length - 1) {
    value /= 1_000;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit] ?? "TB"}`;
}

/** "{from}–{to}", an id range with an en dash (`tamper.range_passed`, `rec.verified_to`). */
export const range = (from: number, to: number): string => `${num(from)}–${num(to)}`;

export const AUDIT_COPY = {
  /**
   * E42-D03 §14 `meta.asof`; before the first answer, and after a failed first read, its first
   * part alone (D04 §1).
   */
  meta: {
    none: "All times UTC",
    asOf: (hms: string): string => `All times UTC · as of ${hms}`,
  },
  audit: {
    appendOnly: "Records can only be added, never edited or deleted. Kept indefinitely.",
    marker: "Viewing this log is recorded — Audit log viewed (admin.audit_read)",
    caption: "Audit log, newest first. All times UTC. Role at the time is not recorded yet.",
    slow: "Taking longer than usual…",
    noMatch: "No records match these filters.",
    ownOnly: "Showing your actions only",
    ownNoMatch: "No actions by you match these filters.",
    ownFilter: "That filter isn't available in your view.",
    /** `{ENV}` the environment in capitals: "LIVE (this page only)". */
    envPage: (env: string): string => `${env.toUpperCase()} (this page only)`,
    /** The pill (D5); at the cap (`NEW_CAP`, a page's 200 rows) "200+". */
    newN: (n: number, capped: boolean): string =>
      capped
        ? "200+ new entries — show newest"
        : n === 1
          ? "1 new entry — show newest"
          : `${num(n)} new entries — show newest`,
    /** The deck gives the plural; the singular is PROPOSED (owner E42-D04). */
    newLoaded: (n: number): string =>
      n === 1 ? "1 new entry loaded" : `${num(n)} new entries loaded`,
    /** AL-6: the rows shown after the Environment facet, never a total (D4). */
    count: (n: number): string =>
      n === 1 ? "1 entry on this page" : `${num(n)} entries on this page`,
    resultStarted: "Started",
    resultIntent: "Intent",
    /** AL-9, and `admin.oldest`'s node: the unfiltered form when no filter is set. */
    end: (filtered: boolean): string =>
      filtered ? "No older entries match these filters." : "No older entries.",
    /** Then [Newest] (`labels.page.newest`). */
    cursorLost: "This page can't be continued. Start again from the newest entries.",
    /**
     * Then [Retry] (`labels.act.retry`). Without a `Retry-After` (no answer, or none sent) the deck
     * has no time to give: that form is PROPOSED (owner E42-D04).
     */
    error: (hms: string | null): string =>
      hms === null
        ? "Couldn't load the audit log — the query took too long or the store is unavailable. Try a shorter time range, or try again."
        : `Couldn't load the audit log — the query took too long or the store is unavailable. Try a shorter time range, or try again at ${hms} UTC.`,
    limited: (hms: string, seconds: number): string =>
      `Too many requests — try again at ${hms} UTC (in ${seconds} s). Run tamper check and opening records still work.`,
    /**
     * PROPOSED (owner E42-D04): after a `429` on a first or filter read, once `Retry-After` has
     * passed; then [Retry] (`labels.act.retry`). AL-16 sends nothing by itself (C-1135P2-04).
     */
    limitEnded: "The rate limit has passed — nothing was loaded. Retry to load these entries.",
    errRange: "From must be earlier than To.",
    errIp: "Enter one IP address, not a range.",
    /**
     * PROPOSED (owner E42-D04): a `422` on a filter §14 gives no line for (D04 keys only `to` and
     * `ip`, AL-17); the server names the field and the rule, never the value.
     */
    errValue: "This filter's value isn't accepted.",
  },
  tamper: {
    pagePassed: "Tamper check: this page checked — passed",
    pagePartial: "Tamper check: this page could not be fully checked — run a tamper check",
    pagePartialOwn: "Tamper check: this page could not be fully checked.",
    newestPartial: "The newest entries could not be fully checked — run a tamper check",
    incidentsUnavailable: "Tamper status: incident log unavailable",
    checking: "Checking entries…",
    rangePassed: (fromTo: string, hm: string): string =>
      `Tamper check: entries ${fromTo} checked at ${hm} UTC — passed. This covers that range only.`,
    rangeEmpty: "No entries in that range — nothing was checked.",
    busy: "A tamper check is already running. Try again when it ends.",
    limited: (hm: string): string => `Too many tamper checks this hour — try again at ${hm} UTC.`,
    stopped: (hms: string): string =>
      `The check didn't finish — nothing was verified. Try again at ${hms} UTC.`,
    stoppedEntry:
      "The check stopped at a record too large to check — nothing was verified. Checking this range again stops there too; tell security.",
    /** PROPOSED (owner E42-D04): a check that got no answer may have run, so it claims neither. */
    noAnswer: "No answer from the tamper check — its result is unknown. Run it again to see one.",
    /** PROPOSED (owner E42-D04): any other refusal of the check. */
    notRun: "The tamper check didn't run — nothing was verified.",
    failed: {
      title: (n: string): string =>
        `Tamper check FAILED at entry ${n} — treat this as a security incident`,
      /** PROPOSED (owner E42-D04): a break whose entry no served field names. */
      titleUnknown: "Tamper check FAILED — treat this as a security incident",
      facts: (hms: string, date: string, fromTo: string): string =>
        `Found at ${hms} UTC on ${date} in a check of entries ${fromTo}.`,
      /** PROPOSED (owner E42-D04): an incident serves its first time, never a checked range. */
      factsIncident: (hms: string, date: string): string => `Found at ${hms} UTC on ${date}.`,
      meaning:
        "Each record is linked to the one before it, so a change or gap shows here. The links are not keyed: someone with database access could also have rewritten earlier records consistently, so treat the whole log as unverified until security has compared it with an independent copy.",
      safe: "Native stop-losses are unaffected. A break does not stop order entry by itself: decide now whether to engage the kill switch (FREEZE…).",
      /**
       * PROPOSED (BQ-5 as overridden; a Deferred A-row to E42-D04 §7, whose `safe` is stale
       * against `04` §8.1 "Enforced posture"): `safe`'s place while the served
       * `audit_chain_break` incident is `open`, the halt #2904 engages; acknowledging lifts it
       * (`22` `acknowledgeAuditChainBreak`).
       */
      halted:
        "Native stop-losses are unaffected. New orders that open or add to a position are halted until the owner acknowledges this break; cancel, close and stop-tightening still work. Decide now whether also to engage the kill switch (FREEZE…).",
      /**
       * PROPOSED (BQ-5's owner, an A-row to E42-D04 §7): `safe`'s place while a run found a break
       * and no incident is served: the verify route halts on its own, so the halt may stand even
       * when the incident's write or its read failed (C-1135P2-08).
       */
      mayBeHalted:
        "Native stop-losses are unaffected. New orders that open or add to a position may be halted until the owner acknowledges this break; cancel, close and stop-tightening still work. Decide now whether to engage the kill switch (FREEZE…).",
      recheck: "A new check finds the same break until the chain is restored.",
      steps:
        "Don't change or delete anything in the database. Snapshot it, find the first broken link in the verifier log and escalate it as a security incident (SECURITY.md). Tell the security reviewer now.",
      copy: "Copy details",
    },
  },
  export: {
    dlgTitle: "Export the audit log",
    dlgBody: (from: string, to: string): string =>
      `A signed file (NDJSON and its signature) of every entry from ${from} to ${to} UTC, with the neighbouring entries that link them — not just the rows on screen. Filters don't apply.`,
    dlgPii: "The file holds personal data (actor IP addresses).",
    dlgRange: "Choose at most 31 days.",
    dlgStarting: "Starting the export…",
    notBuilt: "Export isn't built yet. Nothing was exported or recorded.",
    /** `{n}` absent before the first `progress_pct`: never "0 %" (D02 D4). */
    running: (pct: number | null, id8: string): string =>
      pct === null
        ? `Preparing the export… · job ${id8}`
        : `Preparing the export… ${Math.floor(pct)} % · job ${id8}`,
    pollFailed: "Can't check the export right now — retrying.",
    /** `export.ready`, in its parts: the [Copy] follows `digest`, the [Download] `deleted`. */
    ready: {
      lead: (rows: string, from: string, to: string, bytes: string): string =>
        `Export ready — ${rows} entries (the chain span for ${from} to ${to} UTC), ${bytes}`,
      digest: (hex8: string): string => `sha256 ${hex8}…`,
      key: (keyId: string): string => `key ${keyId}`,
      deleted: (at: string): string => `deleted at ${at} UTC`,
    },
    trust:
      "Verify the signature only with the full key fingerprint you saved from the record of a key rotation you performed, or of the first key's generation — never with the key id or a key served next to the file.",
    fail: {
      export_too_large: "Too many entries for one file — choose a shorter window.",
      signing_key_rotated: "The signing key changed while the file was made — export again.",
      signing_unavailable: "Signing isn't available — nothing was exported.",
      audit_unavailable: "The export couldn't be recorded, so it wasn't made.",
      internal_error: "The export failed — export again.",
    } as Readonly<Record<string, string>>,
    cancelled: "The export was cancelled.",
    lost: "This export's status is no longer available — start a new export.",
    expired: (at: string): string => `The export expired at ${at} UTC and its file was deleted.`,
    limited: (hm: string): string => `Too many downloads this hour — try again at ${hm} UTC.`,
    downloadFailed: "Couldn't start the download — nothing was sent. Try again.",
    /** Then [Check again] (`labels.act.check_again`). */
    unknown: "We couldn't tell whether the export started.",
    refused: {
      range: (days: string): string => `That window is longer than ${days} days.`,
      busy: "An export or a signing-key change is already running.",
      rate: (hm: string): string => `Too many exports this hour — try again at ${hm} UTC.`,
      signing: "Signing isn't available right now — nothing was started.",
      store: "The export couldn't be recorded, so nothing was started.",
      /** PROPOSED (owner E42-D04): any other refusal of the start (X3 lists none). */
      other: "The export wasn't started — nothing was exported.",
    },
    notSent: "Not sent.",
    /**
     * E42-D03 §14's step-up line, by reference: D04 §8's static line, as `Me` serves no grace
     * per class (D03 CG-2), so the live "Still trusted for {class}" form is never shown here.
     */
    stepUpLine: "You'll confirm with your password and a code.",
  },
  rec: {
    immutable: "This record cannot be edited or deleted.",
    role: "Role at the time: not recorded",
    agentNone: "User agent: not recorded",
    chain: "Each record is linked to the one before it.",
    verifiedTo: (fromTo: string, hm: string): string =>
      `In entries ${fromTo}, checked at ${hm} UTC — passed (last tamper check).`,
    notChecked: "No tamper check this session covers this record.",
    afterBreak: (n: string): string => `Not verified — at or after the break at entry ${n}.`,
    correlationNone: "Linked records can't be listed yet.",
    relatedActor: "This actor's entries",
    relatedSubject: "This subject's entries",
    relatedTime: "Entries around this time",
    reasonCode: "Reason code",
    reasonGiven: "Reason given",
    rawFlagged:
      "This record holds a value under a secret-named field — report it to security (SR-069).",
    hidden: "not shown in your view",
    /** CG-33: the read-time pseudonym; the grid cuts it to 4 hex and "…". */
    deletedUser: (hex12: string): string => `deleted-user-${hex12}`,
    rawShow: "Show raw record",
  },
  /** T2 reasons (§12.1), D03's D26 vocabulary, each ≤ 60 characters (D09:85). */
  admin: {
    rateLimited: "Paused by a rate limit.",
    newest: "Already at the start of the list.",
    /** `admin.oldest` is `audit.end`'s line: one node. */
    oldest: (filtered: boolean): string =>
      filtered ? "No older entries match these filters." : "No older entries.",
    pageEdge: "No more records in the loaded page.",
    exportNotBuilt: "Export isn't built yet.",
  },
  /** E09-D09 §11 (by reference): refusals at the point of action. */
  inflight: {
    readOnly: "Not sent — read-only after three wrong codes.",
    /** `{reason}` the vocabulary sentence for the code (D09 §4.2). */
    notSent: (reason: string): string => `Not sent — your access changed. ${reason}`.trim(),
  },
  /**
   * `rbac.owner_only`'s `{verb}` on "My activity" (AL-25, AD-7): D09 §3.2's where it has one, the
   * rest PROPOSED as amendments to E09-D09 §3.2 by A-row (`32` G-T2.4; the orchestrator's BQ-13).
   * A Manager's Actor, IP, Search and Environment are T2 and never sent (BQ-3).
   */
  ownerOnlyVerbs: {
    actor: "see other users' entries",
    ip: "filter by IP address",
    q: "search the audit log",
    environment: "filter by environment",
    export: "export the audit log",
    check: "run a tamper check",
    raw: "see raw records",
  },
  /** `labels.*`: the anatomy strings §4–§8 write (D04 §14), keyed so no screen writes its own. */
  labels: {
    col: {
      time: "Time",
      actor: "Actor",
      role: "Role",
      action: "Action",
      target: "Target",
      environment: "Environment",
      ip: "IP",
      severity: "Severity",
      result: "Result",
    },
    filter: {
      from: "From",
      to: "To",
      utc: "UTC",
      actor: "Actor",
      action: "Action",
      subject: "Subject",
      outcome: "Outcome",
      severity: "Severity",
      ip: "IP",
      search: "Search",
      environment: "Environment",
      clear: "Clear filters",
    },
    page: { newest: "Newest", newer: "Newer", older: "Older", previous: "Previous", next: "Next" },
    act: {
      signedExport: "Signed export…",
      runTamperCheck: "Run tamper check",
      export: "Export",
      cancel: "Cancel",
      copy: "Copy",
      close: "Close",
      download: "Download",
      securityCentre: "Security centre",
      incidentLog: "Incident log",
      whatToDo: "What to do now",
      /** `audit.error`'s [Retry]. */
      retry: "Retry",
      /** `export.unknown`'s [Check again]. */
      checkAgain: "Check again",
    },
    field: { compress: "Compress (gzip)" },
    /**
     * SCR-136's row terms §5 draws without a key, each Copy named "Copy {term}": PROPOSED (owner
     * E42-D04), but "User agent", AD-7's own word for its row.
     */
    term: {
      session: "Session",
      userAgent: "User agent",
      requestId: "Request id",
      entryHash: "Entry hash",
      prevHash: "Previous hash",
    },
    word: {
      critical: "Critical",
      error: "Error",
      warning: "Warning",
      info: "Info",
      debug: "Debug",
      success: "Success",
      failure: "Failure",
      denied: "Denied",
      on: "ON",
      off: "OFF",
      none: "—",
      notRecorded: "not recorded",
      you: "you",
    },
    h: {
      auditLog: "Audit log",
      myActivity: "My activity",
      record: (id: string): string => `Record ${id}`,
      who: "Who",
      what: "What",
      beforeAfter: "Before / after",
      request: "Request",
      related: "Related",
      integrity: "Integrity",
      raw: "Raw record",
    },
  },
} as const;
