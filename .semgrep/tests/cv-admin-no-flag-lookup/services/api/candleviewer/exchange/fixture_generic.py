"""Fixtures for cv-admin-no-flag-lookup in a file with PEP 695 generics, which Semgrep parses
another way (#3549, X03-F4): the rule must hold here too (D10)."""


def first[T](items: list[T]) -> T:
    return items[0]


async def place[T](order: T, flags) -> T:
    if await flags.value("trading.live_enabled"):  # ruleid: cv-admin-no-flag-lookup
        return order
    from candleviewer.admin.flags import default_registry  # ruleid: cv-admin-no-flag-lookup

    return order  # ok: cv-admin-no-flag-lookup
