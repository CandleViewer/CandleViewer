# E07 backup / restore drill (SR-090..093) - procedure

Status: EXECUTED 2026-10-02 (full drill: Postgres + one Parquet partition restored, app started) — CI run https://github.com/CandleViewer/CandleViewer/actions/runs/36954315443.
Automated as `services/api/tests/integration/storage/test_restore_drill.py` (CI `integration` job, every PR); the run's JSON report is the `restore-drill-report` artefact.
Fixtures only; throwaway backup key (`openssl rand -out key 32`), never the runtime KEK.

1. Back up PG dump + one Parquet partition + config; encrypt with the throwaway key.
2. Attempt decryption without the key / with the runtime KEK: must fail (automated analogue:
   `test_sr092_backup_key.py`). Record the attempt here.
3. Run `restore_drill.sh <backup> <scratch>`; the app must start and the partition checksums match.
4. Record date, operator, result in this file.

| Date | Operator | Decrypt-without-key | Restore | Notes |
|---|---|---|---|---|
| 2026-10-02 02:10Z | CI `integration` ([run 36954315443](https://github.com/CandleViewer/CandleViewer/actions/runs/36954315443)) | FAILED as required: runtime-style key -> `InvalidTag` | OK: PG 25/25 audit rows restored, hash chain verified (25 entries) via the app's `AuditQueryService`; partition sha256 `97415461…187bc` before = after; app `/readyz` 200 in 0.033 s; restore 0.263 s | throwaway AES-256-GCM key, fixture rows only; `pg_dump -Fc` 68,574 B -> `pg_restore --exit-on-error` after `DROP SCHEMA public CASCADE` + partition dir deleted |
| 2026-10-02 | claude-agent (E07-X02) | FAILED as required: wrong key (stands in for runtime KEK) -> `bad decrypt`; no key -> script refuses (`CV_BACKUP_KEY_FILE` required) | OK: `restore drill OK`; `trades/part-0000.parquet: OK` (sha256sum -c) | throwaway `openssl rand` keys, fixture bytes only; Postgres dump leg not run (no docker) |

## Execution record (2026-10-02)
Commands: build fixture tar + `_manifests/checksums.sha256`; encrypt with key A (`openssl enc -aes-256-cbc -pbkdf2`);
`CV_BACKUP_KEY_FILE=<key B> restore_drill.sh` -> `bad decrypt` (exit non-zero); with key A -> checksum OK and
`restore drill OK 2026-10-02T00:29:02Z`. The pg_restore leg (loopback scratch DB) runs on the docker-capable
nightly host; the SR-047 loopback restriction is enforced by the script's `-h 127.0.0.1`.

## Full drill (2026-10-02, CI)
Run: https://github.com/CandleViewer/CandleViewer/actions/runs/36954315443 (job `integration`, head `6f9b8f8`). Report `restore-drill.json`:
seeded 25 audit rows (real `AuditWriter`, trigger-chained) -> `pg_dump -Fc` + Parquet partition
`trades/symbol=BTCUSDT/dt=2026-10-17` (1,000 rows, real cold-tier writer) encrypted -> both destroyed ->
decrypt + `pg_restore` + partition restored -> `create_app` (storage_backend=real) `/readyz` 200 ->
chain verified 25/25; sha256 `9741546128be1b3a23d3769c1f20f2ed9173a83e67cecbe66f753e62d2f187bc` matches.
The file-level entry above (2026-10-02, openssl) is the earlier partial run of `infra/scripts/restore_drill.sh`.
