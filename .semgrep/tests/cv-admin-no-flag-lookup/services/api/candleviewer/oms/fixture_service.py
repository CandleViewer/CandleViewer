"""Fixtures for cv-admin-no-flag-lookup in oms/: no flag service, callee or receiver (AC-ADM-14)."""


class Gate:
    def __init__(self, flags, toggles) -> None:
        self._flags, self._toggles = flags, toggles

    async def admit(self) -> bool:
        return not await self._flags.value("x")  # ruleid: cv-admin-no-flag-lookup

    def enabled(self, name: str) -> bool:
        return feature_enabled(name)  # ruleid: cv-admin-no-flag-lookup

    def on(self) -> bool:
        return self._toggles.is_enabled()  # ruleid: cv-admin-no-flag-lookup

    def account(self, order) -> str:
        return order.account_id  # ok: cv-admin-no-flag-lookup


def feature_enabled(name: str) -> bool:
    return False
