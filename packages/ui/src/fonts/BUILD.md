# Re-vendoring the design fonts

Nothing here converts at build or test time, and there is no package script: the four `.woff2`
files are committed as binaries. Re-vendor by hand, in a scratch directory outside the repo,
only when a ticket asks for a new upstream release. Never execute anything from a downloaded
archive; read it with `python -I`.

## Inter (upstream WOFF2, vendored unchanged)

```sh
mkdir -p /tmp/fonts-dl/inter/x && cd /tmp/fonts-dl/inter
# download Inter-4.1.zip from https://github.com/rsms/inter/releases/tag/v4.1
sha256sum Inter-4.1.zip   # 9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e
unzip -q Inter-4.1.zip -d x
cp x/web/InterVariable.woff2 x/web/InterVariable-Italic.woff2 <repo>/packages/ui/src/fonts/
cp x/LICENSE.txt <repo>/packages/ui/src/fonts/OFL-Inter.txt
```

## JetBrains Mono (TTF converted to WOFF2)

```sh
mkdir -p /tmp/fonts-dl/jbm/x && cd /tmp/fonts-dl/jbm
# download JetBrainsMono-2.304.zip from https://github.com/JetBrains/JetBrainsMono/releases/tag/v2.304
sha256sum JetBrainsMono-2.304.zip   # 6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf
unzip -q JetBrainsMono-2.304.zip -d x
python3 -m venv /tmp/fontvenv && /tmp/fontvenv/bin/pip install fonttools==4.68.0 brotli==1.2.1
OUT=<repo>/packages/ui/src/fonts
/tmp/fontvenv/bin/python -I -m fontTools.ttLib.woff2 compress -o "$OUT/JetBrainsMono[wght].woff2" "x/fonts/variable/JetBrainsMono[wght].ttf"
/tmp/fontvenv/bin/python -I -m fontTools.ttLib.woff2 compress -o "$OUT/JetBrainsMono-Italic[wght].woff2" "x/fonts/variable/JetBrainsMono-Italic[wght].ttf"
cp x/OFL.txt "$OUT/OFL-JetBrainsMono.txt"
```

## Verify the conversion

Decompress each converted file (`python -I -m fontTools.ttLib.woff2 decompress -o <out>.ttf <in>.woff2`)
and compare it with the upstream TTF table by table (`TTFont(...).reader[tag]`). Every table must be
byte-identical except `head.checkSumAdjustment` and `head.flags` bit 11 (the WOFF2 transform marker).
Anything else differing means stop.

## Finish

Update `manifest.json` (sha256, bytes, source hashes, release tag, tool versions) and the licence
files, then check the four file names still match `docs/plan/16-design-system-brief.md` §2.
