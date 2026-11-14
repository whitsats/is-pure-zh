"""Batch-rebuild every CHR.AFS sprite and score it against its thumbnail.

Layout established on CHR 2: the pixel block is a sequence of 1024x32 strips;
each sprite is cut into 32-row bands that sit side by side at a constant pitch
inside a strip.  Bands are stacked vertically to recover the picture.

Usage:
    python chr_batch.py            # all 1473 pairs, multiprocessing
    python chr_batch.py 2,6,8      # selected raw entry indices
"""
from pathlib import Path
import csv
import os
import struct
import sys
from multiprocessing import Pool

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848
OUT = ROOT / 'chr_batch'
OUT.mkdir(exist_ok=True)
STRIP_W = 1024


def read_entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    if not off or not length:
        return None
    f.seek(BASE + off)
    return unpack(f.read(length))


def tim2_thumb(raw):
    if not raw or raw[:4] != b'TIM2':
        return None
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    if w == 0 or h == 0 or 0x10 + hs + w * h * 4 > len(raw):
        return None
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


def band_width(run_list, declared_w):
    """Infer the band pitch from evenly spaced runs, else fall back."""
    pitches = []
    for found in run_list:
        for (a, wa), (b, wb) in zip(found, found[1:]):
            pitches.append(b - a)
    if pitches:
        values, counts = np.unique(pitches, return_counts=True)
        return int(values[counts.argmax()])
    if 32 <= declared_w <= 1024:
        return int(declared_w)
    return 160


def rebuild(pixels, width):
    count = pixels.size // 4
    rows = count // STRIP_W
    image = pixels[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
    bands = []
    for r in range(0, rows, 32):
        strip = image[r:r + 32]
        for x in range(0, STRIP_W, width):
            band = strip[:, x:x + width]
            if band.size and (band[:, :, 3] > 0).any():
                bands.append(band)
    if not bands:
        return None
    height = sum(b.shape[0] for b in bands)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    y = 0
    for band in bands:
        out[y:y + band.shape[0], :band.shape[1]] = band
        y += band.shape[0]
    return out


def score(candidate, thumb):
    tw, th, timg = thumb
    rgb = candidate[:, :, :3]
    alpha = candidate[:, :, 3]
    mask = alpha > 0
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    crop = Image.fromarray(rgb, 'RGB').crop(bbox).resize((tw, th),
                                                         Image.Resampling.LANCZOS)
    a = np.asarray(crop, dtype=np.float32).ravel()
    b = timg[:, :, :3].astype(np.float32).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    corr = float(a @ b / denom) if denom else 0.0
    mad = float(np.abs(np.asarray(crop, dtype=np.int16) -
                       timg[:, :, :3].astype(np.int16)).mean())
    return corr, mad, bbox, crop


def worker(index):
    with ISO.open('rb') as f:
        raw = read_entry(f, index)
        thumb_raw = read_entry(f, index + 1)
    if raw is None:
        return {'index': index, 'status': 'empty'}
    thumb = tim2_thumb(thumb_raw)
    if thumb is None:
        return {'index': index, 'status': 'no-thumbnail'}
    hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
    declared = struct.unpack_from('<I', raw, 0x88)[0]
    dw, dh = declared & 0xFFFF, declared >> 16
    pixels = np.frombuffer(raw, np.uint8, offset=hs)
    rows = (pixels.size // 4) // STRIP_W
    if rows == 0:
        return {'index': index, 'status': 'too-small'}
    image = pixels[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
    run_list = []
    for r in range(0, rows, 32):
        run_list.append(runs((image[r:r + 32, :, 3] > 0).any(axis=0)))
    width = band_width(run_list, dw if 0 < dw <= 1024 else 0)
    rebuilt = rebuild(pixels, width)
    if rebuilt is None:
        return {'index': index, 'status': 'no-bands'}
    result = score(rebuilt, thumb)
    if result is None:
        return {'index': index, 'status': 'transparent'}
    corr, mad, bbox, crop = result
    return {
        'index': index, 'status': 'ok', 'corr': round(corr, 4),
        'mad': round(mad, 2), 'band_width': width,
        'rebuilt': f'{rebuilt.shape[1]}x{rebuilt.shape[0]}',
        'bbox': f'{bbox[2] - bbox[0]}x{bbox[3] - bbox[1]}',
        'declared': f'{dw}x{dh}', 'thumb': f'{thumb[0]}x{thumb[1]}',
        'strips': rows // 32,
    }


def save_pair(index, crop, thumb):
    tw, th, timg = thumb
    panel = Image.new('RGB', (tw * 3 + 16, th + 16), (20, 20, 20))
    panel.paste(crop, (4, 12))
    panel.paste(Image.fromarray(timg[:, :, :3], 'RGB'), (tw + 8, 12))
    diff = np.abs(np.asarray(crop, np.int16) - timg[:, :, :3].astype(np.int16))
    panel.paste(Image.fromarray(np.clip(diff * 6, 0, 255).astype(np.uint8)),
                (tw * 2 + 12, 12))
    panel = panel.resize((panel.width * 3, panel.height * 3), Image.Resampling.NEAREST)
    panel.save(OUT / f'CHR_{index:04d}_check.png')


def main():
    if len(sys.argv) > 1:
        indices = [int(v) for v in sys.argv[1].split(',')]
    else:
        indices = list(range(0, 2946, 2))
    print('entries', len(indices))
    rows = []
    cpu = min(8, os.cpu_count() or 4)
    with Pool(cpu) as pool:
        for n, row in enumerate(pool.imap_unordered(worker, indices, chunksize=8), 1):
            rows.append(row)
            if n % 100 == 0:
                print('  %d/%d' % (n, len(indices)), flush=True)
    rows.sort(key=lambda r: r.get('corr', -9), reverse=True)
    ok = [r for r in rows if r['status'] == 'ok']
    print('scored', len(ok), 'of', len(indices))
    if ok:
        import statistics
        corrs = [r['corr'] for r in ok]
        print('corr mean %.3f median %.3f' % (statistics.mean(corrs),
                                              statistics.median(corrs)))
        for threshold in (0.99, 0.95, 0.9, 0.8, 0.6):
            print('  corr >= %.2f : %d' % (threshold,
                                           sum(1 for c in corrs if c >= threshold)))
        print('\nbest 10:')
        for r in ok[:10]:
            print('  CHR %4d corr %.3f mad %5.1f band %4d rebuilt %8s bbox %8s '
                  'declared %8s thumb %9s' %
                  (r['index'], r['corr'], r['mad'], r['band_width'],
                   r['rebuilt'], r['bbox'], r['declared'], r['thumb']))
    keys = ['index', 'status', 'corr', 'mad', 'band_width', 'rebuilt', 'bbox',
            'declared', 'thumb', 'strips']
    with (OUT / 'chr_batch.csv').open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print('wrote', OUT / 'chr_batch.csv')


if __name__ == '__main__':
    main()
