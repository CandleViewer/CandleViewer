"""The web positions goldens (E29-S01, #911, BQ-22): what the web client's contract and
integration tests read, written through the shipped code, never by hand (C-13.5).

``packages/fixtures/golden/positions/`` holds the `positions` topic's snapshot and deltas, the
`wallet` snapshot, one `account_notice`, and the `listPositions` (plain and `?aggregate=true`) and
`listExchangeAccounts` bodies. The rows start as the recorded private `position` push
(``packages/fixtures/bybit/2026-10-05/ws/private-position.jsonl``, its one flat BTCUSDT row), take
the E29-D02 §5.2 LIVE rows' values, are remapped into three fixture accounts, and go through the
shipped chain: ``classify`` and ``read_push`` (the adapter), ``_state`` (the position projection),
then ``position_item``, ``position_document``, ``aggregate_positions`` with
``aggregate_document``, ``account_document``, ``balance_item`` and ``account_notice``. One file,
``ws_positions_contract_fields.json``, adds the four members 23 §15.2 allows and no producer sends
yet (23 §6.2.3: ``margin_mode``, ``realised_pnl_session``, ``r_multiple``, ``trade_group_id``;
E29-T09 owns them), so the client's fallbacks and its trade-group grouping are tested against
contract-valid frames (BQ-8, BQ-10). ``manifest.json`` names the sources and each mapper's commit.

Regenerate from ``services/api`` and review the diff (nothing is written otherwise):
``CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_positions_web_golden.py``. Without it the
test rebuilds every file in memory and compares it byte for byte, so a mapper whose output moves
fails here until the goldens are regenerated with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from candleviewer.accounts.health import AccountHealth, HealthState
from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.accounts.status import AccountStatus
from candleviewer.accounts.wallet import WalletSnapshot
from candleviewer.accounts.wallet_topic import balance_item
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.exchange_accounts import account_document
from candleviewer.api.oms_reads import aggregate_document, position_document
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import AccountRef, Position
from candleviewer.exchange.bybit.private_parse import Push, classify, read_push
from candleviewer.oms.positions import _state
from candleviewer.oms.reads import aggregate_positions
from candleviewer.oms.ws_topics import epoch_ms, position_item
from candleviewer.oms_stream_wiring import account_notice
from candleviewer.storage.repositories.positions import PositionRow

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "packages/fixtures/golden/positions"
CAPTURE = "packages/fixtures/bybit/2026-10-05/ws/private-position.jsonl"
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
REGEN_CMD = "CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_positions_web_golden.py"
ENV: Environment = "live"
#: The read's start that stamps each account's snapshot view, and the deltas after it (23 §6.2.3).
READ_AT = datetime(2026, 10, 31, 14, 2, 11, tzinfo=UTC)
STORED_AT = READ_AT - timedelta(seconds=5)

MAIN = UUID("a1000000-0000-4000-8000-000000000001")
SUB1 = UUID("a1000000-0000-4000-8000-000000000002")
SUB2 = UUID("a1000000-0000-4000-8000-000000000003")
GROUP = "0c000000-0000-4000-8000-000000000001"

type PositionMode = Literal["one_way", "hedge"]
type MarginMode = Literal["cross", "isolated", "portfolio"]
#: (id, label, kind, position mode, margin mode, uid): Sub-2 is the cross, hedge-mode account.
ACCOUNTS: tuple[tuple[UUID, str, AccountKind, PositionMode, MarginMode, str], ...] = (
    (MAIN, "Main", AccountKind.MAIN, "one_way", "isolated", "10000001"),
    (SUB1, "Sub-1", AccountKind.SUB, "one_way", "isolated", "10000002"),
    (SUB2, "Sub-2", AccountKind.SUB, "hedge", "cross", "10000003"),
)

#: E29-D02 §5.2's LIVE rows: account, position id, push overrides (Bybit's field names).
ROWS: tuple[tuple[UUID, str, dict[str, Any]], ...] = (
    (MAIN, "0d000000-0000-4000-8000-000000000001", {
        "symbol": "BTCUSDT", "side": "Buy", "positionIdx": 0, "size": "0.250",
        "entryPrice": "63980.0", "markPrice": "64012.0", "positionValue": "16003",
        "leverage": "10", "unrealisedPnl": "8.00", "liqPrice": "57901.9", "stopLoss": "63880.0",
    }),
    (SUB1, "0d000000-0000-4000-8000-000000000002", {
        "symbol": "BTCUSDT", "side": "Buy", "positionIdx": 0, "size": "0.100",
        "entryPrice": "63985.0", "markPrice": "64012.0", "positionValue": "6401.2",
        "leverage": "5", "unrealisedPnl": "2.70", "liqPrice": "51507.9", "stopLoss": "63900.0",
    }),
    (SUB1, "0d000000-0000-4000-8000-000000000003", {
        "symbol": "ETHUSDT", "side": "Sell", "positionIdx": 0, "size": "1.50",
        "entryPrice": "2480.00", "markPrice": "2561.00", "positionValue": "3841.5",
        "leverage": "20", "unrealisedPnl": "-121.50", "liqPrice": "2591.60", "stopLoss": "2575.00",
    }),
    (SUB2, "0d000000-0000-4000-8000-000000000004", {
        "symbol": "SOLUSDT", "side": "Buy", "positionIdx": 1, "size": "20.0",
        "entryPrice": "152.40", "markPrice": "147.80", "positionValue": "2956",
        "leverage": "25", "unrealisedPnl": "-92.00", "liqPrice": "147.07", "stopLoss": "147.50",
    }),
    (SUB2, "0d000000-0000-4000-8000-000000000005", {
        "symbol": "BTCUSDT", "side": "Buy", "positionIdx": 1, "size": "0.080",
        "entryPrice": "64050.0", "markPrice": "64012.0", "positionValue": "5120.96",
        "leverage": "10", "unrealisedPnl": "-3.04", "liqPrice": "57965.3", "stopLoss": "63950.0",
    }),
)  # fmt: skip

#: The contract-only members, per position id: E29-D02 §5.2's rPnL today, 24 §7.2's R at 4 dp
#: (24 §1.5), and one trade group across Main and Sub-1's BTCUSDT legs.
EXTENSION: Mapping[str, tuple[str, str, str | None]] = {
    "0d000000-0000-4000-8000-000000000001": ("12.4", "0.32", GROUP),
    "0d000000-0000-4000-8000-000000000002": ("0", "0.3176", GROUP),
    "0d000000-0000-4000-8000-000000000003": ("-18.2", "-0.8526", None),
    "0d000000-0000-4000-8000-000000000004": ("0", "-0.9388", None),
    "0d000000-0000-4000-8000-000000000005": ("0", "-0.38", None),
}

#: `wallet` amounts per account (equity, wallet, available, uPnL, IM rate, MM rate): Main's are
#: 22's `listExchangeAccounts` example; Sub-2's MM rate sits in E29-D02 §5.3's cross Near tier.
WALLETS: Mapping[UUID, tuple[str, str, str, str, str, str]] = {
    MAIN: ("51234.9100", "50120.0000", "41000.2500", "1114.9100", "0.1821", "0.0410"),
    SUB1: ("10250.0000", "10368.8000", "8000.0000", "-118.8000", "0.2100", "0.0520"),
    SUB2: ("3000.0000", "3095.0400", "200.0000", "-95.0400", "0.8800", "0.7200"),
}  # fmt: skip

MAPPERS: tuple[tuple[str, str], ...] = (
    ("candleviewer.exchange.bybit.private_parse.read_push", "exchange/bybit/private_parse.py"),
    ("candleviewer.oms.positions._state", "oms/positions.py"),
    ("candleviewer.oms.ws_topics.position_item", "oms/ws_topics.py"),
    ("candleviewer.api.oms_reads.position_document", "api/oms_reads.py"),
    ("candleviewer.oms.reads.aggregate_positions", "oms/reads.py"),
    ("candleviewer.api.exchange_accounts.account_document", "api/exchange_accounts.py"),
    ("candleviewer.accounts.wallet_topic.balance_item", "accounts/wallet_topic.py"),
    ("candleviewer.oms_stream_wiring.account_notice", "oms_stream_wiring.py"),
)
SHA = re.compile(r"[0-9a-f]{40}")


def ms(at: datetime) -> int:
    return epoch_ms(at)


def recorded_push() -> dict[str, Any]:
    """The capture's one private `position` frame: its first line, a flat BTCUSDT row."""
    line = (ROOT / CAPTURE).read_text(encoding="utf-8").splitlines()[0]
    frame: dict[str, Any] = json.loads(line)
    return frame


