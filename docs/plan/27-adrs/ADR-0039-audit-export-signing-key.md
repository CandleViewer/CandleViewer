# ADR-0039 — The audit export's signing key: Ed25519 custody in M2, the injected signer, verification and rotation (#889)

- Status: **accepted (interim)** (2026-10-21): accepted on merge under the owner's delegation (#2701 comment
  6284192190), as decision D1 on #889 says (issuecomment-6297993224), and ratified by main-orchestrator, whose rulings
  of 2026-10-21, recorded in the #889 plan (issuecomment-6323419345), refine D1; where D1's first text differs (item
  1's signed bytes, item 3's module edge and item 5's step-up class), this record follows the rulings. The
  ratification still due (`docs/plan/27-adrs/README.md:5`) is the owner's, on #2701, as for every delegated
  decision; the owner may revoke it there. If a review finds the injection of decision 3 materially worse than an
  import edge, the CONSTITUTION §3 amendment slice opens (C-16.1, the owner personally).
- Date: 2026-10-21
- Deciders: Owner (`@basiltt`) through main-orchestrator (the delegation on #2701; D1 and the rulings on #889); the
  Security engineer through the `security-review` label (C-10.2); the architect as CODEOWNER of `docs/plan/`.
  Author: virtarix-worker-2.
- Consulted: the #889 survey at `main` `7c79b94c` (the plan comment); ADR-0009 Amendments 2 and 4, whose capabilities
  this record copies; `docs/security/threat-models/e42-admin.md`.
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`) and 0038 is the last on
  `main`, so this record takes 0039. The E42-T06 ADR (#1085) takes the next free number when it is written
  (`e42-admin.md` §13.3 item 2).
- Related: #889 (E42-T02; this record is its slice S0), #890 (E42-X01), #1238 (the chain's off-box anchors), #2279
  (the out-of-process signer), #2152, #2266, #3505, #2444 (the 501); ADR-0009 (Amendments 1 to 4, and 8, which this
  record adds), ADR-0025, ADR-0037 decision 6.
- Evidence: every `file:line` holds on `main` at `bf628c8c`. Module paths are under `services/api/candleviewer/`,
  test paths under `services/api/tests/`, and `yaml:n` is a line of `docs/plan/22-api-openapi.yaml`.

## Context and problem statement

E42-T02 (#889) owes a signed, limited audit export. The contract already describes it: `exportAuditLog` schedules a job
that writes the chain span as NDJSON, gzipped by default, with a header line naming the key id (yaml:9051-9113), and
`AuditExportResult` carries a detached Ed25519 signature over the ASCII bytes `cv.audit.export.v1:` followed by the
lowercase hex SHA-256 of the artefact as downloaded, with key ids `cv-audit-export-vN:<16 hex>` (yaml:18820-18860).

`main` cannot produce one. `POST /admin/audit/export` authorises the caller and answers `501 not_implemented`, with no
job and no record (`api/audit.py:723-737`; yaml:9061-9074), because the key's custody was undecided (D1). The download
route is not mounted, `Job` records no requester, and `getJob` answers 404 for every `audit_export` job
(`api/admin_jobs.py:49-56`).

Two constraints shape the answer:

- **Custody.** The ticket body keeps the key "outside the database" (the `audit_checkpoints.signed_by` convention).
  D1 gives it an exchange key's envelope instead: a seed sealed under its own DEK, which the KEK wraps (ADR-0009
  Design §2). M2 seals exchange credentials that way and wraps 32-byte keys under the KEK for `auth` (Amendment 4,
  `secrets/_auth_keyring.py:1-9`), but it signs only HMAC today: a bounded message, refused before any decrypt or
  record, and failures typed with their frames cleared (`secrets/signing.py:35-68`, :84-119). `cryptography`, already
  a dependency (`services/api/pyproject.toml:28`), implements Ed25519.
- **The module boundary.** The export job belongs to `audit` (M19), which may depend on M1 and M10 only
  (`CONSTITUTION.md:334`); the key belongs to `secrets` (M2), which only M4 and M21 may import (C-3.2, `:342`). D1
  item 3 proposed a new §3 edge for one narrow call; a §3 edge is a CONSTITUTION amendment (C-3.4, C-16.1). M2
  already hands narrow capabilities across that boundary without an edge: `CredentialBorrower`, a closure-only object
  (`secrets/service.py:136-168`) minted once by `mint_borrower` (:560-563) in `build_secrets_service`
  (`admin/wiring.py:151-171`), and Amendment 4's keyring for `auth` (M18), which imports neither `secrets` nor
  `admin` (decided; wiring pending on #2152 S4/S5b).

Out of scope: the checkpoint signature (`audit_checkpoints.signature`, `21-database-schema.md:3091-3092`), whose key
#1238 decides, and the chain-lock fix of SR-E42-10, which is S3.
The row "Secrets (KEK, audit signing key) … never in the repo or DB" of `21-database-schema.md:4054` means that
checkpoint key. The export seed is sealed in Postgres, so S4 adds it to 21 §8.1; S0 leaves 21 alone.

## Decision drivers

1. **Offline verification.** Anyone with the file, its manifest and a pinned fingerprint verifies it without the
   backend (D1 item 4).
2. **One digest.** The signature, `sha256sum` and the download's `Repr-Digest` agree (ruling 5).
3. **An exchange key's custody.** Key material is plaintext only inside `secrets`, for one call (C-2.7, C-12.2).
4. **Export never costs trading.** Without its key, export degrades and nothing else does (the #889 plan,
   issuecomment-6323419345: its S6 row and risks).
5. **No owner-gated step on the critical path.** No new module edge, so no CONSTITUTION amendment (C-3.4, C-16.1;
   ruling 1).
6. **Recorded ahead.** Every signature and every rotation is audited before it happens (C-2.9).
7. **Old exports keep verifying,** across rotations and a KEK loss (D1 items 4 to 6).
8. **No new dependency** (C-12.3), contract first (C-6.1), and slices of about 400 changed lines (C-4.8).

## Considered options

- **(a)** An `audit`-owned `Signer` Protocol, implemented in M2 and injected at the composition root.
- **(b)** A CONSTITUTION §3 edge `audit → secrets.sign_audit_export` (D1 item 3 as first written).
- **(c)** The export job in `admin` (M21), which may already import `secrets`.
- **(d)** A key file outside the database and the KEK, like the audit lane key (ADR-0037 decision 6).
- **(e)** RSA, or a JWS envelope, instead of a detached Ed25519 signature.
- **(f)** An HMAC tag instead of a signature.

## Decision outcome

Option (a), with Ed25519.

1. **Ed25519 over the file's digest.** The signature is a detached Ed25519 signature (RFC 8032) over the ASCII bytes
   `cv.audit.export.v1:` followed by the lowercase hex SHA-256 of the export file exactly as downloaded, gzip included
   when `compressed` (yaml:18822-18827, :18847-18850). That SHA-256 is `AuditExportResult.sha256` and, in base64, the
   download's `Repr-Digest`, so a verifier needs `sha256sum` and one Ed25519 check. The prefix keeps the key to this
   one use and versions the format. The manifest (`AuditExportResult`) carries the signature, the algorithm
   (`signature_alg`, `ed25519`), the key id and, from S2, the public key; the file's header line names the key id.
   The key id is `cv-audit-export-v<N>:` and the first 16 hex of the public key's SHA-256 (yaml:18857-18860), N the
   key's version. The entry lines keep the chain's canonical form (S8 pins their bytes), so the signature covers the
   canonical bytes D1 item 1 named, through the digest of the file that holds them. No RSA and no JWS envelope.
2. **Custody (C-2.7, C-12.2).** One signing key per environment (C-2.11). When the environment has none, M2 generates
   it at boot, after the KEK is verified, and stores only its 32-byte seed, sealed under the row's own DEK, which the
   environment's KEK wraps, like an exchange key (ADR-0009 Design §2, Amendment 3). Its wrap and seal bind the
   environment, the purpose and the row under labels of their own, as Amendment 4's wraps do, so neither a credential
   wrap nor an auth key opens as a signing key. The public key and its fingerprint are stored in clear: they are
   public. The seed is plaintext only inside M2, for one signing call: opened for it, never cached, and zeroed after
   it. Nothing outside `secrets` sees it, and no route, record, log or metric carries it. A key that is missing or
   cannot be opened makes export unavailable and nothing else: `start()` latches no order entry for it, while a KEK
   failure still does (ADR-0009 Amendment 1). A key that exists but cannot be opened is never generated over.
   2026-10-22 (#889 S6a-2a): one exception, at a KEK's enrolment boot, is decision 6's dated clause.
3. **An injected signer, no new module edge (ruling 1).** `audit` owns a `Signer` Protocol with one call,
   `sign_audit_export(key_id, digest, job_id, actor_user_id) -> signature`: `digest` is the 32 raw bytes of the file's
   SHA-256, `job_id` and `actor_user_id` (the acting Owner, passed as for `CandidateSigner`, SR-E27-09) are for its
   record only (decision 7), and `signature` is the 64-byte Ed25519 signature. M2 implements it, satisfying the
   Protocol structurally, so neither module imports the other, and bounds it as it bounds the HMAC signer:
   - it accepts exactly 32 bytes and signs only `cv.audit.export.v1:` with their hex, so it is no general-purpose
     signing oracle;
   - it signs with the environment's active key only and refuses any other key id;
   - it writes its audit record before it signs, and refuses when that record cannot be written (decision 7);
   - it fails closed: a refusal or a failure returns no signature and leaves as a typed error with nothing chained
     and the failed call's frames cleared (`scrub_frames`), and the export job then fails.
     `admin/wiring.py` maps that error to an `audit`-owned one carrying a reason code, as Amendment 4's adapter does,
     so it and the job's error code cross the seam without `audit` importing `secrets`.

   The shape and key-id refusals come before any decrypt or record. The capability holds only a closure, like
   `CredentialBorrower`. It is minted once at the composition root, in `admin/wiring.py` beside `mint_borrower` and
   `mint_candidate_keys`, the one site where rule R9 of the M2 AST guard allows a mint (`_m2_guard.py:34-36`, :57-59
   under `tests/unit/credentials_m2/`; S6 adds this mint to its list), and it is injected into the export job alone.
   The job reads the active key's id and public key, which are public and reach it without the seed, through
   `SigningKeyDirectory.active()`, a second `audit`-owned read port the composition root also injects, when it starts,
   names that id in the header line and passes it back when it signs. `audit` never imports `secrets`, so C-3.2, M19's
   row of CONSTITUTION §3 and the import-linter contracts (`docs/plan/module-contracts.toml`,
   `services/api/.importlinter`) stay as they are, and the mint adds no edge either: `admin` already depends on M2
   and M19 (`CONSTITUTION.md:336`). This is Amendment 4's pattern for `auth` (decided; wiring pending on #2152 S4/S5b).
   Why injection rather than the edge D1
   item 3 first proposed:
   - **No owner-gated C-16.1 step:** S10 does not wait for an amendment PR, its discussion period and the owner's
     personal approval;
   - **the same bounding as an import edge:** the bounds above live in M2's code either way, and an edge would bound
     the call no better;
   - **a narrower interface:** one call with plain data in and out, minted once, where an import edge opens a module;
     the out-of-process signer (#2279) can serve it unchanged.

   The rejected alternative is option (b), a CONSTITUTION §3 edge `audit → secrets.sign_audit_export`, which needs
   the owner personally under C-16.1. An amendment slice opens only if this record's review finds the injection
   materially worse.

4. **Verification.** `GET /admin/audit/signing-keys`, read-only, for `audit:read` (the Owner and Managers;
   `auth/rbac_seed.json:237`), lists the environment's keys, active and retired, each with its validity window, its
   algorithm, its fingerprint (SHA-256 over the 32-byte raw public key), the public key and a `verified` mark. A
   verifier pins the full fingerprint, never the 64-bit key id, which only finds the key: the Owner records each new
   fingerprint out of band, from the chain's record of the rotation they performed, not from the list, and a later
   verification compares the manifest's public key with that record, not with what a server says then, as the
   contract asks ("never trust a key served next to the artefact", yaml:18826-18827). That first pin is the
   trust-on-first-use moment: a key substituted before it is the one pinned. Retired keys stay listed, so old exports
   keep verifying. The key id's hash covers the same 32 bytes (yaml:18860). Binding on S4, S5 and S7: the seed's seal
   binds the public key (its AAD includes it, or M2 derives the public key from the opened seed and compares, at boot
   and before every signature), so a row whose public key does not match its seed is refused and paged, never listed
   as usable, and the list marks a key `verified` only after that check (a retired key without its seed stays
   unverified; the Owner's pin covers it). S2 owns the shape of the list's fields and of the Owner's fingerprint duty,
   and confirms `audit:read`, which is derived from `auth/rbac_seed.json:237`.
   2026-10-22 (#889 S2): the list is Owner-only, as `verifyAuditChain` is: a Manager has no verification duty, and the
   list shows incident state.
5. **Rotation.** `POST /admin/keys/audit-signing/rotate`, beside `rewrapKek` (yaml:12553): Owner only
   (`keys:manage`), step-up class `keys` (ruling 2; D1's `security_sensitive` is not a step-up class), CSRF
   (C-12.10), idempotent (a retried request rotates once), single-flight (`409 conflict` while a rotation or an
   export job runs for the environment), capped per hour like `audit_export_rate_per_hour` (S2 names the setting) and
   audited ahead. M2 generates the new key, makes it active and retires the old one, which stays listed for
   verification and never signs again. An export that straddles a rotation anyway fails instead of signing (a job
   error code S2 names), since its header line names the old key. No new screen (D1 item 5).
   `keys` is a grace class (`auth/step_up.py:83-98`), so a `keys` step-up in the last 5 minutes lets a session rotate
   the key with no fresh code (AD-E12). S2 confirms `keys:manage`, derived from `rewrapKek`; the old seed's fate is Q3.
   2026-10-22 (#889 S2): the idempotency record is durable. S4's new key row carries the request's idempotency key and
   fingerprint, and a retry rebuilds the `200` from the key rows, so it commits with the rotation; the in-memory cache
   alone would lose it at a restart.
6. **Backups and KEK re-wrap.** The sealed seed lives in Postgres, so the database backup set carries it, as
   ciphertext only (ADR-0009 Design §7; SR-091); the KEK is kept outside that set as ADR-0009 says (Design §1, §7;
   Amendment 1). A KEK re-wrap covers the signing-key rows as it covers `auth_keys` (Amendment 4; yaml:12567-12570;
   #3505): M2 re-wraps them at the rotation boot, as it does `auth_keys`, and the call counts them; the key check
   value's trial unwrap reaches them, and `security.kek_rotated` (retired rows with no seed aside, Q3)
   waits until none is left at the previous version. A re-wrap that skipped them would break signing silently, at
   the next export rather than at the rotation. Losing the KEK loses the key, the accepted model (D1 item 6): exports
   signed before still verify with the listed public key, and a rotation (decision 5) provides the next key.
   2026-10-22 (#889 S6a-2a, the orchestrator's ruling 2): at a boot that enrols a KEK version, the signing key is part
   of the KEK's no-trust-on-first-use proof only when no API key row is evidence at that version. Then a failed trial
   unwrap of the active key is `kek_mismatch`, a KEK failure that latches order entry, so a wrong KEK never pins the
   lineage. A signing-key store that cannot be read there latches with the existing `kcv_store_unavailable`. When an
   API key row proved the KEK, the signing key is not trialled, and its own failure at the boot check only degrades
   export. The call's `remaining` counts the keys still holding a seed (`export_left` in its records); an unwired
   store reads `unchecked`, and the run is never complete.
7. **Records (C-2.9).** The signer writes `security.audit_export_signed` before it signs, through M2's audit port
   (`admin/wiring.py:114-120`), naming the job id, the acting Owner (`actor_user_id`), the file's digest and the key's
   id and fingerprint. The download writes `admin.audit_export` with reason `downloaded` before any byte is streamed
   (ruling 4; yaml:9097-9109; AC-ADM-21). The request's `admin.audit_export` record stays as the contract has it; the
   completion's (yaml:9110-9113) also names the job id (S2 adds it) beside its digest, so a signature with no matching
   completion is a direct join. The key's generation and its rotation are recorded ahead too (C-2.9), under names S2
   and S6 set, the rotation's record naming both fingerprints. Each slice registers the actions it first emits, with
   their test (SR-E42-11).
   2026-10-22 (#889 S2): the rotation's record is inserted in the rotation's own transaction (C-2.9's same boundary),
   so it exists only for a rotation that committed (wherever this record says a rotation is recorded or audited ahead,
   it is that record), and the key's records name `object_kind` `audit_signing_key`, which
   S6 adds to M2's audit port with a boolean member and a refused record's `outcome: denied`.
   2026-10-22 (#889 S6a-1): the port gives `audit_signing_key` to every `security.audit_signing_key_*` and
   `security.audit_export_*` record before its `key_id` rule, which named an API key, so the records keep the member
   `key_id` that 24 §15.7 names; it stores `retired_material_destroyed` as a JSON boolean, and
   `security.audit_signing_key_rotation_refused` (S7 registers it) as `denied` at warning.
8. **No feature flag (C-4.13).** The export spans S2 to S10, but the contracted `501` is its gate until S10 replaces
   it in one PR (ruling 7): nothing before S10 can produce a signed file, and the download stays dark until then
   (S9). The signing-keys list and the rotation (S7) are complete, audited operations on their own. No flag gates a
   safety control here (C-4.14).

## Consequences

- Good: an export verifies offline with `sha256sum` and one Ed25519 check against a pinned fingerprint. The key has
  an exchange key's custody. No CONSTITUTION change, so S10 waits on no amendment. Old exports verify after a rotation
  and after a KEK loss.
- Bad: one more key class in M2 to generate, re-wrap, back up and rotate, and one more row class every KEK re-wrap
  must cover (SR-E42-16). A rotation is refused (409) while an export runs, and an export that straddles one anyway
  fails and is requested again. The manifest carries a public key that a verifier must not trust on its own.
- Bad: `cryptography` takes the seed as immutable `bytes`, a copy no zeroing reaches: the accepted SR-009 residual
  of every M2 key (`secrets/_envelope.py:18-19`). Zeroing reaches M2's own `bytearray`s only.
- Risk: a stolen seed signs backdated exports that verify (`e42-admin.md` AD-T14), and offline verification alone
  cannot tell. The detection is the Owner's chain cross-check, `queryAuditLog` for `security.audit_export_signed` with
  the manifest's `sha256`, which S2's §15.7 names as a verification step: a signature with no record is a forgery. A
  verifier also rejects an export whose range lies outside the key's validity window. #1238's off-box anchors keep the
  chain itself honest; until #1238 the residual is Medium.
  2026-10-22 (#889 S2): the check is one-sided, every entry before a retired key's `valid_until`, since the current
  key signs older ranges. It does not bound backdating with a stolen seed; the Owner's chain cross-check does.
- Risk: the injection holds only while `audit` never imports `secrets`. The import-linter contracts and rule R9 fail
  a slice that tries.

## Rollout and slices

One branch per slice (`<type>/e42-t02-<slug>`), one PR of about 400 changed lines or fewer (C-4.8), labelled
`security-review`, with `Refs #889` and a `Partial:` line; only S10 closes #889 (C-4.7). There is no S1: the §3
amendment slice of the first plan (#889 issuecomment-6323419345) opens only under decision 3's condition. The critical
path is S0 → S2 → S8 → S9 → S10; S3 starts at once, S5 merges after S0, and S4 after S3 (one migration head, C-5.3).

<!-- prettier-ignore -->
| # | Slice and its tests | After |
| --- | --- | --- |
| S0 | This record, ADR-0009 Amendment 8, the two index rows and the E42 model's signing-key rows (docs) | — |
| S2 | Contract (C-6.1): `GET /admin/audit/signing-keys`, `POST /admin/keys/audit-signing/rotate` (single-flight: `409 conflict` while a rotation or an export runs; capped per hour, the setting named here), the manifest's `public_key`, the export settings (range, rows, bytes, TTL) and the file format in `24-internal-schemas.md` §15.7, which it adds: the header names the environment, so a verifier holding both environments' pins cannot be shown a demo-signed file as live, and the verification steps name the chain cross-check (`queryAuditLog` for `security.audit_export_signed` with the manifest's `sha256`) and the key's validity window; regenerated | S0 |
| S3 | SR-E42-10: `audit_chain()` draws the id under the chain lock. A migration, and a two-connection test with a raw INSERT | — |
| S4 | The signing-key table and its store (`audit_signing_keys`, `21-database-schema.md` §3.1.5b): a DEK-wrapped seed, one active key per environment, write-once except for the retire, the seed's destroy (per Q3) and the KEK re-wrap; a rotated key's row carries its request's `Idempotency-Key` and fingerprint (`client_ref`, `client_body_sha256`, read with the Owner's `created_by`), decision 5's durable record; its store, `ExportKeyStore` (`secrets/store.py`, with M10's `SqlAlchemyExportKeyStore`), retires the old key and destroys its seed in one UPDATE, inserts the next version and commits the rotation's record in one transaction, starts the boot key from its generation record's `event_ts`, and answers a retried rotation with its `200` and the stored fingerprint, which the caller compares; a rotation is revocation-class state for #3084's restore replay (`e42-admin.md` §6 step 8); it adds the sealed seed to `21-database-schema.md` §8.1 | S3 (one migration head) |
| S5 | The M2 Ed25519 core: generate, wrap, sign the prefix and the digest, zero; the key object is never held beyond the call and `private_bytes` is never called, the Python copy of the seed being the stated SR-009 residual. Unit: the RFC 8032 §7.1 vectors; the seed in no repr, pickle, traceback or log | S0 |
| S6 | M2 creates the key at boot, after the KEK is published (export alone degrades without it, never trading; any failure, of the store write or of its record, leaves `secrets` degraded and export unavailable and never latches order entry), mints the export signer and its key directory and writes `security.audit_export_signed` ahead, with the job id and the Owner (decision 7); the KEK re-wrap and its check cover the new rows and skip only retired rows whose seed is already destroyed (per Q3). Unit: the record-before-sign spy; the refusals before any decrypt; a stranded key latches no order entry; a generation record that fails at boot leaves no latch and no key; `secrets` at 95% coverage or more, with mutation testing. Notes for S6, to confirm there: M2's audit port derives `object_kind: api_key` from any `key_id` field (`admin/wiring.py:103`), so name the record's field differently or extend the mapping; a failure after the write-ahead record appends a failed record, as `security.credential_sign_failed` does (Amendment 2); export unavailable answers `503` with a code S2 names; a key that cannot be opened reports `secrets` degraded and pages, as a keyring failure does (Amendment 4), the signal `e42-admin.md` §10.2 lists | S4, S5 |
| S7 | The list and rotate routes: the list marks `verified` only from M2's check (decision 4); rotation is single-flight and rate-capped (decision 5) | S2, S6 |
| S8 | The export writer: batches with verify's renderings, canonical lines, deterministic gzip, SHA-256, off-loop I/O, the file `0600` and opened `O_NOFOLLOW` (repo practice; S8b confirms both). Unit: the lines pinned byte for byte | S2 |
| S9 | The download and the requester rule (`getJob` too), dark until S10. 2026-10-22: four PRs, S9-0 the requester rule and `getJob`, S9-1a the reader (the lookup, the expiry, the file's checks and its guarded stream, mounting nothing), S9-1b the route, S9-2 the boot sweep and the hard-link probe | S2, S8 |
| S10 | The signed export replaces the 501, through the injected signer; an export that straddles a rotation fails the job; the SR-E42-08 mark; AC-ADM-20 and AC-ADM-21 | S6, S7, S9 |

## Why not the alternatives

- **(b) The §3 edge.** It is the same narrow call, made through a CONSTITUTION amendment: C-16.1's issue, three
  working days, the architect, the security engineer, the CODEOWNERs and `@basiltt` personally, while #3949 amends
  the same file. It bounds the call no better than (a), because the bounds are M2's code either way.
- **(c) The job in `admin`.** C-3.2 lets M21 import M2 only for metadata, so a signing call from `admin` raises the
  same question, and the export reads the chain, which is `audit`'s read side.
- **(d) A key file outside the KEK.** The audit lane key avoids the KEK because sign-out must work while the KEK is
  unavailable (ADR-0037 decision 6). Export has no such need, since it degrades instead, so its key takes the
  strongest custody M2 has (D1 item 2).
- **(e) RSA or JWS.** RSA keys and signatures are larger and its padding is a choice to get wrong; a JWS envelope
  wraps the file, or needs its detached-payload form and a JSON parser to verify. Ed25519 is deterministic, its key
  is a 32-byte seed and its signature 64 bytes, and `cryptography` already implements it (C-12.3).
- **(f) HMAC.** Whoever can check an HMAC can make one, so a verifier would hold the secret; an export must verify
  with no secret and no backend (D1 item 4).
- **Signing the canonical rows rather than the file's digest** (D1 item 1's first text): the signature, `sha256sum`
  and `Repr-Digest` would disagree, and a verifier would need the canonicaliser (ruling 5).

## Open questions

Q1 and Q2 are tracked here and on #889; any still open when S10 opens is filed then as a plan-gap item (ruling 6).

- **Q1, D11 of #889 issuecomment-6182603623: the on-demand verify's read-only question.** No decision here depends
  on it: verify signs nothing and holds no signer.
  It asks whether a chain break found by the Owner-only, rate-limited, often partial-range `POST /admin/audit/verify`
  should force read-only mode, as 04 §8.1 intends for start-up and nightly breaks (#2904). The slice keeps (a),
  a page and an operator's decision, not (b), a forced read-only mode.
- **Q2, D11 of D1 item 7: what the export contains for a row whose redaction class is P0.** The signature covers
  whatever bytes the file holds, so the answer changes the file format (S2) and the writer (S8), not the signing.
- **Q3, this record's own: what becomes of a retired key's sealed seed.** D1 and the rulings are silent, and decision
  6 has `security.kek_rotated` wait for every row at the previous KEK version, so a retired seed would be re-wrapped
  for good, though it never signs again, widening AD-T14, unless it is fenced or destroyed. Decided
  (main-orchestrator, 2026-10-21, adopting the proposed default): at rotation the retired key's sealed seed is
  destroyed, its row keeping the public key, fingerprint and validity window for verification; S4's write-once trigger
  permits exactly `retired AND seed IS NULL` as its only UPDATE, and the KEK re-wrap and its count skip only retired
  rows whose seed is already destroyed: a retired row that still holds a seed is counted as a finding
  (`retired_with_seed`), its destroy is retried, and `security.kek_rotated` waits for it (S4, S6). As the security
  review asked, the rotation's audit record (named in S2) carries `seed_destroyed: true` with the retired key's
  fingerprint, which is the proof of destruction, the trigger and the re-wrap are as above, and a restore from before
  a rotation never re-arms the retired key (`e42-admin.md` §6 step 8, #3084).
  2026-10-21 (#889 S2): the contract names that member `retired_material_destroyed`, since the audit redactor erases
  any member whose name contains `seed`.
  2026-10-22 (#889 S4a): the trigger as shipped also permits the retire itself (decision 5) and the KEK re-wrap of a
  row that holds its seed (decision 6); the destroy is the retire's own UPDATE or a later one, never undone
  (`21-database-schema.md` §3.1.5b).

## Validation

- Each slice carries the tests named in its row. Beyond them: a digest that is not 32 bytes and a key id that is not
  the active one are refused before any decrypt or record (S6); a re-wrap that leaves a signing-key row behind does
  not report `security.kek_rotated` (S6); an export that straddles a rotation fails the job, with the code S2 names
  (S10), and a rotation during an export is refused 409 (S7).
- End to end (S10): the downloaded file's `sha256sum` equals `AuditExportResult.sha256` and the `Repr-Digest`, and
  the signature over `cv.audit.export.v1:` and that hex verifies with the key whose full fingerprint was pinned, and
  with no other. Test keys only (the RFC 8032 vectors), never real key material.

## References

- `docs/plan/22-api-openapi.yaml` (`exportAuditLog`, `downloadAuditExport`, `getJob`, `AuditExportResult`,
  `rewrapKek`); `docs/security/threat-models/e42-admin.md` (the seven signing-key rows, SR-E42-15, SR-E42-16);
  ADR-0009 Amendments 1 to 4 and 8; ADR-0037 decision 6
- `secrets/service.py`, `secrets/signing.py`, `secrets/_envelope.py`, `admin/wiring.py`, `api/audit.py`,
  `api/admin_jobs.py`; `tests/unit/credentials_m2/_m2_guard.py`
- #889, #890, #1085, #1238, #2152, #2266, #2279, #2444, #2701, #3505, #3949
