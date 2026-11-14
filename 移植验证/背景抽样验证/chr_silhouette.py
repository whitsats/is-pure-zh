"""Score CHR assemblies by silhouette IoU against the paired thumbnail.

The thumbnails are opaque with a black background, so the reference mask is
"thumbnail luma > threshold".  Comparing silhouettes is robust to colour
differences and to the face being a separate layer.
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


def thumb_mask(f, index):
    raw = entry(f, index)
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    d = np.frombuffer(raw, np.uint8, offset=0x10 + hs, count=w * h * 4)
    rgb = d.reshape(h, w, 4)[:, :, :3].astype(np.int16)
    luma = rgb.mean(axis=2)
    return w, h, (luma > 24)


def bands_of(image, rows, width, order):
    per = STRIP_W // width
    slots = [[image[s * 32:(s + 1) * 32, k * width:(k + 1) * width]
              for k in range(per)] for s in range(rows // 32)]
    if order == 'seq':
        return [slots[s][k] for s in range(len(slots)) for k in range(per)]
    if order == 'slot':
        return [slots[s][k] for k in range(per) for s in range(len(slots))]
    return []


def assemble(bands, width):
    out = np.zeros((len(bands) * 32, width, 4), dtype=np.uint8)
    for n, b in enumerate(bands):
        out[n * 32:(n + 1) * 32] = b
    return out


def iou(mask, ref):
    h, w = ref.shape
    m = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255, 'L')
                   .resize((w, h), Image.Resampling.BOX)) > 127
    inter = np.logical_and(m, ref).sum()
    union = np.logical_or(m, ref).sum()
    return float(inter / union) if union else 0.0


def test(index):
    with ISO.open('rb') as f:
        raw = entry(f, index)
        tw, th, ref = thumb_mask(f, index + 1)
    hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
    px = np.frombuffer(raw, np.uint8, offset=hs)
    rows = (px.size // 4) // STRIP_W
    image = px[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
    results = []
    for width in range(64, 1025, 8):
        for order in ('seq', 'slot'):
            bands = bands_of(image, rows, width, order)
            if not bands:
                continue
            out = assemble(bands, width)
            alpha = out[:, :, 3] > 0
            if not alpha.any():
                continue
            ys, xs = np.where(alpha)
            box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
            crop = alpha[box[1]:box[3], box[0]:box[2]]
            results.append((iou(crop, ref), width, order, out.shape))
    results.sort(reverse=True)
    print(f'\nCHR {index}: rows {rows}, thumb {tw}x{th}')
    for score, width, order, shape in results[:6]:
        print('   width %4d %-4s -> %4dx%-4d IoU %.3f'
              % (width, order, shape[1], shape[0], score))


if __name__ == '__main__':
    for idx in [int(v) for v in (sys.argv[1:] or ['2', '6', '10'])]:
        test(idx)
