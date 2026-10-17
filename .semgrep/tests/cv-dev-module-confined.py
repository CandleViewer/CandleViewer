"""Fixtures for cv-dev-module-confined (#2893 S3)."""
import importlib
import importlib.util
import sys

import cvdev  # ruleid: cv-dev-module-confined
import cvdev.account_fixture.wiring  # ruleid: cv-dev-module-confined
import cvdev.account_fixture as fixture  # ruleid: cv-dev-module-confined
import os, cvdev  # ruleid: cv-dev-module-confined
from cvdev import account_fixture  # ruleid: cv-dev-module-confined
from cvdev.account_fixture.wiring import build, REFUSAL  # ruleid: cv-dev-module-confined
from candleviewer.account_fixture_wiring import build_account_fixture  # ok: cv-dev-module-confined
from candleviewer import settings  # ok: cv-dev-module-confined
import cvdevtools  # ok: cv-dev-module-confined
from mycvdev import thing  # ok: cv-dev-module-confined

_DOOR = "cvdev.account_fixture.wiring"  # ruleid: cv-dev-module-confined
_PROSE = "the cvdev package is dev-only"  # ok: cv-dev-module-confined


def lookups() -> object:
    importlib.import_module("cvdev.account_fixture.wiring")  # ruleid: cv-dev-module-confined
    __import__("cvdev")  # ruleid: cv-dev-module-confined
    importlib.util.find_spec("cvdev")  # ruleid: cv-dev-module-confined
    sys.modules.get("cvdev.account_fixture")  # ruleid: cv-dev-module-confined
    return importlib.import_module("candleviewer.settings")  # ok: cv-dev-module-confined
