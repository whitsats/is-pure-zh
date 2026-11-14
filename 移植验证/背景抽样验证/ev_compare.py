"""Compare EV.AFS decoded CGs against the full 160x112 thumbnail frame."""
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

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
        raise ValueError('empty')
    f.seek(BASE + off)
    return unpack(f.read(length))


def decode(raw):
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


def main():
    with ISO.open('rb') as f:
        ref = thumb(f, 1)
        print('EV thumbnail size', ref.size if ref else None)
        indices = [int(v) for v in (sys.argv[1:] or ['0', '2', '4', '6'])]
        for index in indices:
            image = decode(entry(f, index))
            rgba = Image.fromarray(image, 'RGBA')
            bbox = rgba.getchannel('A').getbbox()
            crop = rgba.crop(bbox).convert('RGB')
            ref_im = thumb(f, index + 1)
            if ref_im is None:
                print(index, 'no thumbnail'); continue
            w, h = ref_im.size
            small = crop.resize((w, h), Image.Resampling.LANCZOS)
            band = crop.resize((w, round(h * 70 / 112)), Image.Resampling.LANCZOS)
            e_full = np.abs(np.asarray(small).astype(np.int16) -
                            np.asarray(ref_im.convert('RGB')).astype(np.int16))
            e_band = np.abs(np.asarray(band).astype(np.int16) -
                            np.asarray(ref_im.convert('RGB').crop((0, 11, w, 81)))
                            .astype(np.int16))
            print(f'EV {index}: bbox {bbox} thumb {w}x{h} '
                  f'diff_full {e_full.mean():.2f} diff_band {e_band.mean():.2f}')
            panel = Image.new('RGB', (w * 3 + 16, h + 20), (20, 20, 20))
            ImageDraw.Draw(panel).text((4, 4), f'EV {index} vs {index + 1}', fill=(230, 230, 230))
            panel.paste(small, (4, 18))
            panel.paste(ref_im.convert('RGB'), (w + 8, 18))
            panel.paste(Image.fromarray(np.clip(e_full * 6, 0, 255).astype(np.uint8)),
                        (w * 2 + 12, 18))
            panel = panel.resize((panel.width * 2, panel.height * 2), Image.Resampling.NEAREST)
            panel.save(OUT / f'EV_{index:03}_check.png')


if __name__ == '__main__':
    main()
