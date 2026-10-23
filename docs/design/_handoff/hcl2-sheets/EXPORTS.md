# Export requests: boards hcl-worker-2 drew that need a PNG (exports are down on the hcl laptop)

Added 06:2xZ, 2026-10-23. These boards are DRAWN and lint-clean in the shared CandleViewer Penpot file. Export each one
at scale 1 by its board id (the `export_shape` tool, or your lane's usual method) to the PNG path given, which is
relative to the repository root. Then push the PNGs, at those same paths, to a branch named `design/hcl2-exports`
(cut from `main`; never a PR). hcl-worker-2 copies them into each ticket's boards PR. Do not redraw or edit a board.

| PR | Page | Page id | Board | Board id | PNG path |
| --- | --- | --- | --- | --- | --- |
| #4070 | `E35-D01` | `504164f9-8cb1-8083-8008-d45b908e0cbb` | `E35-D01-01-arming-journey` | `2f3d2667-6b0f-80a6-8008-d4e1ac460629` | `docs/design/E35/img/E35-D01-01-arming-journey.png` |
| #4070 | `E35-D01` | `504164f9-8cb1-8083-8008-d45b908e0cbb` | `E35-D01-02-probe-stimuli` | `2f3d2667-6b0f-80a6-8008-d4e53e239676` | `docs/design/E35/img/E35-D01-02-probe-stimuli.png` |
| #4070 | `E35-D01` | `504164f9-8cb1-8083-8008-d45b908e0cbb` | `E35-D01-03-copy-annex` | `2f3d2667-6b0f-80a6-8008-d4eb0cff1f26` | `docs/design/E35/img/E35-D01-03-copy-annex.png` |
| #4070 | `E35-D01` | `504164f9-8cb1-8083-8008-d45b908e0cbb` | `E35-D01-04-terms-matrix` | `504164f9-8cb1-8083-8008-d45b91b73b27` | `docs/design/E35/img/E35-D01-04-terms-matrix.png` |
| #4070 | `E35-D01` | `504164f9-8cb1-8083-8008-d45b908e0cbb` | `E35-D01-05-findings-decision-map` | `2f3d2667-6b0f-80a6-8008-d4ef35089879` | `docs/design/E35/img/E35-D01-05-findings-decision-map.png` |
| #4070 | `E35-D01` | `504164f9-8cb1-8083-8008-d45b908e0cbb` | `E35-D01-06-source-conflicts` | `2f3d2667-6b0f-80a6-8008-d4facc9a9a5f` | `docs/design/E35/img/E35-D01-06-source-conflicts.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-01-three-cases` | `2f3d2667-6b0f-80a6-8008-d4fe6b834776` | `docs/design/E33/img/E33-D01-01-three-cases.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-02-caveat-candidates` | `2f3d2667-6b0f-80a6-8008-d500ea9f04eb` | `docs/design/E33/img/E33-D01-02-caveat-candidates.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-03-parameter-defaults` | `2f3d2667-6b0f-80a6-8008-d503b56a07d9` | `docs/design/E33/img/E33-D01-03-parameter-defaults.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-04-monitor-must-show` | `2f3d2667-6b0f-80a6-8008-d507b725260e` | `docs/design/E33/img/E33-D01-04-monitor-must-show.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-05-pre-submit` | `2f3d2667-6b0f-80a6-8008-d50d7372cf2e` | `docs/design/E33/img/E33-D01-05-pre-submit.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-06-findings-decision-map` | `2f3d2667-6b0f-80a6-8008-d5101c45b701` | `docs/design/E33/img/E33-D01-06-findings-decision-map.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-07-source-conflicts` | `2f3d2667-6b0f-80a6-8008-d514206e0af8` | `docs/design/E33/img/E33-D01-07-source-conflicts.png` |
| #4046 | `E33-D01` | `2f3d2667-6b0f-80a6-8008-d4fe6a7cba88` | `E33-D01-08-probe-a-stimulus` | `2f3d2667-6b0f-80a6-8008-d5174124efd6` | `docs/design/E33/img/E33-D01-08-probe-a-stimulus.png` |

SCR-140's 23 boards (#4124's boards PR, page `E16-D02 SCR-140 Recorder`) are being drawn now and are added here when built.
