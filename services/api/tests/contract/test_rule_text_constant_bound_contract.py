"""#5807 (E35): a rule's text constant holds at most 128 characters; contract first.

22 states the bound on the text member of `RuleOperand`'s constant (C-6.1), and the published rule
IR schema (`rule-ir.json`, rendered from the model) states it on both text members of
`Literal_.const`, the decimal text and the plain text. 24 states the refusal and the C-6.3 call in
its section 19 entry. Read from the spec, never a copy (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

import re

from candleviewer.rules.ir.models import MAX_NUMBER_TEXT
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.validator import TEXT_TOO_LONG
from tests.contract._admin_support import ROOT, SPEC, text

#: The ruled bound (#5807), held here as a number of its own.
BOUND = 128
_RAW_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")


def _entry() -> tuple[str, str]:
    """24's section 19 entry for #5807, found by the issue in its heading, never by its number:
    the heading and the entry's text."""
    heading = r"^### 19\.\d+ \d{4}-\d{2}-\d{2} — 22 RuleOperand: .*\(E35, #5807\)$"
    found = re.search(heading, _RAW_24, re.MULTILINE)
    assert found is not None, "24 section 19 holds no entry for #5807"
    return found.group(0), text(_RAW_24.split(found.group(0), 1)[1].split("\n### ", 1)[0])


def test_the_bound_is_the_one_the_save_holds() -> None:
    assert MAX_NUMBER_TEXT == BOUND
    assert TEXT_TOO_LONG == f"A text constant holds at most {BOUND} characters."


def test_rule_operand_states_the_bound_on_its_text() -> None:
    constant = SPEC["components"]["schemas"]["RuleOperand"]["oneOf"][1]["properties"]["const"]
    text_member = {"type": "string", "maxLength": BOUND, "description": TEXT_TOO_LONG}
    assert constant == {"oneOf": [text_member, {"type": "number"}, {"type": "boolean"}]}


def test_the_published_rule_ir_schema_states_the_bound_on_both_text_members() -> None:
    constant = to_json_schema()["$defs"]["Literal_"]["properties"]["const"]
    texts = [member for member in constant["anyOf"] if member.get("type") == "string"]
    assert len(texts) == 2  # the decimal text, which has its pattern, and the plain text
    assert [member["maxLength"] for member in texts] == [BOUND, BOUND]


def test_the_24_entry_states_the_bound_the_refusal_and_the_c63_call() -> None:
    heading, entry = _entry()
    assert heading.endswith(
        f"22 RuleOperand: a text constant holds at most {BOUND} characters (E35, #5807)"
    )
    for stated in (
        f"A text constant in a rule's conditions holds at most {BOUND} characters (a validation"
        " limit), refused at save, validate and compile; stored rules keep loading as before.",
        "`createRule`, `updateRule` and an import answer `422 rule_ir_invalid`",
        "`validateRule` answers `200` with `valid: false`",
        "`compileRule` answers `200` with it in `issues` and `blocks_arming: true`",
        "The refusal writes no audit record and no count, and nothing is stored.",
        "Stored rules and alerts keep loading as before: the bound is not a load rule",
        "Arming runs the validator, so such a version is refused `422 rule_invalid` until a save"
        " shortens the constant",
        "**Not breaking (C-6.3):** it tightens the accepted input on a value nothing well-formed"
        " produces.",
        "the squash title carries no `!` and the body no `BREAKING CHANGE:` footer",
    ):
        assert stated in entry, stated
