"""Planted must-fail bypass probes for the M2 CI guard (AST-only: parsed, **never executed**).

Every snippet the r4 and boundary reviews listed is here. Each must be flagged in an unrelated
module (oms/), both inside a free function and inside a class method, so `self`-rooted chains
are exercised (R2).
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from tests.unit.credentials_m2._m2_guard import m2_violations

#: name -> snippet (expressions/statements; free names are probe parameters).
PROBES: dict[str, str] = {
    # r4 reviewer probe (closure walk) and its pieces
    "closure_walk": (
        "borrow = ctx.exchange_bybit._credentials._CredentialBorrower__borrow\n"
        "b = dict(zip(borrow.__code__.co_freevars, borrow.__closure__))['resolve']"
        ".cell_contents()\n"
        "row = await b._load(key_id)\n"
        "kek = next(v for v in vars(b).values() if type(v).__name__ == 'LoadedKek')\n"
        "e = b.flush_cache.__func__.__globals__['env']\n"
        "e.open_(kek.unwrap_dek(row.dek_ref, credential_id=row.id), row.secret_enc, aad)"
    ),
    "forged_ticket": "b._tickets.add(t := object())",
    "direct_unwrap": "dek = svc._broker._kek.unwrap_dek(ref, credential_id=i)",
    "facade_cell": "svc = ctx.secrets.health.__closure__[0].cell_contents",
    "gc_walk": "import gc\nsvc = gc.get_referents(ctx.secrets.health)[0]",
    "gc_alias": "import gc as g\nsvc = g.get_referents(f)",
    "dek_cache": "deks = broker._cache._items",
    "alias_from": "from candleviewer import secrets\nsecrets._envelope.open_(k, b, a)",
    "alias_rel": "from .. import secrets as s\ns._rotation.RotatingBroker",
    "dyn_import": "import importlib\nk = importlib.import_module('candleviewer.secrets._kek')",
    "dunder_import": "k = __import__('candleviewer.secrets._kek')",
    "sys_modules": "import sys\nk = sys.modules['candleviewer.secrets._kek']",
    "sys_modules_get": "import sys\nk = sys.modules.get('candleviewer.secrets._kek')",
    "find_spec": "import importlib.util\nimportlib.util.find_spec('candleviewer.secrets._kek')",
    "root_pkg_chain": "import candleviewer.oms\nb = candleviewer.secrets.broker",
    "vars_foreign": "v = vars(ctx.secrets)",
    "dict_foreign": "v = ctx.exchange_bybit.__dict__",
    "ctx_private": "c = ctx.exchange_bybit._credentials",
    "getclosurevars": "import inspect\ninspect.getclosurevars(ctx.secrets.health)",
    "getclosurevars_from": "from inspect import getclosurevars\ngetclosurevars(f)",
    "getmembers": "import inspect\nm = inspect.getmembers(svc)",
    "admin_meta_elsewhere": (
        "await ctx.admin.secrets.rewrap_deks(2, actor_user_id='u', actor_role='owner')"
    ),
    "mint_elsewhere": "from candleviewer.secrets import mint_borrower\nmint_borrower(s, 'x')",
    # boundary review: R1 literal-name reflection
    "getattr_closure": "x = getattr(ctx.secrets.health, '__closure__')",
    "getattr_mangled": "x = getattr(borrower, '_CredentialBorrower__borrow')",
    "getattr_broker": "x = getattr(svc, '_broker', None)",
    "getattr_kek": "x = getattr(broker, '_kek')",
    "getattr_self_attr": "x = getattr(f, '__self__')",
    "setattr_sink": "setattr(svc, '_audit_sink', noop)",
    "getattr_ctx_private": "x = getattr(ctx.exchange_bybit, '_credentials')",
    "attrgetter": "import operator\nx = operator.attrgetter('_broker._kek')(svc)",
    "obj_getattribute": "x = object.__getattribute__(svc, '_broker')",
    "getattr_static": "import inspect\nx = inspect.getattr_static(svc, '_broker')",
    # R3/R4 audit sink replacement / writes through AppContext
    "emit_assign": "ctx.audit.writer.emit = noop",
    "emit_type_assign": "type(ctx.audit.writer).emit = noop",
    "writer_assign": "context.audit._writer = w",
    "request_ctx_private": "c = request.app.state.ctx.exchange_bybit._credentials",
    "delattr_ctx": "delattr(ctx.audit, 'writer')",
    # R5 frames / tracebacks
    "tb_locals": "s = exc.__traceback__.tb_next.tb_frame.f_locals['self']",
    "getframe": "import sys\nf = sys._getframe(1).f_locals",
    "currentframe": "import inspect\nf = inspect.currentframe().f_back",
    "capture_locals": (
        "import traceback\ntraceback.TracebackException.from_exception(e, capture_locals=True)"
    ),
    "dict_tracebacks": "import structlog\np = structlog.processors.dict_tracebacks",
    "exc_dict_transformer": "import structlog\nt = structlog.tracebacks.ExceptionDictTransformer()",
    "show_locals": "t = transformer(show_locals=True)",
    # other cheap introspection
    "getstate": "s = borrower.__getstate__()",
    "reduce_ex": "s = borrower.__reduce_ex__(2)",
    "defaults": "d = f.__defaults__",
    "wrapped": "w = f.__wrapped__",
    # R8 last hop / custody literals
    "open_direct": "x = env.open_(k, b, a)",
    "cred_aad_direct": "x = env.cred_aad('live', a, c, 'secret')",
    "rewrap_direct": "await broker.rewrap_all(2)",
    "flush_cache": "broker.flush_cache()",
    "creds_literal": "p = '/run/credentials/cv/kek'",
    "kek_env_literal": "v = os.environ['CV_KEK_HANDLE']",
    "kek_handle_attr": "p = settings.kek_handle",
}

#: Self-rooted chains (R2): only caught when the guard checks the *immediate* receiver.
SELF_PROBES: dict[str, str] = {
    "self_broker_kek": "x = self.svc._broker._kek",
    "self_dek_cache": "x = self.broker._cache._items",
    "cls_require": "x = cls.svc._require()",
    "self_broker_dict": "x = self.broker.__dict__",
    "self_audit_sink_write": "self.svc._audit_sink = noop",
    "self_ctx_private": "x = self.ctx.exchange_bybit._credentials",
}

_PARAMS = "ctx, key_id, t, row, f, svc, broker, ref, i, k, b, a, s, aad, borrower, noop, w, "
_PARAMS += "request, exc, e, transformer, env, c, os, settings, context"


def _free(src: str) -> ast.Module:
    return ast.parse(f"async def probe({_PARAMS}):\n" + textwrap.indent(src, "    "))


def _method(src: str) -> ast.Module:
    body = textwrap.indent(src, "        ")
    return ast.parse(
        "class Probe:\n"
        f"    async def probe(self, {_PARAMS}):\n{body}\n"
        f"    @classmethod\n    async def cprobe(cls, {_PARAMS}):\n{body}\n"
    )


@pytest.mark.parametrize("name", sorted(PROBES))
def test_free_function_probe_is_flagged(name: str) -> None:
    assert m2_violations("oms/credential_probe.py", _free(PROBES[name])), name


@pytest.mark.parametrize("name", sorted(PROBES))
def test_class_method_probe_is_flagged(name: str) -> None:
    assert m2_violations("oms/credential_probe.py", _method(PROBES[name])), name


@pytest.mark.parametrize("name", sorted(SELF_PROBES))
def test_self_rooted_chain_is_flagged(name: str) -> None:
    src = SELF_PROBES[name].replace("cls.", "self.")
    assert m2_violations("oms/credential_probe.py", _method(src)), name
    if name.startswith("cls_"):
        assert m2_violations("oms/credential_probe.py", _method(SELF_PROBES[name])), name


@pytest.mark.parametrize(
    "src",
    [
        "from candleviewer.secrets import SecretsService\n"
        "class ReplaySecrets(SecretsService):\n"
        "    async def _audit(self, a, f):\n        return None",
        "import candleviewer.secrets as m2\nclass X(m2.CredentialBorrower):\n    pass",
        "from candleviewer.secrets.broker import CredentialBroker\nclass B(CredentialBroker): ...",
    ],
)
@pytest.mark.parametrize("where", ["exchange/bybit/x.py", "admin/x.py", "oms/x.py"])
def test_subclassing_an_m2_class_is_flagged(src: str, where: str) -> None:
    assert m2_violations(where, ast.parse(src))


def test_owner_may_use_its_own_private_ctx_field() -> None:
    src = "c = ctx.exchange_bybit._credentials"
    assert not m2_violations("exchange/bybit/x.py", ast.parse(src))
    assert m2_violations("exchange/base/x.py", ast.parse(src))  # exact owner, not 'exchange'


#: R10 (#2339, C-2.7): plaintext stays in `secrets/`. Flagged in every module, the adapter too.
PLAINTEXT_PROBES: dict[str, str] = {
    "borrow": "out = await borrower.with_credentials(key_id, fn, purpose='sign_rest')",
    "borrow_handle": "h = broker.borrow_handle('exchange_adapter')",
    "reveal_attr": "v = signed.api_secret.reveal()",
    "reveal_name": "v = s.reveal()",
    "reveal_getattr": "v = getattr(s, 'reveal')()",
    "reveal_methodcaller": "import operator\nv = operator.methodcaller('reveal')(s)",
    "settings_secret_value": "def f(s):\n    return s.bybit_api_secret._secret_value",
    "settings_secret_getter": "def f(s):\n    return s.bybit_api_secret.get_secret_value()",
    "settings_key_reflect": "def f(s):\n    return getattr(s, 'bybit_api_key')",
    "environ_subscript": "import os\n\ndef f():\n    return os.environ['CV_BYBIT_API_SECRET']",
    "environ_get": "import os\n\ndef f():\n    return os.getenv('CV_BYBIT_API_KEY')",
}
#: R10 in the exchange adapter: no credential plaintext holder and no MAC primitive.
ADAPTER_PROBES: dict[str, str] = {
    "secretstr_import": "from pydantic import SecretStr",
    "secretstr_attr": "import pydantic\nv = pydantic.SecretStr(s)",
    "secretstr_name": "v = SecretStr(s)",
    "get_secret_value": "v = s.get_secret_value()",
    "hmac_import": "import hmac",
    "hmac_alias": "import hmac as h",
    "hmac_from": "from hmac import new",
    "hmac_compare": "from hmac import compare_digest",
    "crypto_hmac": "from cryptography.hazmat.primitives import hmac",
    "crypto_hmac_module": "from cryptography.hazmat.primitives.hmac import HMAC",
}
_ANYWHERE = ["oms/credential_probe.py", "exchange/bybit/credential_probe.py", "admin/x.py"]
_ADAPTER = ["exchange/bybit/credential_probe.py", "exchange/base/x.py"]


@pytest.mark.parametrize("where", _ANYWHERE)
@pytest.mark.parametrize("name", sorted(PLAINTEXT_PROBES))
def test_plaintext_probe_is_flagged_everywhere(name: str, where: str) -> None:
    assert m2_violations(where, _free(PLAINTEXT_PROBES[name])), name
    assert m2_violations(where, _method(PLAINTEXT_PROBES[name])), name


@pytest.mark.parametrize("where", _ADAPTER)
@pytest.mark.parametrize("name", sorted(ADAPTER_PROBES))
def test_adapter_probe_is_flagged_in_the_exchange_adapter(name: str, where: str) -> None:
    assert m2_violations(where, _free(ADAPTER_PROBES[name])), name


@pytest.mark.parametrize("where", ["settings.py", "auth/x.py", "audit/x.py"])
def test_adapter_rules_stay_inside_the_adapter(where: str) -> None:
    src = "import hmac\nfrom pydantic import SecretStr\nv = SecretStr(s).get_secret_value()"
    assert not m2_violations(where, ast.parse(src))


def test_reveal_allowed_only_for_the_signer_header_value() -> None:
    """The one reviewed `.reveal()`: the key id M2 returns, for the request header."""
    ok = "k = signed.api_key.reveal()"
    assert not m2_violations("exchange/bybit/signer.py", ast.parse(ok))
    assert m2_violations("exchange/bybit/rest.py", ast.parse(ok))  # exact file only
    assert m2_violations("exchange/bybit/signer.py", ast.parse("k = signed.secret.reveal()"))


def test_self_own_private_attributes_are_not_flagged() -> None:
    src = "class S:\n    def f(self):\n        return self._broker, self._cache, self.__dict__"
    assert not m2_violations("oms/x.py", ast.parse(src))


#: The offline break-glass proof (#2119) is admin-only metadata like `verify_kek_possession`:
#: the exchange adapter, the other M2 importer, reaches it by no name, alias, attribute or literal.
ADMIN_ONLY_PROBES: dict[str, str] = {
    "proof_name": "from candleviewer.secrets import prove_kek_possession\n"
    "r = await prove_kek_possession(s, k)",
    "proof_alias": "from candleviewer.secrets import prove_kek_possession as p\nr = await p(s, k)",
    "proof_star": "from candleviewer.secrets import *\nr = await prove_kek_possession(s, k)",
    "proof_attr": "import candleviewer.secrets as m\nr = await m.prove_kek_possession(s, k)",
    "proof_getattr": "import candleviewer.secrets as m\n"
    "r = await getattr(m, 'prove_kek_possession')(s, k)",
}


@pytest.mark.parametrize("where", ["exchange/bybit/x.py", "oms/x.py"])
@pytest.mark.parametrize("name", sorted(ADMIN_ONLY_PROBES))
def test_admin_only_probe_is_flagged_outside_admin(name: str, where: str) -> None:
    assert m2_violations(where, _free(ADMIN_ONLY_PROBES[name])), name


@pytest.mark.parametrize("name", sorted(ADMIN_ONLY_PROBES))
def test_admin_may_prove_kek_possession(name: str) -> None:
    assert not m2_violations("admin/wiring.py", _free(ADMIN_ONLY_PROBES[name])), name
