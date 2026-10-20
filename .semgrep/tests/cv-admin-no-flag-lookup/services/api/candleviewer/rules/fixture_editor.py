"""Fixtures for cv-admin-no-flag-lookup: rules/ outside `manager.py` is out of its scope."""


async def editor(flags) -> bool:
    return await flags.value("rules.graph_editor")  # ok: cv-admin-no-flag-lookup
