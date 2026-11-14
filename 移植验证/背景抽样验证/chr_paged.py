"""Apply the background page-transpose formula to CHR entries.

Backgrounds decode as
    reshape(page_columns, 32, page_rows, 64, 4)
    -> transpose(0, 2, 1, 3, 4) -> reshape(page_rows, page_columns, 32, 64, 4)
    -> transpose(0, 2, 1, 3, 4) -> (page_rows*32, page_columns*64)
i.e. the stream is ordered [column][y][row][x].  CHR body entries may use the
same rule with a different page count, so every factorisation is tried and
scored by silhouette IoU against the paired thumbnail.
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
OUT = ROOT / 'chr_paged'
OUT.mkdir(exist_ok=True)


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def thumb(f, index):
    raw = entry(f, index)
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    d = np.frombuffer(raw, np.uint8, offset=0x10 + hs, count=w * h * 4)
    px = d.reshape(h, w, 4)
    return w, h, (px[:, :, :3].astype(np.int16).mean(axis=2) > 24)


def decode(pixels, cols, rows, mode):
    body = pixels.reshape(cols, 32, rows, 64, 4)
    if mode == 'colfirst':
        grid = body.transpose(0, 2, 1, 3, 4).reshape(rows, cols, 32, 64, 4)
        return grid.transpose(0, 2, 1, 3, 4).reshape(rows * 32, cols * 64, 4)
    # plain page order: consecutive pages fill a row of pages
    grid = body.transpose(2, 0, 1, 3, 4).reshape(rows, cols, 32, 64, 4)
    return grid.transpose(0, 2, 1, 3, 4).reshape(rows * 32, cols * 64, 4)


def iou(mask, ref):
    h, w = ref.shape
    ys, xs = np.where(mask)
    if not ys.size:
        return 0.0
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    m = np.asarray(Image.fromarray(crop.astype(np.uint8) * 255, 'L')
                   .resize((w, h), Image.Resampling.BOX)) > 127
    inter = np.logical_and(m, ref).sum()
    union = np.logical_or(m, ref).sum()
    return float(inter / union) if union else 0.0


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['6', '10', '0', '4'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            tw, th, ref = thumb(f, index + 1)
            hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
            px = np.frombuffer(raw, np.uint8, offset=hs)
            pages = px.size // 8192
            print(f'\n=== CHR {index}: {pages} pages, thumb {tw}x{th}')
            results = []
            for cols in range(1, pages + 1):
                if pages % cols:
                    continue
                rows = pages // cols
                if rows * 32 > 4096:
                    continue
                for mode in ('colfirst', 'plain'):
                    img = decode(px[:pages * 8192], cols, rows, mode)
                    alpha = img[:, :, 3] > 0
                    if not alpha.any():
                        continue
                    score = iou(alpha, ref)
                    results.append((score, cols, rows, mode, img))
            results.sort(key=lambda r: -r[0])
            for score, cols, rows, mode, img in results[:5]:
                print('   %2dx%-3d %-9s -> %4dx%-4d IoU %.3f'
                      % (cols, rows, mode, img.shape[1], img.shape[0], score))
            if results:
                score, cols, rows, mode, img = results[0]
                out = np.dstack([img[:, :, :3],
                                 np.where(img[:, :, 3] > 0, 255, 0).astype(np.uint8)])
                path = OUT / f'CHR_{index:04d}_{cols}x{rows}_{mode}.png'
                Image.fromarray(out, 'RGBA').save(path)
                print('   saved', path.name)


if __name__ == '__main__':
    main()