def account_ref(account: UUID) -> AccountRef:
    uid = next(a[5] for a in ACCOUNTS if a[0] == account)
    key = f"00000000-0000-4000-8000-{int(uid):012d}"  # an opaque handle, never a key (C-2.7)
    return AccountRef(account_id=AccountId(account), uid=uid, environment=ENV, key_ref=key)


def parsed(account: UUID, overrides: Mapping[str, Any], updated: datetime) -> Position:
    """The recorded frame with one row of `overrides`, through the adapter's parse."""
    frame = recorded_push()
    row = {**frame["data"][0], **overrides, "updatedTime": str(ms(updated))}
    text = json.dumps({**frame, "creationTime": ms(updated), "data": [row]})
    push = classify(text)
    assert isinstance(push, Push)  # a topic frame is a push, never a reply
    (event,) = read_push(push, account_ref(account), now_us=ms(updated) * 1000)
    assert isinstance(event.payload, Position)
    return event.payload


def stored(position_id: str, position: Position) -> PositionRow:
    """The projection's row as the store keeps it: `_state` plus the store's id and stamps."""
    state = _state(position)
    kept = {f.name: getattr(state, f.name) for f in fields(state)}
    return PositionRow(**kept, id=UUID(position_id), recv_ts=STORED_AT, updated_at=STORED_AT)


