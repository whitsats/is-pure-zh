"""Try GS-style page tilings for CHR.AFS sprite data.

The backgrounds are stored as 64x32 pages ordered column-major, page content
row-major.  CHR sprites may use the same rule with a different page grid, so
this script tries grids that divide the byte budget evenly.
"""
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848
OUT = ROOT / 'chr'
OUT.mkdir(exist_ok=True)


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def header_size(raw):
    for size in (0x180, 0x100):
        if (len(raw) - size) % 8192 == 0 and len(raw) > size:
            return size
    return 0x100


def page_grids(pages):
    out = []
    for cols in range(1, pages + 1):
        if pages % cols:
            continue
        out.append((cols, pages // cols))
    return out


def decode(pixels, cols, rows, order):
    grid = pixels.reshape(cols, 32, rows, 64, 4) if order == 'colmajor' else \
        pixels.reshape(rows, cols, 32, 64, 4).transpose(1, 0, 2, 3, 4)
    grid = grid.transpose(0, 2, 1, 3, 4)          # (cols, rows, 32, 64, 4)
    if order == 'rowmajor':
        pass
    image = grid.transpose(1, 0, 2, 3, 4).reshape(rows * 32, cols * 64, 4)
    return image


def score(image):
    """Real art has long uniform runs; a wrong swizzle looks like noise."""
    alpha = image[:, :, 3]
    transitions = (np.diff(alpha, axis=1) != 0).sum() / alpha.size
    return float(transitions)


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['2', '4'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            hs = header_size(raw)
            declared = struct.unpack_from('<I', raw, 0x88)[0]
            dw, dh = declared & 0xffff, declared >> 16
            pixels = np.frombuffer(raw, dtype=np.uint8, offset=hs)
            pages = pixels.size // 8192
            print(f'CHR {index}: raw {len(raw)} header {hs:#x} px bytes {pixels.size} '
                  f'pages {pages} declared {dw}x{dh}')
            best = []
            for cols, rows in page_grids(pages):
                for order in ('colmajor', 'rowmajor'):
                    image = decode(pixels, cols, rows, order)
                    s = score(image)
                    best.append((s, cols, rows, order, image))
            best.sort(key=lambda r: r[0])
            for rank, (s, cols, rows, order, image) in enumerate(best[:4]):
                alpha = image[:, :, 3]
                ys, xs = np.where(alpha > 0)
                w = xs.max() - xs.min() + 1 if xs.size else 0
                h = ys.max() - ys.min() + 1 if ys.size else 0
                print(f'   {cols}x{rows} {order:9s} {cols * 64}x{rows * 32} '
                      f'noise {s:.3f} alpha bbox {w}x{h}')
                out = np.dstack([image[:, :, :3],
                                 np.where(alpha > 0, 255, 0).astype(np.uint8)])
                path = OUT / f'CHR_{index:04d}_{cols}x{rows}_{order}.png'
                Image.fromarray(out, 'RGBA').save(path)


if __name__ == '__main__':
    main()
