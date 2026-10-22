"""Hash invariance for typed metric params (#4132): no existing rule's hash moves.

``MetricRef.params`` values became ``bool | int | Decimal | str`` and the canonicaliser gained a
``float`` arm, with no ``IR_HASH_VERSION`` bump: every value that hashed before keeps its bytes.
These are the ``ir_hash`` of every ``tests/fixtures/rule_ir`` document and the ``condition_hash`` of
four with metric params, computed on the base commit (the thirty-rule corpus has its own goldens in
``tests/fixtures/rule_corpus/golden_hashes.json``). A failure here needs a hash version bump.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from candleviewer.rules.ir import Rule, ir_hash, parse_ir_json
from candleviewer.rules.ir.canonical import condition_hash

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rule_ir"
IR_HASHES = {
    "bar_close_trigger": "4b11166140a91771e4eecbcea761de3d63c3b736d984ad87d93353981ea62cac",
    "between": "e6687e09d21945f8846454dcb73806a01b2283a9ff171b1d0b67cb7658dcca7a",
    "deep_nesting": "cb929c56524d1f9a3773f30fc46cbee768ffb42ad976817b989d16e24e628f6d",
    "form_all_of_any_of": "8cca20b31f196d4d678cf9fff835f2337ec41335e8829ee99e0e6bf16a524709",
    "form_simple_0": "b70e0421353562852d9b311eb1db840097e6bf7ceea8f4789ea574e87eb3ea3e",
    "form_simple_1": "11e945962cbab4c492a2cc14a1c9dc86ed676d3bfab6c7cfb5231b92734e6571",
    "form_simple_2": "758d56a5fdbe444e611bafc7fae38f10884e3783fd91b69fb2198bf3aaf733f8",
    "form_simple_3": "a96a31b91423a9550003787094aff56a16556958d28e6ef0ffeabcfa358c5365",
    "form_simple_4": "43ef6fa192a033e1c2525d4a710a8620f54a49b787bdec7428b2e2a7052446ae",
    "in_set": "38c79529b2376cc0b7359cdd7467e9d20b08de2f50f34d20f9668fecce1f4ebe",
    "is_true": "71b3dc3a874681c4573652d8f34a7f07fc8d0543f27c5d95cf8e54fe37ad3f8d",
    "large_decimal": "63b049df4f2e4b18eede15ed97f77051bb395286c5f24d78363aa4c42e2d723c",
    "max_children_32": "b733d9eb4437cea1dafc62695e2adfcba1ac9c6c8b5c92248b96def8f44d8ffc",
    "max_operands_8": "45e138229c0c2ed23d45292a0c00d3787c73a8179a831d1de50a5b0eb689f6df",
    "metric_change_trigger": "4a82eabe77dcb7832d9fa07b7e7e6689df9e3ae30e34920dfd20d89d7a1f6859",
    "mixed_0": "816aa61e963eee5d30c526f45396fbb01d7ef15fef669a9c5564eba91fafee13",
    "mixed_1": "6d085071ce7ecf03599579832937b3a0183316ec9fa673a59344607723c88e07",
    "mixed_2": "1e32a206a801776a1a48821a4f81dfbeb23199246b3dc4700ea5040213f380ba",
    "mixed_3": "5b4da2d217db315ce87def63def14caba9371f6e9541b57c88fa2131e921a79d",
    "mixed_4": "beafd92c086d45bd54d4e1d644b17817f6089813ce9e893e23b2a456fd3554ef",
    "mixed_5": "6316b91b62c75c1ee73bee7a26e664e721ab9802f75343fb99e21754ad4a9d1f",
    "mixed_6": "7405f589c4a598a71cdc4d5edf742ef1a6951117c1f54825273b15a41df054b0",
    "n_of": "2d24431e990fddf7e43751f7c913252d27ac9949395ef058141dbe65d9e3739f",
    "nested_arith": "4dc7e06ed41bc279bbbe92ac4201774a2a1c8ed67acb1cd6c727f55ad370a674",
    "schedule_trigger": "8343972bbd8f8ddf4094de138bbc2bc26113f07d31264f746678855eac5c2e11",
    "shared_node_fanout": "f0a37165a91c68b544a2d122d49de47d1b154245c8802aea38d9c979ecd5a20e",
    "small_decimal": "4af11f64d9bda8261f4e692457f90f3b4ac5876f2c81bf1eeb863441f0a1bda2",
    "temporal_occurred_within": "d7a97a42a01a1a84876a62ee3d6d3d80b7c9da293b86c93b7c74ae1d346efcb1",
    "temporal_sustained": "cf754c1365d6c8c549bfdbe640c5190c6277c14d49625fba151cfb34a070c6c6",
    "ten_actions": "3a051f71ea4f813b58cf9e125d6b772a8c335da52e239bd29f61ebf170ad43e5",
    "timer_trigger": "161a4e5a80311f9b62d1e201f5527043c0bf3a859643e5767c8722ca59588fbb",
    "unicode_name": "a0fe40e2db27f7efaae3ba6abaaca48e91d0f7809dd80095e2019271bea092cc",
}
CONDITION_HASHES = {
    "form_simple_0": "5f0fee708fe42a8d04b1ad536aa0786667ac9b98dca04ba6b19e8e38ae18d642",
    "max_children_32": "f73251a19632996294704ca17c9ddc4a1d7f1cd3b097d82a104c5616943534a3",
    "mixed_0": "048afd34c22578388029aedb40d9685996ac9f186755bb0ffa4edef9ad85e065",
    "shared_node_fanout": "282a932545757ef09e6bf295913878e874f1f91866d135eac476ccd807d14a74",
}


def _text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(IR_HASHES))
def test_ir_hash_existing_fixture_keeps_its_base_hash(name: str) -> None:
    text = _text(name)
    assert ir_hash(json.loads(text)) == ir_hash(parse_ir_json(text)) == IR_HASHES[name]


@pytest.mark.parametrize("name", sorted(CONDITION_HASHES))
def test_condition_hash_existing_fixture_keeps_its_base_hash(name: str) -> None:
    rule = Rule.model_validate(json.loads(_text(name)))
    assert condition_hash(rule.model_dump()) == CONDITION_HASHES[name]
