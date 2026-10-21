# Leg snapshot fixtures (E28-T01 #905)

`leg_snapshots_v1.json` is the golden form of `trade_group_legs.profile_snapshot`
(`docs/plan/24-internal-schemas.md` §9.1): the four profile fixtures of `../profiles/`, keyed by
sizing mode, each dumped once with `AccountProfile.model_dump(mode="json")` as `leg_values` writes
it (decimals and ids as strings, `updated_at` in µs, never a float). They are synthetic, not
recorded from an exchange, and hold no credential, account UID or personal data; the ids are the
profile fixtures' placeholders.

The file is frozen. `test_golden_leg_snapshots_still_validate` (`tests/unit/accounts/test_trade_groups.py`)
reads every snapshot back through `leg_profile_snapshot`, so a later `AccountProfile` change keeps
stored snapshots readable or ships a read-side upcaster with a new golden file (decision D-10).
Never regenerate this one to make that test pass.

| File                    | Source                                        | Date       | Env  | Redaction               |
| ----------------------- | --------------------------------------------- | ---------- | ---- | ----------------------- |
| `leg_snapshots_v1.json` | `../profiles/*.json`, `model_dump(mode=json)` | 2026-10-20 | none | none needed (synthetic) |
