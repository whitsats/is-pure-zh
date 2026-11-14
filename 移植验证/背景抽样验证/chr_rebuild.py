"""Rebuild a CHR sprite from its 1024x32 band strip.

Evidence: the alpha channel of CHR 2 at a 1024-pixel row stride shows five
occupied runs of exactly 150 px at a 160 px pitch, i.e. the sprite is cut into
32-row bands laid side by side.  This script detects the runs per strip,
stacks the bands vertically and scores the result against the paired TIM2
thumbnail.
"""
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848
OUT = ROOT / 'chr_rebuild'
OUT.mkdir(exist_ok=True)
STRIP_W = 1024


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def tim2_thumb(raw):
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    data = np.frombuffer(raw, np.uint8, offset=0x10 + hs, count=w * h * 4)
    return w, h, data.reshape(h, w, 4)


def runs(mask, min_len=16):
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i - start))
            start = None
    if start is not None and len(mask) - start >= min_len:
        out.append((start, len(mask) - start))
    return out


def rebuild(pixels):
    """Split the 32-row strips into bands and stack them vertically."""
    count = pixels.size // 4
    rows = count // STRIP_W
    image = pixels.reshape(rows, STRIP_W, 4)
    bands, starts = [], []
    for r in range(0, rows, 32):
        strip = image[r:r + 32]
        occupied = (strip[:, :, 3] > 0).any(axis=0)
        found = runs(occupied)
        starts.append(found)
        for x0, w in found:
            bands.append(strip[:, x0:x0 + w])
    if not bands:
        return None, starts
    height = sum(b.shape[0] for b in bands)
    width = max(b.shape[1] for b in bands)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    y = 0
    for band in bands:
        out[y:y + band.shape[0], :band.shape[1]] = band
        y += band.shape[0]
    return out, starts


def score(candidate, thumb_rgba):
    tw, th, timg = thumb_rgba
    ref_rgb = timg[:, :, :3]
    ref = ref_rgb.astype(np.float32)
    rgb = candidate[:, :, :3]
    alpha = candidate[:, :, 3]
    bbox = (np.where(alpha > 0)[1].min(), np.where(alpha > 0)[0].min(),
            np.where(alpha > 0)[1].max() + 1, np.where(alpha > 0)[0].max() + 1) \
        if (alpha > 0).any() else None
    if bbox is None:
        return None
    crop = Image.fromarray(rgb, 'RGB').crop(bbox).resize((tw, th),
                                                         Image.Resampling.LANCZOS)
    a = np.asarray(crop, dtype=np.float32).ravel()
    b = ref.ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    corr = float(a @ b / denom) if denom else 0.0
    mad = float(np.abs(np.asarray(crop, dtype=np.int16) -
                       ref_rgb.astype(np.int16)).mean())
    return bbox, corr, mad, crop


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['2', '4', '0'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
            pixels = np.frombuffer(raw, np.uint8, offset=hs)
            thumb = tim2_thumb(entry(f, index + 1))
            rebuilt, starts = rebuild(pixels)
            print(f'CHR {index}: {pixels.size // 4} px, strips runs {starts}')
            if rebuilt is None:
                print('   nothing to rebuild')
                continue
            out = np.dstack([rebuilt[:, :, :3],
                             np.where(rebuilt[:, :, 3] > 0, 255, 0).astype(np.uint8)])
            path = OUT / f'CHR_{index:04d}.png'
            Image.fromarray(out, 'RGBA').save(path)
            result = score(rebuilt, thumb)
            if result:
                bbox, corr, mad, crop = result
                print(f'   rebuilt {rebuilt.shape[1]}x{rebuilt.shape[0]} '
                      f'bbox {bbox} corr {corr:.3f} mad {mad:.2f} -> {path.name}')
                tw, th, timg = thumb
                panel = Image.new('RGB', (tw * 3 + 16, th + 16), (20, 20, 20))
                panel.paste(crop, (4, 12))
                panel.paste(Image.fromarray(timg[:, :, :3], 'RGB'), (tw + 8, 12))
                diff = np.abs(np.asarray(crop, np.int16) - timg[:, :, :3].astype(np.int16))
                panel.paste(Image.fromarray(np.clip(diff * 6, 0, 255).astype(np.uint8)),
                            (tw * 2 + 12, 12))
                panel = panel.resize((panel.width * 3, panel.height * 3),
                                     Image.Resampling.NEAREST)
                panel.save(OUT / f'CHR_{index:04d}_check.png')


if __name__ == '__main__':
    main()
