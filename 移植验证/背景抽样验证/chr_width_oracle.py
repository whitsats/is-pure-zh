"""Sweep band widths and score each rebuild against the paired thumbnail.

Validates the method on CHR 2 (known answer: 160) and finds the width for
entries whose bands touch, where alpha runs cannot separate them.
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
STRIP_W = 1024


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def thumb(raw):
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    d = np.frombuffer(raw, np.uint8, offset=0x10 + hs, count=w * h * 4)
    return w, h, d.reshape(h, w, 4)[:, :, :3].astype(np.float32)


def rebuild(image, rows, width):
    per = STRIP_W // width
    if per < 1:
        return None
    bands = []
    for s in range(rows // 32):
        strip = image[s * 32:(s + 1) * 32]
        for i in range(per):
            band = strip[:, i * width:(i + 1) * width]
            if (band[:, :, 3] > 0).any():
                bands.append(band)
    if not bands:
        return None
    out = np.zeros((sum(b.shape[0] for b in bands), width, 4), dtype=np.uint8)
    y = 0
    for band in bands:
        out[y:y + band.shape[0]] = band
        y += band.shape[0]
    return out


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['2', '6', '10', '0'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
            px = np.frombuffer(raw, np.uint8, offset=hs)
            rows = (px.size // 4) // STRIP_W
            image = px[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
            tw, th, tref = thumb(entry(f, index + 1))
            results = []
            for width in range(64, STRIP_W + 1, 8):
                out = rebuild(image, rows, width)
                if out is None:
                    continue
                alpha = out[:, :, 3]
                if not (alpha > 0).any():
                    continue
                ys, xs = np.where(alpha > 0)
                box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
                crop = Image.fromarray(out[:, :, :3], 'RGB').crop(box).resize(
                    (tw, th), Image.Resampling.LANCZOS)
                a = np.asarray(crop, dtype=np.float32).ravel()
                a -= a.mean()
                b = tref.ravel() - tref.mean()
                denom = np.linalg.norm(a) * np.linalg.norm(b)
                corr = float(a @ b / denom) if denom else 0.0
                results.append((corr, width, out.shape[1], out.shape[0]))
            results.sort(reverse=True)
            print(f'\nCHR {index}: {px.size // 4} px, {rows // 32} strips, '
                  f'thumb {tw}x{th}')
            for corr, width, w, h in results[:6]:
                print('   width %4d -> %4dx%-4d corr %.3f' % (width, w, h, corr))


if __name__ == '__main__':
    main()
