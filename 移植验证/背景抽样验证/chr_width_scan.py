"""Find the band width of a CHR entry by seam continuity.

If the sprite is cut into 32-row bands of width W laid side by side inside
each 1024-wide strip, then stacking the bands puts the last row of one band
next to the first row of the next.  The correct W makes those seams smooth.
"""
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848
STRIP_W = 1024


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def seam_score(pixels, width):
    rows = (pixels.size // 4) // STRIP_W
    image = pixels[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
    per_strip = STRIP_W // width
    if per_strip < 1 or rows < 64:
        return None, 0
    bands = []
    for s in range(rows // 32):
        strip = image[s * 32:(s + 1) * 32]
        for i in range(per_strip):
            bands.append(strip[:, i * width:(i + 1) * width])
    if len(bands) < 2:
        return None, 0
    diffs = [np.abs(a[31].astype(np.int16) - b[0].astype(np.int16)).mean()
             for a, b in zip(bands, bands[1:])]
    inside = [np.abs(b[1:].astype(np.int16) - b[:-1].astype(np.int16)).mean()
              for b in bands]
    return float(np.mean(diffs)), float(np.mean(inside))


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['2', '6', '10', '14'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
            pixels = np.frombuffer(raw, np.uint8, offset=hs)
            results = []
            for width in range(64, 1009, 16):
                seam, inside = seam_score(pixels, width)
                if seam is None:
                    continue
                results.append((seam, width, inside))
            results.sort()
            rows = (pixels.size // 4) // STRIP_W
            print(f'\nCHR {index}: {pixels.size // 4} px = {rows // 32} strips')
            for seam, width, inside in results[:6]:
                print('   width %4d  bands/strip %d  seam %.2f  inside %.2f  '
                      'ratio %.2f' % (width, 1024 // width, seam, inside,
                                      seam / inside if inside else 0))


if __name__ == '__main__':
    main()
