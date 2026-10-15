"""#2396: the server's `sub` shape check reads a topic name exactly as §13
`common.schema.json#/$defs/topic` does, so a refused name is one the schema refuses too."""

from __future__ import annotations

from candleviewer.ws.topics import TOPIC_MAX_LEN, TOPIC_NAME_RE, is_topic_name
from tests.contract.ws._harness import SCHEMAS


def test_contract_topic_name_check_equals_the_schema_topic_def() -> None:
    topic = SCHEMAS["cv://ws/v1/common.schema.json"]["$defs"]["topic"]
    assert (TOPIC_NAME_RE.pattern, TOPIC_MAX_LEN) == (topic["pattern"], topic["maxLength"])
    assert topic["minLength"] == 1 and not is_topic_name("")