def open_rows() -> list[PositionRow]:
    return [stored(pid, parsed(acc, over, STORED_AT)) for acc, pid, over in ROWS]


def ws_snapshot(rows: Sequence[PositionRow]) -> dict[str, Any]:
    """`{"positions": [...]}`: each account's view, accounts in id order, each stamped with its
    read's start, one millisecond apart (`TopicReads.read`, `_snapshot`)."""
    items: list[dict[str, Any]] = []
    for n, account in enumerate(sorted(a[0] for a in ACCOUNTS)):
        stamp = ms(READ_AT) + n
        mine = [r for r in rows if r.exchange_account_id == account]
        items.extend(position_item(r, environment=ENV, stamp=stamp) for r in mine)
    return {"positions": items}


def ws_deltas(rows: Sequence[PositionRow]) -> list[dict[str, Any]]:
    """Three deltas after the snapshot: a mark move on Main's BTCUSDT, a late frame of Sub-1's
    ETHUSDT stamped before the snapshot read (23 §15 drops it), and Sub-2's BTCUSDT gone flat."""
    main, eth, flat_src = rows[0], rows[2], rows[4]
    moved = stored(str(main.id), parsed(MAIN, {**ROWS[0][2], "markPrice": "64112.0",
                                               "unrealisedPnl": "33.00"}, READ_AT))  # fmt: skip
    late = stored(str(eth.id), parsed(SUB1, {**ROWS[2][2], "markPrice": "2500.00",
                                             "unrealisedPnl": "-30.00"}, STORED_AT))  # fmt: skip
    flat_over = {
        **ROWS[4][2],
        "side": "",
        "size": "0",
        "entryPrice": "0",
        "positionValue": "0",
        "unrealisedPnl": "0",
        "liqPrice": "0",
        "stopLoss": "0",
    }
    flat = stored(str(flat_src.id), parsed(SUB2, flat_over, READ_AT))
    assert flat.size == 0  # a flat row is a removal (`OmsTopics._fan_out`)
    return [
        {"case": "update", "body": {"positions": [position_item(
            moved, environment=ENV, stamp=ms(READ_AT) + 1000)]}},
        {"case": "late", "body": {"positions": [position_item(
            late, environment=ENV, stamp=ms(READ_AT) - 1000)]}},
        {"case": "flat", "body": {"positions": [], "removed": [str(flat.id)]}},
    ]  # fmt: skip


