"""22's `AuditSigningKey` view of the audit export signing keys (#889 S7; ADR-0039 decisions 4 and
5), which `listAuditSigningKeys` (`api/audit.py`) answers with: an M2 record's public members, the
constant `alg` and the raw public key in base64, with M2's own `verified` mark, validated against
the contract's model, so nothing else (a seed, a wrap, a request fingerprint) can be served.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any, Final

from candleviewer.api._generated import openapi_models as api

#: The members served as M2 gives them (`verified` is M2's: decision 4).
_PUBLIC: Final = (
    "key_id", "fingerprint_sha256", "status", "verified", "valid_from", "valid_until",
    "retired_reason",
)  # fmt: skip


def signing_key_view(key: Mapping[str, Any]) -> dict[str, Any]:
    """22's `AuditSigningKey` of an M2 record, as JSON: public material only."""
    shown = {name: key[name] for name in _PUBLIC} | {"alg": "ed25519"}
    shown["public_key"] = base64.b64encode(key["public_key"]).decode("ascii")
    return api.AuditSigningKey.model_validate(shown).model_dump(mode="json")


__all__ = ["signing_key_view"]
