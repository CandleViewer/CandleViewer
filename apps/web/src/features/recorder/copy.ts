/**
 * SCR-140's copy (E16-S01), verbatim. A placeholder is its parent's own token ("{symbol}",
 * "{warn − 5}", "`<code>`") and `fill` replaces it; nothing here is composed from a server
 * `message` or `detail` (E16-D06 §20.3).
 *
 * `DECK` is the rows of `docs/design/E16/E16-D06-copy.json` this page shows, under the deck's keys:
 * E16-D02 §8 (`d02.8.rNN`, and the five `recorder.*` T2 reasons, PROPOSED by D02 §8.5 for E09-D09
 * §3.1, Q-03) and E16-D04 §14's `storage.purge.*` / `storage.compact.*` (SCR-142 reuses D02 §6.5
 * whole). A row is its parent's quoted strings in order, a template before its example; the deck
 * joins them with " · " and a test holds every row to it. `TEXT` is E16-D02 §3, §4.1 and §6, which
 * the deck does not key (its D02 part is §8 alone). Add a row only with its source.
 */
export const DECK = {
  "d02.8.r01": ["60 s", "30 min", "1 h 30 min"],
  "d02.8.r02": ["Recorder"],
  "d02.8.r03": [
    "Nothing is recorded by default. A symbol is recorded only while you have added it here, its chart has been open for {dwell}, it has an open position, or a rule or alert depends on it. Auto-recorded symbols stop {grace} after the last reason ends. Live price and order-book views work without recording; history, sub-minute bars and replay need it.",
  ],
  "d02.8.r04": [
    "Auto-record on chart open is on.",
    "Auto-record on chart open is off on this server; positions, rules, alerts and symbols you add still record.",
  ],
  "d02.8.r05": ["Nothing is recorded yet"],
  "d02.8.r06": [
    "Add a symbol to keep its trades, order book, tickers and liquidations for replay, footprint history and the journal.",
  ],
  "d02.8.r07": ["Record a symbol"],
  "d02.8.r08": ["Manual", "Auto: chart", "Auto: position", "Auto: rule", "Auto: alert"],
  "d02.8.r09": ["Recording · stops in {n} min", "stops in under a minute"],
  "d02.8.r10": [
    "Recording {n} symbols · {m} auto-recorded · Recorder {healthy|degraded|warning|down}",
    "· 1 starting",
    "updated {hh:mm:ss} UTC",
  ],
  "d02.8.r11": [
    "Growing · auto-record pauses in about {d} days",
    "{used} of {cap} ({pct} %)",
    "Projection: ({autostop} % × {cap} − {used}) ÷ {growth}/day ≈ {d} days. Growth: 7-day trend. In 30 days: about {used30}.",
  ],
  "d02.8.r12": [
    "Steady · usage is not growing",
    "Usage is not growing, so there is no projection.",
  ],
  "d02.8.r13": ["Too early to project", "Less than 1 h of history."],
  "d02.8.r14": [
    "Growing · the budget is full in about {d} days",
    "the disk volume is full in about {d} days",
  ],
  "d02.8.r15": [
    "Near limit · auto-record pauses in about {d} days · clears below {warn − 5} %",
    "Recording budget {pct} % used ({used} of {cap}). It clears once usage is below {warn − 5} % and the runway is more than 8 days.",
  ],
  "d02.8.r16": [
    "Auto-record paused · resumes below {autostop − 5} % of the budget with 20 % of the volume free",
    "Recording budget {pct} % used ({used} of {cap}). New chart-open symbols are not recorded; symbols you added, open positions, rules and alerts keep recording. Recording stops at {halt} % in about {d} days.",
    "Auto-record paused · the disk volume has less than 15 % free",
  ],
  "d02.8.r17": [
    "Recording stopped · resumes below {halt − 5} % with 10 % of the volume free",
    "Open positions keep recording; other symbols' data is dropped and recorded as gaps.",
  ],
  "d02.8.r18": ["Nothing recorded", "0 GB of {cap}."],
  "d02.8.r19": [
    "{warn} % warning · {autostop} % auto-record pauses · {halt} % recording stops (open positions keep writing)",
    "Shorten retention",
    "Reduce depth",
    "Unpin",
  ],
  "recorder.stop_blocked.chart_auto": ["Recording stops {grace} after the last chart closes."],
  "recorder.stop_blocked.chart_manual": ["Stop is available once the last chart closes."],
  "recorder.stop_blocked.position_auto": ["Recording continues while a position is open."],
  "recorder.stop_blocked.position_manual": ["Stop is unavailable while a position is open."],
  "recorder.symbol_cap": ["The symbol limit is reached."],
  // D04 §14: `storage.compact.{button,title,body}` and the purge's `before.help`, `before.reason`,
  // `refused.*` and `typed.reason` are D04's PROPOSED rows; the rest are merged (the deck's `status`).
  "storage.compact.button": ["Compact Parquet…"],
  "storage.compact.title": ["Compact Parquet partitions?"],
  "storage.compact.body": [
    "Merges small files into partitions of at most 512 MiB. Nothing is deleted. Replay is paused on partitions it touches.",
  ],
  "storage.compact.succeeded": ["Compacted at {HH:MM} UTC", "Compacted at 10:42 UTC"],
  "storage.compact.failed": ["Compaction failed (`<code>`); nothing was deleted."],
  "storage.compact.cancelled": ["Compaction cancelled; nothing was deleted."],
  "storage.compact.unknown": ["Compaction status is no longer available on the server."],
  "storage.purge.button": ["Purge data…", "Purge…"],
  "storage.purge.title": ["Purge {symbol} data?", "Purge ETHUSDT data?"],
  "storage.purge.body": [
    "This deletes about {size} recorded from {from} to {to} from QuestDB and Parquet. It cannot be undone, and replay, footprint history and the journal lose this range. Shared QuestDB day partitions are freed by the nightly roll-off.",
  ],
  "storage.purge.before": ["Delete data recorded before"],
  "storage.purge.before.help": ["Data recorded at or after this time is kept."],
  "storage.purge.before.reason": ["Choose a time no later than now."],
  "storage.purge.refused.before": [
    "Not started: the time is later than the server's ({server_time}). Choose a time at or before it.",
    "Not started: the time is later than the server's (2026-09-14 10:31:03 UTC). Choose a time at or before it.",
  ],
  "storage.purge.typed": ["Type the symbol to confirm"],
  "storage.purge.typed.reason": [
    "Type {symbol} exactly to confirm.",
    "Type ETHUSDT exactly to confirm.",
  ],
  "storage.purge.stepup": ["You'll confirm with your password and a code."],
  "storage.purge.stepup.trusted": ["Still trusted for recorder changes · {mm:ss}"],
  "storage.purge.audited": ["This action is audited (high severity)."],
  "storage.purge.confirm": ["Purge {symbol} data", "Purge ETHUSDT data"],
  "storage.purge.refused.pinned": [
    "Pinned data is excluded. Tick Include pinned to delete it too.",
  ],
  "storage.purge.refused.audit": ["Not started: the audit record could not be written."],
  "storage.purge.failed": [
    "Purge of {symbol} failed (`<code>`). Some data may already be deleted: check {symbol}'s size and gaps.",
  ],
  "storage.purge.cancelled": [
    "Purge of {symbol} was cancelled. Data deleted before the cancel is gone.",
  ],
  "storage.purge.unknown": [
    "The purge's status is no longer available on the server. Check {symbol}'s size and gaps.",
  ],
  "storage.purge.succeeded": ["Purged {size} of {symbol} data", "Purged 1.2 GB of ETHUSDT data"],
} as const satisfies Readonly<Record<string, readonly string[]>>;

