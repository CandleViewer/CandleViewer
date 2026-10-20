/* The E17-Q03 protocol client: one WebSocket connection that behaves as the web client does
 * (apps/web/src/lib/ws), not a socket that ignores what it receives (ticket, technical notes).
 *
 * hello -> auth -> sub (frames of at most 50 topics); a `ping` from the server is answered at once
 * (a W5 cohort delays only the `s-rtt-*` probes); the idle `ping` goes out at the welcome's interval;
 * the token is renewed in place (`POST /auth/refresh`, then `auth` on the same socket) a minute
 * before it expires. Per stream `(ch)` it tracks `s`: a complete `snap` sets the baseline (a chunk
 * set, `s: null` but the last, is assembled), a `d` must be the next number, and a gap, duplicate or
 * out-of-order frame counts, voids the stream and sends a `resync` (at most 5 a minute per `ch`, as
 * resyncGuard.ts). Every data frame is decoded (CVWB through the hand-ported decoder), so decode
 * cost is counted; "decode-complete" is `Date.now()` after it, which stands in for paint (no paint is
 * measured, the report says so). Only `cv.v1.json` is spoken, the one subprotocol the web client offers.
 */
/* global console, setTimeout, setInterval, clearTimeout, clearInterval */
import { WebSocket } from "k6/websockets";
import http from "k6/http";
import encoding from "k6/encoding";
import { decode, stats as cvwbStats } from "./cvwb.js";
import { M, SNAP_REASONS } from "./measure.js";

const CAPABILITIES = [
  "binary_book",
  "binary_bars",
  "binary_trades",
  "binary_footprint",
  "binary_heatmap",
  "coalescing",
  "replay",
  "partial_snapshots",
];
const SUB_BATCH = 50;
const RESYNC_LIMIT = 5;
const RESYNC_HORIZON_MS = 61000;
const WINDOW_MS = 60000;
const SNAP_FAMILIES = ["book", "trades", "bars"];
const JSON_HEADERS = { headers: { "Content-Type": "application/json" } };

export class Connection {
  /** cfg: id, url, base, origin, subprotocol, tokens {access, refresh}, topics, clock, role ('conn'|'probe'),
   *  rttDelayMs, reauthAfterS, probeEveryS, refSymbol, traceSp */
  constructor(cfg) {
    this.cfg = cfg;
    this.clock = cfg.clock;
    this.tokens = { ...cfg.tokens };
    this.streams = new Map();
    for (const t of cfg.topics) {
      this.streams.set(t.ch, {
        fam: t.fam,
        last: null,
        state: "pending",
        chunks: 0,
        desyncs: 0,
        resyncs: [],
        prevTs: null,
        ref: t.symbol === cfg.refSymbol,
      });
    }
    this.seq = 0;
    this.planned = false;
    this.timers = [];
    this.window = 0;
    this.round = null;
    this.expiresAt = 0;
    this.phase = "hello";
  }

  start() {
    const c = this.cfg;
    this.ws = new WebSocket(c.url, [c.subprotocol], {
      headers: { Origin: c.origin },
      compression: "deflate",
    });
    this.ws.binaryType = "arraybuffer";
    this.ws.addEventListener("open", () => this.onOpen());
    this.ws.addEventListener("message", (e) => this.onMessage(e));
    this.ws.addEventListener("close", (e) => this.onClose(e));
    this.ws.addEventListener("error", (e) => {
      M.errors.add(1);
      console.error(`vu ${c.id}: socket error ${e.error}`);
    });
    this.every(100, () => this.lagTick());
    this.after(Math.max(0, this.clock.endAt - Date.now()), () => this.finish());
    this.after(Math.max(0, this.clock.steadyAt - Date.now()), () => {
      this.window = 0;
      this.every(WINDOW_MS, () => this.flushWindow());
    });
  }

  // -- timers: every one is tracked, so the iteration ends when the socket does ----------------
  every(ms, fn) {
    this.timers.push(setInterval(fn, ms));
  }
  after(ms, fn) {
    this.timers.push(setTimeout(fn, ms));
  }
  clearTimers() {
    this.timers.forEach((t) => {
      clearInterval(t);
      clearTimeout(t);
    });
    this.timers = [];
  }

  nextId() {
    return `c-${++this.seq}`;
  }
  send(t, p, extra) {
    if (this.ws.readyState !== 1) return;
    this.ws.send(JSON.stringify({ t, id: this.nextId(), ...extra, p }));
  }

  onOpen() {
    if (this.ws.protocol !== this.cfg.subprotocol) {
      M.errors.add(1);
      console.error(
        `vu ${this.cfg.id}: negotiated "${this.ws.protocol}", offered ${this.cfg.subprotocol}`,
      );
    }
    this.send("hello", {
      client: "candleviewer-k6",
      client_version: "e17-q03/1",
      shell: "other",
      protocol: "cv.v1",
      encodings: ["binary", "structured"],
      capabilities: CAPABILITIES,
      locale: "en-GB",
      clock_ms: Date.now(),
    });
  }

