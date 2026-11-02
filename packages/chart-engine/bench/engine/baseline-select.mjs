#!/usr/bin/env node
// E11-T06 PR-2: picks the real-engine baseline for this runner class, behind the pending switch.
//
//   node bench/engine/baseline-select.mjs --dir bench/engine/baselines --mode gpu|fallback \
//        [--enforce] [--output "$GITHUB_OUTPUT"]
//
// One file per runner class (`chromium-gpu.json`, `chromium-hosted.json`); a run is never compared
// with another class's file. `PENDING.md` is the switch: with it and no baseline file, every route
// records only. It fails closed: PENDING.md next to any baseline file fails the run (the baseline
// PR deletes it), and an enforced run with no switch and no file for its class fails too.
import { appendFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const PENDING_FILE = "PENDING.md";
/** The route job's mode (gpu_runner_health.py) to the runner class a baseline belongs to. */
export const RUNNER_CLASS = Object.freeze({ gpu: "gpu", fallback: "hosted" });
/** `<runtime>-<class>.json` (baselines/PENDING.md): any runtime's file trips the switch. */
export const BASELINE_RE = /^[a-z0-9]+-(gpu|hosted)\.json$/;

/**
 * @param {string[]} files the baseline directory's entries
 * @returns {{ baseline: string | null, pending: boolean, error: string | null }}
 */
export function selectBaseline(files, mode, enforce = false) {
  const cls = Object.hasOwn(RUNNER_CLASS, mode) ? RUNNER_CLASS[mode] : null;
  if (!cls) return { baseline: null, pending: false, error: `unknown route mode '${mode}'` };
  const baselines = files.filter((f) => BASELINE_RE.test(f)).sort();
  const pending = files.includes(PENDING_FILE);
  if (pending && baselines.length)
    return {
      baseline: null,
      pending,
      error: `${PENDING_FILE} is still present next to ${baselines.join(", ")}: delete the switch in the baseline PR (fails closed)`,
    };
  if (pending) return { baseline: null, pending, error: null };
  const own = `chromium-${cls}.json`;
  if (baselines.includes(own)) return { baseline: own, pending, error: null };
  return enforce
    ? {
        baseline: null,
        pending,
        error: `no ${own} for the ${cls} runner class and no ${PENDING_FILE}: an enforced run never passes without its baseline (fails closed)`,
      }
    : { baseline: null, pending, error: null };
}

/** CLI body; returns the exit code. */
export function run(argv, io = { log: console.log, error: console.error, append: appendFileSync }) {
  const get = (flag) => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const dir = get("--dir");
  const mode = get("--mode");
  if (!dir || !mode) {
    io.error("usage: baseline-select.mjs --dir <d> --mode gpu|fallback [--enforce] [--output <f>]");
    return 2;
  }
  const files = existsSync(dir) ? readdirSync(dir) : [];
  const r = selectBaseline(files, mode, argv.includes("--enforce"));
  if (r.error) {
    io.error(`::error title=engine-bench baseline::CI-BEN-002: ${r.error}`);
    return 1;
  }
  const path = r.baseline ? join(dir, r.baseline) : "";
  io.log(
    r.pending
      ? `baseline pending (${PENDING_FILE}): recorded, not compared`
      : `baseline: ${path || "none for this runner class (recorded only)"}`,
  );
  const out = get("--output");
  if (out) io.append(out, `baseline=${path}\npending=${r.pending}\n`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(run(process.argv.slice(2)));
}
