# Real-engine baselines: PENDING

This file is the pending switch of `_job-engine-bench.yml` (E11-T06 PR-2). While it is here and no
baseline file is, the real-engine scenarios are recorded on every route and nothing is compared.

- One baseline file per runner class: `chromium-gpu.json` (the registered GPU runner, the only
  enforced route) and `chromium-hosted.json` (the hosted SwiftShader fallback, recorded only).
  Names follow `<runtime>-<class>.json` (`^[a-z0-9]+-(gpu|hosted)\.json$`, `BASELINE_RE` in
  `baseline-select.mjs`): any file of that shape trips the switch below, but a run reads only
  `chromium-<class>.json`.
  A run is compared only with its own class's file, and `ci-compare.mjs`'s not-like-for-like rule
  (#5414) still applies inside it.
- The first baseline is its own `bench:baseline`-class pull request, taken from a `main`-sourced
  run (the nightly's `engine-bench-engine` artefact, or a `workflow_dispatch` that pull request
  adds), and that pull request deletes this file.
- PROPOSED (BQ-07): the baseline commit touches only `bench/engine/baselines/**` and carries a
  `Perf-Baseline-Cause:` trailer stating why the numbers moved (AC3). No CI guard parses the
  trailer yet; until one lands, the chart-engine CODEOWNER review checks it.
- The switch fails closed: once any baseline file sits next to this file, every run fails
  (`bench/engine/baseline-select.mjs`), so a stale switch can never hide a gate.
