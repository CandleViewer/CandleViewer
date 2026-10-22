"""`secrets.Secret`: renders `***`, refuses serialisation, identity equality, invalidation.

Sink registration (log redaction, Problem body, trace attributes, support bundle) is wired
and tested in the service PR.
"""

from __future__ import annotations

import copy
import json
import pickle
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.secret import MASK, Secret

CANARY = "topsecret"


def test_render_paths_mask() -> None:
    s = Secret(CANARY)
    for out in (f"{s}", repr(s), str(s), format(s, ">20"), str([s]), str({"k": s})):
        assert CANARY not in out and MASK in out


@pytest.mark.parametrize("op", [pickle.dumps, copy.copy, copy.deepcopy, lambda s: s.model_dump()])
def test_serialise_paths_refuse(op: Any) -> None:
    with pytest.raises(TypeError):
        op(Secret(CANARY))


def test_json_default_str_masks() -> None:
    out = json.dumps({"k": Secret(CANARY)}, default=str)
    assert CANARY not in out and MASK in out


class _Holder(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    key: Secret[str]


@pytest.mark.parametrize("mode", ["python", "json"])
def test_containing_pydantic_model_dumps_mask(mode: str) -> None:
    dumped = _Holder(key=Secret(CANARY)).model_dump(mode=mode)
    assert dumped == {"key": MASK}
    assert CANARY not in _Holder(key=Secret(CANARY)).model_dump_json()


def test_equality_is_identity_not_plaintext() -> None:
    a, b = Secret(CANARY), Secret(CANARY)
    assert a == a and a != b and hash(a) != hash(b)


def test_no_constant_time_comparison_oracle_either() -> None:
    """The observability base grew `ComparableSecret.equals_constant_time` for arm tokens
    (SR-043); the credential `Secret` extends the base, not that subclass, so it offers no
    value comparison at all — not even a constant-time one."""
    assert not hasattr(Secret(CANARY), "equals_constant_time")
    assert not any("equals_constant_time" in vars(klass) for klass in Secret.__mro__)


def test_no_other_secret_class_can_probe_a_credential() -> None:
    """Neither the observability base nor `ComparableSecret` equals a credential `Secret`
    holding the same value, in either operand order, and `equals_constant_time` refuses it."""
    from candleviewer.observability.secret_type import ComparableSecret
    from candleviewer.observability.secret_type import Secret as ObsSecret

    cred = Secret(CANARY)
    for probe in (ObsSecret(CANARY), ComparableSecret(CANARY)):
        assert probe != cred and cred != probe
        assert not (probe == cred) and not (cred == probe)
    with pytest.raises(TypeError):
        ComparableSecret(CANARY).equals_constant_time(cred)  # type: ignore[arg-type]


def test_invalidate_blocks_reveal() -> None:
    s = Secret(CANARY)
    assert s.reveal() == CANARY
    s.invalidate()
    with pytest.raises(RuntimeError):
        s.reveal()


def test_exception_text_never_contains_key_material() -> None:
    assert str(CredentialUnavailable("credential_unavailable")) == "credential_unavailable"
