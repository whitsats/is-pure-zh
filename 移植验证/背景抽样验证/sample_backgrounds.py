"""Decode sampled even BG entries, save full-size PNGs, and compare each
against its adjacent TIM2 thumbnail.  Read-only on the ISO.

Usage:  python sample_backgrounds.py [index,index,...]
Output: 背景抽样验证/samples/*.png, comparison_*.png, contact_sheet.png,
        summary.csv, summary.json
"""
from pathlib import Path
import csv
import json
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 636928
OUT = ROOT / 'samples'
OUT.mkdir(exist_ok=True)
DEFAULT_SAMPLE = [20, 40, 80, 120, 160, 200, 240, 278]

# 704x512 picture stored as an 11x16 grid of 64x32 blocks inside a
# 1024x352 pixel buffer.
BLOCK_COLS, BLOCK_ROWS = 11, 16
BLOCK_W, BLOCK_H = 64, 32
WIDTH, HEIGHT = BLOCK_COLS * BLOCK_W, BLOCK_ROWS * BLOCK_H


def read_entry(f, index):
    f.seek(BASE + 8 + index * 8)
    entry = f.read(8)
    if len(entry) < 8:
        raise ValueError('entry truncated')
    offset, length = struct.unpack('<II', entry)
    if offset == 0 or length == 0:
        raise ValueError('empty entry')
    f.seek(BASE + offset)
    return unpack(f.read(length))


def decode_background(raw):
    """Return HxWx4 uint8 array plus a note on what was checked."""
    if len(raw) != 0x160100:
        raise ValueError(f'unexpected unpacked length {len(raw):#x}')
    if raw[:4] != b'\x05\x00\x00\x00':
        raise ValueError(f'unexpected header {raw[:4].hex()}')
    pixels = np.frombuffer(raw, dtype=np.uint8, offset=256).reshape(
        BLOCK_COLS, BLOCK_H, BLOCK_ROWS, BLOCK_W, 4)
    tiles = pixels.transpose(0, 2, 1, 3, 4).reshape(
        BLOCK_ROWS, BLOCK_COLS, BLOCK_H, BLOCK_W, 4)
    image = tiles.transpose(0, 2, 1, 3, 4).reshape(HEIGHT, WIDTH, 4).copy()
    image[:, :, 3] = np.minimum(image[:, :, 3].astype(np.uint16) * 2, 255).astype(np.uint8)
    return image


def thumbnail(index):
    """Odd entries are 160x112 TIM2 thumbnails; reuse the earlier exporter."""
    raw = IMG_CACHE.get(index)
    if raw is None:
        return None
    img = Image.open(OUT.parent.parent / '提取测试' / f'BG_{index:03}.png')
    return img.convert('RGBA')


def compare(decoded, thumb):
    """Crop at the alpha bbox, fit to 160x70, compare with thumbnail band."""
    rgba = Image.fromarray(decoded, 'RGBA')
    bbox = rgba.getchannel('A').getbbox()
    if bbox is None:
        return None
    crop = rgba.crop(bbox).convert('RGB').resize((160, 70), Image.Resampling.LANCZOS)
    ref = thumb.convert('RGB').crop((0, 11, 160, 81))
    a = np.asarray(crop).astype(np.int16)
    b = np.asarray(ref).astype(np.int16)
    err = np.abs(a - b)
    return {
        'crop_bbox': bbox,
        'crop_size': (bbox[2] - bbox[0], bbox[3] - bbox[1]),
        'mean_rgb_diff': float(err.mean()),
        'p95_rgb_diff': float(np.percentile(err, 95)),
        'max_rgb_diff': int(err.max()),
        'exact_pixel_pct': float((err.max(axis=2) == 0).mean() * 100),
        'near_pixel_pct': float((err.max(axis=2) <= 8).mean() * 100),
        'crop': crop,
        'ref': ref,
        'err': err,
    }


def comparison_panel(index, decoded, result, thumb):
    """Left: decoded crop, middle: thumbnail band, right: amplified diff."""
    scale = 3
    pad, label_h = 8, 16
    w, h = 160 * scale, 70 * scale
    panel = Image.new('RGB', (w * 3 + pad * 4, h + label_h + pad * 2), (24, 24, 24))
    draw = ImageDraw.Draw(panel)
    tiles = [result['crop'], result['ref'],
             Image.fromarray(np.clip(result['err'] * 8, 0, 255).astype(np.uint8))]
    titles = ['decoded (cropped, 160x70)', 'thumbnail (0,11,160,81)', 'abs diff x8']
    for i, (tile, title) in enumerate(zip(tiles, titles)):
        x = pad + i * (w + pad)
        panel.paste(tile.resize((w, h), Image.Resampling.NEAREST), (x, label_h + pad))
        draw.text((x + 2, 2), title, fill=(220, 220, 220))
    draw.text((w * 3 + pad * 3 - 2, h + label_h + pad - 10),
              'mean %.2f' % result['mean_rgb_diff'], fill=(255, 220, 80),
              anchor='rb')
    path = OUT / f'compare_{index:03}.png'
    panel.save(path)
    return path


IMG_CACHE = {}


