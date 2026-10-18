"""#3272, #3367, #3471: turbo inputs name every file the tests, ui's build and its typecheck read.

#3272: the root `test` and `test:cov` inputs are `src/**`, `test/**` and `tests/**`, but ui's
tests also read its token sources (`tokens/**`) and token build scripts (`scripts/**`), so a cached
run could be replayed after such a change. `packages/ui/turbo.json` adds the two globs for that
package only. Its `inputs` replace the root's unless they start with `$TURBO_EXTENDS$` (turbo 2.11),
and with no package file the root's apply: the effective list is resolved the way turbo does it.

#3367: the tests also read `vitest.config.mjs` and the shared preset it imports, `tsconfig.json` and
the packages/config files it extends (vite's esbuild transform reads them), `contrast/`, the
Storybook decorator in `.storybook/`, and outside the package `tools/contrast/` and
`tools/style-dictionary/` (the token formats, which `ui#build` imports too, and the package.json
that makes Node load them as ES modules). A `$TURBO_ROOT$/` glob is anchored at the checkout root.
The reads are derived from the sources: every `./` or `../` string literal in the tests and the
build scripts and, in turn, in each module those literals name (a tools/ module a test imports
reads files too), the preset import and the tsconfig `extends` chain, so a new read needs an input.

`--filter=@candleviewer/ui...[origin/main]` maps each changed file to the package that holds it, so
a change only under tools/ selected no package and unit-frontend skipped the ui tests. A `tag:`
selector with a git range matches the changed files against the task's inputs instead (turbo 2.11,
no future flag): ui's `test:cov` carries the lane's tag and the lane adds that selector.

#3471: every other suite that spreads the preset (`@candleviewer/config/vitest`) lists the same
runner reads, its `vitest.config.mjs`, the preset and the tsconfig chain. The preset was in ui's
hash only: the one packages/config task the suites depend on (`^build`) hashes only `src/` and
`package.json`. The suites are derived from the workspace globs; packages/config's own suite
imports the preset by a relative path, so the scan leaves it out.

ui's `typecheck` reads the token formats' declarations (its token-build tests import the
formats), derived from the static imports in the files its tsconfig includes; the tsconfig chain
reaches its hash through `^typecheck`. The typecheck lane's `...[origin/main]` filter selected no
package for a change only there, so ui's typecheck carries a tag and the lane adds its selector."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
UI = "packages/ui"
EXTENDS = "$TURBO_EXTENDS$"
TURBO_ROOT = "$TURBO_ROOT$/"
JS_LANE = ROOT / ".github" / "workflows" / "_job-js.yml"
TAG = "unit-frontend"
#: A `./` or `../` string literal without a glob: an import specifier or a path a test reads.
LITERAL = re.compile(r"""["'](\.\.?/[^"'*\s]*)["']""")
SOURCES = {".js", ".mjs", ".ts", ".tsx"}
#: What the package's tasks write: never an input, and present only after a local run.
OUTPUTS = ("build", "coverage", "dist", "node_modules", "storybook-static")
#: Read without a literal: Node reads it to load the formats as ES modules, and the token-build
#: test copies it with path.join segments.
FORMATS_MANIFEST = "tools/style-dictionary/package.json"
#: A vitest config's import of a packages/config module by its package name.
CONFIG_IMPORT = re.compile(r"""from ["'](@candleviewer/config/[^"']+)["']""")
#: A static import or re-export of a relative module: tsc reads the file it resolves to.
STATIC_IMPORT = re.compile(
    r"""^\s*(?:import|export)\b[^"';]*["'](\.\.?/[^"']+)["']""", re.MULTILINE
)
#: What tsc reads for a `.js` or `.mjs` specifier: the TypeScript source, else its declarations.
DECLARATIONS = {".js": (".ts", ".tsx", ".d.ts"), ".mjs": (".mts", ".d.mts")}
TS = {".ts", ".tsx"}  # what tsc includes without allowJs


def _root_inputs(task: str) -> list[str]:
    tasks: dict[str, Any] = json.loads((ROOT / "turbo.json").read_text(encoding="utf-8"))["tasks"]
    inputs: list[str] = tasks[task]["inputs"]
    return inputs


def _tasks(package: str) -> dict[str, Any]:
    """The tasks of the package's turbo.json, none when it has no such file."""
    path = ROOT / package / "turbo.json"
    if not path.is_file():
        return {}
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert config.get("extends") == ["//"], "a package turbo.json extends the root"
    tasks: dict[str, Any] = config.get("tasks", {})
    return tasks


def _inputs(package: str, task: str) -> list[str]:
    own: list[str] | None = _tasks(package).get(task, {}).get("inputs")
    if own is None:
        return _root_inputs(task)
    return _root_inputs(task) + own[1:] if own[:1] == [EXTENDS] else own


def _anchored(pattern: str, package: str) -> str:
    """An input glob of the package as a checkout-relative glob, keeping a leading `!`."""
    bang, body = ("!", pattern[1:]) if pattern.startswith("!") else ("", pattern)
    anchored = body.removeprefix(TURBO_ROOT) if body.startswith(TURBO_ROOT) else f"{package}/{body}"
    return bang + anchored


