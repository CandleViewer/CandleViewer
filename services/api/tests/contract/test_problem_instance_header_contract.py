"""#3990: the contract names the one header an audit entry's `request_id` matches.

`CorrelationMiddleware` reads, validates and echoes `X-Correlation-Id`, and every audit record of
an HTTP request under `api/` and `admin/` takes its `request_id` from the id it bound. No request
header named `X-Request-Id` is read anywhere, so no contract text may say the entry matches one.
"""

from __future__ import annotations

import json

from candleviewer.api.contract_conformance import load_contract_subset
from candleviewer.api.cors import EXPOSE_HEADERS
from candleviewer.observability.correlation import CORRELATION_HEADER
from tests.contract._admin_support import ROOT, SPEC, text

_YAML = ROOT / "docs" / "plan" / "22-api-openapi.yaml"
_RETIRED_HEADER = "x-request-id"


def _instance(spec: dict[str, object]) -> str:
    schemas = spec["components"]["schemas"]  # type: ignore[index]  # the document's own shape
    return text(schemas["Problem"]["properties"]["instance"]["description"])


def test_problem_instance_says_the_audit_entry_matches_the_correlation_header() -> None:
    described = _instance(SPEC)
    assert f"matches the `{CORRELATION_HEADER}` header and the audit entry" in described
    assert _RETIRED_HEADER not in described.lower()


def test_the_runtime_contract_subset_says_the_same() -> None:
    assert _instance(load_contract_subset()) == _instance(SPEC)


def test_no_contract_text_names_the_retired_header() -> None:
    assert _RETIRED_HEADER not in _YAML.read_text(encoding="utf-8").lower()
    assert _RETIRED_HEADER not in json.dumps(load_contract_subset()).lower()


def test_the_header_the_contract_names_is_the_one_cors_exposes_to_pages() -> None:
    assert CORRELATION_HEADER in EXPOSE_HEADERS
