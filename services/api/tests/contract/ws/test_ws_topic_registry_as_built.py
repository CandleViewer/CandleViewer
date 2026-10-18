"""#2823: `23-ws-protocol.md` §5, §6 and §12.1 against the topic registry, so the two cannot drift
apart again. The contract job runs this directory when the doc changes, and the py job when the
registry does. What is read: the §6.1 and §6.2 tables (topic, options, default throttle, binary
form), the §5.4 re-snapshot list, the §12.1 frames, the `encoding` row of §5.1, the family names
of §6.2's accounts paragraph and the series and labels of its metrics paragraph, and from the §13
schemas the `ctl` keys, `params` and `exchange_account_ids`. The rest of the prose is not parsed.
A table row ahead of its registry row fails here by design. What the server does is pinned in
`tests/unit/ws/test_topic_registry_as_built.py`.
"""

from __future__ import annotations

import json
import re
import uuid
from itertools import takewhile
from typing import Any, Final

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.permissions import ConnectionAuthz, auth_ok_payload
from candleviewer.ws.topics import CTL_KEYS, FAMILIES, IDENTITY_OPTIONS, OPTION_NAMES, UNIVERSAL
from tests.contract.ws._harness import PROTOCOL_DOC, SCHEMAS
from tests.unit.ws.test_subscriptions import _services, _sub

_DOC: Final = PROTOCOL_DOC.read_text(encoding="utf-8")
_OPTS: Final = SCHEMAS["cv://ws/v1/sub.schema.json"]["$defs"]["options"]["properties"]  # §13.5
_PUBLIC: Final = ("### 6.1 Public market-data topics", "#### 6.1.1 ")
_PRIVATE: Final = ("### 6.2 Private topics", "#### 6.2.1 ")


def _between(start: str, end: str) -> str:
    """The doc from the first `start` up to the next `end` after it."""
    i = _DOC.find(start)
    j = _DOC.find(end, i + len(start))
    assert 0 <= i < j, f"23-ws-protocol.md no longer has {start!r} followed by {end!r}"
    return _DOC[i:j]


def _paragraph(section: str, needle: str) -> str:
    """The one paragraph of `section` that holds `needle`."""
    found = [p for p in section.split("\n\n") if needle in p]
    assert len(found) == 1, f"{len(found)} paragraphs hold {needle!r}; this test reads exactly one"
    return found[0]


def _table(section: str) -> list[list[str]]:
    """The cells of the first table in `section`, without its header and delimiter rows."""
    lines = section.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("|"))
    rows = takewhile(lambda ln: ln.startswith("|"), lines[first:])
    return [[cell.strip() for cell in ln.strip("|").split("|")] for ln in rows][2:]


def _example(section: str, marker: str) -> dict[str, Any]:
    """The frame of the §12 example line that starts with `marker` (`C→S {...` or `S→C {...`).
    It may run over several lines, up to the next arrow, comment or fence; the arrow is not JSON."""
    start = section.find(marker)
    assert start >= 0, f"§12.1 no longer has an example line starting {marker!r}"
    rest = section[start + len("C→S ") :]
    end = re.search(r"^(?:C→S|S→C|//|```)", rest, re.M)
    frame = json.loads(rest[: end.start() if end else len(rest)])
    assert isinstance(frame, dict)
    return frame


def test_a_the_ctl_keys_are_13_6s_and_5_4_lists_the_re_snapshot_ones() -> None:
    assert CTL_KEYS == set(SCHEMAS["cv://ws/v1/ctl.schema.json"]["properties"])
    marker = "**invalidates the current state**"
    paragraph = _paragraph(_between("### 5.4 ", "## 6. Topic catalogue"), marker)
    assert set(re.findall(r"`([a-z_]+)`", paragraph.split(marker)[0])) == IDENTITY_OPTIONS


def test_a_the_option_names_a_ctl_refusal_may_name_are_13_5s_and_13_6s() -> None:
    """#3370: the registry's names are §13.5's less `params` (test_c below) and §13.6's keys."""
    ctl_keys = set(SCHEMAS["cv://ws/v1/ctl.schema.json"]["properties"])
    assert OPTION_NAMES == (set(_OPTS) - {"params"}) | ctl_keys


def test_c_13_5_lists_params_and_no_topic_takes_it() -> None:
    assert "params" in _OPTS
    assert [f.family for f in FAMILIES.values() if "params" in f.options] == [], (
        "a topic now takes params: E23-T02 (#658) must list it in 23-ws-protocol §6.1 "
        "and update this test"
    )


def test_d_6_2_names_every_account_scoped_family_and_13_5_sets_no_min_items() -> None:
    paragraph = _paragraph(_between(*_PRIVATE), "**As built (#2823).**")
    scoped = [f.family for f in FAMILIES.values() if f.account_scoped]
    assert [family for family in scoped if f"`{family}`" not in paragraph] == []
    assert "minItems" not in _OPTS["exchange_account_ids"]  # the registry's own minimum is 1
    assert FAMILIES["orders"].options["exchange_account_ids"].min_items == 1


