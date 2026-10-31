"""The fire key (24 §11.9 "The fire key"; C-2.10): pure functions, no I/O.

`dedupe_key` names one action of one fire on one account, unique across restarts (`run_id` is the
fire's `rule_runs` id) and stable across `retry_once` and an OMS reconnect. `client_ref` is the key
the OMS anchor keeps per principal; `request_sha256` the fingerprint of the action's request, built
once per action and account and sent unchanged by a retry. The exchange order's client id stays
the OMS's (24 §8.3 rule 1): nothing here enters it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid5

from candleviewer.rules.ir.canonical import dec_str

#: The rules module's namespace for `client_ref`, minted once with `uuid4` and never changed: a new
#: value would give every in-flight fire a second `client_ref`, a new request at the anchor.
RULE_ACTION_NAMESPACE: Final = UUID("b07bbaaa-85e2-433b-885a-2620f013fa9e")
_KEY = re.compile(r"[0-9a-f]{64}")


def dedupe_key(
    *,
    rule_id: UUID | str,
    version: int,
    scope_instance: str,
    node_id: str,
    run_id: UUID,
    account_id: UUID | None,
) -> str:
    """`sha256(canonical(rule_id, version, scope_instance, node_id, run_id, target_account_id))`
    in lower-case hex: the six as one JSON array in that order, each a string (ids in canonical
    lower-case hyphenated form, `version` in decimal) but a missing account, the JSON `null`, in
    UTF-8 with no whitespace. A rule id that is no UUID is a `ValueError`, never echoed."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("version is an int")
    if not scope_instance or not node_id:
        raise ValueError("a fire key names its scope instance and its node")
    try:
        rule = str(UUID(str(rule_id)))
    except ValueError:
        raise ValueError("rule_id is no UUID") from None
    account = None if account_id is None else str(account_id)
    fields = [rule, str(version), scope_instance, node_id, str(run_id), account]
    text = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def client_ref(key: str) -> str:
    """`uuid5(RULE_ACTION_NAMESPACE, dedupe_key)` in canonical text, which `tg_ref_fmt` admits."""
    if _KEY.fullmatch(key) is None:
        raise ValueError("a client_ref is derived from a dedupe_key")  # never echoes the value
    return str(uuid5(RULE_ACTION_NAMESPACE, key))


def request_sha256(request: Mapping[str, Any]) -> str:
    """sha256 hex of the request's canonical JSON: keys sorted, no whitespace, a `Decimal` as its
    plain text (`dec_str`), so `0.010` and `0.01` are one request. A float, a non-string key or a
    value JSON cannot hold is a `TypeError`: an order request carries no binary float."""
    text = json.dumps(
        _canonical(request), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("a request's keys are strings")
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, Decimal):
        return dec_str(value)
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    raise TypeError(f"a request holds no {type(value).__name__}")
