"""List alpha connected components of a CHR pixel block and compare them
with the header records, to identify what the part table encodes.
"""
from pathlib import Path
import struct
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['6', '10', '0', '4'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
            px = np.frombuffer(raw, np.uint8, offset=hs)
            rows = (px.size // 4) // 1024
            image = px[:rows * 1024 * 4].reshape(rows, 1024, 4)
            alpha = image[:, :, 3] > 0
            labels, n = ndimage.label(alpha, structure=np.ones((3, 3)))
            print(f'\n=== CHR {index}: {rows} rows, {n} components')
            sizes = ndimage.sum(alpha, labels, range(1, n + 1))
            order = np.argsort(sizes)[::-1]
            for rank, idx in enumerate(order[:10]):
                ys, xs = np.where(labels == idx + 1)
                print('   comp %2d area %6d  x %4d-%4d  y %3d-%3d  (%dx%d)'
                      % (rank, int(sizes[idx]), xs.min(), xs.max(),
                         ys.min(), ys.max(),
                         xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))
            # header records
            count, zero, wh, flag = struct.unpack_from('<4I', raw, 0x80)
            body = raw[0x90:0x90 + 200]
            print('   header count %d wh %dx%d' % (count, wh & 0xFFFF, wh >> 16))
            vals = struct.unpack_from('<%dI' % ((0xBC - 0x90) // 4 if index == 6 else
                                                (0xDC - 0x90) // 4), raw, 0x90)
            print('   records:', [hex(v) for v in vals])


if __name__ == '__main__':
    main()
