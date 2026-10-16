"""`OUR_ID`, `EXT_ID` and `ext_key` (§8.3; E29-T02, #846). The patterns are compared with
the two `ord_link_fmt` arms that `21-database-schema.md` §3.3.4 declares, read from the
document itself, so this suite fails if the code or the document drifts."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.order_link import EXT_ID, OUR_ID, ext_key

_SCHEMA_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "21-database-schema.md"
_CHECK_ARMS = re.compile(
    r"CONSTRAINT ord_link_fmt\s+CHECK\s*\(\s*order_link_id ~ '([^']+)'"
    r"\s+OR order_link_id ~ '([^']+)'\s*\)"
)
_ROOT = Path(__file__).resolve().parents[5]
_INTERNAL_SCHEMAS_DOC = _ROOT / "docs" / "plan" / "24-internal-schemas.md"
_ADAPTER_RULE = _ROOT / ".semgrep" / "cv-adapter-isolation.yml"
_ADAPTER_PATTERN = re.compile(r"^\s*pattern-regex:\s*'([^']+)'", re.MULTILINE)
_MODULE_SOURCE = Path(__file__).resolve().parents[3] / "candleviewer" / "domain" / "order_link.py"
EXAMPLE = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the §8.3 worked example
CANONICAL = "1A2B3C4D-5E6F-4A7B-8C9D-0E1F2A3B4C5D"
# `st.text()` never draws a surrogate, so a property over it cannot see one.
SURROGATES = st.text(
    alphabet=st.characters(min_codepoint=0xD800, max_codepoint=0xDFFF, exclude_categories=()),
    min_size=1,
)
WITH_SURROGATES = st.tuples(st.text(), SURROGATES, st.text()).map("".join)


def _ord_link_fmt_arms(doc: str) -> tuple[str, str]:
    """The two regexes of the `orders.ord_link_fmt` CHECK, as §3.3.4 writes them in SQL."""
    _, found, rest = doc.partition("#### 3.3.4 ")
    assert found, "21-database-schema.md has no §3.3.4 heading"
    check = _CHECK_ARMS.search(rest.split("#### 3.3.5 ", 1)[0])
    assert check is not None, "§3.3.4 no longer declares ord_link_fmt as two `~ '<regex>'` arms"
    return check.group(1), check.group(2)


def _adopted_rows(doc: str) -> str:
    """The §8.3 "Adopted rows" paragraph of `24-internal-schemas.md`, which defines `ext_key`."""
    _, found, rest = doc.partition("**Adopted rows.**")
    assert found, "24-internal-schemas.md §8.3 has no 'Adopted rows' paragraph"
    return rest.split("\n\n", 1)[0]


def _adapter_isolation_pattern() -> re.Pattern[str]:
    """The `pattern-regex` of the Semgrep rule that keeps exchange names out of `domain/`."""
    found = _ADAPTER_PATTERN.search(_ADAPTER_RULE.read_text(encoding="utf-8"))
    assert found is not None, "cv-adapter-isolation no longer declares a quoted `pattern-regex`"
    return re.compile(found.group(1))


def test_our_id_is_the_first_ord_link_fmt_arm() -> None:
    arms = _ord_link_fmt_arms(_SCHEMA_DOC.read_text(encoding="utf-8"))

    assert OUR_ID.pattern == arms[0]


def test_ext_id_is_the_second_ord_link_fmt_arm() -> None:
    arms = _ord_link_fmt_arms(_SCHEMA_DOC.read_text(encoding="utf-8"))

    assert EXT_ID.pattern == arms[1]


@pytest.mark.parametrize(
    ("before", "after", "arm"),
    [("{21}-", "{20}-", 0), ("ext-[0-9a-f]{32}", "ext-[0-9a-f]{31}", 1)],
)
def test_the_drift_guard_sees_a_changed_check(before: str, after: str, arm: int) -> None:
    """The guard is not vacuous: change one arm in the document and the comparison fails."""
    doc = _SCHEMA_DOC.read_text(encoding="utf-8")
    assert before in doc  # the edit below must really change the CHECK

    drifted = _ord_link_fmt_arms(doc.replace(before, after))

    assert drifted[arm] != (OUR_ID, EXT_ID)[arm].pattern


def test_our_id_accepts_the_contract_example() -> None:
    assert OUR_ID.fullmatch(EXAMPLE) is not None


@pytest.mark.parametrize(
    "value",
    [
        EXAMPLE + "\n",  # Postgres `~` rejects a trailing newline, so fullmatch must too
        EXAMPLE[:-1],
        "cvl-8TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",  # a 128-bit group never leads with 8
        "cvx-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",
        "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00xx",
        "cv-l0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",
        "ext-" + "0" * 32,
    ],
)
def test_our_id_rejects_a_value_the_generator_cannot_produce(value: str) -> None:
    assert OUR_ID.fullmatch(value) is None


@pytest.mark.parametrize("value", ["ext-" + "a" * 32 + "\n", "ext-" + "A" * 32, "ext-" + "a" * 31])
def test_ext_id_rejects_other_shapes(value: str) -> None:
    assert EXT_ID.fullmatch(value) is None


def test_ext_key_keeps_a_canonical_uuid_order_id_lowercased_without_hyphens() -> None:
    assert ext_key(CANONICAL) == "ext-1a2b3c4d5e6f4a7b8c9d0e1f2a3b4c5d"


@pytest.mark.parametrize(
    "order_id",
    [
        CANONICAL.replace("-", ""),  # the right digits, but not the 8-4-4-4-12 form
        "{" + CANONICAL + "}",
        CANONICAL + "0",
        "0" + CANONICAL,
        "1234567890",
        "",
    ],
)
def test_ext_key_hashes_an_order_id_that_is_not_a_canonical_uuid(order_id: str) -> None:
    assert ext_key(order_id) == "ext-" + hashlib.sha256(order_id.encode()).hexdigest()[:32]


@given(st.uuids())
def test_ext_key_of_any_canonical_uuid_keeps_its_digits(order_id: uuid.UUID) -> None:
    assert ext_key(str(order_id).upper()) == "ext-" + order_id.hex


@given(st.one_of(st.text(), WITH_SURROGATES))
def test_ext_key_is_always_a_36_char_ext_id_and_never_our_id(order_id: str) -> None:
    key = ext_key(order_id)

    assert EXT_ID.fullmatch(key) is not None
    assert len(key) == 36
    assert OUR_ID.fullmatch(key) is None
    assert ext_key(order_id) == key


@pytest.mark.parametrize(
    ("order_id", "utf8"),
    [
        ("\ud800", b"\xed\xa0\x80"),
        ("\udfff", b"\xed\xbf\xbf"),
        ("x\udc00y", b"x\xed\xb0\x80y"),
        ("\ud83d\ude00", b"\xed\xa0\xbd\xed\xb8\x80"),  # two lone surrogates, not U+1F600
    ],
)
def test_ext_key_encodes_a_lone_surrogate_as_its_three_bytes_instead_of_raising(
    order_id: str, utf8: bytes
) -> None:
    """A JSON escape such as `"\\ud800"` decodes to a lone surrogate, which strict UTF-8
    refuses; Bybit's own ids are ASCII, so the adapter must still get a key, not an error."""
    assert ext_key(order_id) == "ext-" + hashlib.sha256(utf8).hexdigest()[:32]