  onMessage(e) {
    const raw = e.data;
    if (typeof raw !== "string") {
      M.errors.add(1);
      return;
    }
    const m = JSON.parse(raw);
    switch (m.t) {
      case "snap":
      case "d":
        this.data(m, raw.length);
        break;
      case "ping":
        this.pong(m);
        break;
      case "welcome":
        this.welcome(m);
        break;
      case "auth_ok":
        this.authOk(m);
        break;
      case "sub_ok":
        this.subOk(m);
        break;
      case "unsub_ok":
        this.unsubOk();
        break;
      case "err":
        this.err(m);
        break;
      case "bye":
        console.warn(`vu ${this.cfg.id}: bye ${m.p && m.p.reason}`);
        if (m.p && /^auth/.test(m.p.reason)) M.authFailures.add(1);
        break;
      case "revoked":
        M.errors.add(1);
        console.error(`vu ${this.cfg.id}: revoked ${JSON.stringify(m.p)}`);
        break;
      default:
        break; // pong, permission_change, ctl_ok: nothing to do
    }
  }

  // -- control frames -------------------------------------------------------------------------
  welcome(m) {
    M.clockSkew.add(Math.abs(m.p.clock_skew_ms));
    if (m.p.encoding !== "json") {
      M.errors.add(1);
      console.error(`vu ${this.cfg.id}: welcome.encoding ${m.p.encoding}`);
    }
    this.every(m.p.heartbeat.interval_ms, () => this.send("ping", { client_ms: Date.now() }));
    this.phase = "auth";
    this.send("auth", { access_token: this.tokens.access });
  }

  authOk(m) {
    this.expiresAt = m.p.token_expires_at_ms;
    const wait =
      this.cfg.reauthAfterS > 0
        ? this.cfg.reauthAfterS * 1000
        : Math.max(1000, this.expiresAt - Date.now() - 60000);
    this.after(wait, () => this.reauth());
    if (this.phase === "auth") {
      this.phase = "live";
      M.connectionsUp.add(1);
      this.subscribe();
    } else {
      M.reauthOk.add(1);
    }
  }

  /** In place: a new access token from the refresh double, then `auth` on this socket (4.3). */
  reauth() {
    const r = http.post(
      `${this.cfg.base}/auth/refresh`,
      JSON.stringify({ refresh_token: this.tokens.refresh }),
      JSON_HEADERS,
    );
    if (r.status !== 200) {
      M.authFailures.add(1);
      console.error(`vu ${this.cfg.id}: refresh ${r.status}`);
      return;
    }
    const body = r.json();
    this.tokens = { access: body.access_token, refresh: body.refresh_token };
    this.send("auth", { access_token: this.tokens.access });
  }

  subscribe() {
    const topics = this.cfg.topics.map((t) =>
      Object.keys(t.opts).length ? { ch: t.ch, opts: t.opts } : { ch: t.ch },
    );
    if (this.cfg.role === "probe")
      this.round = {
        start: Date.now(),
        bytes: 0,
        need: new Set(
          this.cfg.topics.filter((t) => SNAP_FAMILIES.includes(t.fam)).map((t) => t.ch),
        ),
      };
    for (let i = 0; i < topics.length; i += SUB_BATCH)
      this.send("sub", { topics: topics.slice(i, i + SUB_BATCH) });
  }

  subOk(m) {
    for (const r of m.p.results) {
      if (!r.ok) {
        M.subRefused.add(1);
        console.error(`vu ${this.cfg.id}: ${r.ch} refused ${r.error && r.error.code}`);
      }
    }
  }

  unsubOk() {
    if (this.cfg.role !== "probe") return;
    for (const st of this.streams.values()) {
      st.last = null;
      st.state = "pending";
      st.chunks = 0;
    }
    const again = this.cfg.probeEveryS * 1000;
    if (Date.now() + again < this.clock.endAt - 5000) this.after(again, () => this.subscribe());
  }

  err(m) {
    M.errors.add(1);
    const code = m.p && m.p.code;
    if (code === "auth_failed") M.authFailures.add(1);
    console.error(`vu ${this.cfg.id}: err ${code} ${m.ch || ""}`);
  }

  pong(m) {
    const reply = () => this.send("pong", { client_ms: Date.now() }, { id: m.id });
    if (this.cfg.rttDelayMs > 0 && typeof m.id === "string" && m.id.startsWith("s-rtt-"))
      this.after(this.cfg.rttDelayMs, reply);
    else reply();
  }