def _glob(pattern: str) -> re.Pattern[str]:
    """turbo's glob syntax as these inputs use it: `**` spans folders, `*` stays in one and
    `{a,b}` matches either."""
    assert not set(pattern) & set("[]?"), f"extend _glob before using {pattern!r}"
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
    regex = re.sub(r"\\\{(.*?)\\\}", lambda m: f"(?:{m[1].replace(',', '|')})", regex)
    return re.compile(regex.replace(r"\*", "[^/]*"))


def _covered(path: str, inputs: list[str], package: str = UI) -> bool:
    """Whether turbo hashes the checkout-relative `path`, or anything in it for a folder."""
    target = f"{path}/x" if (ROOT / path).is_dir() else path
    globs = [_anchored(pattern, package) for pattern in inputs]
    hit = [_glob(g.removeprefix("!")).fullmatch(target) is not None for g in globs]
    included = any(h for g, h in zip(globs, hit, strict=True) if not g.startswith("!"))
    return included and not any(h for g, h in zip(globs, hit, strict=True) if g.startswith("!"))


def _on_disk(path: str) -> str | None:
    """`path`, or the TypeScript source a `.js` specifier names, when either exists."""
    for candidate in (path, re.sub(r"\.js$", ".ts", path), re.sub(r"\.js$", ".tsx", path)):
        if (ROOT / candidate).exists():
            return candidate
    return None


def _literal_reads(folder: str) -> set[str]:
    """The files and folders that the `./` and `../` literals name in the sources under `folder`,
    then in each source file they name, and so on."""
    queue = [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / folder).rglob("*"))]
    scanned: set[str] = set()
    reads: set[str] = set()
    while queue:
        source = queue.pop()
        if source in scanned or PurePosixPath(source).suffix not in SOURCES:
            continue
        scanned.add(source)
        for literal in LITERAL.findall((ROOT / source).read_text(encoding="utf-8")):
            found = _on_disk(posixpath.normpath(posixpath.join(posixpath.dirname(source), literal)))
            if found is None or PurePosixPath(UI).is_relative_to(found):  # the package or above
                continue
            if not any(PurePosixPath(found).is_relative_to(f"{UI}/{out}") for out in OUTPUTS):
                reads.add(found)
                queue.append(found)
    return reads


def _config_export(specifier: str) -> str:
    """The packages/config file a `@candleviewer/config/...` specifier names (its exports map)."""
    manifest = json.loads((ROOT / "packages/config/package.json").read_text(encoding="utf-8"))
    target: str = manifest["exports"]["." + specifier.removeprefix("@candleviewer/config")]
    return posixpath.normpath(posixpath.join("packages/config", target))


def _suites() -> list[str]:
    """The workspace packages whose vitest config imports a packages/config module by name."""
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    configs = sorted(
        path for glob in workspace["packages"] for path in ROOT.glob(f"{glob}/vitest.config.*")
    )
    return [
        path.parent.relative_to(ROOT).as_posix()
        for path in configs
        if CONFIG_IMPORT.search(path.read_text(encoding="utf-8"))
    ]


def _vitest_config(package: str) -> str:
    (config,) = (ROOT / package).glob("vitest.config.*")
    return config.relative_to(ROOT).as_posix()


def _preset(package: str) -> str:
    """The shared Vitest preset that the package's vitest config imports."""
    found = CONFIG_IMPORT.findall((ROOT / _vitest_config(package)).read_text(encoding="utf-8"))
    assert len(found) == 1, found
    return _config_export(found[0])


def _tsconfig_chain(package: str) -> list[str]:
    """The package's tsconfig.json and the files its `extends` chain reads; none without one."""
    chain = [f"{package}/tsconfig.json"]
    if not (ROOT / chain[0]).is_file():
        return []
    for _ in range(5):
        parent = json.loads((ROOT / chain[-1]).read_text(encoding="utf-8")).get("extends")
        if parent is None:
            return chain
        here = posixpath.dirname(chain[-1])
        chain.append(
            _config_export(parent)
            if parent.startswith("@candleviewer/config/")
            else posixpath.normpath(posixpath.join(here, parent))
        )
    raise AssertionError(f"tsconfig extends chain too long: {chain}")


@pytest.mark.parametrize("task", ["test", "test:cov"])
def test_ui_tests_rerun_when_only_tokens_or_scripts_change(task: str) -> None:
    inputs = _inputs(UI, task)
    assert {"tokens/**", "scripts/**"} <= set(inputs)
    assert set(_root_inputs(task)) <= set(inputs), "keeps src, test, tests and the .md exclusion"


@pytest.mark.parametrize("task", ["test", "test:cov"])
def test_ui_test_inputs_cover_every_path_the_tests_name(task: str) -> None:
    reads = _literal_reads(f"{UI}/test")
    # An empty scan proves nothing: the tests read these today.
    assert {
        f"{UI}/contrast/data-ink-matrix.json",
        f"{UI}/.storybook/withThemeRuntime.tsx",
        "tools/contrast/encodings.json",
        "tools/contrast/pairs.mjs",  # no test names it: data-ink-lib.mjs imports it
        "tools/style-dictionary/formats/json-flat.js",
    } <= reads
    inputs = _inputs(UI, task)
    assert sorted(path for path in reads | {FORMATS_MANIFEST} if not _covered(path, inputs)) == []