def main():
    indices = ([int(v) for v in sys.argv[1].split(',')]
               if len(sys.argv) > 1 else DEFAULT_SAMPLE)
    print('ISO', ISO, 'exists', ISO.exists(), 'size', ISO.stat().st_size)
    rows, failures = [], []
    decoded_cache = {}
    with ISO.open('rb') as f:
        head = f.read(8) if f.seek(BASE) == BASE else b''
        print('AFS', head[:4], 'count', struct.unpack('<I', head[4:])[0])
        for index in indices:
            try:
                raw = read_entry(f, index)
            except Exception as exc:
                failures.append({'index': index, 'reason': f'entry/unpack: {exc}'})
                print(index, 'FAILED entry', exc)
                continue
            try:
                decoded = decode_background(raw)
            except Exception as exc:
                failures.append({'index': index, 'reason': f'decode: {exc}'})
                print(index, 'FAILED decode', exc)
                continue
            decoded_cache[index] = decoded
            rgba = Image.fromarray(decoded, 'RGBA')
            full = OUT / f'BG_{index:03}_full.png'
            rgba.save(full)
            alpha = decoded[:, :, 3]
            stats = {
                'index': index,
                'unpacked_bytes': len(raw),
                'header_u32_0': int(struct.unpack_from('<I', raw, 0)[0]),
                'image_size': f'{WIDTH}x{HEIGHT}',
                'alpha_min': int(alpha.min()),
                'alpha_max': int(alpha.max()),
                'alpha_levels': int(np.unique(alpha).size),
                'alpha_zero_pct': float((alpha == 0).mean() * 100),
                'alpha_full_pct': float((alpha == 255).mean() * 100),
                'alpha_bbox': rgba.getchannel('A').getbbox(),
                'png': str(full),
            }
            thumb = thumbnail(index + 1) if IMG_CACHE.get(index + 1) else None
            if thumb is None and (OUT.parent.parent / '提取测试' / f'BG_{index + 1:03}.png').exists():
                thumb = Image.open(OUT.parent.parent / '提取测试' / f'BG_{index + 1:03}.png').convert('RGBA')
            if thumb is None:
                stats['compare'] = 'no thumbnail'
                print(index, 'decoded but no thumbnail', stats)
            else:
                result = compare(decoded, thumb)
                if result is None:
                    stats['compare'] = 'fully transparent'
                    print(index, 'decoded but fully transparent')
                else:
                    stats.update({k: v for k, v in result.items()
                                  if k not in ('crop', 'ref', 'err')})
                    stats['crop_bbox'] = list(result['crop_bbox'])
                    stats['crop_size'] = list(result['crop_size'])
                    panel = comparison_panel(index, decoded, result, thumb)
                    stats['panel'] = str(panel)
                    print(index, 'alpha', stats['alpha_min'], '-', stats['alpha_max'],
                          'levels', stats['alpha_levels'], 'bbox', stats['alpha_bbox'],
                          'diff %.2f' % stats['mean_rgb_diff'],
                          'exact %.1f%%' % stats['exact_pixel_pct'])
            rows.append(stats)

    # control: compare each decoded image against the *previous* sample's
    # thumbnail, to show what an unrelated image scores.
    control = []
    for a, b in zip(indices, indices[1:]):
        if a in decoded_cache:
            thumb_b = Image.open(OUT.parent.parent / '提取测试' / f'BG_{b + 1:03}.png').convert('RGBA')
            result = compare(decoded_cache[a], thumb_b)
            if result:
                control.append({'decoded': a, 'thumbnail_of': b,
                                'mean_rgb_diff': result['mean_rgb_diff'],
                                'exact_pixel_pct': result['exact_pixel_pct']})

    # contact sheet
    if rows:
        cols, cell_w, cell_h = 4, 220, 170
        sheet_rows = (len(rows) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cell_w, sheet_rows * cell_h), (18, 18, 18))
        draw = ImageDraw.Draw(sheet)
        for n, row in enumerate(rows):
            im = Image.open(row['png']).convert('RGBA')
            bbox = im.getchannel('A').getbbox() or (0, 0, WIDTH, HEIGHT)
            crop = im.crop(bbox).convert('RGB')
            crop.thumbnail((cell_w - 12, cell_h - 30), Image.Resampling.LANCZOS)
            x = (n % cols) * cell_w + (cell_w - crop.width) // 2
            y = (n // cols) * cell_h + 20
            sheet.paste(crop, (x, y))
            draw.text(((n % cols) * cell_w + 6, 4 + (n // cols) * cell_h),
                      'BG %d  bbox %s' % (row['index'], row['alpha_bbox']),
                      fill=(230, 230, 230))
        sheet.save(OUT / 'contact_sheet.png')
        print('contact sheet', OUT / 'contact_sheet.png')

    if rows:
        keys = [k for k in rows[0] if k not in ('png', 'panel')]
        with (OUT / 'summary.csv').open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
    payload = {
        'iso': {'path': str(ISO), 'size': ISO.stat().st_size},
        'environment': {'python': sys.version.split()[0],
                        'pillow': Image.__version__ if hasattr(Image, '__version__') else None,
                        'numpy': np.__version__},
        'sample': indices, 'decoded': rows, 'failures': failures, 'control': control,
    }
    (OUT / 'summary.json').write_text(json.dumps(payload, indent=2, default=str),
                                      encoding='utf-8')
    print('decoded', len(rows), 'failed', len(failures))
    print('control (unrelated pair) mean diffs',
          [round(c['mean_rgb_diff'], 2) for c in control])


if __name__ == '__main__':
    main()
