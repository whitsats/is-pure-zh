"""Search CHR page layouts using the paired TIM2 thumbnail as an oracle."""
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


def thumb(f, index):
    raw = entry(f, index)
    assert raw[:4] == b'TIM2'
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    data = np.frombuffer(raw, np.uint8, offset=0x10 + hs)[:w * h * 4]
    im = Image.frombytes('RGBA', (w, h), data.tobytes())
    alpha = im.getchannel('A').point(lambda a: min(255, a * 2))
    im.putalpha(alpha)
    return im.convert('RGBA')


def candidates(pixels):
    """Yield (label, HxWx4) for page tilings and inner swizzles."""
    total = pixels.size // 4
    for pw, ph in ((64, 32), (128, 32), (128, 64), (64, 64), (32, 32), (256, 32)):
        page_px = pw * ph
        if total % page_px:
            continue
        pages = total // page_px
        for cols in range(1, pages + 1):
            if pages % cols:
                continue
            rows = pages // cols
            for order in ('col', 'row'):
                for inner in ('row', 'blk8'):
                    arr = pixels.reshape(pages, ph * pw, 4)
                    if inner == 'row':
                        body = arr.reshape(rows if order == 'row' else cols,
                                           (cols if order == 'row' else rows),
                                           ph, pw, 4)
                        body = body.transpose(2, 0, 3, 1, 4) if order == 'row' else \
                            body.transpose(0, 2, 1, 3, 4)
                    else:
                        bw, bh = 8, 8
                        body = arr.reshape(pages, ph // bh, pw // bw, bh, bw, 4)
                        body = body.transpose(0, 1, 3, 2, 4, 5).reshape(pages, ph, pw, 4)
                        body = body.reshape(rows if order == 'row' else cols,
                                            (cols if order == 'row' else rows),
                                            ph, pw, 4)
                        body = body.transpose(2, 0, 3, 1, 4) if order == 'row' else \
                            body.transpose(0, 2, 1, 3, 4)
                    image = body.reshape(rows * ph, cols * pw, 4)
                    yield (f'{pw}x{ph} {cols}x{rows} {order} {inner}', image)


def corr(a, b):
    a = a.astype(np.float32).ravel()
    b = b.astype(np.float32).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


def main():
    pairs = [(0, 1), (2, 3), (4, 5)]
    with ISO.open('rb') as f:
        for raw_index, thumb_index in pairs:
            raw = entry(f, raw_index)
            hs = 0x180 if (len(raw) - 0x180) % 8192 == 0 else 0x100
            pixels = np.frombuffer(raw, np.uint8, offset=hs)
            ref = thumb(f, thumb_index)
            ref_small = np.asarray(ref.convert('RGB').resize((32, 24),
                                                             Image.Resampling.BOX))
            print(f'\nCHR {raw_index} vs thumbnail {thumb_index} {ref.size}')
            ranked = []
            for label, image in candidates(pixels):
                rgba = Image.fromarray(image, 'RGBA')
                bbox = rgba.getchannel('A').getbbox()
                if not bbox:
                    continue
                crop = rgba.crop(bbox).convert('RGB').resize((32, 24),
                                                             Image.Resampling.BOX)
                score = corr(np.asarray(crop), ref_small)
                ranked.append((score, label, bbox, image))
            ranked.sort(key=lambda r: -r[0])
            for score, label, bbox, image in ranked[:5]:
                print('   %.3f  %-28s bbox %s' % (score, label, bbox))
            if ranked:
                score, label, bbox, image = ranked[0]
                out = np.dstack([image[:, :, :3],
                                 np.where(image[:, :, 3] > 0, 255, 0).astype(np.uint8)])
                Image.fromarray(out, 'RGBA').save(OUT / f'best_{raw_index:04d}.png')
                print('   saved', OUT / f'best_{raw_index:04d}.png')


if __name__ == '__main__':
    main()
