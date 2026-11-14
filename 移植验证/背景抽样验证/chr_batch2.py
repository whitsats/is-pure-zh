"""已废弃（2026-11-13）：请改用 chr_unified.py。

本脚本对全部 1473 个 CHR.AFS 条目穷举 15 种带宽、挑与缩略图相关系数最高的重建结果，
只有 594/1473（40.3%，即半身头像那一类）能达到 corr>=0.80，其余 879 条（全身立绘）
全部失败——因为它们需要 chr_body.py 的"部件表 + 全局块号"模型，不是单条带穷举。

实测证实半身头像条目的头部同样带有部件表（通常只有 1 个部件），用 chr_body.py 的
模型可以 100% 正确解析全部 594 条（IoU 中位数 0.998），不需要猜带宽。
详见 CHR统一批处理说明.md。本文件仅作历史记录保留，不要再用它产出正式素材。

---

Batch over all 1473 CHR.AFS pairs: pick the band width per entry by
thumbnail correlation, record the best score and save the recovered sprites.

Usage:
    python chr_batch2.py            # all pairs
    python chr_batch2.py 2,8,14     # selected raw entry indices
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
WIDTHS = [128, 144, 150, 160, 176, 192, 224, 256, 320, 384, 448, 512, 640, 768, 1024]


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
    if not w or not h or 0x10 + hs + w * h * 4 > len(raw):
        return None
    d = np.frombuffer(raw, np.uint8, offset=0x10 + hs, count=w * h * 4)
    return w, h, d.reshape(h, w, 4)


def rebuild(image, rows, width):
    per = STRIP_W // width
    if per < 1:
        return None
    bands = []
    for s in range(rows // 32):
        strip = image[s * 32:(s + 1) * 32]
        for k in range(per):
            band = strip[:, k * width:(k + 1) * width]
            if (band[:, :, 3] > 0).any():
                bands.append(band)
    if not bands:
        return None
    out = np.zeros((len(bands) * 32, width, 4), dtype=np.uint8)
    for n, band in enumerate(bands):
        out[n * 32:(n + 1) * 32] = band
    return out


def evaluate(out, thumb):
    tw, th, timg = thumb
    alpha = out[:, :, 3]
    if not (alpha > 0).any():
        return None
    ys, xs = np.where(alpha > 0)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    crop = Image.fromarray(out[:, :, :3], 'RGB').crop(box).resize(
        (tw, th), Image.Resampling.LANCZOS)
    a = np.asarray(crop, dtype=np.float32).ravel()
    b = timg[:, :, :3].astype(np.float32).ravel()
    a -= a.mean()
    b -= b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    corr = float(a @ b / denom) if denom else 0.0
    mad = float(np.abs(np.asarray(crop, dtype=np.int16) -
                       timg[:, :, :3].astype(np.int16)).mean())
    return corr, mad, box, crop


def worker(index):
    with ISO.open('rb') as f:
        raw = read_entry(f, index)
        thumb = tim2_thumb(read_entry(f, index + 1))
    if raw is None:
        return {'index': index, 'status': 'empty'}
    if thumb is None:
        return {'index': index, 'status': 'no-thumbnail'}
    hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
    px = np.frombuffer(raw, np.uint8, offset=hs)
    rows = (px.size // 4) // STRIP_W
    if rows == 0:
        return {'index': index, 'status': 'too-small'}
    image = px[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
    best = None
    for width in WIDTHS:
        out = rebuild(image, rows, width)
        if out is None:
            continue
        result = evaluate(out, thumb)
        if result is None:
            continue
        if best is None or result[0] > best[0]:
            best = (result[0], result[1], width, out.shape, result[2])
    if best is None:
        return {'index': index, 'status': 'no-bands'}
    corr, mad, width, shape, box = best
    return {
        'index': index, 'status': 'ok', 'corr': round(corr, 4),
        'mad': round(mad, 2), 'band_width': width,
        'rebuilt': f'{shape[1]}x{shape[0]}',
        'bbox': f'{box[2] - box[0]}x{box[3] - box[1]}',
        'thumb': f'{thumb[0]}x{thumb[1]}', 'strips': rows // 32,
    }


def render(index):
    """Second pass: rebuild the winning width and save PNG + comparison."""
    with ISO.open('rb') as f:
        raw = read_entry(f, index)
        thumb = tim2_thumb(read_entry(f, index + 1))
    hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
    px = np.frombuffer(raw, np.uint8, offset=hs)
    rows = (px.size // 4) // STRIP_W
    image = px[:rows * STRIP_W * 4].reshape(rows, STRIP_W, 4)
    best = None
    for width in WIDTHS:
        out = rebuild(image, rows, width)
        if out is None:
            continue
        result = evaluate(out, thumb)
        if result is None:
            continue
        if best is None or result[0] > best[0]:
            best = (result[0], result[1], width, out, result[2], result[3])
    if best is None:
        return None
    corr, mad, width, out, box, crop = best
    rgba = Image.fromarray(out, 'RGBA')
    rgba.putalpha(rgba.getchannel('A').point(lambda a: min(255, a * 2)))
    rgba.save(OUT / f'CHR_{index:04d}.png')
    sprite = Image.fromarray(out, 'RGBA').crop(box)
    sprite.save(OUT / f'CHR_{index:04d}_sprite.png')
    tw, th, timg = thumb
    scale = max(1, 160 // max(1, tw))
    panel = Image.new('RGB', (tw * 3 + 16, th + 12), (24, 24, 24))
    panel.paste(crop, (4, 8))
    panel.paste(Image.fromarray(timg[:, :, :3], 'RGB'), (tw + 8, 8))
    diff = np.abs(np.asarray(crop, np.int16) - timg[:, :, :3].astype(np.int16))
    panel.paste(Image.fromarray(np.clip(diff * 6, 0, 255).astype(np.uint8)),
                (tw * 2 + 12, 8))
    panel = panel.resize((panel.width * 3, panel.height * 3), Image.Resampling.NEAREST)
    panel.save(OUT / f'CHR_{index:04d}_check.png')
    return corr


def main():
    if len(sys.argv) > 1:
        indices = [int(v) for v in sys.argv[1].split(',')]
    else:
        indices = list(range(0, 2946, 2))
    print('entries', len(indices), flush=True)
    rows = []
    with Pool(min(8, os.cpu_count() or 4)) as pool:
        for n, row in enumerate(pool.imap_unordered(worker, indices, chunksize=4), 1):
            rows.append(row)
            if n % 150 == 0:
                print('  %d/%d' % (n, len(indices)), flush=True)
    rows.sort(key=lambda r: r.get('corr', -9), reverse=True)
    ok = [r for r in rows if r['status'] == 'ok']
    print('scored', len(ok), 'of', len(indices))
    if ok:
        corrs = [r['corr'] for r in ok]
        for t in (0.99, 0.95, 0.9, 0.85, 0.8, 0.6, 0.4):
            print('  corr >= %.2f : %d' % (t, sum(1 for c in corrs if c >= t)))
        print('\nbest 12:')
        for r in ok[:12]:
            print('  CHR %4d corr %.3f mad %5.1f width %4d rebuilt %9s bbox %8s'
                  % (r['index'], r['corr'], r['mad'], r['band_width'],
                     r['rebuilt'], r['bbox']))
    keys = ['index', 'status', 'corr', 'mad', 'band_width', 'rebuilt', 'bbox',
            'thumb', 'strips']
    with (OUT / 'chr_batch.csv').open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print('wrote', OUT / 'chr_batch.csv')
    for r in ok[:12]:
        render(r['index'])
    print('rendered top 12 into', OUT)


if __name__ == '__main__':
    main()