SUITES = _suites()


def test_the_scan_finds_every_suite_that_spreads_the_preset() -> None:
    # An empty scan proves nothing: these suites spread the preset today.
    packages = [f"packages/{name}" for name in ("chart-engine", "fixtures", "protocol", "ui")]
    assert {"apps/desktop", "apps/web", *packages} <= set(SUITES)


@pytest.mark.parametrize("task", ["test", "test:cov"])
@pytest.mark.parametrize("package", SUITES)
def test_vitest_suites_hash_the_runner_config_and_what_it_loads(package: str, task: str) -> None:
    reads = [_vitest_config(package), _preset(package), *_tsconfig_chain(package)]
    assert len(reads) in (2, 5), reads  # the config, the preset and three tsconfig files, if any
    inputs = _inputs(package, task)
    assert [path for path in reads if not _covered(path, inputs, package)] == []


def test_ui_build_inputs_cover_what_the_build_reads() -> None:
    reads = _literal_reads(f"{UI}/scripts")
    assert "tools/style-dictionary/formats/json-flat.js" in reads
    inputs = _inputs(UI, "build")
    assert set(_root_inputs("build")) <= set(inputs), "keeps src, tokens, scripts and tsup.config"
    every = sorted(reads | {FORMATS_MANIFEST, *_tsconfig_chain(UI)})
    assert [path for path in every if not _covered(path, inputs)] == []


def _typecheck_reads() -> set[str]:
    """The files outside packages/ui that its typecheck reads: what each relative module that a
    TypeScript file its tsconfig includes imports statically resolves to."""
    include = json.loads((ROOT / UI / "tsconfig.json").read_text(encoding="utf-8"))["include"]
    tops = sorted({ROOT / UI / entry.split("/")[0] for entry in include})
    files = [file for top in tops for file in ([top] if top.is_file() else sorted(top.rglob("*")))]
    reads: set[str] = set()
    for source in [file.relative_to(ROOT).as_posix() for file in files if file.suffix in TS]:
        for specifier in STATIC_IMPORT.findall((ROOT / source).read_text(encoding="utf-8")):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), specifier))
            stem, suffix = posixpath.splitext(target)
            candidates = [stem + ext for ext in DECLARATIONS.get(suffix, ())]
            found = [path for path in candidates if (ROOT / path).is_file()]
            if found and not PurePosixPath(target).is_relative_to(UI):
                reads.add(found[0])
    return reads


def test_ui_typecheck_hashes_the_declarations_it_reads_outside_the_package() -> None:
    reads = _typecheck_reads()
    # An empty scan proves nothing: ui's token-build tests import the formats today.
    assert "tools/style-dictionary/formats/json-flat.d.ts" in reads
    inputs = _inputs(UI, "typecheck")
    assert set(_root_inputs("typecheck")) <= set(inputs), "keeps the sources and tsconfig files"
    assert sorted(path for path in reads if not _covered(path, inputs)) == []


def _lane_filters(job: str) -> list[list[str]]:
    """The `--filter=` arguments of each step of a js lane job that passes any, sorted per step."""
    steps = yaml.safe_load(JS_LANE.read_text(encoding="utf-8"))["jobs"][job]["steps"]
    runs = [str(step.get("run", "")) for step in steps]
    return [sorted(re.findall(r"--filter=(\S+)", run)) for run in runs if "--filter=" in run]


def test_unit_frontend_selects_the_ui_tests_by_their_inputs() -> None:
    # The name filter maps a changed file to its package and tools/ is in none, so a change only
    # there selected nothing; the tag selector matches it against ui's test:cov inputs.
    assert _tasks(UI)["test:cov"].get("tags") == [TAG]
    turbo, manifest = _lane_filters("unit-frontend")
    assert turbo == manifest, "the coverage manifest records what the turbo run selects"
    assert f"'tag:{TAG}[origin/main]'" in turbo


def test_typecheck_selects_ui_typecheck_by_its_inputs() -> None:
    # `...[origin/main]` maps a changed file to its package and tools/ is in none; the tag selector
    # matches a change to the formats' declarations against ui's typecheck inputs.
    assert _tasks(UI)["typecheck"].get("tags") == ["typecheck"]
    assert _lane_filters("typecheck") == [["'...[origin/main]'", "'tag:typecheck[origin/main]'"]]


def test_turbo_stays_pinned_to_one_2_x_release_from_2_11() -> None:
    # The lane rests on a documented turbo rule (2.11 docs/reference/run.mdx, "Filtering by tag"):
    # a git-qualified tag selector matches the changed files against the task's inputs. An exact
    # pin makes every turbo bump a reviewed change, and a new major must re-check that rule here.
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    version = manifest["devDependencies"]["turbo"]
    found = re.fullmatch(r"2\.(\d+)\.\d+", version)
    assert found is not None and int(found[1]) >= 11, version