def contract_fields(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The snapshot with the four contract-only members on each item (23 §15.2)."""
    modes = {str(a[0]): a[4] for a in ACCOUNTS}
    items = []
    for item in snapshot["positions"]:
        rpnl, r, group = EXTENSION[item["id"]]
        items.append(
            {
                **item,
                "margin_mode": modes[item["exchange_account_id"]],
                "realised_pnl_session": rpnl,
                "r_multiple": r,
                "trade_group_id": group,
            }
        )
    return {"positions": items}


def accounts() -> list[ExchangeAccount]:
    return [
        ExchangeAccount(
            id=acc, env=ExchangeEnv.LIVE, kind=kind, exchange_uid=uid, label=label,
            parent_account_id=None if kind is AccountKind.MAIN else MAIN,
            position_mode=pm, margin_mode=mm, created_at=STORED_AT, updated_at=STORED_AT,
        )
        for acc, label, kind, pm, mm, uid in ACCOUNTS
    ]  # fmt: skip


def wallet_snapshot() -> dict[str, Any]:
    """`{"balances": [...], "health": [...]}` as `WalletTopic.build` sends it, accounts sorted."""
    balances, health = [], []
    for account in sorted(WALLETS):
        eq, wb, av, up, im, mm = (Decimal(v) for v in WALLETS[account])
        snap = WalletSnapshot(coin="USDT", equity=eq, wallet_balance=wb, available_balance=av,
                              unrealised_pnl=up, account_im_rate=im, account_mm_rate=mm,
                              updated_at=READ_AT)  # fmt: skip
        state = AccountHealth(
            state=HealthState.HEALTHY,
            reason="ws_heartbeat",
            heartbeat_age_ms=2140,
            rest_only=False,
            changed_at=STORED_AT,
        )
        status = AccountStatus(connection_state="connected", health=state, balance=snap,
                               balance_stale=False, balance_stale_since=None)  # fmt: skip
        health.append(state.ws_entry(account))
        balances.append(balance_item(account, snap, status))
    return {"balances": balances, "health": health}


def bodies() -> dict[str, Any]:
    rows = open_rows()
    snapshot = ws_snapshot(rows)
    docs = [position_document(r) for r in rows]
    listed = [account_document(a, None) for a in accounts()]
    return {
        "ws_positions_snapshot.json": snapshot,
        "ws_positions_deltas.json": ws_deltas(rows),
        "ws_positions_contract_fields.json": contract_fields(snapshot),
        "ws_wallet_snapshot.json": wallet_snapshot(),
        "ws_system_account_notice.json": account_notice(SUB1, "oms.account_resyncing"),
        "rest_list_positions.json": {"items": docs, "aggregates": []},
        "rest_list_positions_aggregate.json": {
            "items": docs, "aggregates": [aggregate_document(a) for a in aggregate_positions(rows)],
        },
        "rest_list_exchange_accounts.json": {
            "items": listed, "meta": {"next_cursor": None, "has_more": False, "count": len(listed)},
        },
    }  # fmt: skip


def text(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def mapper_commit(rel: str) -> str:
    """The last commit of the mapper's file (regeneration only: the check never runs git)."""
    git = shutil.which("git")
    assert git is not None
    path = f"services/api/candleviewer/{rel}"
    done = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
        [git, "log", "-1", "--format=%H", "--", path], cwd=ROOT, capture_output=True, text=True,
        check=True,
    )  # fmt: skip
    return done.stdout.strip()


