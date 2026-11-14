"""Match each sampled background against *all* 140 thumbnails.

Confirms or refutes the even-N <-> odd-(N+1) pairing instead of assuming it.
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
THUMBS = ROOT.parent / '提取测试'
BASE = 636928
SAMPLES = [12, 14, 16, 18, 20, 40, 80, 120, 160, 200, 240, 278]


def decode(raw):
    pixels = np.frombuffer(raw, dtype=np.uint8, offset=256).reshape(11, 32, 16, 64, 4)
    tiles = pixels.transpose(0, 2, 1, 3, 4).reshape(16, 11, 32, 64, 4)
    image = tiles.transpose(0, 2, 1, 3, 4).reshape(512, 704, 4).copy()
    image[:, :, 3] = np.minimum(image[:, :, 3].astype(np.uint16) * 2, 255).astype(np.uint8)
    return image


def signature(rgb):
    """Small, scale-free fingerprint: 20x10 mean-colour grid in 0..1."""
    small = np.asarray(Image.fromarray(rgb).resize((20, 10), Image.Resampling.BOX),
                       dtype=np.float32)
    small = small - small.mean(axis=(0, 1), keepdims=True)
    norm = np.linalg.norm(small)
    return small.ravel() / (norm if norm else 1)


def main():
    thumbs = {}
    for index in range(1, 280, 2):
        path = THUMBS / f'BG_{index:03}.png'
        if not path.exists():
            continue
        im = Image.open(path).convert('RGB').crop((0, 11, 160, 81))
        thumbs[index] = signature(np.asarray(im))

    with ISO.open('rb') as f:
        for index in SAMPLES:
            f.seek(BASE + 8 + index * 8)
            offset, length = struct.unpack('<II', f.read(8))
            f.seek(BASE + offset)
            raw = unpack(f.read(length))
            image = decode(raw)
            rgba = Image.fromarray(image)
            bbox = rgba.getchannel('A').getbbox() or (0, 0, 704, 512)
            crop = np.asarray(rgba.crop(bbox).convert('RGB').resize((160, 70),
                                                                   Image.Resampling.LANCZOS))
            sig = signature(crop)
            scores = sorted(((float(sig @ thumb), odd) for odd, thumb in thumbs.items()),
                            reverse=True)
            # mean-abs-diff for the best few, for interpretability
            def mad(odd):
                ref = np.asarray(Image.open(THUMBS / f'BG_{odd:03}.png').convert('RGB')
                                 .crop((0, 11, 160, 81)), dtype=np.int16)
                return float(np.abs(crop.astype(np.int16) - ref).mean())
            best = scores[:3]
            print(f'BG {index}: best scores ' +
                  ', '.join(f'{odd}({s:.3f})' % () for s, odd in best) +
                  f'  mad best={mad(best[0][1]):.2f} next={mad(best[1][1]):.2f}' +
                  f'  expected={index + 1} ' +
                  ('OK' if best[0][1] == index + 1 else 'MISMATCH'))


if __name__ == '__main__':
    main()
