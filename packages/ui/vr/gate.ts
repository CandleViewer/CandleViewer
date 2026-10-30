/**
 * The `vr:update` gate (E05-T04): new baselines are never written implicitly in CI. Two checks, one rule:
 * the config calls `assertUpdateAllowed` on the command line before any test, for an early, plain message;
 * and `global-setup.ts` calls `assertModeAllowed` on the mode Playwright resolved from every spelling of
 * the flag (`-u`, `-xu`, `-uall`, `--update-snapshots=missing`, ...), so the gate holds however the update
 * is asked for, `vr:update` or `playwright test` directly.
 */

/** The values Playwright's `--update-snapshots [mode]` takes; a bare flag means "changed". */
const MODES = new Set(["all", "changed", "missing", "none", "default"]);
/** The test command's short options that take the rest of a cluster as their value (`-cfile`, `-gfoo`). */
const VALUED = new Set(["c", "g", "G", "j"]);

/** The mode a `-u` in a short-option cluster asks for: what follows it in the cluster, else the next arg. */
const clusterMode = (cluster: string, next: string): string | undefined => {
  for (let index = 1; index < cluster.length; index += 1) {
    const flag = cluster[index] ?? "";
    if (VALUED.has(flag)) return undefined; // the rest is that option's value, not flags
    if (flag !== "u") continue;
    const attached = cluster.slice(index + 1);
    if (attached !== "") return attached;
    return MODES.has(next) ? next : "changed";
  }
  return undefined;
};

/** Whether the CLI arguments ask Playwright to write snapshots (any mode but "none"). */
export function requestsUpdate(argv: readonly string[]): boolean {
  return argv.some((arg, index) => {
    const next = argv[index + 1] ?? "";
    const long = /^--update-snapshots(?:=(.*))?$/.exec(arg);
    if (long !== null) return (long[1] ?? (MODES.has(next) ? next : "changed")) !== "none";
    if (!/^-[^-]/.test(arg)) return false;
    const mode = clusterMode(arg.split("=")[0] ?? arg, next);
    return mode !== undefined && mode !== "none";
  });
}

const refusal = (): Error =>
  new Error(
    "vr:update refuses to run in CI: baselines change only through the a11y workflow's dispatch " +
      "(`gh workflow run _job-a11y.yml --ref <branch> -f vr_update=true`), whose artifact a person " +
      "commits for design review (packages/ui/README.md, Visual regression)",
  );

/** Whether an update is allowed here: anywhere but CI, or in CI with the dispatch's `VR_UPDATE=1`. */
const allowed = (env: Readonly<Record<string, string | undefined>>): boolean =>
  !env["CI"] || env["VR_UPDATE"] === "1";

/**
 * Throws if the arguments ask for an update in CI (`CI` set) without `VR_UPDATE=1`, which only the a11y
 * workflow's `vr_update` dispatch input sets. Elsewhere, and for a plain comparison, it does nothing.
 */
export function assertUpdateAllowed(
  argv: readonly string[],
  env: Readonly<Record<string, string | undefined>>,
): void {
  if (requestsUpdate(argv) && !allowed(env)) throw refusal();
}

/** The same rule on the mode Playwright resolved (`config.updateSnapshots`), whatever spelled it. */
export function assertModeAllowed(
  mode: string,
  env: Readonly<Record<string, string | undefined>>,
): void {
  if (mode !== "none" && !allowed(env)) throw refusal();
}
