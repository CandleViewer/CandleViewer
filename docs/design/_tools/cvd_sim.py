"""Generate greyscale, deuteranopia- and protanopia-simulated exports of a PNG for CVD review.

Usage: python docs/design/_tools/cvd_sim.py <in.png> <out_prefix>
Writes <out_prefix>-greyscale.png, <out_prefix>-deuteranopia.png and <out_prefix>-protanopia.png
(the protanopia output is additive, E27-D03 BQ-16; the first two are unchanged).

Deuteranopia and protanopia simulation use the standard Brettel/Vienot-style linear RGB
projection matrices (Machado, Oliveira & Fernandes 2009, "sRGB Deuteranopia" and
"sRGB Protanopia", 100% severity).
This is a local, offline, dependency-light approximation adequate for a
design-QA distinguishability check; it is not a certified clinical simulator.
"""
import sys

import numpy as np
from PIL import Image

# Machado et al. 2009 deuteranopia (100% severity) sRGB-space matrix.
DEUTERANOPIA_MATRIX = np.array(
    [
        [0.367322, 0.860646, -0.227968],
        [0.280085, 0.672501, 0.047413],
        [-0.011820, 0.042940, 0.968881],
    ]
)

# Machado et al. 2009 protanopia (100% severity) sRGB-space matrix.
PROTANOPIA_MATRIX = np.array(
    [
        [0.152286, 1.052583, -0.204868],
        [0.114503, 0.786281, 0.108216],
        [-0.003882, -0.048116, 1.051998],
    ]
)


def to_greyscale(arr: np.ndarray) -> np.ndarray:
    # Rec. 601 luma weights, applied per-pixel, broadcast back to 3 channels.
    luma = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    out = np.stack([luma, luma, luma], axis=-1)
    return np.clip(out, 0, 255)


def to_deuteranopia(arr: np.ndarray) -> np.ndarray:
    flat = arr.reshape(-1, 3).astype(np.float64)
    sim = flat @ DEUTERANOPIA_MATRIX.T
    return np.clip(sim, 0, 255).reshape(arr.shape)


def to_protanopia(arr: np.ndarray) -> np.ndarray:
    flat = arr.reshape(-1, 3).astype(np.float64)
    sim = flat @ PROTANOPIA_MATRIX.T
    return np.clip(sim, 0, 255).reshape(arr.shape)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, prefix = sys.argv[1], sys.argv[2]
    im = Image.open(src).convert("RGB")
    arr = np.asarray(im, dtype=np.float64)

    grey = Image.fromarray(to_greyscale(arr).astype(np.uint8), mode="RGB")
    grey.save(f"{prefix}-greyscale.png")

    deut = Image.fromarray(to_deuteranopia(arr).astype(np.uint8), mode="RGB")
    deut.save(f"{prefix}-deuteranopia.png")

    prot = Image.fromarray(to_protanopia(arr).astype(np.uint8), mode="RGB")
    prot.save(f"{prefix}-protanopia.png")

    print(f"wrote {prefix}-greyscale.png, {prefix}-deuteranopia.png and {prefix}-protanopia.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
