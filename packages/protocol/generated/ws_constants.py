"""GENERATED FILE - DO NOT EDIT BY HAND.

Generator: tools/contracts/gen_ws_constants.py (E17-T01). Sources:
docs/plan/23-ws-protocol.md section 6 and packages/protocol/ws-schemas.json.
Edit the Markdown and run `make gen`.
"""

from __future__ import annotations

FRAME_TYPES: tuple[str, ...] = (
    "hello",
    "welcome",
    "auth",
    "auth_ok",
    "sub",
    "sub_ok",
    "unsub",
    "unsub_ok",
    "snap",
    "d",
    "resync",
    "revoked",
    "permission_change",
    "ping",
    "pong",
    "err",
    "ctl",
    "ctl_ok",
    "bye",
)

ENCODINGS: tuple[str, ...] = (
    "j",
    "b",
    "b64",
)

TOPIC_PATTERNS: tuple[str, ...] = (
    "book.{symbol}.{depth}",
    "trades.{symbol}",
    "bars.{symbol}.{bar_type}.{param}",
    "footprint.{symbol}.{bar_type}.{param}",
    "heatmap.{symbol}",
    "profile.{symbol}.{kind}",
    "metrics.{symbol}",
    "ticker.{symbol}",
    "ticker",
    "liquidations.{symbol}",
    "liquidations",
    "orders",
    "positions",
    "executions",
    "wallet",
    "trade_groups",
    "rules",
    "alerts",
    "recorder",
    "system",
)

TOPIC_FAMILIES: tuple[str, ...] = (
    "alerts",
    "bars",
    "book",
    "executions",
    "footprint",
    "heatmap",
    "liquidations",
    "metrics",
    "orders",
    "positions",
    "profile",
    "recorder",
    "rules",
    "system",
    "ticker",
    "trade_groups",
    "trades",
    "wallet",
)