def manifest(files: Mapping[str, str], commits: Mapping[str, str]) -> dict[str, Any]:
    return {
        "note": f"GENERATED - do not hand-edit. Regenerate from services/api with `{REGEN_CMD}` "
        "and review the diff.",
        "story": "E29-S01 (#911), BQ-22",
        "sources": {
            "capture": f"{CAPTURE}, line 1 (a flat BTCUSDT `position` push), the frame every row "
            "starts from",
            "values": "docs/design/E29/E29-D02.md §5.2, the LIVE rows (Main, Sub-1, Sub-2)",
            "wallet": "22 listExchangeAccounts example (Main); Sub-1 and Sub-2 chosen for D02 §5.3",
            "contract_fields": "ws_positions_contract_fields.json adds margin_mode, "
            "realised_pnl_session, r_multiple and trade_group_id: 23 §15.2 allows them and no "
            "producer sends them (23 §6.2.3); E29-T09 owns them (BQ-8, BQ-10)",
        },
        "accounts": {str(a[0]): a[1] for a in ACCOUNTS},
        "environment": ENV,
        "mappers": [
            {"function": fn, "path": f"services/api/candleviewer/{rel}", "commit": commits[rel]}
            for fn, rel in MAPPERS
        ],
        "files": [
            {"name": name, "sha256": hashlib.sha256(body.encode()).hexdigest()}
            for name, body in sorted(files.items())
        ],
    }  # fmt: skip


def without_commits(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {**doc, "mappers": [{**m, "commit": None} for m in doc["mappers"]]}


def test_positions_web_golden_matches_the_shipped_mappers() -> None:
    files = {name: text(body) for name, body in bodies().items()}
    if REGEN:
        OUT.mkdir(parents=True, exist_ok=True)
        commits = {rel: mapper_commit(rel) for _, rel in MAPPERS}
        for name, body in {**files, "manifest.json": text(manifest(files, commits))}.items():
            (OUT / name).write_text(body, encoding="utf-8")
    for name, body in files.items():
        assert (OUT / name).read_text(encoding="utf-8") == body, f"{name} is stale: {REGEN_CMD}"
    kept = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    assert all(SHA.fullmatch(m["commit"]) for m in kept["mappers"])
    expected = manifest(files, {rel: "" for _, rel in MAPPERS})
    assert without_commits(kept) == without_commits(expected), f"manifest.json: {REGEN_CMD}"


def test_positions_web_golden_flat_row_is_a_removal_and_rows_are_open() -> None:
    rows = open_rows()
    assert [r.size > 0 for r in rows] == [True] * len(ROWS)
    deltas = ws_deltas(rows)
    assert deltas[2]["body"] == {"positions": [], "removed": [str(rows[4].id)]}
    late, snap = deltas[1]["body"]["positions"][0], ws_snapshot(rows)["positions"]
    assert late["updated_at_ms"] < min(i["updated_at_ms"] for i in snap)


def test_positions_web_golden_rest_bodies_fit_the_generated_contract() -> None:
    """Each REST body validates against 22's generated models (`api._generated`)."""
    files = bodies()
    for item in files["rest_list_positions_aggregate.json"]["items"]:
        api.Position.model_validate(item)
    for aggregate in files["rest_list_positions_aggregate.json"]["aggregates"]:
        api.AggregatePosition.model_validate(aggregate)
    for account in files["rest_list_exchange_accounts.json"]["items"]:
        api.ExchangeAccount.model_validate(account)