def test_d_the_12_1_example_is_an_owner_cold_start_the_server_accepts() -> None:
    """The example's `auth_ok` is an Owner's, with the `account_scope` the server sends one (an
    Owner holds no grants, so `[]`), and the permissions it lists cover the `sub` that follows:
    each entry of that `sub` is accepted with the `sub_id`, `snapshot_pending` and `effective`
    its `sub_ok` shows."""
    section = _between("### 12.1 ", "### 12.2 ")
    auth_ok = _example(section, 'S→C {"t":"auth_ok"')["p"]
    topics = _example(section, 'C→S {"t":"sub"')["p"]["topics"]
    documented = _example(section, 'S→C {"t":"sub_ok"')["p"]["results"]
    permissions = frozenset(Permission(p) for p in auth_ok["permissions"])
    owner = PrincipalSnapshot(
        uuid.UUID(auth_ok["user_id"]), frozenset(auth_ok["roles"]), permissions
    )
    assert owner.is_owner
    assert auth_ok["account_scope"] == auth_ok_payload(owner)["account_scope"] == []
    results = _sub(ConnectionAuthz(owner, _services()), *topics)
    assert [r["ch"] for r in results] == [t["ch"] for t in topics]
    assert len(results) == len(documented)
    for got, doc in zip(results, documented, strict=True):
        assert got["ok"], got
        keys = ("ch", "sub_id", "snapshot_pending")
        assert {k: got[k] for k in keys} == {k: doc[k] for k in keys}
        assert {k: got["effective"].get(k) for k in doc["effective"]} == doc["effective"]


def test_e_the_5_1_encoding_row_names_no_capability() -> None:
    lines = _between("### 5.1 ", "### 5.2 ").splitlines()
    (row,) = [ln for ln in lines if ln.startswith("| `encoding`")]
    assert "`encoding_unsupported`" in row and "capability" not in row


def test_b_f_the_6_1_and_6_2_tables_match_the_registry_and_the_as_built_paragraph() -> None:
    """Every row's topic, options, default throttle and binary form is the registry's; an option
    the registry takes and the row leaves out is one §6.1's "As built" paragraph names."""
    public = _between(*_PUBLIC)
    by_pattern = {
        pattern.replace("{profile_kind}", "{kind}"): fam
        for fam in FAMILIES.values()
        if fam.family != "machines"
        for pattern in fam.patterns
    }
    rows = [(r, True) for r in _table(public)] + [(r, False) for r in _table(_between(*_PRIVATE))]
    problems: list[str] = []
    left_out: list[tuple[str, str]] = []  # (pattern, option) the registry takes, the row omits
    for row, has_binary_column in rows:
        pattern = row[0].strip("`")
        fam = by_pattern.pop(pattern, None)
        if fam is None:
            problems.append(f"{pattern}: not in the registry")
            continue
        in_name = set(re.findall(r"\{([a-z_]+)\}", pattern))
        shown = {o for o in re.findall(r"`([a-z_]+)`", row[1]) if o not in in_name | set(UNIVERSAL)}
        if shown - set(fam.options):
            problems.append(f"{pattern}: lists {sorted(shown - set(fam.options))}, not taken")
        left_out += [(pattern, option) for option in sorted(set(fam.options) - shown)]
        ms = re.match(r"(\d[\d ]*\d|\d) ms", row[3])  # "1 000 ms"; `heatmap` is "= bucket"
        if ms is not None and int(ms.group(1).replace(" ", "")) != fam.default_throttle_ms:
            problems.append(
                f"{pattern}: default throttle {row[3]!r} is not {fam.default_throttle_ms}"
            )
        if has_binary_column and row[4].startswith("✔") != fam.binary:
            problems.append(f"{pattern}: binary form doc={row[4]!r} registry={fam.binary}")
    assert problems + [f"{p}: not in the doc tables" for p in sorted(by_pattern)] == []
    paragraph = _paragraph(public, "**As built (#2823).**")
    assert [
        (p, o) for p, o in left_out if f"`{p}`" not in paragraph or f"`{o}`" not in paragraph
    ] == []


def test_g_the_6_2_metrics_paragraph_names_the_catalogues_series_and_labels() -> None:
    paragraph = _paragraph(_between(*_PRIVATE), "**Metrics as built (E17-S02, #2823).**")
    specs = {m.name: m for m in CATALOGUE}
    ticket = {"cv_ws_topics_per_client", "cv_ws_upstream_refcount"}  # quoted; the server has none
    recorded = set(re.findall(r"`(cv_ws_[a-z_]+)", paragraph)) - ticket
    four = (
        "cv_ws_subscribe_total cv_ws_client_topics_depth "
        "cv_ws_upstream_consumers_in_use cv_ws_revoked_total"
    ).split()
    assert set(four) <= recorded <= set(specs) and not ticket & set(specs)
    for name, labels in re.findall(r"`(cv_ws_[a-z_]+)\{([^}]*)\}`", paragraph):
        if name in recorded:
            assert {x.strip() for x in labels.split(",")} == set(specs[name].labels) - {"env"}, name