export type DeckKey = keyof typeof DECK;

/** E16-D02's strings the deck does not key, as templates of the parent's examples. */
export const TEXT = {
  /**
   * §4.1's state words: the batch says them (SR-01), #484 PR 3's row detail with a stop's date and the
   * gaps; a grid row draws CMP-177's own copy of them. The lingering words are the deck's (`d02.8.r09`).
   */
  words: {
    recording: "Recording",
    position: "Recording · position",
    positionOpen: "Recording · position open",
    starting: "Starting · initial book snapshot",
    degraded: "Degraded · stream unhealthy",
    gaps: "· {n} gaps in 24 h",
    gated: "Gated · data dropped",
    refusedCap: "Not recording: {limit}-symbol limit reached",
    refusedDisk: "Not recording: disk nearly full",
    silent: "No writes since {hh:mm:ss}",
    error: "Error · retrying",
    stopping: "Stopping · flushing to disk",
    stopped: "Stopped {date}",
    goneBy: "gone by {date}",
    keptForever: "kept forever",
  },
  /** 23 §15.8: a lingering deadline already past reads "stopping", never a negative count. */
  lingerPast: "stopping",
  /** E16-D06 SR-02: the batch's words for a symbol that stopped (§9.3's example). */
  stoppedRecording: "{symbol} stopped recording",
  /** §3 disk critical: the bar's numeric text at level 3. */
  levelThreeMeter: "{pct} % used ({used} of {cap})",
  /** §3 paused: while `accelerate_retention` holds (23 §15.8's 75 % / 25 % release). */
  accelerated:
    "Retention is accelerated until the budget is below 75 % and the volume has 25 % free.",
  levelThree:
    "Recording stopped: the recording budget is {pct} % used ({used} of {cap}). Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording. Free space to resume: purge data, shorten retention or raise the budget.",
  /**
   * PROPOSED (E16-D02's C-8, BQ-10's default; owner E16-D02): §3 words a refused volume as "less
   * than 5 % free", which 22 `getStorageUsage` contradicts (refused at boot), and freeing space
   * cannot resume it; so a neutral cause and no "Free space to resume" sentence.
   */
  levelThreeVolumeRefused:
    "Recording stopped: the recording volume was refused when the server started. Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording.",
  /**
   * PROPOSED (on E16-D02's C-8 row; owner E16-D02; A-5309-04): level 3 held by the volume (24 §13.4.1:
   * under 5 % free), §3's own first sentence for it, and no "raise the budget", which cannot resume it.
   */
  levelThreeVolume:
    "Recording stopped: the disk volume has less than 5 % free. Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording. Free space to resume: purge data or shorten retention.",
  levelThreeActions: ["Purge data…", "Retention policy"],
  incident:
    "Incident: {count} messages were dropped on {symbol} between {from} and {to} UTC. The lost interval is recorded as a gap; charts and replay show it as a gap.",
  /**
   * PROPOSED (owner E16-D02; C-5309-07): the incident before its gap is on record (the coverage read lags
   * or failed), §3's sentence without the interval it cannot name yet.
   */
  incidentOpen:
    "Incident: {count} messages were dropped on {symbol}. The lost interval is recorded as a gap; charts and replay show it as a gap.",
  viewGaps: "View gaps",
  gapsCaption: "Gaps recorded (last 24 h)",
  purgeRunning:
    "Purging {symbol} data recorded before {date}: {pct} %. Recording continues. Deleted data cannot be restored.",
  /** §3.1 */
  statusUnavailable:
    "Recorder status could not be loaded. This page cannot show what is being recorded right now.",
  /** The deck's `storage.unavailable` (E16-D04 §3.1's, which D02 §3.1 shares; a test holds it to the deck). */
  diskUnavailable: "Disk figures could not be loaded.",
  retry: "Retry",
  stale: "Status stale since {hh:mm:ss} UTC",
  staleTag: "stale",
  /** §3.2: the purge failed banner's action. */
  openSymbol: "Open {symbol}",
  /** §6.1 */
  add: {
    symbol: "Symbol",
    streams: "Streams",
    streamNames: ["Trades", "Order-book deltas", "Tickers", "Liquidations", "Klines"],
    depth: "Depth",
    depthHelp: "About 0.5–0.75 GB a day at depth 200: an estimate until an hour of data exists.",
    retention: "Retention",
    keepForever: "Keep forever",
    symbolHelp: "A slot frees when a symbol stops, up to {grace} after its last reason ends.",
    start: "Start recording",
    cancel: "Cancel",
  },
  /** §6.2 ("Keep recording" is the default button). */
  stop: {
    title: "Stop recording {symbol}?",
    body: "{symbol} keeps recording for {grace}, then stops, unless a chart, a position, a rule or an alert needs it. After that its history stops accruing. Existing data is kept per the retention policy ({retention}; forever when pinned) and stays replayable. To delete data, use Purge.",
    keep: "Keep recording",
    confirm: "Stop recording",
  },
  /** §6.4; the step-up lines are the deck's `storage.purge.stepup*`. */
  keepForever: {
    toggle: "Keep {symbol} data forever",
    onTitle: "Keep {symbol} data forever?",
    onBody: "Retention is removed and nothing is deleted automatically. Type {symbol} to confirm.",
    offTitle: "Stop keeping {symbol} forever?",
    offBody:
      "Retention returns to {retention}, so about {size} recorded before {date} becomes eligible for deletion at the next retention run. Type {symbol} to confirm.",
    audited: "This action is audited.",
    notSent: "Not sent",
  },
  /** §6.5; the dialog's other strings are the deck's `storage.purge.*`. */
  purge: {
    symbol: "Symbol",
    reason: "Reason (required, 3–280 characters)",
    includePinned: "Include pinned data",
    pinnedToo: "Pinned data is deleted too.",
    cancel: "Cancel",
    running: "A purge is running.",
  },
  /** §6.6 */
  compact: { button: "Compact now", busy: "Compacting · {pct} %" },
  /** §6.7 */
  detail: {
    label: "{symbol} recording",
    sections: ["Status", "Health", "Cost", "Gaps (last 24 h)"],
    dropped: "{count} messages dropped (incident)",
  },
} as const;

/**
 * Replaces each placeholder token with its value, everywhere it occurs. A token is the parent's
 * literal text ("{d}", "{warn − 5}", "`<code>`"; "{n} symbols" to say "1 symbol").
 */
export function fill(template: string, values: Readonly<Record<string, string | number>>): string {
  return Object.entries(values).reduce(
    // A function replacer: the value goes in as written, never read as a `$&`, `$1` or `$$` pattern.
    (out, [token, value]) => out.replaceAll(token, () => `${value}`),
    template,
  );
}
