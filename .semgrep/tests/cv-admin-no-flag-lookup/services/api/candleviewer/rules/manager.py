"""Fixtures for cv-admin-no-flag-lookup: the rule arm gate (AC-ADM-14)."""


async def arm(rule, flags) -> bool:
    return await flags.value("rules.graph_editor")  # ruleid: cv-admin-no-flag-lookup