def test_ext_key_keeps_lone_surrogates_and_what_they_resemble_apart() -> None:
    values = ["\ud800", "\ud801", "\ud83d\ude00", "\U0001f600", "\ufffd", "?", ""]

    assert len({ext_key(value) for value in values}) == len(values)


@pytest.mark.parametrize("term", ["lone surrogate", "three bytes", 'errors="surrogatepass"'])
def test_the_document_defines_ext_key_for_a_lone_surrogate(term: str) -> None:
    """§8.3 owns the `ext_key` definition (C-16.5). Without this clause a second implementation
    written from it could raise on a lone surrogate, or replace it, and key the same order
    differently from this one."""
    assert term in _adopted_rows(_INTERNAL_SCHEMAS_DOC.read_text(encoding="utf-8"))


def test_the_adapter_isolation_guard_sees_the_exchange_name() -> None:
    """The guard below is not vacuous: the rule's own pattern matches the sentence it flagged."""
    assert _adapter_isolation_pattern().search("Bybit's order ids are ASCII") is not None


def test_the_module_text_names_no_exchange_because_the_adapter_isolation_rule_blocks_it() -> None:
    """C-2.2: `cv-adapter-isolation` is an ERROR in the required `sast` check for any exchange
    name outside `exchange/bybit/`, and a docstring in `domain/` counts as much as code."""
    flagged = _adapter_isolation_pattern().findall(_MODULE_SOURCE.read_text(encoding="utf-8"))

    assert flagged == []