  // -- data frames ----------------------------------------------------------------------------
  data(m, size) {
    if (m.ch === "system") {
      if (m.p && m.p.kind === "connection_quality" && M.cls[m.p.class]) M.cls[m.p.class].add(1);
      return;
    }
    const st = this.streams.get(m.ch);
    if (st === undefined) {
      M.errors.add(1);
      return;
    }
    let body;
    try {
      body = m.e === "b64" ? decode(encoding.b64decode(m.p)) : null;
    } catch (err) {
      M.errors.add(1);
      console.error(`vu ${this.cfg.id}: ${m.ch} frame ${err.code}: ${err.message}`);
      this.voidStream(m.ch, st, "decode_error");
      return;
    }
    const tDec = Date.now();
    const prevTs = st.prevTs; // the stream's previous release: a window's length is the gap between two
    if (m.t === "snap") this.snap(m, st, tDec, size);
    else if (!this.delta(m, st)) return;
    else st.prevTs = m.ts;
    if (this.cfg.role === "probe") return; // the probe measures re-snapshots, nothing else
    if (this.cfg.traceSp && m.sp)
      console.log(`SP ${JSON.stringify({ sp: m.sp, ch: m.ch, s: m.s, ts: m.ts, t_dec: tDec })}`);
    if (st.ref) this.window += size;
    if (!this.clock.steady()) return;
    if (m.sp) M.spFrames.add(1);
    M.bytes[st.fam].add(size);
    M.frames[st.fam].add(1);
    if (m.t === "d") {
      M.release[st.fam].add(tDec - m.ts);
      if (st.fam === "trades") M.tickTrades.add(tDec - oldestPrint(m, body));
      else if (st.ref && prevTs !== null && M.hold[st.fam]) M.hold[st.fam].add(m.ts - prevTs);
    }
  }

  /** A complete `snap` (a chunk set ends at the one carrying `s`) sets the baseline. */
  snap(m, st, tDec, size) {
    if (this.round !== null && this.round.need.has(m.ch)) {
      this.round.bytes += size;
      if (m.s !== null) this.round.need.delete(m.ch);
      if (this.round.need.size === 0) this.endRound(tDec);
    }
    if (m.s === null || m.s === undefined) {
      st.chunks++;
      return;
    }
    st.chunks = 0;
    st.last = m.s;
    st.prevTs = null;
    st.state = "live";
    const reason = (m.meta && m.meta.reason) || "initial";
    M.snap[SNAP_REASONS.includes(reason) ? reason : "other"].add(1);
    if (reason === "upstream_desync") st.desyncs++;
  }

  /** True when the delta applies; a gap voids the stream until its next `snap`. */
  delta(m, st) {
    if (st.state !== "live") return false; // no baseline: never applied, as the web client
    if (m.s === st.last + 1) {
      st.last = m.s;
      return true;
    }
    M.gaps.add(1);
    console.error(`vu ${this.cfg.id}: ${m.ch} gap: last ${st.last}, got ${m.s}`);
    this.voidStream(m.ch, st, "sequence_gap");
    return false;
  }

  voidStream(ch, st, reason) {
    const last = st.last;
    st.state = "resyncing";
    const now = Date.now();
    st.resyncs = st.resyncs.filter((at) => now - at < RESYNC_HORIZON_MS);
    if (st.resyncs.length >= RESYNC_LIMIT) return; // the gateway would revoke it: never sent early
    st.resyncs.push(now);
    M.resyncsSent.add(1);
    this.send("resync", { last_seq: last, reason }, { ch });
  }

  endRound(tDec) {
    const r = this.round;
    this.round = null;
    if (r.start >= this.clock.steadyAt) {
      M.resnapKib.add(r.bytes / 1024);
      M.resnapMs.add(tDec - r.start);
    }
    this.send("unsub", { topics: this.cfg.topics.map((t) => t.ch) });
  }

  // -- windows, lag, end ----------------------------------------------------------------------
  flushWindow() {
    M.rwKibS.add(this.window / 1024 / (WINDOW_MS / 1000));
    this.window = 0;
  }

  lagTick() {
    const now = Date.now();
    if (this.lastTick !== undefined && this.clock.steady())
      M.clientLag.add(Math.max(0, now - this.lastTick - 100));
    this.lastTick = now;
  }

  finish() {
    this.planned = true;
    for (const st of this.streams.values()) if (st.desyncs > 0) M.desyncPerCh.add(st.desyncs);
    M.imprecise.add(cvwbStats.imprecise);
    this.ws.close(1000);
  }

  onClose(e) {
    this.clearTimers();
    if (!this.planned) {
      M.unplannedCloses.add(1);
      console.error(`vu ${this.cfg.id}: closed by the server, code ${e.code}`);
    }
  }
}

/** The oldest print's feeder-stamped time in a trades frame (binary or structured). */
function oldestPrint(m, body) {
  if (body !== null) {
    let min = Infinity;
    for (const r of body.records) if (r[0] < min) min = r[0];
    return body.tsBase + (min === Infinity ? 0 : min);
  }
  return m.p.trades.length ? m.p.trades[0].ts_ms : Date.now();
}
