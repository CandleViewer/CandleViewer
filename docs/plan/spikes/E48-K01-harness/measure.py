"""E48-K01 CI harness (throwaway spike code, not product).

Builds a 20-page fixture with each docs candidate inside `docker run --network=none`;
dependencies are installed beforehand in a networked container. Writes
build/reports/docs-spike.json.
"""
import json
import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path

# the Dockerfile.api pin at the time of E48-K01; the results were measured on this image
PY = "python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"
# Docker Hub index digest for node:24-slim, verified via registry API 2026-10-04
NODE = "node:24-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6"
RUNS = 3
ROOT = Path(os.environ.get("WORK", "/tmp/docs-spike")).resolve()
SPEC = Path("docs/plan/22-api-openapi.yaml").resolve()
INSTALL_NPM = "npm install --no-audit --no-fund"


def pages(n=20):
    mer = "```mermaid\ngraph TD; A-->B; B-->C;\n```\n"
    for i in range(1, n + 1):
        body = f"# Page {i}\n\nLorem ipsum braces and angle text.\n\n" + "para\n\n" * 40
        body += "```python\nprint('x')\n```\n\n" + (mer if i % 4 == 0 else "")
        yield f"page{i:02d}.md", body


def docker(image, workdir, cmd, offline):
    net = "--network=none" if offline else ""
    argv = f"docker run --rm {net} -v {workdir}:/w -w /w {image} sh -c".split()
    return subprocess.run([*argv, cmd], capture_output=True, text=True)


def size(p):
    p = Path(p)
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def write(d, name, text):
    (d / name).parent.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def pkg(deps, extra=None):
    return json.dumps({"name": "s", "private": True, "dependencies": deps, **(extra or {})})


def scaffold():
    c = {}
    d = ROOT / "mkdocs"
    for n, b in pages():
        write(d / "docs", n, b)
    write(d, "mkdocs.yml", "\n".join([
        "site_name: s", "theme:", "  name: material", "plugins:", "  - search",
        "markdown_extensions:", "  - pymdownx.superfences:", "      custom_fences:",
        "        - name: mermaid", "          class: mermaid",
        "          format: !!python/name:pymdownx.superfences.fence_code_format", ""]))
    c["mkdocs-material"] = dict(
        image=PY, dir=d, out="out",
        install="pip install --no-cache-dir --target /w/deps 'mkdocs<2' mkdocs-material",
        build="PYTHONPATH=/w/deps python -m mkdocs build -q -d out")

    d = ROOT / "docusaurus"
    for n, b in pages():
        write(d / "docs", n, b.replace("```mermaid", "```text"))
    write(d, "package.json", pkg({"@docusaurus/core": "3.9.2", "@docusaurus/preset-classic": "3.9.2",
                                  "react": "^19", "react-dom": "^19"},
                                 {"overrides": {"webpack": "5.99.9"}}))  # newer webpack rejects webpackbar ProgressPlugin opts
    write(d, "docusaurus.config.js", (
        "module.exports={title:'s',url:'http://x',baseUrl:'/',onBrokenLinks:'warn',"
        "presets:[['classic',{docs:{routeBasePath:'/',sidebarPath:false},blog:false,pages:false}]]};"))
    c["docusaurus"] = dict(image=NODE, dir=d, out="out", install=INSTALL_NPM,
                           build="DO_NOT_TRACK=1 npx docusaurus build --out-dir out")

    d = ROOT / "starlight"
    for n, b in pages():
        write(d / "src/content/docs", n, f"---\ntitle: {n}\n---\n" + b.split("\n", 1)[1])
    write(d, "package.json", pkg({"astro": "^5", "@astrojs/starlight": "^0.35"}, {"type": "module"}))
    write(d, "astro.config.mjs", (
        "import {defineConfig} from 'astro/config';import starlight from '@astrojs/starlight';"
        "export default defineConfig({outDir:'out',integrations:[starlight({title:'s'})]});"))
    write(d, "src/content.config.ts", (
        "import {defineCollection} from 'astro:content';"
        "import {docsLoader} from '@astrojs/starlight/loaders';"
        "import {docsSchema} from '@astrojs/starlight/schema';"
        "export const collections={docs:defineCollection({loader:docsLoader(),schema:docsSchema()})};"))
    c["astro-starlight"] = dict(image=NODE, dir=d, out="out", install=INSTALL_NPM,
                                build="ASTRO_TELEMETRY_DISABLED=1 npx astro build")

    d = ROOT / "redocly"
    d.mkdir(parents=True)
    shutil.copy(SPEC, d / "openapi.yaml")
    write(d, "package.json", pkg({"@redocly/cli": "latest"}))
    c["redocly"] = dict(image=NODE, dir=d, out="out", install=INSTALL_NPM,
                        note="OpenAPI reference only (real 22-api-openapi.yaml)",
                        build="REDOCLY_TELEMETRY=off npx redocly build-docs openapi.yaml -o out/index.html")

    d = ROOT / "scalar"
    d.mkdir(parents=True)
    shutil.copy(SPEC, d / "openapi.yaml")
    write(d, "package.json", pkg({"@scalar/api-reference": "latest", "yaml": "^2"}))
    write(d, "build.mjs", (
        "import fs from 'fs';import YAML from 'yaml';fs.mkdirSync('out',{recursive:true});"
        "const spec=JSON.stringify(YAML.parse(fs.readFileSync('openapi.yaml','utf8'))).replace(/</g,'\\\\u003c');"
        "const js=fs.readFileSync('node_modules/@scalar/api-reference/dist/browser/standalone.js','utf8')"
        ".replace(/<\\/script>/g,'<\\\\/script>');"
        "fs.writeFileSync('out/index.html','<!doctype html><html><body>"
        "<script id=\"api-reference\" type=\"application/json\">'+spec+'</script><script>'+js+'</script></body></html>');"))
    c["scalar"] = dict(image=NODE, dir=d, out="out", install=INSTALL_NPM, build="node build.mjs",
                       note="OpenAPI reference only; static HTML from @scalar/api-reference standalone bundle")
    return c


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    res = {}
    for name, c in scaffold().items():
        d = str(c["dir"])
        r = dict(image=c["image"], note=c.get("note", ""))
        t = time.time()
        i = docker(c["image"], d, c["install"], offline=False)
        r["install_s"] = round(time.time() - t, 1)
        if i.returncode != 0:
            r.update(offline_build="FAIL", reason="install: " + (i.stderr + i.stdout)[-400:])
            res[name] = r
            continue
        times, ok = [], True
        for _ in range(RUNS):
            shutil.rmtree(c["dir"] / c["out"], ignore_errors=True)
            t = time.time()
            b = docker(c["image"], d, c["build"], offline=True)
            times.append(round(time.time() - t, 1))
            if b.returncode != 0:
                ok = False
                r["reason"] = (b.stderr + b.stdout)[:1500]
                break
        r.update(offline_build="PASS" if ok else "FAIL", build_s=times,
                 build_median_s=statistics.median(times), out_bytes=size(c["dir"] / c["out"]),
                 deps_bytes=size(c["dir"] / "node_modules") + size(c["dir"] / "deps"))
        res[name] = r
    out = Path("build/reports/docs-spike.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
