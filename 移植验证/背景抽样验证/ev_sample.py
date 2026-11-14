"""Decode event CGs from EV.AFS and check them against their thumbnails."""
from pathlib import Path
import csv
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 343689216
OUT = ROOT / 'ev'
OUT.mkdir(exist_ok=True)


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    if not off or not length:
        raise ValueError('empty entry')
    f.seek(BASE + off)
    return unpack(f.read(length))


def decode_bg(raw):
    pixels = np.frombuffer(raw, np.uint8, offset=256).reshape(11, 32, 16, 64, 4)
    tiles = pixels.transpose(0, 2, 1, 3, 4).reshape(16, 11, 32, 64, 4)
    image = tiles.transpose(0, 2, 1, 3, 4).reshape(512, 704, 4).copy()
    image[:, :, 3] = np.minimum(image[:, :, 3].astype(np.uint16) * 2, 255).astype(np.uint8)
    return image


def thumb(f, index):
    raw = entry(f, index)
    if raw[:4] != b'TIM2':
        return None
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    data = np.frombuffer(raw, np.uint8, offset=0x10 + hs)[:w * h * 4]
    im = Image.frombytes('RGBA', (w, h), data.tobytes())
    im.putalpha(im.getchannel('A').point(lambda a: min(255, a * 2)))
    return im.convert('RGBA')


def compare(image, ref):
    rgba = Image.fromarray(image, 'RGBA')
    bbox = rgba.getchannel('A').getbbox()
    if not bbox:
        return None
    crop = rgba.crop(bbox).convert('RGB').resize((160, 70), Image.Resampling.LANCZOS)
    ref_c = ref.convert('RGB').crop((0, 11, 160, 81))
    err = np.abs(np.asarray(crop).astype(np.int16) - np.asarray(ref_c).astype(np.int16))
    return bbox, float(err.mean()), crop, ref_c


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['0', '2', '4', '134'])]
    rows = []
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            if len(raw) != 0x160100:
                print(index, 'not a 0x160100 container', len(raw), raw[:16].hex(' '))
                continue
            image = decode_bg(raw)
            rgba = Image.fromarray(image, 'RGBA')
            path = OUT / f'EV_{index:03}.png'
            rgba.save(path)
            ref = thumb(f, index + 1)
            result = compare(image, ref) if ref is not None else None
            if result:
                bbox, diff, crop, ref_c = result
                panel = Image.new('RGB', (160 * 3 * 2 + 16, 70 * 2 + 20), (20, 20, 20))
                panel.paste(crop.resize((480, 210), Image.Resampling.LANCZOS), (4, 16))
                panel.paste(ref_c.resize((480, 210), Image.Resampling.LANCZOS), (492, 16))
                panel.save(OUT / f'EV_{index:03}_compare.png')
                print(index, 'bbox', bbox, 'alpha', int(image[:, :, 3].min()),
                      int(image[:, :, 3].max()), 'diff %.2f' % diff, '->', path.name)
                rows.append((index, bbox, round(diff, 2)))
            else:
                print(index, 'decoded, no valid thumbnail')
                rows.append((index, rgba.getchannel('A').getbbox(), 'n/a'))
    with (OUT / 'summary.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['index', 'alpha_bbox', 'mean_rgb_diff_vs_thumbnail'])
        w.writerows(rows)


if __name__ == '__main__':
    main()
