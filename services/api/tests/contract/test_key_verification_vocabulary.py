"""Contract (#3089, E27-T03 #836): the key-verification pipeline speaks the contract's words.

`docs/plan/22-api-openapi.yaml` closes three vocabularies (SR-E27-08): the `createApiKey` rule
codes, `KeyVerificationWarning` and `KeyProbeError`, and it names every field of `KeyVerification`.
The pipeline (`accounts/verification.py`) and the adapter's probe table
(`exchange/bybit/key_info.py`) are the code side. Each test reads the spec, never a copy of it, so
a name that drifts on either side fails here (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from candleviewer.accounts.verification import Rule, VerificationResult, VerificationWarning
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.exchange.bybit.key_info import PROBE_ERRORS

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_CREATE_KEY: dict[str, Any] = _SPEC["paths"]["/exchange-accounts/{accountId}/keys"]["post"]
#: The one rule emitted that the contract does not name yet: step 6 refuses an expiry at or before
#: `now` (SR-030a). Slice 2b1 adds `key_expired` (decision 9 on #836) and retires this exemption;
#: the subset check below passes before and after that merge, whichever slice lands first.
_AWAITING_THE_CONTRACT = frozenset({"key_expired"})
#: Added to `KeyVerification` by slice 2b1 (decision 8); the route fills it in from the policy.
_FROM_THE_POLICY = frozenset({"egress_ip"})


def test_the_warnings_are_the_contracts() -> None:
    declared = {warning.value for warning in VerificationWarning}
    assert declared == set(_SCHEMAS["KeyVerificationWarning"]["enum"])


def test_the_probe_error_names_are_the_contracts() -> None:
    assert PROBE_ERRORS == set(_SCHEMAS["KeyProbeError"]["enum"])


def test_the_rules_are_the_ones_create_api_key_names() -> None:
    described = set(re.findall(r"`(key_[a-z_]+)`", _CREATE_KEY["description"]))
    named = described - set(_SCHEMAS["KeyVerificationWarning"]["enum"])
    emitted = {rule.value for rule in Rule}
    assert named <= emitted  # every rule the contract names is emitted
    assert emitted - named <= _AWAITING_THE_CONTRACT  # an emitted rule it lacks is exempt by name


def test_the_result_carries_every_field_of_key_verification() -> None:
    carried = {field.name for field in dataclasses.fields(VerificationResult)}
    assert set(_SCHEMAS["KeyVerification"]["properties"]) - _FROM_THE_POLICY <= carried


def test_the_result_has_no_unified_field() -> None:
    """UTA is read from `uta`; the deprecated `unified` is never read or reported (step 4)."""
    assert "unified" not in {field.name for field in dataclasses.fields(VerificationResult)}
